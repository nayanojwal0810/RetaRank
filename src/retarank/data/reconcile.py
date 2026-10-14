"""Transaction reconciliation and deduplication analysis module for RetaRank."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from retarank.config import OUTPUTS_DIR, PROCESSED_DATA_DIR, RAW_DATA_DIR
from retarank.data.clean import (
    SOURCE_COLUMNS,
    build_canonical_ledger,
    export_processed_datasets,
    get_deduplicated_ledger,
)

logger = logging.getLogger(__name__)


def generate_duplicate_overlap_report(ledger: pd.DataFrame) -> pd.DataFrame:
    """Analyze within-sheet vs cross-sheet duplication and invoice overlap.

    Parameters
    ----------
    ledger : pd.DataFrame
        Complete canonical raw transaction ledger.

    Returns
    -------
    pd.DataFrame
        Summary table quantifying overlap and duplication metrics.
    """
    sheet_names = list(ledger["sheet_name"].unique())
    s1_name = sheet_names[0] if len(sheet_names) > 0 else "Sheet1"
    s2_name = sheet_names[1] if len(sheet_names) > 1 else "Sheet2"

    df_s1 = ledger[ledger["sheet_name"] == s1_name]
    df_s2 = ledger[ledger["sheet_name"] == s2_name]

    s1_rows = len(df_s1)
    s2_rows = len(df_s2)
    total_rows = len(ledger)

    # Within-sheet duplicates
    dup_s1 = int(df_s1["is_duplicate_within_sheet"].sum())
    dup_s2 = int(df_s2["is_duplicate_within_sheet"].sum())
    sum_within_dups = dup_s1 + dup_s2

    # Across workbook duplicates
    total_dups_across = int(ledger["is_duplicate_across_workbook"].sum())
    cross_sheet_dups = int(ledger["is_cross_sheet_duplicate"].sum())

    # Invoices
    inv_s1 = set(df_s1["parsed_invoice"].dropna().unique())
    inv_s2 = set(df_s2["parsed_invoice"].dropna().unique())
    shared_invoices = inv_s1.intersection(inv_s2)

    # Rows with shared invoices
    s1_shared_inv_rows = int(df_s1["parsed_invoice"].isin(shared_invoices).sum())
    s2_shared_inv_rows = int(df_s2["parsed_invoice"].isin(shared_invoices).sum())

    # Date range for shared invoices
    shared_df = ledger[ledger["parsed_invoice"].isin(shared_invoices)]
    min_shared_date = shared_df["parsed_date"].min().isoformat() if not shared_df.empty else None
    max_shared_date = shared_df["parsed_date"].max().isoformat() if not shared_df.empty else None

    # Check exact row matches across sheets
    # A row in Sheet 2 matching a row in Sheet 1 exactly
    df_s1_dedup = df_s1.drop_duplicates(subset=SOURCE_COLUMNS)
    s2_exact_matches_in_s1 = int(
        df_s2.merge(df_s1_dedup[SOURCE_COLUMNS], on=SOURCE_COLUMNS, how="inner").shape[0]
    )

    records = [
        {"metric": "Sheet 1 Raw Rows", "value": s1_rows, "notes": f"{s1_name}"},
        {"metric": "Sheet 2 Raw Rows", "value": s2_rows, "notes": f"{s2_name}"},
        {"metric": "Combined Raw Rows", "value": total_rows, "notes": "Sum of both sheets"},
        {"metric": "Sheet 1 Within-Sheet Duplicates", "value": dup_s1, "notes": "Exact 8-field matches after first occurrence"},
        {"metric": "Sheet 2 Within-Sheet Duplicates", "value": dup_s2, "notes": "Exact 8-field matches after first occurrence"},
        {"metric": "Sum of Within-Sheet Duplicates", "value": sum_within_dups, "notes": "dup_s1 + dup_s2"},
        {"metric": "Shared Distinct Invoices Across Sheets", "value": len(shared_invoices), "notes": "Invoices present in both sheets"},
        {"metric": "Sheet 1 Rows with Shared Invoices", "value": s1_shared_inv_rows, "notes": "Rows in Sheet 1 matching shared invoice IDs"},
        {"metric": "Sheet 2 Rows with Shared Invoices", "value": s2_shared_inv_rows, "notes": "Rows in Sheet 2 matching shared invoice IDs"},
        {"metric": "Shared Invoices Earliest Date", "value": min_shared_date, "notes": "Beginning of overlap window (2010-12-01)"},
        {"metric": "Shared Invoices Latest Date", "value": max_shared_date, "notes": "End of overlap window (2010-12-09)"},
        {"metric": "Sheet 2 Rows Exactly Matching Sheet 1 Rows", "value": s2_exact_matches_in_s1, "notes": "Identical 8-field rows copied from Sheet 1 into Sheet 2"},
        {"metric": "Cross-Sheet Additional Duplicates", "value": cross_sheet_dups, "notes": "Duplicates across workbook not captured by within-sheet checks"},
        {"metric": "Total Duplicates Across Concatenated Workbook", "value": total_dups_across, "notes": "Specification B filter count (sum_within + cross_sheet)"},
        {"metric": "Specification B Deduplicated Rows", "value": total_rows - total_dups_across, "notes": "Primary clean transaction layer"},
    ]

    return pd.DataFrame(records)


def generate_deduplication_sensitivity_report(ledger: pd.DataFrame) -> pd.DataFrame:
    """Compare Specification A (retain all) vs Specification B (deduplicated primary).

    Parameters
    ----------
    ledger : pd.DataFrame
        Complete canonical raw transaction ledger.

    Returns
    -------
    pd.DataFrame
        Comparative metrics table for sensitivity evaluation.
    """
    spec_a = get_deduplicated_ledger(ledger, specification="A")
    spec_b = get_deduplicated_ledger(ledger, specification="B")

    def profile_spec(df: pd.DataFrame, label: str) -> dict[str, Any]:
        pos_lines = df[(df["parsed_quantity"] > 0) & (df["parsed_price"] > 0)]
        neg_lines = df[df["parsed_quantity"] < 0]
        id_cust_lines = df[df["has_customer_id"]]
        anon_lines = df[~df["has_customer_id"]]

        valid_purchase_lines = df[df["is_valid_merchandise_purchase"]]
        valid_return_lines = df[df["is_valid_customer_return"]]

        # Distinct customer-invoice purchase events
        # In Online Retail II, every invoice is tied to at most 1 customer (0 multi-customer invoices).
        # We explicitly calculate distinct (customer_id, invoice) pairs to guarantee exact definition adherence.
        cust_inv_purchase_events = int(
            valid_purchase_lines.groupby(["parsed_customer_id", "parsed_invoice"]).ngroups
        ) if not valid_purchase_lines.empty else 0

        # Storewide commercial sales invoices (positive quantity, positive price, non-cancellation)
        comm_invoices = int(
            df[(df["parsed_quantity"] > 0) & (df["parsed_price"] > 0) & (~df["is_cancellation"])]["parsed_invoice"]
            .dropna()
            .nunique()
        )

        return {
            "specification": label,
            "row_count": len(df),
            "signed_line_amount_sum": round(float(df["raw_line_amount"].sum()), 2),
            "positive_lines_count": len(pos_lines),
            "positive_lines_sum": round(float(pos_lines["raw_line_amount"].sum()), 2),
            "negative_lines_count": len(neg_lines),
            "negative_lines_sum": round(float(neg_lines["raw_line_amount"].sum()), 2),
            "identified_customer_sum": round(float(id_cust_lines["raw_line_amount"].sum()), 2),
            "anonymous_sum": round(float(anon_lines["raw_line_amount"].sum()), 2),
            "distinct_customers": int(df["parsed_customer_id"].dropna().nunique()),
            "distinct_invoices": int(df["parsed_invoice"].dropna().nunique()),
            "commercial_positive_invoices": comm_invoices,
            "valid_merchandise_purchase_lines": len(valid_purchase_lines),
            "distinct_invoices_with_valid_merchandise": int(valid_purchase_lines["parsed_invoice"].dropna().nunique()),
            "customer_invoice_purchase_events": cust_inv_purchase_events,
            "valid_purchase_customers": int(valid_purchase_lines["parsed_customer_id"].dropna().nunique()),
            "valid_customer_return_lines": len(valid_return_lines),
            "valid_customer_return_events": int(valid_return_lines["parsed_invoice"].dropna().nunique()),
        }

    res_a = profile_spec(spec_a, "Specification A (Retain all rows / duplicates)")
    res_b = profile_spec(spec_b, "Specification B (Deduplicated primary)")

    diff = {
        "specification": "Difference (Spec A - Spec B)",
        "row_count": res_a["row_count"] - res_b["row_count"],
        "signed_line_amount_sum": round(res_a["signed_line_amount_sum"] - res_b["signed_line_amount_sum"], 2),
        "positive_lines_count": res_a["positive_lines_count"] - res_b["positive_lines_count"],
        "positive_lines_sum": round(res_a["positive_lines_sum"] - res_b["positive_lines_sum"], 2),
        "negative_lines_count": res_a["negative_lines_count"] - res_b["negative_lines_count"],
        "negative_lines_sum": round(res_a["negative_lines_sum"] - res_b["negative_lines_sum"], 2),
        "identified_customer_sum": round(res_a["identified_customer_sum"] - res_b["identified_customer_sum"], 2),
        "anonymous_sum": round(res_a["anonymous_sum"] - res_b["anonymous_sum"], 2),
        "distinct_customers": res_a["distinct_customers"] - res_b["distinct_customers"],
        "distinct_invoices": res_a["distinct_invoices"] - res_b["distinct_invoices"],
        "commercial_positive_invoices": res_a["commercial_positive_invoices"] - res_b["commercial_positive_invoices"],
        "valid_merchandise_purchase_lines": res_a["valid_merchandise_purchase_lines"] - res_b["valid_merchandise_purchase_lines"],
        "distinct_invoices_with_valid_merchandise": res_a["distinct_invoices_with_valid_merchandise"] - res_b["distinct_invoices_with_valid_merchandise"],
        "customer_invoice_purchase_events": res_a["customer_invoice_purchase_events"] - res_b["customer_invoice_purchase_events"],
        "valid_purchase_customers": res_a["valid_purchase_customers"] - res_b["valid_purchase_customers"],
        "valid_customer_return_lines": res_a["valid_customer_return_lines"] - res_b["valid_customer_return_lines"],
        "valid_customer_return_events": res_a["valid_customer_return_events"] - res_b["valid_customer_return_events"],
    }

    return pd.DataFrame([res_a, res_b, diff])


def generate_transaction_classification_report(
    ledger: pd.DataFrame,
    specification_label: str | None = None,
) -> pd.DataFrame:
    """Produce exhaustive mutually exclusive transaction classification profile.

    Parameters
    ----------
    ledger : pd.DataFrame
        Canonical raw transaction ledger.
    specification_label : str | None, optional
        Label indicating transaction specification (e.g. Specification A or B).

    Returns
    -------
    pd.DataFrame
        Classification breakdown table with counts, amounts, and category descriptions.
    """
    category_descriptions = {
        "PURCHASE_IDENTIFIED_MERCHANDISE": "Standard merchandise purchase with identified customer (eligible for CRM features)",
        "PURCHASE_IDENTIFIED_ADMIN_SERVICE": "Administrative or service fee on identified customer invoice (e.g. POST, M)",
        "PURCHASE_ANONYMOUS_MERCHANDISE": "Merchandise purchase without customer identifier (guest checkout/store sales)",
        "PURCHASE_ANONYMOUS_ADMIN_SERVICE": "Administrative or service fee on anonymous invoice (e.g. DOT postage, Amazon fee)",
        "CANCELLATION_RETURN_IDENTIFIED": "Cancellation/return transaction on identified customer account",
        "CANCELLATION_RETURN_ANONYMOUS": "Cancellation/return transaction on anonymous invoice",
        "INVENTORY_ADJUSTMENT_ZERO_PRICE": "Internal inventory stock correction, damages, or loss (Price = 0, no customer ID)",
        "UNPREFIXED_NEGATIVE_PRICED": "Rare negative quantity with positive price but lacking cancellation 'C' prefix",
        "BAD_DEBT_NEGATIVE_PRICE": "Accounting bad debt balance adjustment (StockCode B, Price < 0)",
        "SAMPLE_GIFT_ZERO_PRICE": "Promotional gift, zero-price sample, or administrative stock addition",
        "CANCELLATION_POSITIVE_QTY": "Cancellation-prefixed invoice with positive quantity (correction entry)",
        "ZERO_QUANTITY_LINE": "Zero quantity transaction line",
        "OTHER_ANOMALY": "Unclassified transaction anomaly",
    }

    records = []
    total_rows = len(ledger)

    grouped = ledger.groupby("classification_category", dropna=False)
    for cat_name, group in grouped:
        count = len(group)
        pct = round(count / total_rows * 100.0, 4) if total_rows > 0 else 0.0
        qty_sum = int(group["parsed_quantity"].sum())
        line_sum = round(float(group["raw_line_amount"].sum()), 2)
        pos_p_count = int((group["parsed_price"] > 0).sum())
        zero_p_count = int((group["parsed_price"] == 0).sum())
        neg_p_count = int((group["parsed_price"] < 0).sum())
        has_cust_count = int(group["has_customer_id"].sum())
        missing_cust_count = int((~group["has_customer_id"]).sum())
        valid_purch_count = int(group["is_valid_merchandise_purchase"].sum())
        valid_ret_count = int(group["is_valid_customer_return"].sum())
        desc = category_descriptions.get(str(cat_name), "Classification category")

        records.append({
            "classification_category": str(cat_name),
            "description": desc,
            "row_count": count,
            "row_pct": pct,
            "total_quantity": qty_sum,
            "signed_line_amount_sum": line_sum,
            "positive_price_rows": pos_p_count,
            "zero_price_rows": zero_p_count,
            "negative_price_rows": neg_p_count,
            "identified_customer_rows": has_cust_count,
            "anonymous_rows": missing_cust_count,
            "valid_merchandise_purchase_rows": valid_purch_count,
            "valid_customer_return_rows": valid_ret_count,
        })

    df_out = pd.DataFrame(records).sort_values("row_count", ascending=False).reset_index(drop=True)
    if specification_label is not None:
        df_out.insert(0, "specification", specification_label)

    # Automated assertions: category row counts and signed sums must reconcile exactly
    assert df_out["row_count"].sum() == total_rows, (
        f"Classification row count ({df_out['row_count'].sum()}) does not match ledger rows ({total_rows})"
    )
    raw_sum = round(float(ledger["raw_line_amount"].sum()), 2)
    cat_sum = round(float(df_out["signed_line_amount_sum"].sum()), 2)
    assert np.isclose(cat_sum, raw_sum, atol=1e-2), (
        f"Classification signed amount ({cat_sum}) does not match ledger line amount ({raw_sum})"
    )

    # Automated assertion: every category must belong to recognized taxonomy
    unknown_cats = set(df_out["classification_category"]) - set(category_descriptions.keys())
    assert not unknown_cats, f"Unrecognized classification categories detected: {unknown_cats}"

    return df_out


def generate_monetary_reconciliation_report(
    ledger: pd.DataFrame,
    specification_label: str | None = None,
) -> pd.DataFrame:
    """Prove mathematical equality of financial arithmetic across independent partitions.

    Parameters
    ----------
    ledger : pd.DataFrame
        Canonical raw transaction ledger.
    specification_label : str | None, optional
        Label indicating transaction specification (e.g. Specification A or B).

    Returns
    -------
    pd.DataFrame
        Reconciliation table proving zero residual across all partitions.
    """
    total_raw_amount = round(float(ledger["raw_line_amount"].sum()), 2)
    total_rows = len(ledger)

    # Partition 1: Quantity Sign x Price Sign
    pos_q_pos_p = round(float(ledger[(ledger["parsed_quantity"] > 0) & (ledger["parsed_price"] > 0)]["raw_line_amount"].sum()), 2)
    neg_q_pos_p = round(float(ledger[(ledger["parsed_quantity"] < 0) & (ledger["parsed_price"] > 0)]["raw_line_amount"].sum()), 2)
    zero_p = round(float(ledger[ledger["parsed_price"] == 0]["raw_line_amount"].sum()), 2)
    neg_p = round(float(ledger[ledger["parsed_price"] < 0]["raw_line_amount"].sum()), 2)
    zero_q_pos_p = round(float(ledger[(ledger["parsed_quantity"] == 0) & (ledger["parsed_price"] > 0)]["raw_line_amount"].sum()), 2)
    p1_sum = round(pos_q_pos_p + neg_q_pos_p + zero_p + neg_p + zero_q_pos_p, 2)
    p1_diff = round(p1_sum - total_raw_amount, 2)

    # Partition 2: Customer Identity
    id_cust_amount = round(float(ledger[ledger["has_customer_id"]]["raw_line_amount"].sum()), 2)
    anon_cust_amount = round(float(ledger[~ledger["has_customer_id"]]["raw_line_amount"].sum()), 2)
    p2_sum = round(id_cust_amount + anon_cust_amount, 2)
    p2_diff = round(p2_sum - total_raw_amount, 2)

    # Partition 3: Cancellation Prefix
    c_amount = round(float(ledger[ledger["is_cancellation"]]["raw_line_amount"].sum()), 2)
    non_c_amount = round(float(ledger[~ledger["is_cancellation"]]["raw_line_amount"].sum()), 2)
    p3_sum = round(c_amount + non_c_amount, 2)
    p3_diff = round(p3_sum - total_raw_amount, 2)

    # Partition 4: Worksheets
    sheets = list(ledger["sheet_name"].unique())
    s1_raw = float(ledger[ledger["sheet_name"] == sheets[0]]["raw_line_amount"].sum()) if len(sheets) > 0 else 0.0
    s2_raw = float(ledger[ledger["sheet_name"] == sheets[1]]["raw_line_amount"].sum()) if len(sheets) > 1 else 0.0
    p4_sum = round(s1_raw + s2_raw, 2)
    s1_amt = round(s1_raw, 2)
    s2_amt = round(p4_sum - s1_amt, 2)
    p4_diff = round(p4_sum - total_raw_amount, 2)

    # Partition 5: Classification Categories
    cat_sum = round(float(ledger.groupby("classification_category", dropna=False)["raw_line_amount"].sum().sum()), 2)
    p5_diff = round(cat_sum - total_raw_amount, 2)

    rows = [
        {
            "partition_name": "Target: Total Raw Line Amount",
            "component": f"All Rows ({total_rows:,})",
            "amount": total_raw_amount,
            "reconciled_sum": total_raw_amount,
            "residual_diff": 0.00,
            "status": "EXACT",
        },
        {
            "partition_name": "Partition 1: Qty Sign x Price Sign",
            "component": "Positive Qty & Positive Price",
            "amount": pos_q_pos_p,
            "reconciled_sum": p1_sum,
            "residual_diff": p1_diff,
            "status": "EXACT" if p1_diff == 0.0 else "UNRECONCILED",
        },
        {
            "partition_name": "Partition 1: Qty Sign x Price Sign",
            "component": "Negative Qty & Positive Price",
            "amount": neg_q_pos_p,
            "reconciled_sum": p1_sum,
            "residual_diff": p1_diff,
            "status": "EXACT" if p1_diff == 0.0 else "UNRECONCILED",
        },
        {
            "partition_name": "Partition 1: Qty Sign x Price Sign",
            "component": "Zero Price Lines (Qty * 0.00 = 0.00)",
            "amount": zero_p,
            "reconciled_sum": p1_sum,
            "residual_diff": p1_diff,
            "status": "EXACT" if p1_diff == 0.0 else "UNRECONCILED",
        },
        {
            "partition_name": "Partition 1: Qty Sign x Price Sign",
            "component": "Negative Price Lines (Bad debt adjustments)",
            "amount": neg_p,
            "reconciled_sum": p1_sum,
            "residual_diff": p1_diff,
            "status": "EXACT" if p1_diff == 0.0 else "UNRECONCILED",
        },
        {
            "partition_name": "Partition 2: Customer Identity",
            "component": "Identified Customer Lines",
            "amount": id_cust_amount,
            "reconciled_sum": p2_sum,
            "residual_diff": p2_diff,
            "status": "EXACT" if p2_diff == 0.0 else "UNRECONCILED",
        },
        {
            "partition_name": "Partition 2: Customer Identity",
            "component": "Anonymous / Missing Customer Lines",
            "amount": anon_cust_amount,
            "reconciled_sum": p2_sum,
            "residual_diff": p2_diff,
            "status": "EXACT" if p2_diff == 0.0 else "UNRECONCILED",
        },
        {
            "partition_name": "Partition 3: Cancellation Invoice Prefix",
            "component": "Invoices with 'C' Prefix (Cancellations)",
            "amount": c_amount,
            "reconciled_sum": p3_sum,
            "residual_diff": p3_diff,
            "status": "EXACT" if p3_diff == 0.0 else "UNRECONCILED",
        },
        {
            "partition_name": "Partition 3: Cancellation Invoice Prefix",
            "component": "Invoices without 'C' Prefix (Normal orders & adjustments)",
            "amount": non_c_amount,
            "reconciled_sum": p3_sum,
            "residual_diff": p3_diff,
            "status": "EXACT" if p3_diff == 0.0 else "UNRECONCILED",
        },
        {
            "partition_name": "Partition 4: Worksheets",
            "component": f"{sheets[0]}" if len(sheets) > 0 else "Sheet 1",
            "amount": s1_amt,
            "reconciled_sum": p4_sum,
            "residual_diff": p4_diff,
            "status": "EXACT" if p4_diff == 0.0 else "UNRECONCILED",
        },
        {
            "partition_name": "Partition 4: Worksheets",
            "component": f"{sheets[1]}" if len(sheets) > 1 else "Sheet 2",
            "amount": s2_amt,
            "reconciled_sum": p4_sum,
            "residual_diff": p4_diff,
            "status": "EXACT" if p4_diff == 0.0 else "UNRECONCILED",
        },
        {
            "partition_name": "Partition 5: Mutually Exclusive Classification Categories",
            "component": "Sum of All 12 Mutually Exclusive Categories",
            "amount": cat_sum,
            "reconciled_sum": cat_sum,
            "residual_diff": p5_diff,
            "status": "EXACT" if p5_diff == 0.0 else "UNRECONCILED",
        },
    ]

    df_out = pd.DataFrame(rows)
    if specification_label is not None:
        df_out.insert(0, "specification", specification_label)

    # Automated assertions: zero residual across all partitions
    unreconciled = df_out[df_out["residual_diff"] != 0.0]
    assert unreconciled.empty, (
        f"Unreconciled partitions detected:\n{unreconciled[['partition_name', 'component', 'residual_diff']]}"
    )

    return df_out


def run_reconciliation_pipeline(
    input_path: Path | str | None = None,
    output_dir: Path | str | None = None,
    data_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Execute complete Phase 2A transaction reconciliation pipeline.

    Parameters
    ----------
    input_path : Path | str | None
        Path to source workbook. Defaults to `data/raw/online_retail_II.xlsx`.
    output_dir : Path | str | None
        Directory for metrics CSV outputs. Defaults to `outputs/metrics`.
    data_dir : Path | str | None
        Directory for processed Parquet datasets. Defaults to `data/processed`.

    Returns
    -------
    dict[str, Any]
        Dictionary of reconciliation results and file paths.
    """
    logger.info("Building canonical raw transaction ledger...")
    ledger = build_canonical_ledger(input_path=input_path)

    # Generate Parquet datasets
    logger.info("Exporting processed transaction datasets (Spec A and Spec B)...")
    parquet_paths = export_processed_datasets(ledger, output_dir=data_dir)

    # Determine metrics output directory
    metrics_path = Path(output_dir).resolve() if output_dir is not None else OUTPUTS_DIR / "metrics"
    metrics_path.mkdir(parents=True, exist_ok=True)

    # Generate Reports
    logger.info("Generating duplicate and overlap report...")
    dup_overlap_df = generate_duplicate_overlap_report(ledger)
    dup_overlap_file = metrics_path / "duplicate_overlap.csv"
    dup_overlap_df.to_csv(dup_overlap_file, index=False)

    logger.info("Generating deduplication sensitivity report...")
    dedup_sens_df = generate_deduplication_sensitivity_report(ledger)
    dedup_sens_file = metrics_path / "deduplication_sensitivity.csv"
    dedup_sens_df.to_csv(dedup_sens_file, index=False)

    logger.info("Generating transaction classification report (Spec A and Spec B)...")
    spec_a = ledger
    spec_b = get_deduplicated_ledger(ledger, specification="B")

    trans_class_a = generate_transaction_classification_report(
        spec_a, specification_label="Specification A (Retained duplicates)"
    )
    trans_class_b = generate_transaction_classification_report(
        spec_b, specification_label="Specification B (Primary deduplicated)"
    )
    trans_class_df = pd.concat([trans_class_a, trans_class_b], ignore_index=True)
    trans_class_file = metrics_path / "transaction_classification.csv"
    trans_class_df.to_csv(trans_class_file, index=False)

    logger.info("Generating monetary reconciliation report (Spec A and Spec B)...")
    recon_a = generate_monetary_reconciliation_report(
        spec_a, specification_label="Specification A (Retained duplicates)"
    )
    recon_b = generate_monetary_reconciliation_report(
        spec_b, specification_label="Specification B (Primary deduplicated)"
    )
    recon_df = pd.concat([recon_a, recon_b], ignore_index=True)
    recon_file = metrics_path / "transaction_reconciliation.csv"
    recon_df.to_csv(recon_file, index=False)

    logger.info("Reconciliation pipeline completed successfully.")
    return {
        "ledger_rows": len(ledger),
        "spec_b_rows": len(ledger) - int(ledger["is_duplicate_across_workbook"].sum()),
        "parquet_primary": parquet_paths["transactions_primary"],
        "parquet_with_duplicates": parquet_paths["transactions_with_duplicates"],
        "duplicate_overlap_file": dup_overlap_file,
        "deduplication_sensitivity_file": dedup_sens_file,
        "transaction_classification_file": trans_class_file,
        "transaction_reconciliation_file": recon_file,
    }

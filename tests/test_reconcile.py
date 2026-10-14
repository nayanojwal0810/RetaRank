"""Automated unit tests for Phase 2A transaction reconciliation, classification, and deduplication."""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from retarank.data.clean import (
    ADMIN_STOCK_CODES,
    SOURCE_COLUMNS,
    build_canonical_ledger,
    get_deduplicated_ledger,
)
from retarank.data.reconcile import (
    generate_deduplication_sensitivity_report,
    generate_duplicate_overlap_report,
    generate_monetary_reconciliation_report,
    generate_transaction_classification_report,
)


@pytest.fixture
def synthetic_multi_sheet_ledger() -> pd.DataFrame:
    """Construct synthetic multi-sheet ledger with known overlap and classification characteristics."""
    # Sheet 1: 6 rows
    sheet1_data = [
        # 1. Normal merchandise purchase (Inv 101, Cust 1001, 2 x 10 = 20)
        {"Invoice": "101", "StockCode": "21421", "Description": "Product A", "Quantity": 2, "InvoiceDate": "2010-01-01 10:00:00", "Price": 10.0, "Customer ID": 1001.0, "Country": "UK"},
        # 2. Exact duplicate within Sheet 1 of row 1 (Inv 101, Cust 1001, 2 x 10 = 20)
        {"Invoice": "101", "StockCode": "21421", "Description": "Product A", "Quantity": 2, "InvoiceDate": "2010-01-01 10:00:00", "Price": 10.0, "Customer ID": 1001.0, "Country": "UK"},
        # 3. Postage line on same invoice (Inv 101, POST, 1 x 5 = 5)
        {"Invoice": "101", "StockCode": "POST", "Description": "POSTAGE", "Quantity": 1, "InvoiceDate": "2010-01-01 10:00:00", "Price": 5.0, "Customer ID": 1001.0, "Country": "UK"},
        # 4. Cancellation return (Inv C102, Cust 1001, -1 x 10 = -10)
        {"Invoice": "C102", "StockCode": "21421", "Description": "Product A Return", "Quantity": -1, "InvoiceDate": "2010-01-05 11:00:00", "Price": 10.0, "Customer ID": 1001.0, "Country": "UK"},
        # 5. Inventory adjustment (damaged, Price = 0, no customer ID, -5 x 0 = 0)
        {"Invoice": "103", "StockCode": "84029", "Description": "damages", "Quantity": -5, "InvoiceDate": "2010-01-06 12:00:00", "Price": 0.0, "Customer ID": np.nan, "Country": "UK"},
        # 6. Shared invoice row that ALSO appears in Sheet 2 (Inv 104, Dec overlap, 4 x 2.50 = 10)
        {"Invoice": "104", "StockCode": "22086", "Description": "Paper Cup", "Quantity": 4, "InvoiceDate": "2010-12-05 14:00:00", "Price": 2.50, "Customer ID": 2002.0, "Country": "UK"},
    ]

    # Sheet 2: 4 rows
    sheet2_data = [
        # 7. Exact cross-sheet copy of row 6 from Sheet 1 (Inv 104, 4 x 2.50 = 10)
        {"Invoice": "104", "StockCode": "22086", "Description": "Paper Cup", "Quantity": 4, "InvoiceDate": "2010-12-05 14:00:00", "Price": 2.50, "Customer ID": 2002.0, "Country": "UK"},
        # 8. Same shared invoice (Inv 104), but DIFFERENT line item (StockCode 22087, 1 x 8 = 8)
        {"Invoice": "104", "StockCode": "22087", "Description": "Paper Plate", "Quantity": 1, "InvoiceDate": "2010-12-05 14:00:00", "Price": 8.0, "Customer ID": 2002.0, "Country": "UK"},
        # 9. Anonymous merchandise purchase (Inv 105, 3 x 4 = 12)
        {"Invoice": "105", "StockCode": "71053", "Description": "White Metal Lantern", "Quantity": 3, "InvoiceDate": "2011-01-10 15:00:00", "Price": 4.0, "Customer ID": np.nan, "Country": "France"},
        # 10. Bad debt adjustment (Inv 106, StockCode B, Price < 0, 1 x -50 = -50)
        {"Invoice": "106", "StockCode": "B", "Description": "Adjust bad debt", "Quantity": 1, "InvoiceDate": "2011-01-15 16:00:00", "Price": -50.0, "Customer ID": np.nan, "Country": "UK"},
    ]

    df1 = pd.DataFrame(sheet1_data)
    df1["sheet_name"] = "Year 2009-2010"
    df1["excel_row"] = np.arange(2, len(df1) + 2)
    df1["source_row_id"] = "Y0910:" + df1["excel_row"].astype(str)
    df1["is_duplicate_within_sheet"] = df1.duplicated(subset=SOURCE_COLUMNS, keep="first")

    df2 = pd.DataFrame(sheet2_data)
    df2["sheet_name"] = "Year 2010-2011"
    df2["excel_row"] = np.arange(2, len(df2) + 2)
    df2["source_row_id"] = "Y1011:" + df2["excel_row"].astype(str)
    df2["is_duplicate_within_sheet"] = df2.duplicated(subset=SOURCE_COLUMNS, keep="first")

    ledger = pd.concat([df1, df2], ignore_index=True)

    # Duplication across workbook
    ledger["is_duplicate_across_workbook"] = ledger.duplicated(subset=SOURCE_COLUMNS, keep="first")
    ledger["is_cross_sheet_duplicate"] = (
        ledger["is_duplicate_across_workbook"] & (~ledger["is_duplicate_within_sheet"])
    )

    # Derived parsed columns
    ledger["parsed_invoice"] = ledger["Invoice"].astype(str).str.strip()
    ledger["parsed_stock_code"] = ledger["StockCode"].astype(str).str.strip()
    ledger["parsed_description"] = ledger["Description"].astype(str).str.strip()
    ledger["parsed_quantity"] = pd.to_numeric(ledger["Quantity"]).astype(np.int64)
    ledger["parsed_date"] = pd.to_datetime(ledger["InvoiceDate"])
    ledger["parsed_price"] = pd.to_numeric(ledger["Price"]).astype(np.float64)
    ledger["parsed_customer_id"] = pd.to_numeric(ledger["Customer ID"])
    ledger["parsed_country"] = ledger["Country"].astype(str).str.strip()
    ledger["raw_line_amount"] = ledger["parsed_quantity"] * ledger["parsed_price"]

    # Flags
    ledger["is_cancellation"] = ledger["parsed_invoice"].str.upper().str.startswith("C")
    ledger["has_customer_id"] = ledger["parsed_customer_id"].notna()
    ledger["quantity_sign"] = np.where(ledger["parsed_quantity"] > 0, "positive", np.where(ledger["parsed_quantity"] < 0, "negative", "zero"))
    ledger["price_sign"] = np.where(ledger["parsed_price"] > 0, "positive", np.where(ledger["parsed_price"] < 0, "negative", "zero"))
    ledger["is_administrative"] = ledger["parsed_stock_code"].str.upper().isin(ADMIN_STOCK_CODES)

    # Classification
    is_pos_q = ledger["parsed_quantity"] > 0
    is_neg_q = ledger["parsed_quantity"] < 0
    is_zero_q = ledger["parsed_quantity"] == 0
    is_pos_p = ledger["parsed_price"] > 0
    is_neg_p = ledger["parsed_price"] < 0
    is_zero_p = ledger["parsed_price"] == 0
    is_c = ledger["is_cancellation"]
    has_cust = ledger["has_customer_id"]
    is_admin = ledger["is_administrative"]

    conditions = [
        is_pos_q & is_pos_p & (~is_c) & has_cust & (~is_admin),
        is_pos_q & is_pos_p & (~is_c) & has_cust & is_admin,
        is_pos_q & is_pos_p & (~is_c) & (~has_cust) & (~is_admin),
        is_pos_q & is_pos_p & (~is_c) & (~has_cust) & is_admin,
        is_neg_q & is_pos_p & is_c & has_cust,
        is_neg_q & is_pos_p & is_c & (~has_cust),
        is_neg_q & is_zero_p & (~is_c),
        is_neg_q & is_pos_p & (~is_c),
        is_neg_p,
        (~is_neg_q) & is_zero_p,
        is_c & is_pos_q,
        is_zero_q,
    ]
    choices = [
        "PURCHASE_IDENTIFIED_MERCHANDISE",
        "PURCHASE_IDENTIFIED_ADMIN_SERVICE",
        "PURCHASE_ANONYMOUS_MERCHANDISE",
        "PURCHASE_ANONYMOUS_ADMIN_SERVICE",
        "CANCELLATION_RETURN_IDENTIFIED",
        "CANCELLATION_RETURN_ANONYMOUS",
        "INVENTORY_ADJUSTMENT_ZERO_PRICE",
        "UNPREFIXED_NEGATIVE_PRICED",
        "BAD_DEBT_NEGATIVE_PRICE",
        "SAMPLE_GIFT_ZERO_PRICE",
        "CANCELLATION_POSITIVE_QTY",
        "ZERO_QUANTITY_LINE",
    ]
    ledger["classification_category"] = np.select(conditions, choices, default="OTHER_ANOMALY")
    ledger["is_valid_merchandise_purchase"] = is_pos_q & is_pos_p & (~is_c) & has_cust & (~is_admin)
    ledger["is_valid_customer_return"] = is_neg_q & is_pos_p & is_c & has_cust & (~is_admin)

    return ledger


def test_provenance_and_unique_source_row_ids(synthetic_multi_sheet_ledger: pd.DataFrame) -> None:
    ledger = synthetic_multi_sheet_ledger
    assert len(ledger) == 10
    # Every row has unique source_row_id
    assert ledger["source_row_id"].nunique() == 10
    assert set(ledger["sheet_name"].unique()) == {"Year 2009-2010", "Year 2010-2011"}
    # Verify excel row numbers are 1-based data rows (starting at 2)
    assert ledger["excel_row"].min() == 2


def test_cross_sheet_duplicates_versus_shared_invoices(synthetic_multi_sheet_ledger: pd.DataFrame) -> None:
    ledger = synthetic_multi_sheet_ledger
    # Invoice 104 appears in both sheets
    s1_invs = set(ledger[ledger["sheet_name"] == "Year 2009-2010"]["parsed_invoice"])
    s2_invs = set(ledger[ledger["sheet_name"] == "Year 2010-2011"]["parsed_invoice"])
    shared = s1_invs.intersection(s2_invs)
    assert shared == {"104"}

    # In Invoice 104:
    # Row 6 (Paper Cup) is in Sheet 1 and row 7 (Paper Cup) is in Sheet 2 -> EXACT cross-sheet duplicate
    # Row 8 (Paper Plate) is also Invoice 104 in Sheet 2 -> SAME INVOICE, DIFFERENT PRODUCT!
    # Proves the pipeline does not discard row 8 simply because its invoice appears in Sheet 1.
    assert bool(ledger.loc[6, "is_cross_sheet_duplicate"]) is True
    assert bool(ledger.loc[7, "is_cross_sheet_duplicate"]) is False
    assert ledger.loc[7, "parsed_stock_code"] == "22087"


def test_within_sheet_and_across_workbook_deduplication(synthetic_multi_sheet_ledger: pd.DataFrame) -> None:
    ledger = synthetic_multi_sheet_ledger
    # Row 1 is exact duplicate of row 0 within Sheet 1
    assert bool(ledger.loc[1, "is_duplicate_within_sheet"]) is True
    # Row 6 is exact cross-sheet duplicate of row 5
    assert bool(ledger.loc[6, "is_duplicate_within_sheet"]) is False
    assert bool(ledger.loc[6, "is_cross_sheet_duplicate"]) is True
    assert bool(ledger.loc[6, "is_duplicate_across_workbook"]) is True

    # Total duplicates across workbook: 2 (row 1 and row 6)
    assert ledger["is_duplicate_across_workbook"].sum() == 2

    # Specification A: 10 rows
    spec_a = get_deduplicated_ledger(ledger, specification="A")
    assert len(spec_a) == 10

    # Specification B: 8 rows (drops row 1 and row 6)
    spec_b = get_deduplicated_ledger(ledger, specification="B")
    assert len(spec_b) == 8


def test_deduplication_sensitivity_metrics(synthetic_multi_sheet_ledger: pd.DataFrame) -> None:
    ledger = synthetic_multi_sheet_ledger
    sens_df = generate_deduplication_sensitivity_report(ledger)

    assert len(sens_df) == 3
    row_a = sens_df[sens_df["specification"].str.contains("Specification A")].iloc[0]
    row_b = sens_df[sens_df["specification"].str.contains("Specification B")].iloc[0]
    diff = sens_df[sens_df["specification"].str.contains("Difference")].iloc[0]

    assert row_a["row_count"] == 10
    assert row_b["row_count"] == 8
    assert diff["row_count"] == 2

    # Both specifications retain all distinct customers (1001, 2002)
    assert row_a["distinct_customers"] == 2
    assert row_b["distinct_customers"] == 2
    assert diff["distinct_customers"] == 0

    # Both specifications retain all distinct invoices (101, C102, 103, 104, 105, 106)
    assert row_a["distinct_invoices"] == 6
    assert row_b["distinct_invoices"] == 6
    assert diff["distinct_invoices"] == 0


def test_monetary_reconciliation_exact_zero_residual(synthetic_multi_sheet_ledger: pd.DataFrame) -> None:
    ledger = synthetic_multi_sheet_ledger
    recon_df = generate_monetary_reconciliation_report(ledger)

    # Total raw line amount in synthetic dataset:
    # Row 0: 2 * 10 = 20
    # Row 1: 2 * 10 = 20
    # Row 2: 1 * 5 = 5 (POST)
    # Row 3: -1 * 10 = -10 (C102)
    # Row 4: -5 * 0 = 0 (damage)
    # Row 5: 4 * 2.5 = 10 (Cup)
    # Row 6: 4 * 2.5 = 10 (Cup copy)
    # Row 7: 1 * 8 = 8 (Plate)
    # Row 8: 3 * 4 = 12 (Lantern)
    # Row 9: 1 * -50 = -50 (Bad debt)
    # Total sum = 20 + 20 + 5 - 10 + 0 + 10 + 10 + 8 + 12 - 50 = 25.0
    target_row = recon_df[recon_df["partition_name"].str.contains("Target")].iloc[0]
    assert target_row["amount"] == 25.0

    # Every partition row must have status == 'EXACT' and residual_diff == 0.00
    assert (recon_df["status"] == "EXACT").all()
    assert (recon_df["residual_diff"] == 0.00).all()


def test_exhaustive_transaction_classification(synthetic_multi_sheet_ledger: pd.DataFrame) -> None:
    ledger = synthetic_multi_sheet_ledger
    class_df = generate_transaction_classification_report(ledger)

    # Sum of row counts must match 100% of rows (10)
    assert class_df["row_count"].sum() == 10
    # Sum of signed line amounts must equal total raw line amount (25.0)
    assert round(class_df["signed_line_amount_sum"].sum(), 2) == 25.0

    # Verify specific categories present:
    categories = set(class_df["classification_category"])
    assert "PURCHASE_IDENTIFIED_MERCHANDISE" in categories
    assert "PURCHASE_IDENTIFIED_ADMIN_SERVICE" in categories
    assert "CANCELLATION_RETURN_IDENTIFIED" in categories
    assert "INVENTORY_ADJUSTMENT_ZERO_PRICE" in categories
    assert "PURCHASE_ANONYMOUS_MERCHANDISE" in categories
    assert "BAD_DEBT_NEGATIVE_PRICE" in categories


def test_non_destructive_input_behaviour(synthetic_multi_sheet_ledger: pd.DataFrame) -> None:
    ledger = synthetic_multi_sheet_ledger
    original_shape = ledger.shape
    original_copy = ledger.copy(deep=True)

    _ = generate_duplicate_overlap_report(ledger)
    _ = generate_deduplication_sensitivity_report(ledger)
    _ = generate_transaction_classification_report(ledger)
    _ = generate_monetary_reconciliation_report(ledger)

    assert ledger.shape == original_shape
    pd.testing.assert_frame_equal(ledger, original_copy)


@pytest.mark.skipif(
    not Path("data/raw/online_retail_II.xlsx").exists(),
    reason="Actual Online Retail II Excel workbook not present",
)
def test_real_workbook_integration_reconciliation() -> None:
    """Real-data integration check verifying exact zero residual on the actual workbook."""
    from retarank.config import RAW_DATA_DIR
    from retarank.data.clean import build_canonical_ledger
    from retarank.data.reconcile import (
        generate_deduplication_sensitivity_report,
        generate_monetary_reconciliation_report,
    )

    ledger = build_canonical_ledger(RAW_DATA_DIR / "online_retail_II.xlsx")
    assert len(ledger) == 1067371
    assert ledger["source_row_id"].nunique() == 1067371

    # Exact zero residual proof
    recon_df = generate_monetary_reconciliation_report(ledger)
    assert (recon_df["status"] == "EXACT").all()
    assert (recon_df["residual_diff"] == 0.00).all()

    # Deduplication integrity
    sens_df = generate_deduplication_sensitivity_report(ledger)
    diff_row = sens_df[sens_df["specification"].str.contains("Difference")].iloc[0]
    assert diff_row["row_count"] == 34335
    assert diff_row["distinct_customers"] == 0
    assert diff_row["distinct_invoices"] == 0


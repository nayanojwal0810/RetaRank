"""Source data profiling and data-quality audit module for RetaRank."""
from __future__ import annotations

import gc
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import openpyxl
import pandas as pd

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".xlsx", ".xlsm", ".xls"}

COLUMN_ALIASES = {
    "invoice": {"invoice", "invoiceno", "invoice_no", "invoicenumber", "invoicenum", "invoice_id"},
    "stock_code": {"stockcode", "stock_code", "item_code", "product_code"},
    "description": {"description", "desc", "item_description"},
    "quantity": {"quantity", "qty", "units"},
    "invoice_date": {"invoicedate", "invoice_date", "date", "timestamp"},
    "price": {"price", "unitprice", "unit_price", "rate", "unitcost"},
    "customer_id": {"customer id", "customer_id", "customerid", "client_id", "user_id", "customer"},
    "country": {"country", "nation"},
}


def _normalise_column_name(name: object) -> str:
    """Normalise a header so harmless spaces and punctuation do not matter."""
    return re.sub(r"[^a-z0-9]", "", str(name).strip().lower())


def normalize_col_name(col: str) -> str:
    """Alias for backwards-compatibility."""
    return _normalise_column_name(col)


def resolve_columns(columns: list[object] | pd.Index) -> dict[str, str | None]:
    """Map known logical fields to observed workbook column names."""
    normalised = {_normalise_column_name(col): str(col) for col in columns}
    resolved: dict[str, str | None] = {}
    for logical_name, aliases in COLUMN_ALIASES.items():
        norm_aliases = {_normalise_column_name(a) for a in aliases}
        resolved[logical_name] = next(
            (normalised[a] for a in norm_aliases if a in normalised),
            None,
        )
    return resolved


def resolve_column_mapping(columns: list[str]) -> dict[str, str]:
    """Resolve column mapping, raising ValueError if essential columns are missing."""
    resolved = resolve_columns(columns)
    required_roles = ["invoice", "quantity", "invoice_date", "price", "customer_id"]
    missing_required = [r for r in required_roles if resolved.get(r) is None]
    if missing_required:
        raise ValueError(
            f"Could not resolve required columns: {missing_required}. "
            f"Available columns in source: {columns}"
        )
    return {k: str(v) for k, v in resolved.items() if v is not None}


def _series_or_na(frame: pd.DataFrame, column: str | None) -> pd.Series:
    if column is None or column not in frame.columns:
        return pd.Series(np.nan, index=frame.index, dtype="float64")
    return frame[column]


def audit_sheet_missingness(
    df: pd.DataFrame,
    sheet_name: str,
    col_map: dict[str, str],
) -> pd.DataFrame:
    """Compute per-column missingness and distinct counts for a sheet."""
    total_rows = len(df)
    inverse_map = {v: k for k, v in col_map.items()}

    records = []
    for col in df.columns:
        null_count = int(df[col].isna().sum())
        null_pct = float((null_count / total_rows * 100.0) if total_rows > 0 else 0.0)
        distinct_count = int(df[col].nunique(dropna=False))
        dtype_str = str(df[col].dtype)
        standard_role = inverse_map.get(str(col), "unmapped")

        records.append({
            "sheet_name": sheet_name,
            "column_name": str(col),
            "standard_role": standard_role,
            "dtype": dtype_str,
            "total_rows": total_rows,
            "null_count": null_count,
            "null_pct": round(null_pct, 4),
            "distinct_values_count": distinct_count,
        })

    return pd.DataFrame.from_records(records)


def profile_worksheet(
    df: pd.DataFrame,
    sheet_name: str,
    col_map: dict[str, str],
) -> dict[str, Any]:
    """Calculate comprehensive diagnostic metrics for a single worksheet without modifying it."""
    total_rows = len(df)
    total_cols = len(df.columns)

    inv_col = col_map.get("invoice")
    qty_col = col_map.get("quantity")
    date_col = col_map.get("invoice_date")
    price_col = col_map.get("price")
    cust_col = col_map.get("customer_id")

    exact_duplicate_rows = int(df.duplicated(keep="first").sum())

    # Customer ID diagnostics
    cust_series = _series_or_na(df, cust_col)
    missing_customer_ids = int(cust_series.isna().sum())
    missing_customer_id_pct = float(
        (missing_customer_ids / total_rows * 100.0) if total_rows > 0 else 0.0
    )
    distinct_customers = int(cust_series.dropna().nunique())

    # Invoice diagnostics
    inv_series = _series_or_na(df, inv_col)
    distinct_invoices = int(inv_series.dropna().nunique())

    # Cancellation recognition
    inv_str = inv_series.astype(str).str.strip().str.upper()
    is_cancellation = inv_str.str.startswith("C")
    cancellation_rows = int(is_cancellation.sum())
    distinct_cancellation_invoices = int(inv_series[is_cancellation].dropna().nunique())

    # Date parsing diagnostics
    date_series = _series_or_na(df, date_col)
    parsed_dates = pd.to_datetime(date_series, errors="coerce")
    if date_col and date_col in df.columns:
        non_null_raw_dates = int(date_series.notna().sum())
        parsed_valid_dates = int(parsed_dates.notna().sum())
        date_parse_failures = non_null_raw_dates - parsed_valid_dates
        min_date_val = parsed_dates.dropna().min()
        max_date_val = parsed_dates.dropna().max()
        min_invoice_date = min_date_val.isoformat() if pd.notna(min_date_val) else None
        max_invoice_date = max_date_val.isoformat() if pd.notna(max_date_val) else None
    else:
        date_parse_failures = 0
        min_invoice_date = None
        max_invoice_date = None

    # Quantity diagnostics
    qty_numeric = pd.to_numeric(_series_or_na(df, qty_col), errors="coerce").fillna(0)
    positive_quantities = int((qty_numeric > 0).sum())
    negative_quantities = int((qty_numeric < 0).sum())
    zero_quantities = int((qty_numeric == 0).sum())

    # Price diagnostics
    price_numeric = pd.to_numeric(_series_or_na(df, price_col), errors="coerce").fillna(0)
    positive_prices = int((price_numeric > 0).sum())
    negative_prices = int((price_numeric < 0).sum())
    zero_prices = int((price_numeric == 0).sum())
    nonpositive_prices = negative_prices + zero_prices

    # Overlap diagnostics
    negative_qty_and_cancellation_invoice = int(((qty_numeric < 0) & is_cancellation).sum())
    negative_qty_and_not_cancellation_invoice = int(((qty_numeric < 0) & (~is_cancellation)).sum())
    positive_qty_and_cancellation_invoice = int(((qty_numeric > 0) & is_cancellation).sum())
    positive_qty_and_not_cancellation_invoice = int(((qty_numeric > 0) & (~is_cancellation)).sum())

    # Potential positive purchase lines
    is_positive_purchase = (qty_numeric > 0) & (price_numeric > 0)
    candidate_positive_purchase = is_positive_purchase & (~is_cancellation)
    potential_positive_purchase_lines = int(is_positive_purchase.sum())
    potential_positive_purchase_identified_cust = int(
        (is_positive_purchase & cust_series.notna()).sum()
    )
    potential_positive_purchase_missing_cust = int(
        (is_positive_purchase & cust_series.isna()).sum()
    )

    # Arithmetic totals (Exploratory diagnostics ONLY)
    raw_line_value = qty_numeric * price_numeric
    preliminary_arithmetic_raw_line_sum = float(round(raw_line_value.sum(), 2))
    preliminary_arithmetic_positive_lines_sum = float(
        round(raw_line_value[is_positive_purchase].sum(), 2)
    )
    preliminary_arithmetic_negative_lines_sum = float(
        round(raw_line_value[qty_numeric < 0].sum(), 2)
    )
    preliminary_arithmetic_identified_cust_sum = float(
        round(raw_line_value[cust_series.notna()].sum(), 2)
    )
    preliminary_arithmetic_missing_cust_sum = float(
        round(raw_line_value[cust_series.isna()].sum(), 2)
    )
    candidate_positive_purchase_value_sum = float(
        round(raw_line_value[candidate_positive_purchase].sum(), 2)
    )

    return {
        "sheet": sheet_name,
        "sheet_name": sheet_name,
        "row_count": total_rows,
        "column_count": total_cols,
        "column_names": [str(c) for c in df.columns],
        "min_invoice_date": min_invoice_date,
        "max_invoice_date": max_invoice_date,
        "date_parse_failures": date_parse_failures,
        "missing_or_unparseable_invoice_dates": date_parse_failures,
        "distinct_customers": distinct_customers,
        "unique_customer_ids": distinct_customers,
        "distinct_invoices": distinct_invoices,
        "unique_invoices": distinct_invoices,
        "exact_duplicate_rows": exact_duplicate_rows,
        "exact_duplicate_rows_after_first": exact_duplicate_rows,
        "missing_customer_ids": missing_customer_ids,
        "missing_customer_id_rows": missing_customer_ids,
        "missing_customer_id_pct": round(missing_customer_id_pct, 4),
        "cancellation_invoices": cancellation_rows,
        "cancellation_prefix_invoice_rows": cancellation_rows,
        "distinct_cancellation_invoices": distinct_cancellation_invoices,
        "positive_quantities": positive_quantities,
        "positive_quantity_rows": positive_quantities,
        "negative_quantities": negative_quantities,
        "negative_quantity_rows": negative_quantities,
        "zero_quantities": zero_quantities,
        "zero_quantity_rows": zero_quantities,
        "positive_prices": positive_prices,
        "negative_prices": negative_prices,
        "zero_prices": zero_prices,
        "nonpositive_prices": nonpositive_prices,
        "nonpositive_price_rows": nonpositive_prices,
        "negative_qty_and_cancellation_invoice": negative_qty_and_cancellation_invoice,
        "negative_quantity_and_cancellation_prefix_overlap_rows": negative_qty_and_cancellation_invoice,
        "negative_qty_and_not_cancellation_invoice": negative_qty_and_not_cancellation_invoice,
        "positive_qty_and_cancellation_invoice": positive_qty_and_cancellation_invoice,
        "positive_qty_and_not_cancellation_invoice": positive_qty_and_not_cancellation_invoice,
        "potential_positive_purchase_lines": potential_positive_purchase_lines,
        "candidate_positive_purchase_rows": int(candidate_positive_purchase.sum()),
        "potential_positive_purchase_identified_cust": potential_positive_purchase_identified_cust,
        "potential_positive_purchase_missing_cust": potential_positive_purchase_missing_cust,
        "preliminary_arithmetic_raw_line_sum": preliminary_arithmetic_raw_line_sum,
        "raw_quantity_times_price_sum_all_rows": preliminary_arithmetic_raw_line_sum,
        "preliminary_arithmetic_positive_lines_sum": preliminary_arithmetic_positive_lines_sum,
        "preliminary_arithmetic_negative_lines_sum": preliminary_arithmetic_negative_lines_sum,
        "preliminary_arithmetic_identified_cust_sum": preliminary_arithmetic_identified_cust_sum,
        "raw_quantity_times_price_sum_identified_customers": preliminary_arithmetic_identified_cust_sum,
        "preliminary_arithmetic_missing_cust_sum": preliminary_arithmetic_missing_cust_sum,
        "raw_quantity_times_price_sum_missing_customer_id": preliminary_arithmetic_missing_cust_sum,
        "candidate_positive_purchase_value_sum": candidate_positive_purchase_value_sum,
        "resolved_columns": col_map,
    }


def profile_sheet(frame: pd.DataFrame, sheet_name: str) -> tuple[dict[str, Any], pd.DataFrame]:
    """Compatibility interface matching initial RetaRank specification."""
    cols_map = resolve_columns(frame.columns)
    valid_map = {k: v for k, v in cols_map.items() if v is not None}
    metrics = profile_worksheet(frame, sheet_name, valid_map)
    row_count = len(frame)
    missing_rows = []
    for column in frame.columns:
        missing_count = int(frame[column].isna().sum())
        missing_rows.append(
            {
                "sheet": sheet_name,
                "column": str(column),
                "dtype_as_read": str(frame[column].dtype),
                "missing_count": missing_count,
                "missing_pct": (100.0 * missing_count / row_count) if row_count else 0.0,
                "distinct_non_null_values": int(frame[column].nunique(dropna=True)),
            }
        )
    return metrics, pd.DataFrame(missing_rows)


def audit_workbook_dataframes(
    sheets_dict: Mapping[str, pd.DataFrame],
    source_name: str = "in_memory_data",
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    """Audit multiple sheet DataFrames and compute profiles, missingness, and combined metrics."""
    sheet_profiles: list[dict[str, Any]] = []
    missingness_dfs: list[pd.DataFrame] = []

    global_customer_ids: set[Any] = set()
    global_invoice_ids: set[Any] = set()
    global_cancellation_invoices: set[Any] = set()

    schema_consistency = {
        "sheets_have_identical_columns": True,
        "sheet_columns": {},
        "unexpected_columns": [],
    }

    first_columns: list[str] | None = None

    for sheet_name, df in sheets_dict.items():
        col_list = list(df.columns)
        schema_consistency["sheet_columns"][sheet_name] = col_list
        if first_columns is None:
            first_columns = col_list
        elif col_list != first_columns:
            schema_consistency["sheets_have_identical_columns"] = False

        col_map = resolve_column_mapping(col_list)

        miss_df = audit_sheet_missingness(df, sheet_name, col_map)
        missingness_dfs.append(miss_df)

        profile = profile_worksheet(df, sheet_name, col_map)
        sheet_profiles.append(profile)

        cust_col = col_map["customer_id"]
        inv_col = col_map["invoice"]
        global_customer_ids.update(df[cust_col].dropna().unique())
        global_invoice_ids.update(df[inv_col].dropna().unique())

        inv_str = df[inv_col].astype(str).str.strip().str.upper()
        cancels = df[inv_col][inv_str.str.startswith("C")].dropna().unique()
        global_cancellation_invoices.update(cancels)

    combined_missingness_df = (
        pd.concat(missingness_dfs, ignore_index=True)
        if missingness_dfs
        else pd.DataFrame()
    )

    total_rows = sum(p["row_count"] for p in sheet_profiles)
    total_exact_duplicates = sum(p["exact_duplicate_rows"] for p in sheet_profiles)
    total_cancellation_rows = sum(p["cancellation_invoices"] for p in sheet_profiles)
    total_missing_cust = sum(p["missing_customer_ids"] for p in sheet_profiles)
    missing_cust_pct = (
        round(total_missing_cust / total_rows * 100.0, 4) if total_rows > 0 else 0.0
    )

    min_dates = [p["min_invoice_date"] for p in sheet_profiles if p["min_invoice_date"]]
    max_dates = [p["max_invoice_date"] for p in sheet_profiles if p["max_invoice_date"]]
    overall_min_date = min(min_dates) if min_dates else None
    overall_max_date = max(max_dates) if max_dates else None

    total_date_parse_failures = sum(p["date_parse_failures"] for p in sheet_profiles)
    total_positive_qty = sum(p["positive_quantities"] for p in sheet_profiles)
    total_negative_qty = sum(p["negative_quantities"] for p in sheet_profiles)
    total_zero_qty = sum(p["zero_quantities"] for p in sheet_profiles)
    total_positive_prices = sum(p["positive_prices"] for p in sheet_profiles)
    total_negative_prices = sum(p["negative_prices"] for p in sheet_profiles)
    total_zero_prices = sum(p["zero_prices"] for p in sheet_profiles)
    total_nonpositive_prices = sum(p["nonpositive_prices"] for p in sheet_profiles)

    total_neg_qty_cancellation = sum(
        p["negative_qty_and_cancellation_invoice"] for p in sheet_profiles
    )
    total_neg_qty_not_cancellation = sum(
        p["negative_qty_and_not_cancellation_invoice"] for p in sheet_profiles
    )
    total_pos_qty_cancellation = sum(
        p["positive_qty_and_cancellation_invoice"] for p in sheet_profiles
    )
    total_pos_qty_not_cancellation = sum(
        p["positive_qty_and_not_cancellation_invoice"] for p in sheet_profiles
    )

    total_potential_purchase_lines = sum(
        p["potential_positive_purchase_lines"] for p in sheet_profiles
    )
    total_potential_purchase_identified_cust = sum(
        p["potential_positive_purchase_identified_cust"] for p in sheet_profiles
    )
    total_potential_purchase_missing_cust = sum(
        p["potential_positive_purchase_missing_cust"] for p in sheet_profiles
    )

    sum_raw_line = round(sum(p["preliminary_arithmetic_raw_line_sum"] for p in sheet_profiles), 2)
    sum_pos_lines = round(sum(p["preliminary_arithmetic_positive_lines_sum"] for p in sheet_profiles), 2)
    sum_neg_lines = round(sum(p["preliminary_arithmetic_negative_lines_sum"] for p in sheet_profiles), 2)
    sum_id_cust = round(sum(p["preliminary_arithmetic_identified_cust_sum"] for p in sheet_profiles), 2)
    sum_miss_cust = round(sum(p["preliminary_arithmetic_missing_cust_sum"] for p in sheet_profiles), 2)

    combined_profile_row = {
        "sheet": "Combined_All_Sheets",
        "sheet_name": "Combined_All_Sheets",
        "row_count": total_rows,
        "column_count": len(first_columns) if first_columns else 0,
        "column_names": first_columns or [],
        "min_invoice_date": overall_min_date,
        "max_invoice_date": overall_max_date,
        "date_parse_failures": total_date_parse_failures,
        "missing_or_unparseable_invoice_dates": total_date_parse_failures,
        "distinct_customers": len(global_customer_ids),
        "unique_customer_ids": len(global_customer_ids),
        "distinct_invoices": len(global_invoice_ids),
        "unique_invoices": len(global_invoice_ids),
        "exact_duplicate_rows": total_exact_duplicates,
        "exact_duplicate_rows_after_first": total_exact_duplicates,
        "missing_customer_ids": total_missing_cust,
        "missing_customer_id_rows": total_missing_cust,
        "missing_customer_id_pct": missing_cust_pct,
        "cancellation_invoices": total_cancellation_rows,
        "cancellation_prefix_invoice_rows": total_cancellation_rows,
        "distinct_cancellation_invoices": len(global_cancellation_invoices),
        "positive_quantities": total_positive_qty,
        "positive_quantity_rows": total_positive_qty,
        "negative_quantities": total_negative_qty,
        "negative_quantity_rows": total_negative_qty,
        "zero_quantities": total_zero_qty,
        "zero_quantity_rows": total_zero_qty,
        "positive_prices": total_positive_prices,
        "negative_prices": total_negative_prices,
        "zero_prices": total_zero_prices,
        "nonpositive_prices": total_nonpositive_prices,
        "nonpositive_price_rows": total_nonpositive_prices,
        "negative_qty_and_cancellation_invoice": total_neg_qty_cancellation,
        "negative_quantity_and_cancellation_prefix_overlap_rows": total_neg_qty_cancellation,
        "negative_qty_and_not_cancellation_invoice": total_neg_qty_not_cancellation,
        "positive_qty_and_cancellation_invoice": total_pos_qty_cancellation,
        "positive_qty_and_not_cancellation_invoice": total_pos_qty_not_cancellation,
        "potential_positive_purchase_lines": total_potential_purchase_lines,
        "potential_positive_purchase_identified_cust": total_potential_purchase_identified_cust,
        "potential_positive_purchase_missing_cust": total_potential_purchase_missing_cust,
        "preliminary_arithmetic_raw_line_sum": sum_raw_line,
        "raw_quantity_times_price_sum_all_rows": sum_raw_line,
        "preliminary_arithmetic_positive_lines_sum": sum_pos_lines,
        "preliminary_arithmetic_negative_lines_sum": sum_neg_lines,
        "preliminary_arithmetic_identified_cust_sum": sum_id_cust,
        "raw_quantity_times_price_sum_identified_customers": sum_id_cust,
        "preliminary_arithmetic_missing_cust_sum": sum_miss_cust,
        "raw_quantity_times_price_sum_missing_customer_id": sum_miss_cust,
    }

    all_profiles = sheet_profiles + [combined_profile_row]
    csv_profiles = []
    for p in all_profiles:
        row = dict(p)
        row["column_names"] = ";".join(str(c) for c in row.get("column_names", []))
        csv_profiles.append(row)
    sheet_profile_df = pd.DataFrame.from_records(csv_profiles)

    audit_json = {
        "audit_metadata": {
            "source_workbook": str(source_name),
            "audit_timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "sheets_found": list(sheets_dict.keys()),
            "total_worksheets": len(sheets_dict),
            "total_rows_all_sheets": total_rows,
        },
        "disclaimer": (
            "All arithmetic sums (Quantity × Price) in this audit are exploratory data diagnostics. "
            "They MUST NOT be cited or interpreted as net revenue, realised revenue, gross margin, "
            "financial impact, or campaign profit."
        ),
        "sheets": {p["sheet_name"]: p for p in sheet_profiles},
        "combined_summary": combined_profile_row,
        "schema_consistency": schema_consistency,
    }

    return audit_json, sheet_profile_df, combined_missingness_df


def audit_workbook(input_path: str | Path, output_dir: str | Path) -> dict[str, Any]:
    """Profile every worksheet and write machine-readable audit outputs."""
    return run_source_data_audit(input_path, output_dir)


def run_source_data_audit(
    input_path: Path | str,
    output_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Execute complete source data audit on the specified workbook file."""
    input_file = Path(input_path).resolve()
    if not input_file.exists():
        raise FileNotFoundError(f"Source data workbook not found at: {input_file}")

    if input_file.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise ValueError(
            f"Unsupported file format '{input_file.suffix}'. "
            f"Expected one of: {sorted(SUPPORTED_EXTENSIONS)}"
        )

    logger.info("Inspecting workbook structure: %s", input_file)
    wb = openpyxl.load_workbook(input_file, read_only=True)
    sheet_names = list(wb.sheetnames)
    wb.close()

    if not sheet_names:
        raise ValueError(f"No worksheets found in workbook: {input_file}")

    logger.info("Found %d worksheets: %s", len(sheet_names), sheet_names)

    sheet_profiles: list[dict[str, Any]] = []
    missingness_dfs: list[pd.DataFrame] = []

    global_customer_ids: set[Any] = set()
    global_invoice_ids: set[Any] = set()
    global_cancellation_invoices: set[Any] = set()

    schema_consistency: dict[str, Any] = {
        "sheets_have_identical_columns": True,
        "sheet_columns": {},
        "unexpected_columns": [],
    }
    first_columns: list[str] | None = None

    for idx, sheet_name in enumerate(sheet_names, start=1):
        logger.info(
            "Loading sheet %d/%d: '%s' from %s",
            idx,
            len(sheet_names),
            sheet_name,
            input_file.name,
        )
        df_sheet = pd.read_excel(input_file, sheet_name=sheet_name)
        col_list = list(df_sheet.columns)
        schema_consistency["sheet_columns"][sheet_name] = [str(c) for c in col_list]

        if first_columns is None:
            first_columns = col_list
        elif col_list != first_columns:
            schema_consistency["sheets_have_identical_columns"] = False

        col_map = resolve_column_mapping(col_list)

        miss_df = audit_sheet_missingness(df_sheet, sheet_name, col_map)
        missingness_dfs.append(miss_df)

        profile = profile_worksheet(df_sheet, sheet_name, col_map)
        sheet_profiles.append(profile)

        cust_col = col_map["customer_id"]
        inv_col = col_map["invoice"]
        global_customer_ids.update(df_sheet[cust_col].dropna().unique())
        global_invoice_ids.update(df_sheet[inv_col].dropna().unique())

        inv_str = df_sheet[inv_col].astype(str).str.strip().str.upper()
        cancels = df_sheet[inv_col][inv_str.str.startswith("C")].dropna().unique()
        global_cancellation_invoices.update(cancels)

        del df_sheet
        gc.collect()

    combined_missingness_df = (
        pd.concat(missingness_dfs, ignore_index=True)
        if missingness_dfs
        else pd.DataFrame()
    )

    total_rows = sum(p["row_count"] for p in sheet_profiles)
    total_exact_duplicates = sum(p["exact_duplicate_rows"] for p in sheet_profiles)
    total_cancellation_rows = sum(p["cancellation_invoices"] for p in sheet_profiles)
    total_missing_cust = sum(p["missing_customer_ids"] for p in sheet_profiles)
    missing_cust_pct = (
        round(total_missing_cust / total_rows * 100.0, 4) if total_rows > 0 else 0.0
    )

    min_dates = [p["min_invoice_date"] for p in sheet_profiles if p["min_invoice_date"]]
    max_dates = [p["max_invoice_date"] for p in sheet_profiles if p["max_invoice_date"]]
    overall_min_date = min(min_dates) if min_dates else None
    overall_max_date = max(max_dates) if max_dates else None

    total_date_parse_failures = sum(p["date_parse_failures"] for p in sheet_profiles)
    total_positive_qty = sum(p["positive_quantities"] for p in sheet_profiles)
    total_negative_qty = sum(p["negative_quantities"] for p in sheet_profiles)
    total_zero_qty = sum(p["zero_quantities"] for p in sheet_profiles)
    total_positive_prices = sum(p["positive_prices"] for p in sheet_profiles)
    total_negative_prices = sum(p["negative_prices"] for p in sheet_profiles)
    total_zero_prices = sum(p["zero_prices"] for p in sheet_profiles)
    total_nonpositive_prices = sum(p["nonpositive_prices"] for p in sheet_profiles)

    total_neg_qty_cancellation = sum(
        p["negative_qty_and_cancellation_invoice"] for p in sheet_profiles
    )
    total_neg_qty_not_cancellation = sum(
        p["negative_qty_and_not_cancellation_invoice"] for p in sheet_profiles
    )
    total_pos_qty_cancellation = sum(
        p["positive_qty_and_cancellation_invoice"] for p in sheet_profiles
    )
    total_pos_qty_not_cancellation = sum(
        p["positive_qty_and_not_cancellation_invoice"] for p in sheet_profiles
    )

    total_potential_purchase_lines = sum(
        p["potential_positive_purchase_lines"] for p in sheet_profiles
    )
    total_potential_purchase_identified_cust = sum(
        p["potential_positive_purchase_identified_cust"] for p in sheet_profiles
    )
    total_potential_purchase_missing_cust = sum(
        p["potential_positive_purchase_missing_cust"] for p in sheet_profiles
    )

    sum_raw_line = round(sum(p["preliminary_arithmetic_raw_line_sum"] for p in sheet_profiles), 2)
    sum_pos_lines = round(sum(p["preliminary_arithmetic_positive_lines_sum"] for p in sheet_profiles), 2)
    sum_neg_lines = round(sum(p["preliminary_arithmetic_negative_lines_sum"] for p in sheet_profiles), 2)
    sum_id_cust = round(sum(p["preliminary_arithmetic_identified_cust_sum"] for p in sheet_profiles), 2)
    sum_miss_cust = round(sum(p["preliminary_arithmetic_missing_cust_sum"] for p in sheet_profiles), 2)

    combined_profile_row = {
        "sheet": "Combined_All_Sheets",
        "sheet_name": "Combined_All_Sheets",
        "row_count": total_rows,
        "column_count": len(first_columns) if first_columns else 0,
        "column_names": first_columns or [],
        "min_invoice_date": overall_min_date,
        "max_invoice_date": overall_max_date,
        "date_parse_failures": total_date_parse_failures,
        "missing_or_unparseable_invoice_dates": total_date_parse_failures,
        "distinct_customers": len(global_customer_ids),
        "unique_customer_ids": len(global_customer_ids),
        "distinct_invoices": len(global_invoice_ids),
        "unique_invoices": len(global_invoice_ids),
        "exact_duplicate_rows": total_exact_duplicates,
        "exact_duplicate_rows_after_first": total_exact_duplicates,
        "missing_customer_ids": total_missing_cust,
        "missing_customer_id_rows": total_missing_cust,
        "missing_customer_id_pct": missing_cust_pct,
        "cancellation_invoices": total_cancellation_rows,
        "cancellation_prefix_invoice_rows": total_cancellation_rows,
        "distinct_cancellation_invoices": len(global_cancellation_invoices),
        "positive_quantities": total_positive_qty,
        "positive_quantity_rows": total_positive_qty,
        "negative_quantities": total_negative_qty,
        "negative_quantity_rows": total_negative_qty,
        "zero_quantities": total_zero_qty,
        "zero_quantity_rows": total_zero_qty,
        "positive_prices": total_positive_prices,
        "negative_prices": total_negative_prices,
        "zero_prices": total_zero_prices,
        "nonpositive_prices": total_nonpositive_prices,
        "nonpositive_price_rows": total_nonpositive_prices,
        "negative_qty_and_cancellation_invoice": total_neg_qty_cancellation,
        "negative_quantity_and_cancellation_prefix_overlap_rows": total_neg_qty_cancellation,
        "negative_qty_and_not_cancellation_invoice": total_neg_qty_not_cancellation,
        "positive_qty_and_cancellation_invoice": total_pos_qty_cancellation,
        "positive_qty_and_not_cancellation_invoice": total_pos_qty_not_cancellation,
        "potential_positive_purchase_lines": total_potential_purchase_lines,
        "potential_positive_purchase_identified_cust": total_potential_purchase_identified_cust,
        "potential_positive_purchase_missing_cust": total_potential_purchase_missing_cust,
        "preliminary_arithmetic_raw_line_sum": sum_raw_line,
        "raw_quantity_times_price_sum_all_rows": sum_raw_line,
        "preliminary_arithmetic_positive_lines_sum": sum_pos_lines,
        "preliminary_arithmetic_negative_lines_sum": sum_neg_lines,
        "preliminary_arithmetic_identified_cust_sum": sum_id_cust,
        "raw_quantity_times_price_sum_identified_customers": sum_id_cust,
        "preliminary_arithmetic_missing_cust_sum": sum_miss_cust,
        "raw_quantity_times_price_sum_missing_customer_id": sum_miss_cust,
    }

    all_profiles = sheet_profiles + [combined_profile_row]
    csv_profiles = []
    for p in all_profiles:
        row = dict(p)
        row["column_names"] = ";".join(str(c) for c in row.get("column_names", []))
        csv_profiles.append(row)
    sheet_profile_df = pd.DataFrame.from_records(csv_profiles)

    audit_json = {
        "input_file": input_file.name,
        "sheet_names": sheet_names,
        "sheets": sheet_profiles,
        "audit_metadata": {
            "source_workbook": str(input_file),
            "audit_timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "sheets_found": sheet_names,
            "total_worksheets": len(sheet_names),
            "total_rows_all_sheets": total_rows,
        },
        "disclaimer": (
            "All arithmetic sums (Quantity × Price) in this audit are exploratory data diagnostics. "
            "They MUST NOT be cited or interpreted as net revenue, realised revenue, gross margin, "
            "financial impact, or campaign profit."
        ),
        "combined_summary": combined_profile_row,
        "schema_consistency": schema_consistency,
    }

    if output_dir is not None:
        out_path = Path(output_dir).resolve()
    else:
        out_path = (Path(__file__).resolve().parents[3] / "outputs" / "metrics").resolve()

    out_path.mkdir(parents=True, exist_ok=True)

    sheet_profile_file = out_path / "source_sheet_profile.csv"
    missingness_file = out_path / "source_missingness.csv"
    audit_json_file = out_path / "source_data_audit.json"

    sheet_profile_df.to_csv(sheet_profile_file, index=False)
    combined_missingness_df.to_csv(missingness_file, index=False)
    with open(audit_json_file, "w", encoding="utf-8") as f:
        json.dump(audit_json, f, indent=2, ensure_ascii=False, default=str)

    logger.info("Saved sheet profiles to: %s", sheet_profile_file)
    logger.info("Saved missingness table to: %s", missingness_file)
    logger.info("Saved audit JSON to: %s", audit_json_file)

    return audit_json

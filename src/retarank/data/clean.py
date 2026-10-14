"""Canonical raw transaction ledger construction and cleaning module for RetaRank."""
from __future__ import annotations

import gc
import logging
from pathlib import Path
from typing import Any

import numpy as np
import openpyxl
import pandas as pd

from retarank.config import PROCESSED_DATA_DIR, RAW_DATA_DIR
from retarank.data.audit import resolve_column_mapping

logger = logging.getLogger(__name__)

# Standard 8 columns in source sheets
SOURCE_COLUMNS = [
    "Invoice",
    "StockCode",
    "Description",
    "Quantity",
    "InvoiceDate",
    "Price",
    "Customer ID",
    "Country",
]

# Recognised administrative, service, fee, and ledger adjustment stock codes
# These are investigated in Phase 2A and categorized separately from merchandise lines.
ADMIN_STOCK_CODES = {
    "POST",
    "DOT",
    "M",
    "D",
    "BANK CHARGES",
    "CRUK",
    "AMAZONFEE",
    "B",
    "ADJUST",
    "TEST",
    "PADS",
}


def _sheet_prefix(sheet_name: str) -> str:
    """Derive short prefix from sheet name for unique row identifier."""
    cleaned = sheet_name.replace("Year", "").replace(" ", "").replace("-", "")
    return f"Y{cleaned}" if cleaned else "S"


def build_canonical_ledger(input_path: Path | str | None = None) -> pd.DataFrame:
    """Build combined canonical raw transaction ledger from both worksheets.

    Preserves:
    - Original sheet name and 1-based original Excel row number.
    - Stable, globally unique source row identifier (`source_row_id`).
    - Exact original values for all 8 source columns.
    - Derived parsed types (date, quantity, price, customer ID).
    - Exact unrounded line amount (`Quantity * Price`).
    - Audit flags, within-sheet duplicate flag, across-workbook duplicate flag,
      and mutually exclusive classification reason codes.

    Parameters
    ----------
    input_path : Path | str | None
        Path to source workbook. If None, defaults to `data/raw/online_retail_II.xlsx`.

    Returns
    -------
    pd.DataFrame
        Complete canonical raw transaction ledger (1,067,371 rows).
    """
    if input_path is None:
        file_path = RAW_DATA_DIR / "online_retail_II.xlsx"
    else:
        file_path = Path(input_path).resolve()

    if not file_path.exists():
        raise FileNotFoundError(f"Source workbook not found at: {file_path}")

    wb = openpyxl.load_workbook(file_path, read_only=True)
    sheet_names = list(wb.sheetnames)
    wb.close()

    if not sheet_names:
        raise ValueError(f"No worksheets found in workbook: {file_path}")

    sheet_frames: list[pd.DataFrame] = []

    for sheet_name in sheet_names:
        logger.info("Loading worksheet '%s' from %s", sheet_name, file_path.name)
        df_sheet = pd.read_excel(file_path, sheet_name=sheet_name)
        col_map = resolve_column_mapping(list(df_sheet.columns))

        # Standardize source column names to canonical casing if slightly different
        inv_col = col_map["invoice"]
        stock_col = col_map.get("stock_code", "StockCode")
        desc_col = col_map.get("description", "Description")
        qty_col = col_map["quantity"]
        date_col = col_map["invoice_date"]
        price_col = col_map["price"]
        cust_col = col_map["customer_id"]
        country_col = col_map.get("country", "Country")

        prefix = _sheet_prefix(sheet_name)
        # Excel data rows start at row 2 (row 1 is header)
        excel_rows = np.arange(2, len(df_sheet) + 2, dtype=np.int64)

        sheet_df = pd.DataFrame({
            "sheet_name": sheet_name,
            "excel_row": excel_rows,
            "source_row_id": [f"{prefix}:{r}" for r in excel_rows],
            "Invoice": df_sheet[inv_col].astype("string"),
            "StockCode": df_sheet[stock_col].astype("string"),
            "Description": df_sheet[desc_col].astype("string"),
            "Quantity": df_sheet[qty_col],
            "InvoiceDate": df_sheet[date_col],
            "Price": df_sheet[price_col],
            "Customer ID": df_sheet[cust_col],
            "Country": df_sheet[country_col].astype("string"),
        })

        # Mark within-sheet duplicates
        sheet_df["is_duplicate_within_sheet"] = sheet_df.duplicated(
            subset=SOURCE_COLUMNS, keep="first"
        )

        sheet_frames.append(sheet_df)
        del df_sheet
        gc.collect()

    logger.info("Combining worksheets into unified raw ledger...")
    ledger = pd.concat(sheet_frames, ignore_index=True)

    # Validate row counts and source-row uniqueness
    expected_rows = sum(len(f) for f in sheet_frames)
    if len(ledger) != expected_rows:
        raise ValueError(
            f"Ledger row count mismatch: combined {len(ledger)} != sum of sheets {expected_rows}"
        )

    if ledger["source_row_id"].nunique() != len(ledger):
        raise ValueError("Source row IDs are not unique in canonical ledger!")

    # Mark across-workbook duplicates (Specification B filter)
    ledger["is_duplicate_across_workbook"] = ledger.duplicated(
        subset=SOURCE_COLUMNS, keep="first"
    )

    # Distinguish cross-sheet duplicates: duplicate across workbook, but NOT within sheet
    ledger["is_cross_sheet_duplicate"] = (
        ledger["is_duplicate_across_workbook"] & (~ledger["is_duplicate_within_sheet"])
    )

    # Parse and enrich derived typed fields
    logger.info("Enriching ledger with parsed fields and classification rules...")
    ledger["sheet_name"] = ledger["sheet_name"].astype("string")
    ledger["source_row_id"] = ledger["source_row_id"].astype("string")
    ledger["parsed_invoice"] = ledger["Invoice"].astype("string").str.strip()
    ledger["parsed_stock_code"] = ledger["StockCode"].astype("string").str.strip()
    ledger["parsed_description"] = ledger["Description"].astype("string").str.strip()
    ledger["parsed_quantity"] = pd.to_numeric(ledger["Quantity"], errors="coerce").fillna(0).astype(np.int64)
    ledger["parsed_date"] = pd.to_datetime(ledger["InvoiceDate"], errors="coerce")
    ledger["parsed_price"] = pd.to_numeric(ledger["Price"], errors="coerce").fillna(0.0).astype(np.float64)
    ledger["parsed_customer_id"] = pd.to_numeric(ledger["Customer ID"], errors="coerce")
    ledger["parsed_country"] = ledger["Country"].astype("string").str.strip()

    # Exact arithmetic line amount: Quantity * Price
    ledger["raw_line_amount"] = (ledger["parsed_quantity"] * ledger["parsed_price"]).astype(np.float64)

    # Diagnostic flags
    ledger["is_cancellation"] = ledger["parsed_invoice"].str.upper().str.startswith("C")
    ledger["has_customer_id"] = ledger["parsed_customer_id"].notna()

    # Quantity sign: positive, negative, zero
    q_sign = np.where(
        ledger["parsed_quantity"] > 0,
        "positive",
        np.where(ledger["parsed_quantity"] < 0, "negative", "zero"),
    )
    ledger["quantity_sign"] = pd.Series(q_sign, index=ledger.index, dtype="string")

    # Price sign: positive, negative, zero
    p_sign = np.where(
        ledger["parsed_price"] > 0,
        "positive",
        np.where(ledger["parsed_price"] < 0, "negative", "zero"),
    )
    ledger["price_sign"] = pd.Series(p_sign, index=ledger.index, dtype="string")

    # Administrative stock code recognition
    clean_stock_upper = ledger["parsed_stock_code"].str.upper()
    ledger["is_administrative"] = clean_stock_upper.isin(ADMIN_STOCK_CODES)

    # Mutually exclusive classification category assignment
    # Vectorized category determination for complete traceability
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
        # 1. Identified Merchandise Purchase: Qty > 0, Price > 0, has Cust, not C, not admin
        is_pos_q & is_pos_p & (~is_c) & has_cust & (~is_admin),
        # 2. Identified Administrative / Service Purchase: Qty > 0, Price > 0, has Cust, not C, is admin (e.g. POST, M)
        is_pos_q & is_pos_p & (~is_c) & has_cust & is_admin,
        # 3. Anonymous Merchandise Purchase: Qty > 0, Price > 0, no Cust, not C, not admin
        is_pos_q & is_pos_p & (~is_c) & (~has_cust) & (~is_admin),
        # 4. Anonymous Administrative / Service Purchase: Qty > 0, Price > 0, no Cust, not C, is admin (e.g. DOT, AMAZONFEE)
        is_pos_q & is_pos_p & (~is_c) & (~has_cust) & is_admin,
        # 5. Identified Cancellation Return: Qty < 0, Price > 0, has Cust, is C
        is_neg_q & is_pos_p & is_c & has_cust,
        # 6. Anonymous Cancellation Return: Qty < 0, Price > 0, no Cust, is C
        is_neg_q & is_pos_p & is_c & (~has_cust),
        # 7. Unprefixed Negative Inventory Adjustment: Qty < 0, Price == 0, not C (damages, check, write-off)
        is_neg_q & is_zero_p & (~is_c),
        # 8. Unprefixed Negative Priced Line: Qty < 0, Price > 0, not C (rare un-prefixed return/manual)
        is_neg_q & is_pos_p & (~is_c),
        # 9. Non-positive Price - Negative Ledger Adjustment: Price < 0 (StockCode B, Bad debt)
        is_neg_p,
        # 10. Non-positive Price - Zero Price Sample/Gift: Qty >= 0, Price == 0
        (~is_neg_q) & is_zero_p,
        # 11. Cancellation Prefix with Positive Quantity: is C, Qty > 0
        is_c & is_pos_q,
        # 12. Zero Quantity line: Qty == 0
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

    ledger["classification_category"] = pd.Series(
        np.select(conditions, choices, default="OTHER_ANOMALY"),
        index=ledger.index,
        dtype="string",
    )

    # Define valid merchandise purchase line:
    # A commercial merchandise purchase line contributing to valid purchase orders
    ledger["is_valid_merchandise_purchase"] = (
        is_pos_q & is_pos_p & (~is_c) & has_cust & (~is_admin)
    )

    # Define valid customer return line:
    # A customer cancellation line deducting from customer spend
    ledger["is_valid_customer_return"] = (
        is_neg_q & is_pos_p & is_c & has_cust & (~is_admin)
    )

    logger.info("Canonical ledger built successfully with %d rows", len(ledger))
    return ledger


def get_deduplicated_ledger(
    ledger: pd.DataFrame,
    specification: str = "B",
) -> pd.DataFrame:
    """Filter canonical ledger to specified deduplication specification.

    Parameters
    ----------
    ledger : pd.DataFrame
        Complete canonical raw transaction ledger.
    specification : str
        'A' or 'with_duplicates' to retain all rows.
        'B' or 'primary' to remove exact 8-field duplicates across the workbook.

    Returns
    -------
    pd.DataFrame
        Filtered ledger under the requested specification.
    """
    spec_upper = str(specification).strip().upper()
    if spec_upper in {"A", "WITH_DUPLICATES", "SPEC_A"}:
        return ledger.copy()
    elif spec_upper in {"B", "PRIMARY", "SPEC_B", "DEDUPLICATED"}:
        return ledger[~ledger["is_duplicate_across_workbook"]].copy()
    else:
        raise ValueError(f"Unknown specification '{specification}'. Expected 'A' or 'B'.")


def export_processed_datasets(
    ledger: pd.DataFrame,
    output_dir: Path | str | None = None,
) -> dict[str, Path]:
    """Export canonical processed transaction datasets in Parquet format.

    Parameters
    ----------
    ledger : pd.DataFrame
        Complete canonical raw transaction ledger.
    output_dir : Path | str | None
        Directory where datasets should be saved.
        Defaults to `data/processed`.

    Returns
    -------
    dict[str, Path]
        Dictionary mapping dataset name to exported Parquet path.
    """
    if output_dir is None:
        out_path = PROCESSED_DATA_DIR
    else:
        out_path = Path(output_dir).resolve()

    out_path.mkdir(parents=True, exist_ok=True)

    spec_b_df = get_deduplicated_ledger(ledger, specification="B")
    spec_a_df = get_deduplicated_ledger(ledger, specification="A")

    primary_file = out_path / "transactions_primary.parquet"
    with_dups_file = out_path / "transactions_with_duplicates.parquet"

    logger.info("Exporting Specification B (Primary) Parquet: %s", primary_file)
    spec_b_df.to_parquet(primary_file, engine="pyarrow", index=False)

    logger.info("Exporting Specification A (With Duplicates) Parquet: %s", with_dups_file)
    spec_a_df.to_parquet(with_dups_file, engine="pyarrow", index=False)

    return {
        "transactions_primary": primary_file,
        "transactions_with_duplicates": with_dups_file,
    }

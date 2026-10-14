"""Tests for source data audit module."""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from retarank.data.audit import (
    audit_sheet_missingness,
    audit_workbook_dataframes,
    normalize_col_name,
    profile_worksheet,
    resolve_column_mapping,
    run_source_data_audit,
)


@pytest.fixture
def synthetic_retail_df() -> pd.DataFrame:
    """Create a controlled synthetic dataset with known properties."""
    data = [
        # Normal purchase 1
        {"Invoice": "10001", "StockCode": "A1", "Description": "Item 1", "Quantity": 10, "InvoiceDate": "2010-01-01 10:00:00", "Price": 2.50, "Customer ID": 12345.0, "Country": "United Kingdom"},
        # Normal purchase 2 (same customer, different invoice)
        {"Invoice": "10002", "StockCode": "B2", "Description": "Item 2", "Quantity": 4, "InvoiceDate": "2010-01-05 12:00:00", "Price": 10.00, "Customer ID": 12345.0, "Country": "United Kingdom"},
        # Exact duplicate of row 2 (same invoice, stockcode, qty, etc.)
        {"Invoice": "10002", "StockCode": "B2", "Description": "Item 2", "Quantity": 4, "InvoiceDate": "2010-01-05 12:00:00", "Price": 10.00, "Customer ID": 12345.0, "Country": "United Kingdom"},
        # Cancellation with negative quantity
        {"Invoice": "C10003", "StockCode": "B2", "Description": "Item 2 Return", "Quantity": -2, "InvoiceDate": "2010-01-10 14:00:00", "Price": 10.00, "Customer ID": 12345.0, "Country": "United Kingdom"},
        # Negative quantity WITHOUT 'C' prefix (e.g. inventory loss / stock adjustment)
        {"Invoice": "10004", "StockCode": "D4", "Description": "Damaged stock", "Quantity": -5, "InvoiceDate": "2010-01-12 15:00:00", "Price": 3.00, "Customer ID": np.nan, "Country": "United Kingdom"},
        # Zero quantity line
        {"Invoice": "10005", "StockCode": "Z0", "Description": "Zero test", "Quantity": 0, "InvoiceDate": "2010-01-15 09:00:00", "Price": 5.00, "Customer ID": 99999.0, "Country": "France"},
        # Zero price line
        {"Invoice": "10006", "StockCode": "FREE", "Description": "Sample item", "Quantity": 1, "InvoiceDate": "2010-01-16 11:00:00", "Price": 0.00, "Customer ID": 99999.0, "Country": "France"},
        # Negative price line (ledger adjustment)
        {"Invoice": "10007", "StockCode": "ADJ", "Description": "Debt adjust", "Quantity": 1, "InvoiceDate": "2010-01-18 16:00:00", "Price": -50.00, "Customer ID": np.nan, "Country": "United Kingdom"},
        # Anonymous customer normal purchase
        {"Invoice": "10008", "StockCode": "G7", "Description": "Guest item", "Quantity": 3, "InvoiceDate": "2010-01-20 17:00:00", "Price": 4.00, "Customer ID": np.nan, "Country": "Germany"},
        # Positive quantity with 'C' prefix (unusual anomaly)
        {"Invoice": "C10009", "StockCode": "A1", "Description": "Weird cancel line", "Quantity": 2, "InvoiceDate": "2010-01-22 18:00:00", "Price": 2.50, "Customer ID": 12345.0, "Country": "United Kingdom"},
    ]
    return pd.DataFrame(data)


def test_flexible_column_name_recognition() -> None:
    # Standard Online Retail II column format
    cols1 = ["Invoice", "StockCode", "Description", "Quantity", "InvoiceDate", "Price", "Customer ID", "Country"]
    map1 = resolve_column_mapping(cols1)
    assert map1["invoice"] == "Invoice"
    assert map1["customer_id"] == "Customer ID"
    assert map1["invoice_date"] == "InvoiceDate"
    assert map1["price"] == "Price"
    assert map1["quantity"] == "Quantity"

    # Alternate naming format (e.g. Kaggle / UCI variant names)
    cols2 = ["InvoiceNo", "Stock_Code", "desc", "Qty", "invoice_date", "UnitPrice", "CustomerID", "country"]
    map2 = resolve_column_mapping(cols2)
    assert map2["invoice"] == "InvoiceNo"
    assert map2["customer_id"] == "CustomerID"
    assert map2["invoice_date"] == "invoice_date"
    assert map2["price"] == "UnitPrice"
    assert map2["quantity"] == "Qty"


def test_missing_required_columns_raises_error() -> None:
    bad_cols = ["Invoice", "StockCode", "Description", "InvoiceDate", "Price"]  # missing Quantity & Customer ID
    with pytest.raises(ValueError, match="Could not resolve required columns"):
        resolve_column_mapping(bad_cols)


def test_missingness_calculation(synthetic_retail_df: pd.DataFrame) -> None:
    col_map = resolve_column_mapping(list(synthetic_retail_df.columns))
    miss_df = audit_sheet_missingness(synthetic_retail_df, "TestSheet", col_map)

    assert len(miss_df) == len(synthetic_retail_df.columns)
    cust_row = miss_df[miss_df["column_name"] == "Customer ID"].iloc[0]
    # In synthetic dataset, rows 4, 7, 8 have NaN Customer ID -> 3 nulls out of 10 rows
    assert cust_row["null_count"] == 3
    assert cust_row["null_pct"] == 30.0
    assert cust_row["total_rows"] == 10


def test_profile_diagnostics_on_synthetic_fixture(synthetic_retail_df: pd.DataFrame) -> None:
    col_map = resolve_column_mapping(list(synthetic_retail_df.columns))
    profile = profile_worksheet(synthetic_retail_df, "TestSheet", col_map)

    assert profile["row_count"] == 10
    assert profile["column_count"] == 8
    # Exact duplicate: row 2 was duplicated once
    assert profile["exact_duplicate_rows"] == 1

    # Customer IDs: 12345.0, 99999.0 -> 2 distinct identified customers
    assert profile["distinct_customers"] == 2
    assert profile["missing_customer_ids"] == 3
    assert profile["missing_customer_id_pct"] == 30.0

    # Invoices: 10001, 10002, C10003, 10004, 10005, 10006, 10007, 10008, C10009 -> 9 distinct
    assert profile["distinct_invoices"] == 9

    # Cancellations: C10003, C10009 -> 2 rows, 2 distinct
    assert profile["cancellation_invoices"] == 2
    assert profile["distinct_cancellation_invoices"] == 2

    # Quantities:
    # Positive: 10, 4, 4, 0(no), 1, 1, 3, 2 -> 7 rows
    # Negative: -2, -5 -> 2 rows
    # Zero: 0 -> 1 row
    assert profile["positive_quantities"] == 7
    assert profile["negative_quantities"] == 2
    assert profile["zero_quantities"] == 1

    # Prices:
    # 2.50, 10.00, 10.00, 10.00, 3.00, 5.00, 0.00, -50.00, 4.00, 2.50
    # Positive: 8
    # Zero: 1 (0.00)
    # Negative: 1 (-50.00)
    # Nonpositive: 2
    assert profile["positive_prices"] == 8
    assert profile["zero_prices"] == 1
    assert profile["negative_prices"] == 1
    assert profile["nonpositive_prices"] == 2

    # Overlaps:
    # Negative qty and cancel invoice: C10003 (-2) -> 1
    # Negative qty and non-cancel: 10004 (-5) -> 1
    # Positive qty and cancel: C10009 (+2) -> 1
    # Positive qty and non-cancel: 10001(10), 10002(4), 10002(4), 10006(1), 10007(1), 10008(3) -> 6
    assert profile["negative_qty_and_cancellation_invoice"] == 1
    assert profile["negative_qty_and_not_cancellation_invoice"] == 1
    assert profile["positive_qty_and_cancellation_invoice"] == 1
    assert profile["positive_qty_and_not_cancellation_invoice"] == 6

    # Potential positive purchase lines: Quantity > 0 and Price > 0
    # 10001 (10 * 2.50 = 25)
    # 10002 (4 * 10 = 40)
    # 10002 (4 * 10 = 40)
    # 10008 (3 * 4 = 12)
    # C10009 (2 * 2.50 = 5)
    # Total lines = 5
    # Identified cust: 10001 (cust 12345), 10002 (12345), 10002 (12345), C10009 (12345) -> 4
    # Missing cust: 10008 (anon) -> 1
    assert profile["potential_positive_purchase_lines"] == 5
    assert profile["potential_positive_purchase_identified_cust"] == 4
    assert profile["potential_positive_purchase_missing_cust"] == 1

    # Arithmetic totals:
    # Row 0: 10 * 2.5 = 25.0
    # Row 1: 4 * 10.0 = 40.0
    # Row 2: 4 * 10.0 = 40.0
    # Row 3: -2 * 10.0 = -20.0
    # Row 4: -5 * 3.0 = -15.0
    # Row 5: 0 * 5.0 = 0.0
    # Row 6: 1 * 0.0 = 0.0
    # Row 7: 1 * -50.0 = -50.0
    # Row 8: 3 * 4.0 = 12.0
    # Row 9: 2 * 2.5 = 5.0
    # Sum: 25 + 40 + 40 - 20 - 15 + 0 + 0 - 50 + 12 + 5 = 37.0
    assert profile["preliminary_arithmetic_raw_line_sum"] == 37.0
    # Positive lines sum: 25 + 40 + 40 + 12 + 5 = 122.0
    assert profile["preliminary_arithmetic_positive_lines_sum"] == 122.0
    # Negative qty lines sum: -20 + -15 = -35.0
    assert profile["preliminary_arithmetic_negative_lines_sum"] == -35.0


def test_non_destructive_profiling(synthetic_retail_df: pd.DataFrame) -> None:
    """Verify that profiling does not mutate the input DataFrame."""
    col_map = resolve_column_mapping(list(synthetic_retail_df.columns))
    original_shape = synthetic_retail_df.shape
    original_copy = synthetic_retail_df.copy(deep=True)

    _ = profile_worksheet(synthetic_retail_df, "TestSheet", col_map)
    _ = audit_sheet_missingness(synthetic_retail_df, "TestSheet", col_map)

    assert synthetic_retail_df.shape == original_shape
    pd.testing.assert_frame_equal(synthetic_retail_df, original_copy)


def test_unparseable_and_missing_dates() -> None:
    df = pd.DataFrame([
        {"Invoice": "1", "Quantity": 1, "Price": 1.0, "Customer ID": 100, "InvoiceDate": "2020-01-01 10:00:00"},
        {"Invoice": "2", "Quantity": 1, "Price": 1.0, "Customer ID": 100, "InvoiceDate": "not_a_real_date"},
        {"Invoice": "3", "Quantity": 1, "Price": 1.0, "Customer ID": 100, "InvoiceDate": None},
    ])
    col_map = resolve_column_mapping(list(df.columns))
    profile = profile_worksheet(df, "DateTest", col_map)

    # 1 unparseable non-null date ("not_a_real_date")
    assert profile["date_parse_failures"] == 1
    assert profile["min_invoice_date"] == "2020-01-01T10:00:00"
    assert profile["max_invoice_date"] == "2020-01-01T10:00:00"


def test_multi_sheet_audit_and_cross_sheet_deduplication(synthetic_retail_df: pd.DataFrame) -> None:
    # Sheet 1: synthetic_retail_df (custs: 12345, 99999)
    # Sheet 2: synthetic_retail_df with 1 new customer (77777) and 1 overlapping customer (12345)
    df2 = pd.DataFrame([
        {"Invoice": "20001", "StockCode": "X", "Description": "X", "Quantity": 5, "InvoiceDate": "2011-02-01 10:00:00", "Price": 10.0, "Customer ID": 12345.0, "Country": "UK"},
        {"Invoice": "20002", "StockCode": "Y", "Description": "Y", "Quantity": 2, "InvoiceDate": "2011-02-02 11:00:00", "Price": 20.0, "Customer ID": 77777.0, "Country": "UK"},
    ])

    sheets = {"Year 2009-2010": synthetic_retail_df, "Year 2010-2011": df2}
    audit_json, sheet_profile_df, missing_df = audit_workbook_dataframes(sheets, "synthetic_test")

    # Sheet 1 has 2 distinct custs; Sheet 2 has 2 distinct custs
    # Combined distinct customers = {12345, 99999, 77777} -> 3
    comb = audit_json["combined_summary"]
    assert comb["distinct_customers"] == 3
    assert comb["row_count"] == 12
    assert audit_json["schema_consistency"]["sheets_have_identical_columns"] is True
    assert len(sheet_profile_df) == 3  # 2 sheets + Combined


def test_unsupported_file_extension_raises(tmp_path: Path) -> None:
    fake_csv = tmp_path / "test.csv"
    fake_csv.write_text("a,b,c\n1,2,3")
    with pytest.raises(ValueError, match="Unsupported file format"):
        run_source_data_audit(fake_csv)


def test_missing_file_raises_not_found() -> None:
    with pytest.raises(FileNotFoundError, match="not found"):
        run_source_data_audit("non_existent_workbook.xlsx")

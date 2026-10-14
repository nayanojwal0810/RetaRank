import pandas as pd

from retarank.data.audit import profile_sheet, resolve_columns


def test_resolve_columns_handles_spaces_and_punctuation() -> None:
    resolved = resolve_columns(
        ["Invoice", "StockCode", "Invoice Date", "Quantity", "Price", "Customer ID"]
    )
    assert resolved["invoice"] == "Invoice"
    assert resolved["invoice_date"] == "Invoice Date"
    assert resolved["quantity"] == "Quantity"
    assert resolved["price"] == "Price"
    assert resolved["customer_id"] == "Customer ID"


def test_profile_sheet_reports_source_metrics_without_cleaning_rows() -> None:
    frame = pd.DataFrame(
        {
            "Invoice": ["1001", "C1002", "1003"],
            "InvoiceDate": ["2010-01-01", "2010-01-02", "bad-date"],
            "Quantity": [2, -1, 0],
            "Price": [5.0, 3.0, 2.0],
            "Customer ID": [123, None, 456],
        }
    )
    profile, missingness = profile_sheet(frame, "test")

    assert profile["row_count"] == 3
    assert profile["missing_customer_id_rows"] == 1
    assert profile["cancellation_prefix_invoice_rows"] == 1
    assert profile["negative_quantity_rows"] == 1
    assert profile["zero_quantity_rows"] == 1
    assert profile["positive_quantity_rows"] == 1
    assert profile["missing_or_unparseable_invoice_dates"] == 1
    assert profile["raw_quantity_times_price_sum_all_rows"] == 7.0
    assert len(missingness) == 5
    assert len(frame) == 3  # profiling must not drop rows

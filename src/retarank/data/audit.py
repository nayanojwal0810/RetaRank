"""Non-destructive profiling of the raw Online Retail II workbook.

This module profiles source records but does not clean, drop, deduplicate, or
reinterpret transaction rows. Reported line values are arithmetic diagnostics,
not certified accounting totals.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


COLUMN_ALIASES = {
    "invoice": {"invoice", "invoiceno", "invoicenumber"},
    "quantity": {"quantity", "qty"},
    "price": {"price", "unitprice", "unitcost"},
    "invoice_date": {"invoicedate", "date"},
    "customer_id": {"customerid", "customer"},
}


def _normalise_column_name(name: object) -> str:
    """Normalise a header so harmless spaces and punctuation do not matter."""
    return re.sub(r"[^a-z0-9]", "", str(name).strip().lower())


def resolve_columns(columns: list[object] | pd.Index) -> dict[str, str | None]:
    """Map known logical fields to observed workbook column names."""
    normalised = {_normalise_column_name(col): str(col) for col in columns}
    resolved: dict[str, str | None] = {}
    for logical_name, aliases in COLUMN_ALIASES.items():
        resolved[logical_name] = next(
            (normalised[alias] for alias in aliases if alias in normalised),
            None,
        )
    return resolved


def _series_or_na(frame: pd.DataFrame, column: str | None) -> pd.Series:
    if column is None:
        return pd.Series(np.nan, index=frame.index, dtype="float64")
    return frame[column]


def profile_sheet(frame: pd.DataFrame, sheet_name: str) -> tuple[dict[str, Any], pd.DataFrame]:
    """Return high-level source diagnostics and per-column missingness."""
    columns = resolve_columns(frame.columns)
    row_count = int(len(frame))
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

    invoice = _series_or_na(frame, columns["invoice"])
    invoice_text = invoice.astype("string").str.strip()
    cancellation_invoice = invoice_text.str.upper().str.startswith("C", na=False)

    quantity = pd.to_numeric(_series_or_na(frame, columns["quantity"]), errors="coerce")
    price = pd.to_numeric(_series_or_na(frame, columns["price"]), errors="coerce")
    line_value = quantity * price
    customer_id = _series_or_na(frame, columns["customer_id"])
    invoice_date_raw = _series_or_na(frame, columns["invoice_date"])
    parsed_date = pd.to_datetime(invoice_date_raw, errors="coerce")

    quantity_negative = quantity.lt(0).fillna(False)
    quantity_zero = quantity.eq(0).fillna(False)
    quantity_positive = quantity.gt(0).fillna(False)
    price_nonpositive = price.le(0).fillna(False)
    candidate_positive_purchase = quantity_positive & price.gt(0).fillna(False) & ~cancellation_invoice

    # This is a source-level duplicate diagnostic. It does not establish that
    # any duplicate is erroneous; a sensitivity analysis is required later.
    exact_duplicate_rows_after_first = int(frame.duplicated(keep="first").sum())
    customer_present = customer_id.notna()

    metrics: dict[str, Any] = {
        "sheet": sheet_name,
        "row_count": row_count,
        "column_count": int(frame.shape[1]),
        "exact_duplicate_rows_after_first": exact_duplicate_rows_after_first,
        "missing_customer_id_rows": int((~customer_present).sum()) if columns["customer_id"] else None,
        "missing_customer_id_pct": (
            100.0 * float((~customer_present).sum()) / row_count
            if columns["customer_id"] and row_count
            else None
        ),
        "unique_customer_ids": int(customer_id.nunique(dropna=True)) if columns["customer_id"] else None,
        "unique_invoices": int(invoice.nunique(dropna=True)) if columns["invoice"] else None,
        "missing_or_unparseable_invoice_dates": int(parsed_date.isna().sum()) if columns["invoice_date"] else None,
        "min_invoice_date": parsed_date.min().isoformat() if columns["invoice_date"] and parsed_date.notna().any() else None,
        "max_invoice_date": parsed_date.max().isoformat() if columns["invoice_date"] and parsed_date.notna().any() else None,
        "cancellation_prefix_invoice_rows": int(cancellation_invoice.sum()) if columns["invoice"] else None,
        "negative_quantity_rows": int(quantity_negative.sum()) if columns["quantity"] else None,
        "zero_quantity_rows": int(quantity_zero.sum()) if columns["quantity"] else None,
        "positive_quantity_rows": int(quantity_positive.sum()) if columns["quantity"] else None,
        "nonpositive_price_rows": int(price_nonpositive.sum()) if columns["price"] else None,
        "negative_quantity_and_cancellation_prefix_overlap_rows": int((quantity_negative & cancellation_invoice).sum()),
        "candidate_positive_purchase_rows": int(candidate_positive_purchase.sum()),
        "raw_quantity_times_price_sum_all_rows": float(line_value.sum(min_count=1)) if columns["quantity"] and columns["price"] else None,
        "raw_quantity_times_price_sum_identified_customers": (
            float(line_value[customer_present].sum(min_count=1))
            if columns["customer_id"] and columns["quantity"] and columns["price"]
            else None
        ),
        "raw_quantity_times_price_sum_missing_customer_id": (
            float(line_value[~customer_present].sum(min_count=1))
            if columns["customer_id"] and columns["quantity"] and columns["price"]
            else None
        ),
        "candidate_positive_purchase_value_sum": (
            float(line_value[candidate_positive_purchase].sum(min_count=1))
            if columns["quantity"] and columns["price"] and columns["invoice"]
            else None
        ),
        "resolved_columns": columns,
    }
    return metrics, pd.DataFrame(missing_rows)


def audit_workbook(input_path: str | Path, output_dir: str | Path) -> dict[str, Any]:
    """Profile every worksheet and write machine-readable audit outputs."""
    input_path = Path(input_path)
    output_dir = Path(output_dir)
    if not input_path.exists():
        raise FileNotFoundError(
            f"Workbook not found: {input_path}. Place it in data/raw/ or pass --input."
        )
    if input_path.suffix.lower() not in {".xlsx", ".xlsm", ".xls"}:
        raise ValueError(f"Expected an Excel workbook, got: {input_path.suffix}")

    output_dir.mkdir(parents=True, exist_ok=True)
    sheet_profiles: list[dict[str, Any]] = []
    missingness_frames: list[pd.DataFrame] = []

    # Read one sheet at a time to reduce peak memory usage.
    with pd.ExcelFile(input_path) as workbook:
        sheet_names = workbook.sheet_names
        for sheet_name in sheet_names:
            frame = pd.read_excel(workbook, sheet_name=sheet_name)
            profile, missingness = profile_sheet(frame, sheet_name)
            sheet_profiles.append(profile)
            missingness_frames.append(missingness)
            del frame

    profile_frame = pd.DataFrame(sheet_profiles)
    missingness_frame = (
        pd.concat(missingness_frames, ignore_index=True)
        if missingness_frames
        else pd.DataFrame()
    )
    profile_frame.to_csv(output_dir / "source_sheet_profile.csv", index=False)
    missingness_frame.to_csv(output_dir / "source_missingness.csv", index=False)

    summary = {
        "input_file": input_path.name,
        "sheet_names": sheet_names,
        "sheets": sheet_profiles,
        "important_note": (
            "This report profiles the source workbook only. It does not clean or delete rows. "
            "Quantity-times-price sums are raw diagnostics and must not be labelled net revenue "
            "until return/cancellation accounting has been specified and reconciled."
        ),
    }
    with (output_dir / "source_data_audit.json").open("w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2, ensure_ascii=False, default=str)
    return summary

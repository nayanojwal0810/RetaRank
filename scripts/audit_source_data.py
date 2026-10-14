"""Run a non-destructive source audit for the Online Retail II workbook."""
from __future__ import annotations

import argparse
from pathlib import Path

from retarank.config import RAW_DATA_DIR, OUTPUTS_DIR
from retarank.data.audit import audit_workbook


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=RAW_DATA_DIR / "online_retail_II.xlsx",
        help="Path to the original workbook (default: data/raw/online_retail_II.xlsx)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=OUTPUTS_DIR / "metrics",
        help="Directory for source audit CSV and JSON outputs",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = audit_workbook(args.input, args.output_dir)
    print(f"Source audit complete: {args.input}")
    print(f"Sheets audited: {', '.join(summary['sheet_names'])}")
    for sheet in summary["sheets"]:
        print(
            f"- {sheet['sheet']}: {sheet['row_count']:,} rows, "
            f"{sheet['column_count']} columns, "
            f"{sheet['exact_duplicate_rows_after_first']:,} exact duplicate rows after first"
        )
    print(f"Outputs written to: {args.output_dir.resolve()}")
    print("No source rows were modified or deleted.")


if __name__ == "__main__":
    main()

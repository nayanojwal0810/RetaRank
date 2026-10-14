#!/usr/bin/env python3
"""Run source data audit on Online Retail II Excel workbook."""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

# Ensure src is on sys.path if running script directly
repo_root = Path(__file__).resolve().parents[1]
src_dir = repo_root / "src"
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from retarank.config import OUTPUTS_DIR, RAW_DATA_DIR
from retarank.data.audit import run_source_data_audit


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit source Excel workbook for RetaRank CRM retention project."
    )
    default_input = RAW_DATA_DIR / "online_retail_II.xlsx"
    default_output = OUTPUTS_DIR / "metrics"

    parser.add_argument(
        "--input",
        type=Path,
        default=default_input,
        help=f"Path to the input Excel workbook (default: {default_input})",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=default_output,
        help=f"Directory to save audit metrics (default: {default_output})",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose debug logging.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    setup_logging(args.verbose)
    logger = logging.getLogger("audit_source_data")

    logger.info("Starting RetaRank Source Data Audit")
    logger.info("Target workbook: %s", args.input)
    logger.info("Metrics destination: %s", args.output_dir)

    t0 = time.time()
    try:
        audit_result = run_source_data_audit(
            input_path=args.input,
            output_dir=args.output_dir,
        )
    except FileNotFoundError as e:
        logger.error("Audit failed: input workbook not found: %s", e)
        return 1
    except Exception as e:
        logger.exception("Audit failed with error: %s", e)
        return 1

    elapsed = time.time() - t0
    logger.info("Source data audit completed in %.2f seconds", elapsed)

    meta = audit_result["audit_metadata"]
    comb = audit_result["combined_summary"]
    print("\n" + "=" * 60)
    print("           RETARANK SOURCE DATA AUDIT SUMMARY")
    print("=" * 60)
    print(f"Workbook:             {meta['source_workbook']}")
    print(f"Sheets Audited:       {', '.join(meta['sheets_found'])}")
    print(f"Total Rows:           {comb['row_count']:,}")
    print(f"Exact Duplicates:     {comb['exact_duplicate_rows']:,}")
    print(f"Distinct Customers:   {comb['distinct_customers']:,}")
    print(f"Distinct Invoices:    {comb['distinct_invoices']:,}")
    print(f"Missing Customer IDs: {comb['missing_customer_ids']:,} ({comb['missing_customer_id_pct']}%)")
    print(f"Cancellation Lines:   {comb['cancellation_invoices']:,}")
    print(f"Observed Date Span:   {comb['min_invoice_date']} to {comb['max_invoice_date']}")
    print(f"Date Parse Failures:  {comb['date_parse_failures']}")
    print(f"Positive Qty Lines:   {comb['positive_quantities']:,}")
    print(f"Negative Qty Lines:   {comb['negative_quantities']:,}")
    print(f"Zero Qty Lines:       {comb['zero_quantities']:,}")
    print(f"Nonpositive Prices:   {comb['nonpositive_prices']:,}")
    print(f"Neg Qty & Cancel Inv: {comb['negative_qty_and_cancellation_invoice']:,}")
    print(f"Neg Qty & Non-Cancel: {comb['negative_qty_and_not_cancellation_invoice']:,}")
    print(f"Pos Qty & Cancel Inv: {comb['positive_qty_and_cancellation_invoice']:,}")
    print(f"Prelim Line Sum:      £{comb['preliminary_arithmetic_raw_line_sum']:,.2f} (DIAGNOSTIC ONLY)")
    print("=" * 60)
    print("Output artifacts generated:")
    print(f" - {args.output_dir / 'source_sheet_profile.csv'}")
    print(f" - {args.output_dir / 'source_missingness.csv'}")
    print(f" - {args.output_dir / 'source_data_audit.json'}")
    print("=" * 60 + "\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())

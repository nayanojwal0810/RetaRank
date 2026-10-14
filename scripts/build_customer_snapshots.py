#!/usr/bin/env python3
"""Execute point-in-time customer snapshot generation pipeline for RetaRank."""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

# Ensure src is on sys.path
repo_root = Path(__file__).resolve().parents[1]
src_dir = repo_root / "src"
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

import pandas as pd

from retarank.config import PROCESSED_DATA_DIR, RAW_DATA_DIR
from retarank.data.clean import build_canonical_ledger, get_deduplicated_ledger
from retarank.data.snapshots import export_snapshot_pipeline, get_monthly_cutoffs


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate point-in-time customer feature snapshots, lapse labels, cohort metrics, and maturity schedule."
    )
    default_parquet = PROCESSED_DATA_DIR / "transactions_primary.parquet"
    default_raw = RAW_DATA_DIR / "online_retail_II.xlsx"
    default_output = PROCESSED_DATA_DIR

    parser.add_argument(
        "--input-parquet",
        type=Path,
        default=default_parquet,
        help=f"Path to primary processed transactions Parquet (default: {default_parquet})",
    )
    parser.add_argument(
        "--input-raw",
        type=Path,
        default=default_raw,
        help=f"Path to raw Excel workbook if Parquet is not yet built (default: {default_raw})",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=default_output,
        help=f"Destination directory for processed customer snapshots (default: {default_output})",
    )
    parser.add_argument(
        "--from-raw",
        action="store_true",
        help="Force rebuild directly from raw Excel workbook instead of loading Parquet.",
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
    logger = logging.getLogger("build_customer_snapshots")

    logger.info("Starting Customer Snapshot Pipeline")
    t0 = time.time()

    # Load or build primary transaction ledger
    if args.input_parquet.exists() and not args.from_raw:
        logger.info("Loading primary transactions from Parquet: %s", args.input_parquet)
        transactions = pd.read_parquet(args.input_parquet)
    else:
        logger.info("Building primary transactions ledger from raw workbook: %s", args.input_raw)
        raw_ledger = build_canonical_ledger(args.input_raw)
        transactions = get_deduplicated_ledger(raw_ledger, specification="B")

    logger.info("Loaded %d clean transactions for snapshot extraction.", len(transactions))

    try:
        results = export_snapshot_pipeline(transactions, output_dir=args.output_dir)
    except Exception as e:
        logger.exception("Snapshot generation failed with error: %s", e)
        return 1

    elapsed = time.time() - t0
    logger.info("Customer snapshot pipeline completed in %.2f seconds", elapsed)

    print("\n" + "=" * 68)
    print("      RETARANK: POINT-IN-TIME CUSTOMER SNAPSHOTS SUMMARY")
    print("=" * 68)
    print(f"Total Customer Snapshot Records:   {results['total_snapshot_rows']:,}")
    print(f"Monthly Scoring Cohorts:           {results['cohort_count']}")
    print(f"Overall 90-Day Lapse Prevalence:   {results['overall_lapse_prevalence_pct']}%")
    print("=" * 68)
    print("Generated Authoritative Artifacts:")
    print(f" - Customer Snapshots (Parquet):    {results['snapshots_parquet']}")
    print(f" - Snapshot Cohort Metrics (CSV):   {results['cohort_metrics_csv']}")
    print(f" - Label Maturity Schedule (CSV):   {results['maturity_schedule_csv']}")
    print("=" * 68 + "\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())

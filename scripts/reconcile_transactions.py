#!/usr/bin/env python3
"""Run transaction reconciliation, cross-sheet overlap audit, and cleaning pipeline for RetaRank."""
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

from retarank.config import OUTPUTS_DIR, PROCESSED_DATA_DIR, RAW_DATA_DIR
from retarank.data.reconcile import run_reconciliation_pipeline


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reconcile transactions, analyze cross-sheet overlap, and export processed Parquet datasets."
    )
    default_input = RAW_DATA_DIR / "online_retail_II.xlsx"
    default_output = OUTPUTS_DIR / "metrics"
    default_data = PROCESSED_DATA_DIR

    parser.add_argument(
        "--input",
        type=Path,
        default=default_input,
        help=f"Path to input Excel workbook (default: {default_input})",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=default_output,
        help=f"Directory for metrics CSV outputs (default: {default_output})",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=default_data,
        help=f"Directory for processed Parquet datasets (default: {default_data})",
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
    logger = logging.getLogger("reconcile_transactions")

    logger.info("Starting Phase 2A Transaction Reconciliation Pipeline")
    logger.info("Source workbook: %s", args.input)
    logger.info("Metrics destination: %s", args.output_dir)
    logger.info("Processed data destination: %s", args.data_dir)

    t0 = time.time()
    try:
        results = run_reconciliation_pipeline(
            input_path=args.input,
            output_dir=args.output_dir,
            data_dir=args.data_dir,
        )
    except FileNotFoundError as e:
        logger.error("Reconciliation failed: input workbook not found: %s", e)
        return 1
    except Exception as e:
        logger.exception("Reconciliation failed with error: %s", e)
        return 1

    elapsed = time.time() - t0
    logger.info("Reconciliation pipeline completed in %.2f seconds", elapsed)

    print("\n" + "=" * 65)
    print("      RETARANK PHASE 2A: TRANSACTION RECONCILIATION SUMMARY")
    print("=" * 65)
    print(f"Total Raw Rows (Spec A):             {results['ledger_rows']:,}")
    print(f"Specification B Deduplicated Rows:   {results['spec_b_rows']:,}")
    print(f"Exact Duplicates Removed:            {results['ledger_rows'] - results['spec_b_rows']:,}")
    print("=" * 65)
    print("Generated Artifacts:")
    print(f" - Primary Parquet (Spec B):         {results['parquet_primary']}")
    print(f" - With Duplicates Parquet (Spec A): {results['parquet_with_duplicates']}")
    print(f" - Duplicate & Overlap CSV:          {results['duplicate_overlap_file']}")
    print(f" - Deduplication Sensitivity CSV:    {results['deduplication_sensitivity_file']}")
    print(f" - Transaction Classification CSV:   {results['transaction_classification_file']}")
    print(f" - Monetary Reconciliation CSV:      {results['transaction_reconciliation_file']}")
    print("=" * 65 + "\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())

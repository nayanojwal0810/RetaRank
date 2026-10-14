"""Point-in-time customer snapshot generation and label maturity tracking for RetaRank."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from retarank.config import PROCESSED_DATA_DIR

logger = logging.getLogger(__name__)

# Standard temporal configuration parameters
DEFAULT_FEATURE_WINDOW_DAYS = 180
DEFAULT_OUTCOME_WINDOW_DAYS = 90
DEFAULT_START_CUTOFF = "2010-06-01"
DEFAULT_END_CUTOFF = "2011-09-01"


def get_monthly_cutoffs(
    start_date: str = DEFAULT_START_CUTOFF,
    end_date: str = DEFAULT_END_CUTOFF,
) -> pd.DatetimeIndex:
    """Generate monthly point-in-time scoring cutoff dates (first of each month).

    Parameters
    ----------
    start_date : str
        First scoring cutoff date (YYYY-MM-DD). Defaults to 2010-06-01.
    end_date : str
        Last scoring cutoff date (YYYY-MM-DD). Defaults to 2011-09-01.

    Returns
    -------
    pd.DatetimeIndex
        Monthly timestamps representing scoring cutoff moments.
    """
    return pd.date_range(start=start_date, end=end_date, freq="MS")


def generate_single_cutoff_snapshot(
    transactions: pd.DataFrame,
    cutoff_date: pd.Timestamp | str,
    feature_window_days: int = DEFAULT_FEATURE_WINDOW_DAYS,
    outcome_window_days: int = DEFAULT_OUTCOME_WINDOW_DAYS,
) -> pd.DataFrame:
    """Compute point-in-time customer feature vector and 90-day lapse target for one cutoff date.

    Strict point-in-time rules enforced:
    - Feature window: [T - 180d, T) - strictly end-exclusive at cutoff T.
    - Outcome window: [T, T + 90d) - strictly start-inclusive at T, end-exclusive at T + 90d.
    - Customer eligibility: At least 1 valid merchandise purchase invoice in feature window.
    - Target label: 1 if 0 valid merchandise purchase invoices in outcome window, else 0.
    - Purchase events: Counted by distinct purchase invoices, never transaction line items.
    - Returns and cancellations: Subtracted from gross spend, never treated as purchase events.

    Parameters
    ----------
    transactions : pd.DataFrame
        Canonical transaction ledger (e.g. Specification B primary deduplicated).
    cutoff_date : pd.Timestamp | str
        Scoring cutoff timestamp T.
    feature_window_days : int
        Lookback duration for feature aggregation in days (default: 180).
    outcome_window_days : int
        Forward observation duration for lapse determination in days (default: 90).

    Returns
    -------
    pd.DataFrame
        Customer-level feature snapshot with binary lapse target for eligible customers.
    """
    t_cutoff = pd.Timestamp(cutoff_date)
    start_feat = t_cutoff - pd.Timedelta(days=feature_window_days)
    end_out = t_cutoff + pd.Timedelta(days=outcome_window_days)

    cutoff_str = t_cutoff.strftime("%Y-%m-%d")

    # Filter transactions into merchandise purchases and customer returns
    purchases = transactions[transactions["is_valid_merchandise_purchase"]]
    returns = transactions[transactions["is_valid_customer_return"]]

    # Historical feature window: [T - 180d, T)
    feat_purch = purchases[
        (purchases["parsed_date"] >= start_feat) & (purchases["parsed_date"] < t_cutoff)
    ]
    feat_ret = returns[
        (returns["parsed_date"] >= start_feat) & (returns["parsed_date"] < t_cutoff)
    ]

    # Future outcome window: [T, T + 90d)
    out_purch = purchases[
        (purchases["parsed_date"] >= t_cutoff) & (purchases["parsed_date"] < end_out)
    ]

    # Eligible customers: customers with >= 1 valid merchandise purchase in feature window
    eligible_cust_ids = feat_purch["parsed_customer_id"].dropna().unique()
    if len(eligible_cust_ids) == 0:
        logger.warning("No eligible customers found for cutoff %s", cutoff_str)
        return pd.DataFrame()

    # Aggregate purchase features
    p_agg = feat_purch.groupby("parsed_customer_id").agg(
        latest_purchase=("parsed_date", "max"),
        purchase_invoice_count_180d=("parsed_invoice", "nunique"),
        purchase_line_count_180d=("parsed_invoice", "count"),
        historical_gross_spend_180d=("raw_line_amount", "sum"),
        distinct_product_count_180d=("parsed_stock_code", "nunique"),
        total_quantity_180d=("parsed_quantity", "sum"),
        country=("parsed_country", lambda s: s.mode().iloc[0] if not s.empty else "Unknown"),
    ).reset_index()

    # Aggregate return deductions (raw_line_amount is negative for returns; take absolute sum)
    r_agg = feat_ret.groupby("parsed_customer_id").agg(
        historical_return_deductions_180d=("raw_line_amount", lambda s: round(abs(float(s.sum())), 2)),
        return_invoice_count_180d=("parsed_invoice", "nunique"),
    ).reset_index()

    snapshot = p_agg.merge(r_agg, on="parsed_customer_id", how="left")
    snapshot["historical_return_deductions_180d"] = snapshot["historical_return_deductions_180d"].fillna(0.0)
    snapshot["return_invoice_count_180d"] = snapshot["return_invoice_count_180d"].fillna(0).astype(int)

    # Derived temporal and monetary metrics
    # Recency: exact fractional days from latest valid purchase to cutoff T
    snapshot["recency_days"] = (
        (t_cutoff - snapshot["latest_purchase"]).dt.total_seconds() / 86400.0
    ).round(2)

    snapshot["historical_gross_spend_180d"] = snapshot["historical_gross_spend_180d"].round(2)
    snapshot["historical_net_spend_180d"] = (
        snapshot["historical_gross_spend_180d"] - snapshot["historical_return_deductions_180d"]
    ).round(2)

    # Average net invoice value
    snapshot["avg_invoice_value_180d"] = (
        snapshot["historical_net_spend_180d"] / snapshot["purchase_invoice_count_180d"]
    ).round(2)

    # Non-negative net spend (clamped at zero for rank-ordering priority score)
    snapshot["historical_net_spend_nonneg_180d"] = snapshot["historical_net_spend_180d"].clip(lower=0.0)

    # Outcome target: 1 = lapsed (0 valid purchases in [T, T + 90d)), 0 = retained (>= 1 valid purchase)
    out_active_custs = set(out_purch["parsed_customer_id"].dropna().unique())
    snapshot["lapsed_90d"] = (~snapshot["parsed_customer_id"].isin(out_active_custs)).astype(int)

    # Metadata columns
    snapshot["customer_id"] = snapshot["parsed_customer_id"].astype(np.int64)
    snapshot["cutoff_date"] = cutoff_str

    ordered_cols = [
        "customer_id",
        "cutoff_date",
        "recency_days",
        "purchase_invoice_count_180d",
        "purchase_line_count_180d",
        "historical_gross_spend_180d",
        "historical_return_deductions_180d",
        "historical_net_spend_180d",
        "historical_net_spend_nonneg_180d",
        "avg_invoice_value_180d",
        "distinct_product_count_180d",
        "total_quantity_180d",
        "return_invoice_count_180d",
        "country",
        "lapsed_90d",
    ]
    snapshot = snapshot[ordered_cols].sort_values("customer_id").reset_index(drop=True)

    # Automated validation assertions on generated cohort
    assert len(snapshot) == len(eligible_cust_ids), "Snapshot row count != eligible customer count"
    assert snapshot["customer_id"].is_unique, f"Duplicate customer_id detected in cutoff {cutoff_str}"
    assert (snapshot["recency_days"] > 0.0).all(), "Negative or zero recency_days detected"
    assert (snapshot["recency_days"] <= float(feature_window_days)).all(), "Recency exceeds feature window"
    assert (snapshot["purchase_invoice_count_180d"] >= 1).all(), "Eligible customer with 0 purchase invoices"
    assert (snapshot["historical_gross_spend_180d"] > 0.0).all(), "Non-positive gross spend on merchandise purchase"
    assert (snapshot["historical_return_deductions_180d"] >= 0.0).all(), "Negative return deduction magnitude"
    assert set(snapshot["lapsed_90d"].unique()).issubset({0, 1}), "Invalid lapse label values"

    return snapshot


def generate_customer_snapshots(
    transactions: pd.DataFrame,
    cutoffs: list[pd.Timestamp | str] | pd.DatetimeIndex | None = None,
    feature_window_days: int = DEFAULT_FEATURE_WINDOW_DAYS,
    outcome_window_days: int = DEFAULT_OUTCOME_WINDOW_DAYS,
) -> pd.DataFrame:
    """Generate multi-cutoff longitudinal customer snapshot dataset.

    Parameters
    ----------
    transactions : pd.DataFrame
        Canonical transaction ledger (e.g. Specification B primary deduplicated).
    cutoffs : list or DatetimeIndex, optional
        List of scoring cutoffs. Defaults to 16 monthly cutoffs (2010-06-01 to 2011-09-01).
    feature_window_days : int
        Lookback duration in days (default: 180).
    outcome_window_days : int
        Outcome observation duration in days (default: 90).

    Returns
    -------
    pd.DataFrame
        Consolidated multi-cutoff customer snapshots table.
    """
    if cutoffs is None:
        cutoffs = get_monthly_cutoffs()

    cohort_dfs = []
    for cutoff in cutoffs:
        t_cutoff = pd.Timestamp(cutoff)
        logger.info("Generating customer snapshot cohort for cutoff %s...", t_cutoff.strftime("%Y-%m-%d"))
        df_cohort = generate_single_cutoff_snapshot(
            transactions=transactions,
            cutoff_date=t_cutoff,
            feature_window_days=feature_window_days,
            outcome_window_days=outcome_window_days,
        )
        if not df_cohort.empty:
            cohort_dfs.append(df_cohort)

    if not cohort_dfs:
        raise ValueError("No customer snapshots were generated across provided cutoffs.")

    snapshots = pd.concat(cohort_dfs, ignore_index=True)

    # Assert composite primary key uniqueness
    pk_dups = snapshots.duplicated(subset=["customer_id", "cutoff_date"]).sum()
    assert pk_dups == 0, f"Primary key violation: {pk_dups} duplicate (customer_id, cutoff_date) rows detected"

    logger.info(
        "Successfully generated %d total customer snapshot rows across %d cutoffs.",
        len(snapshots),
        len(cohort_dfs),
    )
    return snapshots


def generate_snapshot_cohort_metrics(snapshots: pd.DataFrame) -> pd.DataFrame:
    """Produce cohort-level summary table of customer counts, lapse rates, and spend distributions.

    Parameters
    ----------
    snapshots : pd.DataFrame
        Consolidated customer snapshots.

    Returns
    -------
    pd.DataFrame
        Cohort summary metrics per cutoff date.
    """
    records = []
    for cutoff_date, group in snapshots.groupby("cutoff_date", sort=True):
        n_eligible = len(group)
        n_lapsed = int(group["lapsed_90d"].sum())
        n_retained = n_eligible - n_lapsed
        lapse_rate = round(n_lapsed / n_eligible * 100.0, 2) if n_eligible > 0 else 0.0

        records.append({
            "cutoff_date": str(cutoff_date),
            "eligible_customers": n_eligible,
            "lapsed_customers": n_lapsed,
            "retained_customers": n_retained,
            "lapse_prevalence_pct": lapse_rate,
            "mean_recency_days": round(float(group["recency_days"].mean()), 2),
            "median_recency_days": round(float(group["recency_days"].median()), 2),
            "mean_purchase_invoices_180d": round(float(group["purchase_invoice_count_180d"].mean()), 2),
            "mean_historical_gross_spend_180d": round(float(group["historical_gross_spend_180d"].mean()), 2),
            "mean_historical_return_deductions_180d": round(float(group["historical_return_deductions_180d"].mean()), 2),
            "mean_historical_net_spend_180d": round(float(group["historical_net_spend_180d"].mean()), 2),
            "median_historical_net_spend_180d": round(float(group["historical_net_spend_180d"].median()), 2),
            "total_historical_net_spend_180d": round(float(group["historical_net_spend_180d"].sum()), 2),
            "customers_with_returns_pct": round(float((group["return_invoice_count_180d"] > 0).mean() * 100.0), 2),
        })

    return pd.DataFrame(records)


def generate_label_maturity_schedule(
    cutoffs: list[pd.Timestamp | str] | pd.DatetimeIndex | None = None,
    snapshots: pd.DataFrame | None = None,
    outcome_window_days: int = DEFAULT_OUTCOME_WINDOW_DAYS,
) -> pd.DataFrame:
    """Determine exactly which historical training cohorts are mature and leak-free at each scoring date.

    A snapshot cohort dated S can be used for training at scoring cutoff T only when its
    entire outcome window ending at S + 90d has completed by T:
    S + outcome_window_days <= T.

    Parameters
    ----------
    cutoffs : list or DatetimeIndex, optional
        Scoring cutoffs. Defaults to standard 16 monthly cutoffs.
    snapshots : pd.DataFrame, optional
        Customer snapshots table to quantify available training rows per cutoff.
    outcome_window_days : int
        Outcome window duration in days (default: 90).

    Returns
    -------
    pd.DataFrame
        Label maturity and model training availability schedule.
    """
    if cutoffs is None:
        cutoffs = get_monthly_cutoffs()

    cutoff_ts_list = [pd.Timestamp(c) for c in cutoffs]

    # Precompute cohort sizes if snapshots provided
    cohort_sizes = {}
    if snapshots is not None and not snapshots.empty:
        cohort_sizes = snapshots.groupby("cutoff_date").size().to_dict()

    records = []
    for t_score in cutoff_ts_list:
        score_str = t_score.strftime("%Y-%m-%d")
        # Identify mature cohorts
        mature_cohorts = [
            s for s in cutoff_ts_list if s + pd.Timedelta(days=outcome_window_days) <= t_score
        ]
        n_mature = len(mature_cohorts)
        latest_mature = mature_cohorts[-1].strftime("%Y-%m-%d") if mature_cohorts else "NONE"
        mature_dates_str = ", ".join([s.strftime("%Y-%m-%d") for s in mature_cohorts]) if mature_cohorts else "NONE"

        # Calculate training sample size if snapshots are provided
        train_rows = sum(cohort_sizes.get(s.strftime("%Y-%m-%d"), 0) for s in mature_cohorts)

        # Days between scoring date and outcome completion of latest mature cohort
        lag_days = (
            (t_score - (mature_cohorts[-1] + pd.Timedelta(days=outcome_window_days))).days
            if mature_cohorts
            else None
        )

        records.append({
            "scoring_cutoff_date": score_str,
            "mature_training_cohorts_count": n_mature,
            "latest_mature_cohort_date": latest_mature,
            "days_since_latest_cohort_matured": lag_days,
            "cumulative_training_records": train_rows,
            "mature_cohort_dates": mature_dates_str,
            "training_ready": n_mature > 0,
        })

    return pd.DataFrame(records)


def export_snapshot_pipeline(
    transactions: pd.DataFrame,
    output_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Execute complete customer snapshot pipeline and export authoritative artifacts.

    Parameters
    ----------
    transactions : pd.DataFrame
        Primary deduplicated transaction ledger (Specification B).
    output_dir : Path | str | None
        Destination directory for processed artifacts. Defaults to data/processed.

    Returns
    -------
    dict[str, Any]
        Dictionary of generated artifact paths, summary counts, and validation metrics.
    """
    dest_dir = Path(output_dir).resolve() if output_dir is not None else PROCESSED_DATA_DIR
    dest_dir.mkdir(parents=True, exist_ok=True)

    # 1. Generate full customer snapshots across 16 cutoffs
    logger.info("Executing customer snapshot generation...")
    cutoffs = get_monthly_cutoffs()
    snapshots = generate_customer_snapshots(transactions, cutoffs=cutoffs)

    snapshots_file = dest_dir / "customer_snapshots.parquet"
    logger.info("Exporting customer snapshots to %s...", snapshots_file)
    snapshots.to_parquet(snapshots_file, index=False, engine="pyarrow")

    # 2. Generate cohort summary metrics
    logger.info("Generating snapshot cohort metrics...")
    cohort_metrics = generate_snapshot_cohort_metrics(snapshots)
    cohort_metrics_file = dest_dir / "snapshot_cohort_metrics.csv"
    logger.info("Exporting cohort metrics to %s...", cohort_metrics_file)
    cohort_metrics.to_csv(cohort_metrics_file, index=False)

    # 3. Generate label maturity schedule
    logger.info("Generating label maturity schedule...")
    maturity_schedule = generate_label_maturity_schedule(cutoffs, snapshots=snapshots)
    maturity_file = dest_dir / "label_maturity_schedule.csv"
    logger.info("Exporting maturity schedule to %s...", maturity_file)
    maturity_schedule.to_csv(maturity_file, index=False)

    return {
        "snapshots_parquet": snapshots_file,
        "cohort_metrics_csv": cohort_metrics_file,
        "maturity_schedule_csv": maturity_file,
        "total_snapshot_rows": len(snapshots),
        "cohort_count": len(cutoffs),
        "overall_lapse_prevalence_pct": round(float(snapshots["lapsed_90d"].mean() * 100.0), 2),
    }

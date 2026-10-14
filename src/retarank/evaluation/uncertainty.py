"""Customer-cluster bootstrap uncertainty and paired difference analysis for RetaRank."""
from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

from retarank.evaluation.policies import evaluate_policy_selection, score_policies

logger = logging.getLogger(__name__)


def compute_paired_policy_differences(
    policy_metrics_df: pd.DataFrame,
    baseline_policy: str = "Policy E (Risk-only)",
    target_policy: str = "Policy F (Combined Risk x Value)",
) -> pd.DataFrame:
    """Compute per-cutoff paired differences between target policy and baseline policy.

    Parameters
    ----------
    policy_metrics_df : pd.DataFrame
        Dataframe containing policy evaluation records per cutoff and capacity.
    baseline_policy : str
        Name of baseline policy (default: Policy E (Risk-only)).
    target_policy : str
        Name of target policy (default: Policy F (Combined Risk x Value)).

    Returns
    -------
    pd.DataFrame
        Paired difference metrics per cutoff and capacity.
    """
    base_df = policy_metrics_df[policy_metrics_df["policy_name"] == baseline_policy].copy()
    target_df = policy_metrics_df[policy_metrics_df["policy_name"] == target_policy].copy()

    merge_keys = ["cutoff_date", "capacity_pct"]
    merged = target_df.merge(base_df, on=merge_keys, suffixes=("_target", "_base"))

    merged["diff_exposure_capture"] = (
        merged["exposure_capture_target"] - merged["exposure_capture_base"]
    ).round(4)
    merged["diff_lapse_recall"] = (
        merged["lapse_recall_target"] - merged["lapse_recall_base"]
    ).round(4)
    merged["diff_lapse_precision"] = (
        merged["lapse_precision_target"] - merged["lapse_precision_base"]
    ).round(4)
    merged["diff_lapse_lift"] = (
        merged["lapse_lift_target"] - merged["lapse_lift_base"]
    ).round(4)

    output_cols = [
        "cutoff_date",
        "capacity_pct",
        "policy_target",
        "policy_base",
        "exposure_capture_target",
        "exposure_capture_base",
        "diff_exposure_capture",
        "lapse_recall_target",
        "lapse_recall_base",
        "diff_lapse_recall",
        "lapse_precision_target",
        "lapse_precision_base",
        "diff_lapse_precision",
    ]
    merged["policy_target"] = target_policy
    merged["policy_base"] = baseline_policy

    return merged[[c for c in output_cols if c in merged.columns]].sort_values(
        ["capacity_pct", "cutoff_date"]
    ).reset_index(drop=True)


def run_customer_cluster_bootstrap(
    predictions_df: pd.DataFrame,
    capacities: list[float] | None = None,
    n_bootstraps: int = 1000,
    random_seed: int = 42,
) -> pd.DataFrame:
    """Estimate sampling uncertainty for paired policy differences via customer-cluster bootstrap.

    Clustering accounts for repeated appearances of identical customers across monthly
    snapshots by resampling customer_id with replacement.

    Parameters
    ----------
    predictions_df : pd.DataFrame
        Evaluation predictions across cutoffs.
    capacities : list of float, optional
        Outreach capacities (default: [0.10, 0.20, 0.30]).
    n_bootstraps : int
        Number of bootstrap iterations (default: 1000).
    random_seed : int
        Random seed for reproducibility.

    Returns
    -------
    pd.DataFrame
        Uncertainty summary table with point estimates, bootstrap standard errors,
        and 95% confidence intervals.
    """
    if capacities is None:
        capacities = [0.10, 0.20, 0.30]

    df_scored = score_policies(predictions_df)
    unique_custs = np.array(df_scored["customer_id"].unique())
    n_unique = len(unique_custs)

    # Pre-index row indices by customer_id for fast lookup
    cust_to_indices = df_scored.groupby("customer_id").indices

    rng = np.random.default_rng(random_seed)

    # Pre-compute original point estimates per capacity
    point_estimates = {}
    for cap in capacities:
        cap_pct = int(cap * 100)
        # Evaluate Policy E and Policy F per cutoff and average
        diff_exp_list = []
        diff_rec_list = []
        diff_prec_list = []

        for cutoff, group in df_scored.groupby("cutoff_date"):
            res_e = evaluate_policy_selection(group, score_col="score_policy_e", capacity=cap)
            res_f = evaluate_policy_selection(group, score_col="score_policy_f", capacity=cap)
            diff_exp_list.append(res_f["exposure_capture"] - res_e["exposure_capture"])
            diff_rec_list.append(res_f["lapse_recall"] - res_e["lapse_recall"])
            diff_prec_list.append(res_f["lapse_precision"] - res_e["lapse_precision"])

        point_estimates[cap_pct] = {
            "diff_exposure_capture": float(np.mean(diff_exp_list)),
            "diff_lapse_recall": float(np.mean(diff_rec_list)),
            "diff_lapse_precision": float(np.mean(diff_prec_list)),
        }

    # Storage for bootstrap differences
    boot_diffs: dict[int, dict[str, list[float]]] = {
        int(cap * 100): {
            "diff_exposure_capture": [],
            "diff_lapse_recall": [],
            "diff_lapse_precision": [],
        }
        for cap in capacities
    }

    logger.info("Executing %d customer-cluster bootstrap iterations...", n_bootstraps)
    cutoffs = sorted(df_scored["cutoff_date"].unique())

    for b in range(n_bootstraps):
        sampled_custs = rng.choice(unique_custs, size=n_unique, replace=True)
        # Collect row indices
        sampled_indices = []
        for c in sampled_custs:
            if c in cust_to_indices:
                sampled_indices.extend(cust_to_indices[c])

        boot_df = df_scored.iloc[sampled_indices]

        # Group by cutoff and evaluate paired differences
        for cap in capacities:
            cap_pct = int(cap * 100)
            b_exp_diffs = []
            b_rec_diffs = []
            b_prec_diffs = []

            for cutoff in cutoffs:
                c_df = boot_df[boot_df["cutoff_date"] == cutoff]
                if len(c_df) == 0:
                    continue
                res_e = evaluate_policy_selection(c_df, score_col="score_policy_e", capacity=cap)
                res_f = evaluate_policy_selection(c_df, score_col="score_policy_f", capacity=cap)
                b_exp_diffs.append(res_f["exposure_capture"] - res_e["exposure_capture"])
                b_rec_diffs.append(res_f["lapse_recall"] - res_e["lapse_recall"])
                b_prec_diffs.append(res_f["lapse_precision"] - res_e["lapse_precision"])

            if b_exp_diffs:
                boot_diffs[cap_pct]["diff_exposure_capture"].append(float(np.mean(b_exp_diffs)))
                boot_diffs[cap_pct]["diff_lapse_recall"].append(float(np.mean(b_rec_diffs)))
                boot_diffs[cap_pct]["diff_lapse_precision"].append(float(np.mean(b_prec_diffs)))

    # Assemble summary table
    summary_records = []
    for cap in capacities:
        cap_pct = int(cap * 100)
        for metric_name in ["diff_exposure_capture", "diff_lapse_recall", "diff_lapse_precision"]:
            arr = np.array(boot_diffs[cap_pct][metric_name])
            pt = point_estimates[cap_pct][metric_name]
            b_mean = float(np.mean(arr))
            b_se = float(np.std(arr, ddof=1))
            ci_lower = float(np.percentile(arr, 2.5))
            ci_upper = float(np.percentile(arr, 97.5))
            # p-value: proportion of bootstrap iterations with difference <= 0 (or >= 0 depending on hypothesized direction)
            p_val = float(np.mean(arr <= 0.0))

            summary_records.append({
                "comparison": "Policy F (Combined) vs Policy E (Risk-only)",
                "metric": metric_name,
                "capacity_pct": cap_pct,
                "point_estimate": round(pt, 4),
                "bootstrap_mean": round(b_mean, 4),
                "bootstrap_se": round(b_se, 4),
                "ci_95_lower": round(ci_lower, 4),
                "ci_95_upper": round(ci_upper, 4),
                "p_value_one_sided_le_zero": round(p_val, 4),
                "statistically_significant_05": bool(ci_lower > 0.0 or ci_upper < 0.0),
            })

    return pd.DataFrame(summary_records)

"""Evaluation module for RetaRank."""
from retarank.evaluation.metrics import compute_binary_metrics, compute_calibration_bins
from retarank.evaluation.policies import (
    POLICY_NAMES,
    compute_ranking_stability,
    evaluate_all_policies_on_cohort,
    evaluate_policy_selection,
    score_policies,
)
from retarank.evaluation.uncertainty import (
    compute_paired_policy_differences,
    run_customer_cluster_bootstrap,
)

__all__ = [
    "compute_binary_metrics",
    "compute_calibration_bins",
    "POLICY_NAMES",
    "score_policies",
    "evaluate_policy_selection",
    "evaluate_all_policies_on_cohort",
    "compute_ranking_stability",
    "compute_paired_policy_differences",
    "run_customer_cluster_bootstrap",
]

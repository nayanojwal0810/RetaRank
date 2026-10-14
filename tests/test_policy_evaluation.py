"""Unit tests for CRM prioritization policy ranking, metrics, stability, and bootstrap uncertainty."""
import numpy as np
import pandas as pd
import pytest

from retarank.evaluation.metrics import compute_binary_metrics
from retarank.evaluation.policies import (
    compute_ranking_stability,
    evaluate_all_policies_on_cohort,
    evaluate_policy_selection,
    score_policies,
)
from retarank.evaluation.uncertainty import (
    compute_paired_policy_differences,
    run_customer_cluster_bootstrap,
)


@pytest.fixture
def synthetic_policy_cohort() -> pd.DataFrame:
    """Create a 10-customer synthetic cohort with explicit scores and labels."""
    data = [
        # Customer 1: High risk (0.9), High value (500), Lapsed = 1
        {"customer_id": 1, "cutoff_date": "2011-03-01", "recency_days": 120.0, "purchase_invoice_count_180d": 1, "historical_net_spend_nonneg_180d": 500.0, "predicted_lapse_probability": 0.90, "lapsed_90d": 1},
        # Customer 2: High risk (0.85), Low value (20), Lapsed = 1
        {"customer_id": 2, "cutoff_date": "2011-03-01", "recency_days": 110.0, "purchase_invoice_count_180d": 1, "historical_net_spend_nonneg_180d": 20.0, "predicted_lapse_probability": 0.85, "lapsed_90d": 1},
        # Customer 3: Low risk (0.2), High value (1000), Retained = 0
        {"customer_id": 3, "cutoff_date": "2011-03-01", "recency_days": 10.0, "purchase_invoice_count_180d": 8, "historical_net_spend_nonneg_180d": 1000.0, "predicted_lapse_probability": 0.20, "lapsed_90d": 0},
        # Customer 4: Moderate risk (0.5), Moderate value (200), Lapsed = 1
        {"customer_id": 4, "cutoff_date": "2011-03-01", "recency_days": 60.0, "purchase_invoice_count_180d": 3, "historical_net_spend_nonneg_180d": 200.0, "predicted_lapse_probability": 0.50, "lapsed_90d": 1},
        # Customer 5: Low risk (0.1), Moderate value (300), Retained = 0
        {"customer_id": 5, "cutoff_date": "2011-03-01", "recency_days": 15.0, "purchase_invoice_count_180d": 5, "historical_net_spend_nonneg_180d": 300.0, "predicted_lapse_probability": 0.10, "lapsed_90d": 0},
        # Customer 6: Moderate risk (0.6), High value (800), Lapsed = 1
        {"customer_id": 6, "cutoff_date": "2011-03-01", "recency_days": 70.0, "purchase_invoice_count_180d": 2, "historical_net_spend_nonneg_180d": 800.0, "predicted_lapse_probability": 0.60, "lapsed_90d": 1},
        # Customer 7: High risk (0.7), Moderate value (100), Retained = 0
        {"customer_id": 7, "cutoff_date": "2011-03-01", "recency_days": 90.0, "purchase_invoice_count_180d": 2, "historical_net_spend_nonneg_180d": 100.0, "predicted_lapse_probability": 0.70, "lapsed_90d": 0},
        # Customer 8: Low risk (0.15), Low value (50), Retained = 0
        {"customer_id": 8, "cutoff_date": "2011-03-01", "recency_days": 20.0, "purchase_invoice_count_180d": 4, "historical_net_spend_nonneg_180d": 50.0, "predicted_lapse_probability": 0.15, "lapsed_90d": 0},
        # Customer 9: Moderate risk (0.4), Low value (30), Lapsed = 1
        {"customer_id": 9, "cutoff_date": "2011-03-01", "recency_days": 45.0, "purchase_invoice_count_180d": 2, "historical_net_spend_nonneg_180d": 30.0, "predicted_lapse_probability": 0.40, "lapsed_90d": 1},
        # Customer 10: Low risk (0.05), Moderate value (150), Retained = 0
        {"customer_id": 10, "cutoff_date": "2011-03-01", "recency_days": 5.0, "purchase_invoice_count_180d": 10, "historical_net_spend_nonneg_180d": 150.0, "predicted_lapse_probability": 0.05, "lapsed_90d": 0},
    ]
    return pd.DataFrame(data)


def test_score_policies_creates_expected_columns(synthetic_policy_cohort: pd.DataFrame) -> None:
    scored = score_policies(synthetic_policy_cohort)

    assert "score_policy_b" in scored.columns
    assert "score_policy_c" in scored.columns
    assert "score_policy_d" in scored.columns
    assert "score_policy_e" in scored.columns
    assert "score_policy_f" in scored.columns

    # Verify Policy F combined score = P(lapse) * net_spend
    # For customer 1: 0.90 * 500.0 = 450.0
    assert scored.loc[0, "score_policy_f"] == 450.0
    # For customer 6: 0.60 * 800.0 = 480.0
    assert scored.loc[5, "score_policy_f"] == 480.0


def test_evaluate_policy_selection_counts_and_exposure(synthetic_policy_cohort: pd.DataFrame) -> None:
    scored = score_policies(synthetic_policy_cohort)

    # Total lapsed customers: 5 (Customers 1, 2, 4, 6, 9)
    # Total lapsed spend: 500 + 20 + 200 + 800 + 30 = 1550.0
    # At capacity 20% (K = 2):
    # Under Policy F: Top 2 by score_policy_f are Customer 6 (480) and Customer 1 (450).
    # Both Customer 6 and Customer 1 lapsed!
    # Lapsed spend captured = 800 + 500 = 1300.0
    # Exposure capture = 1300 / 1550 = 0.8387 (83.87%)
    res_f = evaluate_policy_selection(scored, score_col="score_policy_f", capacity=0.20)
    assert res_f["n_eligible"] == 10
    assert res_f["n_selected"] == 2
    assert res_f["lapse_precision"] == 1.0  # 2 out of 2 lapsed
    assert res_f["lapse_recall"] == 0.40  # 2 out of 5 lapsed customers
    assert res_f["selected_lapsed_spend"] == 1300.0
    assert res_f["exposure_capture"] == round(1300.0 / 1550.0, 4)

    # Under Policy E (Risk-only): Top 2 by score_policy_e are Customer 1 (0.90) and Customer 2 (0.85).
    # Lapsed spend captured = 500 + 20 = 520.0
    # Exposure capture = 520 / 1550 = 0.3355 (33.55%)
    res_e = evaluate_policy_selection(scored, score_col="score_policy_e", capacity=0.20)
    assert res_e["lapse_precision"] == 1.0  # 2 out of 2 lapsed
    assert res_e["selected_lapsed_spend"] == 520.0
    assert res_e["exposure_capture"] == round(520.0 / 1550.0, 4)

    # Policy F captures significantly more exposure (83.87% vs 33.55%)!
    assert res_f["exposure_capture"] > res_e["exposure_capture"]


def test_random_baseline_reproducibility(synthetic_policy_cohort: pd.DataFrame) -> None:
    res1 = evaluate_policy_selection(synthetic_policy_cohort, score_col="random", capacity=0.20, random_seed=42)
    res2 = evaluate_policy_selection(synthetic_policy_cohort, score_col="random", capacity=0.20, random_seed=42)

    assert res1["lapse_precision"] == res2["lapse_precision"]
    assert res1["exposure_capture"] == res2["exposure_capture"]
    assert res1["lapse_precision_std"] > 0.0


def test_paired_differences_and_bootstrap_uncertainty(synthetic_policy_cohort: pd.DataFrame) -> None:
    df = synthetic_policy_cohort.copy()
    # Add second cutoff to test multi-cutoff bootstrap
    df2 = df.copy()
    df2["cutoff_date"] = "2011-04-01"
    multi_df = pd.concat([df, df2], ignore_index=True)

    boot_summary = run_customer_cluster_bootstrap(multi_df, capacities=[0.20], n_bootstraps=50, random_seed=42)
    assert not boot_summary.empty
    assert len(boot_summary) == 3  # diff_exposure_capture, diff_lapse_recall, diff_lapse_precision

    exp_row = boot_summary[boot_summary["metric"] == "diff_exposure_capture"].iloc[0]
    assert exp_row["point_estimate"] > 0.0
    assert exp_row["ci_95_upper"] >= exp_row["ci_95_lower"]


def test_ranking_stability_jaccard_bounded(synthetic_policy_cohort: pd.DataFrame) -> None:
    df1 = synthetic_policy_cohort.copy()
    df2 = synthetic_policy_cohort.copy()
    df2["cutoff_date"] = "2011-04-01"
    multi_df = pd.concat([df1, df2], ignore_index=True)

    stability = compute_ranking_stability(multi_df, capacity=0.20)
    assert not stability.empty
    assert (stability["jaccard_similarity"] >= 0.0).all()
    assert (stability["jaccard_similarity"] <= 1.0).all()

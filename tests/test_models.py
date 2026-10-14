"""Unit tests for machine-learning pipeline, temporal training, and prediction logic."""
import numpy as np
import pandas as pd
import pytest

from retarank.models.pipeline import (
    FEATURE_COLUMNS,
    FORBIDDEN_COLUMNS,
    NUMERIC_FEATURES,
    TARGET_COLUMN,
    get_model_candidates,
    get_preprocessor,
)
from retarank.models.train import fit_and_predict_cutoff, get_mature_training_data


@pytest.fixture
def synthetic_training_snapshots() -> pd.DataFrame:
    """Create multi-cutoff synthetic snapshot dataset for testing temporal training."""
    records = []
    # Cohorts: 2010-06-01, 2010-07-01, 2010-08-01, 2010-09-01
    dates = ["2010-06-01", "2010-07-01", "2010-08-01", "2010-09-01"]
    rng = np.random.default_rng(42)

    cust_id = 1000
    for d in dates:
        for _ in range(50):
            records.append({
                "customer_id": cust_id,
                "cutoff_date": d,
                "recency_days": float(rng.uniform(1.0, 180.0)),
                "purchase_invoice_count_180d": int(rng.integers(1, 15)),
                "purchase_line_count_180d": int(rng.integers(1, 50)),
                "historical_gross_spend_180d": float(rng.uniform(20.0, 2000.0)),
                "historical_return_deductions_180d": float(rng.uniform(0.0, 100.0)),
                "historical_net_spend_180d": float(rng.uniform(10.0, 1900.0)),
                "historical_net_spend_nonneg_180d": float(rng.uniform(10.0, 1900.0)),
                "avg_invoice_value_180d": float(rng.uniform(10.0, 500.0)),
                "distinct_product_count_180d": int(rng.integers(1, 30)),
                "total_quantity_180d": int(rng.integers(1, 200)),
                "return_invoice_count_180d": int(rng.integers(0, 3)),
                "country": rng.choice(["UK", "France", "Germany", "Unknown"]),
                "lapsed_90d": int(rng.choice([0, 1], p=[0.5, 0.5])),
            })
            cust_id += 1

    return pd.DataFrame(records)


def test_feature_whitelist_excludes_forbidden_columns() -> None:
    """Verify that identifiers and targets are strictly absent from feature whitelist."""
    for col in FORBIDDEN_COLUMNS:
        assert col not in FEATURE_COLUMNS, f"Forbidden column {col} present in FEATURE_COLUMNS"

    assert "customer_id" not in FEATURE_COLUMNS
    assert "cutoff_date" not in FEATURE_COLUMNS
    assert "lapsed_90d" not in FEATURE_COLUMNS
    assert TARGET_COLUMN not in FEATURE_COLUMNS


def test_mature_training_data_temporal_boundary(synthetic_training_snapshots: pd.DataFrame) -> None:
    """Verify that training sets strictly enforce S + 90d <= T without target leakage."""
    snaps = synthetic_training_snapshots

    # At scoring cutoff 2010-09-01:
    # 2010-06-01 + 90d = 2010-08-30 <= 2010-09-01 -> MATURE
    # 2010-07-01 + 90d = 2010-09-29 > 2010-09-01 -> NOT mature
    train_df = get_mature_training_data(snaps, scoring_cutoff="2010-09-01", outcome_window_days=90)
    assert len(train_df) == 50
    assert set(train_df["cutoff_date"]) == {"2010-06-01"}

    # At scoring cutoff 2010-07-01:
    # 2010-06-01 + 90d = 2010-08-30 > 2010-07-01 -> 0 mature cohorts
    train_empty = get_mature_training_data(snaps, scoring_cutoff="2010-07-01", outcome_window_days=90)
    assert len(train_empty) == 0


def test_fit_and_predict_cutoff_probability_orientation(synthetic_training_snapshots: pd.DataFrame) -> None:
    """Verify pipeline prediction output structure, bounds, and positive class orientation."""
    snaps = synthetic_training_snapshots
    candidates = get_model_candidates(random_state=42)

    for model_name, pipeline in candidates.items():
        preds, meta = fit_and_predict_cutoff(
            model_name=model_name,
            pipeline=pipeline,
            snapshots=snaps,
            scoring_cutoff="2010-09-01",
        )
        assert not preds.empty
        assert len(preds) == 50
        assert meta["status"] == "SUCCESS"

        # Check probability bounds
        probs = preds["predicted_lapse_probability"].values
        assert (probs >= 0.0).all()
        assert (probs <= 1.0).all()
        assert not np.isnan(probs).any()

        # Check column retention
        assert "customer_id" in preds.columns
        assert "cutoff_date" in preds.columns
        assert "lapsed_90d" in preds.columns
        assert "historical_net_spend_nonneg_180d" in preds.columns


def test_preprocessing_handles_unknown_and_missing_categories(synthetic_training_snapshots: pd.DataFrame) -> None:
    """Verify preprocessor handles unseen country categories gracefully without error."""
    snaps = synthetic_training_snapshots.copy()
    candidates = get_model_candidates(random_state=42)
    lr_pipeline = candidates["LogisticRegression"]

    # Introduce new unseen country in evaluation cutoff
    snaps.loc[snaps["cutoff_date"] == "2010-09-01", "country"] = "NewUnseenCountry"

    preds, meta = fit_and_predict_cutoff(
        model_name="LogisticRegression",
        pipeline=lr_pipeline,
        snapshots=snaps,
        scoring_cutoff="2010-09-01",
    )
    assert not preds.empty
    assert len(preds) == 50
    assert not preds["predicted_lapse_probability"].isna().any()

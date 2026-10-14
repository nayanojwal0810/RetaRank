"""Temporal training and out-of-time inference logic for RetaRank."""
from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd
from sklearn.pipeline import Pipeline

from retarank.models.pipeline import (
    FEATURE_COLUMNS,
    FORBIDDEN_COLUMNS,
    TARGET_COLUMN,
)

logger = logging.getLogger(__name__)


def get_mature_training_data(
    snapshots: pd.DataFrame,
    scoring_cutoff: str | pd.Timestamp,
    outcome_window_days: int = 90,
) -> pd.DataFrame:
    """Retrieve only historical customer snapshots whose full outcome window has matured.

    Temporal rule:
    training_cutoff + outcome_window_days <= scoring_cutoff

    Parameters
    ----------
    snapshots : pd.DataFrame
        Complete customer snapshots dataset.
    scoring_cutoff : str | pd.Timestamp
        Scoring date T.
    outcome_window_days : int
        Duration of the outcome observation window (default: 90).

    Returns
    -------
    pd.DataFrame
        Matured training subset strictly preceding scoring_cutoff without leakage.
    """
    t_score = pd.Timestamp(scoring_cutoff)

    # Ensure snapshot cutoffs are converted to timestamps for date arithmetic
    cutoff_ts = pd.to_datetime(snapshots["cutoff_date"])
    mature_mask = (cutoff_ts + pd.Timedelta(days=outcome_window_days)) <= t_score

    train_df = snapshots[mature_mask].copy()

    # Hard leakage assertion
    if not train_df.empty:
        max_train_cutoff = pd.to_datetime(train_df["cutoff_date"]).max()
        assert (max_train_cutoff + pd.Timedelta(days=outcome_window_days)) <= t_score, (
            f"Target leakage detected: latest training cutoff {max_train_cutoff} "
            f"matures after scoring date {t_score}"
        )

    return train_df


def fit_and_predict_cutoff(
    model_name: str,
    pipeline: Pipeline,
    snapshots: pd.DataFrame,
    scoring_cutoff: str | pd.Timestamp,
    outcome_window_days: int = 90,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Train pipeline on all matured historical cohorts and predict current cutoff.

    Parameters
    ----------
    model_name : str
        Name identifier of candidate model.
    pipeline : Pipeline
        Scikit-learn pipeline instance.
    snapshots : pd.DataFrame
        Complete customer snapshots dataset.
    scoring_cutoff : str | pd.Timestamp
        Current evaluation cutoff date.
    outcome_window_days : int
        Duration of outcome window (default: 90).

    Returns
    -------
    tuple[pd.DataFrame, dict[str, Any]]
        (Predictions dataframe for evaluation cohort, execution metadata dictionary)
    """
    cutoff_str = pd.Timestamp(scoring_cutoff).strftime("%Y-%m-%d")

    train_df = get_mature_training_data(
        snapshots,
        scoring_cutoff=cutoff_str,
        outcome_window_days=outcome_window_days,
    )

    eval_df = snapshots[snapshots["cutoff_date"] == cutoff_str].copy()
    if eval_df.empty:
        raise ValueError(f"Evaluation cohort for cutoff {cutoff_str} is empty.")

    if train_df.empty:
        logger.warning("No mature training cohorts available for cutoff %s", cutoff_str)
        return pd.DataFrame(), {
            "model_name": model_name,
            "scoring_cutoff": cutoff_str,
            "training_records": 0,
            "status": "NO_MATURE_TRAINING_DATA",
        }

    # Verify predictors
    for col in FORBIDDEN_COLUMNS:
        assert col not in FEATURE_COLUMNS, f"Forbidden column {col} in FEATURE_COLUMNS"

    X_train = train_df[FEATURE_COLUMNS]
    y_train = train_df[TARGET_COLUMN].values

    X_eval = eval_df[FEATURE_COLUMNS]
    y_eval = eval_df[TARGET_COLUMN].values

    # Fit pipeline
    pipeline.fit(X_train, y_train)

    # Predict probability of positive class (lapsed_90d = 1)
    # Scikit-learn classes_ array determines positive class index
    pos_idx = np.where(pipeline.classes_ == 1)[0]
    if len(pos_idx) == 0:
        # Fallback if class 1 was not observed (unlikely)
        prob_pos = np.zeros(len(eval_df), dtype=float)
    else:
        prob_pos = pipeline.predict_proba(X_eval)[:, pos_idx[0]]

    # Ensure probabilities are bounded in [0.0, 1.0]
    prob_pos = np.clip(prob_pos, 0.0, 1.0)

    # Construct clean prediction record
    preds_df = pd.DataFrame({
        "customer_id": eval_df["customer_id"].values,
        "cutoff_date": cutoff_str,
        "model_name": model_name,
        "predicted_lapse_probability": prob_pos,
        "lapsed_90d": y_eval,
        "historical_net_spend_180d": eval_df["historical_net_spend_180d"].values,
        "historical_net_spend_nonneg_180d": eval_df["historical_net_spend_nonneg_180d"].values,
        "recency_days": eval_df["recency_days"].values,
        "purchase_invoice_count_180d": eval_df["purchase_invoice_count_180d"].values,
    })

    metadata = {
        "model_name": model_name,
        "scoring_cutoff": cutoff_str,
        "training_records": len(train_df),
        "training_cohorts_count": train_df["cutoff_date"].nunique(),
        "training_lapse_prevalence": round(float(np.mean(y_train)), 4),
        "evaluation_records": len(eval_df),
        "evaluation_lapse_prevalence": round(float(np.mean(y_eval)), 4),
        "status": "SUCCESS",
    }

    return preds_df, metadata

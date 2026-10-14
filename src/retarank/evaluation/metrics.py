"""Predictive model performance and calibration metrics for RetaRank."""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score


def compute_binary_metrics(
    y_true: np.ndarray | list[int] | pd.Series,
    y_prob: np.ndarray | list[float] | pd.Series,
    capacities: list[float] | None = None,
) -> dict[str, float | None]:
    """Calculate discrimination, calibration, and top-K metrics for binary classification.

    Parameters
    ----------
    y_true : array-like
        Binary ground truth labels (0 or 1).
    y_prob : array-like
        Predicted positive class probabilities in [0.0, 1.0].
    capacities : list of float, optional
        Target population outreach proportions (default: [0.10, 0.20, 0.30]).

    Returns
    -------
    dict[str, float | None]
        Dictionary of performance metrics.
    """
    if capacities is None:
        capacities = [0.10, 0.20, 0.30]

    y_t = np.asarray(y_true).astype(int)
    y_p = np.asarray(y_prob).astype(float)
    n = len(y_t)

    if n == 0:
        return {}

    n_pos = int(np.sum(y_t == 1))
    prevalence = n_pos / n

    # ROC-AUC (requires both classes present)
    if n_pos > 0 and n_pos < n:
        roc_auc = float(roc_auc_score(y_t, y_p))
        avg_prec = float(average_precision_score(y_t, y_p))
    else:
        roc_auc = None
        avg_prec = None

    brier = float(brier_score_loss(y_t, y_p))

    # Rank indices descending by predicted probability (secondary stable index order)
    ranked_indices = np.lexsort((np.arange(n), -y_p))

    metrics: dict[str, float | None] = {
        "n_eval": n,
        "n_pos": n_pos,
        "prevalence": round(prevalence, 4),
        "roc_auc": round(roc_auc, 4) if roc_auc is not None else None,
        "average_precision": round(avg_prec, 4) if avg_prec is not None else None,
        "brier_score": round(brier, 4),
    }

    # Top-K metrics
    for cap in capacities:
        k = max(1, int(np.round(cap * n)))
        selected_idx = ranked_indices[:k]
        k_pos = int(np.sum(y_t[selected_idx] == 1))

        prec_k = k_pos / k
        recall_k = k_pos / n_pos if n_pos > 0 else 0.0
        lift_k = prec_k / prevalence if prevalence > 0 else 0.0

        cap_pct = int(cap * 100)
        metrics[f"precision@{cap_pct}pct"] = round(prec_k, 4)
        metrics[f"recall@{cap_pct}pct"] = round(recall_k, 4)
        metrics[f"lift@{cap_pct}pct"] = round(lift_k, 4)

    return metrics


def compute_calibration_bins(
    y_true: np.ndarray | pd.Series,
    y_prob: np.ndarray | pd.Series,
    n_bins: int = 10,
    model_name: str = "",
    cutoff_date: str = "",
) -> pd.DataFrame:
    """Produce binned reliability table for probability calibration inspection.

    Parameters
    ----------
    y_true : array-like
        Binary ground truth labels.
    y_prob : array-like
        Predicted probabilities.
    n_bins : int
        Number of equal-width probability bins (default: 10).
    model_name : str
        Model identifier.
    cutoff_date : str
        Cohort cutoff date.

    Returns
    -------
    pd.DataFrame
        Calibration summary per probability bin.
    """
    y_t = np.asarray(y_true).astype(int)
    y_p = np.asarray(y_prob).astype(float)

    bin_edges = np.linspace(0.0, 1.0, n_bins + 1)
    bin_indices = np.digitize(y_p, bin_edges, right=True)
    # Clip indices to [1, n_bins]
    bin_indices = np.clip(bin_indices, 1, n_bins)

    records = []
    for b in range(1, n_bins + 1):
        mask = bin_indices == b
        count = int(np.sum(mask))
        if count > 0:
            mean_pred = float(np.mean(y_p[mask]))
            obs_rate = float(np.mean(y_t[mask]))
        else:
            mean_pred = (bin_edges[b - 1] + bin_edges[b]) / 2.0
            obs_rate = 0.0

        records.append({
            "model_name": model_name,
            "cutoff_date": cutoff_date,
            "bin": b,
            "bin_lower": round(bin_edges[b - 1], 2),
            "bin_upper": round(bin_edges[b], 2),
            "sample_count": count,
            "mean_predicted_prob": round(mean_pred, 4),
            "observed_event_rate": round(obs_rate, 4),
            "calibration_error": round(abs(mean_pred - obs_rate), 4) if count > 0 else 0.0,
        })

    return pd.DataFrame(records)

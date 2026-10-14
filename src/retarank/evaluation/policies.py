"""CRM prioritization policy ranking, evaluation, and stability module for RetaRank."""
from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import rankdata

logger = logging.getLogger(__name__)

POLICY_NAMES = [
    "Policy A (Random)",
    "Policy B (Recency-only)",
    "Policy C (RFM Heuristic)",
    "Policy D (Value-only)",
    "Policy E (Risk-only)",
    "Policy F (Combined Risk x Value)",
]


def score_policies(cohort_df: pd.DataFrame) -> pd.DataFrame:
    """Calculate ranking scores for all six CRM prioritization policies on a single cohort.

    Parameters
    ----------
    cohort_df : pd.DataFrame
        Cohort dataframe with customer_id, recency_days, purchase_invoice_count_180d,
        historical_net_spend_180d, historical_net_spend_nonneg_180d, and predicted_lapse_probability.

    Returns
    -------
    pd.DataFrame
        Dataframe with policy priority score columns added.
    """
    df = cohort_df.copy()
    n = len(df)

    # 1. Policy B: Recency-only (higher recency = higher priority)
    df["score_policy_b"] = df["recency_days"].astype(float)

    # 2. Policy C: RFM-inspired heuristic
    # Normalized percentile ranks in [0, 1]:
    # Higher recency -> higher risk (ascending rank)
    r_rank = rankdata(df["recency_days"].values, method="average") / n
    # Lower frequency -> higher risk (descending frequency rank, i.e. rank(-frequency))
    f_rank = rankdata(-df["purchase_invoice_count_180d"].values, method="average") / n
    # Higher monetary value -> higher priority (ascending net spend rank)
    m_rank = rankdata(df["historical_net_spend_nonneg_180d"].values, method="average") / n
    df["score_policy_c"] = r_rank + f_rank + m_rank

    # 3. Policy D: Value-only (higher historical net spend = higher priority)
    df["score_policy_d"] = df["historical_net_spend_nonneg_180d"].astype(float)

    # 4. Policy E: Risk-only (higher predicted lapse probability = higher priority)
    df["score_policy_e"] = df["predicted_lapse_probability"].astype(float)

    # 5. Policy F: Combined risk x value
    df["score_policy_f"] = (
        df["predicted_lapse_probability"].astype(float)
        * df["historical_net_spend_nonneg_180d"].astype(float)
    )

    return df


def evaluate_policy_selection(
    cohort_df: pd.DataFrame,
    score_col: str,
    capacity: float = 0.10,
    random_simulations: int = 500,
    random_seed: int = 42,
) -> dict[str, Any]:
    """Evaluate performance of a prioritization policy at a specific contact capacity.

    Parameters
    ----------
    cohort_df : pd.DataFrame
        Cohort dataframe with ground truth labels and spend.
    score_col : str
        Name of score column, or 'random' for Policy A.
    capacity : float
        Outreach capacity fraction (e.g. 0.10, 0.20, 0.30).
    random_simulations : int
        Number of draws for random baseline (default: 500).
    random_seed : int
        Random seed for reproducibility.

    Returns
    -------
    dict[str, Any]
        Performance metrics dictionary.
    """
    n = len(cohort_df)
    k = max(1, int(np.round(capacity * n)))

    y_true = cohort_df["lapsed_90d"].values.astype(int)
    spend_weight = cohort_df["historical_net_spend_nonneg_180d"].values.astype(float)

    total_pos = int(np.sum(y_true == 1))
    prevalence = total_pos / n if n > 0 else 0.0

    # Total spend exposure of all lapsed customers in cohort (denominator)
    total_lapsed_spend_exposure = float(np.sum(spend_weight * (y_true == 1)))

    if score_col == "random":
        # Policy A: Simulate random draws
        rng = np.random.default_rng(random_seed)
        prec_list = []
        rec_list = []
        exp_list = []

        for _ in range(random_simulations):
            perm = rng.permutation(n)
            sel_idx = perm[:k]
            k_pos = np.sum(y_true[sel_idx] == 1)
            sel_exp = np.sum(spend_weight[sel_idx] * (y_true[sel_idx] == 1))

            prec_list.append(k_pos / k)
            rec_list.append(k_pos / total_pos if total_pos > 0 else 0.0)
            exp_list.append(sel_exp / total_lapsed_spend_exposure if total_lapsed_spend_exposure > 0 else 0.0)

        prec = float(np.mean(prec_list))
        prec_std = float(np.std(prec_list))
        rec = float(np.mean(rec_list))
        rec_std = float(np.std(rec_list))
        exp_cap = float(np.mean(exp_list))
        exp_cap_std = float(np.std(exp_list))
        lift = prec / prevalence if prevalence > 0 else 0.0

        return {
            "n_eligible": n,
            "n_selected": k,
            "capacity_pct": int(capacity * 100),
            "lapse_precision": round(prec, 4),
            "lapse_precision_std": round(prec_std, 4),
            "lapse_recall": round(rec, 4),
            "lapse_recall_std": round(rec_std, 4),
            "lapse_lift": round(lift, 4),
            "exposure_capture": round(exp_cap, 4),
            "exposure_capture_std": round(exp_cap_std, 4),
            "total_lapsed_spend_exposure": round(total_lapsed_spend_exposure, 2),
        }

    # Deterministic ranking: sort by score descending, then customer_id ascending for exact tie-breaking
    scores = cohort_df[score_col].values
    cust_ids = cohort_df["customer_id"].values

    # Lexsort: primary key is -scores, secondary key is cust_ids
    order = np.lexsort((cust_ids, -scores))
    selected_indices = order[:k]

    selected_y = y_true[selected_indices]
    selected_spend = spend_weight[selected_indices]

    k_pos = int(np.sum(selected_y == 1))
    prec = k_pos / k
    rec = k_pos / total_pos if total_pos > 0 else 0.0
    lift = prec / prevalence if prevalence > 0 else 0.0

    selected_lapsed_spend = float(np.sum(selected_spend * (selected_y == 1)))
    exp_cap = (
        selected_lapsed_spend / total_lapsed_spend_exposure
        if total_lapsed_spend_exposure > 0
        else 0.0
    )

    return {
        "n_eligible": n,
        "n_selected": k,
        "capacity_pct": int(capacity * 100),
        "lapse_precision": round(prec, 4),
        "lapse_precision_std": 0.0,
        "lapse_recall": round(rec, 4),
        "lapse_recall_std": 0.0,
        "lapse_lift": round(lift, 4),
        "exposure_capture": round(exp_cap, 4),
        "exposure_capture_std": 0.0,
        "total_lapsed_spend_exposure": round(total_lapsed_spend_exposure, 2),
        "selected_lapsed_spend": round(selected_lapsed_spend, 2),
    }


def evaluate_all_policies_on_cohort(
    cohort_df: pd.DataFrame,
    capacities: list[float] | None = None,
    random_seed: int = 42,
) -> list[dict[str, Any]]:
    """Evaluate all six CRM prioritization policies across all specified capacities.

    Parameters
    ----------
    cohort_df : pd.DataFrame
        Cohort dataframe with predictions and features.
    capacities : list of float, optional
        Outreach capacities (default: [0.10, 0.20, 0.30]).
    random_seed : int
        Seed for reproducibility.

    Returns
    -------
    list[dict[str, Any]]
        List of metric result records.
    """
    if capacities is None:
        capacities = [0.10, 0.20, 0.30]

    df_scored = score_policies(cohort_df)
    cutoff_date = str(cohort_df["cutoff_date"].iloc[0])

    policy_col_map = {
        "Policy A (Random)": "random",
        "Policy B (Recency-only)": "score_policy_b",
        "Policy C (RFM Heuristic)": "score_policy_c",
        "Policy D (Value-only)": "score_policy_d",
        "Policy E (Risk-only)": "score_policy_e",
        "Policy F (Combined Risk x Value)": "score_policy_f",
    }

    records = []
    for policy_name, col in policy_col_map.items():
        for cap in capacities:
            res = evaluate_policy_selection(
                cohort_df=df_scored,
                score_col=col,
                capacity=cap,
                random_seed=random_seed,
            )
            res["cutoff_date"] = cutoff_date
            res["policy_name"] = policy_name
            records.append(res)

    return records


def compute_ranking_stability(
    predictions_df: pd.DataFrame,
    capacity: float = 0.20,
) -> pd.DataFrame:
    """Measure ranking stability and top-K customer overlap across adjacent scoring cutoffs.

    Parameters
    ----------
    predictions_df : pd.DataFrame
        Multi-cutoff predictions dataframe.
    capacity : float
        Outreach capacity fraction (default: 0.20).

    Returns
    -------
    pd.DataFrame
        Stability metrics across adjacent cutoff pairs.
    """
    cutoffs = sorted(predictions_df["cutoff_date"].unique())
    records = []

    # Map policy names to score columns
    policy_map = {
        "Policy B (Recency-only)": "recency_days",
        "Policy D (Value-only)": "historical_net_spend_nonneg_180d",
        "Policy E (Risk-only)": "predicted_lapse_probability",
        "Policy F (Combined Risk x Value)": "combined_score",
    }

    df = predictions_df.copy()
    df["combined_score"] = df["predicted_lapse_probability"] * df["historical_net_spend_nonneg_180d"]

    for i in range(len(cutoffs) - 1):
        t1, t2 = cutoffs[i], cutoffs[i + 1]
        c1 = df[df["cutoff_date"] == t1]
        c2 = df[df["cutoff_date"] == t2]

        # Common customers eligible at both cutoffs
        common_custs = set(c1["customer_id"]).intersection(set(c2["customer_id"]))
        if len(common_custs) == 0:
            continue

        for pol_name, score_col in policy_map.items():
            k1 = max(1, int(np.round(capacity * len(c1))))
            k2 = max(1, int(np.round(capacity * len(c2))))

            top1 = set(c1.sort_values(by=[score_col, "customer_id"], ascending=[False, True]).head(k1)["customer_id"])
            top2 = set(c2.sort_values(by=[score_col, "customer_id"], ascending=[False, True]).head(k2)["customer_id"])

            overlap_count = len(top1.intersection(top2))
            union_count = len(top1.union(top2))
            jaccard = overlap_count / union_count if union_count > 0 else 0.0

            # Overlap among continuously eligible customers
            common_top1 = top1.intersection(common_custs)
            common_top2 = top2.intersection(common_custs)
            common_overlap = len(common_top1.intersection(common_top2))
            common_union = len(common_top1.union(common_top2))
            common_jaccard = common_overlap / common_union if common_union > 0 else 0.0

            records.append({
                "cutoff_t1": t1,
                "cutoff_t2": t2,
                "policy_name": pol_name,
                "capacity_pct": int(capacity * 100),
                "top_k_t1": k1,
                "top_k_t2": k2,
                "overlap_customers": overlap_count,
                "jaccard_similarity": round(jaccard, 4),
                "common_eligible_customers": len(common_custs),
                "common_overlap_customers": common_overlap,
                "common_jaccard_similarity": round(common_jaccard, 4),
            })

    return pd.DataFrame(records)

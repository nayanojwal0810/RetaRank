"""Model pipeline construction and candidate definitions for RetaRank."""
from __future__ import annotations

from typing import Any

from sklearn.compose import ColumnTransformer
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

# Explicit feature whitelist: strictly point-in-time features known at scoring cutoff
NUMERIC_FEATURES = [
    "recency_days",
    "purchase_invoice_count_180d",
    "purchase_line_count_180d",
    "historical_gross_spend_180d",
    "historical_return_deductions_180d",
    "historical_net_spend_180d",
    "avg_invoice_value_180d",
    "distinct_product_count_180d",
    "total_quantity_180d",
    "return_invoice_count_180d",
]

CATEGORICAL_FEATURES = [
    "country",
]

FEATURE_COLUMNS = NUMERIC_FEATURES + CATEGORICAL_FEATURES
TARGET_COLUMN = "lapsed_90d"
FORBIDDEN_COLUMNS = ["customer_id", "cutoff_date", TARGET_COLUMN, "historical_net_spend_nonneg_180d"]


def get_preprocessor(scale_numeric: bool = False) -> ColumnTransformer:
    """Build scikit-learn preprocessing ColumnTransformer.

    Parameters
    ----------
    scale_numeric : bool
        If True, applies StandardScaler to numeric features (required for LogisticRegression).

    Returns
    -------
    ColumnTransformer
        Configured preprocessor.
    """
    if scale_numeric:
        num_transformer = Pipeline(
            steps=[
                ("imputer", SimpleImputer(strategy="median")),
                ("scaler", StandardScaler()),
            ]
        )
    else:
        num_transformer = Pipeline(
            steps=[
                ("imputer", SimpleImputer(strategy="median")),
            ]
        )

    cat_transformer = Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="constant", fill_value="Unknown")),
            ("onehot", OneHotEncoder(handle_unknown="ignore", sparse_output=False)),
        ]
    )

    return ColumnTransformer(
        transformers=[
            ("num", num_transformer, NUMERIC_FEATURES),
            ("cat", cat_transformer, CATEGORICAL_FEATURES),
        ]
    )


def get_model_candidates(random_state: int = 42) -> dict[str, Pipeline]:
    """Return dictionary of configured model candidate pipelines.

    Parameters
    ----------
    random_state : int
        Deterministic random seed.

    Returns
    -------
    dict[str, Pipeline]
        Named candidate pipelines ready for fit/predict.
    """
    candidates = {
        "Dummy": Pipeline(
            steps=[
                ("preprocessor", get_preprocessor(scale_numeric=False)),
                ("classifier", DummyClassifier(strategy="prior")),
            ]
        ),
        "LogisticRegression": Pipeline(
            steps=[
                ("preprocessor", get_preprocessor(scale_numeric=True)),
                ("classifier", LogisticRegression(max_iter=1000, random_state=random_state, solver="lbfgs")),
            ]
        ),
        "RandomForest": Pipeline(
            steps=[
                ("preprocessor", get_preprocessor(scale_numeric=False)),
                ("classifier", RandomForestClassifier(n_estimators=100, max_depth=10, random_state=random_state, n_jobs=-1)),
            ]
        ),
        "HistGradientBoosting": Pipeline(
            steps=[
                ("preprocessor", get_preprocessor(scale_numeric=False)),
                ("classifier", HistGradientBoostingClassifier(max_iter=100, max_depth=6, random_state=random_state)),
            ]
        ),
    }
    return candidates

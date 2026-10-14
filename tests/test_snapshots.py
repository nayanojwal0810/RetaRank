"""Automated unit and integration tests for customer snapshot generation and label maturity."""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from retarank.config import PROCESSED_DATA_DIR
from retarank.data.snapshots import (
    generate_customer_snapshots,
    generate_label_maturity_schedule,
    generate_single_cutoff_snapshot,
    generate_snapshot_cohort_metrics,
    get_monthly_cutoffs,
)


@pytest.fixture
def synthetic_snapshot_ledger() -> pd.DataFrame:
    """Construct deterministic transaction ledger with known temporal and return characteristics.

    Scoring Cutoff: T = 2010-06-01 00:00:00
    Feature window: [2009-12-03 00:00:00, 2010-06-01 00:00:00)
    Outcome window: [2010-06-01 00:00:00, 2010-08-30 00:00:00)
    """
    rows = [
        # Customer 101: Retained customer (purchases in both feature and outcome windows)
        # Purchase 1 (in feature window): 2 items on same invoice -> 1 invoice event, 2 lines
        {"Invoice": "1001", "StockCode": "P1", "Description": "Prod 1", "Quantity": 2, "InvoiceDate": "2010-01-10 10:00:00", "Price": 10.0, "Customer ID": 101.0, "Country": "UK"},
        {"Invoice": "1001", "StockCode": "P2", "Description": "Prod 2", "Quantity": 1, "InvoiceDate": "2010-01-10 10:00:00", "Price": 20.0, "Customer ID": 101.0, "Country": "UK"},
        # Purchase 2 (in feature window, latest: 2010-05-01): 1 item
        {"Invoice": "1002", "StockCode": "P3", "Description": "Prod 3", "Quantity": 1, "InvoiceDate": "2010-05-01 12:00:00", "Price": 50.0, "Customer ID": 101.0, "Country": "UK"},
        # Return 1 (in feature window): -1 of P1 -> returns must not reset recency or count as purchase event
        {"Invoice": "C1003", "StockCode": "P1", "Description": "Prod 1 return", "Quantity": -1, "InvoiceDate": "2010-05-15 14:00:00", "Price": 10.0, "Customer ID": 101.0, "Country": "UK"},
        # Outcome purchase (in outcome window: 2010-07-01): keeps customer 101 retained (lapsed_90d = 0)
        {"Invoice": "1004", "StockCode": "P4", "Description": "Prod 4", "Quantity": 1, "InvoiceDate": "2010-07-01 11:00:00", "Price": 30.0, "Customer ID": 101.0, "Country": "UK"},

        # Customer 202: Lapsed customer (purchases in feature window, none in outcome window)
        # Purchase on exact start of feature window boundary (2009-12-03 00:00:00): should be included
        {"Invoice": "2001", "StockCode": "P1", "Description": "Prod 1", "Quantity": 4, "InvoiceDate": "2009-12-03 00:00:00", "Price": 25.0, "Customer ID": 202.0, "Country": "France"},
        # Outside outcome window (2010-09-15): too late for [T, T+90d) outcome window -> lapsed_90d = 1
        {"Invoice": "2002", "StockCode": "P2", "Description": "Prod 2", "Quantity": 1, "InvoiceDate": "2010-09-15 15:00:00", "Price": 40.0, "Customer ID": 202.0, "Country": "France"},

        # Customer 303: Boundary test customer
        # Purchase exactly at cutoff T (2010-06-01 00:00:00) -> MUST NOT BE IN HISTORICAL FEATURES!
        # It belongs to the outcome window!
        # Prior purchase for customer 303 in feature window:
        {"Invoice": "3001", "StockCode": "P5", "Description": "Prod 5", "Quantity": 1, "InvoiceDate": "2010-04-01 09:00:00", "Price": 15.0, "Customer ID": 303.0, "Country": "Germany"},
        {"Invoice": "3002", "StockCode": "P6", "Description": "Prod 6", "Quantity": 1, "InvoiceDate": "2010-06-01 00:00:00", "Price": 15.0, "Customer ID": 303.0, "Country": "Germany"},

        # Customer 404: Ineligible customer (only returns or transactions outside feature window)
        # Only purchase is 2009-11-01 (before 180d lookback window)
        {"Invoice": "4001", "StockCode": "P1", "Description": "Prod 1", "Quantity": 1, "InvoiceDate": "2009-11-01 10:00:00", "Price": 10.0, "Customer ID": 404.0, "Country": "UK"},
    ]

    df = pd.DataFrame(rows)
    df["parsed_invoice"] = df["Invoice"].astype(str).str.strip()
    df["parsed_stock_code"] = df["StockCode"].astype(str).str.strip()
    df["parsed_description"] = df["Description"].astype(str).str.strip()
    df["parsed_quantity"] = pd.to_numeric(df["Quantity"]).astype(np.int64)
    df["parsed_date"] = pd.to_datetime(df["InvoiceDate"])
    df["parsed_price"] = pd.to_numeric(df["Price"]).astype(np.float64)
    df["parsed_customer_id"] = pd.to_numeric(df["Customer ID"])
    df["parsed_country"] = df["Country"].astype(str).str.strip()
    df["raw_line_amount"] = df["parsed_quantity"] * df["parsed_price"]

    df["is_cancellation"] = df["parsed_invoice"].str.upper().str.startswith("C")
    df["has_customer_id"] = df["parsed_customer_id"].notna()

    # Classification rules
    is_pos_q = df["parsed_quantity"] > 0
    is_neg_q = df["parsed_quantity"] < 0
    is_pos_p = df["parsed_price"] > 0
    is_c = df["is_cancellation"]
    has_cust = df["has_customer_id"]
    is_admin = df["parsed_stock_code"].str.upper().isin({"POST", "M", "D", "BANK CHARGES"})

    df["is_valid_merchandise_purchase"] = is_pos_q & is_pos_p & (~is_c) & has_cust & (~is_admin)
    df["is_valid_customer_return"] = is_neg_q & is_pos_p & is_c & has_cust & (~is_admin)

    return df


def test_single_cutoff_eligibility_and_features(synthetic_snapshot_ledger: pd.DataFrame) -> None:
    ledger = synthetic_snapshot_ledger
    cutoff = "2010-06-01"
    snap = generate_single_cutoff_snapshot(ledger, cutoff_date=cutoff)

    # Eligible customers must be 101, 202, 303 (404 is outside the 180d window)
    assert len(snap) == 3
    assert set(snap["customer_id"]) == {101, 202, 303}

    # Inspect Customer 101
    c101 = snap[snap["customer_id"] == 101].iloc[0]
    # Invoices in feature window: 1001, 1002 -> exactly 2 distinct purchase invoices
    assert c101["purchase_invoice_count_180d"] == 2
    # Line items: 1001 (2 lines) + 1002 (1 line) -> exactly 3 lines
    assert c101["purchase_line_count_180d"] == 3
    # Gross spend: (2*10 + 1*20) + 1*50 = 40 + 50 = 90.0
    assert c101["historical_gross_spend_180d"] == 90.0
    # Return deduction: -1 * 10 = 10.0 deduction
    assert c101["historical_return_deductions_180d"] == 10.0
    # Net spend: 90 - 10 = 80.0
    assert c101["historical_net_spend_180d"] == 80.0
    # Average invoice value: 80.0 / 2 = 40.0
    assert c101["avg_invoice_value_180d"] == 40.0
    # Recency: Latest purchase was 2010-05-01 12:00:00 (Return on 2010-05-15 must NOT reset recency!)
    # Cutoff 2010-06-01 00:00:00 minus 2010-05-01 12:00:00 = 30.5 days
    assert c101["recency_days"] == 30.5
    # Outcome: Purchased on 2010-07-01 -> retained (lapsed_90d = 0)
    assert c101["lapsed_90d"] == 0

    # Inspect Customer 202
    c202 = snap[snap["customer_id"] == 202].iloc[0]
    # Gross spend: 4 * 25 = 100.0, 0 returns -> Net spend: 100.0
    assert c202["historical_net_spend_180d"] == 100.0
    # Outcome: Next purchase on 2010-09-15 is after outcome window (2010-08-30) -> lapsed_90d = 1
    assert c202["lapsed_90d"] == 1

    # Inspect Customer 303 (Boundary check)
    c303 = snap[snap["customer_id"] == 303].iloc[0]
    # Transaction on 2010-06-01 00:00:00 must NOT be counted in historical features
    # Only invoice 3001 (15.0) on 2010-04-01 is historical
    assert c303["purchase_invoice_count_180d"] == 1
    assert c303["historical_gross_spend_180d"] == 15.0
    # But transaction at 2010-06-01 IS in the outcome window -> retained (lapsed_90d = 0)
    assert c303["lapsed_90d"] == 0


def test_recency_strictly_positive_and_bounded(synthetic_snapshot_ledger: pd.DataFrame) -> None:
    ledger = synthetic_snapshot_ledger
    snap = generate_single_cutoff_snapshot(ledger, cutoff_date="2010-06-01")

    assert (snap["recency_days"] > 0).all()
    assert (snap["recency_days"] <= 180.0).all()


def test_deterministic_and_repeatable_generation(synthetic_snapshot_ledger: pd.DataFrame) -> None:
    ledger = synthetic_snapshot_ledger
    snap1 = generate_single_cutoff_snapshot(ledger, cutoff_date="2010-06-01")
    snap2 = generate_single_cutoff_snapshot(ledger, cutoff_date="2010-06-01")

    pd.testing.assert_frame_equal(snap1, snap2)


def test_label_maturity_schedule_correctness() -> None:
    cutoffs = get_monthly_cutoffs(start_date="2010-06-01", end_date="2010-10-01")
    sched = generate_label_maturity_schedule(cutoffs, outcome_window_days=90)

    assert len(sched) == 5
    # 2010-06-01: 0 mature
    assert sched.loc[0, "mature_training_cohorts_count"] == 0
    assert sched.loc[0, "training_ready"] is False or sched.loc[0, "training_ready"] == False

    # 2010-07-01: 0 mature (2010-06-01 + 90d = 2010-08-30 > 2010-07-01)
    assert sched.loc[1, "mature_training_cohorts_count"] == 0

    # 2010-08-01: 0 mature (2010-06-01 + 90d = 2010-08-30 > 2010-08-01)
    assert sched.loc[2, "mature_training_cohorts_count"] == 0

    # 2010-09-01: 1 mature cohort (2010-06-01)
    assert sched.loc[3, "mature_training_cohorts_count"] == 1
    assert sched.loc[3, "latest_mature_cohort_date"] == "2010-06-01"
    assert bool(sched.loc[3, "training_ready"]) is True

    # 2010-10-01: 2 mature cohorts (2010-06-01, 2010-07-01)
    assert sched.loc[4, "mature_training_cohorts_count"] == 2
    assert sched.loc[4, "latest_mature_cohort_date"] == "2010-07-01"


def test_cohort_metrics_aggregation(synthetic_snapshot_ledger: pd.DataFrame) -> None:
    ledger = synthetic_snapshot_ledger
    snap = generate_single_cutoff_snapshot(ledger, cutoff_date="2010-06-01")
    metrics = generate_snapshot_cohort_metrics(snap)

    assert len(metrics) == 1
    m = metrics.iloc[0]
    assert m["cutoff_date"] == "2010-06-01"
    assert m["eligible_customers"] == 3
    assert m["lapsed_customers"] == 1
    assert m["retained_customers"] == 2
    assert m["lapse_prevalence_pct"] == round(1 / 3 * 100, 2)


@pytest.mark.skipif(
    not (PROCESSED_DATA_DIR / "customer_snapshots.parquet").exists(),
    reason="Customer snapshots Parquet not present on disk",
)
def test_real_customer_snapshots_dataset_integrity() -> None:
    """Verify production customer snapshots dataset meets all architectural requirements."""
    snap_path = PROCESSED_DATA_DIR / "customer_snapshots.parquet"
    snapshots = pd.read_parquet(snap_path)

    # 1. Total row count matches 16 monthly cohorts (47,939)
    assert len(snapshots) == 47939

    # 2. Cutoff count
    assert snapshots["cutoff_date"].nunique() == 16
    assert snapshots["cutoff_date"].min() == "2010-06-01"
    assert snapshots["cutoff_date"].max() == "2011-09-01"

    # 3. Composite primary key uniqueness: 0 duplicates
    assert snapshots.duplicated(subset=["customer_id", "cutoff_date"]).sum() == 0

    # 4. Target variable integrity
    assert set(snapshots["lapsed_90d"].unique()) == {0, 1}
    overall_lapse = snapshots["lapsed_90d"].mean()
    assert 0.45 <= overall_lapse <= 0.55

    # 5. Temporal bounds: recency strictly within (0, 180] days
    assert (snapshots["recency_days"] > 0).all()
    assert (snapshots["recency_days"] <= 180.0).all()

    # 6. Purchase invoice count strictly >= 1
    assert (snapshots["purchase_invoice_count_180d"] >= 1).all()

    # 7. Gross spend strictly > 0
    assert (snapshots["historical_gross_spend_180d"] > 0).all()

    # 8. Return deductions strictly >= 0
    assert (snapshots["historical_return_deductions_180d"] >= 0).all()

    # 9. Verify label maturity schedule
    sched_path = PROCESSED_DATA_DIR / "label_maturity_schedule.csv"
    assert sched_path.exists()
    sched = pd.read_csv(sched_path)
    assert len(sched) == 16
    # Last cutoff 2011-09-01 must have 13 mature cohorts and 39,683 training records
    last_row = sched.iloc[-1]
    assert last_row["scoring_cutoff_date"] == "2011-09-01"
    assert last_row["mature_training_cohorts_count"] == 13
    assert last_row["cumulative_training_records"] == 39683

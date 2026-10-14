# RetaRank — End-to-End Implementation Plan

## 1. Purpose

Build a reproducible analytics workflow and professional Power BI decision-support dashboard that evaluates which customer-prioritization policy best serves a CRM team with limited outreach capacity.

### Proposed formal title

**RetaRank: Temporal Evaluation of Risk- and Value-Based Customer Prioritization for CRM Retention**

### Research question

Among identifiable retail customers with a valid purchase in the preceding 180 days, does combining predicted 90-day purchase-lapse risk with historical net spend improve top-10%, top-20% and top-30% CRM queue prioritization compared with risk-only, value-only, recency and conventional RFM rules, and are results stable across forward-in-time evaluation periods?

## 2. Scope and boundaries

In scope:
- Transaction data quality and accounting reconciliation.
- Point-in-time feature engineering and lapse-label construction.
- Temporal model selection and out-of-time evaluation.
- Equal-capacity benchmark of six CRM selection policies.
- Paired differences, uncertainty estimation and temporal ranking stability.
- Power BI dashboard with executive, policy, queue, temporal, model and methodology pages.
- Reproducible code, tests, data dictionary, report and presentation.

Out of scope for the core empirical claims:
- Proving a campaign prevents lapse.
- Causal uplift, incremental revenue, saved sales, profit or ROI.
- Treating model-generated or MiroFish-simulated responses as empirical customer evidence.
- Building a production CRM platform or automated campaign sender.

## 3. Data source

Use UCI Online Retail II: https://archive.ics.uci.edu/dataset/502/online+retail+ii

The workbook contains transaction-line data with invoice, stock code, description, quantity, invoice date, unit price, customer ID and country. Verify source metadata and licence at download time. Preserve attribution. Keep the original workbook outside Git; document its expected location and, if useful, a checksum.

## 4. Core definitions

For each cutoff timestamp T:
- Eligibility: at least one valid merchandise purchase in [T - 180 days, T).
- Feature window: [T - 180 days, T); end-exclusive at T.
- Outcome window: [T, T + 90 days); end-exclusive at T + 90 days.
- Lapse label = 1 if there are zero valid purchase events in the outcome window; otherwise 0.
- Historical value: net merchandise spend from information recorded before T, with purchases and applicable returns treated consistently.
- Ranking value weight: max(historical net spend, 0), documented as a policy choice where net spend is negative.

Purchase events must be based on valid purchase invoices/events, not raw transaction-line counts. Cancellations and returns do not count as purchase events. Monetary treatment of returns must be reconciled and explicitly defined. Do not use transactions occurring at or after T in historical features. For training, include an older snapshot only if its complete 90-day outcome window has matured by the scoring cutoff.

A 90-day no-purchase label is a defined behavioural outcome, not proof of permanent churn.

## 5. Work phases and acceptance gates

### Phase 0 — Repository and environment foundation
- Establish repository structure, README, implementation plan, dependency declaration, ignore rules and tests scaffold.
- Record supported Python version and reproducible commands.
- Keep data, local environments, model binaries and generated large files out of Git.
- Acceptance: fresh clone can create the environment and run a placeholder test suite.

### Phase 1 — Source data and data-quality audit
- Load workbook sheets; record row counts, date range, schema, missingness and data types.
- Quantify missing customer IDs, duplicate transaction lines, cancellations, negative quantities, zero/negative prices and invalid dates.
- Establish transaction accounting: positive eligible sales, return/cancellation deductions, net amount, and reconciliation residual.
- Compare exact-duplicate removal versus retention as a sensitivity analysis.
- Acceptance: data-quality tables are produced by scripts; money reconciliation passes a documented tolerance; every cleaning rule has a rationale and counts.

### Phase 2 — Point-in-time dataset construction
- Choose cutoff dates based on available data and the full 90-day forward horizon.
- Build one row per eligible customer per cutoff.
- Features: recency, distinct purchase-invoice frequency, historical net spend, average invoice value, purchase-gap features where enough history exists, product variety, and justified country/category features.
- Make all feature engineering point-in-time and deterministic.
- Construct labels from the entire future outcome window.
- Record cohort sizes and lapse prevalence by cutoff.
- Acceptance: automated checks prove features precede T, labels use the correct end-exclusive window, IDs and customer-cutoff keys are unique, and labels are only used once matured.

### Phase 3 — Temporal split and baseline
- Fix development, validation and final forward-in-time evaluation periods before comparing candidate models.
- Avoid random row-wise splits as the main evaluation approach.
- At evaluation cutoff T, training snapshots can be used only when their full label windows have matured by T.
- Avoid tuning repeatedly against the final holdout.
- Establish a baseline prediction and report base rate.
- Acceptance: split table documents cutoff dates, training maturity, validation and final evaluation use.

### Phase 4 — Prediction models
- Candidate models: Logistic Regression, Random Forest, and one gradient-boosting implementation supported by the chosen environment.
- Fit preprocessing, encoding, missing-value treatment and calibration inside training folds only.
- Use sensible class weighting only where justified and tune only on development/validation data.
- Metrics: ROC-AUC, PR-AUC, Brier score, calibration diagnostics, plus operational ranking metrics.
- Keep a simple model if complex models do not demonstrate a reliable gain.
- Save model parameters, random seeds, training cutoff information and predictions.
- Acceptance: results are reproducible and only out-of-time predictions enter policy evaluation.

### Phase 5 — Six CRM prioritization policies
1. Random baseline; use reproducible repeated draws and report average/distribution.
2. Recency-only: longer days since last purchase ranks higher.
3. Conventional RFM heuristic with a predeclared, transparent scoring formula.
4. Value-only: higher non-negative historical net spend ranks higher.
5. Risk-only: higher predicted lapse probability ranks higher.
6. Combined risk × value: predicted lapse probability multiplied by non-negative historical net spend.

All policies must rank the same eligible population within each cutoff. Define deterministic tie-breaking. Evaluate top 10%, 20% and 30% capacity with consistent rounding.

### Phase 6 — Policy metrics and inference
Primary monetary metric: share of pre-cutoff historical net-spend exposure associated with future lapsers captured by the selected queue. Define numerator and denominator explicitly and show when the denominator is zero.

Also report:
- Lapse Precision@K and Recall@K.
- Lift@K relative to overall lapse prevalence.
- Historical exposure captured among future-lapse customers, separate from lapse recall.
- Paired differences between policies at the same cutoff and capacity.
- Customer-cluster bootstrap intervals for repeated customer snapshots.
- Per-cutoff results and median/range, not only pooled averages.
- Ranking stability using top-K Jaccard overlap and rank correlation across cutoffs.

Interpret uncertainty carefully: customer-cluster bootstrap is conditional on evaluated calendar periods; it does not alone establish generalization to unseen time periods. Consider cutoff-level or temporal-block sensitivity where computationally reasonable.

### Phase 7 — Robustness and validation
- Lapse horizon sensitivity: 60, 90 and 120 days.
- Deduplication sensitivity: keep vs remove exact duplicates.
- Alternative reasonable RFM formula and policy tie-break sensitivity.
- Compare simpler and complex models.
- Report cutoff-level performance to expose seasonal or one-period dependence.
- Unit tests for window boundaries, returns, duplicates, aggregation, training maturity, top-K counts and metric calculations.
- Real-data integration tests for reconciliations and exported metrics.
- Acceptance: all primary claims trace to reproducible tables; limitations and failures are documented.

### Phase 8 — Power BI output model
Export stable, typed tables from Python rather than rerunning model logic in Power BI:
- `fact_customer_priority`: customer, cutoff, features, predicted risk, value weight, strategy score and rank.
- `fact_policy_metrics`: cutoff, policy, capacity, recall, precision, lift and historical exposure metrics.
- `fact_model_metrics`: cutoff/split/model and predictive/calibration metrics.
- `fact_stability_metrics`: cutoff pair, policy, capacity, overlap and rank stability.
- `dim_cutoff`, `dim_strategy`, and `data_quality_summary`.
Define a data dictionary and reconcile every output table against source calculations.

### Phase 9 — Power BI dashboard
Use a clean, consistent layout and a compact, legible palette. Suggested six pages:
1. Executive overview: population, base rate, selected capacity, policy result and clear caveats.
2. Policy benchmark: six-policy comparisons across capacities and metrics.
3. CRM priority queue: filterable/exportable ranked customer list.
4. Temporal performance: metrics by cutoff and ranking stability.
5. Model validation: ROC-AUC, PR-AUC, Brier/calibration, base rate and comparisons.
6. Customer profile and methodology: segment descriptions, field definitions, data quality and limitations.

Add useful slicers for cutoff, strategy and capacity; descriptive titles; metric definitions; report refresh/build information; and tooltips. Avoid decorative charts without a decision purpose. No result or headline should be hard-coded if it is meant to respond to slicers.

Acceptance:
- Power BI values reconcile to Python output tables.
- Filter and cross-highlight behaviour is tested.
- Empty denominators/missing cutoffs display transparently.
- Customer IDs and historical monetary value are labelled clearly.
- Dashboard never implies causal retention lift or realised ROI.

### Phase 10 — Final report and presentation
Include:
- Business problem, motivation and research question.
- Data source, licence attribution and cleaning decisions.
- Feature/target definitions and temporal validation design.
- Candidate model selection process.
- Strategy formulas, equal-capacity evaluation and uncertainty methodology.
- Results with uncertainty and per-cutoff evidence.
- Dashboard walkthrough and actionable but appropriately bounded CRM recommendations.
- Limitations, reproducibility instructions, and future work.
- A short presentation focused on decision, evidence, trade-offs and limitations.

Optional MiroFish extension only after core empirical work is complete. Clearly label any outputs as AI-generated scenario exploration, not actual customer evidence.

## 6. Repository layout

```text
RetaRank/
├── README.md
├── pyproject.toml or requirements.txt
├── .gitignore
├── data/
│   ├── raw/                 # not committed
│   ├── interim/             # generated, not committed
│   └── processed/           # generated, not committed
├── notebooks/
├── src/retarank/
│   ├── config.py
│   ├── data/
│   ├── features/
│   ├── models/
│   ├── evaluation/
│   └── reporting/
├── tests/
├── outputs/
│   ├── metrics/             # generated
│   ├── tables/              # generated
│   └── figures/             # generated
├── powerbi/
│   └── data/                # curated exports, as approved
└── docs/
    ├── implementation_plan.md
    ├── data_dictionary.md
    ├── methodology.md
    └── final_report.md
```

Adjust this structure to project needs, but keep modules small and testable. Avoid committing the raw workbook, virtual environments, secrets, cache files or bulky intermediate datasets.

## 7. Engineering standards

- Configurable paths and cutoff dates; no machine-specific absolute paths in application code.
- Deterministic seeds for models and random baselines.
- Logging of row counts, date bounds, exclusion rules and warnings.
- Tests for edge cases and metric definitions.
- No leakage from future records or evaluation outcomes.
- Typed, documented functions and reproducible commands.
- Small Git commits with meaningful messages.
- Never manufacture results. Clearly distinguish exploratory metrics from locked final evaluation results.

## 8. Completion criteria

RetaRank is presentation-ready only when the pipeline can run from documented inputs, the data accounting and point-in-time tests pass, all policies are compared on common cohorts/capacities, temporal and uncertainty results are reported, Power BI reconciles to Python, and the final report makes no unsupported causal or financial claims.

A strong grade or particular performance outcome cannot be guaranteed. The project will prioritise validity, reproducibility, meaningful business interpretation, and dashboard quality over chasing a particular metric.

# RetaRank

**Temporal, value-aware customer prioritization for CRM retention.**

RetaRank is a reproducible CRM analytics project that evaluates how customer purchase-lapse risk and historical customer value can guide outreach prioritization under limited contact capacity.

## Research question

Among identifiable retail customers with a valid purchase in the preceding 180 days, does combining predicted 90-day purchase-lapse risk with historical net spend improve top-10%, top-20% and top-30% CRM queue prioritization compared with risk-only, value-only, recency and conventional RFM rules, and are results stable across forward-in-time evaluation periods?

## Planned workflow

1. Clean and reconcile UCI Online Retail II transactions, cancellations and returns.
2. Create point-in-time customer snapshots with a 180-day feature window and 90-day outcome window.
3. Train and evaluate lapse-prediction models with leakage-safe temporal validation.
4. Compare six prioritization policies at 10%, 20% and 30% contact capacity.
5. Quantify ranking quality, historical spend exposure, uncertainty, and temporal stability.
6. Export curated data tables and build a professional Power BI dashboard.

## Scope boundaries

- This is a predictive CRM prioritization study, not a randomized campaign experiment.
- Historical spend exposure associated with a later lapse is **not** saved revenue, incremental revenue, profit, retention uplift or ROI.
- MiroFish is optional and out of scope for the core empirical analysis.
- Results will be reported only after reproducible evaluation; no performance figures are assumed in advance.

## Data source

UCI Machine Learning Repository, [Online Retail II](https://archive.ics.uci.edu/dataset/502/online+retail+ii). Review the source page and licence terms and retain attribution in project materials. Do not commit the raw workbook to Git.

## Current status

Project foundation created. Data pipeline, modelling, policy evaluation and dashboard are not yet implemented.

## Planned tools

Python, Pandas, NumPy, scikit-learn, SciPy, Jupyter, pytest, Git and Power BI Desktop.

## Development

See [docs/implementation_plan.md](docs/implementation_plan.md) for the complete milestone plan. Installation and exact run commands will be added with the first runnable pipeline.

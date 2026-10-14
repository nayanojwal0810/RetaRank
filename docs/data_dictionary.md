# RetaRank — Authoritative Data Dictionary

This document provides the definitive data dictionary for all processed transaction datasets, customer snapshot layers, and cohort tracking tables in RetaRank.

---

## 1. Processed Transaction Ledgers

**File Paths:**
- Primary Deduplicated (Specification B): `data/processed/transactions_primary.parquet` (1,033,036 rows)
- With Duplicates (Specification A): `data/processed/transactions_with_duplicates.parquet` (1,067,371 rows)

**Primary Key:** `source_row_id` (e.g. `Y0910:2`, `Y1011:541911`)

| Column Name | Data Type | Nullable | Business Definition / Logic |
|---|---|---|---|
| `source_row_id` | string | No | Provenance identifier: `SheetPrefix:ExcelRowNumber` |
| `sheet_name` | string | No | Source worksheet name (`Year 2009-2010` or `Year 2010-2011`) |
| `excel_row` | int64 | No | 1-indexed row number in the source worksheet |
| `Invoice` | string | No | Original raw invoice code from workbook |
| `StockCode` | string | No | Original raw inventory product/service code |
| `Description` | string | Yes | Item description |
| `Quantity` | int64 | No | Number of units purchased or returned |
| `InvoiceDate` | string | No | Raw timestamp string |
| `Price` | float64 | No | Unit sales price in GBP |
| `Customer ID` | float64 | Yes | Customer numerical identifier (NaN if guest checkout) |
| `Country` | string | No | Destination / billing country |
| `parsed_invoice` | string | No | Cleaned uppercase stripped invoice identifier |
| `parsed_stock_code` | string | No | Cleaned uppercase stripped stock code |
| `parsed_description` | string | Yes | Cleaned stripped product description |
| `parsed_quantity` | int64 | No | Standardized integer item quantity |
| `parsed_date` | timestamp | No | Parsed pandas datetime timestamp |
| `parsed_price` | float64 | No | Standardized unit price in GBP |
| `parsed_customer_id` | float64 | Yes | Cleaned numeric customer identifier |
| `parsed_country` | string | No | Standardized country string |
| `raw_line_amount` | float64 | No | Signed monetary value: `parsed_quantity * parsed_price` |
| `is_cancellation` | boolean | No | True if `parsed_invoice` begins with 'C' |
| `has_customer_id` | boolean | No | True if customer ID is non-null |
| `quantity_sign` | string | No | Categorical sign: `'positive'`, `'negative'`, `'zero'` |
| `price_sign` | string | No | Categorical sign: `'positive'`, `'negative'`, `'zero'` |
| `is_administrative` | boolean | No | True for administrative stock codes (`POST`, `D`, `M`, etc.) |
| `classification_category` | string | No | One of 12 mutually exclusive transaction categories |
| `is_valid_merchandise_purchase` | boolean | No | True for valid identified merchandise purchases ($Q>0, P>0, \neg C, \text{cust}, \neg\text{admin}$) |
| `is_valid_customer_return` | boolean | No | True for valid customer returns ($Q<0, P>0, C, \text{cust}, \neg\text{admin}$) |
| `is_duplicate_within_sheet` | boolean | No | True if identical 8-field duplicate within same worksheet |
| `is_duplicate_across_workbook` | boolean | No | True if duplicate across concatenated workbook (Specification B drop flag) |
| `is_cross_sheet_duplicate` | boolean | No | True if duplicate across worksheets (Sheet 2 copy of Sheet 1) |

---

## 2. Customer Snapshots Table

**File Path:** `data/processed/customer_snapshots.parquet` (47,939 rows)  
**Primary Key:** `(customer_id, cutoff_date)` — strictly unique (0 duplicates).  
**Eligibility Criterion:** Customer must have $\ge 1$ valid merchandise purchase invoice in $[T - 180\text{d}, T)$.

| Column Name | Data Type | Nullable | Business Definition / Logic |
|---|---|---|---|
| `customer_id` | int64 | No | Cleaned customer identifier |
| `cutoff_date` | string | No | Monthly scoring cutoff timestamp $T$ (`YYYY-MM-DD`) |
| `recency_days` | float64 | No | Days from most recent valid purchase in $[T-180\text{d}, T)$ to $T$; strictly in $(0, 180]$ |
| `purchase_invoice_count_180d` | int64 | No | Distinct valid merchandise purchase invoices in $[T-180\text{d}, T)$ |
| `purchase_line_count_180d` | int64 | No | Total valid merchandise transaction line items in $[T-180\text{d}, T)$ |
| `historical_gross_spend_180d` | float64 | No | Sum of valid merchandise purchase amounts in $[T-180\text{d}, T)$; strictly $> 0$ |
| `historical_return_deductions_180d` | float64 | No | Absolute sum of valid customer return amounts in $[T-180\text{d}, T)$; strictly $\ge 0$ |
| `historical_net_spend_180d` | float64 | No | `historical_gross_spend_180d - historical_return_deductions_180d` |
| `historical_net_spend_nonneg_180d` | float64 | No | `max(0.0, historical_net_spend_180d)` for rank-ordering priority score |
| `avg_invoice_value_180d` | float64 | No | Net spend per purchase invoice: `historical_net_spend_180d / purchase_invoice_count_180d` |
| `distinct_product_count_180d` | int64 | No | Count of distinct stock codes purchased in $[T-180\text{d}, T)$ |
| `total_quantity_180d` | int64 | No | Total quantity of units purchased in $[T-180\text{d}, T)$ |
| `return_invoice_count_180d` | int64 | No | Count of distinct return invoices in $[T-180\text{d}, T)$ |
| `country` | string | No | Customer modal billing country |
| `lapsed_90d` | int64 | No | Binary target: 1 if 0 purchases in $[T, T+90\text{d})$; 0 if $\ge 1$ purchase |

---

## 3. Snapshot Cohort Metrics Table

**File Path:** `data/processed/snapshot_cohort_metrics.csv` (16 rows)  
**Grain:** One row per monthly scoring cutoff date ($T$).

| Column Name | Data Type | Business Definition |
|---|---|---|
| `cutoff_date` | string | Scoring cutoff date (`YYYY-MM-DD`) |
| `eligible_customers` | int64 | Number of active customers with $\ge 1$ purchase in lookback |
| `lapsed_customers` | int64 | Eligible customers who made 0 purchases in 90-day outcome window |
| `retained_customers` | int64 | Eligible customers who made $\ge 1$ purchase in 90-day outcome window |
| `lapse_prevalence_pct` | float64 | Percentage of cohort that lapsed: `lapsed / eligible * 100` |
| `mean_recency_days` | float64 | Average recency across cohort customers at cutoff |
| `median_recency_days` | float64 | Median recency across cohort customers at cutoff |
| `mean_purchase_invoices_180d` | float64 | Average purchase invoice frequency per customer |
| `mean_historical_gross_spend_180d` | float64 | Average gross merchandise spend in 180 days |
| `mean_historical_return_deductions_180d` | float64 | Average return deductions in 180 days |
| `mean_historical_net_spend_180d` | float64 | Average net merchandise spend in 180 days |
| `median_historical_net_spend_180d` | float64 | Median net merchandise spend in 180 days |
| `total_historical_net_spend_180d` | float64 | Total net merchandise spend represented by cohort |
| `customers_with_returns_pct` | float64 | Proportion of eligible customers with $\ge 1$ return in lookback |

---

## 4. Label Maturity Schedule Table

**File Path:** `data/processed/label_maturity_schedule.csv` (16 rows)  
**Grain:** One row per scoring cutoff date ($T$).

| Column Name | Data Type | Business Definition |
|---|---|---|
| `scoring_cutoff_date` | string | Date when model scoring / prediction occurs ($T$) |
| `mature_training_cohorts_count` | int64 | Number of previous cohorts whose 90-day outcome window ended on or before $T$ |
| `latest_mature_cohort_date` | string | Most recent historical cohort available for leak-free training |
| `days_since_latest_cohort_matured` | float64 | Lag in days between scoring date and outcome completion of latest mature cohort |
| `cumulative_training_records` | int64 | Total customer snapshot training rows available without target leakage |
| `mature_cohort_dates` | string | Comma-delimited list of mature cohort dates |
| `training_ready` | boolean | True if $\ge 1$ mature cohort is available for model fitting |

# RetaRank — Source Data Audit Report (Phase 1)

**Audit Execution Date:** 2026-10-14  
**Auditor / Implementation Role:** Implementation Engineer  
**Workspace:** `D:\RetaRank`  
**Repository:** `https://github.com/nayanojwal0810/RetaRank`  
**Phase 1 Gate Decision:** **PASS** (Clear conditional protocols identified for Phase 2 data cleaning)

---

## 1. Executive Summary

A comprehensive source data audit was executed on the local UCI Online Retail II Excel workbook (`data/raw/online_retail_II.xlsx`). The dataset comprises two complete calendar-year worksheets (`Year 2009-2010` and `Year 2010-2011`) totaling **1,067,371 transaction-level rows** spanning from **2009-12-01 07:45:00 to 2011-12-09 12:50:00 UTC**.

Both worksheets exhibit an identical 8-column schema without unexpected columns or date parsing failures. Across both years, **5,942 distinct identified customers** and **53,628 distinct invoice numbers** are observed. An identifiable cohort of **2,813 repeat customers** bridges the two years, providing ample longitudinal transaction depth to support the intended 180-day lookback feature windows and 90-day purchase-lapse prediction horizons.

Crucial empirical accounting anomalies were quantified:
- **243,007 rows (22.77%)** have missing customer identifiers (anonymous retail store or guest purchases).
- **12,133 exact duplicate rows** exist across the worksheets.
- **19,494 cancellation-prefixed invoice lines** (`C...`) and **22,950 negative-quantity rows** were audited. The overlap analysis revealed **19,493 rows** that share both a negative quantity and a `C` prefix, while **3,457 negative quantity rows** lack a `C` prefix (representing inventory adjustments, damages, or un-prefixed returns), and **1 cancellation row** contains a positive quantity.
- **6,207 non-positive unit price rows** (6,202 zero prices and 5 negative prices) were detected.

All metrics are documented in structured CSV and JSON artifacts in `outputs/metrics/`, establishing an empirical baseline for Phase 2 data reconciliation.

---

## 2. Workbook Location and Worksheet Inventory

- **Workbook File Path:** `D:\RetaRank\data\raw\online_retail_II.xlsx`
- **File Size:** 45,622,278 bytes (~43.51 MB)
- **File Integrity:** Valid Microsoft Excel Workbook (ZIP/OpenXML structure, readable by `openpyxl`)
- **Worksheet Count:** 2

| Sheet Index | Sheet Name | Row Count | Column Count | Storage / Processing Note |
|---|---|---|---|---|
| 1 | `Year 2009-2010` | 525,461 | 8 | Audited sequentially; memory reclaimed post-profile |
| 2 | `Year 2010-2011` | 541,910 | 8 | Audited sequentially; memory reclaimed post-profile |
| **Combined** | **Total Inventory** | **1,067,371** | **8** | **Full 2-year longitudinal population** |

---

## 3. Observed Schema and Date Coverage

### Schema Consistency
Both worksheets contain identical column headers in matching sequence:

| Column Position | Column Name | Resolved Standard Role | Detected In-Memory Dtype | Description |
|---|---|---|---|---|
| 1 | `Invoice` | `invoice` | `object` (string) | 6-digit invoice number; prefixed with 'C' for cancellations |
| 2 | `StockCode` | `stock_code` | `object` (string) | 5-digit product code or alphanumeric service code |
| 3 | `Description` | `description` | `object` (string) | Nominal product name or administrative description |
| 4 | `Quantity` | `quantity` | `int64` | Multi-unit quantity purchased or returned |
| 5 | `InvoiceDate` | `invoice_date` | `datetime64[us]` | Invoice timestamp |
| 6 | `Price` | `price` | `float64` | Unit price in Sterling (£) |
| 7 | `Customer ID` | `customer_id` | `float64` | 5-digit unique customer identifier |
| 8 | `Country` | `country` | `object` (string) | Customer billing / shipping country |

### Date Coverage and Transition
- **Earliest Observed Timestamp:** `2009-12-01 07:45:00`
- **Latest Observed Timestamp:** `2011-12-09 12:50:00`
- **Total Calendar Span:** 738 days, 5 hours, 5 minutes (~24.3 months)
- **Date Parse Failures:** `0` (all 1,067,371 rows contain valid, parseable timestamps)

#### Per-Sheet Date Ranges:
- `Year 2009-2010`: `2009-12-01 07:45:00` to `2010-12-09 20:01:00`
- `Year 2010-2011`: `2010-12-01 08:26:00` to `2011-12-09 12:50:00`

> [!NOTE]
> **Inter-Sheet Calendar Overlap:** There is a 9-day temporal overlap between 2010-12-01 and 2010-12-09 present in both sheets, corresponding to 1,088 cross-sheet distinct invoice IDs. This overlap must be explicitly addressed during data ingestion in Phase 2 to prevent double-counting transactions recorded across both annual sheets.

---

## 4. Row Counts and Missingness

Detailed column missingness profile as exported to `outputs/metrics/source_missingness.csv`:

| Sheet Name | Column Name | Standard Role | Total Rows | Null Count | Null % | Distinct Values |
|---|---|---|---|---|---|---|
| `Year 2009-2010` | `Invoice` | `invoice` | 525,461 | 0 | 0.00% | 28,816 |
| `Year 2009-2010` | `StockCode` | `stock_code` | 525,461 | 0 | 0.00% | 4,632 |
| `Year 2009-2010` | `Description` | `description` | 525,461 | 2,928 | 0.56% | 4,682 |
| `Year 2009-2010` | `Quantity` | `quantity` | 525,461 | 0 | 0.00% | 825 |
| `Year 2009-2010` | `InvoiceDate` | `invoice_date` | 525,461 | 0 | 0.00% | 25,296 |
| `Year 2009-2010` | `Price` | `price` | 525,461 | 0 | 0.00% | 1,606 |
| `Year 2009-2010` | `Customer ID` | `customer_id` | 525,461 | 107,927 | 20.54% | 4,384 |
| `Year 2009-2010` | `Country` | `country` | 525,461 | 0 | 0.00% | 40 |
| `Year 2010-2011` | `Invoice` | `invoice` | 541,910 | 0 | 0.00% | 25,900 |
| `Year 2010-2011` | `StockCode` | `stock_code` | 541,910 | 0 | 0.00% | 4,070 |
| `Year 2010-2011` | `Description` | `description` | 541,910 | 1,454 | 0.27% | 4,224 |
| `Year 2010-2011` | `Quantity` | `quantity` | 541,910 | 0 | 0.00% | 722 |
| `Year 2010-2011` | `InvoiceDate` | `invoice_date` | 541,910 | 0 | 0.00% | 23,260 |
| `Year 2010-2011` | `Price` | `price` | 541,910 | 0 | 0.00% | 1,630 |
| `Year 2010-2011` | `Customer ID` | `customer_id` | 541,910 | 135,080 | 24.93% | 4,373 |
| `Year 2010-2011` | `Country` | `country` | 541,910 | 0 | 0.00% | 38 |
| **Combined** | **Customer ID** | `customer_id` | **1,067,371** | **243,007** | **22.77%** | **5,943 (incl. NaN)** |
| **Combined** | **Description** | `description` | **1,067,371** | **4,382** | **0.41%** | **5,700 (incl. NaN)** |

---

## 5. Duplicate, Cancellation, Quantity, Price, and Customer Diagnostics

Summary of worksheet-level diagnostic counts:

| Diagnostic Metric | `Year 2009-2010` | `Year 2010-2011` | Combined (All Sheets) |
|---|---|---|---|
| Total Row Count | 525,461 | 541,910 | 1,067,371 |
| Exact Duplicate Rows | 6,865 | 5,268 | 12,133 |
| Distinct Invoices | 28,816 | 25,900 | 53,628 |
| Distinct Customers (non-null) | 4,383 | 4,372 | 5,942 |
| Missing Customer IDs | 107,927 (20.54%) | 135,080 (24.93%) | 243,007 (22.77%) |
| Cancellation Invoices (`C...`) | 10,206 | 9,288 | 19,494 |
| Distinct Cancellation Invoices | 4,592 | 3,836 | 8,292 |
| Positive Quantities (`> 0`) | 513,135 | 531,286 | 1,044,421 |
| Negative Quantities (`< 0`) | 12,326 | 10,624 | 22,950 |
| Zero Quantities (`== 0`) | 0 | 0 | 0 |
| Positive Prices (`> 0`) | 521,771 | 539,393 | 1,061,164 |
| Zero Prices (`== 0`) | 3,687 | 2,515 | 6,202 |
| Negative Prices (`< 0`) | 3 | 2 | 5 |
| Total Nonpositive Prices (`<= 0`) | 3,690 | 2,517 | 6,207 |

### Cancellation and Quantity Overlap Analysis

A key data-quality objective is auditing the relationship between invoice cancellation flags and negative quantities to prevent double-deducting returns:

```
Total Negative Quantity Rows: 22,950
  ├── Negative Qty AND Cancellation Invoice ('C'): 19,493 (84.94%)
  └── Negative Qty AND Non-Cancellation Invoice:    3,457 (15.06%)

Total Cancellation Rows ('C'): 19,494
  ├── Cancellation Invoice AND Negative Qty:       19,493 (99.99%)
  └── Cancellation Invoice AND Positive Qty:            1 ( 0.01% - Anomaly in 09-10)
```

**Key Findings:**
1. **84.94%** of negative quantity rows carry an explicit `C` prefix.
2. **3,457 rows** represent negative quantities without a `C` prefix. Manual inspection reveals these correspond to inventory stock adjustments, damaged goods write-offs, warehouse losses, or un-prefixed returns.
3. Exactly **1 row** in `Year 2009-2010` has a `C` prefix with a positive quantity (an invoice cancellation correction line).

### Potential Positive Purchase Lines

| Category | `Year 2009-2010` | `Year 2010-2011` | Combined |
|---|---|---|---|
| Total Potential Positive Lines (`Qty > 0 & Price > 0`) | 511,566 | 530,105 | 1,041,671 |
| - With Identified Customer ID | 407,664 | 397,885 | 805,549 |
| - With Missing Customer ID | 103,902 | 132,220 | 236,122 |

---

## 6. Preliminary Arithmetic Totals and Interpretation Limits

> [!CAUTION]
> **Exploratory Accounting Diagnostics Only:**  
> The arithmetic sums below represent uncleaned, raw mathematical computations (`Quantity × Price`) across the source rows. They **MUST NOT** be interpreted as net revenue, realized revenue, gross margin, customer lifetime value, or business financial performance. Raw transactions include non-merchandise fees, manual balance adjustments, postage charges (`POST`), discounts, and unlinked guest transactions.

| Arithmetic Diagnostic Metric | `Year 2009-2010` | `Year 2010-2011` | Combined (All Sheets) |
|---|---|---|---|
| **Raw Line Arithmetic Sum** (`Σ Qty × Price`) | £9,539,484.63 | £9,747,765.93 | **£19,287,250.56** |
| Positive Lines Arithmetic Sum (`Qty > 0 & Price > 0`) | £10,306,265.59 | £10,666,702.54 | £20,972,968.13 |
| Negative Lines Arithmetic Sum (`Qty < 0`) | -£630,228.94 | -£896,812.49 | -£1,527,041.43 |
| Identified Customer Lines Sum (`Customer ID` not null) | £8,348,208.57 | £8,300,083.81 | £16,648,292.38 |
| Missing Customer Lines Sum (`Customer ID` null) | £1,191,276.06 | £1,447,682.12 | £2,638,958.18 |

---

## 7. Data-Quality Risks and Accounting Questions for Phase 2

1. **Risk 1: 9-Day Overlap Between Annual Worksheets**  
   - *Observation:* `Year 2009-2010` ends on `2010-12-09`, while `Year 2010-2011` starts on `2010-12-01`. 1,088 invoice IDs appear in both sheets.
   - *Phase 2 Resolution:* Perform deterministic deduplication across sheets during table ingestion before constructing the unified transaction log.

2. **Risk 2: Return Accounting & Overlap Discrepancy**  
   - *Observation:* 3,457 negative quantity rows lack a `C` invoice prefix. If cancellations and negative quantities are deducted independently without linking, returns would be double-counted or non-customer warehouse corrections would be wrongly imputed as customer returns.
   - *Phase 2 Resolution:* Establish an explicit return reconciliation rule: filter negative quantity lines into (a) valid customer return deductions linked to purchases/customers, and (b) administrative inventory write-offs to be excluded from customer spend.

3. **Risk 3: High Anonymous Volume (22.77%)**  
   - *Observation:* 243,007 rows lack `Customer ID`, representing £2.64M of preliminary gross positive arithmetic value.
   - *Phase 2 Resolution:* Since RetaRank evaluates longitudinal customer prioritization, transactions without customer IDs cannot be assigned to customer queues. Exclude anonymous transactions from customer-level scoring while auditing their volume in macro-level reconciliation tables.

4. **Risk 4: Non-Positive Unit Prices (6,207 rows)**  
   - *Observation:* 6,202 rows have `Price == 0.00` (e.g. promotional samples or inventory adjustments) and 5 rows have `Price < 0.00` (manual debt adjustments such as "Adjust bad debt").
   - *Phase 2 Resolution:* Remove lines with `Price <= 0` from commercial merchandise spend and transaction frequency metrics.

5. **Risk 5: Exact Duplicates (12,133 rows)**  
   - *Observation:* 12,133 exact duplicate lines exist across all columns.
   - *Phase 2 Resolution:* Implement deduplication sensitivity analysis (keeping vs removing exact duplicates) in Phase 2/Phase 7 to ensure model rankings and spend calculations are robust.

---

## 8. Tests and Commands Run

All commands were executed using the project's virtual environment (`D:\RetaRank\.venv\Scripts\python.exe`):

1. **Environment & Dependency Verification:**
   - Command: `python --version; pip list; pytest`
   - Result: Python 3.13.3 verified; editable package `retarank 0.1.0` loaded; initial configuration tests passed (1 passed).
2. **Pytest Unit & Integration Suite:**
   - Command: `pytest -v`
   - Tests run: 10 tests across `tests/test_audit.py` and `tests/test_config.py`
   - Results: **10 passed in 24.51s** (100% pass rate).
   - Tested modules: flexible column resolution, missingness calculation, non-destructive profiling, cancellation & quantity breakdown, unparseable dates, multi-sheet consolidation, unsupported file extension validation, and missing file error handling.
3. **Source Data Audit Script:**
   - Command: `python scripts/audit_source_data.py`
   - Result: Completed successfully in 191.22 seconds, generating verified metrics and output files.

---

## 9. Files Produced

| File Path | Description | Version Control Status |
|---|---|---|
| `src/retarank/data/audit.py` | Core audit and profiling module | Under Git tracking |
| `src/retarank/data/__init__.py` | Data module exports | Under Git tracking |
| `scripts/audit_source_data.py` | CLI audit execution script | Under Git tracking |
| `tests/test_audit.py` | Comprehensive audit test suite (10 tests) | Under Git tracking |
| `outputs/metrics/source_sheet_profile.csv` | Per-sheet and combined diagnostic profile | Excluded by `.gitignore` |
| `outputs/metrics/source_missingness.csv` | Column-level missingness and data types | Excluded by `.gitignore` |
| `outputs/metrics/source_data_audit.json` | Complete machine-readable audit report | Excluded by `.gitignore` |
| `docs/source_data_audit.md` | Formal human-readable Phase 1 audit report | Under Git tracking |
| `.gitignore` | Updated ignore rules (added `*.egg-info/`) | Under Git tracking |

---

## 10. Phase 1 Gate Decision

### **DECISION: PASS**

**Evidence:**
1. **Raw Source Verified:** `data/raw/online_retail_II.xlsx` was loaded, fully parsed across all worksheets, and verified to contain 1,067,371 rows with 0 date parse failures.
2. **Audit Pipeline Reproducible:** The CLI tool `python scripts/audit_source_data.py` and test suite `pytest` execute cleanly and deterministically.
3. **Data Integrity Characterized:** Customer identifiers, cancellation prefixes, negative quantities, non-positive prices, and inter-sheet overlaps have been quantified empirically without premature data mutation.
4. **Git Hygiene Preserved:** The 45.6 MB raw workbook, virtual environment, and generated metric artifacts remain strictly untracked by Git.

---

## 11. Exact Recommended Next Implementation Tasks (Phase 2)

1. **Reconciliation & Ingestion Pipeline (`src/retarank/data/clean.py`):**
   - Ingest both worksheets and resolve the 9-day cross-sheet overlap (`2010-12-01` to `2010-12-09`).
   - Implement clear business logic separating valid customer purchases, customer returns, and administrative warehouse adjustments.
2. **Transaction Deduplication Policy:**
   - Implement parameter-controlled exact duplicate removal and document duplicate sensitivity.
3. **Point-in-Time Snapshot Construction (`src/retarank/features/snapshot.py`):**
   - Define scoring cutoff dates $T$ adhering to [T - 180d, T) feature lookback and [T, T + 90d) outcome horizon.
   - Restrict modeling entities to identified customers with valid purchase history in the lookback window.
4. **Feature & Target Engineering:**
   - Formulate deterministic point-in-time features (recency, frequency, net spend) and binary 90-day lapse labels.

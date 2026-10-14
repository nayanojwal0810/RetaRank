# RetaRank — Transaction Cleaning and Reconciliation Policy

**Status:** Approved for Phase 2 Implementation  
**Auditor / Data Engineering Role:** Implementation Engineer  
**Workspace:** `D:\RetaRank`  
**Dataset:** UCI Online Retail II (`data/raw/online_retail_II.xlsx`)  
**Target Output Artifacts:**  
- `data/processed/transactions_primary.parquet` (Specification B)  
- `data/processed/transactions_with_duplicates.parquet` (Specification A)  

---

## 1. Executive Policy Overview

This document specifies the definitive transaction-accounting and data-cleaning conventions for RetaRank. In Phase 1 and Phase 2A, the raw transaction ledger comprising **1,067,371 rows** across two worksheets (`Year 2009-2010` and `Year 2010-2011`) was audited and reconciled. 

Empirical evidence revealed:
- An exact **22,523-row temporal duplication** where transactions between `2010-12-01` and `2010-12-09` were recorded in both worksheets.
- An additional **12,133 within-sheet exact duplicate rows** resulting from repeated scanner events or batch transmission duplicates.
- **243,007 rows (22.77%)** lacking `Customer ID` (anonymous in-store or guest transactions).
- **3,457 negative-quantity rows** lacking a cancellation prefix (`C`), all of which have `Price == 0.00` and no customer ID (internal warehouse adjustments, damages, and stock write-offs).
- **6,207 non-positive price rows**, including 5 bad-debt ledger balance adjustments (`Price < 0`).
- Special service and administrative stock codes (`POST`, `DOT`, `M`, `D`, `BANK CHARGES`, `CRUK`, `AMAZONFEE`, `B`).

To prevent distortion of customer-level CRM prioritization models while maintaining rigorous audit traceability, RetaRank establishes a dual-specification framework:
- **Specification B (Primary Standard):** Removes all 34,335 exact 8-field duplicates across the concatenated workbook, yielding a clean canonical ledger of **1,033,036 rows**.
- **Specification A (Sensitivity Baseline):** Retains all 1,067,371 source rows for sensitivity and robustness evaluations in Phase 7.

---

## 2. Core Operational Definitions

### 2.1 Valid Merchandise Purchase Event
A transaction line constitutes a **valid merchandise purchase event** if and only if it satisfies all of the following criteria:
1. **Identified Customer:** `Customer ID` is non-null (`has_customer_id == True`).
2. **Positive Commercial Quantity:** `Quantity > 0`.
3. **Positive Commercial Price:** `Price > 0.00`.
4. **Non-Cancellation Invoice:** `Invoice` does not begin with `'C'` or `'c'`.
5. **Commercial Merchandise Product:** `StockCode` represents physical merchandise goods, excluding administrative overhead, bad debt, postage, and marketplace fees (`is_administrative == False`).

> [!IMPORTANT]
> **Event Aggregation Rule:** Customer purchase frequency, recency, eligibility, and future lapse labels are computed at the **distinct invoice event level** within calendar windows, **not by raw transaction line count**. If a customer purchases 12 distinct product items on a single invoice, that order counts as **one valid purchase event**.

### 2.2 Gross Purchase Amount
The **gross purchase amount** is defined as the arithmetic sum of `Quantity × Price` across all valid merchandise purchase lines recorded within the feature lookback window $[T - 180\text{d}, T)$.

$$\text{Gross Purchase Amount} = \sum_{i \in \text{ValidPurchases}_{[T - 180\text{d}, T)}} (\text{Quantity}_i \times \text{Price}_i)$$

### 2.3 Return and Cancellation Treatment
1. **Valid Customer Return:** A transaction line is classified as a valid customer return deduction if:
   - `Quantity < 0` and `Price > 0.00`.
   - `Invoice` starts with `'C'` or `'c'` (cancellation prefix).
   - `Customer ID` is identified (non-null).
2. **Exclusion of Non-Customer Adjustments:** The 3,457 negative-quantity rows with `Price == 0.00` and missing customer IDs represent internal warehouse write-offs (e.g. `damaged`, `check`, `lost`). These rows **must never** be attributed to customer accounts or treated as customer return deductions.
3. **Non-Event Status:** Cancellation and return transactions **never** qualify as purchase events, **never** satisfy the 180-day customer eligibility rule, and **never** reset customer recency.
4. **Point-in-Time Constraint:** Only return lines occurring strictly before the cutoff timestamp $T$ ($\text{InvoiceDate} < T$) may enter historical net spend calculations. Future returns occurring at or after $T$ **must never** be retroactively deducted from historical features.

### 2.4 Historical Net Spend
**Historical Net Spend** in the 180-day lookback window $[T - 180\text{d}, T)$ is defined as:

$$\text{Historical Net Spend}_{180\text{d}} = \text{Gross Purchase Amount}_{180\text{d}} - \sum_{j \in \text{ValidReturns}_{[T - 180\text{d}, T)}} (|\text{Quantity}_j| \times \text{Price}_j)$$

For value-based customer prioritization policies (Policies 4 and 6), the ranking weight is constrained to non-negative values:

$$\text{Ranking Value Weight} = \max\left(\text{Historical Net Spend}_{180\text{d}}, 0\right)$$

Any eligible customer whose net spend is non-positive due to extensive returns is assigned a value weight of £0.00, ensuring risk-based rankings remain bounded.

---

## 3. Treatment of Special Categories

### 3.1 Administrative, Service, and Financial Stock Codes

| Stock Code | Typical Description | Row Count | Signed Value Sum | Cleaning Policy & Rationale |
|---|---|---|---|---|
| `POST` | `POSTAGE` | 2,122 | +£112,341.00 | **Excluded from purchase frequency; tracked in order value.** Postage is shipping overhead, not retail merchandise. |
| `DOT` | `DOTCOM POSTAGE` | 1,446 | +£322,647.47 | **Excluded from customer features.** Internal ecommerce shipping line; predominantly anonymous (no customer ID). |
| `M` | `Manual` | 1,421 | -£82,796.32 | **Excluded from merchandise frequency.** Arbitrary price adjustments, corrections, and ledger credits. |
| `D` | `Discount` | 177 | -£13,484.54 | **Treated as invoice deduction.** Trade and promotional discount concessions. |
| `BANK CHARGES` | `Bank Charges` | 67 | -£7,015.37 | **Excluded.** Banking transaction fees, not retail sales. |
| `AMAZONFEE` | `AMAZON FEE` | 43 | -£260,763.58 | **Excluded.** Marketplace platform commission charges. |
| `B` | `Adjust bad debt` | 6 | -£147,614.08 | **Excluded.** Financial ledger bad-debt write-offs (`Price < 0`). |
| `CRUK` | `CRUK Commission` | 16 | -£7,933.43 | **Excluded.** Charitable commission contributions. |
| `ADJUST` | `Adjustment by john` | 67 | +£6,835.24 | **Excluded.** Manual database administration entries. |

### 3.2 Non-Positive Prices (6,207 rows)
- **Zero Price (`Price == 0.00`, 6,202 rows):** Excluded from commercial purchase frequency and monetary spend. Consists of 3,457 damaged inventory adjustments, promotional samples, and stock audits.
- **Negative Price (`Price < 0.00`, 5 rows):** Excluded from customer purchase features. All correspond to manual ledger bad debt balance write-offs.

### 3.3 Anonymous Transactions (243,007 rows)
- **Customer ID Missing:** 22.77% of raw transactions cannot be tracked longitudinally to an individual account.
- **Policy:** Excluded from customer snapshot tables, lapse prediction, and CRM prioritization. Retained in macro-level reconciliation tables to guarantee total retail accounting transparency.

---

## 4. Deduplication Specification Decision

| Specification | Concatenated Rows | Filter Description | Primary Rationale |
|---|---|---|---|
| **Specification B (Primary)** | **1,033,036** | Remove 34,335 exact 8-field duplicates across concatenated ledger | **Selected as Primary.** Resolves the 22,523 rows duplicated across both annual sheets between Dec 1-9, 2010. Retains 100% of distinct customers (5,942), distinct invoices (53,628), and distinct purchase events (40,077). |
| **Specification A (Sensitivity)** | **1,067,371** | Retain all source rows, including all duplicates | **Retained for Phase 7 Robustness.** Used to evaluate whether duplicate removal alters model ranking stability or policy lift. |

---

## 5. Summary of Downstream Feature Rules for Phase 2B

1. **Cohort Eligibility at Cutoff $T$:** Customer must have at least one valid merchandise purchase invoice in $[T - 180\text{d}, T)$.
2. **Outcome Target ($\text{Lapse}_{90\text{d}}$):** Equals 1 if customer has zero valid merchandise purchase invoices in $[T, T + 90\text{d})$; else 0.
3. **Temporal Partitioning:** All features use strictly $t < T$; all labels use $T \le t < T + 90\text{d}$. No transaction crossing $T$ may contaminate historical metrics.

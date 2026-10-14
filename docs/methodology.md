# RetaRank — Data Pipeline and Customer Snapshot Methodology

## 1. Executive Overview and Research Objective

**Project Title:** RetaRank: Temporal Evaluation of Risk- and Value-Based Customer Prioritization for CRM Retention  
**Primary Dataset:** UCI Online Retail II (`data/raw/online_retail_II.xlsx`)  
**Target Entity Grain:** Point-in-time customer snapshot (`customer_id × cutoff_date`)  

The primary objective of RetaRank is to evaluate whether combining out-of-time purchase lapse risk with documented historical monetary spend improves customer selection under constrained marketing outreach capacity. This document formalizes the authoritative transaction preparation pipeline, point-in-time snapshot extraction rules, label definitions, and training maturity constraints.

---

## 2. Source Provenance and Deduplication Policy

### 2.1 Workbook Structure
The source workbook comprises two consecutive annual worksheets:
- `Year 2009-2010`: 525,461 raw rows (2009-12-01 to 2010-12-09).
- `Year 2010-2011`: 541,910 raw rows (2010-12-01 to 2011-12-09).
- **Concatenated Raw Total:** 1,067,371 rows.

Every row in the canonical ledger is assigned an immutable composite identifier:
$$\text{source\_row\_id} = \text{SheetNamePrefix} : \text{ExcelRowNumber}$$
guaranteeing 100% auditability back to the original Excel grid.

### 2.2 Duplication Analysis
Duplication in the workbook occurs at two levels:
1. **Within-Sheet Duplicates:** 12,133 exact full-row duplicates across all 8 source fields (4,908 in Sheet 1, 7,225 in Sheet 2).
2. **Cross-Sheet Overlap Window:** A 9-day overlapping period exists between `2010-12-01 08:32:00` and `2010-12-09 20:01:00`. Within this window:
   - 1,088 invoice IDs appear in both worksheets.
   - Sheet 2 contains 22,523 rows within this shared period; every one of these rows matches a row in Sheet 1 across all 8 fields.
   - Accounting for 321 duplicates already counted within Sheet 2, there are exactly **22,202 additional cross-sheet duplicates**.

### 2.3 Authoritative Specifications
- **Specification B (Primary Clean Ledger):** Deduplicated primary layer removing all 34,335 exact duplicates ($12,133 + 22,202$), yielding **1,033,036 rows**.
- **Specification A (Sensitivity Ledger):** Retains all 1,067,371 raw rows for robustness and sensitivity evaluation.

#### Deduplication Invariance Proof
Removing exact duplicates eliminates £431,716.87 of redundant transaction amounts while preserving **100% of underlying business entities**:
- Distinct customers: 5,942 (both Spec A and Spec B; difference = 0).
- Distinct invoices: 53,628 (both Spec A and Spec B; difference = 0).
- Storewide commercial positive invoices: 40,077 (both Spec A and Spec B; difference = 0).
- Distinct invoices with valid merchandise: 36,613 (both Spec A and Spec B; difference = 0).
- Valid purchase customers: 5,853 (both Spec A and Spec B; difference = 0).
- Distinct customer return invoices: 7,290 (both Spec A and Spec B; difference = 0).

---

## 3. Transaction Taxonomy and Business Logic

Every transaction row is partitioned into exactly one of 12 mutually exclusive, exhaustive classification categories:

| Category | Definition / Rule | Spec A Rows | Spec B Rows |
|---|---|---|---|
| `PURCHASE_IDENTIFIED_MERCHANDISE` | $Q > 0, P > 0, \neg C, \text{CustomerID present}, \neg \text{Admin}$ | 802,900 | 776,840 |
| `PURCHASE_ANONYMOUS_MERCHANDISE` | $Q > 0, P > 0, \neg C, \text{CustomerID missing}, \neg \text{Admin}$ | 234,469 | 229,881 |
| `CANCELLATION_RETURN_IDENTIFIED` | $Q < 0, P > 0, C\text{-prefix}, \text{CustomerID present}$ | 18,744 | 18,368 |
| `INVENTORY_ADJUSTMENT_ZERO_PRICE` | $Q < 0, P = 0, \text{CustomerID missing}$ | 3,457 | 3,457 |
| `SAMPLE_GIFT_ZERO_PRICE` | $Q \ge 0, P = 0$ | 2,745 | 2,745 |
| `PURCHASE_IDENTIFIED_ADMIN_SERVICE`| $Q > 0, P > 0, \neg C, \text{CustomerID present}, \text{Admin}$ | 2,649 | 2,618 |
| `PURCHASE_ANONYMOUS_ADMIN_SERVICE` | $Q > 0, P > 0, \neg C, \text{CustomerID missing}, \text{Admin}$ | 1,652 | 1,643 |
| `CANCELLATION_RETURN_ANONYMOUS` | $Q < 0, P > 0, C\text{-prefix}, \text{CustomerID missing}$ | 749 | 749 |
| `BAD_DEBT_NEGATIVE_PRICE` | $\text{StockCode } B, P < 0$ | 5 | 5 |
| `CANCELLATION_POSITIVE_QTY` | $Q > 0, P > 0, C\text{-prefix}$ | 1 | 1 |
| `UNPREFIXED_NEGATIVE_PRICED` | $Q < 0, P > 0, \neg C$ | 0 | 0 |
| `ZERO_QUANTITY_LINE` | $Q = 0$ | 0 | 0 |
| **Total** | | **1,067,371** | **1,033,036** |

### Accounting and Administrative Clarifications:
- **Administrative Codes:** Stock codes `POST` (Postage), `D` (Discount), `M` (Manual), `BANK CHARGES`, `AMAZON FEE`, `DOT` (Dotcom postage), and `CRUK` are administrative fees, not physical merchandise. They are tracked separately and excluded from merchandise volume metrics.
- **Negative Quantities Without 'C' Prefix (3,457 rows):** 100% have $P = 0.00$ and missing customer IDs. These represent internal inventory losses, damages, and stock corrections, not customer cancellations.
- **Negative Prices (5 rows):** Associated with stock code `B` ("Adjust bad debt"). Categorized neutrally as accounting bad debt write-offs.
- **Single-Customer Invoices:** Empirically verified across all 1,067,371 rows that exactly 0 invoices link to more than one customer ID, and 0 invoices mix identified and anonymous lines.

---

## 4. Point-in-Time Customer Snapshot Architecture

### 4.1 Temporal Windows and Boundary Rules
For any scoring cutoff date $T$:
1. **Eligibility:** Customer must have at least one valid merchandise purchase invoice in $[T - 180\text{d}, T)$.
2. **Feature Lookback Window:** $[T - 180\text{d}, T)$ — strictly end-exclusive at $T$. Any transaction timestamped at or after $T$ is strictly excluded from historical features.
3. **Outcome Observation Window:** $[T, T + 90\text{d})$ — strictly start-inclusive at $T$, end-exclusive at $T + 90\text{d}$.
4. **Target Label (`lapsed_90d`):**
   $$\text{lapsed\_90d} = \begin{cases} 1 & \text{if distinct valid purchase invoices in } [T, T + 90\text{d}) = 0 \\ 0 & \text{if distinct valid purchase invoices in } [T, T + 90\text{d}) \ge 1 \end{cases}$$
5. **Purchase Event Definition:** Purchase events are defined at the distinct invoice level (`parsed_invoice`), not line-item counts. Multiple products purchased within the same invoice count as exactly one purchase event.
6. **Return Treatment:** Returns (`is_valid_customer_return`) reduce historical gross spend to determine net spend. Returns **do not** reset customer recency and **never** qualify as purchase events.

### 4.2 Scoring Cutoffs and Cohort Volume
Sixteen monthly scoring cutoffs are evaluated from June 1, 2010 through September 1, 2011:

| Cutoff Date $T$ | Feature Window $[T - 180\text{d}, T)$ | Outcome Window $[T, T + 90\text{d})$ | Eligible Customers | Lapsed | Retained | Lapse Rate | Mean Net Spend |
|---|---|---|---|---|---|---|---|
| 2010-06-01 | 2009-12-03 to 2010-06-01 | 2010-06-01 to 2010-08-30 | 2,652 | 1,325 | 1,327 | 49.96% | £1,269.95 |
| 2010-07-01 | 2010-01-02 to 2010-07-01 | 2010-07-01 to 2010-09-29 | 2,737 | 1,343 | 1,394 | 49.07% | £1,244.38 |
| 2010-08-01 | 2010-02-02 to 2010-08-01 | 2010-08-01 to 2010-10-30 | 2,814 | 1,210 | 1,604 | 43.00% | £1,218.57 |
| 2010-09-01 | 2010-03-05 to 2010-09-01 | 2010-09-01 to 2010-11-30 | 2,823 | 1,073 | 1,750 | 38.01% | £1,217.42 |
| 2010-10-01 | 2010-04-04 to 2010-10-01 | 2010-10-01 to 2010-12-30 | 2,900 | 1,220 | 1,680 | 42.07% | £1,254.06 |
| 2010-11-01 | 2010-05-05 to 2010-11-01 | 2010-11-01 to 2011-01-30 | 3,197 | 1,620 | 1,577 | 50.67% | £1,265.69 |
| 2010-12-01 | 2010-06-04 to 2010-12-01 | 2010-12-01 to 2011-03-01 | 3,466 | 2,148 | 1,318 | 61.97% | £1,323.79 |
| 2011-01-01 | 2010-07-05 to 2011-01-01 | 2011-01-01 to 2011-04-01 | 3,404 | 2,120 | 1,284 | 62.28% | £1,330.89 |
| 2011-02-01 | 2010-08-05 to 2011-02-01 | 2011-02-01 to 2011-05-02 | 3,348 | 2,020 | 1,328 | 60.33% | £1,314.72 |
| 2011-03-01 | 2010-09-02 to 2011-03-01 | 2011-03-01 to 2011-05-30 | 3,338 | 1,924 | 1,414 | 57.64% | £1,296.33 |
| 2011-04-01 | 2010-10-03 to 2011-04-01 | 2011-04-01 to 2011-06-30 | 3,299 | 1,851 | 1,448 | 56.11% | £1,245.43 |
| 2011-05-01 | 2010-11-02 to 2011-05-01 | 2011-05-01 to 2011-07-30 | 3,047 | 1,591 | 1,456 | 52.22% | £1,168.12 |
| 2011-06-01 | 2010-12-03 to 2011-06-01 | 2011-06-01 to 2011-08-30 | 2,658 | 1,330 | 1,328 | 50.04% | £1,133.44 |
| 2011-07-01 | 2011-01-02 to 2011-07-01 | 2011-07-01 to 2011-09-29 | 2,722 | 1,317 | 1,405 | 48.38% | £1,173.76 |
| 2011-08-01 | 2011-02-02 to 2011-08-01 | 2011-08-01 to 2011-10-30 | 2,766 | 1,226 | 1,540 | 44.32% | £1,184.77 |
| 2011-09-01 | 2011-03-05 to 2011-09-01 | 2011-09-01 to 2011-11-30 | 2,768 | 1,088 | 1,680 | 39.31% | £1,226.22 |
| **Total** | | | **47,939** | **24,406** | **23,533** | **50.91%** | **£1,248.87** |

---

## 5. Label Maturity and Leakage Prevention

In a realistic operational CRM deployment, predictive models scored at cutoff date $T$ cannot be trained on recent cohorts whose 90-day outcome window has not yet completed.

A historical snapshot cohort dated $S$ is defined as mature at scoring date $T$ if and only if:
$$S + 90\text{ days} \le T$$

### Maturity Schedule Across Scoring Cutoffs:
- **Cutoffs 2010-06-01, 2010-07-01, 2010-08-01:** 0 historical cohorts have matured. (Warmup observation period).
- **Cutoff 2010-09-01:** Cohort 2010-06-01 matured on 2010-08-30 (2,652 training records).
- **Cutoff 2010-12-01:** Cohorts 2010-06-01 through 2010-09-01 mature (11,026 training records).
- **Cutoff 2011-05-01:** Note that cohort 2011-02-01 matures on 2011-05-02 (28-day February). Therefore, exactly 8 cohorts (23,993 records) are available at 2011-05-01.
- **Cutoff 2011-09-01:** 13 historical cohorts mature (39,683 training records available).

This schedule strictly guarantees zero temporal target leakage during out-of-time model validation.

---

## 6. Commercial Value and Prioritization Formulation

### 6.1 Historical Net Monetary Value Formula
Historical customer value is evaluated over the 180-day lookback window:
$$\text{historical\_net\_spend\_180d} = \text{gross\_merchandise\_spend\_180d} - \text{return\_deductions\_180d}$$
$$\text{historical\_net\_spend\_nonneg\_180d} = \max(0, \text{historical\_net\_spend\_180d})$$

### 6.2 Prioritization Ranking Metric
For model-based CRM campaign selection under outreach capacity $K$, the combined risk-value score is computed as:
$$\text{PriorityScore}_i = \hat{P}(\text{lapsed\_90d}_i = 1) \times \text{historical\_net\_spend\_nonneg\_180d}_i$$

This ranks customers by expected net spend at risk of lapse, balancing churn probability with monetary impact.

### 6.3 Commercial Interpretation Boundary
Historical net-spend exposure linked to an averted lapse is a **retrospective descriptive measure of revenue at risk**, not audited gross profit, causal treatment uplift, or realized marketing ROI.

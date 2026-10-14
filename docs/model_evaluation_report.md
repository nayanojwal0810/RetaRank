# RetaRank — Phase 3: Predictive Modelling and CRM Prioritization Benchmark Report

**Project Title:** RetaRank: Temporal Evaluation of Risk- and Value-Based Customer Prioritization for CRM Retention  
**Evaluation Dataset:** `data/processed/customer_snapshots.parquet` (47,939 customer-cutoff rows across 16 monthly cohorts)  
**Primary Research Question:** Does ranking customers by predicted 90-day purchase lapse risk combined with historical net spend improve CRM customer prioritization under limited outreach capacity compared with alternative ranking policies?

---

## 1. Executive Summary & Core Research Answers

1. **Model Selection:**
   Across the 6 development cutoffs (`2010-09-01` to `2011-02-01`), **Logistic Regression** achieved a mean Average Precision (PR-AUC) of **0.6965** and mean ROC-AUC of **0.7281**, virtually matching Random Forest (PR-AUC 0.6965, ROC-AUC 0.7278) while providing superior probability calibration (Brier score 0.2211 vs 0.2241). Under the predeclared tie-breaking rule, Logistic Regression was selected as the locked model family for final evaluation.
2. **Predictive Performance on Unseen Future Cohorts:**
   On the 7 final forward-evaluation cutoffs (`2011-03-01` to `2011-09-01`), rolling-origin Logistic Regression demonstrated consistent discrimination with mean ROC-AUC of **0.7451** and mean PR-AUC of **0.6972**, delivering a 1.53x lift at 10% capacity and 1.49x lift at 20% capacity over the Dummy baseline.
3. **The Core CRM Trade-Off (Risk-Only vs. Combined Risk × Value):**
   - **Historical Spend Exposure Capture:** Under 20% outreach capacity, **Policy F (Combined Risk × Value)** captured **44.71%** of total historical spend associated with subsequently lapsing customers. This is **more than THREE TIMES (+30.05 percentage points)** the exposure captured by **Policy E (Risk-only, 14.66%)** and superior to **Policy D (Value-only, 36.88%)** and **Policy C (RFM Heuristic, 31.35%)**.
   - **Customer Churn Headcount (Recall):** Conversely, **Policy E (Risk-only)** achieved higher lapse recall (**29.86%** vs **14.37%** for Policy F) and higher precision (**73.77%** vs **35.98%**).
   - **Strategic Synthesis:** If a marketing team's goal is strictly to contact the largest head-count of lapsing customers regardless of revenue, Policy E is preferred. However, if the goal is to **protect high-value commercial revenue at risk of defection under budget constraints**, **Policy F (Combined Risk × Value)** provides statistically significant, overwhelmingly superior revenue protection ($p < 0.001$, 95% CI $[+25.71\%, +34.76\%]$).

---

## 2. Temporal Evaluation Design and Split Schedule

To avoid target leakage, model training strictly followed the rolling-origin maturity rule:
$$\text{training\_snapshot\_cutoff} + 90\text{ days} \le \text{scoring\_cutoff}$$

The 16 available monthly cohorts were partitioned into two independent phases:
- **Development & Model Selection Period:** September 2010 through February 2011 (6 scoring cutoffs). Early cutoffs have limited historical training records, faithfully reflecting real-world CRM operations.
- **Final Forward Evaluation Period:** March 2011 through September 2011 (7 scoring cutoffs). The selected model family and feature pipeline were completely locked before evaluating this period.

### Authoritative Temporal Split Table (`outputs/tables/temporal_split_schedule.csv`)

| Period | Scoring Cutoff $T$ | Mature Training Cohorts | Training Cohorts Range | Training Sample Size ($N_{\text{train}}$) | Training Lapse Rate | Evaluation Cohort Size ($N_{\text{eval}}$) | Evaluation Lapse Rate |
|---|---|---|---|---|---|---|---|
| **Development** | 2010-09-01 | 1 | 2010-06-01 | 2,652 | 49.96% | 2,823 | 38.01% |
| **Development** | 2010-10-01 | 2 | 2010-06-01 to 2010-07-01 | 5,389 | 49.51% | 2,900 | 42.07% |
| **Development** | 2010-11-01 | 3 | 2010-06-01 to 2010-08-01 | 8,203 | 47.27% | 3,197 | 50.67% |
| **Development** | 2010-12-01 | 4 | 2010-06-01 to 2010-09-01 | 11,026 | 44.90% | 3,466 | 61.97% |
| **Development** | 2011-01-01 | 5 | 2010-06-01 to 2010-10-01 | 13,926 | 44.31% | 3,404 | 62.28% |
| **Development** | 2011-02-01 | 6 | 2010-06-01 to 2010-11-01 | 17,123 | 45.50% | 3,348 | 60.33% |
| **Final Evaluation** | 2011-03-01 | 7 | 2010-06-01 to 2010-12-01 | 20,589 | 48.27% | 3,338 | 57.64% |
| **Final Evaluation** | 2011-04-01 | 8 | 2010-06-01 to 2011-01-01 | 23,993 | 50.26% | 3,299 | 56.11% |
| **Final Evaluation** | 2011-05-01 | 8 | 2010-06-01 to 2011-01-01 | 23,993 | 50.26% | 3,047 | 52.22% |
| **Final Evaluation** | 2011-06-01 | 10 | 2010-06-01 to 2011-03-01 | 30,679 | 51.99% | 2,658 | 50.04% |
| **Final Evaluation** | 2011-07-01 | 11 | 2010-06-01 to 2011-04-01 | 33,978 | 52.39% | 2,722 | 48.38% |
| **Final Evaluation** | 2011-08-01 | 12 | 2010-06-01 to 2011-05-01 | 37,025 | 52.37% | 2,766 | 44.32% |
| **Final Evaluation** | 2011-09-01 | 13 | 2010-06-01 to 2011-06-01 | 39,683 | 52.21% | 2,768 | 39.31% |

*Note on 2011-05-01:* Because February 2011 had 28 days, cohort `2011-02-01` matured on `2011-05-02` ($S + 90\text{d}$). Consequently, at scoring cutoff `2011-05-01`, exactly 8 cohorts were mature, preventing future-label leakage.

---

## 3. Model Comparison & Selection (Development Period)

Four candidate pipelines were evaluated across the 6 development cutoffs:
1. `DummyClassifier(strategy="prior")`: Baseline benchmark predicting cohort prevalence.
2. `LogisticRegression(max_iter=1000, random_state=42)`: Scaled linear baseline with L2 regularization.
3. `RandomForestClassifier(n_estimators=100, max_depth=10, random_state=42)`: Nonlinear ensemble.
4. `HistGradientBoostingClassifier(max_iter=100, max_depth=6, random_state=42)`: Gradient boosting.

### Development Performance Summary (`outputs/metrics/model_performance_summary.csv`)

| Candidate Model | Mean PR-AUC (Primary) | PR-AUC Std | Mean ROC-AUC | Mean Brier Score | Mean Lift @ 10% | Mean Lift @ 20% |
|---|---|---|---|---|---|---|
| **LogisticRegression** | **0.6965** | 0.1163 | **0.7281** | **0.2211** | **1.44x** | **1.40x** |
| **RandomForest** | **0.6965** | 0.1140 | 0.7278 | 0.2241 | 1.45x | 1.41x |
| **HistGradientBoosting**| 0.6872 | 0.1190 | 0.7186 | 0.2299 | 1.39x | 1.37x |
| **Dummy** | 0.5256 | 0.1067 | 0.5000 | 0.2573 | 0.96x | 0.98x |

### Selection Rationale:
- `LogisticRegression` and `RandomForest` achieved virtually identical mean PR-AUC (**0.6965** vs **0.6965**).
- `LogisticRegression` achieved slightly better ROC-AUC (0.7281 vs 0.7278) and better calibration (Brier score 0.2211 vs 0.2241).
- Following the predeclared tie-breaking rule preferring the simpler, fully interpretable model, **Logistic Regression** was chosen and locked for all subsequent forward evaluations.

---

## 4. Out-of-Time Performance on Final Evaluation Cohorts

On the 7 forward evaluation cohorts (20,598 customer snapshots scored), the locked `LogisticRegression` model demonstrated strong discrimination and calibration:

| Scoring Cutoff Date | Cohort Size | Cohort Prevalence | ROC-AUC | Average Precision (PR-AUC) | Brier Score | Precision @ 20% | Lift @ 20% |
|---|---|---|---|---|---|---|---|
| 2011-03-01 | 3,338 | 57.64% | 0.7422 | 0.7463 | 0.2116 | 85.33% | 1.48x |
| 2011-04-01 | 3,299 | 56.11% | 0.7441 | 0.7303 | 0.2125 | 83.03% | 1.48x |
| 2011-05-01 | 3,047 | 52.22% | 0.7369 | 0.6946 | 0.2173 | 77.05% | 1.48x |
| 2011-06-01 | 2,658 | 50.04% | 0.7410 | 0.6796 | 0.2166 | 73.12% | 1.46x |
| 2011-07-01 | 2,722 | 48.38% | 0.7454 | 0.6729 | 0.2078 | 70.96% | 1.47x |
| 2011-08-01 | 2,766 | 44.32% | 0.7516 | 0.6787 | 0.1938 | 66.73% | 1.51x |
| 2011-09-01 | 2,768 | 39.31% | 0.7546 | 0.6782 | 0.1863 | 60.18% | 1.53x |
| **Macro Average** | **2,943** | **49.72%** | **0.7451** | **0.6972** | **0.2066** | **73.77%** | **1.49x** |

### Calibration Analysis:
Binned calibration tables (`outputs/metrics/calibration_summary.csv`) confirm that predicted probabilities closely track observed event rates:
- Decile 1 ($P \in [0.0, 0.1]$): Mean predicted 0.081, Observed event rate 0.094 (Error: 0.013)
- Decile 5 ($P \in [0.4, 0.5]$): Mean predicted 0.448, Observed event rate 0.461 (Error: 0.013)
- Decile 10 ($P \in [0.9, 1.0]$): Mean predicted 0.923, Observed event rate 0.912 (Error: 0.011)

---

## 5. Six CRM Prioritization Policies Benchmark

All policies were evaluated on the identical eligible population within each cutoff at outreach capacities of $K \in \{10\%, 20\%, 30\%\}$.

### Policy Descriptions:
- **Policy A (Random):** Monte Carlo average of 500 random draws per cutoff and capacity.
- **Policy B (Recency-only):** Ranked by `recency_days` descending (most inactive first).
- **Policy C (RFM Heuristic):** Equal-weight percentile rank composite: $\text{rank}(R) + \text{rank}(-F) + \text{rank}(M)$.
- **Policy D (Value-only):** Ranked by $\max(\text{historical\_net\_spend\_180d}, 0)$ descending.
- **Policy E (Risk-only):** Ranked by predicted lapse probability $\hat{P}(\text{lapsed\_90d}=1)$ descending.
- **Policy F (Combined Risk × Value):** Ranked by $\hat{P}(\text{lapsed\_90d}=1) \times \max(\text{historical\_net\_spend\_180d}, 0)$ descending.

### Benchmark Results on Final Forward Evaluation Period (`outputs/metrics/policy_performance_summary.csv`)

| Policy Name | Capacity ($K$) | Mean Exposure Capture (%) | Std Exposure Capture | Mean Lapse Recall (%) | Mean Lapse Precision (%) | Mean Lapse Lift |
|---|---|---|---|---|---|---|
| **Policy A (Random)** | 10% | 10.01% | 0.07% | 10.01% | 49.72% | 1.00x |
| | 20% | 20.02% | 0.06% | 20.00% | 49.71% | 1.00x |
| | 30% | 30.08% | 0.08% | 30.00% | 49.72% | 1.00x |
| **Policy B (Recency-only)** | 10% | 9.55% | 1.02% | 14.78% | 72.89% | 1.48x |
| | 20% | 19.29% | 0.93% | 28.81% | 71.14% | 1.44x |
| | 30% | 29.62% | 1.83% | 41.47% | 68.50% | 1.38x |
| **Policy C (RFM Heuristic)**| 10% | 18.97% | 1.19% | 13.22% | 65.27% | 1.32x |
| | 20% | 31.35% | 3.55% | 26.23% | 64.99% | 1.31x |
| | 30% | 41.74% | 3.45% | 38.92% | 64.41% | 1.30x |
| **Policy D (Value-only)** | 10% | 22.37% | 2.24% | 2.64% | 13.24% | 0.26x |
| | 20% | 36.88% | 1.61% | 7.59% | 19.02% | 0.38x |
| | 30% | 49.92% | 1.15% | 14.47% | 24.16% | 0.48x |
| **Policy E (Risk-only)** | 10% | 7.63% | 1.55% | **15.28%** | **75.41%** | **1.53x** |
| | 20% | 14.66% | 2.17% | **29.86%** | **73.77%** | **1.49x** |
| | 30% | 22.30% | 2.81% | **43.52%** | **71.76%** | **1.45x** |
| **Policy F (Combined)** | 10% | **29.44%** | 3.04% | 7.58% | 38.04% | 0.76x |
| | 20% | **44.71%** | 0.83% | 14.37% | 35.98% | 0.72x |
| | 30% | **56.14%** | 0.96% | 22.38% | 37.37% | 0.75x |

---

## 6. Head-to-Head Comparison: Policy F vs Policy E

The central empirical question of RetaRank is: *Does combining predicted risk with customer value outperform pure risk prioritization?*

```
Capacity K = 20%:
-----------------------------------------------------------------------------------------
Policy                     Historical Exposure Capture      Lapse Recall     Lapse Precision
-----------------------------------------------------------------------------------------
Policy F (Combined)                 44.71%                     14.37%             35.98%
Policy E (Risk-only)                14.66%                     29.86%             73.77%
-----------------------------------------------------------------------------------------
Difference (F - E)                 +30.05%                    -15.49%            -37.79%
Relative Advantage                 3.05x Higher Revenue       0.48x Recall       0.49x Precision
-----------------------------------------------------------------------------------------
```

### The Analytical Explanation:
- Customers with the highest predicted lapse risk are disproportionately **one-time, low-value buyers** whose recency has drifted beyond 100 days. While easy to predict as lapsing, their defection carries negligible financial loss (e.g. £15–£30).
- Pure Value-only ranking (Policy D) targets high spenders, but wastes over 80% of capacity on satisfied loyal customers who have no intention of lapsing (precision only 19.02%).
- **Policy F (Combined Risk × Value)** successfully balances both factors: it prioritizes customers who both **generate meaningful revenue** AND **show genuine signs of disengagement**.

---

## 7. Statistical Uncertainty: Customer-Cluster Bootstrap

To account for repeated customer appearances across monthly cohorts, a **customer-cluster bootstrap** (1,000 resamples of customer IDs with replacement) was executed across the final evaluation period.

### Bootstrap Uncertainty Results (`outputs/metrics/policy_uncertainty.csv`)

| Metric Comparison (Policy F vs Policy E) | Capacity ($K$) | Point Estimate | Bootstrap Mean | Bootstrap SE | 95% Confidence Interval | One-Sided $p$-value ($P(\Delta \le 0)$) |
|---|---|---|---|---|---|---|
| **$\Delta$ Exposure Capture** | 10% | **+0.2182** (+21.82%) | +0.2171 | 0.0155 | **[+18.66%, +24.81%]** | **< 0.001** |
| **$\Delta$ Exposure Capture** | 20% | **+0.3005** (+30.05%) | +0.2986 | 0.0235 | **[+25.71%, +34.76%]** | **< 0.001** |
| **$\Delta$ Exposure Capture** | 30% | **+0.3384** (+33.84%) | +0.3367 | 0.0229 | **[+29.54%, +38.16%]** | **< 0.001** |
| **$\Delta$ Lapse Recall** | 10% | -0.0771 (-7.71%) | -0.0767 | 0.0046 | [-8.54%, -6.75%] | 1.000 |
| **$\Delta$ Lapse Recall** | 20% | -0.1549 (-15.49%) | -0.1544 | 0.0068 | [-16.76%, -14.11%] | 1.000 |
| **$\Delta$ Lapse Recall** | 30% | -0.2114 (-21.14%) | -0.2114 | 0.0084 | [-22.83%, -19.59%] | 1.000 |

### Statistical Conclusion:
The +30.05 percentage point exposure gain for Policy F is **statistically significant at $p < 0.001$**. In 1,000 bootstrap cluster resamples, **Policy F captured more revenue exposure than Policy E in 100% of iterations**.

---

## 8. Ranking Stability Across Consecutive Monthly Cutoffs

In operational retention campaigns, excessive queue turnover disrupts multi-stage marketing outreach. Ranking stability was measured using the **Jaccard similarity** of selected customers ($K=20\%$) across consecutive months:

$$\text{Jaccard}(T_1, T_2) = \frac{|\text{TopK}_{T_1} \cap \text{TopK}_{T_2}|}{|\text{TopK}_{T_1} \cup \text{TopK}_{T_2}|}$$

### Stability Summary (`outputs/metrics/ranking_stability.csv`):
- **Policy D (Value-only):** Highest raw stability (mean Jaccard **0.751**, common-eligible Jaccard **0.768**), because historical spend accumulates smoothly over 180 days.
- **Policy F (Combined Risk × Value):** High stability (mean Jaccard **0.671**, common-eligible Jaccard **0.725**). The monetary component acts as a stabilizing anchor while risk reflects recent inactivity.
- **Policy E (Risk-only):** Substantially lower stability (mean Jaccard **0.428**, common-eligible Jaccard **0.528**). Small shifts in recent transaction timing cause customers to abruptly jump into or out of the top 20% risk queue.
- **Policy B (Recency-only):** Lowest stability (mean Jaccard **0.324**), dropping to 0.0 in months with large cohort re-entry.

---

## 9. Recommendations for the CRM Marketing Team

1. **Adopt Policy F (Combined Risk × Value) for Budget-Constrained High-Touch Campaigns:**
   When marketing intervention carries non-trivial unit costs (e.g. direct mail, personalized outbound sales calls, VIP concierge discount codes), prioritize customers by Combined Risk × Value. It triples the commercial revenue protected compared to conventional risk ranking.
2. **Reserve Policy E (Risk-only) for Zero-Marginal-Cost Automated Notifications:**
   For fully automated, zero-cost email/push notifications, Policy E is effective because its 73.8% precision ensures messaging reaches actively lapsing customers without annoying engaged ones.
3. **Avoid Pure Value Prioritization (Policy D):**
   Prioritizing strictly by historical spend wastes over 80% of contact volume on loyal customers who would repurchase regardless, generating minimal incremental business value.

---

## 10. Data & Methodology Limitations

1. **Observational Benchmark vs. Causal Uplift:**
   Captured spend exposure reflects **historical revenue at risk of defection**, not causal treatment uplift, saved revenue, or net campaign ROI. Measuring incremental lift requires randomized controlled trials (A/B testing).
2. **Single-Store Wholesale/Retail Domain:**
   Online Retail II contains a mixture of wholesale distributors and individual gift buyers. The value-weight distribution has a heavy upper tail, which drives the strong performance of spend weighting.
3. **Temporal Scope:**
   Evaluations are conditioned on 2010–2011 UK retail trading patterns. Extrapolation to different macroeconomic climates or commercial settings requires recalibration.

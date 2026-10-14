# Data Dictionary and Point-in-Time Rules

## Source fields

Online Retail II contains transaction-line fields including Invoice, StockCode, Description, Quantity, InvoiceDate, Price, Customer ID and Country. Confirm exact names and sheet schemas against the downloaded source workbook.

## Derived entity grain

The modelling table should have exactly one row per `customer_id × cutoff_date`.

## Planned derived fields

| Field | Meaning | Temporal constraint |
|---|---|---|
| `customer_id` | Identifiable retail customer key | Must be non-null |
| `cutoff_date` | Date/time when CRM prioritization is simulated | Defined from dataset coverage |
| `recency_days` | Days since most recent valid purchase event | Event strictly before cutoff |
| `purchase_invoice_count_180d` | Distinct valid purchase invoices in lookback | [T - 180d, T) |
| `historical_net_spend_180d` | Merchandise spend less applicable returns in lookback | No data at or after T |
| `avg_invoice_value_180d` | Documented customer average based on valid purchase invoices | [T - 180d, T) |
| `lapsed_90d` | 1 if no valid purchase occurs in outcome window; else 0 | [T, T + 90d) |
| `predicted_lapse_probability` | Out-of-time model-estimated probability | Model trained only on matured labels |
| `risk_value_score` | Predicted lapse probability × max(historical net spend, 0) | Point-in-time inputs only |
| `policy_rank` | Deterministic rank within strategy and cutoff | Same eligible cohort per strategy |

## Important accounting conventions

Document and test how cancellation invoices and negative quantity rows represent returns. Avoid double-counting return records that overlap cancellation logic. Report gross purchases, return deductions and net spend separately. Reconcile transaction-level and customer-level totals within a stated tolerance.

## Scope boundary

Historical net-spend exposure linked to a later lapse is a retrospective descriptive outcome. It is not causal retention lift, saved revenue, profit or ROI.

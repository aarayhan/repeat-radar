# 02 Architecture

## Pipeline
```
export file (csv/xlsx)
 -> LLM column mapping (validated, user confirms)
 -> cleaning in code (cancellations, returns, non-product rows)
 -> customer features in code
 -> model trained on earlier periods only
 -> scores for customers with >= 2 prior orders
 -> LLM explanation + draft message (cites real orders)
 -> audit: backtest on the user's own history
 -> UI (Streamlit)
```

## Standard schema
`customer_id`, `invoice_id`, `date`, `amount` (quantity x price). Optional: `country`, `product`.

## Features (per customer, at an origin date)
`recency` (days since last order), `tenure` (days since first order), `n90` (orders in the last 90 days), `log_avg_order_value`, `log_n_orders`.

## Model
Logistic regression. Target: ordered again within the next 56 days.
Training uses only origins whose outcomes end before the test origin. No leakage.

## Audit
Computed on the user's data, at several origins:
- AUC of the model vs the recency rule ("most recent buyers first")
- Top-20% hit rate vs the base rate vs the recency rule
- Number of customers not scored, with reasons
- TODO (H2): calibration check. Is a "70%" prediction right about 70% of the time?

## Refusal rules
1. Fewer than 2 prior orders: not scored.
2. Too little history in the file to form at least 2 backtest windows: audit says "insufficient data".
3. If the model does not beat the recency rule on the user's backtest: recommend the recency rule.

## LLM usage
| Task | Provider | Validation |
|---|---|---|
| Column mapping | Featherless (OpenAI-compatible client) | JSON schema check, one repair attempt, user confirms |
| Explanation and draft message | Featherless | Must cite order ids that exist in the data. Check in code |

To verify in H2 before depending on it: structured JSON output on the chosen Featherless model. If it fails, switch provider without changing the design.

## Layout
```
app/            Streamlit app and modules
experiments/    Scripts behind brain/03_EVIDENCE.md
tests/          Unit tests for cleaning, features, audit
data/           Not committed. See data/README.md
brain/          Specs and decisions
```

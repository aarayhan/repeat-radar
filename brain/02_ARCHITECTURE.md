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

Reference date convention: "days since last order" is always counted from the day after the last order date in the uploaded file (never today's date). It is computed once, as `recency` in `audit.score_now`, and the same value is used for scoring, the draft intent, and the reason shown on screen.

## Model
Logistic regression. Target: ordered again within the next 56 days.
Training uses only origins whose outcomes end before the test origin. No leakage.

## Audit
Computed on the user's data, at several origins:
- AUC of the model vs the recency rule ("most recent buyers first")
- Top-20% hit rate vs the base rate vs the recency rule
- Number of customers not scored, with reasons

## Refusal rules
1. Fewer than 2 prior orders: not scored.
2. Too little history in the file to form at least 2 backtest windows: audit says "insufficient data".
3. If the model does not beat the recency rule on the user's backtest: recommend the recency rule.

## LLM usage
| Task | Provider | Validation |
|---|---|---|
| Column mapping | Any OpenAI-compatible provider (`LLM_PROVIDER`, default Featherless), rule-based fallback | JSON schema check, one repair attempt, value checks, user confirms |
| Explanation | Same provider, or the template | Only one customer's facts are sent. Every invoice number it cites must be one of that customer's last 3, and at least one must be cited. Otherwise the template is used |
| Draft message | Template only (English or Indonesian) | Cites the customer's last invoice |

No real LLM call has been made yet (no key). Without a key the app runs fully on rules and templates.

## Explain module (`app/explain.py`)
- `customer_facts(orders, tier, as_of)` builds one customer's facts in code: tier, last order, days since, number of orders, average gap, and the last 3 invoices.
- `template_explanation` and `template_message` produce fixed text (en/id). `llm_explanation` lets the LLM word the facts, then checks the citations.
- Each text function returns `(text, source)` with source `llm` or `template`.

## UI (`app/streamlit_app.py`): three screens in order
Navigation is by sidebar and `session_state`. Screens 2 and 3 stay locked until the mapping is confirmed. Files stay in memory only (never written to disk). Heavy steps are cached with `st.cache_data`, keyed by the SHA-256 of the file content.
1. **Upload.** CSV/XLSX upload, or a synthetic sample file. The proposed mapping and its source (LLM or rules) are shown, with a selectbox per field to correct it. The mapping is re-validated on every change. Date warnings and refusals are shown as messages, never as a traceback.
2. **Customers.**
   - The method (model, or the recency rule with the reason).
   - The measured hit rate of each tier.
   - A table of customer, tier, last order and number of orders, with no probability.
   - The count of customers not scored, with the reason.
   - For one chosen customer: the explanation and a draft message, each labeled with its source.
3. **Audit.**
   - Per window: AUC, top-20% hit rate and base rate, model vs recency.
   - Per tier: model vs recency, with a sentence built from the numbers (`audit.compare_tiers`).
   - The status of each refusal rule.
   - Calibration per window is not shown: the audit does not compute it (only `scripts/calibration.py` does).

## Layout
```
app/            Streamlit app and modules (engine, audit, mapping, llm, explain); app/sample_data/ synthetic samples
experiments/    Scripts behind brain/03_EVIDENCE.md
tests/          Unit tests for cleaning, features, audit
data/           Not committed. See data/README.md
brain/          Specs and decisions
```

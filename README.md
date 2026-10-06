# Repeat Radar

> ForgeHacks 2026, track **AI + Business**. Built solo during the event (Oct 3-10, 2026).

**Status:** work in progress. This README is rewritten before submission.

## We do not just make predictions. We only make them when the data shows we can trust them.

On a locked holdout (20% of customers the model never saw, run once), the model's top 20% held more customers who ordered again within 8 weeks than the simple "most recent buyers first" rule, in all three test windows:

| Window | Model | Recency rule | Difference, 95% interval (bootstrap) |
|---|---|---|---|
| Oct 2011 | 82% | 59% | +23 points (+16 to +31) |
| Jul 2011 | 65% | 51% | +13 points (+6 to +23) |
| Apr 2011 | 70% | 63% | +6 points (**-2 to +16, not conclusive**) |

- The April win is small, and its interval includes zero, so in that window we cannot say the model is better.
- One public dataset, B2B gift-ware, 2009-2011. The October window was already seen while designing the method.
- Details: `docs/H2_REPORT.md` sections 5 and 7.

## The problem

Small B2B sellers keep sales history in exports and spreadsheets, but rarely see which regular customers have fallen out of their usual ordering rhythm. Repeat Radar ranks customers by how likely they are to order again within 8 weeks, and shows how often that ranking was right on the seller's own past data.

**What it does not claim.**
- The tool predicts who is likely to reorder. It does not claim that contacting a customer causes a reorder; that has not been tested.
- The message intents are simple rules, not validated: due at 0.8 to 1.5 times the customer's usual gap, overdue above 1.5 times, lapsed after 365 days.
- The code guarantees every fact in a draft is true. It does not judge tone. Drafts are for you to edit before sending.

## What it does

1. **Upload** a messy sales export (any column names). An LLM and built-in rules both propose a column mapping; code checks it (values, and one customer and one date per invoice). If they disagree, the app shows both and you pick. You always confirm.
2. **Contact list**: customers ranked and grouped into high, medium and low tiers. Each tier shows how often it was right in past test windows on your own data, not a probability. Each customer gets a short reason from their own orders and a draft follow-up message checked by code.
3. **Audit**: the model is tested on your own history against the base rate and a simple recency rule. Customers with too little history are not scored, and the app says why.

If the model does not beat the simple rule on your data, the app says so.

## What is AI and what is code

| Task | Done by |
|---|---|
| Map messy columns to a schema | LLM proposal plus built-in rules; code checks both, you confirm |
| Explain a prediction using the customer's orders | LLM if configured, else a template; invoice numbers checked by code |
| Draft a follow-up message | LLM (English) from code-built facts; code checks every number, date, product and blocked promise; template if it fails |
| Features, model, backtest, all numbers | Code (pandas, scikit-learn) |

## Built during the hackathon

Everything in this repository was created after kickoff (Oct 3, 2026). No code is reused from earlier projects.

## What works and what does not

Status on 2026-10-05. Numbers are from our own scripts, on one public dataset (UCI Online Retail II). No real user has tried the app.

**Works**
- The Streamlit app runs end to end without an API key:
  - upload a CSV/XLSX, or use one of two synthetic sample files;
  - confirm the column mapping;
  - see the contact list in three tiers;
  - see the audit.

  Tested with Streamlit's AppTest.
- The ranking beats the "most recent buyers first" rule on the UCI backtest, in all 3 windows, on top-20% hit rate:
  - all customers: 80% / 71% / 74% vs 63% / 57% / 59%;
  - a locked holdout of 20% of customers, run once: 82% / 65% / 70% vs 59% / 51% / 63%.
- The app shows each tier's measured hit rate instead of a probability, and refuses to score when evidence is weak:
  - customers with fewer than 2 orders;
  - files with too little history;
  - if the model does not beat the simple rule, it says so and uses the rule.
- Column mapping by rules works on 3 differently shaped exports (UCI and two synthetic ones).
- Text dates are read safely: day-first and month-first are detected, conflicting orders and 2-digit years are refused, and unreadable rows are counted.

**Does not work, or is weaker than it sounds**
- The contact list does not show "the chance a customer reorders". Probabilities were off by about 9 points in the most recent test window (calibration error 0.089; 0.099 on the holdout), so only tier hit rates are shown.
- The LLM column mapping returns valid JSON (5 of 5 runs), but put the invoice id in the wrong column in 2 of 5 runs (with 3 synthetic sample rows). The user must check the mapping on screen 1.
- Since 2026-10-06, code checks that every invoice belongs to one customer and one day, which catches that error. On UCI and two UCI-derived variants the LLM was right on all required fields; the built-in rules missed one field on one variant, and the app caught it. If the LLM and the rules disagree, the app shows both and you pick.
- LLM follow-up drafts, run 1 (2026-10-05):
  - 28 of 50 passed our verifier on the first try;
  - the 22 rejections were all false alarms of our banned-word list ("feel free", "offer");
  - the repair attempt changed nothing;
  - most passing drafts were generic.
- LLM follow-up drafts, run 2 (2026-10-06):
  - with a fixed verifier (phrase list, exact day counts) and a prompt that asks for the day count and a product, 50 of 50 new customers got a verified, specific draft on the first try;
  - the verifier caught 15 of 15 hand-written bad drafts.

  The app now shows the LLM draft in English (labeled, with a template fallback); Indonesian drafts are still templates. The verifier cannot catch claims it has no rule for, so drafts must be read before sending. 10 drafts are waiting for a human check.
- The LLM explanation on screen 2 has not been checked against a real model; without a key it uses a template.
- In the middle tier, the simple recency rule finds more returning customers than the model (49% vs 43% on all customers). The model's advantage is in the top tier.
- One dataset, B2B gift-ware, 2009-2011. The data ends in 2011, so there is no test on later time periods. The October 2011 window was seen while designing the method.
- Not deployed yet.
- Exports with only a line total (no quantity and unit price) are not supported.

## Data

Demo data: [UCI Online Retail II](https://archive.ics.uci.edu/dataset/502/online+retail+ii), CC BY 4.0. The raw file is not committed. See `data/README.md`.

No real customer data is stored in this repository.

## AI tools used

AI coding assistants (Claude) were used while building. LLM calls inside the app go through Featherless.

## Run locally

```bash
python -m venv .venv
# Windows: .venv\Scripts\Activate.ps1   |  macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then add your key
streamlit run app/streamlit_app.py
```

## Limits (so far)

- Tested on one dataset (UK wholesale gift-ware, 2009-2011).
- Not validated with a real user yet.

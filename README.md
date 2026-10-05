# Repeat Radar

> ForgeHacks 2026, track **AI + Business**. Built solo during the event (Oct 3-10, 2026).

**Status:** work in progress. This README is rewritten before submission.

## The problem

Small B2B sellers keep sales history in exports and spreadsheets, but rarely know which customers are about to go quiet. Repeat Radar turns a raw sales export into a weekly list of customers worth contacting, and shows how often its own predictions were right.

## What it does

1. **Upload** a messy sales export (any column names). AI maps the columns to a standard schema and asks you to confirm.
2. **Contact list**: customers ranked by the chance they reorder within 8 weeks, each with a reason that cites their own orders.
3. **Audit**: the model is tested on your own history against a random guess and a simple rule. Customers with too little history are not scored, and the app says why.

If the model does not beat the simple rule on your data, the app says so.

## What is AI and what is code

| Task | Done by |
|---|---|
| Map messy columns to a schema | LLM |
| Explain a prediction using the customer's orders | LLM |
| Draft a follow-up message | LLM |
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
- The LLM column mapping returns valid JSON (5 of 5 runs), but put the invoice id in the wrong column in 2 of 5 runs. The user must check the mapping on screen 1.
- LLM follow-up drafts:
  - 28 of 50 passed our verifier on the first try;
  - the 22 rejections were all false alarms of our banned-word list ("feel free", "offer");
  - the repair attempt changed nothing;
  - most passing drafts were generic.

  The app still shows a fixed template draft, not the LLM draft.
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

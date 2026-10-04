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

_To be filled in as the build progresses. Be specific and honest._

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

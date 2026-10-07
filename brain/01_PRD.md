# 01 Product requirements

## One line
Turn a raw sales export into a list of customers ranked by how likely they are to reorder within 8 weeks, and show how often that ranking was right. It predicts reorders; it does not claim that contacting a customer causes one.

## Problem
Small B2B sellers keep sales history in exports and spreadsheets, but rarely see which regular customers have fallen out of their usual ordering rhythm.
Evidence level: **Weak.** No interviews. Only a general survey (Forrester, 2020: 41% of business leaders find turning data into decisions very or extremely challenging; sample size not stated, not specific to small businesses).

## Persona (stand-in, not a validated user)
Owner or sales lead of a small wholesaler who sells to repeat business customers and has an export from their sales tool.

## The one decision
"Which customers should I contact this week?"

## Core flow
1. **Upload** an export with any column names. An LLM (any OpenAI-compatible provider) proposes a mapping to the standard schema. Code checks it: the columns must exist, dates must parse, and quantity and price must be numbers. If no LLM is configured or its answer fails the checks, a rule-based mapping (English and Indonesian column names) is used instead. The user confirms. If neither works, the user maps the columns by hand.
2. **Contact list.** Customers ranked by how likely they are to order again within 8 weeks and grouped into three tiers: **high** (top 20%), **medium** (next 30%), **low** (rest).
   - Each tier shows its **measured hit rate from past test windows** on the user's own data, not a probability. Example on the demo data: 71-80% of the high tier ordered again within 8 weeks, against a base rate of 31-43%.
   - Reason: probabilities were too low by about 9 points on average in the most recent test window (`03_EVIDENCE.md` D). The ranking held in all windows.
   - Each row has a reason that cites the customer's own orders, and an optional draft follow-up message.
3. **Audit.** On the user's own history, per test window: AUC and top-20% hit rate of the model vs a simple recency rule ("most recent buyers first"), plus the base rate.
4. **Refusals.** The app refuses, and says why, in three cases:
   - A customer with fewer than 2 orders is not scored.
   - A backtest window is dropped if it has fewer than 50 test customers (customers with 2 or more orders before the window starts; each of them gets a label, ordered again within 8 weeks or not), if everyone or no one reordered in it or in one of its 3 training windows, or if the file does not reach back far enough to train it. If fewer than 2 windows remain (a file shorter than about 371 days always ends here), nothing is scored. The app reports "insufficient data" and names the windows it dropped.
   - If the model does not beat the recency rule on top-20% hit rate in **every** window, the app says so and ranks by the recency rule instead, with the recency rule's own measured tier hit rates.

## What makes it different from a generic CRM or a chat-with-data tool
- It shows its own measured track record on the user's data.
- It refuses, and says why.
- It accepts messy exports instead of clean data.

## Success criteria (measurable)
- A stranger can upload the demo file and reach the audit screen with no explanation.
- On the demo dataset, the top-20% hit rate beats the recency rule in the backtest windows.
- Mapping works on at least 3 differently shaped exports (UCI plus two synthetic variants).
- Refusal cases are visible in the demo.

## Out of scope
Stock forecasting (failed, see evidence), login, multi-user, WhatsApp or email sending, payments, mobile app.

## Mapping to the judging criteria
| Criterion | Plan | Risk |
|---|---|---|
| Real-World Impact | Clear persona, honest "not yet validated by a real user" | **High.** Weakest criterion |
| Technical and AI use | LLM for column mapping, explanation, drafts. Code for model and audit | Medium. LLM role must be real, not decoration |
| Innovation | Audit plus refusal plus messy input | Medium. The model itself is standard |
| Execution | Three screens, end to end, deployed | Medium |
| Presentation | 3-minute video, README with failures named | Low if time is protected |

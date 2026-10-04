# 01 Product requirements

## One line
Turn a raw sales export into a weekly list of customers worth contacting, and show how often the predictions were right.

## Problem
Small B2B sellers keep sales history in exports and spreadsheets, but rarely know which regular customers are about to go quiet.
Evidence level: **Weak.** No interviews. Only a general survey (Forrester, 2020: 41% of business leaders find turning data into decisions very or extremely challenging; sample size not stated, not specific to small businesses).

## Persona (stand-in, not a validated user)
Owner or sales lead of a small wholesaler who sells to repeat business customers and has an export from their sales tool.

## The one decision
"Which customers should I contact this week?"

## Core flow
1. **Upload** an export with any column names. An LLM proposes a mapping to the standard schema. The user confirms.
2. **Contact list.** Customers ranked by the probability of ordering again within 8 weeks. Each row has a reason that cites the customer's own orders, and an optional draft follow-up message.
3. **Audit.** On the user's own history: top-20% hit rate vs the base rate vs a simple recency rule. Customers with fewer than 2 orders are not scored, with the reason shown. If the model does not beat the simple rule on this data, the app says so and recommends the simple rule.

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

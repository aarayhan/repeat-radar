# 03 Evidence (measured on 2026-10-04)

Dataset: UCI Online Retail II. 1,067,371 rows, Dec 2009 to Dec 2011, UK online gift-ware retailer, CC BY 4.0. Verified against the UCI page.
Scripts: `experiments/`. Limits: one dataset, B2B wholesale, intermittent demand. Code not yet reviewed by a second person.

## A. Stock forecasting per product: did NOT hold up
Weekly units per product, 1-week horizon. Gate decided on a 12-week validation window, evaluated on the next 12 weeks. Three windows: A (Sep-Nov 2011), B (Jun-Aug 2011), C (Mar-May 2011).

| Experiment | Gate-passed products beat baseline (A / B / C) | Refused products beat baseline (A / B / C) |
|---|---|---|
| Best of 5 models per product, baseline = same as last week | 71% / 67% / 57% | 77% / 75% / 68% |
| Same, baseline = best of last week or 4-week average | 51% / 50% / 43% (aggregate error 8% / 5% / 19% worse than baseline) | 63% / 63% / 61% |
| One fixed smoothing model, consistency gate, weak baseline | 83% / 78% / 70% | 77% / 73% / 65% |
| Same, strong baseline | 66% / 62% / 60% | 69% / 66% / 60% |

Other findings:
- 80% prediction interval covered the truth only 68% / 72% / 79% of the time (A / B / C). Intervals were 1.7 to 3.1 times the mean weekly level.
- Yearly seasonality as a forecast was 1.3 to 1.6 times worse than the baseline.
- At total-weekly-units level, no model consistently beat a 4-week average.
- About 55% of products sold in fewer than 20 of the previous 52 weeks and are too sparse to forecast.
- Inference: picking a winner from several models on a short window captures luck.

## B. Customer repeat purchase: signal exists
Question: of customers with at least 2 prior orders, who orders again within 56 days.

| Origin | Customers | Base rate | AUC model vs recency rule | Top-20% hit rate model vs recency rule |
|---|---|---|---|---|
| 14 Oct 2011 | 3,859 | 43% | 0.765 vs 0.712 | 80% vs 63% |
| 15 Jul 2011 | 3,534 | 31% | 0.810 vs 0.751 | 71% vs 57% |
| 15 Apr 2011 | 3,221 | 35% | 0.779 vs 0.727 | 74% vs 59% |

Not yet tested: calibration, other datasets, real users.

## C. Competitor note (for the README)
Standard customer repeat-purchase models are common. Our claim is the audit, the refusal, and the messy input, not the model.

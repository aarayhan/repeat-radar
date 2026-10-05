# 03 Evidence (measured on 2026-10-04; sections D-F added in H2/H3, G in H4)

Dataset: UCI Online Retail II. 1,067,371 rows, Dec 2009 to Dec 2011, UK online gift-ware retailer, CC BY 4.0. Verified against the UCI page.
Scripts: `experiments/` (A, B), `scripts/calibration.py` (D), `scripts/audit_uci.py` (E, F). Limits: one dataset, B2B wholesale, intermittent demand. Code not yet reviewed by a second person.

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

Reproduced exactly by `app/` (engine and audit modules) in H2 and H3. Verified.
Not yet tested: other datasets, real users. Calibration: section D.

## C. Competitor note (for the README)
Standard customer repeat-purchase models are common. Our claim is the audit, the refusal, and the messy input, not the model.

## D. Calibration: fine on average, off in the most recent window (H2)
Same 3 test windows, 10 probability bins. The threshold was fixed before the run (pooled ECE > 0.05, or a bin with 100+ customers off by more than 10 points).
- Pooled: ECE 0.030, Brier 0.177. Customers scored 0.6-0.8 (n = 995): predicted 0.689 on average, 0.742 actually reordered. Verified.
- Per window, the ECE was 0.089 (Oct 2011), 0.023 (Jul 2011) and 0.018 (Apr 2011).
  - Oct 2011: base rate 0.433, mean prediction 0.344. Three bins were under-predicted by more than 10 points. Verified.
  - Inference: the pre-Christmas base-rate jump is not in the features.
- Consequence: the app shows rank tiers with measured hit rates, not probabilities (section E). Details in `docs/H2_REPORT.md`.

## E. Tiers and refusals on the demo data (H3)
- Tiers are by rank: high = top 20%, medium = 20-50%, low = rest. The hit rate is the share who ordered within 56 days, across the 3 test windows.
- The base rate in those windows was 0.313-0.433. Verified.

| Tier | Model: min-max (pooled) | Recency rule: min-max (pooled) |
|---|---|---|
| High | 0.708-0.803 (0.752) | 0.571-0.630 (0.599) |
| Medium | 0.379-0.504 (0.429) | 0.423-0.583 (0.494) |
| Low | 0.116-0.242 (0.177) | 0.144-0.264 (0.200) |

- The model beats the recency rule on top-20% hit rate in all 3 windows, so the app uses the model (rule 3 not triggered). Verified.
- The recency rule does better in the **medium** tier (0.494 vs 0.429 pooled). The model's advantage is concentrated at the top. Verified. Why: Unknown.
- Current list (day after the last order): 4,255 customers scored (851 high, 1,276 medium, 2,128 low). 1,623 not scored, with the reason "only 1 order in the file". Verified.
- Refusal rule 2 (insufficient history) is triggered by a 300-day synthetic file. The message is "file covers 291 days; 2 windows need at least 371". Verified (unit test).
- The UCI "invoice starts with C" rule was dropped. All 19,494 'C' lines already have quantity ≤ 0, and the cleaned result is identical (36,969 invoices). Verified.

## F. Column mapping (H3)
- The rule-based mapping maps the real UCI columns correctly, and its values pass the checks on the first 1,000 lines. Verified.
- It also maps two synthetic formats correctly, end to end to invoices (unit tests). Verified, but synthetic only:
  - an Indonesian POS export (`No Nota, Tanggal, Kode Pelanggan, Jml, Harga Satuan`);
  - an e-commerce export (`Order Number, Order Date, Customer No, Qty Ordered, Unit Price`).
- The value checks catch an LLM answer whose names are valid but whose columns are swapped, and fall back to the rules. Verified with a fake LLM.
- **A real LLM has never been called.** There is no API key and no account, and no local model is available. Whether Featherless (or any provider) returns valid mappings is Unknown.
- The rules map the short names `Tgl`, `No Nota`, `Pelanggan`, `Qty` and `Total` correctly; `Total` becomes the optional `line_total`.
  - `Total` is never mapped to price. The rules do not do it, and the value check rejects an LLM answer that does (fake LLM). Verified (unit tests).

Date reading in text columns, `parse_dates` in `app/engine.py`. Verified by unit tests on synthetic values:
- Year-first dates (`2009-12-01`, `2009/12/01 07:45`) are read as year-month-day.
- Year-last dates (`05/01/2030`, `05-01-2030`, `05.01.2030`):
  - a first part above 12 means day-first;
  - a second part above 12 means month-first;
  - both in one column: the file is refused, and the message names an example row of each;
  - neither: read as day-first, with a warning.
- 2-digit years are refused ("use 4-digit years").
- Unreadable values: up to 1% of rows are dropped with a warning that gives the count; more than 1% refuses the file.
- A column that mixes datetime cells and text cells gets one warning with both counts. Parsing of that column is unchanged.
- Datetime columns are not touched.
  - UCI dates load as datetime. The cleaned UCI result is identical to H2 (36,969 invoices) and has no warnings.

Remaining limits:
- Dates Excel has already misread (day and month swapped) cannot be recovered.
  - A column that mixes datetime and text cells gets a warning.
  - A column Excel converted entirely to dates gets no warning, because the swap cannot be seen from the values.
- A file with `Qty` and `Total` but no unit price is refused ("missing required keys: ['price']").
- Exports with only a line total are not supported (`04_DECISIONS.md` decision 11).
- The synonym list is finite.

## G. Audit on the two sample files (H4). Synthetic data, not real-world evidence
- The files were generated by `scripts/make_sample_data.py` (seed 42): 300 made-up customers each, Jan 2023 to Dec 2024.
- Customers have their own buying rates, about half stop buying at some point, and about 15% buy once. The generator was not tuned to favor the model.
- Numbers below are from the app's own code, as shown on screens 2 and 3. They only show that the pipeline runs end to end. They say nothing about real businesses.

**Indonesian POS (`kasir_indonesia.csv`).** 3,216 invoices; 72 customers not scored (1 order).

| Window starts | Customers | Base rate | AUC model / recency | Top-20% hit model / recency |
|---|---|---|---|---|
| 2024-11-05 | 209 | 50% | 0.850 / 0.844 | 90% / 80% |
| 2024-08-06 | 179 | 56% | 0.835 / 0.817 | 86% / 86% |
| 2024-05-07 | 151 | 67% | 0.852 / 0.867 | 97% / 97% |

- **Method chosen: recency rule.** The model only tied the recency rule on top-20% hit rate in 2 of 3 windows, and a tie counts as a loss (rule 3).
- Tier hit rates, pooled (min to max), recency rule: high 87% (80-97%), medium 79% (75-89%), low 32% (23-42%).
- For the model: high 91%, medium 75%, low 32%.

**E-commerce (`ecommerce.csv`).** 3,428 invoices; 63 customers not scored (1 order).

| Window starts | Customers | Base rate | AUC model / recency | Top-20% hit model / recency |
|---|---|---|---|---|
| 2024-11-05 | 219 | 45% | 0.864 / 0.858 | 86% / 77% |
| 2024-08-06 | 182 | 56% | 0.785 / 0.810 | 92% / 86% |
| 2024-05-07 | 157 | 66% | 0.803 / 0.756 | 90% / 77% |

- **Method chosen: model.** It beat the recency rule on top-20% hit rate in all 3 windows.
- Its AUC was lower than recency's in the Aug 2024 window.
- Tier hit rates, pooled (min to max), model: high 89% (86-92%), medium 70% (62-85%), low 32% (18-46%).
- For the recency rule: high 80%, medium 80%, low 29%.

In both files the recency rule had the higher medium-tier hit rate, as on UCI (section E). Verified on synthetic data only.

## H. Locked customer holdout on UCI (2026-10-05)
- Split: salted hash of the customer id, 20% holdout (`app/engine.is_holdout`): 4,718 development customers and 1,160 holdout customers.
- Same 3 origins and the same method as table B. Script: `scripts/holdout_eval.py`.

| Window | All customers (table B): n, base, AUC model/recency, top-20% model/recency, ECE | Development 80% | Holdout 20% (run once) |
|---|---|---|---|
| 14 Oct 2011 | 3,859, 0.433, 0.765/0.712, 0.803/0.630, 0.089 | 3,092, 0.433, 0.768/0.716, 0.806/0.644, 0.087 | 767, 0.433, 0.757/0.694, 0.817/0.588, 0.099 |
| 15 Jul 2011 | 3,534, 0.313, 0.810/0.751, 0.708/0.571, 0.023 | 2,824, 0.321, 0.816/0.758, 0.725/0.589, 0.021 | 710, 0.282, 0.786/0.718, 0.648/0.514, 0.066 |
| 15 Apr 2011 | 3,221, 0.349, 0.779/0.727, 0.738/0.592, 0.018 | 2,580, 0.347, 0.782/0.727, 0.746/0.579, 0.025 | 641, 0.357, 0.761/0.733, 0.695/0.633, 0.027 |

Tier hit rates, pooled (min-max):

| | High | Medium | Low |
|---|---|---|---|
| Development, model | 0.761 (0.725-0.806) | 0.432 (0.387-0.509) | 0.176 (0.120-0.239) |
| Holdout, model | 0.735 (0.669-0.818) | 0.418 (0.326-0.502) | 0.189 (0.108-0.259) |
| Holdout, recency rule | 0.557 (0.500-0.602) | 0.494 (0.382-0.598) | 0.204 (0.128-0.282) |

On the holdout, the cutoffs come from development scores and the model is fit on development customers only.

- On the holdout, the model beats the recency rule on top-20% hit rate in all 3 windows, so rule 3 is not triggered. Verified.
- The holdout is a little weaker than development in Jul and Apr 2011 (top-20% 0.648 vs 0.725, 0.695 vs 0.746). Its calibration error is higher in every window (ECE 0.099 / 0.066 / 0.027). Verified.
- Again the recency rule has the higher medium-tier hit rate (0.494 vs 0.418). Verified.
- Limits:
  - Oct 2011 was already seen during design.
  - The data ends Dec 2011, so no later, time-based holdout is possible. This holdout separates customers, not time.
  - The holdout is one public dataset; n = 641 to 767 customers per window.

## I. Verified LLM drafts on UCI (2026-10-05)
Setup: Qwen2.5-7B on Featherless, 50 development customers (seed 42). Details and raw output: `docs/H2_REPORT.md` section 6.
- Results: 28 of 50 passed the verifier on the first try, 0 passed after repair, 22 were rejected (template shown).
- No JSON failures and no API errors; 2.8 s per draft on average. Verified.
- All 22 rejections were false positives of the banned-word list ("feel free" 19, the verb "offer" 3). No invented number, date or product was found. Verified.
- The single repair attempt returned the identical text in 21 of 22 cases at temperature 0, so the repair as built does not work. Verified.
- 17 of the 28 passing drafts used no specific fact (no number, date or exact product name). Verified.
- Unknown: the verifier cannot see paraphrased product names. It has not been tested in Indonesian or with other models.

## J. Holdout intervals (2026-10-05)
Paired bootstrap, 1,000 resamples per window, on the saved holdout predictions. The holdout was reproduced once with frozen code and matched exactly (`04_DECISIONS.md` decision 13).

| Window | Holdout customers / in top 20% | Top-20% hit, model minus recency | 95% interval |
|---|---|---|---|
| Oct 2011 | 767 / 153 | +0.229 | +0.157 to +0.314 |
| Jul 2011 | 710 / 142 | +0.134 | +0.063 to +0.232 |
| Apr 2011 | 641 / 128 | +0.062 | -0.023 to +0.164 |

The model's win on the holdout is clear in Oct and Jul 2011. **It is not conclusive in Apr 2011.** Verified.

# H2 report (2026-10-04, branch `h2-engine`, not pushed)

Status: **stopped at step 3.** The Featherless smoke test could not run because there is no `.env` / `FEATHERLESS_API_KEY`. Steps 1 and 2 are done.

## 1. Engine moved to `app/` (works)
- `app/engine.py`: `load_uci`, `clean`, `features`, `fit`, `predict`, `backtest`, `top_k_hit`, `calibration`, `ece`. Same method as `experiments/customer_repeat.py`.
- `tests/test_engine.py`: 6 tests covering the cleaning rules, feature values, the label window boundaries, no leakage from future invoices, top-k hit rate, and the calibration bins.
- Faithfulness check on the real data: the refactor reproduces `brain/03_EVIDENCE.md` table B exactly.

| Origin | n | Base rate | AUC model / recency | Top-20% hit model / recency |
|---|---|---|---|---|
| 2011-10-14 | 3,859 | 0.433 | 0.765 / 0.712 | 0.803 / 0.630 |
| 2011-07-15 | 3,534 | 0.313 | 0.810 / 0.751 | 0.708 / 0.571 |
| 2011-04-15 | 3,221 | 0.349 | 0.779 / 0.727 | 0.738 / 0.592 |

Tests: **19 passed** (`pytest tests -q`, engine + LLM validator).

## 2. Calibration (mixed result, reported as is)
Method: the same 3 backtest origins. Predictions go into 10 equal-width bins, comparing predicted vs observed rate. ECE is the count-weighted mean |gap|.
Threshold fixed before the run: **bad if pooled ECE > 0.05, or any bin with ≥ 100 customers is off by > 10 percentage points.** No change to the method after seeing results.

**Pooled verdict: OK.** n = 10,614, ECE = 0.030, Brier = 0.177, mean predicted 0.338 vs base rate 0.368.

**The "70%" question:** customers scored 0.6–0.8 (n = 995) had a mean prediction of 0.689 and actually reordered 0.742 of the time. A "70%" is right a bit more than 70% of the time. The model is slightly under-confident, not over-confident.

Pooled bins:

| Bin | n | Predicted | Observed | Gap |
|---|---|---|---|---|
| 0.0-0.1 | 1220 | 0.073 | 0.108 | +0.036 |
| 0.1-0.2 | 2540 | 0.149 | 0.163 | +0.014 |
| 0.2-0.3 | 1945 | 0.249 | 0.269 | +0.021 |
| 0.3-0.4 | 1434 | 0.347 | 0.376 | +0.029 |
| 0.4-0.5 | 1085 | 0.447 | 0.493 | +0.046 |
| 0.5-0.6 | 816 | 0.547 | 0.599 | +0.052 |
| 0.6-0.7 | 564 | 0.646 | 0.695 | +0.049 |
| 0.7-0.8 | 431 | 0.746 | 0.803 | +0.057 |
| 0.8-0.9 | 308 | 0.849 | 0.886 | +0.037 |
| 0.9-1.0 | 271 | 0.952 | 0.956 | +0.003 |

**Per origin (the pooled number hides this):**

| Origin | Base rate | Mean predicted | ECE | Brier | Bins failing the rule |
|---|---|---|---|---|---|
| 2011-10-14 | 0.433 | 0.344 | **0.089** | 0.200 | **3** (0.1-0.2 +0.103, 0.4-0.5 +0.106, 0.5-0.6 +0.118) |
| 2011-07-15 | 0.313 | 0.325 | 0.023 | 0.155 | 0 |
| 2011-04-15 | 0.349 | 0.344 | 0.018 | 0.174 | 0 |

- At the most recent origin (Oct 2011, the pre-Christmas window), the base rate jumped to 43% but the model was trained on earlier windows and predicted 34% on average. Every bin under-predicts, by up to 12 percentage points. Inference: seasonality / base-rate shift, which the features do not capture.
- The pre-set rule was defined on the pooled result, so the formal verdict is OK. Taken on its own, the most recent window would fail it. Nothing was changed to make this look better.
- Suggested claim wording (not applied, for H3): "Ranking is reliable across 3 windows. Probabilities were well calibrated in 2 of 3 windows and too low by about 9 points on average in the pre-Christmas window." Showing calibration per window in the audit screen fits the existing audit design.

## 3. Featherless smoke test (did not run)
- Code is ready. `app/llm.py` has `validate_mapping` (strict `json.loads`, must be an object, required keys `customer_id, invoice_id, date, quantity, price`, optional `country, product`, values must be real column names, no duplicates, no unknown keys). `map_columns` makes one call plus one repair attempt, then fails visibly. The validator and the repair loop are unit-tested with a fake client (13 tests).
- `scripts/smoke_featherless.py` result: `FAIL: FEATHERLESS_API_KEY is not set (.env)`. No API call was made. **Whether Featherless returns valid JSON on `Qwen/Qwen2.5-7B-Instruct` is still unknown.**
- The sample rows in the smoke test are synthetic.

## Other changes on the branch
- `brain/`, `experiments/` and `CLAUDE.md` moved from the nested `repeat-radar/repeat-radar/` to the repo root.
- `.gitignore.append` merged into `.gitignore` (data, `.csv`, `.xlsx`, `.env`), plus `*.zip`. Before this, raw data was not ignored.
- `pytest` added to `requirements.txt`.
- The UCI data was downloaded to `data/`, and a cleaned invoice cache was written to `data/invoices.csv`. Both are gitignored and not committed.

## Commands to repeat (from the repo root)
```
uv venv .venv
uv pip install -p .venv -r requirements.txt
.venv\Scripts\python -m pytest tests -q
.venv\Scripts\python scripts\calibration.py        # downloads UCI data if missing; first run reads the xlsx (several minutes)
# create .env with FEATHERLESS_API_KEY=... (optional FEATHERLESS_MODEL=...), then:
.venv\Scripts\python scripts\smoke_featherless.py  # exit 0 = PASS, 1 = failed twice / no key, 2 = valid JSON but wrong mapping
```

---

# H2-trust update (2026-10-05, branch `h2-trust`, not pushed)

## 4. Featherless smoke test (now run, 5 times)
`scripts/smoke_featherless.py`, model `Qwen/Qwen2.5-7B-Instruct`, temperature 0. The input was the UCI column names plus 3 synthetic rows. The key was redacted from the output (none appeared).

| Run | Valid JSON (schema) | Mapping correct | Wall time (incl. ~1.7 s Python startup) |
|---|---|---|---|
| 1 | yes, first attempt | yes (product → StockCode) | 6.5 s |
| 2 | yes, first attempt | **no**: invoice_id → `StockCode` | 9.9 s |
| 3 | yes, first attempt | **no**: invoice_id → `StockCode` | 5.4 s |
| 4 | yes, first attempt | yes | 4.9 s |
| 5 | yes, first attempt | yes | 4.7 s |

- **5 of 5 valid JSON, 3 of 5 correct mappings.**
- The wrong runs pass the app's value checks, because `StockCode` is a non-empty column. The user-confirm step on screen 1 is therefore the real safeguard.
- Raw reply of run 2, as printed:
  `{"customer_id": "Customer ID", "invoice_id": "StockCode", "date": "InvoiceDate", "quantity": "Quantity", "price": "Price", "country": "Country", "product": "Description", "line_total": null}`
- Temperature 0 did not make the answer deterministic.
- No change was made after seeing this.

## 5. Locked holdout (customer level)
Method: see `brain/04_DECISIONS.md` decision 12 and `brain/03_EVIDENCE.md` H. 20% of customers by salted hash; 4,718 development customers, 1,160 holdout customers. The holdout was run once.

Real output, `python scripts/holdout_eval.py --dev`:
```
== ALL CUSTOMERS (old table B) | status ok | ranker model (model beat the recency rule on top-20% hit rate in all 3 test windows)
    origin    n  base_rate  auc_model  auc_recency  top20_model  top20_recency   ece
2011-10-14 3859      0.433      0.765        0.712        0.803          0.630 0.089
2011-07-15 3534      0.313      0.810        0.751        0.708          0.571 0.023
2011-04-15 3221      0.349      0.779        0.727        0.738          0.592 0.018
high 0.708-0.803 pooled 0.752 | medium 0.379-0.504 pooled 0.429 | low 0.116-0.242 pooled 0.177

== DEVELOPMENT ONLY (80%) | status ok | ranker model (model beat the recency rule on top-20% hit rate in all 3 test windows)
    origin    n  base_rate  auc_model  auc_recency  top20_model  top20_recency   ece
2011-10-14 3092      0.433      0.768        0.716        0.806          0.644 0.087
2011-07-15 2824      0.321      0.816        0.758        0.725          0.589 0.021
2011-04-15 2580      0.347      0.782        0.727        0.746          0.579 0.025
high 0.725-0.806 pooled 0.761 | medium 0.387-0.509 pooled 0.432 | low 0.120-0.239 pooled 0.176
```
(tier lines condensed from the printed tier tables, same numbers)

Real output, `python scripts/holdout_eval.py --holdout` (run once, 2026-10-05T11:12:58):
```
== HOLDOUT (20%, 1160 customers): model fitted on development customers only
    origin   n  base_rate  auc_model  auc_recency  top20_model  top20_recency   ece
2011-10-14 767      0.433      0.757        0.694        0.817          0.588 0.099
2011-07-15 710      0.282      0.786        0.718        0.648          0.514 0.066
2011-04-15 641      0.357      0.761        0.733        0.695          0.633 0.027

tiers on holdout, ranker=model (cutoffs from development scores):
           n   min   max  pooled
high     385 0.669 0.818   0.735
medium   655 0.326 0.502   0.418
low     1078 0.108 0.259   0.189

tiers on holdout, ranker=recency (cutoffs from development scores):
           n   min   max  pooled
high     418 0.500 0.602   0.557
medium   624 0.382 0.598   0.494
low     1076 0.128 0.282   0.204

rule 3 on holdout: model beats recency on top-20% hit in every window: True
```
- The model holds up on unseen customers. It is weaker than development in Jul and Apr, and its calibration is worse in every window.
- Limits:
  - the Oct 2011 window was seen during design;
  - the data ends Dec 2011, so no time-based holdout is possible;
  - this is one dataset.

## 6. Verified follow-up drafts (`app/drafts.py`)
**What was reused** from `app/explain.py`:
- the date logic of `customer_facts`;
- the "LLM words it, code checks it, template on failure" pattern, with a source label;
- the `(client, model)` tuple from `app/llm.client()`;
- `FakeLLM` in the tests.

**Facts object** (code only), the only content a draft may use:
- customer id;
- last order date;
- days since the last order;
- up to 3 usual products (bought in the most distinct invoices);
- typical gap (median days between orders);
- tier;
- the tier's measured hit rate (development data).

**Verifier** (code). For each draft it checks:
- every number is one of the facts (days, gap, hit-rate %, year, customer id), including the number words two to twelve, dozen and hundred;
- every date (ISO, numeric, or with a month name) is the last order date;
- no product name from the data's catalogue (5,198 names, at least 8 characters) appears unless it is one of the usual products;
- no word from this explicit list appears (whole words, case-insensitive):

> discount, off, sale, free, complimentary, gift, voucher, coupon, promo, promotion, offer, deal, deals, price, prices, priced, pricing, cheap, cheaper, cost, save, saving, savings, £, $, €, stock, restock, restocked, available, availability, limited, deadline, expire, expires, expiry, last chance, hurry, until, ends, guarantee, guaranteed, delivery, deliver, shipping, ship, new arrival, new arrivals, exclusive, tomorrow, next week, this week, weekend, monday, tuesday, wednesday, thursday, friday, saturday, sunday

When a draft fails, there is one repair call that passes the verifier's errors back. If it still fails, the plain template is shown, labeled `template`.

**Evaluation:** `python scripts/draft_eval.py`, Qwen2.5-7B on Featherless, temperature 0. The sample was 50 development customers (seed 42; no holdout customers): 8 high, 12 medium and 30 low tier. Real output:
```
model Qwen/Qwen2.5-7B-Instruct | ranker model | 50 development customers, seed 42 | catalogue 5198 products
passed first try: 28 of 50 | passed after repair: 0 of 50 | rejected (template shown): 22 of 50 | API errors (template shown): 0
JSON failures: 0 replies in 0 drafts | LLM calls: 72
seconds per draft: mean 2.8, median 3.1, max 5.9
verifier reasons on first attempts: {'promise or claim outside the facts': 22}
```
**3 worst failures.** Customer ids are redacted; product names are from the public catalogue. The repair returned the same text in all three.
1. `"Hi there! It's been a while since your last order. We hope you're doing well. Feel free to reach out if you're ready to place another order."`. Verifier: `promise or claim outside the facts: 'free'`.
2. `"... Feel free to drop by again if you need any of your usual products like the cake stand or fairy cake cases."`. Verifier: `'free'`.
3. `"... We noticed you ordered with us last on December 5, 2011. We'd love to have you back and offer your usual products like LIGHT GARLAND BUTTERFILES PINK and SET 7 BABUSHKA NESTING BOXES. Drop by anytime!"`. Verifier: `'offer'`.

**Reading of the result:**
- **All 22 rejections are false positives of the keyword list, not real errors.** 19 came from the idiom "feel free" and 3 from "offer" used as a verb. On a first attempt the verifier found no invented number, date or product, and no real promise.
- **The repair did not work.** At temperature 0, 21 of the 22 repair replies were identical to the first reply.
- **Most passing drafts are generic.** Of the 28, only 6 contain a number or date and 8 an exact usual-product name; 17 contain neither.
- No change was made after seeing these results.
- Possible fixes, to decide before any re-run:
  - allow "feel free" and the verb "offer";
  - repair at a non-zero temperature, or with a stronger instruction;
  - require at least one fact in the draft.
- Not tested:
  - drafts in Indonesian;
  - other models;
  - paraphrased product names (for example "cake stand"), which the verifier cannot detect;
  - the drafts are not yet wired into the Streamlit UI, which still shows the template draft.

Full drafts with customer ids are in `data/draft_eval.json` and the printed output in `data/draft_eval_output.txt` (both gitignored).

## 7. Holdout reproduction and bootstrap intervals (2026-10-05)
**Reproduction.** The single holdout run had saved only aggregates. It was reproduced once to save per-customer predictions (`brain/04_DECISIONS.md` decision 13):
- frozen code: a git worktree at `04ebc87`, removed afterwards;
- the same venv: python 3.13.14, numpy 2.5.3, pandas 3.0.6, scikit-learn 1.9.1. The original run did not record versions, so they cannot be compared; the venv was not changed in between;
- the same `data/invoices.csv` (sha256 `d6b43cfa242f2cb293d29f18cbd0ca52cd297551140eff00ef945568ada3821e`, last modified 2026-10-04);
- `scripts/holdout_reproduce.py`, which never touches the marker.

Result: all 21 printed lines match the original output exactly (n, base rate, AUC, top-20% hit rates, ECE, tier tables, rule 3 line). The script printed them side by side; every line is marked `|` (equal).
```
RESULT: EXACT MATCH on all 21 lines. Wrote holdout_predictions.csv (2118 rows), sha256 c6f733af5d13fb87e933290813560db1934191e5b41b9418a32029d9cb0e325c
```
`data/holdout_predictions.csv` is gitignored. SHA-256: `c6f733af5d13fb87e933290813560db1934191e5b41b9418a32029d9cb0e325c`.

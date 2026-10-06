# 04 Decisions

Format: date, decision, reason, evidence level.

## 2026-10-04
1. **Track: AI + Business.** Prompt: "turns business data into clear insights, predictions, or recommendations that help people make better decisions." Verified (Participant Packet).
2. **Dropped: boarding-house late-payment advisor.** Payments in the owner's data were 98.5% collected and on average about 50 days early. Verified from the owner's dashboard (not committed).
3. **Dropped: boarding-house vacancy promise and expense insight.** Pain is weak and expenses are not recorded by staff for reasons unknown. Verified (dashboard) and Weak (staff answer, no reason).
4. **Dropped: halal self-declare copilot.** A direct competitor exists (SmartHalal, "AI SJPH Builder", free for the self-declare route), and the idea does not fit the track prompt. Verified (competitor site). The fine of up to Rp2 billion was not confirmed on the BPJPH page we fetched: Weak source.
5. **Dropped: per-product stock forecasting.** Failed out-of-sample, see `03_EVIDENCE.md` section A. Verified (our experiment).
6. **Chosen: customer follow-up decision.** Only decision with a measured signal in three time windows. Verified (our experiment). Real-World Impact remains weak and is stated openly.
7. **Real user.** None reachable in the first 24 hours. If a real business with customer data replies before Tue Oct 6, swap the beneficiary and keep the engine. Otherwise ship with the stand-in persona and say so.
8. **Mentor.** One ticket sent on Discord with the stock result and the question about when practitioners trust a forecast. Answer is a bonus, not a dependency.
9. **UI: Streamlit.** Fastest for a solo builder with a weak UI background. Recommendation, revisit if blocked.
10. **Sponsor tools.** Featherless for LLM calls. n8n optional. Others skipped. None are required by the rules.
11. **Not supported yet: exports with only a line total (no quantity and no unit price).**
    - What happens now: the mapping recognizes the total column (`line_total`), but price is a required field, so the app refuses the file with "missing required keys: ['price']" instead of guessing.
    - Reasons:
      - The engine is built and verified on quantity × price. It uses quantity ≤ 0 to drop returns and cancellations, and price ≤ 0 to drop free or zero lines. With only a total, those rules would have to be rebuilt on the sign of the total and re-verified.
      - We have seen no real export of this shape (no real user yet; decision 7). Building for it would be guessing at a format.
      - Feature freeze is at the end of H5, and the time goes to the three screens.
    - Evidence: Inference. Revisit if a real user's export has this shape.

## 2026-10-05
12. **Locked customer holdout (mentor advice).**
    - 20% of customers are held out by a salted hash of the customer id (`app/engine.is_holdout`, salt `repeat-radar-holdout-v1`). The salt never changes.
    - Holdout customers are excluded from fitting, tier cutoffs, calibration checks, and every decision from now on. All future decisions use development (80%) numbers only.
    - The holdout was run once on 2026-10-05, after the method was fixed; `data/holdout_used.txt` blocks a second run. Result: the model still beat the recency rule in all 3 windows (`03_EVIDENCE.md` H). Nothing was changed after seeing it.
    - Limits:
      - the Oct 2011 window was already seen while designing the method;
      - the data ends Dec 2011, so a later, time-based holdout is impossible. This holdout is by customer, not by time.
    - Evidence: Verified (our experiment).
13. **Holdout reproduced once with frozen code (2026-10-05), only to save per-customer predictions.**
    - The single holdout run had saved only aggregates. On the owner's instruction it was reproduced once:
      - from a git worktree at commit `04ebc87`, the code of the original run;
      - with the same venv and the same `data/invoices.csv`, unchanged since 2026-10-04;
      - by `scripts/holdout_reproduce.py`.
    - All 21 printed lines matched the original output exactly, so the predictions were accepted: `data/holdout_predictions.csv`, 2,118 rows, sha256 `c6f733af5d13fb87e933290813560db1934191e5b41b9418a32029d9cb0e325c`.
    - The marker `data/holdout_used.txt` was not touched.
    - The per-customer rows are used only for the bootstrap intervals (`docs/H2_REPORT.md` section 7), and for nothing else.

## 2026-10-06
14. **Message intent thresholds are simple rules, not validated.**
    - not_due below 0.8 × the customer's usual gap; due from 0.8 to 1.5 ×; overdue above 1.5 ×; lapsed after 365 days.
    - No experiment supports these exact numbers. Evidence: Inference.
15. **Prediction, not causation.** The tool predicts who is likely to reorder within 8 weeks. It does not claim that contacting a customer causes a reorder; no experiment has tested that. Evidence: Unknown.
16. **Draft verifier frozen for deploy.** No new rules after this date. The code guarantees every fact in a draft is true. It does not judge tone; drafts are for the owner to edit before sending.

## Open questions
- Is the model calibrated? Answered in H2: on average yes, not in the most recent window (`03_EVIDENCE.md` D, H).
- Does Featherless support reliable structured JSON on the chosen model? Partly answered 2026-10-05: 5 of 5 smoke runs returned valid JSON, but 2 of 5 mapped the invoice id to the wrong column (`docs/H2_REPORT.md`).
- Is an optional kos dataset usable as a refusal example? Needs the owner's permission and anonymization. Not committed.

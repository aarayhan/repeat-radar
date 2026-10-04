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

## Open questions
- Is the model calibrated? Test in H2.
- Does Featherless support reliable structured JSON on the chosen model? Test in H2.
- Is an optional kos dataset usable as a refusal example? Needs the owner's permission and anonymization. Not committed.

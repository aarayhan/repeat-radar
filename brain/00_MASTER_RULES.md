# 00 Master rules

## Hackathon rules that bind us (ForgeHacks 2026, track AI + Business)
- Build window: Oct 3-10, 2026. Submissions lock Sat Oct 10, 12:00 PM ET (= 23:00 WIB).
- Our own target: submit by 18:00 WIB on Oct 10. Winners are announced Mon Oct 12, 3:00 PM ET.
- A project started before kickoff is not eligible. Libraries, frameworks and boilerplate are fine.
- AI tools are allowed. Be clear about what we built, what we used, and what actually runs.
- Submission needs: what we built and the problem, the track, a demo video OR a live link, the code repo, and what works and what does not.
- "A half-working project is okay. Overstating isn't. Judges will test what you submit."
- Criteria (20% each): Real-World Impact, Technical Implementation and AI Use, Innovation, Execution and Completeness, Presentation.

## Engineering rules
1. **Code does the math.** Features, model, backtest, metrics: pandas and scikit-learn. The LLM never produces a number that is shown as a result.
2. **LLM output is validated.** Structured output goes through a schema check. One repair attempt, then fail visibly.
3. **Refuse when evidence is weak.** The app must say "not scored" with a reason instead of guessing.
4. **Every claim has a label** in docs and README: Verified, Weak source, Inference, Unknown.
5. **No secrets in git.** Keys live in `.env`. No raw datasets. No real customer or tenant data, even anonymized.
6. **No new features after the end of H5.** H6 and H7 are for testing, README, video, submission.
7. **No login, no multi-user, no WhatsApp integration.** Out of scope.

## Honesty rules for the README
- State that no real user has validated the product yet (unless that changes).
- Name the failures found in `03_EVIDENCE.md`.
- State the dataset, its license, and its limits.
- State that AI coding assistants were used.

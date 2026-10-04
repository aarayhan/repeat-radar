# Repeat Radar: instructions for Claude Code

Read `brain/` before changing anything. Start with `brain/00_MASTER_RULES.md`.

- Product spec: `brain/01_PRD.md`
- Architecture, model and audit design: `brain/02_ARCHITECTURE.md`
- Measured evidence (what worked, what failed): `brain/03_EVIDENCE.md`
- Why we decided things: `brain/04_DECISIONS.md`
- Daily plan: `brain/05_MICROTASKS.md`

Hard rules (details in MASTER_RULES):
1. All numbers come from code. The LLM never calculates.
2. Never overstate. If something does not work, say so in the README.
3. Never commit secrets, raw datasets, or real customer data.
4. Do not reuse code from earlier projects. This repo was started after the hackathon kickoff.
5. Feature freeze at the end of H5 (Thu Oct 8).

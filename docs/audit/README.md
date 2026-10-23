# Audit and remediation records

These are records of the audit of baseline commit `814f90b`, and of the plans for fixing what it found. They were moved here from a temporary working directory so they aren't lost.

| File | Contents |
|---|---|
| `HANDOFF.md` | Summary of the audit and the decisions made |
| `LEDGER.md` | Tier 0–2 validation ledger: each finding confirmed, refuted or inconclusive, with its evidence |
| `REMEDIATION_PLAN.md` | Workstreams WS1–WS6 and the owner decisions |
| `IMPLEMENTATION_PLAN.md` | Policies P-1 to P-6, stages A0–A10 and M1–M4, and Tier 3 |
| `IMPLEMENTATION_PLAN_REVIEW.md` | Amendments A–D to the owner's revised plan, which is the plan in force |
| `evidence/tier{0,1,2}/` | Raw outputs: tier JSON, pytest logs, pip freezes, integrity hashes |
| `harness/tier{0,1,2}/` | The scripts used to run the audit checks offline, outside the repository |

## Decisions (2026-10-23)
- All work happens on branch `backend-remediation`, one commit per stage. It merges into `main` through a single PR once Track A is green.
- The backend comes first. Frontend changes, including the A3 UI part and a frontend test framework, are deferred.
- A3 ships with no diagnostic endpoint; it's added in A6. Model tests are marked `model` and run in a venv with sklearn 1.8.0, xgboost 3.2.0 and shap 0.54.1 until A8 pins them.
- These steps still need the owner's separate approval:
  - applying A9 to the committed DB;
  - Tier 3 (live network calls);
  - A10;
  - the frontend phase;
  - Track M.

## Stage status
| Stage | Commit | Result |
|---|---|---|
| Records preserved | (this commit) | done |
| A0 test isolation | | pending |
| A1 migration framework | | pending |
| A2 SHAP fix | | pending |
| A4 extraction quality | | pending |
| A5 lifecycle | | pending |
| A3 severity withholding (backend) | | pending |
| A6 trigger | | pending |
| A7 isolation and health | | pending |
| A8 startup and pins | | pending |
| A9 backfills (tested on copies) | | pending |

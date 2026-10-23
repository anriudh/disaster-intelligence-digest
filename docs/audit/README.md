# Audit and remediation records

These are records of the audit of baseline commit `814f90b`, and of the plans for fixing what it found. They were moved here from a temporary working directory so they aren't lost.

| File | Contents |
|---|---|
| `HANDOFF.md` | Summary of the audit and the decisions made |
| `LEDGER.md` | Tier 0–2 validation ledger: each finding confirmed, refuted or inconclusive, with its evidence |
| `REMEDIATION_PLAN.md` | Workstreams WS1–WS6 and the owner decisions |
| `IMPLEMENTATION_PLAN.md` | Policies P-1 to P-6, stages A0–A10 and M1–M4, and Tier 3 |
| `A9_DRY_RUN.md` | What applying the migrations and backfills to the committed DB would change, from a dry run on a copy |
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
| Records preserved | c49456a | done |
| A0 test isolation | bb62184 | done: plain `pytest` passes offline (8 passed, 2 skipped); model tests 2/2 in the audit ML venv; committed DB and pkl hashes unchanged |
| A1 migration framework | 1b7a937 | done: 10 migration tests (fresh DB, copy of committed DB, no-op rerun, rollback on failure, checksum and missing-file guards, restore from backup); startup verified on a DB copy with no writes |
| A2 SHAP fix | 9dc6dbb | done: SHAP values equal xgboost pred_contribs for LOW, MODERATE and HIGH fixtures; labels unchanged; failures recorded as shap_status=error; tests fail on the old indexing |
| A4 extraction quality | 00c078f | done: the JS shell (real trafilatura output) is rejected; articles accepted; null description no longer gives "None"; source and quality stored |
| A5 lifecycle | f915952 | done: 12 lifecycle tests through run_pipeline (10 fail on the old code): date order, reprocessing, source-only closure, not_observed + 30-day listing, NULL digests, digest preservation, nlp_summary refresh, polygon centre |
| P-2 explicit GDACS missingness | d43fd6e | done: unmatched events give None (not -1) to the scorer, imputed features recorded, gdacs_match_status stored; 17-feature contract unchanged |
| A3 severity withholding (backend) | f4fea7a | done: /events, /events/{id} and /trends serve no severity, score, SHAP or severity_rationale, and add severity_status; values still stored; digests paused unless DIGEST_GENERATION_ENABLED=true. UI part deferred |
| A6 trigger | ee26444 | done: no token 503, bad token 401, good token 202, 409 during a run, scheduler skips during a manual run, 3/hour trigger (failed attempts count) and 120/min reads give 429, token-protected diagnostics endpoint |
| A7 isolation and health | 2009cec | done: a bad event is rolled back and counted while the rest are saved; runs recorded in pipeline_runs; /api/health/live without DB; /api/health pending/ok/degraded (25/45 min) with injected clock; polygon and naive-date GDACS matching; quota counts every attempt (3 of 3) |
| A8 startup and pins | 9f9a804 | done: README commands work from the repo root; model paths file-relative; sklearn/xgboost/shap pinned; constraints.txt installs cleanly (77 + 9 model tests pass in that venv, network off); dev requirements split; spaCy model in the Render build; health reports model availability |
| A9 backfills (tested on copies) | (this commit) | done on copies only: B1 100, B2 1, B3 100, B4 99+1, B5 0, B6 100 rows; originals in legacy_values; rerun no-op; restore gives the original content; new rows untouched. See A9_DRY_RUN.md. **Applying to the committed DB awaits approval** |

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
| `evidence/tier3/` | Tier 3 summary only (raw responses and HTML kept outside the repository) |
| `harness/tier{0,1,2}/` | The scripts used to run the audit checks offline, outside the repository |

## Decisions (2026-10-23)
- All work happens on branch `backend-remediation`, one commit per stage. It merges into `main` through a single PR once Track A is green.
- The backend comes first. Frontend changes, including the A3 UI part and a frontend test framework, are deferred.
- A3 ships with no diagnostic endpoint; it's added in A6. Model tests are marked `model` and run in a venv with sklearn 1.8.0, xgboost 3.2.0 and shap 0.54.1 until A8 pins them.
- These steps still need the owner's separate approval:
  - Tier 3 (live network calls): approved; blocked by this environment's network policy (eonet.gsfc.nasa.gov is denied);
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
| A9 applied to committed DB | (this commit) | done with owner approval: migrations 0001–0011 applied with the runner (verified backup first, network off); integrity ok; row counts unchanged; per-backfill changes match A9_DRY_RUN.md; rerun is a no-op. sha256 0f9df649…a7c5c6 → 1994d536…76c2d. Rollback: restore the pre-A9 file from git (c723444) |
| Tests on the legacy fixture | 7cfe1ea | after A9, 3 tests that copied the committed DB as legacy data failed (pushed in 315ba36 without a test run). They now use tests/fixtures/legacy_baseline.db (the pre-A9 DB); a new test migrates the committed DB to the latest version |
| A10 stale-event lookup | (this commit) | done, provisional: unseen_runs counts consecutive completed runs without the event (failed runs don't count); after 3, up to STALE_LOOKUP_LIMIT (default 5) lookups per run, least recently looked up first; a closed record closes the event (closure_source=eonet_lookup); an open record or a failed lookup leaves it open and not_observed; nothing is deleted. 11 tests with mocked lookups. N=5 and S=30 days are provisional until T3-3 runs. Offline suite: 112 passed (test_nlp: 3 fail, models not downloaded) |
| Tier 3 live sample | (this commit) | done: 13 external calls (cap 13), analysed offline. T3-1: 10/10 sampled sources unextractable (IRWIN JS shells rejected by the A4 gate; JTWC binary or 403), only 2 domains in the sample; multi-point geometry all ascending. T3-3: limit=100 misses 7,095 of 7,194 open allowed-category events, none updated within 30 days; 42 events within 30 days. T3-2: fromdate is naive (read as UTC); 1 match of 99, a coverage gap between the feeds, not a parsing defect. See evidence/tier3/SUMMARY.md |

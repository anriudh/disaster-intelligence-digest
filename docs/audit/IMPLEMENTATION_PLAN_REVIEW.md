# Review of the revised implementation plan (owner draft, baseline 814f90b)

**Status:** this review is recorded. The owner draft is accepted as the governing plan, subject to the amendments below. It supersedes `IMPLEMENTATION_PLAN.md` wherever the two differ. The new owner decisions are adopted as stated: digests paused, 30-day listing, limits of 3 per hour and 120 per minute.

**Checks made for this review (read-only):** the repository is unchanged versus the Tier 0 baseline; the branch is `backend-remediation`; the frontend has no test framework or test script; the environment's SQLite is 3.45.1.

## A. Accuracy corrections to §2 (confirmed findings)

| Draft statement | Correction | Evidence |
|---|---|---|
| "EONET geometry dates can be stored incorrectly when the source ordering differs from the assumed ordering." | More precisely: the code stores `geometry[0]` as `last_updated` and `geometry[-1]` as `first_seen`. With **ascending** input, both are swapped and newer observations are never re-processed. That **ascending is EONET's real order is unconfirmed live**; one committed row (EONET_19481) is consistent with it. | T1 (C); T11 (D) |
| "simultaneous triggers can duplicate work" | Confirmed, including **2 Gemini calls for one event**. The quota race **within one process was refuted**; a multi-process race is untested. | T7, T8 (C) |
| "All 100 events report a digest … despite having no actual digest" | Also: the committed DB contains **no real digests** (100/100 `'null'`). "Preserve existing digests" therefore preserves zero real digests today. That's still the right rule for deployed databases. | T11 (D), T1 API (C) |
| "Model artifacts loaded in the tested environment" | Tested with sklearn 1.8.0, xgboost 3.2.0 (both recorded in the artifacts), shap 0.54.1, and Python 3.13.16. | T2-1 (C) |

Everything else in §2 matches the ledger, including the retained corrected diagnosis.

## B. Internal inconsistencies to resolve before A0 starts

1. **The A0 acceptance criterion contradicts A0's own scope.** "Baseline commit and tracked-file hashes remain unchanged" can't hold, because A0 edits `backend/tests/test_ingest.py` and adds test configuration.
   - **Amend to:** (a) the baseline is verified unchanged *before* A0 begins; (b) after A0, the diff touches only the declared files; (c) the **committed DB's sha256** and the artifact hashes are unchanged after the full test suite runs.
2. **Commits are outside the current authorization (§9).** Implementing A0 produces repository changes.
   - **Needs an explicit decision:** may A0's changes be committed to the working branch, and pushed? Or should they be left uncommitted for review?
   - Proposed: commit to that branch, push only after review, and open no PR unless asked.
3. **A3 depends on A6 for diagnostic access.** The only server-side authentication in the plan is A6's shared secret.
   - **Amend:** A3 ships with **no diagnostic endpoint**. The internal diagnostic data stays in the DB. The authenticated endpoint is added in A6, or as a follow-up stage after it.
   - This makes A3 independent, and satisfies "cannot be reached anonymously" trivially.
4. **The A2 tests need the ML stack.** Verifying values against xgboost contributions requires sklearn, xgboost and shap at known versions, and the plan forbids new installs.
   - **Amend:** A2's tests run in the existing Tier 2 audit venv (no new install). They're marked `model`, and are excluded from the default offline run until A8 pins those versions in the project.
   - A8 then makes them part of the documented test environment.
5. **The A3 UI acceptance relies on "UI tests", but the frontend has no test framework.** Adding one (e.g. Vitest plus Testing Library) is a dependency-manifest change and an npm install.
   - **Options (owner):**
     - (a) A3's UI acceptance uses backend API tests plus a static check that the frontend source no longer references `severity_label`, `severity_score` or `shap_values` in rendered paths;
     - (b) approve adding a frontend test framework as a separate stage.
   - **Proposed:** (a) now, (b) later.
6. **A6 says "Public read limits are tested with proxy-aware client identification."** Render's forwarded-header behaviour can't be established offline from the repo.
   - **Amend:**
     - test the limiter offline with simulated `X-Forwarded-For` headers;
     - document the assumption;
     - verifying Render's actual behaviour needs either your confirmation or one documentation read. That's a live access, so it needs separate approval.
   - Until then, the per-client limits are documented as "per proxy-visible address".
7. **A7 includes "quota accounting … robust against concurrent execution".** P-1 pauses digest generation, so no Gemini calls happen while the policy is active. A6's shared lock already prevents concurrent runs within the single process.
   - **Amend:** A7 corrects attempt counting (T7). The multi-process race (U) is documented, not engineered around, while there's one process and digests are paused.
8. **A9 rollback.** Migrations are additive only, so "rollback" means **restoring from the pre-migration backup**, not reverse migrations.
   - **Amend** A1 and A9 to state this explicitly.
   - Demonstrate a restore on a disposable copy: backup → migrate → restore → the sha256 equals the backup's.

## C. Small additions

- **Digest pause mechanism (A3).** A single server-side flag, default "paused", checked before `generate_digest` is called. It is not removed from code. The digest path stays testable with a fake client.
- **A5 and A9 boundary.** A5 changes write behaviour for new and updated rows only. Corrections to existing rows happen only in A9 (backfills B1–B6 from `IMPLEMENTATION_PLAN.md` §2 P-6), with originals preserved.
- **A10 inputs.** It counts consecutive unseen *successful runs*, which needs A7's run records. Failed runs don't count as "unseen".
- **Integration (§5).** A2–A5 all touch `orchestrator.py`, `routes.py` and the schema. Recommended merge order after independent review: A2 → A4 → A5 → A3, with the full offline suite run after each merge. A3 goes last because it reshapes API responses that the others' tests may assert on.

## D. Open items needing owner answers before A0
1. Commit and push permissions for implementation stages (B.2).
2. The frontend test approach (B.5).
3. Confirmation of B.3 (A3 without a diagnostic endpoint) and B.4 (A2 tests in the existing audit venv until A8).

No other blockers. Once these are answered, A0 can begin, and its evidence is returned before A1.

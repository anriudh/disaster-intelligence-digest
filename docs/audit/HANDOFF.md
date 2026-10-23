# Handoff: Disaster Intelligence Digest audit and remediation planning

> **Archived copy.** The original lived in a temporary working directory outside the repository. Here, the plans are in `docs/audit/`, raw evidence in `docs/audit/evidence/tier{0,1,2}/` (originally `out/`, `t1/out/`, `t2/out/`), and harnesses in `docs/audit/harness/`. The open questions below were answered on 2026-10-23; see `docs/audit/README.md`.

## Context
The project audits `anriudh/disaster-intelligence-digest`, a FastAPI, SQLite, XGBoost and React pipeline that ingests NASA EONET and GDACS disaster events, scores their severity, and shows them on a map.

- Phase 0 was a read-only audit.
- Tiers 0, 1 and 2 were controlled validation in disposable copies: offline, no credentials, no Gemini calls, no database writes.
- A prioritized remediation plan and a staged implementation plan exist. The owner revised the implementation plan, and I reviewed it with amendments.
- **No remediation has been implemented.** The next step is answering the open questions, then stage A0 only.

## Current state (verified 2026-10-23, read-only)
- **Repo:** branch `backend-remediation` at HEAD `814f90b`, which equals `origin/main`. Clean working tree.
- **Integrity:** the commit, the status, and all 49 tracked-file sha256 hashes are identical to the Tier 0 baseline.
- **Nothing committed or pushed. No PR.** The only write to `.git` during the audit was `git fetch` updating the remote-tracking refs.

## Where everything lives
All of it was in a temporary working directory outside the repository (`p1/`); it is now archived in `docs/audit/`.

| File | Contents |
|---|---|
| `LEDGER.md` | Tier 0–2 validation ledger (confirmed / refuted / inconclusive, with evidence and environment) |
| `REMEDIATION_PLAN.md` | Workstreams WS1–WS6, plus §4 owner decisions 1–6 |
| `IMPLEMENTATION_PLAN.md` | My staged plan: policies P-1 to P-6, stages A0–A10, M1–M4, bounded Tier 3 |
| `IMPLEMENTATION_PLAN_REVIEW.md` | My review of the owner's revised plan, which is now the governing plan, with amendments A–D |
| `out/`, `t1/out/`, `t2/out/` | Raw evidence: tier JSON, pytest logs, pip freezes, static pickle inspection, integrity before/after files |
| `tests/`, `t1/run_tier1.py`, `t2/harness/` | Audit harnesses: stubs, Tier 0 tests, Tier 1 API and trafilatura checks, Tier 2 model and SHAP diagnosis |
| `t1/venv`, `t2/venv` | Throwaway venvs. Tier 2 has sklearn 1.8.0, xgboost 3.2.0, shap 0.54.1 on Python 3.13.16 |

**Risk:** the working directory isn't in the repository and is temporary. The ledger and plans would be lost. **Recommend** that the owner approve preserving them, e.g. committing `docs/audit/` to the branch.

## Key validated findings (details in LEDGER.md)
- **Severity:** all 100 committed events are LOW / 0.9991. Reproduced exactly (100/100) from reconstructed vectors with the committed artifacts.
  - **The cause:** the model is trained on **synthetic** data where `persons_affected` leaks the label. Production text never yields `persons_affected`, so it's imputed with the median 399.5 (the LOW range).
  - **Correction:** Tier 0's guess (GDACS −1, source count, duration, NER counts) was refuted as the cause. Those are data-quality issues only.
- **SHAP:** the explainer is correct, with shape (1, 17, 3), matching xgboost's own `pred_contribs`. `scorer.py:67-70` indexes it wrongly: LOW gives 3 mislabelled zeros, MODERATE/HIGH give `IndexError`, stored as `{}`.
- **Scraper:** it accepts "You need to enable JavaScript to run this app." as article text (99/100 rows). A null description gives "Title None".
- **Lifecycle:**
  - with ascending geometry, `first_seen` and `last_updated` are swapped, and updates are never re-processed;
  - events never close, and `seed()` saves 0 closed events;
  - "no digest" is stored as `'null'`, so `has_digest` is true for 100/100;
  - `nlp_summary` goes stale on re-processing.
- **Reliability:**
  - one bad event aborts a run, and `/health` says healthy anyway, even six months stale;
  - the trigger is unauthenticated and allows concurrent runs, causing duplicate Gemini calls;
  - the rate limiter has 0 limits;
  - failed Gemini calls aren't counted against the quota;
  - an in-process quota race was **refuted**.
- **Startup and tests:**
  - the README start command fails (`No module named 'backend'`);
  - plain `pytest` can't collect, while `python -m pytest` can;
  - `test_match_events` fails;
  - the quota test deletes today's quota row from whatever DB is configured.
- **Unverified:** behaviour under other dependency versions, real EONET ordering and truncation, GDACS date format, live scraper prevalence, F8, F13, and the frontend defects.

## Governing plan and decisions
The owner's revised plan governs, with the amendments in `IMPLEMENTATION_PLAN_REVIEW.md`. Owner decisions:
- severity, confidence and SHAP withheld publicly; **digest generation paused**;
- explicit GDACS missingness, keeping the 17-feature contract;
- closure only from the source, with `last_seen` tracking and **30-day** listing of unobserved events, and a bounded lookup after 3 unseen runs;
- health: liveness separate from pipeline health, **45 min** degraded, **25 min** pending;
- trigger: shared-secret authentication that fails closed, a shared lock with 409 on overlap, limits of **3 per hour** for the trigger and **120 per minute** for reads;
- additive versioned migrations with backups and preserved originals, with no execution on a real DB without separate approval.

**Stage order:**
- A0 test isolation, then A1 migrations.
- A2 SHAP, A4 extraction, A5 lifecycle and A3 withholding in parallel, merged in that order.
- A6 trigger and A7 error isolation and health.
- A8 startup and pins.
- A9 backfills; running them on a real DB needs approval.
- Tier 3 (bounded), then A10.
- Track M (model validation) is separate.

## Open questions blocking A0 (owner)
1. May implementation stages commit to `backend-remediation`? Proposed: commit, push only after review, no PR unless asked.
2. Frontend testing: a static check now, and a frontend test framework (an npm dependency change) as a later stage?
3. Confirm A3 ships without a diagnostic endpoint (added in A6), and that A2's model tests run in the existing `t2/venv` until A8 pins the versions.
4. Also: preserve the audit records in the repo (see the risk above)?

## Verification for whoever continues
- Integrity check: compare `git rev-parse HEAD`, `git --no-optional-locks status --porcelain --ignored`, and `git ls-files -z | xargs -0 sha256sum` against `p1/out/integrity-before.txt`.
- Run all audit harnesses under `env -i` and `unshare --net`, from a `git archive` copy, never from the repo.
- After A0, the acceptance check is that the committed DB's sha256 is unchanged after the full test suite.

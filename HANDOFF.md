# HANDOFF 2026-10-23 18:45 | backend-remediation@3491a17 | paused: manual
Resume protocol: read this file and nothing else, then open only the files under Load.
Do not scan the repo, re-read the old conversation, or re-derive what is listed here.
If HEAD is not 3491a17, run `git log --oneline 3491a17..HEAD` first. Start at Not done 1.
Delete this file once Not done is finished.

## Goal
Fix the audited defects in the disaster-intelligence-digest backend (Track A, stages A0-A10), then frontend and model validation. Done = all stages merged to `main` through one PR, CI/tests green.

## Done (verified)
- Audit records archived in `docs/audit/` (c49456a). Stage status table: `docs/audit/README.md`.
- A0 test isolation (bb62184), A1 migration framework (1b7a937), A2 SHAP fix (9dc6dbb), A4 extraction quality (00c078f), A5 lifecycle (f915952), P-2 GDACS missingness (d43fd6e), A3 severity withholding, backend only (f4fea7a), A6 trigger auth/lock/limits (ee26444), A7 isolation + health (2009cec), A8 startup + pins (9f9a804), A9 backfills tested on copies only (c723444). All pushed to origin/backend-remediation.
- Full offline suite: 97 passed, network off, in a venv built from `backend/constraints.txt`; committed DB and model sha256 unchanged.

## Unverified
- NLP tests (`backend/tests/test_nlp.py`) never ran: spaCy/KeyBERT/sentence-transformers models were not downloaded (the plan prohibits model downloads).
- `render.yaml` PYTHON_VERSION 3.13.16: may not be offered by Render.

## Not done
1. Ask the owner which next step to take. Each of these needs their explicit approval:
   a. (done) A9 applied to the committed DB; see docs/audit/README.md.
   b. Tier 3 live checks (`docs/audit/IMPLEMENTATION_PLAN.md` §5: 1 EONET GET, ≤10 source URLs, 1 GDACS call; outputs outside the repo), then A10 (stale-event lookup after 3 unseen runs).
   c. Frontend phase: remove severity UI (Map.jsx, EventDetail.jsx, TrendPanel.jsx), plus a frontend test framework.
   d. Track M (model validation, M1-M4).
2. When the owner asks: open one PR `backend-remediation` → `main`, using a merge commit, not a squash.
3. Before the project ends: delete HANDOFF.md from the repo (owner request).

## Decisions
- One branch `backend-remediation`, one commit per stage, merge to main at the end: owner choice.
- Backend before frontend: owner choice. Until the frontend phase, the map shows no severity.
- A3 shipped without a diagnostic endpoint; it was added in A6, behind the trigger token.
- The run claim uses an in-process flag, not a DB lock: one process (render.yaml).
- Rate-limit key is the proxy-visible address; X-Forwarded-For is not trusted.
- Migrations auto-run at startup (with backup), so merging or deploying applies the backfills to that DB copy. Flagged to the owner.

## Gotchas
- Run tests from the repo root: `pytest` (default excludes the `network` and `model` markers); `pytest -m "not network"` includes the model tests.
- Test venvs lived in the scratchpad (lost on reclaim). Recreate with `uv venv -p 3.13 V && VIRTUAL_ENV=V uv pip install -r backend/requirements-dev.txt -c backend/constraints.txt` (6 GB, CUDA torch). Run offline with `env -i PATH=/usr/bin:/bin HOME=$TMP unshare --net -r V/bin/python -m pytest -m "not network"` on a copy of the tree, then check that `sha256sum backend/data/disaster_intel.db backend/models/*.pkl` is unchanged.
- Without spaCy installed, `backend/tests/conftest.py` installs stand-in nlp/embeddings modules.
- git identity is set in the local repo config: anriudh <anirudham.10b.svn@gmail.com>.
- The handoff skill lives only in this container (`~/.claude/skills/handoff/`), lost on reclaim; see the owner's options (claude.ai skill upload / setup script).

## Session rules
- Commits: authored as the owner, no AI attribution or co-author trailers, no AI mentions in the repo.
- Never modify the committed DB (A9 applied with approval), make live network calls or download models without explicit approval.
- Push only to `backend-remediation`. No PR unless asked.

## Load
- `docs/audit/README.md`: stage status and pending approvals.
- `docs/audit/A9_DRY_RUN.md`: only if the owner approves applying A9.

## Verify
- `git log --oneline -1` -> `c723444 A9: backfill legacy rows (tested on copies only)` (or a later HANDOFF commit)
- `pytest -m "not network"` (full venv, offline) -> 97 passed, test_nlp skipped or deselected

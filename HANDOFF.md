# HANDOFF 2026-10-23 19:21 | backend-remediation@2ff0bff | paused: manual (moving to a local environment for network access)
Resume protocol: read this file and nothing else, then open only the files under Load.
Do not scan the repo, re-read the old conversation, or re-derive what is listed here.
If HEAD is not 2ff0bff, run `git log --oneline 2ff0bff..HEAD` first. Start at Not done 1.
Delete this file once Not done is finished.

## Goal
Fix the audited defects in the disaster-intelligence-digest backend (Track A, A0-A10), then Track M (model validation), then the frontend. Done = everything merged to `main` through one PR (merge commit), CI/tests green.

## Done (verified)
- A0-A9 code stages, all on origin/backend-remediation; stage table in `docs/audit/README.md`.
- A9 applied to the committed `backend/data/disaster_intel.db`, with owner approval (315ba36): runner backup made first, network off; integrity ok; counts match `docs/audit/A9_DRY_RUN.md`; rerun no-op. sha256 0f9df649… -> 1994d536…
- Fixed the regression A9 caused in 3 tests that used the committed DB as legacy data (7cfe1ea). They now copy `backend/tests/fixtures/legacy_baseline.db` (pre-A9 DB, sha 0f9df649…, conftest checks it is never modified); new test `test_committed_db_copy_migrates_to_latest`.
- A10, provisional (c3152d5): migration 0012 (`events.unseen_runs`, `events.last_lookup_at`); `ingest.fetch_eonet_event`; `orchestrator.lookup_stale_events`, run after `mark_unobserved`; STALE_AFTER_RUNS=3, `STALE_LOOKUP_LIMIT` env (default 5); 11 tests in `backend/tests/test_stale_lookup.py`.
- Offline suite at c3152d5: 112 passed, 1 deselected; the 3 `test_nlp` failures are explained under Gotchas. Committed DB and pkl hashes unchanged.
- Tier 3 fetch harness committed at `docs/audit/harness/tier3/fetch.py` (b54c599). Never run: the cloud proxy returned 403 for eonet.gsfc.nasa.gov, so no request reached any external host.

## Unverified
- `fetch.py` has never run end to end. In particular, the source-picking loop (round-robin by category, distinct domains first) is untested.
- Category-filtered EONET GET `?status=open&category=wildfires,severeStorms,volcanoes,floods,earthquakes` assumes EONET accepts comma-separated categories.
- Per-event endpoint `https://eonet.gsfc.nasa.gov/api/v3/events/{id}` (used by A10) is assumed from the plan; never called live.
- NLP tests never passed (models not downloaded). `render.yaml` PYTHON_VERSION 3.13.16 may not be offered by Render.

## Not done
1. In the local env: rebuild the venv (see Gotchas). Run the full offline suite once and confirm 112 passed.
2. Tier 3 (owner-approved). Run `python docs/audit/harness/tier3/fetch.py <dir OUTSIDE the repo>`: 1 open-events GET, 1 category GET, ≤10 source URLs, 1 GDACS `latest_events()`. Check `fetch_log.json` calls ≤ 13.
3. Write and run the offline analysis phase, also outside the repo and with network off:
   - T3-1: trafilatura.extract + `scraper.is_boilerplate` on the saved HTML; share of unextractable sources; ascending vs descending geometry order on live records.
   - T3-3: allowed-category events missing from the limit=100 response vs the category GET (truncation).
   - T3-2: `ingest.match_events` on the GDACS payload; `fromdate` format; why there are 0 matches.
   - Save the summary as `docs/audit/evidence/tier3/` (summary only, no raw HTML) and add a row to the `docs/audit/README.md` table.
4. Finalize A10's N (STALE_LOOKUP_LIMIT default) and S (30-day listing window in `backend/app/api/routes.py:35` query) from T3-3; propose the values to the owner before changing them.
5. Track M (owner-approved), `docs/audit/IMPLEMENTATION_PLAN.md` §4. Start with M1: find a real, independently labelled source (e.g. historical GDACS alerts joined to EONET). Write a data card covering provenance, licensing, coverage per category, label definition, and a leakage review; owner approves it. Then M2-M4.
6. Frontend phase last: remove severity UI (Map.jsx, EventDetail.jsx, TrendPanel.jsx) + frontend test framework.
7. When the owner asks: one PR `backend-remediation` -> `main`, merge commit, not squash.
8. Before the project ends: delete HANDOFF.md from the repo (owner request).

## Decisions
- One branch `backend-remediation`, one commit per stage, merge to main at the end; backend before frontend; order now Tier 3 -> A10 N/S -> Track M -> frontend: owner choices.
- Keep the 6 GB venv as is (CUDA torch); do not switch to CPU torch: owner choice.
- A10 counts consecutive *completed* runs (success or partial); failed runs don't count (plan review amendment). Lookups rotate by `last_lookup_at` (NULL first) so a large stale set is cycled, not starved. A failed lookup still sets `last_lookup_at`.
- Migration 0012 was not applied to the committed DB; it auto-applies (with backup) at startup on deploy.
- Run claim is an in-process flag (single process); rate-limit key is the proxy-visible address.

## Dead ends
- Tier 3 from the claude.ai cloud env: proxy CONNECT 403 for eonet.gsfc.nasa.gov (network policy). Needs a local env or the env's allowed domains changed.

## Gotchas
- Tests run from the repo root. Plain `pytest` excludes the `network` and `model` markers. `-m "not network"` replaces that filter, so the model tests run, and `test_nlp` fails (3 tests) unless the spaCy en_core_web_md / KeyBERT / MiniLM models are downloaded. This is expected and not a regression.
- Venv: `uv venv -p 3.13 V && VIRTUAL_ENV=V uv pip install -r backend/requirements-dev.txt -c backend/constraints.txt` (about 6 GB on a cold cache). Offline run on Linux: `env -i PATH=/usr/bin:/bin HOME=$TMP unshare --net -r V/bin/python -m pytest -m "not network"` on a copy of the tree. Afterwards check `sha256sum backend/data/disaster_intel.db backend/tests/fixtures/legacy_baseline.db backend/models/*.pkl` -> 1994d536…, 0f9df649…, ece13ae9…, dec3b0b1…
- Without spaCy installed, `backend/tests/conftest.py` installs stand-in nlp/embeddings modules. `FakePipeline` in `backend/tests/helpers.py` fakes `fetch_eonet_event` (`.records`, `.lookups`).
- `.gitignore` ignores `*.db` with an exception for the legacy fixture.
- git identity in local repo config: anriudh <anirudham.10b.svn@gmail.com>.
- The handoff skill lived only in the cloud container (`~/.claude/skills/handoff/`); install it locally to keep using /handoff.

## Session rules
- Commits authored as the owner; no AI attribution, co-author trailers or AI mentions in the repo.
- Never modify the committed DB, make live network calls beyond the Tier 3 scope (no full pipeline run, no Gemini calls, no live data written to the project DB, no NLP model downloads, no frontend build during Tier 3), or download models, without explicit approval. Tier 3 outputs stay outside the repo.
- Push only to `backend-remediation`. No PR unless asked.
- Run the test suite before every push (lesson from 315ba36).

## Load
- `docs/audit/harness/tier3/fetch.py`: the Tier 3 fetch script to run.
- `docs/audit/IMPLEMENTATION_PLAN.md:232-243`: Tier 3 scope and prohibitions.
- `backend/app/pipeline/ingest.py` and `backend/app/pipeline/scraper.py`: functions the analysis phase calls.

## Verify
- `git log --oneline -1` -> `b54c599 Tier 3: add the bounded fetch harness (not yet run)` (or a later HANDOFF commit)
- `pytest -m "not network"` (full venv, offline) -> 112 passed, 3 failed (test_nlp only), 1 deselected

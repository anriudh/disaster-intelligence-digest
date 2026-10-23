# Disaster Intelligence Digest: staged implementation plan (proposal; nothing implemented)

**Inputs**
- `LEDGER.md`: Tier 0–2 evidence.
- `REMEDIATION_PLAN.md`: workstreams WS1–WS6 and the §4 owner decisions.
- Baseline commit `814f90b`.

**Evidence labels:** **C** confirmed under execution; **D** committed-DB data only; **R** code reading; **H** hypothesis; **U** unresolved.

**Track separation**
- **Track A (reliability and data integrity):** Stages A0–A9. Ordinary fixes; none depend on model validity.
- **Track M (model validation):** Stages M1–M4. Kept separate. Nothing in Track A retrains, replaces, or re-tunes the model, or changes the label policy (argmax, then `{0: LOW, 1: MODERATE, 2: HIGH}`).

**Conventions for every stage**
- One reviewable change, with its tests in the same change.
- Tests run offline, against a `tmp_path` database (after A0).
- Stages touching the database need a migration (A1) and a migration test on a disposable copy of the committed DB.
- The committed `backend/data/disaster_intel.db` is **never** modified by tests or development runs. Migrations are applied to it only as an explicit, reviewed, backed-up step.

---

## 1. Facts established for the owner decisions (read-only checks)

| Topic | Fact | Source |
|---|---|---|
| Severity in the UI | Shown in 3 places: map marker colour and popup (Map.jsx:16-23, 100, 106-110); detail badge with `severity_score*100` % (EventDetail.jsx:45-49); trends pie chart and "Critical (HIGH) Alerts" card (TrendPanel.jsx:29-40, 88-100). | R |
| Severity in the digest | The Gemini prompt includes the severity label and score (gemini.py:71) and asks for `severity_rationale` (gemini.py:79), which the UI displays (EventDetail.jsx:76). Generating a digest at all depends on MODERATE/HIGH (orchestrator.py:84). | R |
| SHAP in the UI | Bar chart on the detail page (EventDetail.jsx:29-32, 110-126). It explains the withheld rating. | R |
| Trigger caller | No frontend code calls `/api/pipeline/trigger`. | R (grep) |
| Schedule | `IntervalTrigger(minutes=20)`, `max_instances=1`, `coalesce=True`, `misfire_grace_time=300` (main.py:45-52). No run at startup; first run at +20 min. README: "every 20 minutes when the backend is active". | R |
| Workers | `uvicorn backend.app.main:app` with no `--workers`, so one process (render.yaml:6). | R |
| Deployment configuration | render.yaml env vars: `GEMINI_API_KEY`, `FRONTEND_URL` (`sync: false`), `PYTHONPATH`. Rendering the frontend isn't part of render.yaml. | R |
| Rate limiter | `Limiter(key_func=get_remote_address)` is registered (main.py:19-22), with 0 limits (C, T1). Route handlers take no `request` argument (routes.py), which slowapi decorators require. Verify at implementation. | C / R |
| Migrations | None. `execute_schema()` runs `CREATE TABLE IF NOT EXISTS`, so new columns would **never** reach an existing DB. | R |
| GDACS in the model | Training data has **no** missing GDACS values: score 0–6.98, population 9–~1e6 (C, T10). Imputer medians: score **2.286**, population **7555** (C, T2-1). XGBoost `missing=NaN` (C). With the current imputer, NaN is replaced by the median before the model sees it, so it reaches the model as a plausible mid-range GDACS measurement, not as "missing". In the Tier 2 sensitivity test, NaN vs −1 produced identical output for the reconstructed vector (C, T2-5). | C |
| Stored dates | Only `geometry[0].date` and `geometry[-1].date` survive, stored swapped as `last_updated` and `first_seen` (C, T1). The full geometry list isn't stored. | C / R |

---

## 2. Policies proposed for the owner decisions (to approve before the stages that use them)

### P-1 Severity withholding (decision 1)
- **Normal API responses** (`/api/events`, `/api/events/{id}`, `/api/trends`) drop `severity_label`, `severity_score`, `shap_values`, and the severity aggregation. They add `"severity_status": "withheld_unvalidated_model"`.
- **No replacement value** is shown or computed.
- **Diagnostics** are preserved: the scorer still runs and stores label, score and SHAP in the DB. A new authenticated endpoint `GET /api/internal/events/{id}/diagnostics` returns them, using the same server-side token as the trigger (P-5).
- **The normal UI** shows neutral markers, no severity badge, no SHAP chart, and no severity pie or "HIGH alerts" card. A short note says "Severity assessment is not shown: the model has not been validated."
- **Open questions for the owner (not decided here):**
  - (a) The digest's `severity_rationale` field is derived from the withheld rating. **Proposed:** don't display it in the normal UI. The stored digest is kept unchanged.
  - (b) Digest generation is gated on the withheld MODERATE/HIGH label. In practice that means no digests (0/100 committed). **The plan doesn't change the gate.** If you want digests for unrated events, that's a separate policy decision.
  - (c) Whether the prompt should keep including the severity label. That's left as-is until (b) is decided.

### P-2 Explicit GDACS missingness (decision 2)
- **Storage.**
  - `gdacs_enrichment` already represents "no match" as **no row**.
  - Add `events.gdacs_match_status TEXT`: `matched`, `no_match`, or `not_checked` (the last for legacy rows).
  - Stored measurements stay NULL when absent. `-1` is never written.
- **Feature building.** The feature dict carries `None` plus a separate list `missing_features = ["gdacs_alert_score", "gdacs_population_exposure"]`.
- **Model adapter (scorer).** This is one explicit, tested function that turns None into NaN, applies the **existing** imputer, and returns `imputed_features`. Whatever values go in are recorded in diagnostics.
- **Disclosure.** For the current model, imputation turns "missing" into median GDACS values (2.286 / 7555). That is no more truthful than −1, only differently wrong. It is acceptable only because severity is withheld (P-1). The diagnostics show which features were imputed.
- **The proper fix is Track M.** A model trained with an explicit `gdacs_matched` indicator (or native NaN handling), validated on real data.
- **Track A must not:**
  - change `FEATURE_COLUMNS` order or length (17), since the imputer and model require it (C);
  - add an indicator feature to the current model;
  - pass NULL or None to `imputer.transform` without conversion.

### P-3 Closure and stale-event rules (decision 3)
- **Columns:**
  - `last_seen` (the last run whose feed contained the event);
  - `closed_at` (from the source);
  - `closure_source` (`eonet_closed_field`, `eonet_lookup`, or NULL);
  - `observation_state` (`observed`, `not_observed`, `unknown_legacy`).
- `status` keeps the values `open` and `closed` and is set **only** from a source statement.
- **EONET closure:** set `status='closed'` and `closed_at` **only** when an EONET record for that ID has a non-null `closed` field. That record comes either from the regular feed or from a per-event lookup (`/api/v3/events/{id}`).
- **Absence:** if an open event isn't in the current feed, set `observation_state='not_observed'` and keep `last_seen` unchanged.
  - **Not** closed, because `limit=100` truncation means absence is unreliable (U, Tier 3 Q1).
  - **Proposed** follow-up: after the event has been unseen for at least 3 consecutive successful runs (~1 h at 20-minute intervals), do one per-event lookup per run, capped at N lookups per run. If the lookup says closed, close it. If it says open, keep it open and `not_observed`.
- **GDACS:** never used for closure. It's an enrichment source with different event identity.
- **Stale display (owner to confirm):** default `/api/events` lists `status='open'` events that are `observed`, or `not_observed` with `last_seen` within S days (S to be chosen). It includes `observation_state` and `last_seen`, so the UI can mark them. Nothing is deleted.
- **Legacy rows:** `observation_state='unknown_legacy'`, `last_seen` NULL. Not inferred from `analysed_at`.

### P-4 Health and freshness (decision 4)
- **Liveness:** a new `GET /api/health/live` returns 200 when the process is up. No DB access.
- **Pipeline health:** `GET /api/health` (kept for compatibility) reports `status` (`ok`, `degraded`, `pending`), `last_run_started`, `last_run_finished`, `last_successful_run`, `last_error` (time, message, failing event ID if any), and counts (processed, skipped, failed), all from a `pipeline_runs` table.
- **Freshness threshold**, from the schedule (20 min interval, 300 s misfire grace):
  - `stale_after = 2 × interval + grace = 45 min` since the last **successful** run;
  - `pending` while uptime is under `interval + grace` (25 min) and no run has completed yet (there's no startup run);
  - `degraded` if the last run failed, or the last success is older than 45 min.
- **Unresolved:** run duration is unmeasured. Sequential scraping sleeps 1.5–3.5 s per successful source, so 100 events could take minutes. If runs approach 20 minutes, the threshold needs revisiting. A-stage logs record durations. Render free-tier sleep behaviour is unknown and would make "degraded" expected while idle.

### P-5 Trigger authentication, concurrency and rate limits (decision 5)
- **Authentication:** the existing configuration pattern is Render env vars with `sync: false`, so the smallest mechanism is a shared secret.
  - New env var `PIPELINE_TRIGGER_TOKEN`, declared in render.yaml as `sync: false`. The value is never committed.
  - Header `Authorization: Bearer <token>`, compared with `hmac.compare_digest`.
  - **If the variable isn't set, the trigger endpoint is disabled (503)**, never open.
  - The frontend never calls it. No secret appears in frontend code or `VITE_*` variables.
  - The diagnostics endpoint (P-1) uses the same token.
- **Concurrency:**
  - one module-level `asyncio.Lock` shared by the scheduler job and the trigger;
  - the trigger returns 409 while a run is active;
  - keep a reference to the task.
  - Valid because there's one process (render.yaml). Multiple workers would need a DB-based lock (U, documented).
- **Rate limits:** `@limiter.limit` on the trigger (proposed 2/minute) and on public GETs (proposed 60/minute). The exact values are the owner's.
  - **U:** behind Render's proxy, `get_remote_address` may see the proxy IP. Whether to trust `X-Forwarded-For` must be checked against Render's documented header behaviour before the per-client limits mean anything.

### P-6 Migrations and backfills (decision 6)
- A `schema_migrations(version, applied_at, checksum)` table, and numbered migration files `backend/app/db/migrations/NNNN_*.sql` (or `.py` for backfills).
- They run at startup after `execute_schema()`, are idempotent, and each one runs in a transaction.
- **Backup:** before applying any migration, copy the DB with the SQLite online backup API to `disaster_intel.db.bak-<version>-<timestamp>`, next to the DB and git-ignored. Verify by `PRAGMA integrity_check` plus row counts.
- **Additive only.** `ALTER TABLE … ADD COLUMN`, new tables, no `DROP`, no `DELETE`.
- **Corrections preserve originals.** Before any backfill changes a value, the original is copied to `legacy_values(table, row_id, column, old_value, migration_version)`. Every backfill is deterministic, and re-running it is a no-op.
- **Proposed backfills:**

| Backfill | Rule | Why it's deterministic |
|---|---|---|
| B1 `'null'` digest | `gemini_digest='null'` → SQL NULL (original kept in `legacy_values`) | exact string match |
| B2 date order | `first_seen := min(first_seen, last_updated)`, `last_updated := max(…)` | both stored values are geometry endpoints, so min/max is order-independent. Only 1 committed row changes (EONET_19481). |
| B3 SHAP validity | add `shap_status`; set `'invalid_legacy_indexing'` for all pre-fix rows. Values are kept, not recomputed (the inputs weren't stored). | rule depends only on migration version |
| B4 scrape quality | add `scrape_quality`; `'rejected_boilerplate'` where `raw_text` equals a known shell phrase; else `'legacy_unchecked'`. Text kept. | exact match against a fixed list |
| B5 `nlp_summary` | recompute from stored `keyphrases[:3]` (the same formula as orchestrator.py:125) where it differs | pure function of a stored column |
| B6 observation | `observation_state='unknown_legacy'`, `gdacs_match_status='not_checked'` | constant |

- **Migration tests:** on a `tmp_path` copy of the committed DB, check:
  - the expected row counts are unchanged;
  - each backfill changes exactly the expected rows (B1 100, B2 1, B4 99, …);
  - re-running is a no-op;
  - `legacy_values` holds the originals;
  - `PRAGMA integrity_check` passes;
  - the committed DB's sha256 is unchanged after the test.
- **Applying migrations to the committed DB file** is a separate, explicit, reviewed step (stage A9), never a side effect of tests or development.

---

## 3. Track A stages (reliability and data integrity)

| Stage | Content | Depends on | Independent of |
|---|---|---|---|
| **A0 Test harness** | `pytest.ini` (`pythonpath = .`, `asyncio_mode`, `network` marker, default `-m "not network"`). A `conftest.py` that redirects `database.DB_PATH` to `tmp_path` for every test. Fix `test_match_events` mocks (dict GeoJSON). Mark `test_fetch_eonet_events` and `test_nlp` as network/model tests. | — | everything |
| **A1 Migration framework** | P-6 machinery, backup, `schema_migrations`, `legacy_values`. No backfills yet. | A0 | A2, A3, A4 |
| **A2 SHAP extraction fix** (WS3.1) | Normalise shap output (list or 3-D), assert the length, top-5 for the predicted class, logging instead of print, write `shap_status='ok'` or `'error'`. | A0; A1 for the `shap_status` column (or deliver the code first and the column in A1) | A3, A4, A5 |
| **A3 Severity withholding** (P-1) | API field removal, `severity_status`, diagnostics endpoint stub (auth comes in A6; until then it **returns 404**, not open), UI changes, README correction. | A0 | A2, A4, A5 |
| **A4 Extraction quality** (WS1.1–1.2) | Quality gate, `None` fallback fix, persist `scrape_source` and `scrape_quality`. | A0, A1 | A2, A3, A5 |
| **A5 Event lifecycle** (WS5.1–5.4 + P-3 part 1) | min/max dates and latest-point coordinates; update detection on max date; upsert updates `status`, `title`, `lat`, `lon`, `nlp_summary`; write SQL NULL for no digest and fix `has_digest`; `last_seen`, `observation_state`, `closed_at` from the feed's `closed` field; **no closure from absence**. | A0, A1 | A2, A3, A4 |
| **A6 Trigger and concurrency** (P-5) | Token auth (disabled when unset), shared `asyncio.Lock`, 409 on overlap, task reference, rate limits, auth on the diagnostics endpoint, render.yaml `PIPELINE_TRIGGER_TOKEN` (`sync: false`). | A0; A3 for the diagnostics endpoint | A4, A5 |
| **A7 Per-event isolation and health** (WS5.5 + P-4) | Per-event try/except with counts; `finally` close; Polygon and naive-date handling in `match_events`; `pipeline_runs` table; `/api/health/live`; freshness-based `/api/health`; quota counts every attempt (WS5.8). | A0, A1; ideally A6 (the lock defines a "run") | A2, A3, A4 |
| **A8 Startup and reproducibility** (WS4) | README start command; file-relative `MODEL_PATH`; pin sklearn 1.8.0, xgboost 3.2.0, shap 0.54.1 (Tier 2 validated); constraints file; `PYTHON_VERSION` in render.yaml; dev requirements split; spaCy model in the build plus availability in health. | A0; A7 for the health field | A2–A6 |
| **A9 Backfills and controlled application** | Backfills B1–B6 as migrations, tested on copies. Then a reviewed, explicit application to the committed DB (backup first, verification report). | A1, A2, A4, A5, A7 | — |
| **A10 Stale-event lookup** (P-3 part 2) | Capped per-event EONET lookup after 3 unseen runs. | A5, A7; **Tier 3 Q1 results** (truncation) inform N and S | — |

**Can proceed in parallel after A0 (and A1 where marked):** A2, A3, A4, A5. A6 and A7 can proceed in parallel with each other. A8 can go at any time after A0 (only the health field waits for A7).

### Tests and acceptance criteria per stage
- **A0.**
  - Plain `pytest` from the repo root collects all offline tests.
  - The default run passes offline.
  - `test_match_events` passes, and fails if the type, distance, or date checks are removed.
  - **After the full suite, the committed DB's sha256 is unchanged.**
- **A1.**
  - A fresh DB and a copy of the committed DB both migrate to the current version.
  - Re-running is a no-op.
  - A backup file exists and passes `integrity_check`.
  - A forced failing migration rolls back, leaving version and data unchanged.
- **A2.** With the committed artifacts and the pinned versions:
  - the result has 5 keys, all from `FEATURE_COLUMNS`;
  - values equal xgboost `pred_contribs` for the predicted class (tolerance 1e-5);
  - a MODERATE fixture (`persons_affected=3000`) gives 5 non-empty entries;
  - an injected SHAP failure gives `shap_status='error'` and an error log line, not `{}`;
  - a characterisation test confirms labels are unchanged versus the pre-fix code on fixtures.
- **A3.**
  - Normal endpoints contain no `severity_label`, `severity_score`, or `shap_values` keys, and do contain `severity_status`.
  - Severity is still computed and stored (a DB assertion).
  - The diagnostics endpoint isn't reachable without auth.
  - Frontend: markers use one neutral style; no severity text, percentage, SHAP chart, or severity pie (component tests or a grep-based lint).
  - `severity_rationale` isn't rendered (pending owner question (a)).
- **A4.** SPA shell gives the fallback with `scrape_quality='rejected_boilerplate'`; an article is accepted; a null description gives no "None"; the existing scraper tests pass.
- **A5.** Fixtures:
  - ascending and descending geometry give correct `first_seen` and `last_updated`;
  - a newly appended point triggers reprocessing;
  - an unchanged feed doesn't;
  - an explicitly closed feed record gives `status='closed'` and `closed_at` set;
  - **absence gives `observation_state='not_observed'` with status still `open`;**
  - a no-digest event gives SQL NULL and `has_digest = 0`;
  - re-processing updates `nlp_summary`;
  - Tier 0 tests T1, T2, T3, T5 rewritten as regression tests now pass, inverted where they documented defects.
- **A6.**
  - No token configured gives 503.
  - A wrong token gives 401; a correct token gives 202.
  - A second trigger during a run gives 409.
  - A scheduled run during a manual run is skipped by the same lock.
  - Exceeding the configured limit gives 429.
  - Frontend source contains no token, and no `VITE_` variable references a token.
- **A7.**
  - 3 events with a bad middle one: 2 saved, `failed=1`, `last_error` names the event.
  - A Polygon fixture doesn't crash matching; naive and aware dates both compare.
  - `/api/health/live` gives 200 even if the DB is unavailable.
  - `/api/health` gives `pending`, `ok`, or `degraded` per P-4, with an injected clock.
  - Quota counts invalid, error, and valid replies as 3.
- **A8.**
  - The README command, run from the repo root in a clean venv built from the constraints, imports the app (subprocess test).
  - `MODEL_PATH` resolves from any cwd.
  - The pinned install passes A2's tests.
  - `/api/health` reports NLP model availability.
- **A9.**
  - The migration test on a copy gives the expected per-backfill row counts (B1 100, B2 1, B4 99; B3/B6 all rows; B5 count recorded).
  - `legacy_values` is complete; re-running is a no-op.
  - **Then**, as a separately approved step, apply to the committed DB with a backup, and include a before/after verification report in the change.
- **A10.** With mocked lookups: closed gives `closed`; open stays `open` and `not_observed`; the per-run cap is enforced; nothing is deleted.

### Stage risks and unresolved questions
- **A2:** correct attributions will show that the model relies on `persons_affected` (the leakage). That's acceptable because it's diagnostic-only after A3.
- **A3:** removing severity changes the product substantially, and the digest questions P-1 (a–c) are open.
- **A4:** if most sources are JS-only (U, Tier 3 Q3), most events will use fallback text.
- **A5:** latest-point coordinates move markers for multi-point events. That's a visible change to note in the release notes.
- **A6:** proxy IP handling for rate limits (U). Multiple workers are unsupported by the in-process lock.
- **A7:** run duration and Render sleep behaviour are unknown (U).
- **A9:** applying migrations changes the committed DB file in git. That needs your explicit approval at the time.

---

## 4. Track M stages (model validation; separate from Track A)

| Stage | Content | Depends on | Acceptance |
|---|---|---|---|
| **M1 Data source and label definition** | Identify a real, independently labelled source (e.g. historical GDACS alerts joined to EONET). Write a data card: provenance, licensing, coverage per category, label definition, and a leakage review (GDACS score as both feature and label source). | Owner prioritisation; Tier 3 Q4 (desk research plus a read-only sample) | Data card approved by the owner |
| **M2 Feature contract** | Freeze the feature definitions with honest missingness (P-2 indicator or native NaN), units (WS1.5), duration, and volcano encoding (WS1.3). | A4, A5 (honest inputs); M1 | A written contract plus tests that the feature builder implements it |
| **M3 Training-script hygiene** | Imputer fit on the train split only; versioned metadata (data hash, library versions, metrics) saved with artifacts. No artifact replacement until M4 passes. | M1, M2, A8 (pins) | Unit tests; reproducible run on fixed data |
| **M4 Evaluation** | Held-out real events; per-class and per-category metrics; single-feature-separation leakage check; calibration assessment; model card. The owner sets the acceptance thresholds. | M1–M3 | Owner sign-off. **Only then** can P-1 withholding be revisited, as a separate decision. |

Nothing in Track M may silently change the label policy or thresholds. Any change is proposed explicitly with M4's evidence.

---

## 5. Tier 3 (bounded; not started; prerequisites must be reviewed first)

| Item | Scope (fixed) | Answers | Prerequisites before running |
|---|---|---|---|
| T3-1 EONET extraction sample | 1 read-only GET of open events (`limit=100`); fetch **≤10** source URLs; save the raw HTML; run trafilatura plus the A4 quality gate **offline** on the saved files | Share of unextractable sources (Q3); geometry ordering on live records (Q1) | A4 merged (so the gate is the one being measured); output written outside the repository only |
| T3-2 GDACS sample | **1** `latest_events()` call; save the payload; run `match_events` offline on it | `fromdate` timezone format; why there are 0 matches (Q2) | A7 merged (format-agnostic matching) |
| T3-3 Event-limit check | From T3-1's single response, plus at most one extra category-filtered GET: count allowed-category events lost to filter-after-limit | F15 truncation; informs A10's N and S | Same as T3-1 |

**Prohibited throughout Tier 3:** a full pipeline run, Gemini calls, writing live data into the project DB, NLP model downloads, a frontend build. All outputs stay outside the repository.

---

## 6. Suggested review order
1. Approve policies P-1 to P-6, including P-1's open digest questions and the P-3 S value.
2. A0, then A1. Then A2 to A5 in parallel, then A6 and A7, then A8.
3. A9, applied to the committed DB only with your explicit approval at that point.
4. T3-1 to T3-3 once their prerequisites are merged and reviewed.
5. A10, informed by T3-3.
6. Track M on its own schedule.

# Disaster Intelligence Digest: prioritized remediation plan (proposal; nothing implemented)

**Baseline:** commit `814f90b`. The evidence is in `LEDGER.md` (Tiers 0–2) and the `out/`, `t1/out/`, and `t2/out/` directories. The repository was verified unchanged after every tier.

**Evidence labels used below**
- **C**: confirmed under execution.
- **D**: confirmed from committed-DB data only.
- **H**: hypothesis, not yet validated.
- **U**: open uncertainty.

**Ground rules for every change**
- No change to severity thresholds or labels. The current policy is: argmax of 3 classes, then `{0: LOW, 1: MODERATE, 2: HIGH}`, with confidence equal to the top-class probability.
- The confidence is **not calibrated** and must not be described as calibrated.
- Reconstructed vectors are test fixtures, not captured production inputs.
- Retraining is not treated as a fix for model validity.

---

## 0. Key corrected finding (carried forward)
- **Tier 0's hypothesis was wrong about the cause of all-LOW.** It attributed the result to out-of-range inputs: GDACS −1, `source_count` = 1, zero duration, zero NER counts.
- **Tier 2 refuted that as the cause (C).** Changing any of those features alone left the rating at **LOW 0.9991**.
- The committed model responds almost only to `persons_affected` and `casualties`. The synthetic generator assigns `persons_affected` disjoint ranges per label (train_model.py:70-79), so it leaks the label.
- Production text never yields `persons_affected`, so it is imputed with the median **399.5**, which falls in the GREEN/LOW range.
- The out-of-range inputs remain a **data-quality defect** (C, T10), just not the driver.

---

## 1. Priority order

| Order | Item | Why first |
|---|---|---|
| P0-a | WS3.1 Correct the SHAP extraction | Every stored explanation is wrong or empty (C). Small, isolated, low risk. |
| P0-b | WS5.1–5.4 Event lifecycle integrity (dates, update detection, closure, `'null'` digest, stale summary) | Wrong data is persisted and served for every event (C). |
| P0-c | WS1.1 Reject non-article extraction output | 99/100 events were analysed from "enable JavaScript" boilerplate (C/D). |
| P0-d | WS2.1 Disclose model provenance and status in API and UI | The dashboard shows severities from a synthetic-data model as if they were real assessments (C). This is the main risk of misleading users. It's a product decision for the owner; options are given below. |
| P1 | WS5.5–5.7 Per-event error isolation, honest health, trigger guard | Partial runs and a "healthy" status six months stale (C). Duplicate Gemini calls (C). |
| P1 | WS6 Test fixes and regression coverage | Needed to land the P0 changes safely. |
| P1 | WS4 Startup and dependency reproducibility | The README start command fails (C). Unpinned dependencies around version-bound pickles (U). |
| P2 | WS1.2–1.5 Feature-preparation corrections | They make inputs honest, but **won't change outputs** with the current model (C, T2-5). They only matter alongside WS2. |
| P2 | WS2.2–2.4 Model validity work | Large and needs owner decisions. It must not be done as "just retrain". |

**Must be fixed before real-data end-to-end testing:** WS3.1, WS5.1–5.6, WS1.1, WS6.1–6.3, WS4.1, and a decision on WS2.1. Otherwise an end-to-end run would again store mislabelled dates, never-closing events, boilerplate-based features, `'null'` digests, and fabricated SHAP. Its results couldn't be interpreted.

---

## WS1: Article extraction and feature preparation

### WS1.1 Reject non-article extraction output (P0)
- **Defect (C).** `scraper.py:30-31` accepts any non-None trafilatura result. Real trafilatura 2.3.1 returns "You need to enable JavaScript to run this app." for a JS-only page shell, and the scraper stores it with `source=<url>` (T1). That text appears in 99/100 committed rows (D, T11). It feeds NER (giving the entity `JavaScript/ORG`), keyphrases ("run app"), the regex signals, and the Gemini excerpt.
- **Intended behavior.** Text that isn't article content isn't treated as a successful extraction. The record shows which source the text came from (article or EONET fallback), so downstream consumers know what the features were computed on.
- **Smallest scope.**
  - Add a content-quality check in `fetch_source_text`, with a minimum word count (value to be agreed) and a small denylist of known shell phrases.
  - On failure, use the fallback.
  - Persist `scrape_source` (url or `"fallback"`) to `event_analysis`. This is a new column, so it needs a schema migration (see risks).
- **Tests and acceptance.**
  - The SPA-shell fixture returns the fallback with `source == "fallback"`.
  - The article fixture still returns article text.
  - The empty page returns the fallback.
  - The existing `test_scraper` tests still pass.
- **Depends on:** WS6.1 (pytest config), so the tests run.
- **Risks / unresolved.**
  - **U:** how many real EONET sources are JS-only. If most are, fallback text (title plus description) becomes the norm and `persons_affected` stays missing. Tier 3 Q3 answers this.
  - Thresholds can wrongly reject short but genuine bulletins.
  - JS rendering (e.g. headless browsers) is out of scope.

### WS1.2 Fallback text must not contain "None" (P0, part of WS1.1)
- **Defect (C).** `scraper.py:43-45` turns a null description into "Title None" (T6), seen in the DB as "Super Typhoon Sinlaku None".
- **Intended behavior:** a missing description contributes nothing.
- **Scope:** coalesce `None` to `""` on the same lines.
- **Tests:** a `description: None` fixture produces text equal to the title.
- **Risks:** none significant.

### WS1.3 Encode the volcano alert feature that the model expects (P2)
- **Defect (C).** The regex emits the string `volcano_alert` (nlp.py:32), but the model expects `volcano_alert_encoded` (scorer.py:33). The value is dropped (T2-4 `dropped_extra_keys`) and imputed every time.
- **Intended behavior.** Encode it as Normal=0, Advisory=1, Watch=2, Warning=3, the encoding documented in train_model.py:24.
- **Scope:** a mapping in the orchestrator's feature build.
- **Tests:** "Alert Level: Watch" produces `volcano_alert_encoded == 2` in the built features.
- **Depends on** WS2 for any effect on outputs.
- **Risk:** the training data is synthetic, so a "correct" encoding has no validated meaning yet.

### WS1.4 Missing GDACS values and placeholder duration (P2; needs a decision)
- **Defect (C).**
  - No GDACS match gives `-1` (orchestrator.py:69-70). Training never contains −1: 100% of production values fall outside the training range (T10).
  - `event_duration_days` is hard-coded to 0.0 (orchestrator.py:68), outside the training range of 0.11–29.95.
  - The schema's `duration_days` is never written.
- **Intended behavior.** "No data" is represented the way the model was trained to see missing data, and duration is computed from the event's own geometry dates.
- **Scope.**
  - (a) Compute duration as (latest − earliest geometry date), in days. Depends on WS5.1's date fix.
  - (b) **Decision needed:** keep −1, or use NaN so the imputer handles it. Training-time handling must be chosen together with WS2. Choosing a sentinel silently would be a scoring-policy change.
- **Tests.** A two-point geometry 4 days apart gives duration 4.0. The no-match path produces whatever value is agreed.
- **Risk:** **no effect on current outputs** (C, T2-5). Value only comes with a valid model.

### WS1.5 Unit-correct wind speed and other regex issues (P2)
- **Defect.** `wind_speed_mph` captures km/h and knots values unconverted (nlp.py:28). This is from code reading, not executed in the audit.
- **Intended behavior:** values converted to mph, or the unit stored alongside.
- **Scope:** capture the unit group and convert.
- **Tests:** "120 km/h" gives ~74.6; "100 knots" gives ~115.
- **Risk / U:** further regex false positives haven't been measured on real text (Tier 3 Q3).

---

## WS2: Training-data provenance, validity, evaluation

### WS2.1 Disclose model status in API and UI (P0; owner decision)
- **Defect (C).**
  - README.md:8 and commit be94c97 claim "historical GDACS data". The artifacts are consistent with the **synthetic random generator**: identical imputer medians, and 100% accuracy on the regenerated rows (T2-2).
  - The dashboard presents LOW/MODERATE/HIGH and a percentage "confidence" with no qualification (EventDetail.jsx:49).
  - The confidence is the top-class softmax probability (T2-6). It is **not calibrated**.
- **Intended behavior.** Users can tell that severity comes from an unvalidated, synthetic-data model, and the percentage isn't presented as a probability of severity.
- **Smallest scope.** Correct the README. Then pick one of three options; **the owner decides**:
  - **A.** Add a `model_status` field (e.g. `"experimental-synthetic"`) to `/api/events` and the detail endpoint, and show a visible notice in the UI.
  - **B.** A or C, plus hide the confidence percentage until it's validated.
  - **C.** Withhold severity display until WS2.3 passes.
  - **No thresholds or labels change in any option.**
- **Tests.** The API response contains the status field; a UI component test or snapshot shows the notice. A README check is manual.
- **Depends on** WS6 for the test harness.
- **Risk / U:** this is a product choice; option C removes the main feature.

### WS2.2 Establish a real labelled data source (P2; prerequisite for any retraining)
- **Problem (C).** There's no real training data. The generator leaks the label through `persons_affected` (T2-5). Retraining on the same generator would reproduce the leak, so **retraining alone is not a fix**.
- **Intended behavior.** Training and evaluation data are documented real records, with known label provenance and no feature computed from the label.
- **Scope (investigation first):**
  - Identify a candidate source, for example historical GDACS alerts joined to EONET events.
  - Document licensing and coverage.
  - Define the label (is the GDACS alert level the intended "severity"?).
  - Check for circularity: GDACS alert score is both a feature and the label's source, so near-target leakage is a risk.
- **Acceptance:** a written data card (source, date range, counts per class, label definition, leakage review), approved by the owner.
- **Risk / U:** real labels may be scarce for wildfires, which are 99% of current events. GDACS covers wildfires only partially.

### WS2.3 Evaluation on representative real-world examples (P2)
- **Intended behavior.** Before any model is shown as authoritative, it is evaluated on held-out real events across categories, with per-class metrics and a calibration assessment. The confidence must not be presented as calibrated until that assessment supports it.
- **Scope.** An evaluation script (offline) plus a frozen evaluation set. This does **not** use the reconstructed vectors as ground truth.
- **Acceptance.**
  - Metrics are reported per class and per category.
  - A leakage check: there must be no single feature with near-perfect separation, like the current `persons_affected`.
  - A model card that states its limitations.
- **Depends on** WS2.2, WS1 (honest features), and WS4.2 (pinned versions).
- **Risk / U:** the acceptance thresholds are the owner's call, not invented here.

### WS2.4 Fix training-script hygiene if retraining happens (P2)
- **Defects (code reading).**
  - The imputer is fit before the train/test split (train_model.py:115-123).
  - The per-category median imputation the PRD reportedly requires isn't implemented.
  - The script prints a report but doesn't persist metrics or version metadata.
- **Scope:**
  - fit the imputer on the training split only;
  - write a metadata file (data hash, library versions, metrics) next to the artifacts.
- **Tests:** a unit test that the imputer is fit on training rows only.
- **Depends on** WS2.2.

---

## WS3: SHAP output handling

### WS3.1 Extract per-class SHAP values correctly (P0)
- **Defect (C, T2-7).** shap 0.54.1 returns an `ndarray` of shape **(1, 17, 3)**, i.e. (sample, feature, class). These values are correct: additivity error ≤ 1.4e-6, and they're identical to xgboost's `pred_contribs`. `scorer.py:67` indexes `shap_vals[pred_class][0]`:
  - **class 0:** returns the 3 per-class values of feature 0. `zip` mislabels them as the first 3 feature names. That is the exact stored `{event_category_encoded: 0, geometry_type_encoded: 0, source_count: 0}` for 100/100 events.
  - **classes 1 and 2:** `IndexError`, swallowed (scorer.py:73-75) and stored as `{}`.
  - The real top attribution (`persons_affected` +3.39) never reaches the UI.
- **Intended behavior.** The top-5 features by |SHAP| for the predicted class, with correct names. If SHAP fails, that is visible (logged as an error and marked), not an empty or fabricated dict.
- **Smallest scope.**
  - In `score_event`, normalise the output: if it's a list, take `sv[pred_class][0]`; if it's a 3-D array, take `sv[0, :, pred_class]`. Assert the length equals `len(FEATURE_COLUMNS)` before zipping.
  - Replace `print` with logging.
  - Don't change the label logic.
- **Tests and acceptance.**
  - Using the committed model, offline, with a fixture vector:
    - the returned dict has 5 entries, keys from `FEATURE_COLUMNS`;
    - the values equal xgboost `pred_contribs` for the predicted class;
    - `persons_affected` is the top key for the LOW fixture;
    - a MODERATE fixture (`persons_affected` = 3000) returns 5 non-empty entries;
    - the sum of all class-SHAP values plus `expected_value` equals the margin (tolerance 1e-5).
  - Strengthen `test_score_event_keys`, which currently only checks `<= 5` entries.
- **Depends on** WS4.2 (pin shap, since the output format is version-dependent) and WS6.1.
- **Risks / U.**
  - The SHAP values stored for existing rows are wrong. They need a decision: recompute, or null them out with a flag (WS5.8).
  - The attributions will now *correctly* show that the model relies on `persons_affected`. That is honest, but it exposes WS2's leakage to users, which is another reason WS2.1 should land at the same time.

### WS3.2 SHAP semantics in the UI (P1)
- **Issue.** EventDetail.jsx:126 says red "increases severity score". The values are log-odds contributions for the *predicted* class, not a severity score. This is from code reading.
- **Intended behavior:** the legend states that values are contributions to the predicted class's log-odds.
- **Scope:** a text change in the UI, plus an API field naming the class explained.
- **Tests:** a component test of the legend text.
- **Depends on** WS3.1.

---

## WS4: Startup and dependency reproducibility

### WS4.1 A working start command (P1)
- **Defect (C, T1).** `python backend/app/main.py` (README.md:27) fails at main.py:9 with `No module named 'backend'`. The Render form (`PYTHONPATH=.` with uvicorn) resolves the import. `scorer.py:9-10` uses cwd-relative model paths.
- **Intended behavior:** the documented commands work from a fresh clone.
- **Scope:**
  - Change the README to `uvicorn backend.app.main:app` from the repo root (or `python -m backend.app.main`).
  - Make `MODEL_PATH` file-relative, as `database.py:4` already is.
- **Tests:** a subprocess test that imports `backend.app.main` from the repo root; a unit test that `MODEL_PATH` exists regardless of cwd.
- **Risk:** low.

### WS4.2 Pin dependencies and the Python version (P1)
- **Defect.**
  - `requirements.txt` has no versions.
  - The pickles are version-bound: sklearn 1.8.0 and xgboost 3.2.0 are recorded in the artifacts (C).
  - SHAP's output format is version-dependent (C).
  - There's no Python version pin for Render.
  - Test packages are mixed into runtime requirements.
- **Intended behavior:** a fresh install reproduces the validated environment.
- **Scope:**
  - Pin at least scikit-learn==1.8.0, xgboost==3.2.0, and shap==0.54.1 (the versions validated in Tier 2).
  - Generate a lock or constraints file.
  - Add `PYTHON_VERSION` to render.yaml.
  - Split dev dependencies into a separate file.
- **Tests:** CI install from the lock, then the WS3.1 tests pass.
- **Risk / U:** **untested** whether other versions load the artifacts (T2-1). Pinning avoids the question rather than answering it.

### WS4.3 spaCy model in deployment (P1)
- **Defect.** `en_core_web_md` isn't installed by render.yaml:5, and nlp.py:12-16 silently sets `nlp=None`.
  - Tier 0/1 showed the silent-degradation code path with stubs (C).
  - Real behavior on Render is not executed (H).
- **Intended behavior:** a missing NLP model is a visible failure, or an explicit and reported degraded mode.
- **Scope:** add the model install to the build command; report model availability in `/health`.
- **Tests:** a unit test that `/health` reports `nlp_model: unavailable` when loading fails.
- **Depends on** WS5.6.

---

## WS5: Pipeline triggering, concurrency, error handling, health
(This also covers the event-lifecycle integrity defects.)

### WS5.1 Correct first_seen / last_updated and update detection (P0)
- **Defect (C, T1).** With ascending geometry dates, `first_seen` gets the newest date and `last_updated` the oldest (orchestrator.py:38, 105). An event with a newly appended observation is **never re-processed**. One committed row is consistent with this (EONET_19481, D).
- **Intended behavior.** `first_seen` = earliest, `last_updated` = latest, and a newer observation triggers re-processing.
- **Scope.** Derive both from min and max of the parsed geometry dates, which **works whatever the ordering** and avoids depending on Tier 3. Compare `last_updated` against the max. Use the coordinates of the latest point for lat/lon, month, and hemisphere.
- **Tests:**
  - an ascending fixture and a descending fixture each produce correct dates;
  - appending a newer point causes reprocessing (`analysed_at` changes);
  - an unchanged feed causes no reprocessing.
- **Risk / U:** using latest-point coordinates moves map markers for multi-point events. That's a behavior change to state in the change notes.

### WS5.2 Record event closure (P0)
- **Defect (C, T2).** Status stays `open` in every case: the event drops out of the open feed; it arrives with `closed` set; it arrives with `closed` set and changed geometry. The upsert at orchestrator.py:102 doesn't update `status`. `seed()` saves 0 of the 3 closed events it fetches. The committed DB has 0 closed events, all last updated in April (D).
- **Intended behavior.**
  - The upsert updates `status` (and title, lat, lon).
  - Events missing from the open feed are reconciled, either by fetching their status or marking them stale (**owner decision**).
  - `seed()` persists the closed events it fetched, or is documented as open-only.
- **Scope:** extend the upsert's `DO UPDATE` clause; add a reconciliation step after ingestion; either fix or rename the seed function.
- **Tests:**
  - a closed fixture sets `status='closed'`, and `/api/events` excludes it;
  - absence from the feed has the agreed effect;
  - seeding 3 closed fixtures saves 3 rows.
- **Risk / U:** "absent from the feed" can mean either closed or truncated by `limit=100` (F15, not quantified; Tier 3 Q1).

### WS5.3 Store a missing digest as SQL NULL (P0)
- **Defect (C, T3 / T1).** `json.dumps(None)` is stored as TEXT `'null'` (orchestrator.py:124). All 100 rows report `has_digest: true` through the real API, and `verify_pipeline` counts them as digests.
- **Intended behavior:** no digest means SQL NULL and `has_digest = false`.
- **Scope:**
  - write None when there's no digest;
  - make `has_digest` also exclude `'null'`, which handles existing rows without a data migration;
  - optionally a one-off migration `UPDATE … SET gemini_digest=NULL WHERE gemini_digest='null'` (owner decision, WS5.8).
- **Tests:** a LOW fixture gives NULL and `has_digest == 0`; a row with legacy `'null'` also gives `has_digest == 0`.

### WS5.4 Keep `nlp_summary` consistent on update (P0)
- **Defect (C, T5).** `nlp_summary` is missing from the conflict-update list (orchestrator.py:116-119). After re-processing, the keyphrases update but the summary stays stale.
- **Scope:** add `nlp_summary=excluded.nlp_summary`.
- **Tests:** re-processing with new keyphrases updates the summary.

### WS5.5 Per-event error isolation (P1)
- **Defect (C, T4).** A single bad event aborts the whole run (one try at orchestrator.py:21-152). Event 1 is saved and the rest are lost. A Polygon EONET geometry raises `IndexError` (an audit correction: not `TypeError`). A timezone-naive GDACS `fromdate` raises `TypeError` and crashes the whole ingestion. The connection isn't closed on error.
- **Intended behavior.** A failing event is logged with its ID and skipped, the rest are processed, and the run result reports counts (processed, skipped, failed).
- **Scope:**
  - a try/except per event;
  - `finally: conn.close()`;
  - in `match_events`, handle Polygon geometry (use a representative point, e.g. the first ring vertex or centroid) and naive dates (assume UTC);
  - a run summary returned and logged.
- **Tests:**
  - 3 events with a bad middle one save 2 and report 1 failed;
  - a Polygon fixture doesn't crash matching;
  - naive and aware dates both compare.
- **Risk / U:** whether real GDACS dates are naive is unverified (Tier 3 Q2). The fix is format-agnostic, so it doesn't block.

### WS5.6 Honest health reporting (P1)
- **Defect (C, T4 / T1).** `/health` always reports `"healthy"`. `last_pipeline_run` is `MAX(analysed_at)`: the last *processed event*, not the last run. It showed 2026-04-18 on 2026-10-21 and still said healthy.
- **Intended behavior.** Health reports the last run start and end, the outcome, failure counts, and model availability, and degrades when the last successful run is older than an agreed threshold (**owner decision**).
- **Scope:** a small `pipeline_runs` table (or an in-memory record) written by `run_pipeline`; `/health` reads it.
- **Tests:** a failed run gives a degraded status; a stale success beyond the threshold gives degraded.
- **Depends on** WS5.5.

### WS5.7 Guard the manual trigger and prevent concurrent runs (P1)
- **Defect (C, T1 / T8).** `POST /api/pipeline/trigger` has no authentication. Two triggers run concurrently, and 2 concurrent runs made **2 Gemini calls for one event**. The slowapi limiter is registered with **0 limits**, and 100 GETs returned 100 × 200. `asyncio.create_task` keeps no reference.
- **Intended behavior.** Only one pipeline run at a time, whether scheduled or manual. The trigger requires an authorised caller. The rate limits are whatever the owner sets.
- **Scope:**
  - a module-level `asyncio.Lock` (single-process deployment; multi-worker needs a DB lock, U);
  - the trigger returns 409 when a run is in progress;
  - a shared-secret header check (env var);
  - `@limiter.limit` on routes with owner-chosen limits;
  - keep a task reference.
- **Tests:**
  - two triggers give one run and one 409;
  - an unauthenticated trigger gives 401;
  - the limiter returns 429 above the configured limit.
- **Risk / U:** limit values and the authentication mechanism are owner decisions.

### WS5.8 Quota accounting (P1)
- **Defect (C, T7).** Failed and malformed Gemini responses are not counted: 3 API calls left the counter at 1. **Refuted:** the race within one process. Untested: a multi-worker race.
- **Intended behavior:** every API call attempt counts against the quota.
- **Scope:** increment before or around the call, not only on a successful parse.
- **Tests:** invalid JSON, an error, and a valid reply give a counter of 3.

### WS5.9 Existing-data remediation (P1; owner decision)
- **Problem.** The committed DB contains rows produced by the defects above: wrong SHAP, `'null'` digests, swapped dates, boilerplate text, never-closed events.
- **Options:**
  - (a) Leave it, with fixes applied going forward and API-side guards (WS5.3).
  - (b) A one-off migration script for SQL-fixable fields only.
  - (c) Re-seed after the P0 fixes. This needs live data, i.e. Tier 3.
- **This plan doesn't choose.** Any migration is run on a copy first.

---

## WS6: Test failures and regression coverage

### WS6.1 Test configuration (P1, prerequisite)
- **Defect (C, T1).** Plain `pytest` fails to collect: `No module named 'backend'`. `python -m pytest` works.
- **Scope:** `pytest.ini` or `pyproject` `[tool.pytest.ini_options]` with `pythonpath = .`, `asyncio_mode`, and a `network` marker.
- **Acceptance:** plain `pytest` collects all offline tests from the repo root.

### WS6.2 Fix `test_match_events` (P1)
- **Defect (C, T0 / T1).** The mocks are attribute objects, but `match_events` uses `dict.get`, so the test fails with `AttributeError`.
- **Scope:** rewrite the mocks as GeoJSON-style dicts matching what `ingest.get_gdacs_events` returns. Add Polygon and naive-date cases (WS5.5).
- **Acceptance:** passes; it also fails if the type, distance, or date logic is broken.

### WS6.3 Isolate tests from the committed DB (P0 for safety)
- **Defect (C, T9).** `test_gemini_quota_guard` deletes today's quota row from whatever `DB_PATH` points at. By default that's the committed DB.
- **Scope:** a `conftest.py` fixture that points `database.DB_PATH` at a `tmp_path` DB for every test.
- **Acceptance:** after the full suite, the committed DB's sha256 is unchanged.

### WS6.4 Separate network-dependent tests (P1)
- **Defect (C, T1).** `test_fetch_eonet_events` needs live EONET, and test_nlp needs model downloads.
- **Scope:** mark them `@pytest.mark.network`, excluded by default; replace them with a recorded-fixture test for the parsing logic.
- **Acceptance:** the default run passes offline.

### WS6.5 Regression tests for every fix (P1)
- One test per fix above, as listed in each item.
- **Plus** an offline model test using the committed artifacts and pinned versions, asserting:
  - the reconstructed baseline fixture gives LOW. This documents current behavior and is labelled as a *characterisation* test, not a correctness claim.
  - the SHAP structure (WS3.1).
- **Acceptance:** CI runs the offline suite on every push.

### WS6.6 Make existing tests meaningful (P2)
- `test_score_event_keys` passes despite malformed SHAP. Strengthen it per WS3.1.
- `verify_pipeline.py` checks only the first row and counts `'null'` digests. Fix it per WS5.3.
- `smoke_test.py`'s rate-limit check can't fail. Assert 429 once WS5.7 defines limits.

---

## 2. Bounded Tier 3 (only where it answers a specific open question)

| Q | Question it answers | Why it matters | Minimal procedure | When |
|---|---|---|---|---|
| Q3 | What share of EONET source URLs are JS-only or otherwise unextractable? | Decides whether WS1.1's fallback becomes the norm, and so whether text-derived features can ever populate | One read-only EONET open-events GET; fetch ≤10 source URLs; run trafilatura plus the WS1.1 quality check offline on the saved HTML | After WS1.1, before WS2.2 scoping |
| Q2 | Are GDACS `fromdate` values timezone-naive, and why are there 0 GDACS matches? | Confirms the WS5.5 crash path is live, and whether enrichment ever works | One `latest_events()` call; inspect the fields; run `match_events` offline on the saved payload | After WS5.5 (the fix is format-agnostic, so this is confirmation only) |
| Q1 | Is EONET geometry ascending? How many allowed-category events are cut by `limit=100`? | Quantifies F15 truncation and the impact of WS5.2 reconciliation; confirms the real-data impact of WS5.1 | The same EONET fetch as Q3, with no extra calls | Together with Q3 |
| Q4 | Is there a usable real labelled source for severity? | Prerequisite for WS2.2 and WS2.3 | Desk research plus one read-only sample of historical GDACS alerts; no training | When the owner prioritises WS2 |

**Not proposed:** NLP model downloads (F13/F8), frontend build (F18/F19), and an end-to-end live run until the P0 items land.

---

## 3. Remaining uncertainties (not resolved by the audit)
- Whether other library versions load the artifacts and produce the same outputs (F14).
- Which shap version, if any, produced the list format the code expects.
- Whether the stored rows came from inputs identical to the reconstructions: month and hemisphere are approximated, and GDACS is assumed −1.
- Real-world prevalence of the scraper failure, the GDACS date format, and EONET ordering and truncation (Tier 3 Q1–Q3).
- The multi-worker quota race and SQLite lock behavior (untested).
- Event-loop blocking (F8), the silent spaCy failure on Render (F13), and the frontend defects (F18/F19): found by code reading only, never executed.

---

## 4. Owner decisions (recorded 2026-10-21; these supersede the open options above)
1. **Model status.** Withhold severity ratings and confidence percentages from the normal user-facing interface until the model has been evaluated on representative, independently labelled real events. Preserve diagnostic outputs for internal investigation. No replacement scores, and no calibration claims. This chooses **option C** of WS2.1.
2. **Missing GDACS values.** Represent missingness explicitly, not as `-1`. Check the schema, imputer, feature order and training pipeline first. Define and test a consistent policy. A nullable DB value must not be assumed safe to pass straight to the model.
3. **Events absent from the open feed.** Don't infer closure from absence. Preserve history, track `last_seen`, and distinguish *explicitly closed* from *no longer observed*. Propose source-specific closure and stale rules before implementing them.
4. **Health.** Establish the intended schedule first. Derive a freshness threshold from that schedule, with a grace period. Expose the last successful run and the last error. Separate process liveness from pipeline health.
5. **Manual trigger.** Require server-side authentication, prevent concurrent duplicate runs, and add rate limiting. Pick the smallest mechanism that fits the existing deployment. Never put secrets in frontend code.
6. **Existing database.** Preserve existing rows: no reseeding, deleting, or overwriting to resolve findings. Use versioned migrations and deterministic backfills, with backups, and test migrations on disposable copies.

The staged implementation plan that applies these decisions is in `IMPLEMENTATION_PLAN.md`. It supersedes the WS2.1 options, WS5.2's reconciliation option, WS5.6's threshold, WS5.7's mechanism, and WS5.9's options.

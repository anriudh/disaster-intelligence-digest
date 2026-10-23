# Phase 1, Tier 0 validation ledger

**Run conditions**
- Code: a disposable `git archive` copy of `814f90b`.
- Network: none (`unshare --net`).
- Environment: `env -i`, so no credentials and no Gemini key.
- Third-party imports: placeholder stubs. Anything that would touch the network, load a model, or unpickle raises instead.
- Databases: each test used a temporary DB under `p1/work/` (outside the repository).
- Raw output: `out/tier0.json`. Harness: `tests/`.

**Repository integrity:** HEAD, `git status`, and the sha256 of all 49 tracked files are identical before and after (`out/integrity-{before,after}.txt`).

Grades: **R** = defect reproduced. **M** = mechanism isolated. **I** = impact measured.

| Test | Finding | Result | Evidence |
|---|---|---|---|
| T1 | F5 geometry order / update detection | **Confirmed (R, M)** | With geometry dates in ascending order `[04-01, 04-05]`, the stored `first_seen` is 04-05 and `last_updated` is 04-01, so the two are swapped. After a newer point (04-09) was appended, the event was **not re-processed**: scored once, `analysed_at` unchanged. Whether real EONET data is ascending is still unverified live; the committed-DB row EONET_19481 (`first_seen` 04-18 > `last_updated` 04-09) is consistent with it. |
| T2 | F6 closure / seeding | **Confirmed (R, M)** | Status stays `open` in all three cases: the event disappears from the feed; it arrives with `closed` set and the same geometry (skipped); it arrives with `closed` set and changed geometry (re-processed, but the upsert doesn't update `status`). It is still returned by `/api/events`. `seed()` fetched 3 closed events and **saved 0**; it only calls `run_pipeline()`. |
| T3 | F7 `'null'` digest | **Confirmed (R, M)** | The stored value is the TEXT `'null'`. `/api/events` returns `has_digest = 1` for an event with no digest. The `verify_pipeline` query counts it as a digest. The detail endpoint shows `None`, so the UI is unaffected. |
| T4 | F9 abort / health | **Confirmed (R, I)** | When event 2 of 3 is a Polygon, or when the scorer raises on event 2: `run_pipeline` returns False, only event A is saved, and event C is never processed. `/health` still says `"healthy"`, with a recent `last_pipeline_run`. |
| T4 | F15 polygon / timezone | **Confirmed, mechanism corrected** | A Polygon EONET event fails in `match_events` with **IndexError** (`coordinates[1]` on a nested ring list), not the TypeError Phase 0 predicted. A GDACS `fromdate` without timezone raises `TypeError: can't subtract offset-naive and offset-aware datetimes`. A timezone-aware date matches. Whether real GDACS dates lack a timezone is still unverified live. |
| T5 | F16 stale `nlp_summary` | **Confirmed (R, M)** | On re-processing, `keyphrases` updates (alpha, bravo → zulu, yankee) but `nlp_summary` stays "alpha, bravo". |
| T6 | F4 fallback text | **Confirmed (R, M)** | A null description produces "Super Typhoon X None". This matches the committed-DB row "Super Typhoon Sinlaku None". |
| T7 | F11 quota accounting | **Confirmed in part; race refuted in-process** | 3 API calls (invalid JSON, error, valid) leave the counter at **1**, so failed calls aren't counted. Two concurrent in-process calls at count 79 resulted in 1 API call and a final count of 80, so **there is no race within one process**. This matches the revision-1 correction. A multi-worker race is untested. |
| T8 | F10 concurrent runs | **Confirmed (R, I)** | Two simultaneous `run_pipeline` runs on one MODERATE event made **2 Gemini calls** (quota 2) for a single event. No SQLite lock error occurred in this single-process test. |
| T9 | F17 existing tests | **Confirmed (R)** | `test_match_events` **fails** with `AttributeError: 'MockGDACSEvent' object has no attribute 'get'`; `test_haversine` passes. `test_gemini_quota_guard` passes but **writes to whatever DB is configured**: today's row (count 37) was deleted, and the file changed. Pointed at the committed DB, which is the default, it would reset the real quota counter. |
| T10 | F1 / F2 training vs inference | **Confirmed (I, partial M)** | The training generator is synthetic (runs from code, 1000 rows). Production feature values **outside** every training value: `event_duration_days` = 0 (train 0.11–29.95), `gdacs_alert_score` = −1 (train 0–6.98), `gdacs_population_exposure` = −1 (train 9–1e6), `ner_location_count` = 0 (train 1–4), all 100%. `persons_affected` and `casualties` are never NaN in training but always NaN in production. In training, **every** row with `source_count = 1` (all 100 production events) is GREEN (LOW): 153/153. Every row with `gdacs_alert_score < 2` is GREEN: 416/416. This explains all-LOW as consistent with the training data. Confirming the model's actual response needs Tier 2. |
| T11 | F2 / F3 / F4 / F7 data | **Re-confirmed** | 100/100 LOW, all with the **identical** score 0.9991. One identical SHAP dict of 3 zeros for all 100. 100/100 digests `'null'`. 99/100 `raw_text` = "You need to enable JavaScript to run this app." 0 GDACS rows. 0 closed events. Last update 2026-04-15. |

## Still open (needs a later tier)
- **F3:** SHAP mechanism (the shape of shap's output). Tier 2.
- **F2:** the model's actual response to in-range inputs. Tier 2.
- **F14:** version coupling of the pickles. Tier 2.
- **F12:** README start command. Tier 1.
- **F4:** real trafilatura behaviour. Tier 1; prevalence needs Tier 3 live pages.
- **F17:** `pytest` vs `python -m pytest` import path. Tier 1.
- **F10:** rate limiter. Tier 1.
- **F5 / F15 real formats:** Tier 3 live EONET and GDACS.
- **F13 / F8:** Tier 3 models.
- **F18 / F19:** Tier 3 frontend.

---

# Tier 1 validation ledger

**Environment**
- Python 3.13.16 (GCC 13.3.0), Linux 6.18 x86_64.
- uv 0.11.32 venv at `p1/t1/venv` (outside the repository, confirmed before install).
- Installed: wheels only, 60 packages, 204 MB. Full list in `t1/out/freeze.txt`. Key versions: fastapi 0.158.1, starlette 1.9.0, httpx 0.28.1, slowapi 0.1.10, limits 5.8.0, apscheduler 3.11.3, trafilatura 2.3.1, lxml 6.1.3, lxml-html-clean 0.4.5, pytest 9.1.1, pytest-asyncio 1.4.0, python-dotenv 1.2.4, gdacs-api 2.0.0, google-genai 2.32.0, pandas 3.0.6, numpy 2.5.4.
- Network was used **only** for the install, with a minimal `env -i` (proxy and CA variables only).
- **Every check ran under `unshare --net` and `env -i`:** no network, no credentials, no `GEMINI_API_KEY`, and no `.env` in the copy.
- Code: a fresh `git archive` copy at `t1/copy`, verified 49/49 against the repo hashes.
- The API checks used a separate DB copy at `t1/work/api.db`.
- Still stubbed (raise if used): spacy, keybert, sentence_transformers, joblib, shap. These are Tier 2/3.

**Integrity:** the repository is unchanged after Tier 1 (HEAD, status, 49 hashes). The `t1/copy` is unchanged too.

| Finding | Command / check | Result | Grade |
|---|---|---|---|
| **F12 README start command** | `cd t1/copy; python backend/app/main.py` (no PYTHONPATH) | `main.py` line 9: `ModuleNotFoundError: No module named 'backend'`, exit 1. fastapi, apscheduler, and slowapi (lines 2–8) imported fine, so the failure is the package path. | **R + M** |
| F12, Render form | `PYTHONPATH=. python -c "import backend.app.main"` | Resolves `backend`. It then stops at `import spacy` (nlp.py:1), which is not installed in Tier 1. So the import path works; a full startup needs Tier 2/3 packages. | M (contrast case) |
| **F17 import path** | `pytest --collect-only` vs `python -m pytest` vs `PYTHONPATH=. pytest`, on test_ingest and test_scraper | Plain `pytest`: **2 collection errors**, `No module named 'backend'`. `python -m pytest` and `PYTHONPATH=. pytest`: 8 tests collected. There is no pytest config or conftest in the repo. | **R + M** |
| **F17 offline run** | `python -m pytest -p no:cacheprovider -rA backend/tests/test_ingest.py backend/tests/test_scraper.py` (net disabled) | **6 passed, 2 failed.** `test_match_events` fails with `AttributeError: 'MockGDACSEvent' object has no attribute 'get'` (ingest.py:78), a test-vs-code contract mismatch. `test_fetch_eonet_events` fails with `ConnectError` (name resolution), showing the test requires live network. The scraper tests pass but really sleep (3.4 s, 2.3 s, 1.9 s). Full-suite collection: `test_nlp` needs spacy, `test_scorer` needs joblib (Tier 2/3). Output in `t1/out/pytest-offline.txt`. | **R** |
| **F4 scraper boilerplate** | real `trafilatura.extract` on fixtures; real `scrape_event_sources` with httpx mocked | A JS-only page shell yields exactly **"You need to enable JavaScript to run this app."**, and the scraper **accepts it as article text**, with `source` set to the URL instead of `fallback`. A real article extracts correctly. An empty page goes to the fallback "Sawmill Fire None". This matches 99/100 committed rows, so trafilatura plus the "any non-None is success" rule (scraper.py:30-31) is the mechanism. How common it is on live sources still needs Tier 3. | **R + M + I** (impact from DB) |
| **F10 rate limiter** | 100 × `GET /api/events` through the real FastAPI app (httpx ASGITransport) | **100 × 200, 0 × 429.** slowapi has 0 route limits and no default limits registered. | **R + M** |
| **F10 unauthenticated trigger** | 2 × `POST /api/pipeline/trigger`, with `run_pipeline` replaced by an instrumented slow stub | Both return 200 "Pipeline triggered", with no auth. **Peak concurrent runs: 2.** Together with Tier 0 T8 (2 Gemini calls for one event), duplicate external calls are possible. | **R + M**; I via T8 |
| **F7 impact via real API** | `GET /api/events` on a copy of the committed DB | **100/100 events report `has_digest: true`**, while the detail endpoint shows `gemini_digest: null`. | **I** |
| F16 payload (informational) | `GET /api/events/{id}` | 9,502-byte response. `embedding` is returned as an unparsed **string** (8,431 chars) that the frontend never uses. Also includes `raw_text`. | observed |
| **F9 health** | `GET /api/health` | `"status": "healthy"` with `last_pipeline_run` 2026-04-18 (six months before the run date, 2026-10-21). Health does not reflect staleness or failure. | **I** |

## Tier 1 updates to the baseline
- **Confirmed:** F12, F17 (import path, failing test, network dependency), F4 mechanism, F10 (limiter inactive; trigger allows concurrency), plus F7 and F9 impact.
- **Not done in Tier 1 (by design):** a full app startup, which needs spacy and model packages, so it is Tier 2/3.

## Still open
- **Tier 2:** F2 (the model's actual response), F3 (SHAP mechanism), F14 (pickle loading under current library versions), and running `test_scorer`.
- **Tier 3:** live formats for F5 and F15, F4 prevalence, F13, F8, F18, F19.

---

# Tier 2 validation ledger (offline model validation)

## Environment and safeguards
- **Code:** a fresh `git archive 814f90b` copy at `t2/copy`, verified 49/49. cwd was the copy root, because `scorer.py` uses repo-relative `MODEL_PATH`.
- **Tests ran** under `unshare --net` (no network) and `env -i` (no credentials, no `GEMINI_API_KEY`).
- **SQLite:** any non-read-only connection is refused. Nothing was written to any database.
- **Python:** 3.13.16 (GCC 13.3.0), Linux x86_64. The venv is `t2/venv`, outside the repository, confirmed before install. Wheels only, 947 MB (mostly the NCCL library pulled by xgboost). Full list in `t2/out/freeze.txt`.
- **Versions:**
  - **Pinned to versions recorded inside the artifacts:** scikit-learn **1.8.0** (from `_sklearn_version` in `imputer.pkl`) and xgboost **3.2.0** (from the booster's embedded `version` field).
  - **The repository pins nothing.** `requirements.txt` lists `xgboost`, `shap`, `joblib`, `pandas`, `numpy`, `scikit-learn` without versions, and there's no lockfile or other manifest.
  - **Selected for this test, not project-declared:** shap 0.54.1, joblib 1.6.0, numpy 2.5.4, pandas 3.0.6, scipy 1.18.1, pytest 9.1.1, nvidia-nccl-cu12 2.32.3 (an xgboost wheel dependency).
- **Stubbed:** only `google.genai` and `dotenv`, through an audit-only pytest plugin (`t2/harness/t2stubs.py`), because `test_scorer` imports `gemini.py`. No application code or manifests were changed.

## Artifact inspection before loading (static; preliminary, not proof of safety)

| Artifact | Size | SHA-256 | Globals referenced | Suspicious constructs |
|---|---|---|---|---|
| `backend/models/severity_model.pkl` | 232,558 B | `dec3b0b1…5331` | `xgboost.sklearn.XGBClassifier`, `xgboost.core.Booster`, `builtins.bytearray` | none. 1 REDUCE (the bytearray holding the 231,657-byte UBJSON booster) and 2 BUILD. No os, subprocess, eval, exec, getattr, or similar. |
| `backend/models/imputer.pkl` | 1,199 B | `ece13ae9…3235` | `sklearn.impute._base.SimpleImputer`, `joblib.numpy_pickle.NumpyArrayWrapper`, `numpy.ndarray`, `numpy.dtype`, `numpy._core.multiarray._reconstruct` | none. The joblib layout is: outer pickle; nested pickle for the object array `feature_names_in_`; a 16-byte-aligned raw float64 buffer (`statistics_`, decoded statically); a tail with `_sklearn_version='1.8.0'`. |

- **Provenance:** both files were committed in `be94c97` (author anriudh, 2026-04-18), in the same commit as `train_model.py`, and never changed since.
- **Booster metadata, statically:** `num_class` 3, `num_feature` 17, `num_trees` 300, objective `multi:softprob`.
- **Decision:** loading proceeded in the disposable offline copy. Scripts: `t2/harness/static_inspect.py`; output in `t2/out/static_*`.

| # | Finding | Result | Evidence |
|---|---|---|---|
| T2-1 | **F14** artifact loading | **Confirmed loadable under the recorded versions; drift untested** | `scorer.load_models()`, the application's own code path, loaded both artifacts with **no errors and no warnings** under sklearn 1.8.0, xgboost 3.2.0, and shap 0.54.1. Model: `XGBClassifier`, classes [0, 1, 2], 17 features, 100 rounds, `multi:softprob`; the config's version is [3, 2, 0]. Imputer: `median`; `feature_names_in_` order equals `scorer.FEATURE_COLUMNS`; `statistics_` equals the static decode. (`_sklearn_version` reads None after load because sklearn strips it during unpickling; the static value is 1.8.0.) **Not tested:** whether other versions load, since the repo is unpinned. F14 stays a **risk, inconclusive**. |
| T2-2 | **F1** provenance | **Confirmed: consistent with the synthetic script** (not proof) | The imputer medians are **identical** (max abs diff 0.0) to the medians of `fetch_historical_data()`, the seeded random generator. The model predicts the regenerated synthetic rows with **accuracy 1.0**. The hyperparameters (100, 5, 0.1, 42) match `train_model.py:126-133`. |
| T2-3 | `test_scorer` | **2 passed, 1 deselected** | `test_model_loading` and `test_score_event_keys` pass (`t2/out/pytest-test_scorer.txt`). `test_gemini_quota_guard` was deselected because it writes a database (Tier 0 T9 already covered it). `test_score_event_keys` **passes even though SHAP is malformed**, because it only asserts `len(shap_values) <= 5`. That's a coverage gap. |
| T2-4 | **F2** all-LOW / 0.9991 | **Confirmed (R, M)** | The 100 vectors were **RECONSTRUCTED** from copied-DB fields; they are not captured pipeline inputs. Approximations: month comes from stored `last_updated`, hemisphere from stored `lat`, GDACS is -1 because the enrichment table is empty. They collapse to **2 distinct vectors** (99 + 1). Both produce **identical raw margins [4.33607, -3.24916, -3.49266]**, probabilities [0.999095, 0.000507, 0.000398], argmax 0, so **LOW / 0.9990948**. The match with stored values is **100/100** for label, score (4 decimal places), and SHAP dict. Input prep (`scorer.py:46-54`): 2 extra keys are dropped (`volcano_alert`, `magnitude`); 6 signal columns arrive as `object` dtype holding None; 7 columns are NaN before imputation (all regex signals plus `volcano_alert_encoded`), and nothing is non-finite after it. **Establishes:** the stored ratings are exactly reproducible from these inputs with the committed artifacts. **Doesn't establish:** that the stored rows came from identical live inputs, or what the true severity of these events was. |
| T2-5 | **F2** what drives the rating (sensitivity within the model) | **Mechanism refined; corrects the Tier 0 hypothesis** | Single-feature changes to the reconstructed vector: GDACS missing as NaN, GDACS 2.5/50k, `source_count` 3 or 6, duration 7, `ner_location_count` 2, and all-NaN each leave **LOW 0.9991**. GDACS 5/500k gives LOW 0.9987. **`persons_affected` = 3000 alone gives MODERATE 0.9966.** The SHAP for the LOW prediction is dominated by `persons_affected` (+3.39); every other feature is about 0. Interpretation: the model has learned essentially only `persons_affected` and `casualties`. That fits the synthetic generator, which draws `persons_affected` from disjoint ranges per label (GREEN 0–500, ORANGE 1000–5000, RED 5000–20000; train_model.py:70-79): label leakage. In production, the regex never finds `persons_affected` (the scraped text is boilerplate), so it's imputed with the median **399.5**, inside the GREEN range, giving LOW. **The −1 GDACS defaults, `source_count` = 1, zero duration, and zero NER counts do not drive the result**, contrary to the Tier 0 inference from training ranges. Tier 0's out-of-range observation stands as a data-quality issue, but not as the cause of all-LOW. |
| T2-6 | Severity and confidence mapping | **Confirmed** | `predict_proba` (softmax of raw margins) → `argmax` → `LABEL_MAP {0: LOW, 1: MODERATE, 2: HIGH}` (scorer.py:27, 58-60). The confidence is `probs[argmax]`, the top-class probability (scorer.py:60), not a severity magnitude. Training labels GREEN, ORANGE, RED (0, 1, 2) correspond to LOW, MODERATE, HIGH. |
| T2-7 | **F3** SHAP | **Confirmed (R, M); fails in downstream indexing, not in the explainer** | `explainer.shap_values(X)` returns an `ndarray` of shape **(1, 17, 3)**, i.e. (sample, feature, class), with `expected_value` [0.91769, 0.06027, -0.82078]. Explainer values are **correct**: additivity error ≤ 1.4e-6, and they are **identical** (max diff 0.0) to xgboost's own `pred_contribs`. `scorer.py:67` assumes the old list-per-class format and indexes `shap_vals[pred_class][0]`. **pred_class 0:** picks sample 0, then feature 0 → the 3 per-class values of `event_category_encoded`, all 0.0. `zip` with `FEATURE_COLUMNS` (scorer.py:70) truncates to 3 → `{event_category_encoded: 0, geometry_type_encoded: 0, source_count: 0}`. That is the exact stored dict: the three names are mislabelled, and the values belong to a single feature across classes. **pred_class 1 or 2:** `IndexError: index N is out of bounds for axis 0 with size 1`, caught at scorer.py:73-75 and stored as `{}`, with only a stdout `print` (4 occurrences in this run). The correct top contributor for this LOW vector is `persons_affected` (+3.39), which is absent from the stored output. The version that would have produced the list format was not tested (no older shap installed). |

## Tier 2 summary

| Finding | Tier 2 status |
|---|---|
| F1 synthetic training | confirmed (artifact consistent with the synthetic generator) |
| F2 all-LOW | confirmed and reproduced exactly; mechanism refined to imputed `persons_affected` plus label leakage |
| F3 SHAP | confirmed; failure point is `scorer.py:67-70` indexing, not the explainer or input preparation |
| F14 version coupling | loads cleanly with recorded versions; other versions untested (inconclusive) |
| F17 test coverage | `test_scorer` passes without detecting F3 |

## Remaining uncertainties
- Whether a different, unpinned shap, xgboost, or sklearn version (e.g. what a fresh Render build resolves) loads the artifacts and gives the same outputs.
- Which shap version, if any, produced the list format the code expects.
- Whether live inputs at the time matched the reconstruction (month and hemisphere approximations).
- How severity would behave on real article text where `persons_affected` or `casualties` are extracted. The Tier 3 scraper and NLP work would bear on this.

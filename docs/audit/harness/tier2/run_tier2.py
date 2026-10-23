"""Tier 2: load the committed artifacts through the application's own code, evaluate inputs, diagnose SHAP.

Offline, no credentials, cwd = disposable copy root (scorer.py uses repo-relative MODEL_PATH).
Only google.genai and dotenv are stubbed (needed solely because test_scorer imports gemini.py).
No database is written: the copied DB is opened read-only.
"""
import ast, contextlib, io, json, os, sqlite3, sys, types, warnings

SCRATCH = os.environ["P1_SCRATCH"]
COPY = os.path.join(SCRATCH, "t2", "copy")
COPY_DB = os.path.join(COPY, "backend/data/disaster_intel.db")
assert os.getcwd() == COPY

real_connect = sqlite3.connect
def ro_only(db, *a, **k):
    s = str(db)
    assert s.startswith("file:") and "mode=ro" in s, f"non-read-only sqlite connect refused: {s}"
    return real_connect(db, *a, **k)
sqlite3.connect = ro_only

import numpy as np, pandas as pd, sklearn, xgboost as xgb, shap, joblib, scipy

OUT = {"versions": {"python": sys.version.split()[0], "numpy": np.__version__, "pandas": pd.__version__,
                    "scikit-learn": sklearn.__version__, "xgboost": xgb.__version__, "shap": shap.__version__,
                    "joblib": joblib.__version__, "scipy": scipy.__version__}}

# ---------------- 1. Load through the application's code path ----------------
from backend.app.pipeline import scorer
with warnings.catch_warnings(record=True) as w:
    warnings.simplefilter("always")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        scorer.load_models()
OUT["load"] = {
    "printed_errors": buf.getvalue().strip() or None,
    "warnings": [f"{x.category.__name__}: {str(x.message)[:300]}" for x in w],
    "model_type": type(scorer.model).__name__, "imputer_type": type(scorer.imputer).__name__,
    "explainer_type": type(scorer.explainer).__name__,
}
model, imputer, explainer = scorer.model, scorer.imputer, scorer.explainer
booster = model.get_booster()
cfg = json.loads(booster.save_config())
OUT["model"] = {
    "classes_": model.classes_.tolist(), "n_classes_": int(model.n_classes_),
    "n_features_in_": int(model.n_features_in_),
    "booster_feature_names": booster.feature_names,
    "num_boosted_rounds": booster.num_boosted_rounds(),
    "objective": cfg["learner"]["objective"]["name"],
    "xgboost_version_in_config": cfg.get("version"),
    "params": {k: model.get_params()[k] for k in ("n_estimators", "max_depth", "learning_rate", "random_state", "missing")},
}
OUT["imputer"] = {
    "strategy": imputer.strategy, "sklearn_version_in_pickle": getattr(imputer, "_sklearn_version", None),
    "feature_names_in_": imputer.feature_names_in_.tolist(),
    "statistics_": [round(float(v), 4) for v in imputer.statistics_],
    "feature_order_matches_scorer": imputer.feature_names_in_.tolist() == scorer.FEATURE_COLUMNS,
}
static = [2.0, 1.0, 3.0, 14.6245, 2.286, 7555.0, 801.4125, 84.5355, 34.8603, 2.0, 1.0, 399.5232, 0.0, 3.0, 2.0, 6.0, 1.0]
OUT["imputer"]["matches_static_decode"] = bool(np.allclose(np.round(imputer.statistics_, 4), static))

# Provenance cross-check: medians of the synthetic training generator (code only, no training)
src = open("backend/scripts/train_model.py").read()
keep = [n for n in ast.parse(src).body if (isinstance(n, ast.Assign) and n.targets[0].id in
        ("FEATURE_COLUMNS", "CATEGORY_ENCODING", "LABEL_ENCODING")) or
        (isinstance(n, ast.FunctionDef) and n.name == "fetch_historical_data")]
ns = {"np": np, "pd": pd}
exec(compile(ast.Module(body=keep, type_ignores=[]), "train_model_extract", "exec"), ns)
with contextlib.redirect_stdout(io.StringIO()):
    train = ns["fetch_historical_data"]()
gen_medians = train[ns["FEATURE_COLUMNS"]].median().values
OUT["imputer"]["equals_synthetic_generator_medians"] = bool(np.allclose(gen_medians, imputer.statistics_))
OUT["imputer"]["max_abs_diff_vs_generator"] = float(np.max(np.abs(gen_medians - imputer.statistics_)))

# Fidelity on the synthetic data the script would split for testing (prediction only)
X = train[ns["FEATURE_COLUMNS"]]
Xi = pd.DataFrame(imputer.transform(X), columns=ns["FEATURE_COLUMNS"])
pred = model.predict(Xi)
OUT["model"]["accuracy_on_regenerated_synthetic_rows"] = float((pred == train["label"].values).mean())

# ---------------- 2. Existing test_scorer model tests (run separately via pytest) ----------------
# see run log; quota test is deselected because it writes a database.

# ---------------- 3. Reconstructed vectors from the copied DB ----------------
conn = sqlite3.connect(f"file:{COPY_DB}?mode=ro", uri=True); conn.row_factory = sqlite3.Row
recs = conn.execute("SELECT e.*, a.ner_entities, a.regex_signals, a.severity_label AS stored_label, "
                    "a.severity_score AS stored_score, a.shap_values AS stored_shap "
                    "FROM events e JOIN event_analysis a ON a.event_id = e.id ORDER BY e.id").fetchall()
conn.close()

def reconstruct(r):
    """Mirror orchestrator.py:64-77 using stored DB fields. RECONSTRUCTED, not captured from a pipeline run.
    Known approximations: month from stored last_updated (= geometry[0].date per orchestrator.py:38);
    hemisphere from stored lat (= geometry[0] latitude); gdacs -1 because gdacs_enrichment is empty."""
    ents = json.loads(r["ner_entities"])
    f = {
        "event_category_encoded": ns["CATEGORY_ENCODING"].get(r["category"], 0),
        "geometry_type_encoded": 1 if r["geometry_type"] == "Polygon" else 0,
        "source_count": r["source_count"],
        "event_duration_days": 0.0,
        "gdacs_alert_score": -1.0,
        "gdacs_population_exposure": -1,
        "ner_location_count": len([e for e in ents if e[1] in ("GPE", "LOC")]),
        "ner_org_count": len([e for e in ents if e[1] == "ORG"]),
        "month": int(r["last_updated"][5:7]),
        "hemisphere": 0 if r["lat"] > 0 else 1,
    }
    f.update(json.loads(r["regex_signals"]))  # same as features.update(nlp_results["signals"])
    return f

def trace(features):
    """Step through score_event's own preparation, then call the real score_event and compare."""
    df = pd.DataFrame([features])
    for col in scorer.FEATURE_COLUMNS:
        if col not in df.columns:
            df[col] = np.nan
    dropped = [c for c in df.columns if c not in scorer.FEATURE_COLUMNS]
    df = df[scorer.FEATURE_COLUMNS]
    Xi = pd.DataFrame(imputer.transform(df), columns=scorer.FEATURE_COLUMNS)
    probs = model.predict_proba(Xi)[0]
    margin = booster.predict(xgb.DMatrix(Xi), output_margin=True)[0]
    res = scorer.score_event(dict(features))
    return {
        "dropped_extra_keys": dropped,
        "input_dtypes": {c: str(t) for c, t in df.dtypes.items() if str(t) != "float64"},
        "nan_before_impute": [c for c in df.columns if pd.isna(df[c].iloc[0])],
        "imputed_vector": {c: round(float(v), 4) for c, v in Xi.iloc[0].items()},
        "nonfinite_after_impute": int((~np.isfinite(Xi.values)).sum()),
        "raw_margins": [round(float(m), 5) for m in margin],
        "probabilities": [round(float(p), 6) for p in probs],
        "argmax": int(np.argmax(probs)),
        "score_event_result": res,
    }

vecs = [reconstruct(r) for r in recs]
keys = [json.dumps(v, sort_keys=True) for v in vecs]
distinct = sorted(set(keys))
traces = []
for k in distinct:
    t = trace(json.loads(k))
    t["n_events_with_this_vector"] = keys.count(k)
    traces.append(t)
results = [trace(v)["score_event_result"] for v in vecs]
OUT["reconstructed"] = {
    "label": "RECONSTRUCTED from copied DB fields (not captured from a pipeline execution)",
    "n_events": len(vecs), "n_distinct_vectors": len(distinct),
    "distinct_vector_traces": traces,
    "reproduced_labels": {l: sum(1 for r in results if r["severity_label"] == l) for l in {r["severity_label"] for r in results}},
    "reproduced_scores": sorted({round(r["severity_score"], 4) for r in results}),
    "stored_labels": {l: sum(1 for r in recs if r["stored_label"] == l) for l in {r["stored_label"] for r in recs}},
    "stored_scores": sorted({round(r["stored_score"], 4) for r in recs}),
    "per_event_label_match": sum(1 for r, x in zip(recs, results) if r["stored_label"] == x["severity_label"]),
    "per_event_score_match_4dp": sum(1 for r, x in zip(recs, results) if round(r["stored_score"], 4) == round(x["severity_score"], 4)),
    "per_event_shap_match": sum(1 for r, x in zip(recs, results) if json.loads(r["stored_shap"]) == x["shap_values"]),
}

# ---------------- 3b. Sensitivity (within the model; not a claim about true severity) ----------------
base = vecs[0]
med = dict(zip(scorer.FEATURE_COLUMNS, imputer.statistics_))
variants = {
    "baseline_reconstructed": {},
    "gdacs_missing_as_NaN": {"gdacs_alert_score": np.nan, "gdacs_population_exposure": np.nan},
    "gdacs_score_2.5_pop_50000": {"gdacs_alert_score": 2.5, "gdacs_population_exposure": 50000},
    "gdacs_score_5_pop_500000": {"gdacs_alert_score": 5.0, "gdacs_population_exposure": 500000},
    "source_count_3": {"source_count": 3},
    "source_count_6": {"source_count": 6},
    "duration_7_days": {"event_duration_days": 7.0},
    "ner_location_2": {"ner_location_count": 2},
    "persons_affected_3000": {"persons_affected": 3000},
    "all_NaN_except_category": {c: np.nan for c in scorer.FEATURE_COLUMNS if c != "event_category_encoded"},
    "combined_in_range_moderate_like": {"gdacs_alert_score": 3.0, "gdacs_population_exposure": 200000, "source_count": 4,
                                        "event_duration_days": 7.0, "ner_location_count": 2, "persons_affected": 3000},
}
sens = {}
for name, ch in variants.items():
    f = dict(base); f.update(ch)
    t = trace(f)
    sens[name] = {"probabilities": t["probabilities"], "label": t["score_event_result"]["severity_label"],
                  "score": round(t["score_event_result"]["severity_score"], 4)}
OUT["sensitivity_on_reconstructed_vector"] = sens

# ---------------- 4. SHAP diagnosis ----------------
def shap_diag(features, tag):
    df = pd.DataFrame([features])
    for c in scorer.FEATURE_COLUMNS:
        if c not in df.columns:
            df[c] = np.nan
    Xi = pd.DataFrame(imputer.transform(df[scorer.FEATURE_COLUMNS]), columns=scorer.FEATURE_COLUMNS)
    probs = model.predict_proba(Xi)[0]; pc = int(np.argmax(probs))
    sv = explainer.shap_values(Xi)
    arr = np.asarray(sv) if not isinstance(sv, list) else None
    d = {"tag": tag, "pred_class": pc,
         "raw_type": type(sv).__name__,
         "raw_shape": list(arr.shape) if arr is not None else [list(np.asarray(x).shape) for x in sv],
         "expected_value": [round(float(v), 5) for v in np.atleast_1d(explainer.expected_value)]}
    # What scorer.py:67 does
    try:
        sel = sv[pc][0]
        d["scorer_indexing_sv[pred_class][0]_shape"] = list(np.shape(sel))
        d["scorer_indexing_values"] = [round(float(v), 6) for v in np.atleast_1d(sel)]
        d["scorer_zip_result"] = dict(zip(scorer.FEATURE_COLUMNS, [float(v) for v in np.atleast_1d(sel)]))
    except Exception as e:
        d["scorer_indexing_error"] = f"{type(e).__name__}: {e}"
    if arr is not None and arr.ndim == 3:
        per_class = arr[0, :, pc]
        d["correct_values_for_pred_class_top5"] = dict(sorted(
            {c: round(float(v), 5) for c, v in zip(scorer.FEATURE_COLUMNS, per_class)}.items(),
            key=lambda x: -abs(x[1]))[:5])
        d["feature0_across_classes"] = [round(float(v), 6) for v in arr[0, 0, :]]
        margin = booster.predict(xgb.DMatrix(Xi), output_margin=True)[0]
        d["additivity_max_err"] = float(np.max(np.abs(arr[0].sum(axis=0) + np.atleast_1d(explainer.expected_value) - margin)))
        contribs = booster.predict(xgb.DMatrix(Xi), pred_contribs=True)  # xgboost's own TreeSHAP
        contribs = np.asarray(contribs)
        d["xgboost_pred_contribs_shape"] = list(contribs.shape)
        d["max_abs_diff_shap_vs_xgboost_contribs"] = float(np.max(np.abs(contribs[0, :, :-1].T - arr[0]))) if contribs.ndim == 3 else None
    d["score_event_shap_values"] = scorer.score_event(dict(features))["shap_values"]
    return d

shap_cases = [shap_diag(vecs[0], "reconstructed_event_0 (LOW)")]
for cls in (1, 2):
    row = train[train["label"] == cls].iloc[0][ns["FEATURE_COLUMNS"]].to_dict()
    shap_cases.append(shap_diag(row, f"synthetic_training_row_label_{cls}"))
OUT["shap"] = shap_cases

print(json.dumps(OUT, indent=1, default=str))

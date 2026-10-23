import ast
import asyncio
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import traceback
from datetime import date

import stubs
stubs.install()

SCRATCH = os.environ["P1_SCRATCH"]
COPY = os.path.join(SCRATCH, "copy")
WORK = os.path.join(SCRATCH, "work")
COPY_DB = os.path.join(COPY, "backend/data/disaster_intel.db")
os.makedirs(WORK, exist_ok=True)

from backend.app.db import database
from backend.app.pipeline import orchestrator, ingest, scraper, gemini
from backend.app.api import routes

RESULTS = {}


def fresh_db(name, from_copy=False):
    path = os.path.join(WORK, name + ".db")
    if os.path.exists(path):
        os.remove(path)
    if from_copy:
        shutil.copyfile(COPY_DB, path)
    database.DB_PATH = path
    assert os.path.realpath(database.DB_PATH).startswith(os.path.realpath(SCRATCH) + os.sep)
    database.execute_schema()
    return path


def rows(sql, args=()):
    conn = database.get_db()
    out = [dict(r) for r in conn.execute(sql, args).fetchall()]
    conn.close()
    return out


def event(eid, dates, gtype="Point", closed=None, desc="desc", cat="Wildfires", lat=32.0, lon=-110.0):
    coords = [lon, lat] if gtype == "Point" else [[[lon, lat], [lon + 1, lat], [lon, lat + 1], [lon, lat]]]
    return {
        "id": eid, "title": f"Event {eid}", "description": desc, "closed": closed,
        "categories": [{"id": "x", "title": cat}],
        "sources": [{"id": "S", "url": "https://example.invalid/x"}],
        "geometry": [{"date": d, "type": gtype, "coordinates": coords} for d in dates],
    }


class Fakes:
    """Patches the expensive or external stages in the orchestrator namespace."""

    def __init__(self, feed, label="LOW", keyphrases=(("alpha", 0.9),), score_raises_on=None, scrape_delay=0.0):
        self.feed, self.label, self.keyphrases = feed, label, list(keyphrases)
        self.score_raises_on, self.scrape_delay = score_raises_on, scrape_delay
        self.scored = []

    def apply(self):
        async def run_ingestion():
            return [{"eonet": e, "gdacs": None} for e in self.feed]

        async def scrape(e):
            await asyncio.sleep(self.scrape_delay)
            return {"text": "canned text " + e["id"], "source": "fake"}

        def nlp(text):
            return {"entities": [], "signals": {"acres_burned": None}, "keyphrases": self.keyphrases}

        def score(features):
            self.scored.append(features)
            if self.score_raises_on is not None and len(self.scored) == self.score_raises_on:
                raise ValueError("forced scorer failure")
            return {"severity_label": self.label, "severity_score": 0.9, "shap_values": {}}

        orchestrator.run_ingestion = run_ingestion
        orchestrator.scrape_event_sources = scrape
        orchestrator.run_nlp_pipeline = nlp
        orchestrator.get_embeddings = lambda t: [0.0, 1.0]
        orchestrator.score_event = score
        return self


def run(coro):
    return asyncio.run(coro)


def test(name):
    def deco(fn):
        try:
            RESULTS[name] = {"ok": True, **fn()}
        except Exception as e:
            RESULTS[name] = {"ok": False, "harness_error": repr(e), "tb": traceback.format_exc()[-1500:]}
        return fn
    return deco


T1, T2, T3 = "2026-04-01T00:00:00Z", "2026-04-05T00:00:00Z", "2026-04-09T00:00:00Z"


@test("T1_geometry_order_and_update_detection")
def _():
    fresh_db("t1")
    f = Fakes([event("E1", [T1, T2])]).apply()
    run(orchestrator.run_pipeline())
    r1 = rows("SELECT e.first_seen, e.last_updated, a.analysed_at FROM events e JOIN event_analysis a ON a.event_id=e.id")[0]
    f.feed = [event("E1", [T1, T2, T3])]  # EONET appends a newer observation
    run(orchestrator.run_pipeline())
    r2 = rows("SELECT e.first_seen, e.last_updated, a.analysed_at FROM events e JOIN event_analysis a ON a.event_id=e.id")[0]
    return {
        "input_geometry_dates_ascending": [T1, T2],
        "after_run1": r1,
        "after_run2_with_newer_point_appended": r2,
        "times_scored": len(f.scored),
        "first_seen_is_newest": r1["first_seen"] == T2,
        "last_updated_is_oldest": r1["last_updated"] == T1,
        "update_skipped": r1["analysed_at"] == r2["analysed_at"] and len(f.scored) == 1,
    }


@test("T2_closure_and_seeding")
def _():
    fresh_db("t2")
    f = Fakes([event("E2", [T1])]).apply()
    run(orchestrator.run_pipeline())
    s1 = rows("SELECT status FROM events")[0]["status"]
    f.feed = []  # event no longer in the open feed
    run(orchestrator.run_pipeline())
    s2 = rows("SELECT status FROM events")[0]["status"]
    f.feed = [event("E2", [T1], closed="2026-04-10T00:00:00Z")]  # closed, same geometry
    run(orchestrator.run_pipeline())
    s3a = rows("SELECT status FROM events")[0]["status"]
    f.feed = [event("E2", [T2], closed="2026-04-10T00:00:00Z")]  # closed, geometry changed so it is reprocessed
    run(orchestrator.run_pipeline())
    s3b = rows("SELECT status FROM events")[0]["status"]
    listed = [e["id"] for e in run(routes.get_events())["events"]]

    # seed_db: fetches closed events, then only calls run_pipeline()
    fresh_db("t2_seed")
    from backend.scripts import seed_db
    calls = {"run_pipeline": 0}

    async def fake_closed(days=90):
        return [event(f"C{i}", [T1], closed=T2) for i in range(3)]

    async def fake_run_pipeline():
        calls["run_pipeline"] += 1
        return True

    seed_db.fetch_closed_events = fake_closed
    seed_db.get_gdacs_events = lambda: []
    seed_db.run_pipeline = fake_run_pipeline
    orchestrator.run_pipeline = fake_run_pipeline  # seed() re-imports it from the orchestrator
    run(seed_db.seed())
    seeded = rows("SELECT COUNT(*) AS n FROM events")[0]["n"]
    return {
        "status_open_run": s1, "status_after_absent_from_feed": s2,
        "status_after_closed_same_geometry": s3a, "status_after_closed_changed_geometry": s3b,
        "still_listed_by_/api/events": "E2" in listed,
        "seed_closed_events_fetched": 3, "seed_closed_events_saved": seeded,
        "seed_run_pipeline_calls": calls["run_pipeline"],
    }


def reload_orchestrator():
    import importlib
    importlib.reload(orchestrator)


@test("T3_null_digest_and_has_digest")
def _():
    reload_orchestrator()
    fresh_db("t3")
    Fakes([event("E3", [T1])], label="LOW").apply()
    run(orchestrator.run_pipeline())
    raw = rows("SELECT gemini_digest, typeof(gemini_digest) AS t FROM event_analysis")[0]
    listing = run(routes.get_events())["events"][0]
    detail = run(routes.get_event_detail("E3"))
    return {
        "raw_gemini_digest": raw["gemini_digest"], "sqlite_type": raw["t"],
        "has_digest_in_/api/events": listing["has_digest"],
        "detail_gemini_digest": detail["gemini_digest"],
        "verify_pipeline_query_count": rows("SELECT COUNT(*) AS n FROM event_analysis WHERE gemini_digest IS NOT NULL")[0]["n"],
    }


@test("T4_abort_semantics_and_matching_fragility")
def _():
    out = {}
    for variant, feed, raises in [
        ("polygon_second", [event("A", [T1]), event("B", [T1], gtype="Polygon"), event("C", [T1])], None),
        ("scorer_raises_on_second", [event("A", [T1]), event("B", [T1]), event("C", [T1])], 2),
    ]:
        reload_orchestrator()
        fresh_db("t4_" + variant)
        Fakes(feed, score_raises_on=raises).apply()
        ok = run(orchestrator.run_pipeline())
        out[variant] = {
            "run_pipeline_returned": ok,
            "events_saved": [r["id"] for r in rows("SELECT id FROM events ORDER BY id")],
            "health": run(routes.health()),
        }

    poly = event("P", [T1], gtype="Polygon")
    gd_point = {"properties": {"eventtype": "WF", "fromdate": "2026-04-01T00:00:00Z"},
                "geometry": {"coordinates": [-110.0, 32.0]}}
    try:
        ingest.match_events(poly, [gd_point])
        out["match_polygon_eonet"] = "no error"
    except Exception as e:
        out["match_polygon_eonet"] = repr(e)

    pt = event("Q", [T1])
    gd_naive = {"properties": {"eventtype": "WF", "fromdate": "2026-04-01T00:00:00"},
                "geometry": {"coordinates": [-110.1, 32.1]}}
    try:
        out["match_naive_gdacs_date"] = "returned " + str(ingest.match_events(pt, [gd_naive]) is gd_naive)
    except Exception as e:
        out["match_naive_gdacs_date"] = repr(e)
    gd_aware = dict(gd_naive, properties={"eventtype": "WF", "fromdate": "2026-04-01T00:00:00Z"})
    out["match_aware_gdacs_date_matches"] = ingest.match_events(pt, [gd_aware]) is gd_aware
    return out


@test("T5_stale_nlp_summary")
def _():
    reload_orchestrator()
    fresh_db("t5")
    f = Fakes([event("E5", [T1])], keyphrases=[("alpha", 0.9), ("bravo", 0.8)]).apply()
    run(orchestrator.run_pipeline())
    a = rows("SELECT keyphrases, nlp_summary FROM event_analysis")[0]
    f.keyphrases = [("zulu", 0.9), ("yankee", 0.8)]
    f.feed = [event("E5", [T2])]  # geometry[0] changed so it is reprocessed
    run(orchestrator.run_pipeline())
    b = rows("SELECT keyphrases, nlp_summary FROM event_analysis")[0]
    return {"run1": a, "run2": b, "nlp_summary_stale": a["nlp_summary"] == b["nlp_summary"] and a["keyphrases"] != b["keyphrases"]}


@test("T6_fallback_text_with_null_description")
def _():
    r = run(scraper.scrape_event_sources({"title": "Super Typhoon X", "description": None, "sources": []}))
    return {"result": r, "contains_literal_None": r["text"].endswith("None")}


class FakeGemini:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), 0
        self.models = self

    def generate_content(self, model, contents):
        self.calls += 1
        r = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(r, Exception):
            raise r
        return type("R", (), {"text": r})()


def quota_count():
    r = rows("SELECT call_count FROM gemini_calls WHERE call_date = ?", (date.today().isoformat(),))
    return r[0]["call_count"] if r else 0


DATA = {"title": "T", "category": "Wildfires", "severity_label": "HIGH", "severity_score": 0.9, "raw_text": "x"}


@test("T7_quota_accounting")
def _():
    fresh_db("t7")
    fake = FakeGemini(["not json", RuntimeError("API 500"), '{"what_happened": "a"}'])
    gemini.client = fake
    seq = []
    for _ in range(3):
        res = run(gemini.generate_digest(DATA))
        seq.append({"returned": res, "api_calls_so_far": fake.calls, "quota_counter": quota_count()})

    fresh_db("t7_race")
    conn = database.get_db()
    conn.execute("INSERT INTO gemini_calls VALUES (?, 79)", (date.today().isoformat(),))
    conn.commit(); conn.close()
    fake2 = FakeGemini(['{"what_happened": "a"}'])
    gemini.client = fake2

    async def two():
        return await asyncio.gather(gemini.generate_digest(DATA), gemini.generate_digest(DATA))
    res = run(two())
    gemini.client = None
    return {"sequence": seq, "race_at_79": {"api_calls": fake2.calls, "final_counter": quota_count(),
                                             "results_none": [r is None for r in res]}}


@test("T8_concurrent_pipeline_runs")
def _():
    reload_orchestrator()
    fresh_db("t8")
    Fakes([event("E8", [T1])], label="MODERATE", scrape_delay=0.05).apply()
    fake = FakeGemini(['{"what_happened": "a"}'])
    gemini.client = fake

    async def two():
        return await asyncio.gather(orchestrator.run_pipeline(), orchestrator.run_pipeline())
    res = run(two())
    gemini.client = None
    return {"run_results": res, "gemini_calls_for_one_event": fake.calls,
            "quota_counter": quota_count(), "events_rows": rows("SELECT COUNT(*) AS n FROM events")[0]["n"]}


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


@test("T9_existing_tests")
def _():
    out = {}
    from backend.tests import test_ingest
    for fn in ("test_haversine", "test_match_events"):
        try:
            getattr(test_ingest, fn)()
            out[fn] = "passed"
        except Exception as e:
            out[fn] = "FAILED: " + repr(e)

    # test_gemini_quota_guard against a copy of the committed DB, with a quota row present for today
    path = fresh_db("t9_quota", from_copy=True)
    conn = database.get_db()
    conn.execute("INSERT INTO gemini_calls VALUES (?, 37)", (date.today().isoformat(),))
    conn.commit(); conn.close()
    before = sha(path)
    from backend.tests import test_scorer
    try:
        test_scorer.test_gemini_quota_guard()
        out["test_gemini_quota_guard"] = "passed"
    except Exception as e:
        out["test_gemini_quota_guard"] = "FAILED: " + repr(e)
    out["db_file_changed"] = sha(path) != before
    out["todays_quota_row_before"] = 37
    out["todays_quota_row_after"] = quota_count()
    out["db_path_used_by_test"] = "redirected temp copy (test itself uses whatever DB_PATH points at; default is the committed DB)"
    return out


def load_training_generator():
    src = open(os.path.join(COPY, "backend/scripts/train_model.py")).read()
    tree = ast.parse(src)
    keep = [n for n in tree.body if (isinstance(n, ast.Assign) and n.targets[0].id in
            ("FEATURE_COLUMNS", "CATEGORY_ENCODING", "LABEL_ENCODING")) or
            (isinstance(n, ast.FunctionDef) and n.name == "fetch_historical_data")]
    import numpy as np
    import pandas as pd
    ns = {"np": np, "pd": pd}
    exec(compile(ast.Module(body=keep, type_ignores=[]), "train_model_extract", "exec"), ns)
    return ns


@test("T10_training_vs_inference_features")
def _():
    import numpy as np
    import pandas as pd
    ns = load_training_generator()
    import contextlib, io
    with contextlib.redirect_stdout(io.StringIO()):
        train = ns["fetch_historical_data"]()
    cols = ns["FEATURE_COLUMNS"]

    # Rebuild the vectors the orchestrator would have produced for the 100 stored events
    conn = sqlite3.connect(f"file:{COPY_DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    recs = conn.execute("SELECT e.*, a.ner_entities, a.regex_signals FROM events e JOIN event_analysis a ON a.event_id=e.id").fetchall()
    conn.close()
    inf = []
    for r in recs:
        ents = json.loads(r["ner_entities"]); sig = json.loads(r["regex_signals"])
        v = {
            "event_category_encoded": ns["CATEGORY_ENCODING"].get(r["category"], 0),
            "geometry_type_encoded": 1 if r["geometry_type"] == "Polygon" else 0,
            "source_count": r["source_count"], "event_duration_days": 0.0,
            "gdacs_alert_score": -1.0, "gdacs_population_exposure": -1,
            "ner_location_count": sum(1 for e in ents if e[1] in ("GPE", "LOC")),
            "ner_org_count": sum(1 for e in ents if e[1] == "ORG"),
            "month": int(r["last_updated"][5:7]), "hemisphere": 0 if r["lat"] > 0 else 1,
        }
        v.update({k: sig.get(k) for k in ("acres_burned", "pct_contained", "wind_speed_mph", "storm_category",
                                           "persons_affected", "casualties")})
        inf.append(v)
    inf = pd.DataFrame(inf).reindex(columns=cols).astype(float)

    table = {}
    for c in cols:
        t = train[c].astype(float)
        i = inf[c]
        known = i.dropna()
        table[c] = {
            "train_min": round(float(t.min()), 2) if t.notna().any() else None,
            "train_max": round(float(t.max()), 2) if t.notna().any() else None,
            "train_nan_pct": round(100 * float(t.isna().mean()), 1),
            "inference_values": sorted(set(round(float(x), 2) for x in known))[:6],
            "inference_nan_pct": round(100 * float(i.isna().mean()), 1),
            "inference_outside_train_range_pct": round(100 * float(((known < t.min()) | (known > t.max())).mean()), 1) if len(known) and t.notna().any() else None,
        }
    label_by_source1 = train[train["source_count"] == 1]["label"].value_counts().to_dict()
    label_by_low_gdacs = train[train["gdacs_alert_score"] < 2]["label"].value_counts().to_dict()
    return {"n_training_rows": len(train), "training_label_counts": train["label"].value_counts().to_dict(),
            "features": table,
            "training_labels_when_source_count_eq_1": label_by_source1,
            "training_labels_when_gdacs_score_lt_2": label_by_low_gdacs,
            "note": "0=GREEN->LOW, 1=ORANGE->MODERATE, 2=RED->HIGH"}


@test("T11_committed_db_evidence")
def _():
    conn = sqlite3.connect(f"file:{COPY_DB}?mode=ro", uri=True)
    q = lambda s: conn.execute(s).fetchall()
    out = {
        "events": q("SELECT COUNT(*) FROM events")[0][0],
        "status": q("SELECT status, COUNT(*) FROM events GROUP BY status"),
        "severity": q("SELECT severity_label, COUNT(*), ROUND(MIN(severity_score),4), ROUND(MAX(severity_score),4) FROM event_analysis GROUP BY 1"),
        "distinct_shap_values": q("SELECT shap_values, COUNT(*) FROM event_analysis GROUP BY 1"),
        "gemini_digest": q("SELECT gemini_digest, COUNT(*) FROM event_analysis GROUP BY 1"),
        "raw_text_top": q("SELECT raw_text, COUNT(*) FROM event_analysis GROUP BY 1 ORDER BY 2 DESC LIMIT 2"),
        "gdacs_rows": q("SELECT COUNT(*) FROM gdacs_enrichment")[0][0],
        "first_seen_after_last_updated": q("SELECT id, first_seen, last_updated FROM events WHERE first_seen > last_updated"),
        "last_updated_range": q("SELECT MIN(last_updated), MAX(last_updated) FROM events")[0],
    }
    conn.close()
    return out


print(json.dumps(RESULTS, indent=1, default=str))

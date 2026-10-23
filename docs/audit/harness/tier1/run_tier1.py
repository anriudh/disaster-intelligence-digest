"""Tier 1 checks: real trafilatura, real FastAPI/slowapi/httpx. Offline, no credentials.

Only modules not installed in Tier 1 (NLP models, ML, joblib) are stubbed; anything that would
load a model or unpickle raises.
"""
import asyncio
import json
import os
import shutil
import sqlite3
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

SCRATCH = os.environ["P1_SCRATCH"]
COPY = os.path.join(SCRATCH, "t1", "copy")
WORK = os.path.join(SCRATCH, "t1", "work")
os.makedirs(WORK, exist_ok=True)


def blocked(what):
    def f(*a, **k):
        raise RuntimeError(f"{what} blocked in Tier 1")
    return f


for name, attrs in {
    "spacy": {"load": blocked("spacy.load")},
    "keybert": {"KeyBERT": blocked("KeyBERT")},
    "sentence_transformers": {"SentenceTransformer": blocked("SentenceTransformer")},
    "joblib": {"load": blocked("joblib.load"), "dump": blocked("joblib.dump")},
    "shap": {"TreeExplainer": blocked("shap")},
}.items():
    m = types.ModuleType(name); m.__dict__.update(attrs); sys.modules[name] = m

real_connect = sqlite3.connect
def guarded(db, *a, **k):
    p = str(db)
    p = p[5:].split("?")[0] if p.startswith("file:") else p
    assert os.path.realpath(p).startswith(os.path.realpath(SCRATCH) + os.sep), f"refused {p}"
    return real_connect(db, *a, **k)
sqlite3.connect = guarded

import trafilatura
import httpx
from backend.app.db import database
from backend.app.pipeline import scraper

R = {}

# ---------- F4: real trafilatura on fixtures ----------
SPA = """<!doctype html><html lang="en"><head><meta charset="utf-8"><title>InciWeb</title>
<script defer src="/static/js/main.js"></script></head>
<body><noscript>You need to enable JavaScript to run this app.</noscript><div id="root"></div></body></html>"""
ARTICLE = "<html><head><title>Fire update</title></head><body><article><h1>Sawmill Fire</h1>" + "".join(
    f"<p>Paragraph {i}: the fire has burned 5,000 acres near Flagstaff, Arizona and is 30% contained. "
    f"Crews from the Arizona State Forestry continue suppression work today.</p>" for i in range(6)) + "</article></body></html>"
EMPTY = "<html><body></body></html>"

R["F4_trafilatura_extract_direct"] = {k: trafilatura.extract(v) for k, v in
                                      {"spa_shell": SPA, "article": ARTICLE, "empty": EMPTY}.items()}
R["F4_trafilatura_extract_direct"]["article"] = (R["F4_trafilatura_extract_direct"]["article"] or "")[:120] + "..."


async def scrape_with(html):
    resp = MagicMock(); resp.text = html; resp.raise_for_status = MagicMock()
    with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=resp)), \
         patch("asyncio.sleep", new=AsyncMock()):
        ev = {"title": "Sawmill Fire", "description": None, "sources": [{"url": "https://inciweb.example/x"}]}
        return await scraper.scrape_event_sources(ev)

R["F4_scrape_event_sources"] = {k: asyncio.run(scrape_with(v)) for k, v in
                                {"spa_shell": SPA, "empty": EMPTY}.items()}
R["F4_trafilatura_version"] = trafilatura.__version__ if hasattr(trafilatura, "__version__") else "see freeze"

# ---------- API checks with the real FastAPI app ----------
db = os.path.join(WORK, "api.db")
shutil.copyfile(os.path.join(COPY, "backend/data/disaster_intel.db"), db)
database.DB_PATH = db

from backend.app import main  # real FastAPI, slowapi, apscheduler; startup NOT run (no lifespan)
from backend.app.api import routes


async def api_checks():
    out = {}
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        # F10a: rate limiter
        codes = {}
        for _ in range(100):
            r = await c.get("/api/events")
            codes[r.status_code] = codes.get(r.status_code, 0) + 1
        out["F10_rate_limit_100_GETs_status_counts"] = codes
        out["F10_routes_with_limit_decorators"] = [
            getattr(rt, "path", "?") for rt in main.app.routes
            if getattr(getattr(rt, "endpoint", None), "__name__", "") in getattr(main.limiter, "_route_limits", {})]
        out["F10_limiter_route_limits_registered"] = len(getattr(main.limiter, "_route_limits", {}))
        out["F10_limiter_default_limits"] = [str(x) for x in getattr(main.limiter, "_default_limits", [])]

        # F10b: unauthenticated trigger -> concurrent runs
        state = {"active": 0, "peak": 0, "started": 0}

        async def slow_pipeline():
            state["started"] += 1; state["active"] += 1
            state["peak"] = max(state["peak"], state["active"])
            await asyncio.sleep(0.3)
            state["active"] -= 1
            return True

        routes.run_pipeline = slow_pipeline
        r1 = await c.post("/api/pipeline/trigger")
        r2 = await c.post("/api/pipeline/trigger")
        await asyncio.sleep(0.1)
        out["F10_trigger_responses"] = [r1.status_code, r1.json(), r2.status_code]
        out["F10_trigger_peak_concurrent_runs"] = state["peak"]
        out["F10_trigger_runs_started"] = state["started"]
        await asyncio.sleep(0.4)

        # F7 impact through the real HTTP API on a copy of the committed DB
        ev = (await c.get("/api/events")).json()["events"]
        out["F7_api_events_total"] = len(ev)
        out["F7_api_has_digest_true"] = sum(1 for e in ev if e["has_digest"])
        d = await c.get(f"/api/events/{ev[0]['id']}")
        dj = d.json()
        out["F7_api_detail_gemini_digest"] = dj["gemini_digest"]
        out["F16_detail_payload_bytes"] = len(d.content)
        out["F16_detail_embedding_type"] = type(dj.get("embedding")).__name__
        out["F16_detail_embedding_chars"] = len(dj.get("embedding") or "")
        out["F9_health"] = (await c.get("/api/health")).json()
        out["missing_event_status"] = (await c.get("/api/events/NOPE")).status_code
    return out

R.update(asyncio.run(api_checks()))
print(json.dumps(R, indent=1, default=str))

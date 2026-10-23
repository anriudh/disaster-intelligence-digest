from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from backend.app.api import routes
from backend.app.api.routes import pipeline_status
from backend.app.db import database
from backend.app.db.database import get_db
from backend.app.pipeline import gemini, orchestrator
from backend.app.pipeline.ingest import match_events
from backend.tests.helpers import eonet_event, row

T0 = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


def run_row(status, finished=T0, started=None):
    started = started or finished - timedelta(minutes=2)
    return {"status": status, "started_at": started.isoformat(), "finished_at": finished.isoformat()}


# --- one bad event no longer aborts the run ---------------------------------

async def test_bad_event_is_isolated(pipeline, client):
    bad = eonet_event("EONET_BAD", geometry=[])  # no dated geometry: raises
    await pipeline.run(eonet_event("EONET_1"), bad, eonet_event("EONET_3"))

    assert row("events", "id", "EONET_1") is not None
    assert row("events", "id", "EONET_3") is not None
    assert row("events", "id", "EONET_BAD") is None

    run = row("pipeline_runs", "id", 1)
    assert (run["status"], run["processed"], run["skipped"], run["failed"]) == ("partial", 2, 0, 1)
    assert run["error_event_id"] == "EONET_BAD"
    assert "no dated geometry" in run["error_message"]

    health = client.get("/api/health").json()
    assert health["status"] == "degraded"
    assert health["last_error"]["event_id"] == "EONET_BAD"
    assert health["counts"] == {"processed": 2, "skipped": 0, "failed": 1}


async def test_successful_run_is_recorded_and_healthy(pipeline, client):
    await pipeline.run(eonet_event("EONET_1"))
    await pipeline.run(eonet_event("EONET_1"))
    second = row("pipeline_runs", "id", 2)
    assert (second["status"], second["processed"], second["skipped"]) == ("success", 0, 1)

    health = client.get("/api/health").json()
    assert health["status"] == "ok"
    assert health["last_run_status"] == "success"
    assert health["last_error"] is None
    assert health["last_successful_run"] == second["finished_at"]


async def test_whole_run_failure_is_recorded(pipeline, monkeypatch):
    async def broken():
        raise RuntimeError("EONET unreachable")

    monkeypatch.setattr(orchestrator, "run_ingestion", broken)
    assert await orchestrator.run_pipeline() is False
    run = row("pipeline_runs", "id", 1)
    assert run["status"] == "failed"
    assert "EONET unreachable" in run["error_message"]
    assert run["finished_at"] is not None


# --- health states (P-4) ------------------------------------------------------

def test_pending_before_first_run():
    assert pipeline_status(None, None, False, T0 + timedelta(minutes=24), T0)[0] == "pending"


def test_degraded_when_first_run_never_happens():
    assert pipeline_status(None, None, False, T0 + timedelta(minutes=26), T0)[0] == "degraded"


def test_pending_ignores_runs_from_a_previous_process():
    old = run_row("success", finished=T0 - timedelta(days=180))
    assert pipeline_status(old, old, False, T0 + timedelta(minutes=5), T0)[0] == "pending"
    # ...but once the pending window is over, six-month-old data is stale
    assert pipeline_status(old, old, False, T0 + timedelta(minutes=30), T0)[0] == "degraded"


def test_ok_within_45_minutes_then_stale():
    done = run_row("success", finished=T0)
    started = T0 - timedelta(hours=1)
    assert pipeline_status(done, done, True, T0 + timedelta(minutes=45), started)[0] == "ok"
    status, reason = pipeline_status(done, done, True, T0 + timedelta(minutes=46), started)
    assert status == "degraded" and "recently" in reason


def test_failed_or_partial_last_run_is_degraded():
    done = run_row("success", finished=T0 - timedelta(minutes=20))
    started = T0 - timedelta(hours=1)
    assert pipeline_status(run_row("failed"), done, True, T0, started) == ("degraded", "the last pipeline run failed")
    partial = run_row("partial")
    assert pipeline_status(partial, partial, True, T0, started)[0] == "degraded"
    # A failure during the pending window is reported, not hidden
    assert pipeline_status(run_row("failed"), None, False, T0 + timedelta(minutes=5), T0)[0] == "degraded"


def test_liveness_does_not_need_the_database(client, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", "/nonexistent/dir/db.sqlite")
    assert client.get("/api/health/live").json() == {"status": "alive"}
    response = client.get("/api/health")
    assert response.status_code == 503
    assert response.json()["status"] == "degraded"


def test_health_pending_on_a_fresh_process(client, monkeypatch):
    monkeypatch.setattr(routes, "PROCESS_STARTED_AT", datetime.now(timezone.utc))
    assert client.get("/api/health").json()["status"] == "pending"


# --- GDACS matching -------------------------------------------------------------

def gdacs(eventtype="WF", lat=32.1, lon=-110.1, fromdate="2024-06-01T10:00:00Z", geometry=None):
    return {"properties": {"eventtype": eventtype, "fromdate": fromdate, "eventid": 1},
            "geometry": geometry or {"type": "Point", "coordinates": [lon, lat]}}


def test_match_handles_naive_and_aware_dates():
    event = eonet_event(coords=[(-110.0, 32.0)])
    assert match_events(event, [gdacs(fromdate="2024-06-01T10:00:00")]) is not None
    assert match_events(event, [gdacs(fromdate="2024-06-01T10:00:00+02:00")]) is not None


def test_match_handles_polygons():
    ring = [[-110.2, 31.9], [-109.8, 31.9], [-109.8, 32.1], [-110.2, 32.1], [-110.2, 31.9]]
    event = eonet_event(geometry=[{"date": "2024-06-01T00:00:00Z", "type": "Polygon", "coordinates": [ring]}])
    match = gdacs(geometry={"type": "Polygon", "coordinates": [ring]})
    assert match_events(event, [match]) is match


def test_match_skips_malformed_gdacs_events():
    event = eonet_event(coords=[(-110.0, 32.0)])
    good = gdacs()
    bad = gdacs(fromdate="not a date")
    assert match_events(event, [bad, good]) is good


# --- quota counts every attempt -------------------------------------------------

async def test_every_gemini_attempt_counts(monkeypatch):
    replies = iter(["not json", RuntimeError("API error"), '{"what_happened": "fire"}'])

    def generate_content(model, contents):
        reply = next(replies)
        if isinstance(reply, Exception):
            raise reply
        return SimpleNamespace(text=reply)

    fake = SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))
    monkeypatch.setattr(gemini, "client", fake)

    results = [await gemini.generate_digest({"title": "Fire", "raw_text": "x"}) for _ in range(3)]
    assert results == [None, None, {"what_happened": "fire"}]
    count = row("gemini_calls", "call_date", date.today().isoformat())["call_count"]
    assert count == 3

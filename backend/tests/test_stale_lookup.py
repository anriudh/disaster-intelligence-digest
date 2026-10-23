import pytest

from backend.app.db.database import get_db
from backend.app.pipeline import ingest
from backend.tests.helpers import eonet_event, row


async def run_without(pipeline, runs, *present):
    """Completes `runs` pipeline runs whose feed holds only `present`."""
    for _ in range(runs):
        await pipeline.run(*present)


async def test_no_lookup_before_three_unseen_runs(pipeline):
    await pipeline.run(eonet_event("EONET_1"))
    await run_without(pipeline, 2)
    assert row("events", "id", "EONET_1")["unseen_runs"] == 2
    assert pipeline.lookups == []


async def test_closed_record_closes_stale_event(pipeline):
    await pipeline.run(eonet_event("EONET_1"))
    pipeline.records["EONET_1"] = eonet_event("EONET_1", closed="2024-06-20T00:00:00Z")
    await run_without(pipeline, 3)

    assert pipeline.lookups == ["EONET_1"]
    event = row("events", "id", "EONET_1")
    assert event["status"] == "closed"
    assert event["closed_at"] == "2024-06-20T00:00:00Z"
    assert event["closure_source"] == "eonet_lookup"

    await run_without(pipeline, 1)
    assert pipeline.lookups == ["EONET_1"]  # closed events are not looked up again


async def test_open_record_stays_open_and_not_observed(pipeline, client):
    await pipeline.run(eonet_event("EONET_1"))
    pipeline.records["EONET_1"] = eonet_event("EONET_1")
    await run_without(pipeline, 3)

    event = row("events", "id", "EONET_1")
    assert event["status"] == "open"
    assert event["observation_state"] == "not_observed"
    assert event["closed_at"] is None
    assert event["last_lookup_at"] is not None
    assert [e["id"] for e in client.get("/api/events").json()["events"]] == ["EONET_1"]


async def test_failed_lookup_leaves_event_unchanged(pipeline):
    await pipeline.run(eonet_event("EONET_1"))
    before = row("events", "id", "EONET_1")
    await run_without(pipeline, 3)  # no record: the lookup raises

    after = row("events", "id", "EONET_1")
    assert pipeline.lookups == ["EONET_1"]
    assert (after["status"], after["closed_at"], after["closure_source"]) == ("open", None, None)
    assert after["last_seen"] == before["last_seen"]
    conn = get_db()
    assert conn.execute("SELECT status FROM pipeline_runs ORDER BY id DESC").fetchone()[0] == "success"
    conn.close()


async def test_reappearing_resets_the_count(pipeline):
    await pipeline.run(eonet_event("EONET_1"))
    await run_without(pipeline, 2)
    await pipeline.run(eonet_event("EONET_1"))
    assert row("events", "id", "EONET_1")["unseen_runs"] == 0
    await run_without(pipeline, 2)
    assert pipeline.lookups == []


async def test_failed_runs_do_not_count(pipeline, monkeypatch):
    from backend.app.pipeline import orchestrator
    await pipeline.run(eonet_event("EONET_1"))

    async def broken_feed():
        raise RuntimeError("EONET unreachable")
    monkeypatch.setattr(orchestrator, "run_ingestion", broken_feed)
    for _ in range(3):
        assert await orchestrator.run_pipeline() is False
    assert row("events", "id", "EONET_1")["unseen_runs"] == 0
    assert pipeline.lookups == []


async def test_cap_per_run_rotates_and_deletes_nothing(pipeline, monkeypatch):
    monkeypatch.setenv("STALE_LOOKUP_LIMIT", "2")
    ids = [f"EONET_{i}" for i in range(5)]
    await pipeline.run(*(eonet_event(i) for i in ids))
    for i in ids:
        pipeline.records[i] = eonet_event(i)  # all still open at the source
    await run_without(pipeline, 3)
    assert len(pipeline.lookups) == 2

    await run_without(pipeline, 2)
    assert len(pipeline.lookups) == 6
    assert set(pipeline.lookups[:6]) == set(ids)  # least recently looked up first
    conn = get_db()
    assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 5
    conn.close()


async def test_limit_zero_disables_lookups(pipeline, monkeypatch):
    monkeypatch.setenv("STALE_LOOKUP_LIMIT", "0")
    await pipeline.run(eonet_event("EONET_1"))
    await run_without(pipeline, 4)
    assert pipeline.lookups == []


@pytest.mark.parametrize("value", ["", "five", "-3"])
def test_invalid_limit(monkeypatch, value):
    from backend.app.pipeline import orchestrator
    monkeypatch.setenv("STALE_LOOKUP_LIMIT", value)
    expected = 0 if value == "-3" else orchestrator.DEFAULT_STALE_LOOKUP_LIMIT
    assert orchestrator.stale_lookup_limit() == expected


async def test_fetch_eonet_event_rejects_other_id(monkeypatch):
    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"id": "EONET_2"}

    class Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            pass

        async def get(self, url):
            assert url.endswith("/api/v3/events/EONET_1")
            return Response()

    monkeypatch.setattr(ingest.httpx, "AsyncClient", Client)
    with pytest.raises(ValueError):
        await ingest.fetch_eonet_event("EONET_1")

import json
from datetime import datetime, timedelta, timezone

import pytest

from backend.app.db.database import get_db
from backend.tests.helpers import eonet_event, row


@pytest.mark.parametrize("dates", [
    ("2024-06-01T00:00:00Z", "2024-06-03T00:00:00Z", "2024-06-05T00:00:00Z"),  # ascending
    ("2024-06-05T00:00:00Z", "2024-06-03T00:00:00Z", "2024-06-01T00:00:00Z"),  # descending
])
async def test_dates_and_position_independent_of_order(pipeline, dates):
    coords = {"2024-06-01T00:00:00Z": (-110.0, 32.0), "2024-06-03T00:00:00Z": (-111.0, 33.0),
              "2024-06-05T00:00:00Z": (-112.0, 34.0)}
    await pipeline.run(eonet_event(dates=dates, coords=[coords[d] for d in dates], category="Severe Storms"))

    event = row("events", "id", "EONET_1")
    assert event["first_seen"] == "2024-06-01T00:00:00Z"
    assert event["last_updated"] == "2024-06-05T00:00:00Z"
    assert (event["lat"], event["lon"]) == (34.0, -112.0)  # the latest point
    assert pipeline.scored[0]["month"] == 6
    assert pipeline.scored[0]["event_duration_days"] == 4.0


async def test_new_point_triggers_reprocessing(pipeline):
    await pipeline.run(eonet_event(dates=("2024-06-01T00:00:00Z",)))
    await pipeline.run(eonet_event(dates=("2024-06-01T00:00:00Z",)))
    assert len(pipeline.scored) == 1  # unchanged feed is skipped

    await pipeline.run(eonet_event(dates=("2024-06-01T00:00:00Z", "2024-06-02T00:00:00Z")))
    assert len(pipeline.scored) == 2
    event = row("events", "id", "EONET_1")
    assert event["last_updated"] == "2024-06-02T00:00:00Z"
    assert event["first_seen"] == "2024-06-01T00:00:00Z"


async def test_title_and_status_update_on_reprocessing(pipeline):
    await pipeline.run(eonet_event(dates=("2024-06-01T00:00:00Z",)))
    await pipeline.run(eonet_event(dates=("2024-06-01T00:00:00Z", "2024-06-02T00:00:00Z"),
                                   title="Sawmill Fire (renamed)", closed="2024-06-02T12:00:00Z"))
    event = row("events", "id", "EONET_1")
    assert event["title"] == "Sawmill Fire (renamed)"
    assert event["status"] == "closed"


async def test_closed_record_closes_event(pipeline):
    await pipeline.run(eonet_event(closed="2024-06-10T00:00:00Z"))
    event = row("events", "id", "EONET_1")
    assert event["status"] == "closed"
    assert event["closed_at"] == "2024-06-10T00:00:00Z"
    assert event["closure_source"] == "eonet_closed_field"


async def test_absence_marks_not_observed_but_keeps_open(pipeline, client):
    await pipeline.run(eonet_event("EONET_1"), eonet_event("EONET_2"))
    seen = row("events", "id", "EONET_2")["last_seen"]
    assert row("events", "id", "EONET_2")["observation_state"] == "observed"

    await pipeline.run(eonet_event("EONET_1"))
    gone = row("events", "id", "EONET_2")
    assert gone["status"] == "open"
    assert gone["observation_state"] == "not_observed"
    assert gone["last_seen"] == seen
    assert row("events", "id", "EONET_1")["observation_state"] == "observed"

    # Listed for 30 days after it was last seen, then hidden (not deleted)
    ids = {e["id"] for e in client.get("/api/events").json()["events"]}
    assert ids == {"EONET_1", "EONET_2"}

    old = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat(timespec="seconds")
    conn = get_db()
    conn.execute("UPDATE events SET last_seen = ? WHERE id = 'EONET_2'", (old,))
    conn.commit()
    conn.close()
    ids = {e["id"] for e in client.get("/api/events").json()["events"]}
    assert ids == {"EONET_1"}
    assert row("events", "id", "EONET_2") is not None


async def test_empty_feed_marks_everything_not_observed(pipeline):
    await pipeline.run(eonet_event("EONET_1"))
    await pipeline.run()
    assert row("events", "id", "EONET_1")["observation_state"] == "not_observed"


async def test_no_digest_is_sql_null(pipeline, client):
    await pipeline.run(eonet_event())
    assert row("event_analysis", "event_id", "EONET_1")["gemini_digest"] is None
    [event] = client.get("/api/events").json()["events"]
    assert event["has_digest"] == 0


async def test_legacy_null_string_is_not_a_digest(pipeline, client):
    await pipeline.run(eonet_event())
    conn = get_db()
    conn.execute("UPDATE event_analysis SET gemini_digest = 'null'")
    conn.commit()
    conn.close()
    [event] = client.get("/api/events").json()["events"]
    assert event["has_digest"] == 0


async def test_existing_digest_is_kept(pipeline, monkeypatch):
    monkeypatch.setenv("DIGEST_GENERATION_ENABLED", "true")
    pipeline.label = "HIGH"
    pipeline.digest = {"what_happened": "fire"}
    await pipeline.run(eonet_event(dates=("2024-06-01T00:00:00Z",)))

    pipeline.digest = None
    await pipeline.run(eonet_event(dates=("2024-06-01T00:00:00Z", "2024-06-02T00:00:00Z")))
    stored = row("event_analysis", "event_id", "EONET_1")["gemini_digest"]
    assert json.loads(stored) == {"what_happened": "fire"}


async def test_reprocessing_updates_nlp_summary(pipeline):
    await pipeline.run(eonet_event(dates=("2024-06-01T00:00:00Z",)))
    assert row("event_analysis", "event_id", "EONET_1")["nlp_summary"] == "wildfire, arizona, smoke"

    pipeline.keyphrases = [("flood", 0.9)]
    await pipeline.run(eonet_event(dates=("2024-06-01T00:00:00Z", "2024-06-02T00:00:00Z")))
    assert row("event_analysis", "event_id", "EONET_1")["nlp_summary"] == "flood"


async def test_polygon_uses_ring_centre(pipeline):
    ring = [[-110.0, 30.0], [-108.0, 30.0], [-108.0, 32.0], [-110.0, 32.0], [-110.0, 30.0]]
    geometry = [{"date": "2024-06-01T00:00:00Z", "type": "Polygon", "coordinates": [ring]}]
    await pipeline.run(eonet_event(geometry=geometry))
    event = row("events", "id", "EONET_1")
    assert (event["lat"], event["lon"]) == (31.0, -109.0)
    assert event["geometry_type"] == "Polygon"


async def test_gdacs_missingness_is_explicit(pipeline):
    pipeline.gdacs["EONET_1"] = {"properties": {"eventid": 7, "alertlevel": "Orange",
                                               "alertscore": 2.5, "population": 1200}}
    await pipeline.run(eonet_event("EONET_1", category="Severe Storms"),
                       eonet_event("EONET_2", category="Severe Storms"))

    # GDACS is the label source, never a feature (M2 contract)
    matched, unmatched = pipeline.scored
    assert json.dumps(matched) == json.dumps(unmatched)  # NaN-safe comparison

    assert row("events", "id", "EONET_1")["gdacs_match_status"] == "matched"
    assert row("events", "id", "EONET_2")["gdacs_match_status"] == "no_match"
    assert row("gdacs_enrichment", "event_id", "EONET_1")["population_exposure"] == 1200
    assert row("gdacs_enrichment", "event_id", "EONET_2") is None


async def test_gdacs_match_without_population_stores_null(pipeline):
    pipeline.gdacs["EONET_1"] = {"properties": {"eventid": 7, "alertlevel": "Green", "alertscore": 1.0}}
    await pipeline.run(eonet_event("EONET_1"))
    assert row("gdacs_enrichment", "event_id", "EONET_1")["population_exposure"] is None

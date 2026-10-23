import json

from backend.tests.helpers import eonet_event, row

WITHHELD = {"severity_label", "severity_score", "shap_values", "shap_status", "imputed_features"}


async def seed_rated_event(pipeline, monkeypatch):
    monkeypatch.setenv("DIGEST_GENERATION_ENABLED", "true")
    pipeline.label = "HIGH"
    pipeline.shap_values = {"persons_affected": 1.5}
    pipeline.digest = {"what_happened": "fire", "severity_rationale": "rated HIGH", "outlook": "growing"}
    await pipeline.run(eonet_event())


async def test_event_list_withholds_severity(pipeline, client, monkeypatch):
    await seed_rated_event(pipeline, monkeypatch)
    [event] = client.get("/api/events").json()["events"]
    assert not WITHHELD & event.keys()
    assert event["severity_status"] == "withheld_unvalidated_model"
    assert event["has_digest"] == 1


async def test_event_detail_withholds_severity(pipeline, client, monkeypatch):
    await seed_rated_event(pipeline, monkeypatch)
    event = client.get("/api/events/EONET_1").json()
    assert not WITHHELD & event.keys()
    assert event["severity_status"] == "withheld_unvalidated_model"
    assert event["gemini_digest"] == {"what_happened": "fire", "outlook": "growing"}

    # Still computed and stored, for diagnostics
    stored = row("event_analysis", "event_id", "EONET_1")
    assert stored["severity_label"] == "HIGH"
    assert json.loads(stored["shap_values"]) == {"persons_affected": 1.5}
    assert json.loads(stored["gemini_digest"])["severity_rationale"] == "rated HIGH"


async def test_trends_withhold_severity(pipeline, client, monkeypatch):
    await seed_rated_event(pipeline, monkeypatch)
    trends = client.get("/api/trends").json()
    assert "severity_trends" not in trends
    assert trends["severity_status"] == "withheld_unvalidated_model"
    assert trends["category_trends"] == [{"category": "Wildfires", "count": 1}]


async def test_digests_paused_by_default(pipeline, monkeypatch):
    monkeypatch.delenv("DIGEST_GENERATION_ENABLED", raising=False)
    pipeline.label = "HIGH"
    pipeline.digest = {"what_happened": "fire"}
    await pipeline.run(eonet_event())
    assert pipeline.digest_calls == 0
    assert row("event_analysis", "event_id", "EONET_1")["gemini_digest"] is None


async def test_digests_resume_when_enabled(pipeline, monkeypatch):
    monkeypatch.setenv("DIGEST_GENERATION_ENABLED", "true")
    pipeline.label = "MODERATE"
    pipeline.digest = {"what_happened": "fire"}
    await pipeline.run(eonet_event())
    assert pipeline.digest_calls == 1


async def test_missing_event_is_404(client):
    assert client.get("/api/events/NOPE").status_code == 404

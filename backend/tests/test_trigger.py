import asyncio
import pathlib

import pytest

from backend.app.api import routes
from backend.app.pipeline import orchestrator
from backend.tests.helpers import eonet_event

TOKEN = "s3cret-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
REPO = pathlib.Path(__file__).resolve().parents[2]


@pytest.fixture
def token(monkeypatch):
    monkeypatch.setenv("PIPELINE_TRIGGER_TOKEN", TOKEN)


@pytest.fixture
def started(monkeypatch):
    """Records trigger starts without running the pipeline in the test client's loop."""
    calls = []

    def fake_start():
        calls.append(1)
        return object()

    monkeypatch.setattr(routes, "start_pipeline_task", fake_start)
    return calls


def test_trigger_disabled_without_configured_token(client, monkeypatch, started):
    monkeypatch.delenv("PIPELINE_TRIGGER_TOKEN", raising=False)
    assert client.post("/api/pipeline/trigger", headers=AUTH).status_code == 503
    assert started == []


@pytest.mark.parametrize("headers", [
    {}, {"Authorization": "Bearer wrong"}, {"Authorization": TOKEN}, {"Authorization": f"Basic {TOKEN}"},
])
def test_trigger_rejects_bad_tokens(client, token, started, headers):
    response = client.post("/api/pipeline/trigger", headers=headers)
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert started == []


def test_trigger_accepts_correct_token(client, token, started):
    response = client.post("/api/pipeline/trigger", headers=AUTH)
    assert response.status_code == 202
    assert started == [1]


def test_trigger_conflicts_while_a_run_is_active(client, token):
    assert orchestrator.try_claim_run()
    response = client.post("/api/pipeline/trigger", headers=AUTH)
    assert response.status_code == 409
    orchestrator.release_run()


async def test_scheduled_run_skipped_during_manual_run(pipeline, monkeypatch):
    pipeline.feed = [eonet_event()]
    gate = asyncio.Event()
    original = orchestrator.process_event

    async def slow_process_event(*args):
        await gate.wait()
        return await original(*args)

    monkeypatch.setattr(orchestrator, "process_event", slow_process_event)
    manual = orchestrator.start_pipeline_task()
    assert manual is not None
    assert orchestrator.start_pipeline_task() is None  # refused before the task even starts
    await asyncio.sleep(0)
    assert await orchestrator.run_pipeline() is None   # the scheduler's call is skipped
    gate.set()
    assert await manual is True
    assert len(pipeline.scored) == 1
    assert not orchestrator.run_in_progress()


async def test_run_released_after_failure(pipeline, monkeypatch):
    async def broken():
        raise RuntimeError("feed down")

    monkeypatch.setattr(orchestrator, "run_ingestion", broken)
    assert await orchestrator.run_pipeline() is False
    assert not orchestrator.run_in_progress()


def test_trigger_rate_limited_including_failed_attempts(client, token, started):
    codes = [client.post("/api/pipeline/trigger", headers={"Authorization": "Bearer wrong"}).status_code
             for _ in range(3)]
    assert codes == [401, 401, 401]
    assert client.post("/api/pipeline/trigger", headers=AUTH).status_code == 429
    assert started == []


def test_reads_rate_limited(client):
    codes = [client.get("/api/trends").status_code for _ in range(121)]
    assert codes[:120] == [200] * 120
    assert codes[120] == 429


async def test_diagnostics_require_token(pipeline, client, token, monkeypatch):
    pipeline.label = "HIGH"
    pipeline.shap_values = {"persons_affected": 1.5}
    await pipeline.run(eonet_event())

    assert client.get("/api/internal/events/EONET_1/diagnostics").status_code == 401
    response = client.get("/api/internal/events/EONET_1/diagnostics", headers=AUTH)
    assert response.status_code == 200
    body = response.json()
    assert body["severity_label"] == "HIGH"
    assert body["shap_values"] == {"persons_affected": 1.5}
    assert body["imputed_features"] == []
    assert client.get("/api/internal/events/NOPE/diagnostics", headers=AUTH).status_code == 404

    monkeypatch.delenv("PIPELINE_TRIGGER_TOKEN")
    assert client.get("/api/internal/events/EONET_1/diagnostics", headers=AUTH).status_code == 503


def test_frontend_holds_no_trigger_token():
    for path in (REPO / "frontend" / "src").rglob("*"):
        if path.is_file() and path.suffix in {".js", ".jsx", ".ts", ".tsx"}:
            text = path.read_text()
            assert "PIPELINE_TRIGGER_TOKEN" not in text, path
            assert "pipeline/trigger" not in text, path
            assert "internal/events" not in text, path

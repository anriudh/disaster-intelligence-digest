"""Shared builders and fakes for pipeline and API tests."""
from backend.app.db.database import get_db
from backend.app.pipeline import orchestrator


def eonet_event(event_id="EONET_1", dates=("2024-06-01T00:00:00Z",), closed=None,
                coords=None, title="Sawmill Fire", geometry=None):
    """An EONET event whose geometry points are listed in the given date order."""
    if geometry is None:
        geometry = [
            {"date": d, "type": "Point", "coordinates": list(coords[i]) if coords else [-110.0 - i, 32.0 + i]}
            for i, d in enumerate(dates)
        ]
    return {
        "id": event_id,
        "title": title,
        "description": None,
        "closed": closed,
        "categories": [{"title": "Wildfires"}],
        "sources": [{"url": "https://example.com"}],
        "geometry": geometry,
    }


class FakePipeline:
    """Replaces the network, NLP and model steps of the orchestrator."""

    def __init__(self, monkeypatch):
        self.feed = []
        self.scored = []
        self.keyphrases = [("wildfire", 0.9), ("arizona", 0.8), ("smoke", 0.7)]
        self.label = "LOW"
        self.digest = None

        self.gdacs = {}

        async def run_ingestion():
            return [{"eonet": e, "gdacs": self.gdacs.get(e["id"])} for e in self.feed]

        async def scrape(event):
            return {"text": "text", "source": "fallback", "quality": "fallback"}

        self.shap_values = {}

        def score(features):
            self.scored.append(features)
            return {"severity_label": self.label, "severity_score": 0.9,
                    "shap_values": self.shap_values, "shap_status": "ok", "imputed_features": []}

        self.digest_calls = 0

        async def digest(data):
            self.digest_calls += 1
            return self.digest

        # EONET records returned by the per-event lookup; a missing ID raises
        self.records = {}
        self.lookups = []

        async def lookup(event_id):
            self.lookups.append(event_id)
            if event_id not in self.records:
                raise RuntimeError(f"no record for {event_id}")
            return self.records[event_id]

        monkeypatch.setattr(orchestrator, "run_ingestion", run_ingestion)
        monkeypatch.setattr(orchestrator, "fetch_eonet_event", lookup)
        monkeypatch.setattr(orchestrator, "scrape_event_sources", scrape)
        monkeypatch.setattr(orchestrator, "run_nlp_pipeline",
                            lambda text: {"entities": [], "signals": {}, "keyphrases": self.keyphrases})
        monkeypatch.setattr(orchestrator, "get_embeddings", lambda text: [0.0])
        monkeypatch.setattr(orchestrator, "score_event", score)
        monkeypatch.setattr(orchestrator, "generate_digest", digest)

    async def run(self, *events):
        self.feed = list(events)
        assert await orchestrator.run_pipeline()


def row(table, key, value):
    conn = get_db()
    result = conn.execute(f"SELECT * FROM {table} WHERE {key} = ?", (value,)).fetchone()
    conn.close()
    return dict(result) if result else None

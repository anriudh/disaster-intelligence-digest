"""B5: recompute nlp_summary from the stored keyphrases where it went stale (it was not updated on reprocessing)."""
import json

from backend.app.db.migrate import preserve_original

VERSION = 10


def migrate(conn):
    rows = conn.execute("SELECT event_id, keyphrases, nlp_summary FROM event_analysis").fetchall()
    for event_id, keyphrases, summary in rows:
        try:
            phrases = json.loads(keyphrases) if keyphrases else []
        except ValueError:
            continue
        expected = ", ".join([k[0] for k in phrases[:3]])  # same formula as the orchestrator
        if summary != expected:
            preserve_original(conn, "event_analysis", event_id, "nlp_summary", summary, VERSION)
            conn.execute("UPDATE event_analysis SET nlp_summary = ? WHERE event_id = ?", (expected, event_id))

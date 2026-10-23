"""B1: digests that were never generated were stored as the string 'null'; make them SQL NULL."""
from backend.app.db.migrate import preserve_original

VERSION = 6


def migrate(conn):
    rows = conn.execute("SELECT event_id, gemini_digest FROM event_analysis WHERE gemini_digest = 'null'").fetchall()
    for event_id, old in rows:
        preserve_original(conn, "event_analysis", event_id, "gemini_digest", old, VERSION)
    conn.execute("UPDATE event_analysis SET gemini_digest = NULL WHERE gemini_digest = 'null'")

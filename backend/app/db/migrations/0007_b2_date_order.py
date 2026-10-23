"""
B2: rows stored from ascending EONET geometry have first_seen and last_updated
swapped. Both are geometry endpoints, so min/max restores them whatever the order.
"""
from backend.app.db.migrate import preserve_original

VERSION = 7


def migrate(conn):
    rows = conn.execute(
        "SELECT id, first_seen, last_updated FROM events WHERE first_seen > last_updated"
    ).fetchall()
    for event_id, first_seen, last_updated in rows:
        preserve_original(conn, "events", event_id, "first_seen", first_seen, VERSION)
        preserve_original(conn, "events", event_id, "last_updated", last_updated, VERSION)
        conn.execute(
            "UPDATE events SET first_seen = ?, last_updated = ? WHERE id = ?",
            (last_updated, first_seen, event_id),
        )

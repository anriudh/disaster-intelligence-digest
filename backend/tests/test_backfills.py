"""
Backfills B1-B6, run against a copy of the committed database. The committed
file itself is never migrated by tests (conftest checks its hash).
"""
import glob
import hashlib
import json
import shutil
import sqlite3

import pytest

from backend.app.db import database
from backend.app.db.migrate import MIGRATIONS_DIR, discover_migrations, restore_backup, run_migrations
from backend.tests.conftest import COMMITTED_DB


def sha256(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def query(db, sql, args=()):
    conn = sqlite3.connect(db)
    rows = conn.execute(sql, args).fetchall()
    conn.close()
    return rows


def scalar(db, sql, args=()):
    return query(db, sql, args)[0][0]


@pytest.fixture
def committed_copy(tmp_path):
    copy = tmp_path / "committed_copy.db"
    shutil.copyfile(COMMITTED_DB, copy)
    return copy


@pytest.fixture
def migrated_copy(committed_copy):
    before = {t: scalar(committed_copy, f"SELECT COUNT(*) FROM {t}")
              for t in ("events", "event_analysis", "gdacs_enrichment", "event_history")}
    run_migrations(str(committed_copy))
    after = {t: scalar(committed_copy, f"SELECT COUNT(*) FROM {t}") for t in before}
    assert after == before  # additive only: no rows added or removed
    return committed_copy


def legacy(db, version):
    return query(db, "SELECT table_name, row_id, column_name, old_value FROM legacy_values "
                     "WHERE migration_version = ? ORDER BY id", (version,))


def test_b1_null_digests(migrated_copy):
    assert scalar(migrated_copy, "SELECT COUNT(*) FROM event_analysis WHERE gemini_digest = 'null'") == 0
    assert scalar(migrated_copy, "SELECT COUNT(*) FROM event_analysis WHERE gemini_digest IS NULL") == 100
    originals = legacy(migrated_copy, 6)
    assert len(originals) == 100
    assert {(t, c, v) for t, _, c, v in originals} == {("event_analysis", "gemini_digest", "null")}


def test_b2_date_order(migrated_copy):
    assert query(migrated_copy, "SELECT first_seen, last_updated FROM events WHERE id = 'EONET_19481'") == [
        ("2026-04-09T18:00:00Z", "2026-04-18T12:00:00Z")]
    assert scalar(migrated_copy, "SELECT COUNT(*) FROM events WHERE first_seen > last_updated") == 0
    assert legacy(migrated_copy, 7) == [
        ("events", "EONET_19481", "first_seen", "2026-04-18T12:00:00Z"),
        ("events", "EONET_19481", "last_updated", "2026-04-09T18:00:00Z"),
    ]


def test_b3_shap_marked_invalid_but_kept(committed_copy):
    before = query(committed_copy, "SELECT event_id, shap_values FROM event_analysis ORDER BY event_id")
    run_migrations(str(committed_copy))
    assert scalar(committed_copy, "SELECT COUNT(*) FROM event_analysis "
                                  "WHERE shap_status = 'invalid_legacy_indexing'") == 100
    assert query(committed_copy, "SELECT event_id, shap_values FROM event_analysis ORDER BY event_id") == before


def test_b4_scrape_quality(migrated_copy):
    counts = dict(query(migrated_copy, "SELECT scrape_quality, COUNT(*) FROM event_analysis GROUP BY 1"))
    assert counts == {"rejected_boilerplate": 99, "legacy_unchecked": 1}
    assert legacy(migrated_copy, 9) == []  # text is kept, nothing overwritten


def test_b5_nlp_summary(migrated_copy):
    # Every committed summary already matches its keyphrases
    assert legacy(migrated_copy, 10) == []


def test_b6_legacy_markers(migrated_copy):
    assert query(migrated_copy, "SELECT observation_state, gdacs_match_status, COUNT(*) FROM events GROUP BY 1, 2") == [
        ("unknown_legacy", "not_checked", 100)]


def test_rerun_is_a_noop_and_db_is_sound(migrated_copy):
    before = sha256(migrated_copy)
    assert run_migrations(str(migrated_copy)) == []
    assert sha256(migrated_copy) == before
    assert scalar(migrated_copy, "PRAGMA integrity_check") == "ok"


def dump(db):
    conn = sqlite3.connect(db)
    lines = list(conn.iterdump())
    conn.close()
    return lines


def test_restore_returns_the_original_content(committed_copy):
    original = dump(committed_copy)
    run_migrations(str(committed_copy))
    assert dump(committed_copy) != original
    [backup] = glob.glob(f"{committed_copy}.bak-*")
    # The backup API copies pages, so file headers may differ; the content may not
    assert dump(backup) == original
    restore_backup(backup, str(committed_copy))
    assert sha256(committed_copy) == sha256(backup)
    assert dump(committed_copy) == original


def test_api_after_backfill(migrated_copy, client, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", str(migrated_copy))
    events = client.get("/api/events").json()["events"]
    assert len(events) == 100
    assert all(e["has_digest"] == 0 for e in events)
    assert all(e["observation_state"] == "unknown_legacy" for e in events)


def test_b5_recomputes_stale_summary(tmp_path):
    # Apply the schema migrations only, store a stale legacy row, then the backfills
    early = tmp_path / "early"
    early.mkdir()
    for version, name, path in discover_migrations():
        if version <= 5:
            shutil.copy(path, early / name)
    db = tmp_path / "db.sqlite"
    database_path = str(db)
    conn = sqlite3.connect(db)
    with open(database.SCHEMA_PATH) as f:
        conn.executescript(f.read())
    conn.close()
    run_migrations(database_path, str(early), backup=False)

    conn = sqlite3.connect(db)
    conn.execute("INSERT INTO events (id, title, category) VALUES ('E1', 'Fire', 'Wildfires')")
    conn.execute("INSERT INTO event_analysis (event_id, keyphrases, nlp_summary) VALUES ('E1', ?, 'old summary')",
                 (json.dumps([["flood", 0.9], ["river", 0.8]]),))
    conn.commit()
    conn.close()

    run_migrations(database_path, MIGRATIONS_DIR, backup=False)
    assert scalar(db, "SELECT nlp_summary FROM event_analysis WHERE event_id = 'E1'") == "flood, river"
    assert legacy(db, 10) == [("event_analysis", "E1", "nlp_summary", "old summary")]


async def test_backfills_leave_new_rows_alone(pipeline, tmp_path, monkeypatch):
    """Rows written by the fixed pipeline already carry the new markers and are not rewritten."""
    early = tmp_path / "early"
    early.mkdir()
    for version, name, path in discover_migrations():
        if version <= 5:
            shutil.copy(path, early / name)
    db = tmp_path / "db.sqlite"
    monkeypatch.setattr(database, "DB_PATH", str(db))
    database.execute_schema()
    run_migrations(str(db), str(early), backup=False)

    from backend.tests.helpers import eonet_event
    await pipeline.run(eonet_event(dates=("2024-06-01T00:00:00Z", "2024-06-03T00:00:00Z")))
    before = query(db, "SELECT * FROM events"), query(db, "SELECT * FROM event_analysis")

    run_migrations(str(db), MIGRATIONS_DIR, backup=False)
    after = query(db, "SELECT * FROM events"), query(db, "SELECT * FROM event_analysis")
    assert after == before
    assert scalar(db, "SELECT COUNT(*) FROM legacy_values") == 0

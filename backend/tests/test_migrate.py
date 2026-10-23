import glob
import hashlib
import shutil
import sqlite3

import pytest

from backend.app.db import database
from backend.app.db.migrate import (
    MigrationError,
    discover_migrations,
    restore_backup,
    run_migrations,
)
from backend.tests.conftest import COMMITTED_DB, LEGACY_DB


def sha256(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def columns(db_path, table):
    conn = sqlite3.connect(db_path)
    cols = [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]
    conn.close()
    return cols


def versions(db_path):
    conn = sqlite3.connect(db_path)
    rows = [row[0] for row in conn.execute("SELECT version FROM schema_migrations ORDER BY version")]
    conn.close()
    return rows


def backups(db_path):
    return sorted(glob.glob(f"{db_path}.bak-*"))


@pytest.fixture
def raw_db(tmp_path, monkeypatch):
    """A temporary DB with the base schema only, for exercising the runner itself."""
    db_path = tmp_path / "raw.db"
    monkeypatch.setattr(database, "DB_PATH", str(db_path))
    database.execute_schema()
    return db_path


@pytest.fixture
def mig_dir(tmp_path):
    d = tmp_path / "migrations"
    d.mkdir()
    (d / "0001_add_note.sql").write_text(
        "-- add a column\nALTER TABLE events ADD COLUMN note TEXT;\n"
    )
    (d / "0002_add_table.py").write_text(
        "def migrate(conn):\n"
        "    conn.execute('CREATE TABLE extra (id INTEGER PRIMARY KEY)')\n"
    )
    return d


def test_shipped_migrations_are_well_formed():
    # The README in the migrations directory must not be picked up as a migration
    shipped = discover_migrations()
    assert [v for v, _, _ in shipped] == list(range(1, len(shipped) + 1))
    for version, name, path in shipped:
        assert name.endswith((".sql", ".py"))


def test_shipped_migrations_apply_to_legacy_db_copy(tmp_path):
    copy = tmp_path / "legacy_copy.db"
    shutil.copyfile(LEGACY_DB, copy)
    applied = run_migrations(str(copy))
    assert applied == [v for v, _, _ in discover_migrations()]
    assert run_migrations(str(copy)) == []
    conn = sqlite3.connect(copy)
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    conn.close()


def test_committed_db_copy_migrates_to_latest(tmp_path):
    # The committed DB has had 0001-0011 applied (A9); later migrations apply at startup
    copy = tmp_path / "committed_copy.db"
    shutil.copyfile(COMMITTED_DB, copy)
    shipped = [v for v, _, _ in discover_migrations()]
    already = versions(copy)
    assert already[:11] == list(range(1, 12))
    assert run_migrations(str(copy)) == [v for v in shipped if v not in already]
    assert versions(copy) == shipped
    assert run_migrations(str(copy)) == []
    conn = sqlite3.connect(copy)
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    conn.close()


def test_init_db_migrates_fresh_db(isolated_db):
    # conftest builds every test DB with init_db()
    assert versions(isolated_db) == [v for v, _, _ in discover_migrations()]


def test_fresh_db_migrates_with_backup(raw_db, mig_dir):
    assert run_migrations(str(raw_db), str(mig_dir)) == [1, 2]
    assert "note" in columns(raw_db, "events")
    assert versions(raw_db) == [1, 2]

    [backup] = backups(raw_db)
    assert ".bak-0001-" in backup
    conn = sqlite3.connect(backup)
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert "note" not in [row[1] for row in conn.execute("PRAGMA table_info(events)")]
    conn.close()


def test_rerun_is_a_noop(raw_db, mig_dir):
    run_migrations(str(raw_db), str(mig_dir))
    before = sha256(raw_db)
    assert run_migrations(str(raw_db), str(mig_dir)) == []
    assert sha256(raw_db) == before
    assert len(backups(raw_db)) == 1


def test_nothing_pending_writes_nothing(raw_db, tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    before = sha256(raw_db)
    assert run_migrations(str(raw_db), str(empty)) == []
    assert sha256(raw_db) == before
    assert backups(raw_db) == []


def test_copy_of_legacy_db_migrates(tmp_path, mig_dir):
    copy = tmp_path / "legacy_copy.db"
    shutil.copyfile(LEGACY_DB, copy)
    conn = sqlite3.connect(copy)
    counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
              for t in ("events", "event_analysis", "gdacs_enrichment")}
    conn.close()

    assert run_migrations(str(copy), str(mig_dir)) == [1, 2]

    conn = sqlite3.connect(copy)
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    for table, count in counts.items():
        assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == count
    conn.close()
    assert counts["events"] > 0


def test_failing_migration_rolls_back(raw_db, mig_dir):
    (mig_dir / "0003_broken.sql").write_text(
        "ALTER TABLE events ADD COLUMN half_done TEXT;\nTHIS IS NOT SQL;\n"
    )
    (mig_dir / "0004_never_runs.sql").write_text("ALTER TABLE events ADD COLUMN later TEXT;\n")

    with pytest.raises(MigrationError, match="0003_broken.sql"):
        run_migrations(str(raw_db), str(mig_dir))

    cols = columns(raw_db, "events")
    assert "note" in cols
    assert "half_done" not in cols
    assert "later" not in cols
    assert versions(raw_db) == [1, 2]


def test_changed_migration_is_refused(raw_db, mig_dir):
    run_migrations(str(raw_db), str(mig_dir))
    (mig_dir / "0001_add_note.sql").write_text("ALTER TABLE events ADD COLUMN other TEXT;\n")
    with pytest.raises(MigrationError, match="changed after it was applied"):
        run_migrations(str(raw_db), str(mig_dir))


def test_missing_applied_migration_is_refused(raw_db, mig_dir):
    run_migrations(str(raw_db), str(mig_dir))
    (mig_dir / "0002_add_table.py").unlink()
    with pytest.raises(MigrationError, match="missing"):
        run_migrations(str(raw_db), str(mig_dir))


def test_restore_from_backup(raw_db, mig_dir):
    conn = sqlite3.connect(raw_db)
    conn.execute("INSERT INTO events (id, title, category) VALUES ('E1', 'Fire', 'Wildfires')")
    conn.commit()
    conn.close()

    run_migrations(str(raw_db), str(mig_dir))
    [backup] = backups(raw_db)
    assert sha256(raw_db) != sha256(backup)

    restore_backup(backup, str(raw_db))
    assert sha256(raw_db) == sha256(backup)
    assert "note" not in columns(raw_db, "events")


def test_defaults_to_configured_db(raw_db, mig_dir):
    assert database.DB_PATH == str(raw_db)
    assert run_migrations(migrations_dir=str(mig_dir)) == [1, 2]

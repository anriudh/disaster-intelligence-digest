"""
Additive, versioned schema migrations.

Migrations live in backend/app/db/migrations/ as NNNN_name.sql or NNNN_name.py
(a .py migration defines migrate(conn) and must not commit). Each one runs in its own transaction
and is recorded in schema_migrations with a checksum of its file.

Before anything is applied, the database is copied with the SQLite backup API
to <db>.bak-<version>-<timestamp> and the copy is verified. Migrations are
additive only, so rolling back means restoring that backup (restore_backup).
"""
import hashlib
import importlib.util
import logging
import os
import re
import shutil
import sqlite3
from datetime import datetime, timezone

from backend.app.db import database

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = os.path.join(os.path.dirname(__file__), "migrations")
MIGRATION_FILE = re.compile(r"^(\d{4})_[a-z0-9_]+\.(sql|py)$")

BOOKKEEPING_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    checksum TEXT NOT NULL,
    applied_at TEXT NOT NULL
);

-- Original values of rows changed by backfills, so corrections are reversible
CREATE TABLE IF NOT EXISTS legacy_values (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    table_name TEXT NOT NULL,
    row_id TEXT NOT NULL,
    column_name TEXT NOT NULL,
    old_value TEXT,
    migration_version INTEGER NOT NULL,
    recorded_at TEXT NOT NULL
);
"""


class MigrationError(Exception):
    pass


def _now():
    return datetime.now(timezone.utc).isoformat()


def _checksum(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def discover_migrations(migrations_dir=MIGRATIONS_DIR):
    """Return [(version, name, path)] sorted by version."""
    found = []
    if not os.path.isdir(migrations_dir):
        return found
    for filename in os.listdir(migrations_dir):
        match = MIGRATION_FILE.match(filename)
        if match:
            found.append((int(match.group(1)), filename, os.path.join(migrations_dir, filename)))
    found.sort()
    versions = [v for v, _, _ in found]
    if len(versions) != len(set(versions)):
        raise MigrationError(f"Duplicate migration versions in {migrations_dir}")
    return found


def applied_migrations(conn):
    """Return {version: checksum} for applied migrations, without writing anything."""
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
    ).fetchone()
    if not exists:
        return {}
    return {row[0]: row[1] for row in conn.execute("SELECT version, checksum FROM schema_migrations")}


def _table_counts(conn):
    tables = [row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    )]
    return {t: conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tables}


def backup_database(db_path, version):
    """Copy db_path with the SQLite backup API and verify the copy. Returns the backup path."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup_path = f"{db_path}.bak-{version:04d}-{stamp}"
    src = sqlite3.connect(db_path)
    dst = sqlite3.connect(backup_path)
    try:
        src.backup(dst)
        if dst.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise MigrationError(f"Backup {backup_path} failed integrity_check")
        if _table_counts(src) != _table_counts(dst):
            raise MigrationError(f"Backup {backup_path} row counts differ from {db_path}")
    finally:
        dst.close()
        src.close()
    logger.info(f"Backed up {db_path} to {backup_path}")
    return backup_path


def restore_backup(backup_path, db_path):
    """Roll back by replacing db_path with a backup. No connections may be open."""
    for suffix in ("-wal", "-shm", "-journal"):
        if os.path.exists(db_path + suffix):
            raise MigrationError(f"{db_path}{suffix} exists; close all connections before restoring")
    shutil.copyfile(backup_path, db_path)
    logger.info(f"Restored {db_path} from {backup_path}")


def _split_sql(script):
    statements, current = [], ""
    for line in script.splitlines(keepends=True):
        current += line
        if sqlite3.complete_statement(current):
            if current.strip():
                statements.append(current)
            current = ""
    leftover = [l for l in current.splitlines() if l.strip() and not l.strip().startswith("--")]
    if leftover:
        raise MigrationError("Incomplete SQL statement at end of migration")
    return statements


def _run_python_migration(conn, path):
    spec = importlib.util.spec_from_file_location(f"migration_{os.path.basename(path)[:-3]}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.migrate(conn)


def run_migrations(db_path=None, migrations_dir=MIGRATIONS_DIR, backup=True):
    """
    Apply pending migrations in version order. Returns the list of applied versions.

    Writes nothing when there is nothing pending. Raises MigrationError if an
    applied migration's file changed or went missing, or if a migration fails;
    a failed migration is rolled back and later ones are not attempted.
    """
    db_path = db_path or database.DB_PATH
    migrations = discover_migrations(migrations_dir)

    conn = sqlite3.connect(db_path, isolation_level=None)
    try:
        applied = applied_migrations(conn)
        known = {v for v, _, _ in migrations}
        for version, checksum in applied.items():
            if version not in known:
                raise MigrationError(f"Applied migration {version:04d} is missing from {migrations_dir}")
        pending = []
        for version, name, path in migrations:
            if version in applied:
                if applied[version] != _checksum(path):
                    raise MigrationError(f"Migration {name} changed after it was applied")
            else:
                pending.append((version, name, path))
        if not pending:
            return []

        if backup:
            conn.close()
            backup_database(db_path, pending[0][0])
            conn = sqlite3.connect(db_path, isolation_level=None)

        conn.executescript(BOOKKEEPING_SQL)
        done = []
        for version, name, path in pending:
            conn.execute("BEGIN")
            try:
                if path.endswith(".sql"):
                    with open(path) as f:
                        for statement in _split_sql(f.read()):
                            conn.execute(statement)
                else:
                    _run_python_migration(conn, path)
                conn.execute(
                    "INSERT INTO schema_migrations (version, name, checksum, applied_at) VALUES (?, ?, ?, ?)",
                    (version, name, _checksum(path), _now()),
                )
                conn.execute("COMMIT")
            except Exception as e:
                conn.execute("ROLLBACK")
                raise MigrationError(f"Migration {name} failed and was rolled back: {e}") from e
            logger.info(f"Applied migration {name}")
            done.append(version)
        return done
    finally:
        conn.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    database.execute_schema()
    print(f"Applied migrations: {run_migrations() or 'none pending'}")

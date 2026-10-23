import hashlib
import os

import pytest

from backend.app.db import database

COMMITTED_DB = os.path.abspath(database.DB_PATH)


def _sha256(path):
    if not os.path.exists(path):
        return None
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    """Point every test at a fresh temporary database, never the committed one."""
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(database, "DB_PATH", str(db_path))
    database.execute_schema()
    return db_path


@pytest.fixture(scope="session", autouse=True)
def committed_db_untouched():
    """Fail the run if any test modified the committed database file."""
    before = _sha256(COMMITTED_DB)
    yield
    assert _sha256(COMMITTED_DB) == before, f"{COMMITTED_DB} was modified by the test run"

import hashlib
import importlib.util
import os
import sys
import types

import pytest

from backend.app.db import database

COMMITTED_DB = os.path.abspath(database.DB_PATH)


def _install_nlp_stand_ins():
    """
    The NLP modules load spaCy, KeyBERT and sentence-transformers models at import.
    Where those libraries are not installed, register stand-in modules so the
    orchestrator and API can be imported; tests replace the functions they use.
    test_nlp.py skips itself in that case, so it never sees these stand-ins.
    """
    if not all(importlib.util.find_spec(n) for n in ("spacy", "keybert")):
        nlp = types.ModuleType("backend.app.pipeline.nlp")
        nlp.nlp = None
        nlp.kw_model = None
        nlp.run_nlp_pipeline = lambda text: {"entities": [], "signals": {}, "keyphrases": []}
        sys.modules["backend.app.pipeline.nlp"] = nlp
    if not importlib.util.find_spec("sentence_transformers"):
        emb = types.ModuleType("backend.app.pipeline.embeddings")
        emb.model = None
        emb.get_embeddings = lambda text: []
        sys.modules["backend.app.pipeline.embeddings"] = emb


_install_nlp_stand_ins()


def _sha256(path):
    if not os.path.exists(path):
        return None
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    """Point every test at a fresh, fully migrated temporary database, never the committed one."""
    from backend.app.db.migrate import init_db

    db_path = tmp_path / "test.db"
    monkeypatch.setattr(database, "DB_PATH", str(db_path))
    init_db(backup=False)
    return db_path


@pytest.fixture(scope="session", autouse=True)
def committed_db_untouched():
    """Fail the run if any test modified the committed database file."""
    before = _sha256(COMMITTED_DB)
    yield
    assert _sha256(COMMITTED_DB) == before, f"{COMMITTED_DB} was modified by the test run"

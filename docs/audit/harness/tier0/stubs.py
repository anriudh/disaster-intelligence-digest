"""Placeholder modules for third-party imports that are not installed.

They let the project's own logic be imported. Anything that would touch the
network, load a model or unpickle an artifact raises instead.
"""
import os
import sqlite3
import sys
import types

SCRATCH = os.environ["P1_SCRATCH"]


class Blocked(RuntimeError):
    pass


def _blocked(what):
    def f(*a, **k):
        raise Blocked(f"{what} is blocked in Tier 0")
    return f


def _mod(name, **attrs):
    m = types.ModuleType(name)
    m.__dict__.update(attrs)
    sys.modules[name] = m
    return m


def install():
    # Network
    _mod("httpx", AsyncClient=_blocked("httpx.AsyncClient"), get=_blocked("httpx.get"))
    _mod("gdacs")
    _mod("gdacs.api", GDACSAPIReader=_blocked("GDACSAPIReader"))
    _mod("trafilatura", extract=_blocked("trafilatura.extract"))
    # NLP models: the project catches load failures and degrades to None
    _mod("spacy", load=_blocked("spacy.load"))
    _mod("keybert", KeyBERT=_blocked("KeyBERT"))
    _mod("sentence_transformers", SentenceTransformer=_blocked("SentenceTransformer"))
    # ML / artifacts
    _mod("joblib", load=_blocked("joblib.load (unpickling)"), dump=_blocked("joblib.dump"))
    _mod("shap", TreeExplainer=_blocked("shap.TreeExplainer"))
    _mod("xgboost", XGBClassifier=_blocked("XGBClassifier"))
    _mod("sklearn")
    _mod("sklearn.model_selection", train_test_split=_blocked("train_test_split"))
    _mod("sklearn.metrics", classification_report=_blocked("classification_report"))
    _mod("sklearn.impute", SimpleImputer=_blocked("SimpleImputer"))
    # Gemini / env
    g = _mod("google")
    genai = _mod("google.genai", Client=_blocked("genai.Client"))
    g.genai = genai
    _mod("dotenv", load_dotenv=lambda *a, **k: False)

    # fastapi: pass-through decorators so route handlers can be called directly
    class HTTPException(Exception):
        def __init__(self, status_code, detail=None):
            super().__init__(status_code, detail)
            self.status_code, self.detail = status_code, detail

    class APIRouter:
        def _deco(self, *a, **k):
            return lambda f: f
        get = post = _deco

    _mod("fastapi", APIRouter=APIRouter, HTTPException=HTTPException, Request=object)

    # pytest: only what the test modules use at import time
    class _Mark:
        def __getattr__(self, _):
            return lambda f: f
    _mod("pytest", mark=_Mark())

    # SQLite guard: only databases inside the scratch directory may be opened
    real_connect = sqlite3.connect

    def guarded(database, *a, **k):
        path = str(database)
        if path.startswith("file:"):
            path = path[5:].split("?", 1)[0]
        if path != ":memory:":
            real = os.path.realpath(path)
            if not real.startswith(os.path.realpath(SCRATCH) + os.sep):
                raise Blocked(f"sqlite connect outside scratch refused: {real}")
        return real_connect(database, *a, **k)

    sqlite3.connect = guarded

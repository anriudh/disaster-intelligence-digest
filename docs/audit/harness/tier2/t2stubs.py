"""pytest plugin (audit only): stub google.genai and dotenv, which test_scorer imports via gemini.py
but which are not ML dependencies; refuse any non-read-only SQLite connection."""
import sqlite3, sys, types
def _blocked(*a, **k): raise RuntimeError("genai.Client blocked in Tier 2")
g = types.ModuleType("google"); genai = types.ModuleType("google.genai"); genai.Client = _blocked; g.genai = genai
sys.modules.setdefault("google", g); sys.modules["google.genai"] = genai
d = types.ModuleType("dotenv"); d.load_dotenv = lambda *a, **k: False; sys.modules["dotenv"] = d
_real = sqlite3.connect
def _ro(db, *a, **k):
    s = str(db)
    if not (s.startswith("file:") and "mode=ro" in s):
        raise RuntimeError(f"database write path refused in Tier 2: {s}")
    return _real(db, *a, **k)
sqlite3.connect = _ro

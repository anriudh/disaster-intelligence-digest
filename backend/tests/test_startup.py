import os
import pathlib
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]


def test_documented_module_paths_resolve_from_repo_root():
    """The README runs `uvicorn backend.app.main:app` and `python -m backend.scripts.seed_db` from the root."""
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    code = (
        "import importlib.util as u;"
        "assert u.find_spec('backend.app.main');"
        "assert u.find_spec('backend.scripts.seed_db')"
    )
    subprocess.run([sys.executable, "-c", code], cwd=REPO, env=env, check=True)


def test_readme_commands_use_module_paths():
    readme = (REPO / "README.md").read_text()
    assert "uvicorn backend.app.main:app" in readme
    assert "python -m backend.scripts.seed_db" in readme
    assert "python backend/app/main.py" not in readme


@pytest.mark.model
def test_model_paths_resolve_from_any_directory(tmp_path, monkeypatch):
    pytest.importorskip("xgboost")
    from backend.app.pipeline import scorer

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(scorer, "model", None)
    monkeypatch.setattr(scorer, "imputer", None)
    monkeypatch.setattr(scorer, "explainer", None)
    scorer.load_models()
    assert scorer.model is not None and scorer.imputer is not None


def test_pinned_versions_match_the_model_artifacts():
    requirements = (REPO / "backend" / "requirements.txt").read_text().split()
    constraints = (REPO / "backend" / "constraints.txt").read_text().split()
    for pin in ("scikit-learn==1.8.0", "xgboost==3.2.0", "shap==0.54.1"):
        assert pin in requirements
        assert pin in constraints
    assert not any(r.startswith("pytest") for r in requirements)

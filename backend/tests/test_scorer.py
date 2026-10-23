import pytest

pytest.importorskip("xgboost")
pytest.importorskip("shap")

from backend.app.pipeline.scorer import score_event, load_models

pytestmark = pytest.mark.model

def test_model_loading():
    load_models()
    from backend.app.pipeline.scorer import model, imputer, explainer
    assert model is not None
    assert imputer is not None
    assert explainer is not None

def test_score_event_keys():
    dummy_features = {
        "event_category_encoded": 0,
        "gdacs_alert_score": 4.5,
        "source_count": 5
    }
    result = score_event(dummy_features)
    assert "severity_label" in result
    assert "severity_score" in result
    assert "shap_values" in result
    assert result["severity_label"] in ["LOW", "MODERATE", "HIGH"]
    assert isinstance(result["severity_score"], float)
    assert len(result["shap_values"]) <= 5


import logging

import numpy as np
import pandas as pd
import xgboost as xgb

from backend.app.pipeline import scorer
from backend.app.pipeline.scorer import FEATURE_COLUMNS, LABEL_MAP, class_contributions

# persons_affected drives the current model's label (see docs/audit/LEDGER.md)
LOW_FIXTURE = {"event_category_encoded": 0, "source_count": 1}
MODERATE_FIXTURE = {"persons_affected": 3000}
HIGH_FIXTURE = {"persons_affected": 50000, "casualties": 50}


def xgb_contributions(features):
    scorer.load_models()
    df = pd.DataFrame([features]).reindex(columns=FEATURE_COLUMNS).astype(float)
    X = pd.DataFrame(scorer.imputer.transform(df), columns=FEATURE_COLUMNS)
    probs = scorer.model.predict_proba(X)[0]
    pred = int(np.argmax(probs))
    contribs = scorer.model.get_booster().predict(xgb.DMatrix(X), pred_contribs=True)
    return LABEL_MAP[pred], dict(zip(FEATURE_COLUMNS, contribs[0, pred, :-1]))


@pytest.mark.parametrize("features,label", [
    (LOW_FIXTURE, "LOW"), (MODERATE_FIXTURE, "MODERATE"), (HIGH_FIXTURE, "HIGH"),
])
def test_shap_matches_xgboost_contributions(features, label):
    result = score_event(features)
    expected_label, contribs = xgb_contributions(features)

    # Labels are unchanged by the fix
    assert result["severity_label"] == expected_label == label
    assert result["shap_status"] == "ok"
    assert len(result["shap_values"]) == 5
    for feature, value in result["shap_values"].items():
        assert feature in FEATURE_COLUMNS
        assert value == pytest.approx(float(contribs[feature]), abs=1e-5)

    top5 = sorted(contribs, key=lambda f: abs(contribs[f]), reverse=True)[:5]
    assert set(result["shap_values"]) == set(top5)


def test_shap_failure_is_reported_not_hidden(monkeypatch, caplog):
    scorer.load_models()

    class BrokenExplainer:
        def shap_values(self, X):
            raise RuntimeError("boom")

    monkeypatch.setattr(scorer, "explainer", BrokenExplainer())
    with caplog.at_level(logging.ERROR, logger=scorer.__name__):
        result = score_event(MODERATE_FIXTURE)
    assert result["severity_label"] == "MODERATE"
    assert result["shap_status"] == "error"
    assert result["shap_values"] == {}
    assert "boom" in caplog.text


def test_class_contributions_shapes():
    n = len(FEATURE_COLUMNS)
    per_class = [np.full((1, n), float(c)) for c in range(3)]
    stacked = np.stack(per_class, axis=-1)  # (1, n, 3)

    for c in range(3):
        assert np.all(class_contributions(per_class, c) == c)
        assert np.all(class_contributions(stacked, c) == c)
    assert class_contributions(np.ones((1, n)), 0).shape == (n,)

    with pytest.raises(ValueError):
        class_contributions(np.ones((1, n - 1, 3)), 0)

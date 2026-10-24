import pytest

pytest.importorskip("xgboost")
pytest.importorskip("shap")

import logging

import numpy as np
import pandas as pd
import shap
import xgboost as xgb

from backend.app.pipeline import scorer
from backend.app.pipeline.scorer import FEATURE_COLUMNS, LABEL_MAP, NOT_SCORED, class_contributions, score_event

pytestmark = pytest.mark.model

# The committed model predates the M2 contract and is refused (test_startup), so
# these tests use a small model trained here on the contract's features, with
# the label driven by wind_max_mph
LOW_FIXTURE = {"wind_max_mph": 40.0, "source_count": 1}
MODERATE_FIXTURE = {"wind_max_mph": 100.0}
HIGH_FIXTURE = {"wind_max_mph": 170.0, "wind_latest_mph": 160.0}


@pytest.fixture
def storm_model(monkeypatch):
    rng = np.random.default_rng(0)
    n = 300
    X = pd.DataFrame({c: rng.uniform(0, 1, n) for c in FEATURE_COLUMNS})
    X["wind_max_mph"] = rng.uniform(30, 180, n)
    X.loc[::7, "wind_trend_mph_per_day"] = np.nan  # the model sees missing values in training
    y = np.digitize(X["wind_max_mph"], [80, 130])
    model = xgb.XGBClassifier(n_estimators=20, max_depth=2, objective="multi:softprob", random_state=0)
    model.fit(X, y)
    monkeypatch.setattr(scorer, "model", model)
    monkeypatch.setattr(scorer, "explainer", shap.TreeExplainer(model))
    return model


def xgb_contributions(model, features):
    X = pd.DataFrame([features]).reindex(columns=FEATURE_COLUMNS).astype(float)
    pred = int(np.argmax(model.predict_proba(X)[0]))
    contribs = model.get_booster().predict(xgb.DMatrix(X), pred_contribs=True)
    return LABEL_MAP[pred], dict(zip(FEATURE_COLUMNS, contribs[0, pred, :-1]))


@pytest.mark.parametrize("features,label", [
    (LOW_FIXTURE, "LOW"), (MODERATE_FIXTURE, "MODERATE"), (HIGH_FIXTURE, "HIGH"),
])
def test_shap_matches_xgboost_contributions(storm_model, features, label):
    result = score_event(features)
    expected_label, contribs = xgb_contributions(storm_model, features)

    assert result["severity_label"] == expected_label == label
    assert result["shap_status"] == "ok"
    assert len(result["shap_values"]) == 5
    for feature, value in result["shap_values"].items():
        assert feature in FEATURE_COLUMNS
        assert value == pytest.approx(float(contribs[feature]), abs=1e-5)

    # Ties at zero may be ordered either way; every non-zero top-5 contribution is reported
    top5 = sorted(contribs, key=lambda f: abs(contribs[f]), reverse=True)[:5]
    assert {f for f in top5 if abs(contribs[f]) > 1e-6} <= set(result["shap_values"])


def test_shap_failure_is_reported_not_hidden(storm_model, monkeypatch, caplog):
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


def test_missing_features_stay_nan_and_are_reported(storm_model):
    result = score_event({"wind_max_mph": 100.0, "wind_trend_mph_per_day": None, "source_count": 2})
    assert "wind_trend_mph_per_day" in result["imputed_features"]
    assert "month" in result["imputed_features"]
    assert "wind_max_mph" not in result["imputed_features"]

    # None, NaN and an absent feature are treated alike, and nothing is imputed
    absent = score_event({"wind_max_mph": 100.0, "source_count": 2, "wind_trend_mph_per_day": float("nan")})
    assert absent["severity_score"] == pytest.approx(result["severity_score"])
    assert scorer.model.predict_proba(
        pd.DataFrame([{"wind_max_mph": 100.0, "source_count": 2}]).reindex(columns=FEATURE_COLUMNS).astype(float)
    )[0].max() == pytest.approx(result["severity_score"])
    assert not hasattr(scorer, "imputer")


def test_model_with_other_features_is_refused(storm_model):
    scorer.check_feature_names(storm_model)

    legacy = xgb.XGBClassifier(n_estimators=2, max_depth=1, objective="multi:softprob")
    legacy.fit(pd.DataFrame({"gdacs_alert_score": [0.0, 1.0, 2.0], "source_count": [1, 2, 3]}), [0, 1, 2])
    with pytest.raises(ValueError, match="do not match the feature contract"):
        scorer.check_feature_names(legacy)

    reordered = xgb.XGBClassifier(n_estimators=2, max_depth=1, objective="multi:softprob")
    reordered.fit(pd.DataFrame([[0.0] * len(FEATURE_COLUMNS)] * 3, columns=FEATURE_COLUMNS[::-1]), [0, 1, 2])
    with pytest.raises(ValueError):
        scorer.check_feature_names(reordered)


def test_no_prediction_without_features_or_model(monkeypatch):
    assert score_event(None) == NOT_SCORED
    monkeypatch.setattr(scorer, "model", None)
    monkeypatch.setattr(scorer, "load_models", lambda: None)
    assert score_event(MODERATE_FIXTURE)["shap_status"] == "not_scored"

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

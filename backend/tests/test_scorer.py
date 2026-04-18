import pytest
from backend.app.pipeline.scorer import score_event, load_models
from backend.app.pipeline.gemini import check_quota, increment_quota
from backend.app.db.database import get_db, execute_schema
import os
from datetime import date

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

def test_gemini_quota_guard():
    # Ensure DB is ready
    execute_schema()
    today = date.today().isoformat()
    
    # Reset/Clear quota for today if exists
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM gemini_calls WHERE call_date = ?", (today,))
    conn.commit()
    conn.close()
    
    # Test initial state
    assert check_quota() is True
    
    # Simulate 80 calls
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO gemini_calls (call_date, call_count) VALUES (?, 80)", (today,))
    conn.commit()
    conn.close()
    
    assert check_quota() is False
    
    # Clean up
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM gemini_calls WHERE call_date = ?", (today,))
    conn.commit()
    conn.close()

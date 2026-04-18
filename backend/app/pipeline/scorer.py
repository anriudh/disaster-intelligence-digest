import joblib
import pandas as pd
import numpy as np
import shap
import os
import json

# Load model and imputer once at module level
MODEL_PATH = "backend/models/severity_model.pkl"
IMPUTER_PATH = "backend/models/imputer.pkl"

model = None
imputer = None
explainer = None

def load_models():
    global model, imputer, explainer
    if model is None:
        try:
            model = joblib.load(MODEL_PATH)
            imputer = joblib.load(IMPUTER_PATH)
            explainer = shap.TreeExplainer(model)
        except Exception as e:
            print(f"Error loading models: {e}")

# Labels mapping
LABEL_MAP = {0: "LOW", 1: "MODERATE", 2: "HIGH"}

FEATURE_COLUMNS = [
    "event_category_encoded", "geometry_type_encoded", "source_count",
    "event_duration_days", "gdacs_alert_score", "gdacs_population_exposure",
    "acres_burned", "pct_contained", "wind_speed_mph", "storm_category",
    "volcano_alert_encoded", "persons_affected", "casualties",
    "ner_location_count", "ner_org_count", "month", "hemisphere"
]

def score_event(features_dict: dict):
    """
    Predicts severity and returns label, score, and SHAP values.
    """
    load_models()
    if model is None or imputer is None:
        return {"severity_label": "UNKNOWN", "severity_score": 0.0, "shap_values": {}}

    # Prepare DataFrame
    df = pd.DataFrame([features_dict])
    # Ensure all columns exist and are in order
    for col in FEATURE_COLUMNS:
        if col not in df.columns:
            df[col] = np.nan
    df = df[FEATURE_COLUMNS]

    # Impute
    X_imputed = pd.DataFrame(imputer.transform(df), columns=FEATURE_COLUMNS)

    # Predict
    probs = model.predict_proba(X_imputed)[0]
    pred_class = np.argmax(probs)
    severity_label = LABEL_MAP.get(pred_class, "UNKNOWN")
    severity_score = float(probs[pred_class])

    # SHAP values
    try:
        shap_vals = explainer.shap_values(X_imputed)
        # shap_vals for multi-class is a list of arrays (one per class)
        # We take the values for the predicted class
        class_shap_vals = shap_vals[pred_class][0]
        
        # Create dict of feature: importance and take top 5
        feat_importances = dict(zip(FEATURE_COLUMNS, [float(v) for v in class_shap_vals]))
        sorted_feats = sorted(feat_importances.items(), key=lambda x: abs(x[1]), reverse=True)
        top_shap = dict(sorted_feats[:5])
    except Exception as e:
        print(f"Error calculating SHAP values: {e}")
        top_shap = {}

    return {
        "severity_label": severity_label,
        "severity_score": severity_score,
        "shap_values": top_shap
    }

if __name__ == "__main__":
    # Test with dummy features
    dummy_features = {
        "event_category_encoded": 0,
        "gdacs_alert_score": 4.5,
        "source_count": 5
    }
    result = score_event(dummy_features)
    print(json.dumps(result, indent=2))

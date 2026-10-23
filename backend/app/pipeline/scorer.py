import joblib
import pandas as pd
import numpy as np
import shap
import os
import json
import logging

logger = logging.getLogger(__name__)

# Load model and imputer once at module level
MODELS_DIR = os.path.join(os.path.dirname(__file__), "../../models")
MODEL_PATH = os.path.join(MODELS_DIR, "severity_model.pkl")
IMPUTER_PATH = os.path.join(MODELS_DIR, "imputer.pkl")

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
            logger.error(f"Error loading models: {e}")

# Labels mapping
LABEL_MAP = {0: "LOW", 1: "MODERATE", 2: "HIGH"}

FEATURE_COLUMNS = [
    "event_category_encoded", "geometry_type_encoded", "source_count",
    "event_duration_days", "gdacs_alert_score", "gdacs_population_exposure",
    "acres_burned", "pct_contained", "wind_speed_mph", "storm_category",
    "volcano_alert_encoded", "persons_affected", "casualties",
    "ner_location_count", "ner_org_count", "month", "hemisphere"
]

def class_contributions(shap_vals, pred_class: int):
    """
    Returns the SHAP values of the first sample for one class, as a 1-D array.

    Depending on the shap version, multi-class output is either a list with one
    (n_samples, n_features) array per class, or a single array shaped
    (n_samples, n_features, n_classes).
    """
    if isinstance(shap_vals, list):
        values = np.asarray(shap_vals[pred_class])[0]
    else:
        shap_vals = np.asarray(shap_vals)
        if shap_vals.ndim == 3:
            values = shap_vals[0, :, pred_class]
        elif shap_vals.ndim == 2:
            values = shap_vals[0]
        else:
            raise ValueError(f"Unexpected SHAP output shape {shap_vals.shape}")
    if len(values) != len(FEATURE_COLUMNS):
        raise ValueError(f"Expected {len(FEATURE_COLUMNS)} SHAP values, got {len(values)}")
    return values

def score_event(features_dict: dict):
    """
    Predicts severity and returns label, score, and SHAP values.

    shap_status is "ok" when shap_values holds the top 5 contributions for the
    predicted class, "error" when they could not be computed.
    """
    load_models()
    if model is None or imputer is None:
        return {"severity_label": "UNKNOWN", "severity_score": 0.0, "shap_values": {}, "shap_status": "error",
                "imputed_features": []}

    # Prepare DataFrame. Missing features (absent or None) become NaN, which the
    # imputer fills with its training medians; imputed_features records which.
    df = pd.DataFrame([features_dict])
    # Ensure all columns exist and are in order
    for col in FEATURE_COLUMNS:
        if col not in df.columns:
            df[col] = np.nan
    df = df[FEATURE_COLUMNS].apply(pd.to_numeric).astype(float)
    imputed_features = [col for col in FEATURE_COLUMNS if pd.isna(df.at[0, col])]

    # Impute
    X_imputed = pd.DataFrame(imputer.transform(df), columns=FEATURE_COLUMNS)

    # Predict
    probs = model.predict_proba(X_imputed)[0]
    pred_class = int(np.argmax(probs))
    severity_label = LABEL_MAP.get(pred_class, "UNKNOWN")
    severity_score = float(probs[pred_class])

    # SHAP values
    try:
        class_shap_vals = class_contributions(explainer.shap_values(X_imputed), pred_class)

        # Create dict of feature: importance and take top 5
        feat_importances = dict(zip(FEATURE_COLUMNS, [float(v) for v in class_shap_vals]))
        sorted_feats = sorted(feat_importances.items(), key=lambda x: abs(x[1]), reverse=True)
        top_shap = dict(sorted_feats[:5])
        shap_status = "ok"
    except Exception as e:
        logger.error(f"Error calculating SHAP values: {e}")
        top_shap = {}
        shap_status = "error"

    return {
        "severity_label": severity_label,
        "severity_score": severity_score,
        "shap_values": top_shap,
        "shap_status": shap_status,
        "imputed_features": imputed_features
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

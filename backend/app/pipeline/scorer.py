import joblib
import pandas as pd
import numpy as np
import shap
import os
import json
import logging
from backend.app.pipeline.features import FEATURE_COLUMNS

logger = logging.getLogger(__name__)

# Load the model once at module level. There is no imputer: missing features
# reach the model as NaN (M2 contract).
MODELS_DIR = os.path.join(os.path.dirname(__file__), "../../models")
MODEL_PATH = os.path.join(MODELS_DIR, "severity_model.pkl")

model = None
explainer = None

def load_models():
    global model, explainer
    if model is None:
        try:
            loaded = joblib.load(MODEL_PATH)
            check_feature_names(loaded)
            model = loaded
            explainer = shap.TreeExplainer(model)
        except Exception as e:
            logger.error(f"Error loading models: {e}")

def check_feature_names(candidate):
    """Refuses a model not trained on FEATURE_COLUMNS, in this order."""
    names = list(getattr(candidate, "feature_names_in_", []))
    if names != FEATURE_COLUMNS:
        raise ValueError(f"Model features {names} do not match the feature contract {FEATURE_COLUMNS}")

# Labels mapping
LABEL_MAP = {0: "LOW", 1: "MODERATE", 2: "HIGH"}

# Returned when no prediction is made: a category that is not scored, or no usable model
NOT_SCORED = {"severity_label": "UNKNOWN", "severity_score": 0.0, "shap_values": {},
              "shap_status": "not_scored", "imputed_features": []}

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

def score_event(features_dict):
    """
    Predicts severity and returns label, score, and SHAP values. features_dict
    is None for a category that is not scored.

    shap_status is "ok" when shap_values holds the top 5 contributions for the
    predicted class, "error" when they could not be computed, and "not_scored"
    when no prediction was made.
    """
    if features_dict is None:
        return dict(NOT_SCORED)
    load_models()
    if model is None:
        return dict(NOT_SCORED)

    # Prepare DataFrame. Missing features (absent, None or NaN) stay NaN and are
    # handled natively by the model; imputed_features records which were missing
    # (the key predates M2 and is kept to avoid a migration).
    df = pd.DataFrame([features_dict])
    # Ensure all columns exist and are in order
    for col in FEATURE_COLUMNS:
        if col not in df.columns:
            df[col] = np.nan
    X = df[FEATURE_COLUMNS].apply(pd.to_numeric).astype(float)
    imputed_features = [col for col in FEATURE_COLUMNS if pd.isna(X.at[0, col])]

    # Predict
    probs = model.predict_proba(X)[0]
    pred_class = int(np.argmax(probs))
    severity_label = LABEL_MAP.get(pred_class, "UNKNOWN")
    severity_score = float(probs[pred_class])

    # SHAP values
    try:
        class_shap_vals = class_contributions(explainer.shap_values(X), pred_class)

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
        "wind_max_mph": 120.0,
        "source_count": 2,
        "month": 9
    }
    result = score_event(dummy_features)
    print(json.dumps(result, indent=2))

-- B3: SHAP values stored before the A2 fix used the wrong indexing. They are kept
-- (the model inputs were not stored, so they cannot be recomputed) but marked invalid.
UPDATE event_analysis SET shap_status = 'invalid_legacy_indexing' WHERE shap_status IS NULL;

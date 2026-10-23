-- matched / no_match / not_checked (legacy rows)
ALTER TABLE events ADD COLUMN gdacs_match_status TEXT;
-- JSON list of model features that were missing and filled by the imputer
ALTER TABLE event_analysis ADD COLUMN imputed_features TEXT;

-- When the event was last present in the EONET feed (ISO datetime, UTC)
ALTER TABLE events ADD COLUMN last_seen TEXT;
-- observed / not_observed / unknown_legacy
ALTER TABLE events ADD COLUMN observation_state TEXT;
-- Closure date as stated by the source, and which source stated it
ALTER TABLE events ADD COLUMN closed_at TEXT;
ALTER TABLE events ADD COLUMN closure_source TEXT;

-- A10: consecutive completed runs whose feed did not contain the event
ALTER TABLE events ADD COLUMN unseen_runs INTEGER NOT NULL DEFAULT 0;
-- When the event was last looked up by ID (ISO datetime, UTC)
ALTER TABLE events ADD COLUMN last_lookup_at TEXT;

-- One row per pipeline run, for health reporting
CREATE TABLE IF NOT EXISTS pipeline_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,             -- ISO datetime, UTC
    finished_at TEXT,
    status TEXT NOT NULL,                 -- running / success / partial / failed
    processed INTEGER DEFAULT 0,
    skipped INTEGER DEFAULT 0,
    failed INTEGER DEFAULT 0,
    error_message TEXT,                   -- last error of the run
    error_event_id TEXT,                  -- event that raised it, if any
    error_at TEXT
);

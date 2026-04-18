-- Core events table
CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,                  -- EONET event ID
    title TEXT NOT NULL,
    category TEXT NOT NULL,
    status TEXT DEFAULT 'open',           -- open / closed
    first_seen TEXT,                      -- ISO datetime
    last_updated TEXT,
    lat REAL,
    lon REAL,
    geometry_type TEXT,                   -- point / polygon
    source_count INTEGER DEFAULT 1,
    duration_days REAL DEFAULT 0
);

-- NLP and model output
CREATE TABLE IF NOT EXISTS event_analysis (
    event_id TEXT PRIMARY KEY REFERENCES events(id),
    raw_text TEXT,                        -- trafilatura output or fallback
    ner_entities TEXT,                    -- JSON: [(text, label), ...]
    regex_signals TEXT,                   -- JSON: {acres_burned: 5000, ...}
    keyphrases TEXT,                      -- JSON: [(phrase, score), ...]
    embedding TEXT,                       -- JSON: [float, ...] (384 dims)
    severity_label TEXT,                  -- LOW / MODERATE / HIGH
    severity_score REAL,
    shap_values TEXT,                     -- JSON: {feature: value, ...}
    gemini_digest TEXT,                   -- JSON: {what_happened, where, ...}
    nlp_summary TEXT,                     -- fallback for LOW events
    analysed_at TEXT
);

-- GDACS enrichment
CREATE TABLE IF NOT EXISTS gdacs_enrichment (
    event_id TEXT PRIMARY KEY REFERENCES events(id),
    gdacs_event_id TEXT,
    gdacs_alert_level TEXT,               -- Green / Orange / Red
    gdacs_alert_score REAL,
    population_exposure INTEGER,
    matched_at TEXT
);

-- Gemini quota tracker
CREATE TABLE IF NOT EXISTS gemini_calls (
    call_date TEXT PRIMARY KEY,           -- YYYY-MM-DD
    call_count INTEGER DEFAULT 0
);

-- Historical data for trend panel
CREATE TABLE IF NOT EXISTS event_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT,
    severity_label TEXT,
    event_date TEXT,
    lat REAL,
    lon REAL
);

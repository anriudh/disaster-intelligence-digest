# Disaster Intelligence Digest

An end-to-end AI/ML pipeline that ingests real-time natural disaster events from NASA's EONET API, enriches them with GDACS severity data, and generates structured AI digests.

## Features
- **Real-time Ingestion:** Fetches events from NASA EONET and correlates with GDACS.
- **NLP Pipeline:** Entity extraction (spaCy), signal detection (Regex), and keyphrases (KeyBERT).
- **Severity Scoring (withheld):** An XGBoost model scores each event, but it was trained on synthetic data and has not been validated, so its ratings and SHAP explanations are kept for diagnostics only and are not served by the API (`severity_status: "withheld_unvalidated_model"`). See `docs/audit/`.
- **AI Summaries (paused):** Structured digests by Gemini 2.5 Flash for MODERATE/HIGH events. Paused by default because they depend on the withheld rating; set `DIGEST_GENERATION_ENABLED=true` to resume.
- **Dashboard:** Interactive React map and analytics panel.

## Tech Stack
- **Backend:** FastAPI, SQLite, XGBoost, spaCy, KeyBERT, Sentence-Transformers, Google GenAI.
- **Frontend:** React, Vite, Tailwind CSS, Leaflet, Recharts.

## Setup Instructions

### Backend
Run every command from the repository root.

1. Clone the repository.
2. Create a virtual environment with Python 3.13: `python -m venv venv`
3. Activate venv: `source venv/bin/activate` (or `.\venv\Scripts\activate` on Windows)
4. Install dependencies: `pip install -r backend/requirements.txt -c backend/constraints.txt`
5. Download spaCy model: `python -m spacy download en_core_web_md`
6. Create `.env` in `backend/` from `backend/.env.example` and set `GEMINI_API_KEY`. Set `PIPELINE_TRIGGER_TOKEN` to enable `POST /api/pipeline/trigger`.
7. Seed the database: `python -m backend.scripts.seed_db`
8. Start the server: `uvicorn backend.app.main:app --port 8000`

Database migrations in `backend/app/db/migrations/` apply automatically at startup, after a backup of the database file (`*.db.bak-*`).

### Tests
1. Install test dependencies: `pip install -r backend/requirements-dev.txt -c backend/constraints.txt`
2. Run `pytest` from the repository root. Tests use a temporary database and never touch `backend/data/disaster_intel.db`.
3. `pytest -m model` runs the tests that need the NLP models and model artifacts; `pytest -m network` runs the ones that call live APIs.

### Frontend
1. Navigate to `frontend/`.
2. Install dependencies: `npm install`
3. Create `.env.local` with `VITE_API_BASE_URL=http://localhost:8000`.
4. Start dev server: `npm run dev`

## Notes
- The database is pre-seeded with recent events.
- The pipeline runs automatically every 20 minutes when the backend is active, one run at a time. The first run is 20 minutes after startup.
- `GET /api/health/live` reports that the process is up. `GET /api/health` reports pipeline freshness: `pending`, `ok`, or `degraded` when the last run failed or none completed in 45 minutes.
- `POST /api/pipeline/trigger` needs `Authorization: Bearer <PIPELINE_TRIGGER_TOKEN>` and is disabled when the token is not set. API reads are limited to 120 per minute and the trigger to 3 per hour, per client address as the server sees it.
- Gemini calls are capped at 80 attempts per day to protect free tier quotas.

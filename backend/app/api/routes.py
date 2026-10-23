from fastapi import APIRouter, Request, HTTPException
from backend.app.api.limits import limiter, READ_LIMIT, TRIGGER_LIMIT, require_pipeline_token
from backend.app.db.database import get_db
from backend.app.pipeline.orchestrator import start_pipeline_task
from datetime import date, datetime, timedelta, timezone
import json

router = APIRouter()

# The severity model has not been validated on real data (docs/audit/LEDGER.md),
# so its outputs stay in the database for diagnostics and are not served.
SEVERITY_STATUS = "withheld_unvalidated_model"
WITHHELD_FIELDS = ("severity_label", "severity_score", "shap_values", "shap_status", "imputed_features")
# Digest fields that restate the withheld rating
WITHHELD_DIGEST_FIELDS = ("severity_rationale",)

# Open events missing from the feed stay listed this long after they were last seen
UNOBSERVED_LISTING_DAYS = 30

@router.get("/events")
@limiter.limit(READ_LIMIT)
async def get_events(request: Request):
    conn = get_db()
    cursor = conn.cursor()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=UNOBSERVED_LISTING_DAYS)).isoformat(timespec="seconds")
    # 'null' is how digests that were never generated used to be stored.
    query = """
        SELECT e.*,
               (a.gemini_digest IS NOT NULL AND a.gemini_digest != 'null') as has_digest
        FROM events e
        LEFT JOIN event_analysis a ON e.id = a.event_id
        WHERE e.status = 'open'
          AND (e.observation_state IS NOT 'not_observed' OR e.last_seen >= ?)
    """
    cursor.execute(query, (cutoff,))
    rows = cursor.fetchall()
    conn.close()
    
    events = [dict(row, severity_status=SEVERITY_STATUS) for row in rows]
    return {"events": events}

@router.get("/events/{event_id}")
@limiter.limit(READ_LIMIT)
async def get_event_detail(request: Request, event_id: str):
    conn = get_db()
    cursor = conn.cursor()
    query = """
        SELECT e.*, a.*, g.gdacs_alert_level, g.gdacs_alert_score, g.population_exposure
        FROM events e
        LEFT JOIN event_analysis a ON e.id = a.event_id
        LEFT JOIN gdacs_enrichment g ON e.id = g.event_id
        WHERE e.id = ?
    """
    cursor.execute(query, (event_id,))
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        raise HTTPException(status_code=404, detail="Event not found")
    
    event = dict(row)
    for field in WITHHELD_FIELDS:
        event.pop(field, None)
    event["severity_status"] = SEVERITY_STATUS

    # Parse JSON fields
    for field in ["ner_entities", "regex_signals", "keyphrases", "gemini_digest"]:
        if event.get(field):
            event[field] = json.loads(event[field])
    if isinstance(event.get("gemini_digest"), dict):
        for field in WITHHELD_DIGEST_FIELDS:
            event["gemini_digest"].pop(field, None)
            
    return event

@router.get("/trends")
@limiter.limit(READ_LIMIT)
async def get_trends(request: Request):
    conn = get_db()
    cursor = conn.cursor()
    # Simple aggregation by category
    query = """
        SELECT category, COUNT(*) as count
        FROM events
        GROUP BY category
    """
    cursor.execute(query)
    rows = cursor.fetchall()
    category_trends = [dict(row) for row in rows]
    
    conn.close()
    return {
        "category_trends": category_trends,
        "severity_status": SEVERITY_STATUS
    }

@router.get("/health")
async def health():
    conn = get_db()
    cursor = conn.cursor()
    
    # Get last pipeline run (analysed_at from event_analysis)
    cursor.execute("SELECT MAX(analysed_at) FROM event_analysis")
    last_run = cursor.fetchone()[0]
    
    # Get gemini calls today
    today = date.today().isoformat()
    cursor.execute("SELECT call_count FROM gemini_calls WHERE call_date = ?", (today,))
    gemini_count = cursor.fetchone()
    gemini_count = gemini_count[0] if gemini_count else 0
    
    conn.close()
    
    return {
        "status": "healthy",
        "last_pipeline_run": last_run,
        "gemini_calls_today": gemini_count
    }

# The token is checked inside the rate-limited handler, so failed attempts count too
@router.post("/pipeline/trigger", status_code=202)
@limiter.limit(TRIGGER_LIMIT)
async def trigger_pipeline(request: Request):
    require_pipeline_token(request.headers.get("authorization"))
    # Run in background to avoid timeout
    if start_pipeline_task() is None:
        raise HTTPException(status_code=409, detail="A pipeline run is already in progress")
    return {"message": "Pipeline triggered"}

@router.get("/internal/events/{event_id}/diagnostics")
@limiter.limit(READ_LIMIT)
async def get_event_diagnostics(request: Request, event_id: str):
    """The withheld model outputs for one event, for operators only."""
    require_pipeline_token(request.headers.get("authorization"))
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT event_id, severity_label, severity_score, shap_values, shap_status, imputed_features, "
        "gemini_digest, scrape_source, scrape_quality, analysed_at FROM event_analysis WHERE event_id = ?",
        (event_id,)
    )
    row = cursor.fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="Event not found")

    diagnostics = dict(row)
    for field in ["shap_values", "imputed_features", "gemini_digest"]:
        if diagnostics.get(field):
            diagnostics[field] = json.loads(diagnostics[field])
    return diagnostics

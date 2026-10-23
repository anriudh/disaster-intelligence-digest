from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse
from backend.app.api.limits import limiter, READ_LIMIT, TRIGGER_LIMIT, require_pipeline_token
from backend.app.db.database import get_db
from backend.app.pipeline.orchestrator import start_pipeline_task, PIPELINE_INTERVAL_MINUTES, MISFIRE_GRACE_SECONDS
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

# Freshness thresholds from the schedule: no run has completed yet while the
# first scheduled run is still due, and data is stale after two missed runs.
PENDING_WINDOW = timedelta(minutes=PIPELINE_INTERVAL_MINUTES, seconds=MISFIRE_GRACE_SECONDS)
STALE_AFTER = timedelta(minutes=2 * PIPELINE_INTERVAL_MINUTES, seconds=MISFIRE_GRACE_SECONDS)
# Second precision, like the run timestamps it is compared with
PROCESS_STARTED_AT = datetime.now(timezone.utc).replace(microsecond=0)

def pipeline_status(last_finished, last_completed, completed_since_start, now, started_at):
    """
    Returns (status, reason) from pipeline_runs rows:
    last_finished is the latest finished run, last_completed the latest
    success or partial run. completed_since_start says whether this process
    has completed a run yet.
    """
    if not completed_since_start and now - started_at < PENDING_WINDOW:
        if last_finished is None or last_finished["status"] != "failed":
            return "pending", "waiting for the first scheduled run"
    if last_completed is None:
        return "degraded", "no pipeline run has completed"
    if last_finished["status"] == "failed":
        return "degraded", "the last pipeline run failed"
    if last_finished["status"] == "partial":
        return "degraded", "events failed in the last pipeline run"
    if now - datetime.fromisoformat(last_completed["finished_at"]) > STALE_AFTER:
        return "degraded", "no pipeline run has completed recently"
    return "ok", None

@router.get("/health/live")
async def liveness():
    """The process is up. Does not touch the database."""
    return {"status": "alive"}

@router.get("/health")
async def health():
    now = datetime.now(timezone.utc)
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM pipeline_runs WHERE status != 'running' ORDER BY started_at DESC, id DESC LIMIT 1"
        )
        last_finished = cursor.fetchone()
        cursor.execute(
            "SELECT * FROM pipeline_runs WHERE status IN ('success', 'partial') ORDER BY started_at DESC, id DESC LIMIT 1"
        )
        last_completed = cursor.fetchone()
        cursor.execute("SELECT * FROM pipeline_runs ORDER BY started_at DESC, id DESC LIMIT 1")
        last_run = cursor.fetchone()

        # Get gemini calls today
        today = date.today().isoformat()
        cursor.execute("SELECT call_count FROM gemini_calls WHERE call_date = ?", (today,))
        gemini_count = cursor.fetchone()
        gemini_count = gemini_count[0] if gemini_count else 0
        conn.close()
    except Exception as e:
        return JSONResponse(status_code=503, content={"status": "degraded", "reason": f"database unavailable: {e}"})

    completed_since_start = (
        last_completed is not None
        and datetime.fromisoformat(last_completed["started_at"]) >= PROCESS_STARTED_AT
    )
    status, reason = pipeline_status(last_finished, last_completed, completed_since_start, now, PROCESS_STARTED_AT)
    last_error = None
    if last_finished is not None and last_finished["error_message"]:
        last_error = {
            "at": last_finished["error_at"],
            "message": last_finished["error_message"],
            "event_id": last_finished["error_event_id"],
        }
    return {
        "status": status,
        "reason": reason,
        "last_run_started": last_run["started_at"] if last_run else None,
        "last_run_finished": last_finished["finished_at"] if last_finished else None,
        "last_run_status": last_finished["status"] if last_finished else None,
        "last_successful_run": last_completed["finished_at"] if last_completed else None,
        "last_error": last_error,
        "counts": {k: last_finished[k] for k in ("processed", "skipped", "failed")} if last_finished else None,
        "stale_after_minutes": int(STALE_AFTER.total_seconds() // 60),
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

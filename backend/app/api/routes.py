from fastapi import APIRouter, Request, HTTPException
from backend.app.db.database import get_db
from backend.app.pipeline.orchestrator import run_pipeline
from datetime import date
import json
import asyncio

router = APIRouter()

@router.get("/events")
async def get_events():
    conn = get_db()
    cursor = conn.cursor()
    # Join events with event_analysis to get severity_label
    query = """
        SELECT e.*, a.severity_label, a.severity_score, 
               (a.gemini_digest IS NOT NULL) as has_digest
        FROM events e
        LEFT JOIN event_analysis a ON e.id = a.event_id
        WHERE e.status = 'open'
    """
    cursor.execute(query)
    rows = cursor.fetchall()
    conn.close()
    
    events = [dict(row) for row in rows]
    return {"events": events}

@router.get("/events/{event_id}")
async def get_event_detail(event_id: str):
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
    # Parse JSON fields
    for field in ["ner_entities", "regex_signals", "keyphrases", "shap_values", "gemini_digest"]:
        if event.get(field):
            event[field] = json.loads(event[field])
            
    return event

@router.get("/trends")
async def get_trends():
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
    
    # Severity distribution
    query = """
        SELECT severity_label, COUNT(*) as count
        FROM event_analysis
        GROUP BY severity_label
    """
    cursor.execute(query)
    rows = cursor.fetchall()
    severity_trends = [dict(row) for row in rows]
    
    conn.close()
    return {
        "category_trends": category_trends,
        "severity_trends": severity_trends
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

@router.post("/pipeline/trigger")
async def trigger_pipeline():
    # Run in background to avoid timeout
    asyncio.create_task(run_pipeline())
    return {"message": "Pipeline triggered"}

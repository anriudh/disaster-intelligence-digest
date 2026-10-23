import asyncio
from datetime import datetime, timezone
import json
import logging
from backend.app.pipeline.ingest import run_ingestion, event_timeline, point_of, parse_date
from backend.app.pipeline.scraper import scrape_event_sources
from backend.app.pipeline.nlp import run_nlp_pipeline
from backend.app.pipeline.embeddings import get_embeddings
from backend.app.pipeline.scorer import score_event
from backend.app.pipeline.gemini import generate_digest, digests_enabled
from backend.app.db.database import get_db

logger = logging.getLogger(__name__)

def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def optional_number(value, cast):
    return None if value is None else cast(value)

async def process_event(cursor, eonet: dict, gdacs, now: str) -> str:
    """
    Analyses and saves one EONET event. Returns "processed", or "skipped" when
    its latest observation is already stored (it is still marked as seen).
    """
    event_id = eonet["id"]
    first_seen, last_updated, latest = event_timeline(eonet)

    # Check if event already analysed and updated
    cursor.execute("SELECT last_updated FROM events WHERE id = ?", (event_id,))
    row = cursor.fetchone()
    if row and row[0] == last_updated:
        cursor.execute(
            "UPDATE events SET last_seen = ?, observation_state = 'observed' WHERE id = ?",
            (now, event_id)
        )
        return "skipped"

    logger.info(f"Processing event: {event_id} - {eonet['title']}")
    lat, lon = point_of(latest)

    # 2. Scrape
    scraping_result = await scrape_event_sources(eonet)
    raw_text = scraping_result["text"]

    # 3. NLP
    nlp_results = run_nlp_pipeline(raw_text)

    # 4. Embeddings (on description as per PRD)
    description = eonet.get("description") or eonet.get("title", "")
    embeddings = get_embeddings(description)

    # 5. Prepare features for Scorer
    # Mapping EONET categories to encoded values
    from backend.scripts.train_model import CATEGORY_ENCODING
    cat_name = eonet["categories"][0]["title"]

    gdacs_props = gdacs.get("properties", {}) if gdacs else {}

    features = {
        "event_category_encoded": CATEGORY_ENCODING.get(cat_name, 0),
        "geometry_type_encoded": 1 if latest["type"] == "Polygon" else 0,
        "source_count": len(eonet["sources"]),
        "event_duration_days": 0.0, # Placeholder
        # None when there is no GDACS match; never a -1 sentinel
        "gdacs_alert_score": optional_number(gdacs_props.get("alertscore"), float),
        "gdacs_population_exposure": optional_number(gdacs_props.get("population"), int),
        "ner_location_count": len([e for e in nlp_results["entities"] if e[1] in ("GPE", "LOC")]),
        "ner_org_count": len([e for e in nlp_results["entities"] if e[1] == "ORG"]),
        "month": parse_date(last_updated).month,
        "hemisphere": 0 if lat > 0 else 1
    }
    # Add regex signals to features
    features.update(nlp_results["signals"])

    # 6. Score
    scoring_result = score_event(features)

    # 7. Gemini (MODERATE or HIGH, while digests are enabled)
    gemini_digest = None
    if digests_enabled() and scoring_result["severity_label"] in ("MODERATE", "HIGH"):
        event_data_for_gemini = {
            "title": eonet["title"],
            "category": cat_name,
            "ner_entities": nlp_results["entities"],
            "severity_label": scoring_result["severity_label"],
            "severity_score": scoring_result["severity_score"],
            "regex_signals": nlp_results["signals"],
            "keyphrases": nlp_results["keyphrases"],
            "raw_text": raw_text
        }
        gemini_digest = await generate_digest(event_data_for_gemini)

    # 8. Save to SQLite
    # Status and closure come only from the source's own "closed" field
    closed_at = eonet.get("closed")
    cursor.execute(
        "INSERT INTO events (id, title, category, status, first_seen, last_updated, lat, lon, geometry_type, "
        "source_count, closed_at, closure_source, last_seen, observation_state, gdacs_match_status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'observed', ?) "
        "ON CONFLICT(id) DO UPDATE SET title=excluded.title, status=excluded.status, "
        "first_seen=MIN(COALESCE(events.first_seen, excluded.first_seen), excluded.first_seen), "
        "last_updated=excluded.last_updated, lat=excluded.lat, lon=excluded.lon, "
        "geometry_type=excluded.geometry_type, source_count=excluded.source_count, "
        "closed_at=excluded.closed_at, closure_source=excluded.closure_source, "
        "last_seen=excluded.last_seen, observation_state=excluded.observation_state, "
        "gdacs_match_status=excluded.gdacs_match_status",
        (
            event_id, eonet["title"], cat_name, 'open' if closed_at is None else 'closed',
            first_seen, last_updated, lat, lon, latest["type"], len(eonet["sources"]),
            closed_at, None if closed_at is None else "eonet_closed_field", now,
            "matched" if gdacs else "no_match"
        )
    )

    # Save analysis. A digest that was not generated this time is stored as NULL,
    # and never overwrites one generated earlier.
    cursor.execute(
        "INSERT INTO event_analysis (event_id, raw_text, scrape_source, scrape_quality, ner_entities, regex_signals, keyphrases, embedding, "
        "severity_label, severity_score, shap_values, shap_status, imputed_features, gemini_digest, nlp_summary, analysed_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(event_id) DO UPDATE SET raw_text=excluded.raw_text, scrape_source=excluded.scrape_source, "
        "scrape_quality=excluded.scrape_quality, ner_entities=excluded.ner_entities, "
        "regex_signals=excluded.regex_signals, keyphrases=excluded.keyphrases, embedding=excluded.embedding, "
        "severity_label=excluded.severity_label, severity_score=excluded.severity_score, "
        "shap_values=excluded.shap_values, shap_status=excluded.shap_status, imputed_features=excluded.imputed_features, "
        "gemini_digest=COALESCE(excluded.gemini_digest, event_analysis.gemini_digest), "
        "nlp_summary=excluded.nlp_summary, analysed_at=excluded.analysed_at",
        (
            event_id, raw_text, scraping_result["source"], scraping_result["quality"],
            json.dumps(nlp_results["entities"]), json.dumps(nlp_results["signals"]),
            json.dumps(nlp_results["keyphrases"]), json.dumps(embeddings),
            scoring_result["severity_label"], scoring_result["severity_score"],
            json.dumps(scoring_result["shap_values"]), scoring_result["shap_status"],
            json.dumps(scoring_result["imputed_features"]),
            json.dumps(gemini_digest) if gemini_digest is not None else None,
            ", ".join([k[0] for k in nlp_results["keyphrases"][:3]]), # simple fallback summary
            now
        )
    )

    # Save GDACS enrichment
    if gdacs:
        cursor.execute(
            "INSERT INTO gdacs_enrichment (event_id, gdacs_event_id, gdacs_alert_level, gdacs_alert_score, population_exposure, matched_at) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(event_id) DO UPDATE SET gdacs_alert_level=excluded.gdacs_alert_level, "
            "gdacs_alert_score=excluded.gdacs_alert_score, population_exposure=excluded.population_exposure",
            (
                event_id, str(gdacs_props.get("eventid")), gdacs_props.get("alertlevel"),
                optional_number(gdacs_props.get("alertscore"), float),
                optional_number(gdacs_props.get("population"), int),
                now
            )
        )
    return "processed"

def mark_unobserved(cursor, seen_ids, now: str):
    """
    Open events missing from this run's feed are marked not_observed, never
    closed: the feed is truncated at 100 events, so absence proves nothing.
    """
    placeholders = ", ".join("?" for _ in seen_ids)
    exclude = f"AND id NOT IN ({placeholders})" if seen_ids else ""
    cursor.execute(
        f"UPDATE events SET observation_state = 'not_observed' WHERE status = 'open' {exclude}",
        list(seen_ids)
    )

# One run at a time, shared by the scheduler and the manual trigger. The app runs
# a single process (render.yaml), so an in-process flag is enough; several
# workers would need a lock in the database instead.
_run_active = False
_background_tasks = set()

def try_claim_run() -> bool:
    global _run_active
    if _run_active:
        return False
    _run_active = True
    return True

def release_run():
    global _run_active
    _run_active = False

def run_in_progress() -> bool:
    return _run_active

async def run_pipeline():
    """Runs the pipeline unless a run is already in progress (then returns None)."""
    if not try_claim_run():
        logger.warning("Pipeline run skipped: another run is in progress.")
        return None
    try:
        return await _execute_run()
    finally:
        release_run()

def start_pipeline_task():
    """
    Claims a run and starts it in the background. Returns the task, or None if
    a run is already in progress. The claim is taken before this returns, so a
    second caller is refused even before the first task has started.
    """
    if not try_claim_run():
        return None

    async def run_and_release():
        try:
            return await _execute_run()
        finally:
            release_run()

    task = asyncio.create_task(run_and_release())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task

async def _execute_run():
    """
    Orchestrates the full pipeline: Ingest -> Scrape -> NLP -> Score -> Gemini -> SQLite
    """
    logger.info("Starting pipeline run...")

    try:
        # 1. Ingest
        ingested_events = await run_ingestion()
        logger.info(f"Ingested {len(ingested_events)} events.")

        conn = get_db()
        cursor = conn.cursor()
        now = utc_now()

        for item in ingested_events:
            await process_event(cursor, item["eonet"], item["gdacs"], now)
            conn.commit()

        mark_unobserved(cursor, [item["eonet"]["id"] for item in ingested_events], now)
        conn.commit()
        conn.close()
        logger.info("Pipeline run completed successfully.")
        return True
    except Exception as e:
        logger.error(f"Pipeline run failed: {e}")
        return False

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_pipeline())

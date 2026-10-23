import asyncio
from datetime import datetime, date
import json
import logging
from backend.app.pipeline.ingest import run_ingestion
from backend.app.pipeline.scraper import scrape_event_sources
from backend.app.pipeline.nlp import run_nlp_pipeline
from backend.app.pipeline.embeddings import get_embeddings
from backend.app.pipeline.scorer import score_event
from backend.app.pipeline.gemini import generate_digest
from backend.app.db.database import get_db

logger = logging.getLogger(__name__)

async def run_pipeline():
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
        
        for item in ingested_events:
            eonet = item["eonet"]
            gdacs = item["gdacs"]
            
            event_id = eonet["id"]
            
            # Check if event already analysed and updated
            cursor.execute("SELECT last_updated FROM events WHERE id = ?", (event_id,))
            row = cursor.fetchone()
            eonet_last_updated = eonet["geometry"][0]["date"]
            
            if row and row[0] == eonet_last_updated:
                # logger.info(f"Event {event_id} already up to date. Skipping.")
                continue
                
            logger.info(f"Processing event: {event_id} - {eonet['title']}")
            
            # 2. Scrape
            scraping_result = await scrape_event_sources(eonet)
            raw_text = scraping_result["text"]
            
            # 3. NLP
            nlp_results = run_nlp_pipeline(raw_text)
            
            # 4. Embeddings (on description as per PRD)
            description = eonet.get("description", "") or eonet.get("title", "")
            embeddings = get_embeddings(description)
            
            # 5. Prepare features for Scorer
            # Mapping EONET categories to encoded values
            from backend.scripts.train_model import CATEGORY_ENCODING
            cat_name = eonet["categories"][0]["title"]
            
            gdacs_props = gdacs.get("properties", {}) if gdacs else {}
            
            features = {
                "event_category_encoded": CATEGORY_ENCODING.get(cat_name, 0),
                "geometry_type_encoded": 1 if eonet["geometry"][0]["type"] == "Polygon" else 0,
                "source_count": len(eonet["sources"]),
                "event_duration_days": 0.0, # Placeholder
                "gdacs_alert_score": float(gdacs_props.get("alertscore", -1.0)),
                "gdacs_population_exposure": int(gdacs_props.get("population", -1)),
                "ner_location_count": len([e for e in nlp_results["entities"] if e[1] in ("GPE", "LOC")]),
                "ner_org_count": len([e for e in nlp_results["entities"] if e[1] == "ORG"]),
                "month": datetime.fromisoformat(eonet_last_updated.replace("Z", "+00:00")).month,
                "hemisphere": 0 if eonet["geometry"][0]["coordinates"][1] > 0 else 1
            }
            # Add regex signals to features
            features.update(nlp_results["signals"])
            
            # 6. Score
            scoring_result = score_event(features)
            
            # 7. Gemini (MODERATE or HIGH)
            gemini_digest = None
            if scoring_result["severity_label"] in ("MODERATE", "HIGH"):
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
            # Save core event
            cursor.execute(
                "INSERT INTO events (id, title, category, status, first_seen, last_updated, lat, lon, geometry_type, source_count) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET last_updated=excluded.last_updated, source_count=excluded.source_count",
                (
                    event_id, eonet["title"], cat_name, 'open' if eonet.get('closed') is None else 'closed', 
                    eonet["geometry"][-1]["date"], eonet_last_updated,
                    eonet["geometry"][0]["coordinates"][1], eonet["geometry"][0]["coordinates"][0],
                    eonet["geometry"][0]["type"], len(eonet["sources"])
                )
            )
            
            # Save analysis
            cursor.execute(
                "INSERT INTO event_analysis (event_id, raw_text, scrape_source, scrape_quality, ner_entities, regex_signals, keyphrases, embedding, "
                "severity_label, severity_score, shap_values, shap_status, gemini_digest, nlp_summary, analysed_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(event_id) DO UPDATE SET raw_text=excluded.raw_text, scrape_source=excluded.scrape_source, "
                "scrape_quality=excluded.scrape_quality, ner_entities=excluded.ner_entities, "
                "regex_signals=excluded.regex_signals, keyphrases=excluded.keyphrases, embedding=excluded.embedding, "
                "severity_label=excluded.severity_label, severity_score=excluded.severity_score, "
                "shap_values=excluded.shap_values, shap_status=excluded.shap_status, gemini_digest=excluded.gemini_digest, analysed_at=excluded.analysed_at",
                (
                    event_id, raw_text, scraping_result["source"], scraping_result["quality"],
                    json.dumps(nlp_results["entities"]), json.dumps(nlp_results["signals"]),
                    json.dumps(nlp_results["keyphrases"]), json.dumps(embeddings),
                    scoring_result["severity_label"], scoring_result["severity_score"],
                    json.dumps(scoring_result["shap_values"]), scoring_result["shap_status"], json.dumps(gemini_digest),
                    ", ".join([k[0] for k in nlp_results["keyphrases"][:3]]), # simple fallback summary
                    datetime.now().isoformat()
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
                        float(gdacs_props.get("alertscore", 0)),
                        int(gdacs_props.get("population", -1)),
                        datetime.now().isoformat()
                    )
                )
            
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

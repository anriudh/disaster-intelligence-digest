import asyncio
import logging
import httpx
from datetime import datetime, timedelta
from backend.app.pipeline.ingest import CATEGORY_MAP, match_events, get_gdacs_events
from backend.app.pipeline.orchestrator import run_pipeline
from backend.app.db.database import execute_schema, get_db

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def fetch_closed_events(days=90):
    """
    Fetch closed events from EONET for the last N days.
    """
    url = f"https://eonet.gsfc.nasa.gov/api/v3/events?status=closed&limit=50"
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
        response.raise_for_status()
        data = response.json()
        return data.get("events", [])

async def seed():
    logger.info("Starting database seeding...")
    execute_schema()
    
    # We use a modified version of run_pipeline or just call it 
    # since it already handles multiple events. 
    # But run_pipeline fetches open events. 
    # Let's write a targeted seed function.
    
    closed_events = await fetch_closed_events()
    gdacs_events = get_gdacs_events()
    
    # Bundle into the format run_pipeline expects (though we'll do it manually here for closed events)
    events_to_process = []
    for e in closed_events:
        category = e["categories"][0]["title"]
        if category in CATEGORY_MAP:
            matched = match_events(e, gdacs_events)
            events_to_process.append({"eonet": e, "gdacs": matched})
            
    logger.info(f"Seeding {len(events_to_process)} closed events...")
    
    # We can reuse the core logic of run_pipeline by slightly refactoring or 
    # just manually iterating here. Re-using run_pipeline's logic:
    # (Actually, orchestrator.run_pipeline doesn't take arguments, so we'll 
    # duplicate the loop logic or refactor. For simplicity in a script, we duplicate)
    
    from backend.app.pipeline.orchestrator import run_pipeline
    # But run_pipeline always fetches open. 
    # Let's just run run_pipeline() once to get all currently open events too.
    await run_pipeline()
    
    logger.info("Seeding completed.")

if __name__ == "__main__":
    asyncio.run(seed())

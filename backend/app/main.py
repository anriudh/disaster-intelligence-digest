import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from backend.app.api.routes import router
from backend.app.db.database import execute_schema
from backend.app.pipeline.orchestrator import run_pipeline
from backend.app.pipeline.scorer import load_models
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

limiter = Limiter(key_func=get_remote_address)
app = FastAPI(title="Disaster Intelligence Digest")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        os.getenv("FRONTEND_URL", "http://localhost:5173")
    ],
    allow_methods=["GET", "POST"],
    allow_headers=["*"]
)

# Scheduler
scheduler = AsyncIOScheduler()

@app.on_event("startup")
async def startup():
    logger.info("Starting up FastAPI application...")
    execute_schema()
    load_models()
    
    # Schedule pipeline to run every 20 minutes
    scheduler.add_job(
        run_pipeline,
        trigger=IntervalTrigger(minutes=20),
        id="main_pipeline",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300
    )
    scheduler.start()
    logger.info("Scheduler started.")

@app.on_event("shutdown")
async def shutdown():
    logger.info("Shutting down application...")
    scheduler.shutdown()

# Include routes
app.include_router(router, prefix="/api")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

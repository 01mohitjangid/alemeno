"""FastAPI application entrypoint.

Step 1 exposes a root and a health endpoint (with a live DB check). The job
endpoints are mounted here in Step 2.
"""
from __future__ import annotations

from fastapi import Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.routes import jobs
from app.database import get_db

app = FastAPI(
    title="AI-Powered Transaction Processing Pipeline",
    description=(
        "Upload a raw transactions CSV, process it asynchronously through a job "
        "queue (clean -> detect anomalies -> LLM classify -> summarise), and poll "
        "for structured results."
    ),
    version="0.2.0",
)

app.include_router(jobs.router)


@app.get("/", tags=["meta"])
def root() -> dict:
    return {"service": "transaction-pipeline", "status": "ok", "docs": "/docs"}


@app.get("/health", tags=["meta"])
def health(db: Session = Depends(get_db)) -> dict:
    """Liveness + DB connectivity probe."""
    db.execute(text("SELECT 1"))
    return {"status": "healthy", "database": "connected"}

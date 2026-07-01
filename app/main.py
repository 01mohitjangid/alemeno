"""FastAPI application entrypoint.

Exposes the job API (app/api/routes/jobs.py), a health probe, and serves a
lightweight static dashboard at /ui (with / redirecting to it).
"""
from __future__ import annotations

from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
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
    version="0.3.0",
)

app.include_router(jobs.router)


@app.get("/health", tags=["meta"])
def health(db: Session = Depends(get_db)) -> dict:
    """Liveness + DB connectivity probe."""
    db.execute(text("SELECT 1"))
    return {"status": "healthy", "database": "connected"}


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    """Send the browser to the dashboard."""
    return RedirectResponse(url="/ui/")


# Static dashboard (single-page, no build step). Mounted last so it never
# shadows the API routes above.
_STATIC_DIR = Path(__file__).parent / "static"
app.mount("/ui", StaticFiles(directory=str(_STATIC_DIR), html=True), name="ui")

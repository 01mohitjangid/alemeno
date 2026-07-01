"""Celery tasks for the transaction-processing pipeline.

`process_job` owns the job lifecycle (pending -> processing -> completed/failed)
and error handling; the actual work lives in app.services.pipeline.run_pipeline.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from app.celery_app import celery_app
from app.database import SessionLocal
from app.models import Job, JobStatus
from app.services.pipeline import run_pipeline

logger = logging.getLogger(__name__)


@celery_app.task(name="tasks.ping")
def ping() -> str:
    """Health-check task used to verify the worker <-> broker round-trip."""
    return "pong"


@celery_app.task(bind=True, name="tasks.process_job", max_retries=0)
def process_job(self, job_id: str) -> dict:
    """Process an uploaded CSV job end-to-end.

    Job-level failures are captured on the Job row (status=failed,
    error_message) rather than crashing silently. LLM-batch retries are handled
    inside the pipeline (Step 4), so this task does not retry the whole job.
    """
    db = SessionLocal()
    try:
        job = db.get(Job, uuid.UUID(job_id))
        if job is None:
            logger.error("process_job: job %s not found", job_id)
            return {"job_id": job_id, "status": "not_found"}

        job.status = JobStatus.processing.value
        db.commit()
        logger.info("Job %s: processing started", job_id)

        run_pipeline(job, db)

        job.status = JobStatus.completed.value
        job.completed_at = datetime.now(timezone.utc)
        db.commit()
        logger.info("Job %s: completed", job_id)
        return {"job_id": job_id, "status": job.status}

    except Exception as exc:  # noqa: BLE001 - record failure on the job, don't lose it
        logger.exception("Job %s: failed", job_id)
        db.rollback()
        job = db.get(Job, uuid.UUID(job_id))
        if job is not None:
            job.status = JobStatus.failed.value
            job.error_message = str(exc)[:2000]
            job.completed_at = datetime.now(timezone.utc)
            db.commit()
        return {"job_id": job_id, "status": "failed", "error": str(exc)[:500]}
    finally:
        db.close()

"""Processing pipeline orchestration.

The Celery `process_job` task delegates the actual work here. Step 2 wires the
lifecycle (read the CSV, record row counts); Step 3 adds cleaning + anomaly
detection + persistence, and Step 4 adds LLM classification + narrative summary.
"""
from __future__ import annotations

import logging

import pandas as pd
from sqlalchemy.orm import Session

from app.models import Job
from app.services.storage import csv_path_for

logger = logging.getLogger(__name__)


def run_pipeline(job: Job, db: Session) -> None:
    """Execute the full pipeline for a job (mutates rows, commits progress).

    Step 2: load the uploaded CSV and record the raw row count.
    (Cleaning, anomaly detection, LLM stages are added in Steps 3 & 4.)
    """
    path = csv_path_for(job.id)
    if not path.exists():
        raise FileNotFoundError(f"Uploaded CSV not found for job {job.id}: {path}")

    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    job.row_count_raw = len(df)
    db.commit()
    logger.info("Job %s: loaded %d raw rows", job.id, len(df))

    # --- Step 3 will add here: clean -> dedupe -> anomaly detect -> persist ---
    # --- Step 4 will add here: LLM classify batches -> narrative JobSummary ---

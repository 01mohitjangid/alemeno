"""Processing pipeline orchestration.

The Celery `process_job` task delegates the work here:
  Step 3: load CSV -> clean -> detect anomalies -> persist Transaction rows.
  Step 4 will add: LLM classification of uncategorised rows + narrative summary.
"""
from __future__ import annotations

import logging

import pandas as pd
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.models import Job, Transaction
from app.services.anomaly import detect_anomalies
from app.services.cleaning import clean_records
from app.services.storage import csv_path_for

logger = logging.getLogger(__name__)


def run_pipeline(job: Job, db: Session) -> None:
    """Execute the cleaning + anomaly-detection pipeline for a job."""
    path = csv_path_for(job.id)
    if not path.exists():
        raise FileNotFoundError(f"Uploaded CSV not found for job {job.id}: {path}")

    # keep_default_na=False -> blank cells become "" (not NaN), so cleaning is
    # explicit; dtype=str -> no silent numeric/date coercion by pandas.
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    job.row_count_raw = len(df)

    # --- §5a clean + dedupe ---
    records, clean_count = clean_records(df)

    # --- §5b anomaly detection (mutates records in place) ---
    anomaly_count = detect_anomalies(records)

    # --- persist (idempotent: clear any prior rows for a re-run) ---
    db.execute(delete(Transaction).where(Transaction.job_id == job.id))
    db.add_all(Transaction(job_id=job.id, **rec) for rec in records)
    job.row_count_clean = clean_count
    db.commit()

    logger.info(
        "Job %s: cleaned %d -> %d rows (%d duplicates removed), %d anomalies",
        job.id,
        len(df),
        clean_count,
        len(df) - clean_count,
        anomaly_count,
    )

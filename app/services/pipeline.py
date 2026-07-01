"""Processing pipeline orchestration.

The Celery `process_job` task delegates the work here:
  §5a clean -> §5b detect anomalies -> persist -> §5c LLM classify -> §5d summary.

LLM failures (§5e) are contained: a failed batch is marked `llm_failed` and the
pipeline continues; the job is never failed because of the LLM.
"""
from __future__ import annotations

import logging
from collections import defaultdict

import pandas as pd
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Job, JobSummary, Transaction
from app.services.anomaly import detect_anomalies
from app.services.cleaning import UNCATEGORISED, clean_records
from app.services.llm import LLMError, classify_transactions, generate_narrative
from app.services.storage import csv_path_for

logger = logging.getLogger(__name__)


def run_pipeline(job: Job, db: Session) -> None:
    """Execute the full pipeline for a job."""
    path = csv_path_for(job.id)
    if not path.exists():
        raise FileNotFoundError(f"Uploaded CSV not found for job {job.id}: {path}")

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
        "Job %s: cleaned %d -> %d rows (%d duplicates), %d anomalies",
        job.id, len(df), clean_count, len(df) - clean_count, anomaly_count,
    )

    # --- §5c LLM classification of uncategorised rows ---
    _classify_uncategorised(job, db)

    # --- §5d narrative summary ---
    _build_summary(job, db)


def _classify_uncategorised(job: Job, db: Session) -> None:
    """Batch-classify transactions whose category is 'Uncategorised'."""
    rows = list(
        db.scalars(
            select(Transaction).where(
                Transaction.job_id == job.id,
                Transaction.category == UNCATEGORISED,
            )
        )
    )
    if not rows:
        return

    if not settings.llm_enabled:
        logger.warning("Job %s: LLM disabled (no API key); %d rows left unclassified",
                       job.id, len(rows))
        for r in rows:
            r.llm_failed = True
        db.commit()
        return

    batch_size = max(1, settings.llm_batch_size)
    for start in range(0, len(rows), batch_size):
        batch = rows[start : start + batch_size]
        items = [
            {"index": i, "merchant": r.merchant or "", "notes": r.notes or ""}
            for i, r in enumerate(batch)
        ]
        try:
            mapping, raw = classify_transactions(items)
        except LLMError as exc:
            # §5e: mark this batch failed and continue; do not fail the job.
            logger.warning("Job %s: classification batch failed: %s", job.id, exc)
            for r in batch:
                r.llm_failed = True
            db.commit()
            continue

        for i, r in enumerate(batch):
            r.llm_category = mapping.get(i, "Other")
            r.llm_raw_response = raw[:5000]
            r.llm_failed = False
        db.commit()
        logger.info("Job %s: classified batch of %d rows", job.id, len(batch))


def _heuristic_risk(anomaly_count: int, total: int) -> str:
    """Deterministic fallback risk level when the LLM is unavailable."""
    if total == 0:
        return "low"
    ratio = anomaly_count / total
    if anomaly_count >= 5 or ratio > 0.10:
        return "high"
    if anomaly_count >= 1 or ratio > 0.03:
        return "medium"
    return "low"


def _build_summary(job: Job, db: Session) -> None:
    """Compute factual stats, get an LLM narrative, store a JobSummary."""
    rows = list(db.scalars(select(Transaction).where(Transaction.job_id == job.id)))

    total_inr = sum(float(r.amount) for r in rows if r.amount and r.currency == "INR")
    total_usd = sum(float(r.amount) for r in rows if r.amount and r.currency == "USD")

    merch: dict[str, list] = defaultdict(lambda: [0.0, 0])  # merchant -> [spend, count]
    for r in rows:
        if r.merchant and r.amount:
            merch[r.merchant][0] += float(r.amount)
            merch[r.merchant][1] += 1
    top_merchants = [
        {"merchant": m, "total_spend": round(v[0], 2), "transactions": v[1]}
        for m, v in sorted(merch.items(), key=lambda kv: -kv[1][0])[:3]
    ]

    anomaly_count = sum(1 for r in rows if r.is_anomaly)
    stats = {
        "total_spend_inr": round(total_inr, 2),
        "total_spend_usd": round(total_usd, 2),
        "top_merchants": top_merchants,
        "anomaly_count": anomaly_count,
        "transaction_count": len(rows),
    }

    risk = _heuristic_risk(anomaly_count, len(rows))
    if settings.llm_enabled:
        try:
            narrative, llm_risk, _raw = generate_narrative(stats)
            risk = llm_risk or risk
        except LLMError as exc:
            logger.warning("Job %s: narrative generation failed: %s", job.id, exc)
            narrative = "LLM narrative unavailable (all retries failed); computed statistics only."
    else:
        narrative = "LLM disabled (no API key); computed statistics only."

    # Upsert (idempotent for re-runs).
    existing = db.scalar(select(JobSummary).where(JobSummary.job_id == job.id))
    if existing is not None:
        db.delete(existing)
        db.flush()
    db.add(
        JobSummary(
            job_id=job.id,
            total_spend_inr=total_inr,
            total_spend_usd=total_usd,
            top_merchants=top_merchants,
            anomaly_count=anomaly_count,
            narrative=narrative,
            risk_level=risk,
        )
    )
    db.commit()
    logger.info("Job %s: summary stored (risk=%s)", job.id, risk)

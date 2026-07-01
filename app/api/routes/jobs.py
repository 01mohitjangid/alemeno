"""Job endpoints: upload, status, results, list."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.config import settings
from app.database import get_db
from app.models import Job, JobStatus, Transaction
from app.schemas import (
    JobListItem,
    JobListResponse,
    JobResultsResponse,
    JobStatusResponse,
    JobSummaryOut,
    JobUploadResponse,
    TransactionOut,
)
from app.services.storage import CSVValidationError, save_csv, validate_and_count
from app.tasks.processing import process_job

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post(
    "/upload",
    response_model=JobUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Upload a transactions CSV and enqueue processing",
)
async def upload_job(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> JobUploadResponse:
    # Cheap guard on extension/content-type before reading the body.
    name = (file.filename or "").lower()
    if not name.endswith(".csv") and file.content_type not in (
        "text/csv",
        "application/vnd.ms-excel",
        "application/octet-stream",
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only .csv files are accepted.",
        )

    # Reject oversized uploads by declared size first (avoids reading a huge body
    # into memory), then re-check the actual bytes as a backstop.
    if file.size is not None and file.size > settings.max_upload_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds {settings.max_upload_bytes} bytes.",
        )
    content = await file.read()
    if len(content) > settings.max_upload_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds {settings.max_upload_bytes} bytes.",
        )

    # Validate structure (and get raw row count) BEFORE creating a Job record,
    # so we never leave orphan jobs behind for bad uploads.
    try:
        row_count_raw = validate_and_count(content)
    except CSVValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    job = Job(
        id=uuid.uuid4(),
        filename=file.filename or "upload.csv",
        status=JobStatus.pending.value,
        row_count_raw=row_count_raw,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    # Persist the file where the worker can read it, then enqueue. If either step
    # fails, mark the job failed so it is never left stuck in 'pending'.
    try:
        save_csv(job.id, content)
        process_job.delay(str(job.id))
    except Exception as exc:  # noqa: BLE001 - surface storage/broker failures cleanly
        job.status = JobStatus.failed.value
        job.error_message = f"Failed to store/enqueue upload: {exc}"[:2000]
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not queue the job for processing; please retry.",
        )

    return JobUploadResponse(
        job_id=job.id,
        status=job.status,
        filename=job.filename,
        row_count_raw=row_count_raw,
    )


def _get_job_or_404(db: Session, job_id: uuid.UUID) -> Job:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Job {job_id} not found."
        )
    return job


@router.get(
    "/{job_id}/status",
    response_model=JobStatusResponse,
    summary="Get job status (with summary once completed)",
)
def get_job_status(job_id: uuid.UUID, db: Session = Depends(get_db)) -> JobStatusResponse:
    job = _get_job_or_404(db, job_id)
    summary = (
        JobSummaryOut.model_validate(job.summary) if job.summary is not None else None
    )
    return JobStatusResponse(
        job_id=job.id,
        status=job.status,
        filename=job.filename,
        row_count_raw=job.row_count_raw,
        row_count_clean=job.row_count_clean,
        created_at=job.created_at,
        completed_at=job.completed_at,
        error_message=job.error_message,
        summary=summary,
    )


@router.get(
    "/{job_id}/results",
    response_model=JobResultsResponse,
    summary="Get full structured results for a job",
)
def get_job_results(job_id: uuid.UUID, db: Session = Depends(get_db)) -> JobResultsResponse:
    # Eager-load children to avoid N+1 queries when serialising.
    job = db.scalar(
        select(Job)
        .where(Job.id == job_id)
        .options(selectinload(Job.transactions), selectinload(Job.summary))
    )
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Job {job_id} not found."
        )

    txns = list(job.transactions)
    anomalies = [t for t in txns if t.is_anomaly]

    # Per-category spend, split by currency (computed from persisted rows).
    breakdown: dict[str, dict[str, float]] = {}
    for t in txns:
        category = t.llm_category or t.category or "Uncategorised"
        currency = (t.currency or "UNKNOWN").upper()
        amount = float(t.amount) if t.amount is not None else 0.0
        breakdown.setdefault(category, {})
        breakdown[category][currency] = round(
            breakdown[category].get(currency, 0.0) + amount, 2
        )

    summary = (
        JobSummaryOut.model_validate(job.summary) if job.summary is not None else None
    )
    return JobResultsResponse(
        job_id=job.id,
        status=job.status,
        row_count_raw=job.row_count_raw,
        row_count_clean=job.row_count_clean,
        summary=summary,
        transactions=[TransactionOut.model_validate(t) for t in txns],
        anomalies=[TransactionOut.model_validate(t) for t in anomalies],
        category_breakdown=breakdown,
    )


@router.get(
    "",
    response_model=JobListResponse,
    summary="List jobs (optionally filtered by ?status=)",
)
def list_jobs(
    status_filter: JobStatus | None = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
) -> JobListResponse:
    stmt = select(Job).order_by(Job.created_at.desc())
    if status_filter is not None:
        stmt = stmt.where(Job.status == status_filter.value)
    jobs = db.scalars(stmt).all()
    items = [
        JobListItem(
            id=j.id,
            filename=j.filename,
            status=j.status,
            row_count=j.row_count_raw,
            created_at=j.created_at,
        )
        for j in jobs
    ]
    return JobListResponse(count=len(items), jobs=items)

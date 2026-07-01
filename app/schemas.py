"""Pydantic response/request schemas for the API layer.

Money fields are exposed as floats for friendly JSON; they are stored exactly as
Numeric in the DB and only widened for display.
"""
from __future__ import annotations

import uuid
# Alias the date type: a Pydantic field is named `date`, which would otherwise
# shadow the type when the (stringised) annotation `date | None` is evaluated.
from datetime import date as date_type
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class JobUploadResponse(BaseModel):
    job_id: uuid.UUID
    status: str
    filename: str
    row_count_raw: int
    message: str = "Upload accepted; processing enqueued."


class JobSummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    total_spend_inr: float
    total_spend_usd: float
    top_merchants: list[dict[str, Any]] | None = None
    anomaly_count: int
    narrative: str | None = None
    risk_level: str | None = None


class TransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    txn_id: str | None = None
    date: date_type | None = None
    merchant: str | None = None
    amount: float | None = None
    currency: str | None = None
    status: str | None = None
    category: str | None = None
    account_id: str | None = None
    notes: str | None = None
    is_anomaly: bool = False
    anomaly_reason: str | None = None
    llm_category: str | None = None
    llm_failed: bool = False


class JobStatusResponse(BaseModel):
    job_id: uuid.UUID
    status: str
    filename: str
    row_count_raw: int | None = None
    row_count_clean: int | None = None
    created_at: datetime
    completed_at: datetime | None = None
    error_message: str | None = None
    # Present only once the job is completed.
    summary: JobSummaryOut | None = None


class JobResultsResponse(BaseModel):
    job_id: uuid.UUID
    status: str
    row_count_raw: int | None = None
    row_count_clean: int | None = None
    summary: JobSummaryOut | None = None
    transactions: list[TransactionOut] = []
    anomalies: list[TransactionOut] = []
    # category -> currency -> summed spend
    category_breakdown: dict[str, dict[str, float]] = {}


class JobListItem(BaseModel):
    id: uuid.UUID
    filename: str
    status: str
    row_count: int | None = None
    created_at: datetime


class JobListResponse(BaseModel):
    count: int
    jobs: list[JobListItem]

"""ORM models: Job, Transaction, JobSummary.

Design notes:
- UUID primary keys keep job IDs opaque and safe to expose in a public API.
- Numeric(14, 2) stores money exactly (never float) up to ~999 billion.
- Raw LLM responses are retained per row for auditability/debugging.
"""
from __future__ import annotations

import enum
import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class JobStatus(str, enum.Enum):
    pending = "pending"
    processing = "processing"
    completed = "completed"
    failed = "failed"


class RiskLevel(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_uuid
    )
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=JobStatus.pending.value, index=True
    )
    row_count_raw: Mapped[int | None] = mapped_column(Integer, nullable=True)
    row_count_clean: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    transactions: Mapped[list["Transaction"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )
    summary: Mapped["JobSummary | None"] = relationship(
        back_populates="job", cascade="all, delete-orphan", uselist=False
    )


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_uuid
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), index=True
    )

    # Cleaned/normalised transaction fields
    txn_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    date: Mapped[date | None] = mapped_column(nullable=True)          # ISO 8601 date
    merchant: Mapped[str | None] = mapped_column(String(256), nullable=True)
    amount: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(8), nullable=True)
    status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    account_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Anomaly detection
    is_anomaly: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    anomaly_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # LLM classification
    llm_category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    llm_raw_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    llm_failed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    job: Mapped["Job"] = relationship(back_populates="transactions")


class JobSummary(Base):
    __tablename__ = "job_summaries"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_uuid
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        unique=True,
        index=True,
    )

    total_spend_inr: Mapped[float] = mapped_column(Numeric(16, 2), default=0)
    total_spend_usd: Mapped[float] = mapped_column(Numeric(16, 2), default=0)
    top_merchants: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    anomaly_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    narrative: Mapped[str | None] = mapped_column(Text, nullable=True)
    risk_level: Mapped[str | None] = mapped_column(String(16), nullable=True)

    job: Mapped["Job"] = relationship(back_populates="summary")

"""initial schema: jobs, transactions, job_summaries

Revision ID: 0001_initial
Revises:
Create Date: 2026-07-01
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("filename", sa.String(length=512), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("row_count_raw", sa.Integer(), nullable=True),
        sa.Column("row_count_clean", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_jobs_status", "jobs", ["status"])
    op.create_index("ix_jobs_created_at", "jobs", ["created_at"])

    op.create_table(
        "transactions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("txn_id", sa.String(length=64), nullable=True),
        sa.Column("date", sa.Date(), nullable=True),
        sa.Column("merchant", sa.String(length=256), nullable=True),
        sa.Column("amount", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("currency", sa.String(length=8), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=True),
        sa.Column("category", sa.String(length=64), nullable=True),
        sa.Column("account_id", sa.String(length=64), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_anomaly", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("anomaly_reason", sa.Text(), nullable=True),
        sa.Column("llm_category", sa.String(length=64), nullable=True),
        sa.Column("llm_raw_response", sa.Text(), nullable=True),
        sa.Column("llm_failed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_transactions_job_id", "transactions", ["job_id"])
    op.create_index("ix_transactions_account_id", "transactions", ["account_id"])

    op.create_table(
        "job_summaries",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "total_spend_inr",
            sa.Numeric(precision=16, scale=2),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "total_spend_usd",
            sa.Numeric(precision=16, scale=2),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("top_merchants", postgresql.JSONB(), nullable=True),
        sa.Column(
            "anomaly_count", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("narrative", sa.Text(), nullable=True),
        sa.Column("risk_level", sa.String(length=16), nullable=True),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    # unique=True + index=True on the model => a single UNIQUE index (one summary per job)
    op.create_index(
        "ix_job_summaries_job_id", "job_summaries", ["job_id"], unique=True
    )


def downgrade() -> None:
    op.drop_index("ix_job_summaries_job_id", table_name="job_summaries")
    op.drop_table("job_summaries")
    op.drop_index("ix_transactions_account_id", table_name="transactions")
    op.drop_index("ix_transactions_job_id", table_name="transactions")
    op.drop_table("transactions")
    op.drop_index("ix_jobs_created_at", table_name="jobs")
    op.drop_index("ix_jobs_status", table_name="jobs")
    op.drop_table("jobs")

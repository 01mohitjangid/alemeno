"""Upload storage + CSV validation.

Uploaded CSVs are written to a shared volume (settings.upload_dir) at a
deterministic path keyed by job id, so the Celery worker can read the exact file
the API received. In a scaled deployment this becomes object storage (S3/GCS).
"""
from __future__ import annotations

import io
import uuid
from pathlib import Path

import pandas as pd

from app.config import settings

# Header columns expected in the raw export (values may be blank per assignment).
REQUIRED_COLUMNS = {
    "txn_id",
    "date",
    "merchant",
    "amount",
    "currency",
    "status",
    "category",
    "account_id",
    "notes",
}


class CSVValidationError(ValueError):
    """Raised when an uploaded file is not a usable transactions CSV."""


def _ensure_dir() -> None:
    Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)


def csv_path_for(job_id: uuid.UUID | str) -> Path:
    return Path(settings.upload_dir) / f"{job_id}.csv"


def validate_and_count(content: bytes) -> int:
    """Parse the CSV header + rows; return the raw data-row count.

    Raises CSVValidationError with a human-readable message on any problem.
    """
    if not content or not content.strip():
        raise CSVValidationError("Uploaded file is empty.")
    try:
        df = pd.read_csv(io.BytesIO(content), dtype=str, keep_default_na=False)
    except Exception as exc:  # noqa: BLE001 - surface any parse error to the client
        raise CSVValidationError(f"Could not parse CSV: {exc}") from exc

    columns = {c.strip() for c in df.columns}
    missing = REQUIRED_COLUMNS - columns
    if missing:
        raise CSVValidationError(
            f"CSV is missing required columns: {sorted(missing)}"
        )
    if len(df) == 0:
        raise CSVValidationError("CSV has a header but no data rows.")
    return len(df)


def save_csv(job_id: uuid.UUID | str, content: bytes) -> Path:
    _ensure_dir()
    path = csv_path_for(job_id)
    path.write_bytes(content)
    return path

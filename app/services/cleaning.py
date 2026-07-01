"""Data-cleaning stage (assignment §5a).

- Normalise dates to ISO 8601 (handles DD-MM-YYYY, YYYY/MM/DD, YYYY-MM-DD).
- Strip currency symbols / thousands separators from amounts.
- Upper-case status and currency.
- Fill blank categories with 'Uncategorised'.
- Remove exact-duplicate rows.
"""
from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation

import pandas as pd

# Year-first (2024/02/05 or 2024-07-15) vs day-first (04-09-2024 or 04/09/2024).
_YMD = re.compile(r"^(\d{4})[/-](\d{1,2})[/-](\d{1,2})$")
_DMY = re.compile(r"^(\d{1,2})[/-](\d{1,2})[/-](\d{4})$")

UNCATEGORISED = "Uncategorised"


def parse_date(raw: object) -> date | None:
    """Parse the known mixed formats into a date; None if unparseable."""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    m = _YMD.match(s)
    if m:
        y, mo, d = (int(x) for x in m.groups())
    else:
        m = _DMY.match(s)
        if not m:
            return None
        d, mo, y = (int(x) for x in m.groups())
    try:
        return date(y, mo, d)
    except ValueError:
        return None


def parse_amount(raw: object) -> Decimal | None:
    """Strip '$', '₹', commas, and spaces; return an exact Decimal or None."""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    s = re.sub(r"[^0-9.\-]", "", s)  # keep digits, dot, sign
    if s in ("", "-", ".", "-.", "."):
        return None
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def _s(value: object) -> str:
    return str(value).strip() if value is not None else ""


def clean_records(df: pd.DataFrame) -> tuple[list[dict], int]:
    """Return (list of cleaned record dicts, clean_row_count).

    Records are keyed to match the Transaction model constructor.
    """
    # Remove exact-duplicate rows (every column identical).
    df = df.drop_duplicates()

    records: list[dict] = []
    for _, row in df.iterrows():
        merchant = _s(row.get("merchant"))
        records.append(
            {
                "txn_id": _s(row.get("txn_id")) or None,
                "date": parse_date(row.get("date")),
                "merchant": merchant or None,
                "amount": parse_amount(row.get("amount")),
                "currency": _s(row.get("currency")).upper() or None,
                "status": _s(row.get("status")).upper() or None,
                "category": _s(row.get("category")) or UNCATEGORISED,
                "account_id": _s(row.get("account_id")) or None,
                "notes": _s(row.get("notes")) or None,
            }
        )
    return records, len(records)

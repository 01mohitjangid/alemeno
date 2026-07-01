"""Unit tests for the cleaning stage (pure functions, no DB/network)."""
import datetime as dt
from decimal import Decimal

import pandas as pd

from app.services.cleaning import UNCATEGORISED, clean_records, parse_amount, parse_date

COLUMNS = [
    "txn_id", "date", "merchant", "amount", "currency",
    "status", "category", "account_id", "notes",
]


def test_parse_date_all_formats():
    assert parse_date("04-09-2024") == dt.date(2024, 9, 4)   # DD-MM-YYYY (day-first)
    assert parse_date("2024/02/05") == dt.date(2024, 2, 5)   # YYYY/MM/DD (year-first)
    assert parse_date("2024-07-15") == dt.date(2024, 7, 15)  # ISO
    assert parse_date("2024-02-29") == dt.date(2024, 2, 29)  # leap year is valid


def test_parse_date_invalid():
    assert parse_date("") is None
    assert parse_date("not-a-date") is None
    assert parse_date("32-01-2024") is None   # impossible day
    assert parse_date("2023-02-29") is None   # not a leap year


def test_parse_amount():
    assert parse_amount("$11325.79") == Decimal("11325.79")
    assert parse_amount("6874.1") == Decimal("6874.1")
    assert parse_amount("1,234.50") == Decimal("1234.50")
    assert parse_amount("") is None
    assert parse_amount("abc") is None


def test_clean_records_dedupe_and_normalise():
    rows = [
        ["TXN1", "04-09-2024", "Swiggy", "$100", "inr", "success", "", "ACC1", ""],
        ["TXN1", "04-09-2024", "Swiggy", "$100", "inr", "success", "", "ACC1", ""],  # dup
        ["TXN2", "2024/02/05", "Ola", "200", "INR", "FAILED", "Transport", "ACC1", ""],
    ]
    records, n = clean_records(pd.DataFrame(rows, columns=COLUMNS))

    assert n == 2  # exact duplicate removed
    first = records[0]
    assert first["currency"] == "INR"          # upper-cased
    assert first["status"] == "SUCCESS"        # upper-cased
    assert first["amount"] == Decimal("100")   # '$' stripped
    assert first["category"] == UNCATEGORISED  # blank filled
    assert first["date"] == dt.date(2024, 9, 4)


def test_clean_records_blank_txn_id_becomes_none():
    rows = [["", "01-01-2024", "Amazon", "50", "INR", "SUCCESS", "Shopping", "ACC1", ""]]
    records, _ = clean_records(pd.DataFrame(rows, columns=COLUMNS))
    assert records[0]["txn_id"] is None

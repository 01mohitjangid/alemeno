"""Anomaly-detection stage (assignment §5b).

1. Statistical outlier: amount exceeds `multiplier` x the account's median.
2. Currency mismatch: USD charged on a domestic-only (India) merchant.

Mutates each record in place, setting `is_anomaly` and `anomaly_reason`.
A single row can trip both rules; reasons are joined with "; ".
"""
from __future__ import annotations

import statistics
from collections import defaultdict

from app.config import settings


def detect_anomalies(
    records: list[dict],
    multiplier: float | None = None,
    domestic: set[str] | None = None,
) -> int:
    mult = multiplier if multiplier is not None else settings.anomaly_median_multiplier
    dom = domestic if domestic is not None else settings.domestic_merchant_set

    # Per-account median of (present) amounts.
    by_account: dict[str, list[float]] = defaultdict(list)
    for r in records:
        if r.get("amount") is not None and r.get("account_id"):
            by_account[r["account_id"]].append(float(r["amount"]))
    medians = {acc: statistics.median(vals) for acc, vals in by_account.items() if vals}

    anomaly_count = 0
    for r in records:
        reasons: list[str] = []

        amt = float(r["amount"]) if r.get("amount") is not None else None
        med = medians.get(r.get("account_id"))
        if amt is not None and med is not None and med > 0 and amt > mult * med:
            reasons.append(
                f"Statistical outlier: amount {amt:.2f} exceeds "
                f"{mult:g}x account median ({med:.2f})"
            )

        merchant = r.get("merchant") or ""
        if r.get("currency") == "USD" and merchant.strip().lower() in dom:
            reasons.append(
                f"Currency mismatch: USD charged on domestic-only merchant '{merchant}'"
            )

        r["is_anomaly"] = bool(reasons)
        r["anomaly_reason"] = "; ".join(reasons) if reasons else None
        if reasons:
            anomaly_count += 1

    return anomaly_count

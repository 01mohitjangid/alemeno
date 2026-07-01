"""Unit tests for the anomaly-detection stage (pure functions)."""
from decimal import Decimal

from app.services.anomaly import detect_anomalies


def _rec(**kw) -> dict:
    base = dict(
        txn_id="T", merchant="X", amount=None, currency="INR",
        status="SUCCESS", category="Food", account_id="ACC1", notes=None,
    )
    base.update(kw)
    return base


def test_statistical_outlier_flagged():
    recs = [
        _rec(amount=Decimal("100")),
        _rec(amount=Decimal("100")),
        _rec(amount=Decimal("100")),
        _rec(amount=Decimal("1000")),  # 10x median(=100) -> outlier
    ]
    n = detect_anomalies(recs, multiplier=3.0, domestic={"swiggy"})
    assert recs[3]["is_anomaly"] is True
    assert "outlier" in recs[3]["anomaly_reason"].lower()
    assert recs[0]["is_anomaly"] is False
    assert n == 1


def test_usd_on_domestic_merchant_flagged():
    recs = [_rec(amount=Decimal("50"), currency="USD", merchant="Swiggy", account_id="A9")]
    detect_anomalies(recs, multiplier=3.0, domestic={"swiggy"})
    assert recs[0]["is_anomaly"] is True
    assert "domestic" in recs[0]["anomaly_reason"].lower()


def test_usd_on_international_merchant_not_flagged():
    recs = [_rec(amount=Decimal("50"), currency="USD", merchant="MakeMyTrip", account_id="A9")]
    detect_anomalies(recs, multiplier=3.0, domestic={"swiggy"})
    assert recs[0]["is_anomaly"] is False


def test_both_rules_combine_into_one_reason():
    recs = [
        _rec(amount=Decimal("10"), account_id="A1"),
        _rec(amount=Decimal("10"), account_id="A1"),
        _rec(amount=Decimal("100"), currency="USD", merchant="Ola", account_id="A1"),
    ]
    detect_anomalies(recs, multiplier=3.0, domestic={"ola"})
    reason = recs[2]["anomaly_reason"].lower()
    assert recs[2]["is_anomaly"] is True
    assert "outlier" in reason and "domestic" in reason  # both rules present

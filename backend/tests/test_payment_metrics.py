"""SP-903 payment metric schema and privacy tests."""

from app.soulmate import metrics


def test_payment_metric_catalog_covers_sp903_requirements():
    assert set(metrics.PAYMENT_METRIC_FIELDS) == {
        "webhook_verification_failure",
        "webhook_event_processing_failure",
        "webhook_duplicate_event",
        "first_payment_confirmation_latency",
        "reconciliation_mismatch",
        "payment_failure",
    }


def test_payment_metric_uses_stable_event_and_drops_unsafe_fields(monkeypatch):
    emitted = []
    monkeypatch.setattr(metrics, "log_event", lambda **kwargs: emitted.append(kwargs))

    metrics.record_payment_metric(
        "payment_failure",
        fields={
            "reason_category": "buyer@example.com",
            "provider_reason_code": "PRIVATE_PROVIDER_DETAIL",
        },
    )

    assert len(emitted) == 1
    assert emitted[0]["event_type"] == "payment_metric"
    assert emitted[0]["extra_data"] == {
        "metric": "payment_failure",
        "count": 1,
        "reason_category": "other",
    }


def test_payment_latency_is_non_negative_and_category_values_are_bounded(monkeypatch):
    emitted = []
    monkeypatch.setattr(metrics, "log_event", lambda **kwargs: emitted.append(kwargs))

    metrics.record_payment_metric(
        "first_payment_confirmation_latency",
        fields={"latency_ms": -9},
    )
    assert emitted[0]["extra_data"]["latency_ms"] == 0

    assert metrics.payment_failure_reason_category("INSUFFICIENT_FUNDS") == "insufficient_funds"
    assert metrics.payment_failure_reason_category("buyer@example.com") == "other"
    assert metrics.payment_webhook_event_category("PAYMENT.SALE.REFUNDED") == "refund_or_reversal"
    assert metrics.payment_webhook_event_category("private-event-name") == "other"


def test_payment_metric_transport_failure_is_best_effort(monkeypatch):
    def fail_transport(**kwargs):
        raise RuntimeError("transport details must not escape")

    monkeypatch.setattr(metrics, "log_event", fail_transport)
    monkeypatch.setattr(metrics.logger, "exception", lambda *args, **kwargs: None)

    metrics.record_payment_metric("webhook_duplicate_event", fields={"event_category": "other"})

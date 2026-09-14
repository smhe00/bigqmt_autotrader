from datetime import datetime, timezone

from bigqmt_autotrader.domain import OrderStatus
from bigqmt_autotrader.qmt import (
    BrokerEvidenceCandidate,
    QmtHostIngestion,
    QmtIngressBuffer,
    encode_transport_frame,
)


FP = "sha256:" + "d" * 64


def event(sequence, event_type, payload, *, session_id="session-ingest"):
    return {
        "protocol_version": "0.2",
        "session_id": session_id,
        "sequence": sequence,
        "timestamp_ms": 1_800_000_000_000 + sequence,
        "event_type": event_type,
        "source": "callback" if event_type != "snapshot" else "active_query",
        "account_fingerprint": FP,
        "account_type": "STOCK",
        "payload": payload,
    }


def snapshot(sequence=1):
    return event(
        sequence,
        "snapshot",
        {
            "account_fingerprint": FP,
            "account_type": "STOCK",
            "account": [{"balance": "1000", "available_cash": "800"}],
            "positions": [],
            "orders": [],
            "deals": [],
            "query_errors": [],
        },
    )


class FakeSink:
    def __init__(self):
        self.calls = []

    def ingest_broker_evidence(self, **kwargs):
        self.calls.append(kwargs)
        return object()


def test_order_and_deal_are_quarantined_without_calibrated_mapper():
    ingress = QmtIngressBuffer(expected_account_fingerprint=FP)
    host = QmtHostIngestion(max_quarantine=4)

    host.handle(ingress.ingest_frame(encode_transport_frame(snapshot())))
    order_result = host.handle(
        ingress.ingest_frame(
            encode_transport_frame(
                event(
                    2,
                    "order",
                    {
                        "remark": "BQTOKEN001",
                        "broker_order_id": "12345",
                        "status_code": 50,
                        "filled_quantity": 0,
                    },
                )
            )
        )
    )
    deal_result = host.handle(
        ingress.ingest_frame(
            encode_transport_frame(
                event(
                    3,
                    "deal",
                    {
                        "remark": "BQTOKEN001",
                        "broker_order_id": "12345",
                        "trade_id": "t1",
                        "quantity": 100,
                    },
                )
            )
        )
    )

    assert order_result.quarantined is True
    assert deal_result.quarantined is True
    assert len(host.quarantine) == 2
    assert host.read_model.healthy is True


def test_explicit_mapper_is_required_before_oms_evidence_sink_is_called():
    ingress = QmtIngressBuffer(expected_account_fingerprint=FP)
    sink = FakeSink()

    def mapper(qmt_event):
        if qmt_event.event_type != "order":
            return None
        return BrokerEvidenceCandidate(
            source="qmt_callback",
            source_event_id=None,
            account_fingerprint=qmt_event.account_fingerprint,
            client_order_id="client-001",
            evidence_type="ORDER",
            requested_status=OrderStatus.ACKNOWLEDGED,
            filled_quantity=0,
            broker_order_id=qmt_event.payload.get("broker_order_id"),
            payload=qmt_event.payload,
            observed_at=datetime(2026, 9, 14, tzinfo=timezone.utc),
        )

    host = QmtHostIngestion(evidence_sink=sink, evidence_mapper=mapper)
    host.handle(ingress.ingest_frame(encode_transport_frame(snapshot())))
    result = host.handle(
        ingress.ingest_frame(
            encode_transport_frame(
                event(
                    2,
                    "order",
                    {
                        "remark": "BQTOKEN001",
                        "broker_order_id": "12345",
                        "status_code": 50,
                        "filled_quantity": 0,
                    },
                )
            )
        )
    )

    assert result.evidence_ingested is True
    assert result.quarantined is False
    assert len(sink.calls) == 1
    call = sink.calls[0]
    assert call["client_order_id"] == "client-001"
    assert call["source_event_id"] == "session-ingest:2"
    assert call["requested_status"] is OrderStatus.ACKNOWLEDGED


def test_mapper_cannot_change_account_identity():
    ingress = QmtIngressBuffer(expected_account_fingerprint=FP)
    sink = FakeSink()

    def bad_mapper(qmt_event):
        return BrokerEvidenceCandidate(
            source="qmt_callback",
            source_event_id=None,
            account_fingerprint="sha256:" + "e" * 64,
            client_order_id="client-001",
            evidence_type="ORDER",
            requested_status=OrderStatus.ACKNOWLEDGED,
            filled_quantity=0,
            broker_order_id=None,
            payload=qmt_event.payload,
            observed_at=datetime(2026, 9, 14, tzinfo=timezone.utc),
        )

    host = QmtHostIngestion(evidence_sink=sink, evidence_mapper=bad_mapper)
    host.handle(ingress.ingest_frame(encode_transport_frame(snapshot())))

    import pytest

    with pytest.raises(ValueError, match="changed account identity"):
        host.handle(
            ingress.ingest_frame(
                encode_transport_frame(event(2, "order", {"status_code": 50}))
            )
        )
    assert sink.calls == []


def test_identical_account_callback_is_semantically_deduplicated_but_sequence_advances():
    ingress = QmtIngressBuffer(expected_account_fingerprint=FP)
    host = QmtHostIngestion()

    first = host.handle(ingress.ingest_frame(encode_transport_frame(snapshot())))
    assert first.deduplicated is False
    assert host.read_model.view is not None
    assert host.read_model.view.sequence == 1

    same = host.handle(
        ingress.ingest_frame(
            encode_transport_frame(
                event(2, "account", {"balance": "1000", "available_cash": "800"})
            )
        )
    )
    assert same.deduplicated is True
    assert host.account_semantic_duplicates == 1
    assert host.read_model.view is not None
    assert host.read_model.view.sequence == 2
    assert host.read_model.view.account[0]["available_cash"] == "800"

    changed = host.handle(
        ingress.ingest_frame(
            encode_transport_frame(
                event(3, "account", {"balance": "1000", "available_cash": "700"})
            )
        )
    )
    assert changed.deduplicated is False
    assert host.account_semantic_duplicates == 1
    assert host.read_model.view is not None
    assert host.read_model.view.sequence == 3
    assert host.read_model.view.account[0]["available_cash"] == "700"

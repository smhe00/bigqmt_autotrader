import ast
import importlib.util
from pathlib import Path

import pytest

from bigqmt_autotrader.qmt import (
    IngressDisposition,
    LocalQmtReceiver,
    QmtIngressBuffer,
    QmtProtocolError,
    QmtReadModel,
    decode_transport_frame,
    encode_transport_frame,
)


ROOT = Path(__file__).resolve().parents[2]
QMT_TRANSPORT = ROOT / "qmt_side" / "BIGQMT_LOCALHOST_TRANSPORT.py"
FP = "sha256:" + "a" * 64


def snapshot_event(sequence=1, session_id="session-a"):
    return {
        "protocol_version": "0.2",
        "session_id": session_id,
        "sequence": sequence,
        "timestamp_ms": 1_800_000_000_000,
        "event_type": "snapshot",
        "source": "active_query",
        "account_fingerprint": FP,
        "account_type": "STOCK",
        "payload": {
            "account_fingerprint": FP,
            "account_type": "STOCK",
            "account": [{"available_cash": "100.0", "balance": "120.0"}],
            "positions": [{"symbol": "000001.SZ", "quantity": 100}],
            "orders": [],
            "deals": [],
            "query_errors": [],
        },
    }


def callback_event(sequence, event_type="position", session_id="session-a"):
    return {
        "protocol_version": "0.2",
        "session_id": session_id,
        "sequence": sequence,
        "timestamp_ms": 1_800_000_000_001 + sequence,
        "event_type": event_type,
        "source": "callback",
        "account_fingerprint": FP,
        "account_type": "STOCK",
        "payload": {"symbol": "000001.SZ", "quantity": 200},
    }


def load_qmt_transport():
    spec = importlib.util.spec_from_file_location("bigqmt_qmt_transport", QMT_TRANSPORT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_qmt_transport_source_is_python36_compatible():
    source = QMT_TRANSPORT.read_text(encoding="utf-8")
    ast.parse(source, filename=str(QMT_TRANSPORT), feature_version=(3, 6))


def test_protocol_round_trip_and_rejects_wrong_account():
    raw = encode_transport_frame(snapshot_event())
    event = decode_transport_frame(raw)
    assert event.event_type == "snapshot"
    assert event.account_fingerprint == FP
    assert event.payload["positions"][0]["symbol"] == "000001.SZ"

    ingress = QmtIngressBuffer(expected_account_fingerprint="sha256:" + "b" * 64)
    with pytest.raises(QmtProtocolError, match="unexpected account_fingerprint"):
        ingress.ingest(event)


def test_gap_is_fail_closed_until_clean_snapshot():
    ingress = QmtIngressBuffer(expected_account_fingerprint=FP)
    model = QmtReadModel()

    first = ingress.ingest_frame(encode_transport_frame(snapshot_event(sequence=1)))
    assert first.disposition is IngressDisposition.ACCEPTED
    model.apply(first)
    assert model.healthy is True

    gap = ingress.ingest_frame(encode_transport_frame(callback_event(sequence=3)))
    assert gap.disposition is IngressDisposition.GAP
    model.apply(gap)
    assert model.healthy is False

    duplicate = ingress.ingest_frame(encode_transport_frame(callback_event(sequence=3)))
    assert duplicate.disposition is IngressDisposition.DUPLICATE
    assert len(ingress.events) == 2

    recovered = ingress.ingest_frame(encode_transport_frame(snapshot_event(sequence=4)))
    model.apply(recovered)
    assert recovered.needs_resync is False
    assert model.healthy is True
    assert model.view is not None
    assert model.view.sequence == 4


def test_new_session_requires_snapshot_before_healthy():
    ingress = QmtIngressBuffer(expected_account_fingerprint=FP)
    model = QmtReadModel()
    model.apply(ingress.ingest_frame(encode_transport_frame(snapshot_event(sequence=1))))
    assert model.healthy

    new_session_callback = ingress.ingest_frame(
        encode_transport_frame(callback_event(sequence=1, session_id="session-b"))
    )
    model.apply(new_session_callback)
    assert new_session_callback.needs_resync is True
    assert model.healthy is False


def test_python36_sender_to_host_receiver_end_to_end():
    ingress = QmtIngressBuffer(expected_account_fingerprint=FP)
    transport = load_qmt_transport()

    with LocalQmtReceiver(ingress, port=0) as receiver:
        ack = transport.send_event(
            snapshot_event(sequence=1),
            port=receiver.port,
            timeout_seconds=0.5,
        )

    assert ack["ok"] is True
    assert ack["disposition"] == "ACCEPTED"
    assert ack["needs_resync"] is False
    events = ingress.drain()
    assert len(events) == 1
    assert events[0].event_type == "snapshot"


def test_qmt_sender_queue_retains_failed_event():
    transport = load_qmt_transport()
    events = [snapshot_event(sequence=1), snapshot_event(sequence=2)]
    # Port 9 is intentionally not backed by the test receiver. The helper must
    # fail quickly and retain the FIFO rather than silently dropping facts.
    sent = transport.flush_event_queue(events, port=9, timeout_seconds=0.01)
    assert sent == 0
    assert len(events) == 2

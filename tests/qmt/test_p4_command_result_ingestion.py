import pytest

from bigqmt_autotrader.qmt import (
    QmtHostIngestion,
    QmtIngressBuffer,
    QmtProtocolError,
    encode_transport_frame,
)


FP = "sha256:" + "d" * 64


def event(sequence: int, event_type: str, payload: dict):
    return {
        "protocol_version": "0.2",
        "session_id": "session-p4",
        "sequence": sequence,
        "timestamp_ms": 1_800_000_000_000 + sequence,
        "event_type": event_type,
        "source": "active_query" if event_type == "snapshot" else "command_spool",
        "account_fingerprint": FP,
        "account_type": "STOCK",
        "payload": payload,
    }


def snapshot_payload():
    return {
        "account_fingerprint": FP,
        "account_type": "STOCK",
        "account": [{"balance": "1000"}],
        "positions": [{"symbol": "000001.SZ", "quantity": 100}],
        "orders": [],
        "deals": [],
        "query_errors": [],
    }


def test_command_result_advances_sequence_without_faking_broker_state():
    ingress = QmtIngressBuffer(expected_account_fingerprint=FP)
    host = QmtHostIngestion()

    snap = ingress.ingest_frame(encode_transport_frame(event(1, "snapshot", snapshot_payload())))
    host.handle(snap)
    before = host.read_model.view
    assert before is not None
    assert host.read_model.healthy is True

    result = ingress.ingest_frame(
        encode_transport_frame(
            event(
                2,
                "command_result",
                {
                    "command_id": "cmd-001",
                    "command_type": "SUBMIT_LIMIT",
                    "client_order_id": "cid-001",
                    "broker_token": "BQ" + "a" * 20,
                    "result_status": "SHADOW_ACCEPTED",
                    "execution_mode": "SHADOW",
                    "live_side_effect": False,
                },
            )
        )
    )
    outcome = host.handle(result)
    after = host.read_model.view

    assert outcome.evidence_ingested is False
    assert after is not None
    assert after.sequence == 2
    assert after.account == before.account
    assert after.positions == before.positions
    assert after.orders == before.orders
    assert after.deals == before.deals
    assert host.read_model.healthy is True


def test_command_result_cannot_claim_non_boolean_live_side_effect():
    with pytest.raises(QmtProtocolError):
        encode_transport_frame(
            event(
                1,
                "command_result",
                {
                    "command_id": "cmd-001",
                    "command_type": "SUBMIT_LIMIT",
                    "result_status": "SHADOW_ACCEPTED",
                    "live_side_effect": "false",
                },
            )
        )

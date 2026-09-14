import pytest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from bigqmt_autotrader.domain import (
    OrderIntent,
    OrderStatus,
    RiskDecision,
    RiskReasonCode,
    Side,
)
from bigqmt_autotrader.drivers import QmtShadowDriver
from bigqmt_autotrader.oms import (
    CommandResultConflict,
    OfflineOms,
    OmsQmtCommandResultSink,
    OmsRepository,
    connect_database,
    initialize_database,
)
from bigqmt_autotrader.qmt import (
    QmtCommandSpool,
    QmtHostIngestion,
    QmtIngressBuffer,
    QmtProtocolError,
    broker_token_for,
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


def test_shadow_command_result_is_durably_joined_to_oms_reconciliation_without_ack(tmp_path):
    conn = connect_database(tmp_path / "oms.sqlite3")
    initialize_database(conn)
    repo = OmsRepository(conn)
    driver = QmtShadowDriver(QmtCommandSpool(tmp_path / "spool"))
    oms = OfflineOms(repo, driver)
    oms.recover()
    now = datetime.now(timezone.utc)
    order_intent = OrderIntent(
        client_order_id="cid-001",
        strategy_id="strategy",
        strategy_version="1",
        account_fingerprint=FP,
        symbol="000001.SZ",
        side=Side.BUY,
        quantity=100,
        limit_price=Decimal("10.50"),
        created_at=now,
        expires_at=now + timedelta(minutes=5),
        signal_id="signal-1",
        reason_code="p4-command-result",
    )
    decision = RiskDecision(
        accepted=True,
        reason_code=RiskReasonCode.OK,
        rule_version="p4-test",
        snapshot_hash="sha256:p4-test",
        decided_at=now,
    )
    submitted = oms._submit_decided_intent(order_intent, decision)
    assert submitted.status is OrderStatus.UNKNOWN

    ingress = QmtIngressBuffer(expected_account_fingerprint=FP)
    host = QmtHostIngestion(command_result_sink=OmsQmtCommandResultSink(oms))
    host.handle(ingress.ingest_frame(encode_transport_frame(event(1, "snapshot", snapshot_payload()))))
    token = broker_token_for(FP, "cid-001")
    command_payload = {
        "command_id": "submit-" + token,
        "command_type": "SUBMIT_LIMIT",
        "client_order_id": "cid-001",
        "broker_token": token,
        "result_status": "SHADOW_ACCEPTED",
        "execution_mode": "SHADOW",
        "live_side_effect": False,
    }
    result = host.handle(
        ingress.ingest_frame(
            encode_transport_frame(
                event(
                    2,
                    "command_result",
                    command_payload,
                )
            )
        )
    )

    assert result.command_result_ingested is True
    assert result.evidence_ingested is False
    assert repo.get_status(FP, "cid-001") is OrderStatus.RECONCILING
    assert repo.get_status(FP, "cid-001") is not OrderStatus.ACKNOWLEDGED
    journal = conn.execute("SELECT * FROM qmt_command_results").fetchall()
    assert len(journal) == 1
    assert journal[0]["result_status"] == "SHADOW_ACCEPTED"
    assert journal[0]["live_side_effect"] == 0
    event_types = [row["event_type"] for row in repo.list_events(FP, "cid-001")]
    assert "QMT_COMMAND_RESULT_SHADOW_ACCEPTED" in event_types

    duplicate = oms.ingest_qmt_command_result(
        qmt_session_id="session-p4",
        qmt_sequence=2,
        account_fingerprint=FP,
        payload=command_payload,
        observed_at=datetime.fromtimestamp((1_800_000_000_000 + 2) / 1000, tz=timezone.utc),
    )
    assert duplicate.duplicate is True
    assert len(conn.execute("SELECT * FROM qmt_command_results").fetchall()) == 1

    with pytest.raises(CommandResultConflict):
        oms.ingest_qmt_command_result(
            qmt_session_id="session-p4",
            qmt_sequence=2,
            account_fingerprint=FP,
            payload={**command_payload, "result_status": "REJECTED_EXPIRED"},
            observed_at=datetime.fromtimestamp(
                (1_800_000_000_000 + 2) / 1000, tz=timezone.utc
            ),
        )


def test_live_side_effect_command_result_is_rejected_at_protocol_boundary():
    token = broker_token_for(FP, "cid-001")
    with pytest.raises(QmtProtocolError, match="live side effect"):
        encode_transport_frame(
            event(
                1,
                "command_result",
                {
                    "command_id": "submit-" + token,
                    "command_type": "SUBMIT_LIMIT",
                    "client_order_id": "cid-001",
                    "broker_token": token,
                    "result_status": "SHADOW_ACCEPTED",
                    "execution_mode": "SHADOW",
                    "live_side_effect": True,
                },
            )
        )

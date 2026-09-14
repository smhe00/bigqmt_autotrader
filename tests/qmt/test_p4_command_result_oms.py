from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json

from bigqmt_autotrader.domain import (
    OrderIntent,
    OrderStatus,
    RiskDecision,
    RiskReasonCode,
    Side,
)
from bigqmt_autotrader.drivers import SimulatedDriver
from bigqmt_autotrader.oms import (
    OfflineOms,
    OmsQmtCommandResultSink,
    OmsRepository,
    connect_database,
    initialize_database,
)
from bigqmt_autotrader.qmt import QmtHostIngestion, QmtIngressBuffer, encode_transport_frame


FP = "sha256:" + "e" * 64
CID = "cid-p4-oms-001"
TOKEN = "BQ" + "1" * 20


def order_intent() -> OrderIntent:
    created = datetime(2026, 9, 15, 1, 0, tzinfo=timezone.utc)
    return OrderIntent(
        client_order_id=CID,
        strategy_id="p4-test",
        strategy_version="1",
        account_fingerprint=FP,
        symbol="000001.SZ",
        side=Side.BUY,
        quantity=100,
        limit_price=Decimal("10.00"),
        created_at=created,
        expires_at=created + timedelta(minutes=5),
        signal_id="signal-p4",
        reason_code="shadow",
    )


def accepted_risk() -> RiskDecision:
    return RiskDecision(
        accepted=True,
        reason_code=RiskReasonCode.OK,
        rule_version="p4-test",
        snapshot_hash="sha256:p4-test",
        decided_at=datetime.now(timezone.utc),
    )


def make_oms(tmp_path):
    conn = connect_database(tmp_path / "oms.sqlite3")
    initialize_database(conn)
    repo = OmsRepository(conn)
    oms = OfflineOms(repo, SimulatedDriver())
    oms.recover()
    return repo, oms


def event(sequence: int, event_type: str, payload: dict):
    return {
        "protocol_version": "0.2",
        "session_id": "session-p4-oms",
        "sequence": sequence,
        "timestamp_ms": 1_789_420_000_000 + sequence,
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
        "positions": [],
        "orders": [],
        "deals": [],
        "query_errors": [],
    }


def command_result_payload():
    return {
        "command_id": "submit-" + TOKEN,
        "command_type": "SUBMIT_LIMIT",
        "client_order_id": CID,
        "broker_token": TOKEN,
        "result_status": "SHADOW_ACCEPTED",
        "execution_mode": "SHADOW",
        "live_side_effect": False,
    }


def test_shadow_command_result_is_audited_but_never_promotes_unknown_to_ack(tmp_path):
    repo, oms = make_oms(tmp_path)
    intent = order_intent()
    repo.create_intent(intent)
    repo.record_risk_decision(FP, CID, accepted_risk())
    repo.prepare_submit(FP, CID)
    repo.transition_order(
        FP,
        CID,
        OrderStatus.UNKNOWN,
        event_type="TEST_DRIVER_OUTCOME_UNKNOWN",
    )

    ingress = QmtIngressBuffer(expected_account_fingerprint=FP)
    host = QmtHostIngestion(command_result_sink=OmsQmtCommandResultSink(oms))
    host.handle(ingress.ingest_frame(encode_transport_frame(event(1, "snapshot", snapshot_payload()))))
    result = host.handle(
        ingress.ingest_frame(
            encode_transport_frame(event(2, "command_result", command_result_payload()))
        )
    )

    assert result.command_result_ingested is True
    assert result.evidence_ingested is False
    assert repo.get_status(FP, CID) is OrderStatus.UNKNOWN
    assert repo.get_order_row(FP, CID)["broker_order_id"] is None

    events = repo.list_events(FP, CID)
    audit = [row for row in events if row["event_type"] == "QMT_COMMAND_RESULT_SHADOW_ACCEPTED"]
    assert len(audit) == 1
    evidence = json.loads(audit[0]["evidence_json"])
    assert evidence["broker_evidence"] is False
    assert evidence["live_side_effect"] is False
    assert evidence["command_id"] == "submit-" + TOKEN


def test_shadow_command_result_racing_submit_reservation_can_only_move_to_unknown(tmp_path):
    repo, oms = make_oms(tmp_path)
    intent = order_intent()
    repo.create_intent(intent)
    repo.record_risk_decision(FP, CID, accepted_risk())
    repo.prepare_submit(FP, CID)
    assert repo.get_status(FP, CID) is OrderStatus.SUBMITTING

    sink = OmsQmtCommandResultSink(oms)
    result = sink.ingest_execution_command_result(
        source_event_id="session-p4-oms:2",
        account_fingerprint=FP,
        command_id="submit-" + TOKEN,
        command_type="SUBMIT_LIMIT",
        client_order_id=CID,
        broker_token=TOKEN,
        result_status="SHADOW_ACCEPTED",
        execution_mode="SHADOW",
        live_side_effect=False,
        payload=command_result_payload(),
        observed_at=datetime.now(timezone.utc),
    )

    assert result.status is OrderStatus.UNKNOWN
    assert repo.get_status(FP, CID) is OrderStatus.UNKNOWN
    assert repo.get_order_row(FP, CID)["broker_order_id"] is None

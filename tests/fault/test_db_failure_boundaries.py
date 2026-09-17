import sqlite3
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from bigqmt_autotrader.domain import (
    OrderIntent,
    OrderStatus,
    RiskDecision,
    RiskReasonCode,
    Side,
)
from bigqmt_autotrader.drivers import SimulatedDriver
from bigqmt_autotrader.oms import (
    BrokerEvidenceSourceKind,
    BrokerEvidenceType,
    BrokerEvidenceV1,
    OfflineOms,
    OmsRepository,
    connect_database,
    initialize_database,
)


FP = "sha256:" + "c" * 64


def _intent(client_order_id="cid-db-fault"):
    created = datetime(2026, 9, 12, 9, 40, tzinfo=timezone(timedelta(hours=8)))
    return OrderIntent(
        client_order_id=client_order_id,
        strategy_id="strategyA",
        strategy_version="git:test",
        account_fingerprint=FP,
        symbol="000333.SZ",
        side=Side.BUY,
        quantity=100,
        limit_price=Decimal("75.00"),
        created_at=created,
        expires_at=created + timedelta(minutes=1),
        signal_id="signal-db-fault",
        reason_code="TARGET_POSITION_REBALANCE",
    )


def _decision():
    return RiskDecision(
        accepted=True,
        reason_code=RiskReasonCode.OK,
        rule_version="p1-test",
        snapshot_hash="sha256:test",
        decided_at=datetime.now(timezone.utc),
    )


def _stack(tmp_path):
    conn = connect_database(tmp_path / "oms.sqlite3")
    initialize_database(conn)
    repo = OmsRepository(conn)
    driver = SimulatedDriver()
    oms = OfflineOms(repo, driver)
    oms.recover()
    return conn, repo, driver, oms


def _fail_event(conn, trigger_name, event_type):
    conn.execute(
        f"""
        CREATE TRIGGER {trigger_name}
        BEFORE INSERT ON order_events
        WHEN NEW.event_type='{event_type}'
        BEGIN
            SELECT RAISE(ABORT, 'injected {event_type} persistence failure');
        END
        """
    )


def _submit_ok(repo, driver, oms):
    submitted = oms.submit_intent(_intent(), _decision())
    assert submitted.status is OrderStatus.ACKNOWLEDGED
    row = repo.get_order_row(FP, "cid-db-fault")
    assert row["broker_order_id"] is not None
    assert driver.submit_call_count(FP, "cid-db-fault") == 1
    return row["broker_order_id"]


def test_read_only_database_fails_before_any_broker_submit(tmp_path):
    conn, _, driver, oms = _stack(tmp_path)
    conn.execute("PRAGMA query_only=ON")

    with pytest.raises(sqlite3.OperationalError):
        oms.submit_intent(_intent(), _decision())

    assert driver.submit_call_count(FP, "cid-db-fault") == 0


def test_risk_persistence_failure_leaves_created_orphan_and_never_calls_broker(tmp_path):
    conn, repo, driver, oms = _stack(tmp_path)
    conn.execute(
        """
        CREATE TRIGGER fail_risk_insert
        BEFORE INSERT ON risk_decisions
        BEGIN
            SELECT RAISE(ABORT, 'injected risk persistence failure');
        END
        """
    )

    with pytest.raises(sqlite3.IntegrityError):
        oms.submit_intent(_intent(), _decision())

    assert repo.get_status(FP, "cid-db-fault") is OrderStatus.CREATED
    assert driver.submit_call_count(FP, "cid-db-fault") == 0

    conn.execute("DROP TRIGGER fail_risk_insert")
    oms.close()
    restarted = OfflineOms(repo, driver)
    restarted.recover()
    assert repo.get_status(FP, "cid-db-fault") is OrderStatus.ABORTED
    assert driver.submit_call_count(FP, "cid-db-fault") == 0


def test_submit_reservation_transaction_failure_rolls_back_and_never_calls_broker(tmp_path):
    conn, repo, driver, oms = _stack(tmp_path)
    _fail_event(conn, "fail_submit_reserved", "SUBMIT_RESERVED")

    with pytest.raises(sqlite3.IntegrityError):
        oms.submit_intent(_intent(), _decision())

    row = repo.get_order_row(FP, "cid-db-fault")
    assert row["status"] == OrderStatus.RISK_ACCEPTED.value
    assert row["submit_call_started"] == 0
    assert driver.submit_call_count(FP, "cid-db-fault") == 0


def test_submit_ack_persistence_failure_recovers_broker_fact_without_resubmit(tmp_path):
    conn, repo, driver, oms = _stack(tmp_path)
    _fail_event(conn, "fail_submit_ack", "BROKER_EVIDENCE_ORDER_ACCEPTED")

    with pytest.raises(sqlite3.IntegrityError):
        oms.submit_intent(_intent(), _decision())

    row = repo.get_order_row(FP, "cid-db-fault")
    assert row["status"] == OrderStatus.RECONCILING.value
    assert row["submit_call_started"] == 1
    assert driver.submit_call_count(FP, "cid-db-fault") == 1

    conn.execute("DROP TRIGGER fail_submit_ack")
    oms.close()
    restarted = OfflineOms(repo, driver)
    restarted.recover()

    assert repo.get_status(FP, "cid-db-fault") is OrderStatus.ACKNOWLEDGED
    assert driver.submit_call_count(FP, "cid-db-fault") == 1


def test_cancel_reservation_transaction_failure_rolls_back_and_never_calls_broker(tmp_path):
    conn, repo, driver, oms = _stack(tmp_path)
    _submit_ok(repo, driver, oms)
    _fail_event(conn, "fail_cancel_reserved", "CANCEL_RESERVED")

    with pytest.raises(sqlite3.IntegrityError):
        oms.cancel_order(FP, "cid-db-fault")

    row = repo.get_order_row(FP, "cid-db-fault")
    assert row["status"] == OrderStatus.ACKNOWLEDGED.value
    assert row["cancel_call_started"] == 0
    assert driver.cancel_call_count(FP, "cid-db-fault") == 0


def test_cancel_ack_persistence_failure_recovers_without_second_cancel(tmp_path):
    conn, repo, driver, oms = _stack(tmp_path)
    _submit_ok(repo, driver, oms)
    _fail_event(conn, "fail_cancel_ack", "BROKER_EVIDENCE_ORDER_CANCELLED")

    with pytest.raises(sqlite3.IntegrityError):
        oms.cancel_order(FP, "cid-db-fault")

    row = repo.get_order_row(FP, "cid-db-fault")
    assert row["status"] == OrderStatus.RECONCILING.value
    assert row["cancel_call_started"] == 1
    assert row["cancel_outcome_resolved"] == 0
    assert driver.cancel_call_count(FP, "cid-db-fault") == 1

    conn.execute("DROP TRIGGER fail_cancel_ack")
    oms.close()
    restarted = OfflineOms(repo, driver)
    restarted.recover()

    assert repo.get_status(FP, "cid-db-fault") is OrderStatus.CANCELLED
    assert driver.cancel_call_count(FP, "cid-db-fault") == 1


def test_evidence_key_failure_rolls_back_aggregate_event_and_journal(tmp_path):
    conn, repo, _, oms = _stack(tmp_path)
    broker_order_id = _submit_ok(repo, oms.driver, oms)
    conn.execute(
        """
        CREATE TRIGGER fail_evidence_key
        BEFORE INSERT ON broker_evidence_keys
        BEGIN
            SELECT RAISE(ABORT, 'injected evidence key failure');
        END
        """
    )

    with pytest.raises(sqlite3.IntegrityError):
        oms.ingest_broker_evidence(BrokerEvidenceV1.build(
            source="QMT_CALLBACK",
            source_kind=BrokerEvidenceSourceKind.ORDER_CALLBACK,
            source_event_id="evt-key-fail",
            mapper_profile="test-order-v1",
            account_fingerprint=FP,
            client_order_id="cid-db-fault",
            broker_token=None,
            broker_order_id=broker_order_id,
            order_ref=None,
            trade_id=None,
            evidence_type=BrokerEvidenceType.PARTIAL_FILL,
            requested_status=OrderStatus.PARTIALLY_FILLED,
            filled_quantity=50,
            observed_at_ms=1_700_000_000_000,
            raw_payload_ref="test://evt-key-fail",
        ))

    row = repo.get_order_row(FP, "cid-db-fault")
    assert row["status"] == OrderStatus.ACKNOWLEDGED.value
    assert row["filled_quantity"] == 0
    assert conn.execute("SELECT COUNT(*) FROM broker_evidence_keys").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM broker_evidence_observations").fetchone()[0] == 1
    assert conn.execute(
        "SELECT COUNT(*) FROM order_events WHERE event_type='BROKER_EVIDENCE_PARTIAL_FILL'"
    ).fetchone()[0] == 0


def test_evidence_observation_failure_rolls_back_aggregate_key_and_event(tmp_path):
    conn, repo, _, oms = _stack(tmp_path)
    broker_order_id = _submit_ok(repo, oms.driver, oms)
    conn.execute(
        """
        CREATE TRIGGER fail_evidence_observation
        BEFORE INSERT ON broker_evidence_observations
        WHEN NEW.classification='NEW'
        BEGIN
            SELECT RAISE(ABORT, 'injected evidence observation failure');
        END
        """
    )

    with pytest.raises(sqlite3.IntegrityError):
        oms.ingest_broker_evidence(BrokerEvidenceV1.build(
            source="QMT_CALLBACK",
            source_kind=BrokerEvidenceSourceKind.ORDER_CALLBACK,
            source_event_id="evt-observation-fail",
            mapper_profile="test-order-v1",
            account_fingerprint=FP,
            client_order_id="cid-db-fault",
            broker_token=None,
            broker_order_id=broker_order_id,
            order_ref=None,
            trade_id=None,
            evidence_type=BrokerEvidenceType.PARTIAL_FILL,
            requested_status=OrderStatus.PARTIALLY_FILLED,
            filled_quantity=50,
            observed_at_ms=1_700_000_000_001,
            raw_payload_ref="test://evt-observation-fail",
        ))

    row = repo.get_order_row(FP, "cid-db-fault")
    assert row["status"] == OrderStatus.ACKNOWLEDGED.value
    assert row["filled_quantity"] == 0
    assert conn.execute("SELECT COUNT(*) FROM broker_evidence_keys").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM broker_evidence_observations").fetchone()[0] == 1
    assert conn.execute(
        "SELECT COUNT(*) FROM order_events WHERE event_type='BROKER_EVIDENCE_PARTIAL_FILL'"
    ).fetchone()[0] == 0

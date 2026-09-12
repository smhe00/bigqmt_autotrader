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
from bigqmt_autotrader.oms import OfflineOms, OmsRepository, connect_database, initialize_database


def _intent(client_order_id="cid-db-fault"):
    created = datetime(2026, 9, 12, 9, 40, tzinfo=timezone(timedelta(hours=8)))
    return OrderIntent(
        client_order_id=client_order_id,
        strategy_id="strategyA",
        strategy_version="git:test",
        account_fingerprint="account-A",
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


def test_read_only_database_fails_before_any_broker_submit(tmp_path):
    conn, _, driver, oms = _stack(tmp_path)
    conn.execute("PRAGMA query_only=ON")

    with pytest.raises(sqlite3.OperationalError):
        oms.submit_intent(_intent(), _decision())

    assert driver.submit_call_count("account-A", "cid-db-fault") == 0


def test_submit_reservation_transaction_failure_rolls_back_and_never_calls_broker(tmp_path):
    conn, repo, driver, oms = _stack(tmp_path)
    _fail_event(conn, "fail_submit_reserved", "SUBMIT_RESERVED")

    with pytest.raises(sqlite3.IntegrityError):
        oms.submit_intent(_intent(), _decision())

    row = repo.get_order_row("account-A", "cid-db-fault")
    assert row["status"] == OrderStatus.RISK_ACCEPTED.value
    assert row["submit_call_started"] == 0
    assert driver.submit_call_count("account-A", "cid-db-fault") == 0


def test_submit_ack_persistence_failure_recovers_broker_fact_without_resubmit(tmp_path):
    conn, repo, driver, oms = _stack(tmp_path)
    _fail_event(conn, "fail_submit_ack", "SUBMIT_ACK")

    with pytest.raises(sqlite3.IntegrityError):
        oms.submit_intent(_intent(), _decision())

    row = repo.get_order_row("account-A", "cid-db-fault")
    assert row["status"] == OrderStatus.SUBMITTING.value
    assert row["submit_call_started"] == 1
    assert driver.submit_call_count("account-A", "cid-db-fault") == 1

    conn.execute("DROP TRIGGER fail_submit_ack")
    oms.close()
    restarted = OfflineOms(repo, driver)
    restarted.recover()

    assert repo.get_status("account-A", "cid-db-fault") is OrderStatus.ACKNOWLEDGED
    assert driver.submit_call_count("account-A", "cid-db-fault") == 1


def test_cancel_ack_persistence_failure_recovers_without_second_cancel(tmp_path):
    conn, repo, driver, oms = _stack(tmp_path)
    submitted = oms.submit_intent(_intent(), _decision())
    assert submitted.status is OrderStatus.ACKNOWLEDGED
    _fail_event(conn, "fail_cancel_ack", "CANCEL_ACK")

    with pytest.raises(sqlite3.IntegrityError):
        oms.cancel_order("account-A", "cid-db-fault")

    row = repo.get_order_row("account-A", "cid-db-fault")
    assert row["status"] == OrderStatus.CANCEL_PENDING.value
    assert row["cancel_call_started"] == 1
    assert row["cancel_outcome_resolved"] == 0
    assert driver.cancel_call_count("account-A", "cid-db-fault") == 1

    conn.execute("DROP TRIGGER fail_cancel_ack")
    oms.close()
    restarted = OfflineOms(repo, driver)
    restarted.recover()

    assert repo.get_status("account-A", "cid-db-fault") is OrderStatus.CANCELLED
    assert driver.cancel_call_count("account-A", "cid-db-fault") == 1

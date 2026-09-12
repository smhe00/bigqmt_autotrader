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
from bigqmt_autotrader.drivers import CancelFailureMode, SimulatedDriver
from bigqmt_autotrader.oms import (
    CancelAlreadyStarted,
    OfflineOms,
    OmsRepository,
    connect_database,
    initialize_database,
)


def intent(client_order_id="cid-cancel"):
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
        signal_id="signal-cancel",
        reason_code="TARGET_POSITION_REBALANCE",
    )


def accept_decision():
    return RiskDecision(
        accepted=True,
        reason_code=RiskReasonCode.OK,
        rule_version="p1-test",
        snapshot_hash="sha256:test",
        decided_at=datetime.now(timezone.utc),
    )


def make_stack(tmp_path, driver=None):
    conn = connect_database(tmp_path / "oms.sqlite3")
    initialize_database(conn)
    repo = OmsRepository(conn)
    driver = driver or SimulatedDriver()
    oms = OfflineOms(repo, driver)
    oms.recover()
    return conn, repo, driver, oms


def submit_one(oms):
    result = oms.submit_intent(intent(), accept_decision())
    assert result.status is OrderStatus.ACKNOWLEDGED


def test_normal_cancel_is_reserved_resolved_and_called_once(tmp_path):
    _, repo, driver, oms = make_stack(tmp_path)
    submit_one(oms)

    result = oms.cancel_order("account-A", "cid-cancel")

    assert result.status is OrderStatus.CANCELLED
    assert repo.get_status("account-A", "cid-cancel") is OrderStatus.CANCELLED
    assert driver.cancel_call_count("account-A", "cid-cancel") == 1
    row = repo.get_order_row("account-A", "cid-cancel")
    assert row["cancel_call_started"] == 1
    assert row["cancel_outcome_resolved"] == 1


def test_cancel_timeout_after_accept_reconciles_to_cancelled_without_retry(tmp_path):
    _, repo, driver, oms = make_stack(tmp_path)
    submit_one(oms)
    driver.fail_next_cancel(CancelFailureMode.TIMEOUT_AFTER_ACCEPT)

    result = oms.cancel_order("account-A", "cid-cancel")
    assert result.status is OrderStatus.UNKNOWN
    assert repo.get_order_row("account-A", "cid-cancel")["cancel_outcome_resolved"] == 0
    assert driver.cancel_call_count("account-A", "cid-cancel") == 1

    restarted = OfflineOms(repo, driver)
    restarted.recover()
    assert repo.get_status("account-A", "cid-cancel") is OrderStatus.CANCELLED
    assert repo.get_order_row("account-A", "cid-cancel")["cancel_outcome_resolved"] == 1
    assert driver.cancel_call_count("account-A", "cid-cancel") == 1


def test_cancel_timeout_before_accept_reconciles_active_without_retry(tmp_path):
    _, repo, driver, oms = make_stack(tmp_path)
    submit_one(oms)
    driver.fail_next_cancel(CancelFailureMode.TIMEOUT_BEFORE_ACCEPT)

    result = oms.cancel_order("account-A", "cid-cancel")
    assert result.status is OrderStatus.UNKNOWN

    restarted = OfflineOms(repo, driver)
    restarted.recover()
    assert repo.get_status("account-A", "cid-cancel") is OrderStatus.ACKNOWLEDGED
    assert repo.get_order_row("account-A", "cid-cancel")["cancel_outcome_resolved"] == 1
    assert driver.cancel_call_count("account-A", "cid-cancel") == 1

    with pytest.raises(CancelAlreadyStarted):
        restarted.cancel_order("account-A", "cid-cancel")
    assert driver.cancel_call_count("account-A", "cid-cancel") == 1


def test_crash_after_cancel_reservation_before_side_effect_never_recancels(tmp_path):
    _, repo, driver, oms = make_stack(tmp_path)
    submit_one(oms)
    repo.prepare_cancel("account-A", "cid-cancel")
    assert repo.get_status("account-A", "cid-cancel") is OrderStatus.CANCEL_PENDING
    assert driver.cancel_call_count("account-A", "cid-cancel") == 0

    restarted = OfflineOms(repo, driver)
    restarted.recover()
    assert repo.get_status("account-A", "cid-cancel") is OrderStatus.ACKNOWLEDGED
    row = repo.get_order_row("account-A", "cid-cancel")
    assert row["cancel_call_started"] == 1
    assert row["cancel_outcome_resolved"] == 1
    assert driver.cancel_call_count("account-A", "cid-cancel") == 0

    with pytest.raises(CancelAlreadyStarted):
        restarted.cancel_order("account-A", "cid-cancel")
    assert driver.cancel_call_count("account-A", "cid-cancel") == 0


def test_partial_fill_does_not_erase_unresolved_cancel_across_restart(tmp_path):
    _, repo, driver, oms = make_stack(tmp_path)
    submit_one(oms)
    repo.prepare_cancel("account-A", "cid-cancel")

    driver.set_order_status(
        "account-A", "cid-cancel", OrderStatus.PARTIALLY_FILLED, filled_quantity=50
    )
    repo.transition_order(
        "account-A",
        "cid-cancel",
        OrderStatus.PARTIALLY_FILLED,
        event_type="SIM_PARTIAL_FILL_CALLBACK",
        filled_quantity=50,
    )
    row = repo.get_order_row("account-A", "cid-cancel")
    assert row["status"] == OrderStatus.PARTIALLY_FILLED.value
    assert row["cancel_call_started"] == 1
    assert row["cancel_outcome_resolved"] == 0

    restarted = OfflineOms(repo, driver)
    restarted.recover()
    row = repo.get_order_row("account-A", "cid-cancel")
    assert row["status"] == OrderStatus.PARTIALLY_FILLED.value
    assert row["filled_quantity"] == 50
    assert row["cancel_outcome_resolved"] == 1
    assert driver.cancel_call_count("account-A", "cid-cancel") == 0

    event_types = [row["event_type"] for row in repo.list_events("account-A", "cid-cancel")]
    assert "STARTUP_RESTORE_CANCEL_PENDING" in event_types
    assert "STARTUP_CANCEL_AMBIGUITY" in event_types


def test_cancel_event_log_records_ambiguity_and_reconciliation(tmp_path):
    _, repo, driver, oms = make_stack(tmp_path)
    submit_one(oms)
    driver.fail_next_cancel(CancelFailureMode.TIMEOUT_AFTER_ACCEPT)
    oms.cancel_order("account-A", "cid-cancel")
    OfflineOms(repo, driver).recover()

    event_types = [row["event_type"] for row in repo.list_events("account-A", "cid-cancel")]
    assert "CANCEL_RESERVED" in event_types
    assert "CANCEL_OUTCOME_UNKNOWN" in event_types
    assert "STARTUP_RECONCILE_BEGIN" in event_types
    assert "RECONCILE_BROKER_EVIDENCE" in event_types

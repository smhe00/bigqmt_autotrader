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
    OfflineOms,
    OmsRepository,
    RecoveryInvariantViolation,
    connect_database,
    initialize_database,
)


def _intent(client_order_id="cid-pre-submit"):
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
        signal_id="signal-pre-submit",
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


def test_created_orphan_is_aborted_on_restart_without_broker_call(tmp_path):
    _, repo, driver, oms = _stack(tmp_path)
    repo.create_intent(_intent())
    assert repo.get_status("account-A", "cid-pre-submit") is OrderStatus.CREATED

    oms.close()
    restarted = OfflineOms(repo, driver)
    restarted.recover()

    assert repo.get_status("account-A", "cid-pre-submit") is OrderStatus.ABORTED
    assert driver.submit_call_count("account-A", "cid-pre-submit") == 0
    events = [row["event_type"] for row in repo.list_events("account-A", "cid-pre-submit")]
    assert events[-1] == "STARTUP_PRE_SUBMIT_ABORT"


def test_risk_accepted_orphan_is_aborted_not_auto_submitted(tmp_path):
    _, repo, driver, oms = _stack(tmp_path)
    repo.create_intent(_intent())
    repo.record_risk_decision("account-A", "cid-pre-submit", _decision())
    assert repo.get_status("account-A", "cid-pre-submit") is OrderStatus.RISK_ACCEPTED

    oms.close()
    restarted = OfflineOms(repo, driver)
    restarted.recover()

    row = repo.get_order_row("account-A", "cid-pre-submit")
    assert row["status"] == OrderStatus.ABORTED.value
    assert row["submit_call_started"] == 0
    assert row["broker_order_id"] is None
    assert driver.submit_call_count("account-A", "cid-pre-submit") == 0


def test_pre_submit_state_with_side_effect_marker_fails_closed(tmp_path):
    conn, repo, driver, oms = _stack(tmp_path)
    repo.create_intent(_intent())
    repo.record_risk_decision("account-A", "cid-pre-submit", _decision())

    conn.execute(
        """
        UPDATE broker_orders
        SET submit_call_started=1
        WHERE account_fingerprint='account-A' AND client_order_id='cid-pre-submit'
        """
    )

    oms.close()
    restarted = OfflineOms(repo, driver)
    with pytest.raises(RecoveryInvariantViolation, match="impossible side-effect evidence"):
        restarted.recover()

    assert repo.get_status("account-A", "cid-pre-submit") is OrderStatus.RISK_ACCEPTED
    assert driver.submit_call_count("account-A", "cid-pre-submit") == 0


def test_aborted_order_cannot_be_prepared_for_submit(tmp_path):
    _, repo, driver, oms = _stack(tmp_path)
    repo.create_intent(_intent())
    oms.close()
    restarted = OfflineOms(repo, driver)
    restarted.recover()

    with pytest.raises(ValueError, match="illegal order transition"):
        repo.prepare_submit("account-A", "cid-pre-submit")
    assert driver.submit_call_count("account-A", "cid-pre-submit") == 0

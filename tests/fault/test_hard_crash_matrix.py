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
from bigqmt_autotrader.drivers import (
    CancelFailureMode,
    SimulatedDriver,
    SimulatedProcessCrash,
    SubmitFailureMode,
)
from bigqmt_autotrader.oms import OfflineOms, OmsRepository, connect_database, initialize_database


class ManualClock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, *, seconds):
        self.now += timedelta(seconds=seconds)


def _intent(client_order_id="cid-hard-crash"):
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
        signal_id="signal-hard-crash",
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


def _start(path, driver, clock):
    conn = connect_database(path)
    initialize_database(conn)
    repo = OmsRepository(conn)
    oms = OfflineOms(repo, driver, leader_lease_seconds=5, clock=clock)
    oms.recover()
    return conn, repo, oms


def _restart_after_crash(path, driver, clock):
    clock.advance(seconds=6)
    conn = connect_database(path)
    initialize_database(conn)
    repo = OmsRepository(conn)
    oms = OfflineOms(repo, driver, leader_lease_seconds=5, clock=clock)
    oms.recover()
    return conn, repo, oms


@pytest.mark.parametrize(
    ("failure_mode", "expected_status"),
    [
        (SubmitFailureMode.CRASH_BEFORE_ACCEPT, OrderStatus.MANUAL_REVIEW),
        (SubmitFailureMode.CRASH_AFTER_ACCEPT, OrderStatus.ACKNOWLEDGED),
    ],
)
def test_hard_crash_during_submit_never_resubmits(tmp_path, failure_mode, expected_status):
    path = tmp_path / "oms.sqlite3"
    driver = SimulatedDriver()
    clock = ManualClock(datetime(2026, 9, 12, 1, 0, tzinfo=timezone.utc))
    conn1, repo1, oms1 = _start(path, driver, clock)
    driver.fail_next_submit(failure_mode)

    with pytest.raises(SimulatedProcessCrash):
        oms1.submit_intent(_intent(), _decision())

    row = repo1.get_order_row("account-A", "cid-hard-crash")
    assert row["status"] == OrderStatus.SUBMITTING.value
    assert row["submit_call_started"] == 1
    assert driver.submit_call_count("account-A", "cid-hard-crash") == 1

    # Simulate abrupt process death: close only the SQLite handle. Do not call
    # OfflineOms.close(), because a real crash does not release its leader lease.
    conn1.close()
    conn2, repo2, _ = _restart_after_crash(path, driver, clock)

    assert repo2.get_status("account-A", "cid-hard-crash") is expected_status
    assert driver.submit_call_count("account-A", "cid-hard-crash") == 1
    conn2.close()


@pytest.mark.parametrize(
    ("failure_mode", "expected_status"),
    [
        (CancelFailureMode.CRASH_BEFORE_ACCEPT, OrderStatus.ACKNOWLEDGED),
        (CancelFailureMode.CRASH_AFTER_ACCEPT, OrderStatus.CANCELLED),
    ],
)
def test_hard_crash_during_cancel_never_recancels(tmp_path, failure_mode, expected_status):
    path = tmp_path / "oms.sqlite3"
    driver = SimulatedDriver()
    clock = ManualClock(datetime(2026, 9, 12, 1, 0, tzinfo=timezone.utc))
    conn1, repo1, oms1 = _start(path, driver, clock)
    submitted = oms1.submit_intent(_intent(), _decision())
    assert submitted.status is OrderStatus.ACKNOWLEDGED

    driver.fail_next_cancel(failure_mode)
    with pytest.raises(SimulatedProcessCrash):
        oms1.cancel_order("account-A", "cid-hard-crash")

    row = repo1.get_order_row("account-A", "cid-hard-crash")
    assert row["status"] == OrderStatus.CANCEL_PENDING.value
    assert row["cancel_call_started"] == 1
    assert row["cancel_outcome_resolved"] == 0
    assert driver.cancel_call_count("account-A", "cid-hard-crash") == 1

    conn1.close()
    conn2, repo2, _ = _restart_after_crash(path, driver, clock)

    assert repo2.get_status("account-A", "cid-hard-crash") is expected_status
    assert driver.cancel_call_count("account-A", "cid-hard-crash") == 1
    row = repo2.get_order_row("account-A", "cid-hard-crash")
    assert row["cancel_outcome_resolved"] == 1
    conn2.close()


def test_crash_after_submit_reservation_before_driver_call_is_never_reissued(tmp_path):
    path = tmp_path / "oms.sqlite3"
    driver = SimulatedDriver()
    clock = ManualClock(datetime(2026, 9, 12, 1, 0, tzinfo=timezone.utc))
    conn1, repo1, _ = _start(path, driver, clock)

    repo1.create_intent(_intent())
    repo1.record_risk_decision("account-A", "cid-hard-crash", _decision())
    repo1.prepare_submit("account-A", "cid-hard-crash")
    assert repo1.get_status("account-A", "cid-hard-crash") is OrderStatus.SUBMITTING
    assert driver.submit_call_count("account-A", "cid-hard-crash") == 0

    conn1.close()
    conn2, repo2, _ = _restart_after_crash(path, driver, clock)

    assert repo2.get_status("account-A", "cid-hard-crash") is OrderStatus.MANUAL_REVIEW
    assert driver.submit_call_count("account-A", "cid-hard-crash") == 0
    conn2.close()


def test_crash_after_cancel_reservation_before_driver_call_is_never_recancelled(tmp_path):
    path = tmp_path / "oms.sqlite3"
    driver = SimulatedDriver()
    clock = ManualClock(datetime(2026, 9, 12, 1, 0, tzinfo=timezone.utc))
    conn1, repo1, oms1 = _start(path, driver, clock)
    submitted = oms1.submit_intent(_intent(), _decision())
    assert submitted.status is OrderStatus.ACKNOWLEDGED

    repo1.prepare_cancel("account-A", "cid-hard-crash")
    assert repo1.get_status("account-A", "cid-hard-crash") is OrderStatus.CANCEL_PENDING
    assert driver.cancel_call_count("account-A", "cid-hard-crash") == 0

    conn1.close()
    conn2, repo2, _ = _restart_after_crash(path, driver, clock)

    # Query sees the original ACK, so the abandoned cancel is resolved without
    # issuing another cancel call.
    assert repo2.get_status("account-A", "cid-hard-crash") is OrderStatus.ACKNOWLEDGED
    assert driver.cancel_call_count("account-A", "cid-hard-crash") == 0
    assert repo2.get_order_row("account-A", "cid-hard-crash")["cancel_outcome_resolved"] == 1
    conn2.close()

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
    OmsLeaderLost,
    OmsLeaderUnavailable,
    OmsRepository,
    connect_database,
    initialize_database,
)


class ManualClock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, *, seconds):
        self.now += timedelta(seconds=seconds)


def _intent(client_order_id="cid-leader"):
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
        signal_id="signal-leader",
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


def _two_repositories(tmp_path):
    path = tmp_path / "oms.sqlite3"
    conn1 = connect_database(path)
    initialize_database(conn1)
    conn2 = connect_database(path)
    initialize_database(conn2)
    return (conn1, OmsRepository(conn1)), (conn2, OmsRepository(conn2))


def test_second_oms_fails_closed_while_leader_lease_is_live(tmp_path):
    (_, repo1), (_, repo2) = _two_repositories(tmp_path)
    driver = SimulatedDriver()
    clock = ManualClock(datetime(2026, 9, 12, 1, 0, tzinfo=timezone.utc))

    leader = OfflineOms(repo1, driver, leader_lease_seconds=30, clock=clock)
    with pytest.raises(OmsLeaderUnavailable):
        OfflineOms(repo2, driver, leader_lease_seconds=30, clock=clock)

    leader.close()
    successor = OfflineOms(repo2, driver, leader_lease_seconds=30, clock=clock)
    assert successor.leader_lease.epoch == 1


def test_expired_lease_takeover_increments_fencing_epoch(tmp_path):
    (_, repo1), (_, repo2) = _two_repositories(tmp_path)
    driver = SimulatedDriver()
    clock = ManualClock(datetime(2026, 9, 12, 1, 0, tzinfo=timezone.utc))

    old = OfflineOms(repo1, driver, leader_lease_seconds=5, clock=clock)
    old.recover()
    old_epoch = old.leader_lease.epoch

    clock.advance(seconds=6)
    successor = OfflineOms(repo2, driver, leader_lease_seconds=5, clock=clock)
    assert successor.leader_lease.epoch == old_epoch + 1

    with pytest.raises(OmsLeaderLost):
        old.assert_leader()
    with pytest.raises(OmsLeaderLost):
        old.heartbeat()


def test_lost_leader_after_submit_reservation_never_calls_broker(tmp_path):
    (_, repo1), (_, repo2) = _two_repositories(tmp_path)
    driver = SimulatedDriver()
    clock = ManualClock(datetime(2026, 9, 12, 1, 0, tzinfo=timezone.utc))

    old = OfflineOms(repo1, driver, leader_lease_seconds=5, clock=clock)
    old.recover()
    order_intent = _intent()
    repo1.create_intent(order_intent)
    repo1.record_risk_decision("account-A", "cid-leader", _decision())
    repo1.prepare_submit("account-A", "cid-leader")
    assert repo1.get_status("account-A", "cid-leader") is OrderStatus.SUBMITTING

    clock.advance(seconds=6)
    successor = OfflineOms(repo2, driver, leader_lease_seconds=5, clock=clock)

    with pytest.raises(OmsLeaderLost):
        old.assert_leader()
    assert driver.submit_call_count("account-A", "cid-leader") == 0

    successor.recover()
    assert repo2.get_status("account-A", "cid-leader") is OrderStatus.MANUAL_REVIEW
    assert driver.submit_call_count("account-A", "cid-leader") == 0


def test_heartbeat_extends_only_current_unexpired_lease(tmp_path):
    (_, repo1), (_, repo2) = _two_repositories(tmp_path)
    driver = SimulatedDriver()
    clock = ManualClock(datetime(2026, 9, 12, 1, 0, tzinfo=timezone.utc))

    leader = OfflineOms(repo1, driver, leader_lease_seconds=5, clock=clock)
    first_expiry = leader.leader_lease.expires_at
    clock.advance(seconds=3)
    renewed = leader.heartbeat()
    assert renewed.expires_at > first_expiry

    clock.advance(seconds=3)
    with pytest.raises(OmsLeaderUnavailable):
        OfflineOms(repo2, driver, leader_lease_seconds=5, clock=clock)

    clock.advance(seconds=3)
    successor = OfflineOms(repo2, driver, leader_lease_seconds=5, clock=clock)
    assert successor.leader_lease.epoch == leader.leader_lease.epoch + 1

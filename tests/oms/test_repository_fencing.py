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
    OmsRepository,
    OrderNotFound,
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


def _intent(client_order_id):
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
        signal_id="signal-fence",
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


def test_repository_write_rechecks_fence_after_prior_service_assertion(tmp_path):
    path = tmp_path / "oms.sqlite3"
    conn1 = connect_database(path)
    initialize_database(conn1)
    conn2 = connect_database(path)
    initialize_database(conn2)
    repo1 = OmsRepository(conn1)
    repo2 = OmsRepository(conn2)
    driver = SimulatedDriver()
    clock = ManualClock(datetime(2026, 9, 12, 1, 0, tzinfo=timezone.utc))

    old = OfflineOms(repo1, driver, leader_lease_seconds=5, clock=clock)
    old.recover()
    submitted = old.submit_intent(_intent("cid-existing"), _decision())
    assert submitted.status is OrderStatus.ACKNOWLEDGED

    # This models the exact race the repository guard must close: a service-level
    # fence assertion succeeds, then the lease expires and a successor takes over
    # before the old process enters its durable write transaction.
    old.assert_leader()
    clock.advance(seconds=6)
    successor = OfflineOms(repo2, driver, leader_lease_seconds=5, clock=clock)

    with pytest.raises(OmsLeaderLost):
        repo1.transition_order(
            "account-A",
            "cid-existing",
            OrderStatus.CANCEL_PENDING,
            event_type="STALE_WRITER_ATTEMPT",
        )
    assert repo2.get_status("account-A", "cid-existing") is OrderStatus.ACKNOWLEDGED

    with pytest.raises(OmsLeaderLost):
        repo1.create_intent(_intent("cid-stale-create"))
    with pytest.raises(OrderNotFound):
        repo2.get_status("account-A", "cid-stale-create")

    # The current owner can still perform its own fenced repository writes.
    successor.recover()
    repo2.create_intent(_intent("cid-current-create"))
    assert repo2.get_status("account-A", "cid-current-create") is OrderStatus.CREATED

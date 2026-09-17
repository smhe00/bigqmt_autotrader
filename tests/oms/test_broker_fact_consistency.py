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
from bigqmt_autotrader.drivers import SimulatedDriver, SimulatedOrderEvidence
from bigqmt_autotrader.oms import (
    BrokerEvidenceConflict,
    InvalidFilledQuantity,
    OfflineOms,
    OmsRepository,
    connect_database,
    initialize_database,
)


class QueryOverrideDriver(SimulatedDriver):
    def __init__(self):
        super().__init__()
        self.query_override = None

    def query_by_client_order_id(self, account_fingerprint, client_order_id):
        if self.query_override is not None:
            return self.query_override
        return super().query_by_client_order_id(account_fingerprint, client_order_id)


def _intent(client_order_id="cid-facts"):
    created = datetime(2026, 9, 12, 9, 40, tzinfo=timezone(timedelta(hours=8)))
    return OrderIntent(
        client_order_id=client_order_id,
        strategy_id="strategyA",
        strategy_version="git:test",
        account_fingerprint="sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        symbol="000333.SZ",
        side=Side.BUY,
        quantity=100,
        limit_price=Decimal("75.00"),
        created_at=created,
        expires_at=created + timedelta(minutes=1),
        signal_id="signal-facts",
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
    driver = QueryOverrideDriver()
    oms = OfflineOms(repo, driver)
    oms.recover()
    result = oms.submit_intent(_intent(), _decision())
    assert result.status is OrderStatus.ACKNOWLEDGED
    return conn, repo, driver, oms


def test_stale_ack_query_cannot_erase_known_partial_fill(tmp_path):
    _, repo, driver, oms = _stack(tmp_path)
    broker_id = repo.get_order_row("sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "cid-facts")["broker_order_id"]

    repo.prepare_cancel("sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "cid-facts")
    repo.transition_order(
        "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "cid-facts",
        OrderStatus.PARTIALLY_FILLED,
        event_type="TEST_PARTIAL_FILL",
        broker_order_id=broker_id,
        filled_quantity=50,
    )
    driver.query_override = SimulatedOrderEvidence(
        broker_order_id=broker_id,
        status=OrderStatus.ACKNOWLEDGED,
        filled_quantity=0,
    )

    oms.close()
    restarted = OfflineOms(repo, driver)
    restarted.recover()

    row = repo.get_order_row("sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "cid-facts")
    assert row["status"] == OrderStatus.PARTIALLY_FILLED.value
    assert row["filled_quantity"] == 50
    assert row["cancel_outcome_resolved"] == 1


def test_reconciliation_rejects_changed_broker_order_identity(tmp_path):
    _, repo, driver, oms = _stack(tmp_path)
    repo.prepare_cancel("sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "cid-facts")
    driver.query_override = SimulatedOrderEvidence(
        broker_order_id="SIM-WRONG-IDENTITY",
        status=OrderStatus.ACKNOWLEDGED,
        filled_quantity=0,
    )

    oms.close()
    restarted = OfflineOms(repo, driver)
    with pytest.raises(BrokerEvidenceConflict, match="broker_order_id_mismatch"):
        restarted.recover()

    row = repo.get_order_row("sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "cid-facts")
    assert row["broker_order_id"] != "SIM-WRONG-IDENTITY"
    assert row["status"] == OrderStatus.MANUAL_REVIEW.value
    assert driver.submit_call_count("sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "cid-facts") == 1


def test_reconciliation_rejects_overfill_without_mutating_quantity(tmp_path):
    _, repo, driver, oms = _stack(tmp_path)
    broker_id = repo.get_order_row("sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "cid-facts")["broker_order_id"]
    repo.prepare_cancel("sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "cid-facts")
    driver.query_override = SimulatedOrderEvidence(
        broker_order_id=broker_id,
        status=OrderStatus.FILLED,
        filled_quantity=101,
    )

    oms.close()
    restarted = OfflineOms(repo, driver)
    with pytest.raises(BrokerEvidenceConflict, match="filled_quantity_exceeds"):
        restarted.recover()

    row = repo.get_order_row("sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "cid-facts")
    assert row["filled_quantity"] == 0
    assert row["status"] == OrderStatus.MANUAL_REVIEW.value


def test_filled_status_requires_full_quantity(tmp_path):
    _, repo, _, _ = _stack(tmp_path)
    broker_id = repo.get_order_row("sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "cid-facts")["broker_order_id"]

    with pytest.raises(InvalidFilledQuantity, match="FILLED broker status"):
        repo.transition_order(
            "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "cid-facts",
            OrderStatus.FILLED,
            event_type="TEST_CONTRADICTORY_FILL",
            broker_order_id=broker_id,
            filled_quantity=50,
        )

    row = repo.get_order_row("sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "cid-facts")
    assert row["status"] == OrderStatus.ACKNOWLEDGED.value
    assert row["filled_quantity"] == 0

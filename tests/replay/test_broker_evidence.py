from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from bigqmt_autotrader.domain import (
    OrderIntent,
    OrderStatus,
    RiskDecision,
    RiskReasonCode,
    Side,
    TransitionDisposition,
)
from bigqmt_autotrader.drivers import SimulatedDriver
from bigqmt_autotrader.oms import (
    BrokerEvidenceConflict,
    BrokerEvidenceSourceKind,
    BrokerEvidenceType,
    BrokerEvidenceV1,
    OfflineOms,
    OmsLeaderLost,
    OmsRepository,
    connect_database,
    initialize_database,
)


FP = "sha256:" + "a" * 64


class ManualClock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, *, seconds):
        self.now += timedelta(seconds=seconds)


def _intent():
    created = datetime(2026, 9, 12, 9, 40, tzinfo=timezone(timedelta(hours=8)))
    return OrderIntent(
        client_order_id="cid-evidence",
        strategy_id="strategyA",
        strategy_version="git:test",
        account_fingerprint=FP,
        symbol="000333.SZ",
        side=Side.BUY,
        quantity=100,
        limit_price=Decimal("75.00"),
        created_at=created,
        expires_at=created + timedelta(minutes=1),
        signal_id="signal-evidence",
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
    result = oms.submit_intent(_intent(), _decision())
    assert result.status is OrderStatus.ACKNOWLEDGED
    row = repo.get_order_row(FP, "cid-evidence")
    return conn, repo, driver, oms, row["broker_order_id"]


def _ingest(oms, broker_order_id, *, event_id, status, filled):
    evidence_type = {
        OrderStatus.ACKNOWLEDGED: BrokerEvidenceType.ORDER_ACCEPTED,
        OrderStatus.PARTIALLY_FILLED: BrokerEvidenceType.PARTIAL_FILL,
        OrderStatus.FILLED: BrokerEvidenceType.FULL_FILL,
        OrderStatus.CANCELLED: BrokerEvidenceType.ORDER_CANCELLED,
        OrderStatus.REJECTED: BrokerEvidenceType.ORDER_REJECTED,
    }[status]
    return oms.ingest_broker_evidence(BrokerEvidenceV1.build(
        source="QMT_CALLBACK",
        source_kind=BrokerEvidenceSourceKind.ORDER_CALLBACK,
        source_event_id=event_id,
        mapper_profile="test-order-v1",
        account_fingerprint=FP,
        client_order_id="cid-evidence",
        broker_token=None,
        broker_order_id=broker_order_id,
        order_ref=None,
        trade_id=None,
        evidence_type=evidence_type,
        requested_status=status,
        filled_quantity=filled,
        observed_at_ms=1_700_000_000_000,
        raw_payload_ref="test://" + event_id,
        raw_status=None,
    ))


def test_exact_replay_is_audited_but_applied_once(tmp_path):
    conn, repo, _, oms, broker_order_id = _stack(tmp_path)

    first = _ingest(
        oms,
        broker_order_id,
        event_id="evt-partial-1",
        status=OrderStatus.PARTIALLY_FILLED,
        filled=50,
    )
    second = _ingest(
        oms,
        broker_order_id,
        event_id="evt-partial-1",
        status=OrderStatus.PARTIALLY_FILLED,
        filled=50,
    )

    assert first.duplicate is False
    assert first.disposition is TransitionDisposition.APPLIED
    assert second.duplicate is True
    assert repo.get_status(FP, "cid-evidence") is OrderStatus.PARTIALLY_FILLED
    assert repo.get_order_row(FP, "cid-evidence")["filled_quantity"] == 50

    observations = oms.list_broker_evidence(FP, "cid-evidence")
    assert [row["classification"] for row in observations] == ["NEW", "NEW", "DUPLICATE"]
    event_count = conn.execute(
        """
        SELECT COUNT(*) FROM order_events
        WHERE account_fingerprint=? AND client_order_id=?
          AND event_type='BROKER_EVIDENCE_PARTIAL_FILL'
        """, (FP, "cid-evidence")
    ).fetchone()[0]
    assert event_count == 1


def test_out_of_order_ack_cannot_downgrade_partial_fill_or_quantity(tmp_path):
    _, repo, _, oms, broker_order_id = _stack(tmp_path)
    _ingest(
        oms,
        broker_order_id,
        event_id="evt-partial",
        status=OrderStatus.PARTIALLY_FILLED,
        filled=50,
    )

    normalized_duplicate = _ingest(
        oms,
        broker_order_id,
        event_id="evt-old-ack",
        status=OrderStatus.ACKNOWLEDGED,
        filled=0,
    )

    # The shared broker-fact normalizer combines the stale ACK with the already
    # known fill=50 and normalizes it to PARTIALLY_FILLED before FSM evaluation.
    assert normalized_duplicate.disposition is TransitionDisposition.DUPLICATE_IGNORED
    assert normalized_duplicate.status is OrderStatus.PARTIALLY_FILLED
    row = repo.get_order_row(FP, "cid-evidence")
    assert row["status"] == OrderStatus.PARTIALLY_FILLED.value
    assert row["filled_quantity"] == 50


def test_late_partial_after_fill_cannot_downgrade_terminal_fact(tmp_path):
    _, repo, _, oms, broker_order_id = _stack(tmp_path)
    _ingest(
        oms,
        broker_order_id,
        event_id="evt-fill",
        status=OrderStatus.FILLED,
        filled=100,
    )

    normalized_duplicate = _ingest(
        oms,
        broker_order_id,
        event_id="evt-late-partial",
        status=OrderStatus.PARTIALLY_FILLED,
        filled=50,
    )

    assert normalized_duplicate.disposition is TransitionDisposition.DUPLICATE_IGNORED
    row = repo.get_order_row(FP, "cid-evidence")
    assert row["status"] == OrderStatus.FILLED.value
    assert row["filled_quantity"] == 100


def test_ack_with_positive_fill_is_rejected_by_v1_model(tmp_path):
    _, repo, _, oms, broker_order_id = _stack(tmp_path)

    with pytest.raises(ValueError, match="ORDER_ACCEPTED"):
        _ingest(
            oms,
            broker_order_id,
            event_id="evt-ack-with-fill",
            status=OrderStatus.ACKNOWLEDGED,
            filled=40,
        )
    row = repo.get_order_row(FP, "cid-evidence")
    assert row["status"] == OrderStatus.ACKNOWLEDGED.value
    assert row["filled_quantity"] == 0


def test_filled_status_with_short_quantity_fails_closed(tmp_path):
    _, repo, _, oms, broker_order_id = _stack(tmp_path)

    with pytest.raises(BrokerEvidenceConflict, match="filled_status_quantity_mismatch"):
        _ingest(
            oms,
            broker_order_id,
            event_id="evt-bad-filled",
            status=OrderStatus.FILLED,
            filled=50,
        )

    row = repo.get_order_row(FP, "cid-evidence")
    assert row["status"] == OrderStatus.MANUAL_REVIEW.value
    assert row["filled_quantity"] == 0


def test_same_source_event_id_with_changed_fact_fails_closed_and_is_retained(tmp_path):
    _, _, _, oms, broker_order_id = _stack(tmp_path)
    _ingest(
        oms,
        broker_order_id,
        event_id="evt-reused",
        status=OrderStatus.PARTIALLY_FILLED,
        filled=50,
    )

    with pytest.raises(BrokerEvidenceConflict, match="source_event_id_reused"):
        _ingest(
            oms,
            broker_order_id,
            event_id="evt-reused",
            status=OrderStatus.FILLED,
            filled=100,
        )

    observations = oms.list_broker_evidence(FP, "cid-evidence")
    assert [row["classification"] for row in observations] == ["NEW", "NEW", "CONFLICT"]


def test_broker_order_identity_mismatch_fails_closed(tmp_path):
    _, repo, _, oms, _ = _stack(tmp_path)

    with pytest.raises(BrokerEvidenceConflict, match="broker_order_id_mismatch"):
        _ingest(
            oms,
            "SIM-WRONG",
            event_id="evt-wrong-order",
            status=OrderStatus.PARTIALLY_FILLED,
            filled=10,
        )

    assert repo.get_status(FP, "cid-evidence") is OrderStatus.MANUAL_REVIEW


def test_distinct_terminal_broker_facts_force_manual_review(tmp_path):
    _, repo, _, oms, broker_order_id = _stack(tmp_path)
    _ingest(
        oms,
        broker_order_id,
        event_id="evt-fill-terminal",
        status=OrderStatus.FILLED,
        filled=100,
    )

    with pytest.raises(BrokerEvidenceConflict, match="terminal_broker_fact_conflict"):
        _ingest(
            oms,
            broker_order_id,
            event_id="evt-cancel-conflict",
            status=OrderStatus.CANCELLED,
            filled=50,
        )

    row = repo.get_order_row(FP, "cid-evidence")
    assert row["status"] == OrderStatus.MANUAL_REVIEW.value
    assert row["filled_quantity"] == 100


def test_cancelled_then_higher_fill_forces_manual_review_and_keeps_max_fill(tmp_path):
    _, repo, _, oms, broker_order_id = _stack(tmp_path)
    _ingest(
        oms,
        broker_order_id,
        event_id="evt-partial-before-cancel",
        status=OrderStatus.PARTIALLY_FILLED,
        filled=50,
    )
    _ingest(
        oms,
        broker_order_id,
        event_id="evt-cancel-terminal",
        status=OrderStatus.CANCELLED,
        filled=50,
    )

    with pytest.raises(BrokerEvidenceConflict, match="gained fill"):
        _ingest(
            oms,
            broker_order_id,
            event_id="evt-late-higher-fill",
            status=OrderStatus.PARTIALLY_FILLED,
            filled=75,
        )

    row = repo.get_order_row(FP, "cid-evidence")
    assert row["status"] == OrderStatus.MANUAL_REVIEW.value
    assert row["filled_quantity"] == 75


def test_impossible_overfill_fails_closed_without_mutating_order(tmp_path):
    _, repo, _, oms, broker_order_id = _stack(tmp_path)

    with pytest.raises(BrokerEvidenceConflict, match="filled_quantity_exceeds_order_quantity"):
        _ingest(
            oms,
            broker_order_id,
            event_id="evt-overfill",
            status=OrderStatus.FILLED,
            filled=101,
        )

    row = repo.get_order_row(FP, "cid-evidence")
    assert row["status"] == OrderStatus.MANUAL_REVIEW.value
    assert row["filled_quantity"] == 0


def test_fenced_old_leader_cannot_write_callback_observation_or_aggregate(tmp_path):
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
    result = old.submit_intent(_intent(), _decision())
    assert result.status is OrderStatus.ACKNOWLEDGED
    broker_order_id = result.broker_order_id
    assert broker_order_id is not None

    clock.advance(seconds=6)
    successor = OfflineOms(repo2, driver, leader_lease_seconds=5, clock=clock)

    with pytest.raises(OmsLeaderLost):
        _ingest(
            old,
            broker_order_id,
            event_id="evt-from-fenced-leader",
            status=OrderStatus.PARTIALLY_FILLED,
            filled=25,
        )

    row = repo2.get_order_row(FP, "cid-evidence")
    assert row["status"] == OrderStatus.ACKNOWLEDGED.value
    assert row["filled_quantity"] == 0
    assert len(successor.list_broker_evidence(FP, "cid-evidence")) == 1

    accepted = _ingest(
        successor,
        broker_order_id,
        event_id="evt-from-current-leader",
        status=OrderStatus.PARTIALLY_FILLED,
        filled=25,
    )
    assert accepted.status is OrderStatus.PARTIALLY_FILLED
    assert len(successor.list_broker_evidence(FP, "cid-evidence")) == 2

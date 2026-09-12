from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from bigqmt_autotrader.domain import (
    DuplicateClientOrderId,
    OrderIntent,
    OrderStatus,
    RiskDecision,
    RiskReasonCode,
    Side,
)
from bigqmt_autotrader.drivers import SimulatedDriver, SubmitFailureMode
from bigqmt_autotrader.oms import (
    OfflineOms,
    OmsNotReconciled,
    OmsRepository,
    connect_database,
    initialize_database,
)


def intent(client_order_id="cid-1"):
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
        signal_id="signal-1",
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
    return conn, repo, driver, oms


def test_database_uses_wal(tmp_path):
    conn, *_ = make_stack(tmp_path)
    assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"


def test_new_session_must_reconcile_before_accepting_intent(tmp_path):
    _, _, _, oms = make_stack(tmp_path)
    with pytest.raises(OmsNotReconciled):
        oms.submit_intent(intent(), accept_decision())


def test_normal_submit_is_durable_and_called_once(tmp_path):
    _, repo, driver, oms = make_stack(tmp_path)
    oms.recover()
    result = oms.submit_intent(intent(), accept_decision())
    assert result.status is OrderStatus.ACKNOWLEDGED
    assert repo.get_status("account-A", "cid-1") is OrderStatus.ACKNOWLEDGED
    assert driver.submit_call_count("account-A", "cid-1") == 1
    row = repo.get_order_row("account-A", "cid-1")
    assert row["submit_call_started"] == 1


def test_duplicate_client_order_id_never_submits_twice(tmp_path):
    _, _, driver, oms = make_stack(tmp_path)
    oms.recover()
    oms.submit_intent(intent(), accept_decision())
    with pytest.raises(DuplicateClientOrderId):
        oms.submit_intent(intent(), accept_decision())
    assert driver.submit_call_count("account-A", "cid-1") == 1


def test_timeout_after_accept_enters_unknown_then_reconciles_without_resubmit(tmp_path):
    _, repo, driver, oms = make_stack(tmp_path)
    oms.recover()
    driver.fail_next_submit(SubmitFailureMode.TIMEOUT_AFTER_ACCEPT)
    result = oms.submit_intent(intent(), accept_decision())
    assert result.status is OrderStatus.UNKNOWN
    assert driver.submit_call_count("account-A", "cid-1") == 1

    oms.close()
    restarted = OfflineOms(repo, driver)
    restarted.recover()
    assert repo.get_status("account-A", "cid-1") is OrderStatus.ACKNOWLEDGED
    assert driver.submit_call_count("account-A", "cid-1") == 1


def test_timeout_before_accept_goes_to_manual_review_and_is_not_retried(tmp_path):
    _, repo, driver, oms = make_stack(tmp_path)
    oms.recover()
    driver.fail_next_submit(SubmitFailureMode.TIMEOUT_BEFORE_ACCEPT)
    result = oms.submit_intent(intent(), accept_decision())
    assert result.status is OrderStatus.UNKNOWN

    oms.close()
    restarted = OfflineOms(repo, driver)
    restarted.recover()
    assert repo.get_status("account-A", "cid-1") is OrderStatus.MANUAL_REVIEW
    assert driver.submit_call_count("account-A", "cid-1") == 1


def test_crash_after_submit_reservation_before_side_effect_never_resubmits(tmp_path):
    _, repo, driver, oms = make_stack(tmp_path)
    oms.recover()
    order_intent = intent()
    repo.create_intent(order_intent)
    repo.record_risk_decision("account-A", "cid-1", accept_decision())
    repo.prepare_submit("account-A", "cid-1")
    assert repo.get_status("account-A", "cid-1") is OrderStatus.SUBMITTING
    assert driver.submit_call_count("account-A", "cid-1") == 0

    oms.close()
    restarted = OfflineOms(repo, driver)
    restarted.recover()
    assert repo.get_status("account-A", "cid-1") is OrderStatus.MANUAL_REVIEW
    assert driver.submit_call_count("account-A", "cid-1") == 0


def test_event_log_keeps_reconciliation_evidence(tmp_path):
    _, repo, driver, oms = make_stack(tmp_path)
    oms.recover()
    driver.fail_next_submit(SubmitFailureMode.TIMEOUT_AFTER_ACCEPT)
    oms.submit_intent(intent(), accept_decision())
    oms.close()
    restarted = OfflineOms(repo, driver)
    restarted.recover()
    event_types = [row["event_type"] for row in repo.list_events("account-A", "cid-1")]
    assert "SUBMIT_OUTCOME_UNKNOWN" in event_types
    assert "STARTUP_RECONCILE_BEGIN" in event_types
    assert "RECONCILE_BROKER_EVIDENCE" in event_types

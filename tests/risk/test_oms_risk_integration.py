from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from bigqmt_autotrader.domain import OrderIntent, OrderStatus, RiskReasonCode, Side
from bigqmt_autotrader.drivers import SimulatedDriver
from bigqmt_autotrader.oms import OfflineOms, OmsRepository, connect_database, initialize_database
from bigqmt_autotrader.risk import (
    AccountRiskSnapshot,
    RiskPolicy,
    RiskSnapshot,
    RuntimeMode,
    SecurityRiskSnapshot,
    StrategyPolicy,
    StrategyRiskSnapshot,
)


TZ = timezone(timedelta(hours=8))
NOW = datetime(2026, 9, 12, 10, 0, tzinfo=TZ)


def _intent(client_order_id="cid-p2-integration"):
    return OrderIntent(
        client_order_id=client_order_id,
        strategy_id="strategyA",
        strategy_version="git:v1",
        account_fingerprint="sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        symbol="000333.SZ",
        side=Side.BUY,
        quantity=100,
        limit_price=Decimal("75.00"),
        created_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(minutes=10),
        signal_id="signal-p2-integration",
        reason_code="TARGET_POSITION_REBALANCE",
    )


def _policy():
    return RiskPolicy(
        rule_version="p2-integration-v1",
        expected_account_fingerprint="sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        permitted_execution_modes=frozenset({RuntimeMode.SIMULATION}),
        require_qmt_healthy=False,
        account_max_age_seconds=30,
        strategy_max_age_seconds=30,
        market_max_age_seconds=5,
        min_cash_buffer=Decimal("10000"),
        fee_buffer_rate=Decimal("0.002"),
        max_account_gross_exposure=Decimal("800000"),
        max_daily_loss_abs=Decimal("50000"),
        max_daily_turnover=Decimal("1000000"),
        max_daily_orders=100,
        max_daily_cancels=50,
        max_order_notional=Decimal("100000"),
        max_security_gross_exposure=Decimal("200000"),
        max_price_deviation_rate=Decimal("0.10"),
        strategy=StrategyPolicy(
            strategy_id="strategyA",
            allowed_versions=frozenset({"git:v1"}),
            allowed_symbols=frozenset({"000333.SZ"}),
            max_gross_exposure=Decimal("300000"),
            max_daily_turnover=Decimal("500000"),
            max_position_count=10,
        ),
    )


def _snapshot(*, mode=RuntimeMode.SIMULATION):
    return RiskSnapshot(
        mode=mode,
        database_healthy=True,
        oms_healthy=True,
        leader_held=True,
        reconciliation_complete=True,
        qmt_healthy=False,
        market_open=True,
        global_ambiguity_block=False,
        blocked_symbols=frozenset(),
        account=AccountRiskSnapshot(
            account_fingerprint="sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            available_cash=Decimal("500000"),
            gross_exposure=Decimal("300000"),
            daily_pnl=Decimal("1000"),
            daily_turnover=Decimal("100000"),
            daily_order_count=5,
            daily_cancel_count=2,
            observed_at=NOW - timedelta(seconds=1),
        ),
        strategy=StrategyRiskSnapshot(
            strategy_id="strategyA",
            strategy_version="git:v1",
            gross_exposure=Decimal("100000"),
            security_gross_exposure=Decimal("50000"),
            daily_turnover=Decimal("50000"),
            position_count=3,
            heartbeat_at=NOW - timedelta(seconds=1),
        ),
        security=SecurityRiskSnapshot(
            symbol="000333.SZ",
            tick_size=Decimal("0.01"),
            lower_price_limit=Decimal("67.50"),
            upper_price_limit=Decimal("82.50"),
            reference_price=Decimal("75.00"),
            buy_lot_size=100,
            sell_lot_size=100,
            sellable_quantity=1000,
            gross_exposure=Decimal("50000"),
            observed_at=NOW - timedelta(seconds=1),
        ),
    )


def _stack(tmp_path):
    conn = connect_database(tmp_path / "oms.sqlite3")
    initialize_database(conn)
    repo = OmsRepository(conn)
    driver = SimulatedDriver()
    oms = OfflineOms(repo, driver, clock=lambda: NOW)
    oms.recover()
    return repo, driver, oms


def test_public_oms_entry_evaluates_accepts_and_persists_risk_before_submit(tmp_path):
    repo, driver, oms = _stack(tmp_path)

    result = oms.submit_intent(_intent(), _snapshot(), _policy())

    assert result.status is OrderStatus.ACKNOWLEDGED
    assert result.risk_evaluation is not None
    assert result.risk_evaluation.decision.accepted is True
    assert result.risk_evaluation.decision.reason_code is RiskReasonCode.OK
    assert driver.submit_call_count("sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "cid-p2-integration") == 1
    persisted = repo.conn.execute(
        "SELECT accepted, reason_code, rule_version, snapshot_hash FROM risk_decisions "
        "WHERE account_fingerprint=? AND client_order_id=?",
        ("sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "cid-p2-integration"),
    ).fetchone()
    assert persisted["accepted"] == 1
    assert persisted["reason_code"] == RiskReasonCode.OK.value
    assert persisted["rule_version"] == "p2-integration-v1"
    assert persisted["snapshot_hash"].startswith("sha256:")


def test_public_oms_entry_rejects_before_submit_and_persists_primary_reason(tmp_path):
    repo, driver, oms = _stack(tmp_path)
    disabled = _snapshot(mode=RuntimeMode.DISABLED)

    result = oms.submit_intent(_intent(), disabled, _policy())

    assert result.status is OrderStatus.RISK_REJECTED
    assert result.risk_evaluation is not None
    assert result.risk_evaluation.decision.accepted is False
    assert result.risk_evaluation.decision.reason_code is RiskReasonCode.MODE_NOT_ARMED
    assert driver.submit_call_count("sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "cid-p2-integration") == 0
    persisted = repo.conn.execute(
        "SELECT accepted, reason_code FROM risk_decisions "
        "WHERE account_fingerprint=? AND client_order_id=?",
        ("sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "cid-p2-integration"),
    ).fetchone()
    assert persisted["accepted"] == 0
    assert persisted["reason_code"] == RiskReasonCode.MODE_NOT_ARMED.value


def test_live_named_mode_is_still_rejected_by_p2_default_policy(tmp_path):
    _, driver, oms = _stack(tmp_path)
    live_named = _snapshot(mode=RuntimeMode.LIVE_ARMED)

    result = oms.submit_intent(_intent("cid-live-name"), live_named, _policy())

    assert result.status is OrderStatus.RISK_REJECTED
    assert result.risk_evaluation.decision.reason_code is RiskReasonCode.MODE_NOT_ARMED
    assert driver.submit_call_count("sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "cid-live-name") == 0

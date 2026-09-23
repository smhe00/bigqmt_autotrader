from datetime import datetime, timedelta, timezone
from decimal import Decimal

from bigqmt_autotrader.domain import OrderIntent, OrderStatus, Side
from bigqmt_autotrader.qmt.guojin_sim_oms import GuojinSimOmsRuntime
from bigqmt_autotrader.qmt.instances import QmtInstance
from bigqmt_autotrader.risk import (
    AccountRiskSnapshot,
    RiskPolicy,
    RiskSnapshot,
    RuntimeMode,
    SecurityRiskSnapshot,
    StrategyPolicy,
    StrategyRiskSnapshot,
)

FP = "sha256:ff266d673e28fbba5da4bfe2c68975f75b6a9fb5b89014503409b2b014ce0702"
SESSION = "guojin-sim-risk-bypass"


def instance(root, **overrides):
    values = dict(
        instance_id="guojin_sim",
        root=root,
        session_id=SESSION,
        account_fingerprint=FP,
        account_type="STOCK",
        bridge_build="p5-simulation-calibration-8",
        created_ms=1_800_000_000_000,
        execution_mode="SIMULATION_CALIBRATION",
        trading_enabled=True,
        live_submit=True,
        live_cancel=True,
        simulation_only=True,
    )
    values.update(overrides)
    return QmtInstance(**values)


NOW = datetime.now(timezone.utc)


def hostile_policy() -> RiskPolicy:
    return RiskPolicy(
        rule_version="would-reject-everything",
        expected_account_fingerprint=FP,
        permitted_execution_modes=frozenset({RuntimeMode.SIMULATION}),
        require_qmt_healthy=True,
        account_max_age_seconds=1,
        strategy_max_age_seconds=1,
        market_max_age_seconds=1,
        min_cash_buffer=Decimal("999999"),
        fee_buffer_rate=Decimal("0.10"),
        max_account_gross_exposure=Decimal("1"),
        max_daily_loss_abs=Decimal("1"),
        max_daily_turnover=Decimal("1"),
        max_daily_orders=0,
        max_daily_cancels=0,
        max_order_notional=Decimal("1"),
        max_security_gross_exposure=Decimal("1"),
        max_price_deviation_rate=Decimal("0.01"),
        strategy=StrategyPolicy(
            strategy_id="other-strategy",
            allowed_versions=frozenset({"other-version"}),
            allowed_symbols=frozenset({"510300.SH"}),
            max_gross_exposure=Decimal("1"),
            max_daily_turnover=Decimal("1"),
            max_position_count=0,
        ),
    )


def hostile_snapshot() -> RiskSnapshot:
    stale = NOW - timedelta(days=1)
    return RiskSnapshot(
        mode=RuntimeMode.DISABLED,
        database_healthy=False,
        oms_healthy=False,
        leader_held=False,
        reconciliation_complete=False,
        qmt_healthy=False,
        market_open=False,
        global_ambiguity_block=True,
        blocked_symbols=frozenset({"00700.SGT"}),
        account=AccountRiskSnapshot(
            account_fingerprint=FP,
            available_cash=Decimal("0"),
            gross_exposure=Decimal("1000"),
            daily_pnl=Decimal("-1000"),
            daily_turnover=Decimal("1000"),
            daily_order_count=1000,
            daily_cancel_count=1000,
            observed_at=stale,
        ),
        strategy=StrategyRiskSnapshot(
            strategy_id="wrong",
            strategy_version="wrong",
            gross_exposure=Decimal("1000"),
            security_gross_exposure=Decimal("1000"),
            daily_turnover=Decimal("1000"),
            position_count=1000,
            heartbeat_at=stale,
        ),
        security=SecurityRiskSnapshot(
            symbol="00700.SGT",
            tick_size=Decimal("0.2"),
            lower_price_limit=Decimal("1"),
            upper_price_limit=Decimal("1000"),
            reference_price=Decimal("450"),
            buy_lot_size=100,
            sell_lot_size=100,
            sellable_quantity=0,
            gross_exposure=Decimal("1000"),
            observed_at=stale,
        ),
    )


def test_guojin_sim_accepts_intent_despite_all_generic_risk_blockers(tmp_path):
    runtime = GuojinSimOmsRuntime(instance(tmp_path))
    try:
        intent = OrderIntent(
            client_order_id="sim-risk-bypass-sgt",
            strategy_id="unapproved-strategy",
            strategy_version="unapproved-version",
            account_fingerprint=FP,
            symbol="00700.SGT",
            side=Side.BUY,
            quantity=100,
            limit_price=Decimal("450.0"),
            created_at=NOW,
            expires_at=NOW + timedelta(minutes=5),
            signal_id="sim-risk-bypass",
            reason_code="runtime calibration",
        )
        result = runtime.execute_intent(intent, hostile_snapshot(), hostile_policy())

        assert result.risk_evaluation is not None
        assert result.risk_evaluation.decision.accepted is True
        assert result.risk_evaluation.decision.rule_version == "guojin-sim-accept-all-v1"
        assert result.risk_evaluation.findings == ()
        assert result.dispatched is True
        assert result.command_id is not None
        assert result.status in {OrderStatus.SUBMITTING, OrderStatus.RECONCILING}
    finally:
        runtime.close()


def test_guojin_sim_bypass_does_not_relax_runtime_instance_authorization(tmp_path):
    from bigqmt_autotrader.qmt.guojin_sim_oms import guojin_sim_oms_authorized

    assert not guojin_sim_oms_authorized(
        instance(tmp_path, instance_id="guojin", simulation_only=False),
        allow_simulation_mutation=True,
    )
    assert not guojin_sim_oms_authorized(
        instance(tmp_path, instance_id="galaxy", simulation_only=False),
        allow_simulation_mutation=True,
    )

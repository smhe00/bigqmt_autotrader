from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from bigqmt_autotrader.domain import OrderIntent, RiskReasonCode, Side
from bigqmt_autotrader.market_data import MarketDataService, MarketQuote
from bigqmt_autotrader.oms import connect_database, initialize_database
from bigqmt_autotrader.operations import (
    HealthComponent,
    HealthObservation,
    HealthRegistry,
    OperationsControl,
    RuntimeModeController,
)
from bigqmt_autotrader.risk import (
    ActiveBrokerOrderFact,
    DailyRiskLedger,
    ExternalOrderRiskClassifier,
    RiskPolicy,
    RuntimeMode,
    SecurityRiskReference,
    StrategyPolicy,
)
from bigqmt_autotrader.service import (
    AccountState,
    ExecutionRuntimeCoordinator,
    RuntimeRiskAssembler,
    StrategyState,
)
from bigqmt_autotrader.strategy_api import StrategyHeartbeat, StrategyRuntimeService


TZ = timezone(timedelta(hours=8))
NOW = datetime(2026, 9, 23, 14, 0, tzinfo=TZ)
DAY = date(2026, 9, 23)


def policy():
    return RiskPolicy(
        rule_version="coordinator-v1",
        expected_account_fingerprint="acct",
        permitted_execution_modes=frozenset({RuntimeMode.SIMULATION}),
        require_qmt_healthy=True,
        account_max_age_seconds=10,
        strategy_max_age_seconds=5,
        market_max_age_seconds=5,
        min_cash_buffer=Decimal("100"),
        fee_buffer_rate=Decimal("0.01"),
        max_account_gross_exposure=Decimal("1000000"),
        max_daily_loss_abs=Decimal("10000"),
        max_daily_turnover=Decimal("1000000"),
        max_daily_orders=100,
        max_daily_cancels=100,
        max_order_notional=Decimal("100000"),
        max_security_gross_exposure=Decimal("500000"),
        max_price_deviation_rate=Decimal("0.10"),
        strategy=StrategyPolicy(
            strategy_id="s1",
            allowed_versions=frozenset({"v1"}),
            allowed_symbols=frozenset({"510300.SH"}),
            max_gross_exposure=Decimal("500000"),
            max_daily_turnover=Decimal("500000"),
            max_position_count=10,
        ),
    )


def setup(tmp_path):
    conn = connect_database(tmp_path / "coordinator.sqlite3")
    initialize_database(conn)

    market = MarketDataService()
    market.ingest(
        MarketQuote(
            symbol="510300.SH",
            last_price=Decimal("4.64"),
            broker_time=NOW - timedelta(seconds=1),
            observed_at=NOW - timedelta(seconds=1),
            source="qmt_tick",
        )
    )
    ledger = DailyRiskLedger(conn)
    ledger.record_pnl_snapshot(
        snapshot_key="pnl",
        account_fingerprint="acct",
        trading_date=DAY,
        daily_pnl=Decimal("0"),
        observed_at=NOW - timedelta(seconds=1),
        source="account_query",
    )
    strategies = StrategyRuntimeService()
    strategies.ingest_heartbeat(
        StrategyHeartbeat(
            strategy_id="s1",
            strategy_version="v1",
            session_id="strategy-1",
            sequence=1,
            observed_at=NOW - timedelta(seconds=1),
        )
    )
    assembler = RuntimeRiskAssembler(
        market_data=market,
        daily_risk=ledger,
        strategies=strategies,
    )

    registry = HealthRegistry()
    for component in HealthComponent:
        registry.observe(
            HealthObservation(
                component=component,
                healthy=True,
                observed_at=NOW,
            )
        )
    modes = RuntimeModeController(
        conn,
        runtime_session_id="host-1",
        started_at=NOW,
    )
    operations = OperationsControl(modes=modes, health=registry)
    operations.enter_observe(
        request_id="observe",
        actor="test",
        reason="preflight",
        now=NOW,
        max_age_seconds=5,
    )

    coordinator = ExecutionRuntimeCoordinator(
        operations=operations,
        risk_assembler=assembler,
        policy=policy(),
        health_max_age_seconds=5,
    )
    return registry, operations, coordinator


def intent():
    return OrderIntent(
        client_order_id="coid-1",
        strategy_id="s1",
        strategy_version="v1",
        account_fingerprint="acct",
        symbol="510300.SH",
        side=Side.BUY,
        quantity=100,
        limit_price=Decimal("4.64"),
        created_at=NOW,
        expires_at=NOW + timedelta(seconds=30),
        signal_id="sig-1",
        reason_code="test",
    )


def account():
    return AccountState(
        account_fingerprint="acct",
        available_cash=Decimal("100000"),
        gross_exposure=Decimal("0"),
        observed_at=NOW - timedelta(seconds=1),
    )


def strategy():
    return StrategyState(
        strategy_id="s1",
        strategy_version="v1",
        gross_exposure=Decimal("0"),
        security_gross_exposure=Decimal("0"),
        position_count=0,
    )


def security():
    return SecurityRiskReference(
        symbol="510300.SH",
        tick_size=Decimal("0.001"),
        lower_price_limit=Decimal("4.0"),
        upper_price_limit=Decimal("5.0"),
        buy_lot_size=100,
        sell_lot_size=100,
        sellable_quantity=0,
        gross_exposure=Decimal("0"),
    )


def evaluate(coordinator):
    return coordinator.evaluate_intent(
        intent(),
        trading_date=DAY,
        now=NOW,
        market_open=True,
        global_ambiguity_block=False,
        blocked_symbols=frozenset(),
        account=account(),
        strategy=strategy(),
        security=security(),
    )


def test_coordinator_accepts_only_after_explicit_simulation_arm(tmp_path):
    _, operations, coordinator = setup(tmp_path)

    before = evaluate(coordinator)
    assert not before.risk.decision.accepted
    assert before.risk.decision.reason_code is RiskReasonCode.MODE_NOT_ARMED
    assert before.operations.mode is RuntimeMode.OBSERVE

    operations.arm_simulation(
        request_id="sim",
        actor="test",
        reason="arm",
        now=NOW,
        max_age_seconds=5,
    )
    after = evaluate(coordinator)
    assert after.risk.decision.accepted
    assert after.risk.decision.reason_code is RiskReasonCode.OK
    assert after.operations.mode is RuntimeMode.SIMULATION


def test_unhealthy_qmt_rejects_even_if_mode_was_previously_armed(tmp_path):
    registry, operations, coordinator = setup(tmp_path)
    operations.arm_simulation(
        request_id="sim",
        actor="test",
        reason="arm",
        now=NOW,
        max_age_seconds=5,
    )
    registry.observe(
        HealthObservation(
            component=HealthComponent.QMT,
            healthy=False,
            observed_at=NOW + timedelta(milliseconds=1),
            detail="disconnect",
        )
    )

    result = coordinator.evaluate_intent(
        intent(),
        trading_date=DAY,
        now=NOW + timedelta(milliseconds=1),
        market_open=True,
        global_ambiguity_block=False,
        blocked_symbols=frozenset(),
        account=AccountState(
            account_fingerprint="acct",
            available_cash=Decimal("100000"),
            gross_exposure=Decimal("0"),
            observed_at=NOW,
        ),
        strategy=strategy(),
        security=security(),
    )
    assert not result.risk.decision.accepted
    assert result.risk.decision.reason_code is RiskReasonCode.DATA_STALE
    assert not result.operations.health.qmt_healthy


def test_external_manual_order_blocks_symbol_and_counts_pending_buy_exposure(tmp_path):
    _, operations, coordinator = setup(tmp_path)
    operations.arm_simulation(
        request_id="sim-external",
        actor="test",
        reason="arm",
        now=NOW,
        max_age_seconds=5,
    )
    external = ExternalOrderRiskClassifier(
        registered_system_tokens=set()
    ).classify(
        [
            ActiveBrokerOrderFact(
                source_event_id="manual-order-1",
                symbol="510300.SH",
                side=Side.BUY,
                quantity=100,
                filled_quantity=0,
                limit_price=Decimal("4.64"),
                broker_token=None,
                observed_at=NOW,
            )
        ]
    )

    result = coordinator.evaluate_intent(
        intent(),
        trading_date=DAY,
        now=NOW,
        market_open=True,
        global_ambiguity_block=False,
        blocked_symbols=frozenset(),
        external_orders=external,
        account=account(),
        strategy=strategy(),
        security=security(),
    )

    assert not result.risk.decision.accepted
    assert result.risk.decision.reason_code is RiskReasonCode.UNKNOWN_ORDER
    assert "510300.SH" in result.snapshot.blocked_symbols
    assert result.snapshot.account.gross_exposure == Decimal("464.00")
    assert result.snapshot.security.gross_exposure == Decimal("464.00")

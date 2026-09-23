from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from bigqmt_autotrader.market_data import MarketDataService, MarketQuote
from bigqmt_autotrader.oms import connect_database, initialize_database
from bigqmt_autotrader.operations import RuntimeHealth
from bigqmt_autotrader.risk import (
    DailyRiskLedger,
    RiskPolicy,
    RuntimeMode,
    SecurityRiskReference,
    StrategyPolicy,
)
from bigqmt_autotrader.service import (
    AccountState,
    RuntimeRiskAssembler,
    RuntimeRiskUnavailable,
    StrategyState,
)
from bigqmt_autotrader.strategy_api import StrategyHeartbeat, StrategyRuntimeService, StrategyStale


TZ = timezone(timedelta(hours=8))
NOW = datetime(2026, 9, 23, 13, 30, tzinfo=TZ)
DAY = date(2026, 9, 23)


def policy():
    return RiskPolicy(
        rule_version="runtime-assembler-v1",
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


def health():
    return RuntimeHealth(
        database_healthy=True,
        oms_healthy=True,
        leader_held=True,
        reconciliation_complete=True,
        qmt_healthy=True,
        market_data_healthy=True,
        strategy_healthy=True,
    )


def setup_runtime(tmp_path, *, pnl_age=1, heartbeat_age=1, quote_age=1):
    conn = connect_database(tmp_path / "runtime.sqlite3")
    initialize_database(conn)
    ledger = DailyRiskLedger(conn)
    ledger.record_order_submit(
        event_key="submit-1", account_fingerprint="acct", strategy_id="s1",
        trading_date=DAY, observed_at=NOW, source_ref="cmd-1"
    )
    ledger.record_cancel_request(
        event_key="cancel-1", account_fingerprint="acct", strategy_id="s1",
        trading_date=DAY, observed_at=NOW, source_ref="cmd-c1"
    )
    ledger.record_trade(
        event_key="trade-1", account_fingerprint="acct", strategy_id="s1",
        trading_date=DAY, notional=Decimal("464"), observed_at=NOW, source_ref="deal-1"
    )
    ledger.record_pnl_snapshot(
        snapshot_key="pnl-1", account_fingerprint="acct", trading_date=DAY,
        daily_pnl=Decimal("-12.5"), observed_at=NOW - timedelta(seconds=pnl_age),
        source="account_query"
    )

    market = MarketDataService()
    market.ingest(
        MarketQuote(
            symbol="510300.SH",
            last_price=Decimal("4.64"),
            broker_time=NOW - timedelta(seconds=quote_age),
            observed_at=NOW - timedelta(seconds=quote_age),
            source="qmt_tick",
        )
    )
    strategies = StrategyRuntimeService()
    strategies.ingest_heartbeat(
        StrategyHeartbeat(
            strategy_id="s1", strategy_version="v1", session_id="strategy-session",
            sequence=1, observed_at=NOW - timedelta(seconds=heartbeat_age)
        )
    )
    return conn, RuntimeRiskAssembler(
        market_data=market, daily_risk=ledger, strategies=strategies
    )


def account():
    return AccountState(
        account_fingerprint="acct",
        available_cash=Decimal("100000"),
        gross_exposure=Decimal("10000"),
        observed_at=NOW - timedelta(seconds=1),
    )


def strategy():
    return StrategyState(
        strategy_id="s1",
        strategy_version="v1",
        gross_exposure=Decimal("10000"),
        security_gross_exposure=Decimal("10000"),
        position_count=1,
    )


def security():
    return SecurityRiskReference(
        symbol="510300.SH",
        tick_size=Decimal("0.001"),
        lower_price_limit=Decimal("4.0"),
        upper_price_limit=Decimal("5.0"),
        buy_lot_size=100,
        sell_lot_size=100,
        sellable_quantity=100,
        gross_exposure=Decimal("10000"),
    )


def build(assembler):
    return assembler.build(
        policy=policy(),
        trading_date=DAY,
        now=NOW,
        mode=RuntimeMode.SIMULATION,
        health=health(),
        market_open=True,
        global_ambiguity_block=False,
        blocked_symbols=frozenset(),
        account=account(),
        strategy=strategy(),
        security=security(),
    )


def test_runtime_assembler_sources_daily_counters_heartbeat_and_market_price(tmp_path):
    _, assembler = setup_runtime(tmp_path)
    snapshot = build(assembler)

    assert snapshot.account.daily_order_count == 1
    assert snapshot.account.daily_cancel_count == 1
    assert snapshot.account.daily_turnover == Decimal("464")
    assert snapshot.account.daily_pnl == Decimal("-12.5")
    assert snapshot.strategy.daily_turnover == Decimal("464")
    assert snapshot.strategy.heartbeat_at == NOW - timedelta(seconds=1)
    assert snapshot.security.reference_price == Decimal("4.64")


def test_stale_daily_pnl_fails_before_risk_engine(tmp_path):
    _, assembler = setup_runtime(tmp_path, pnl_age=30)
    with pytest.raises(RuntimeRiskUnavailable, match="daily PnL snapshot is stale"):
        build(assembler)


def test_stale_strategy_heartbeat_fails_before_risk_engine(tmp_path):
    _, assembler = setup_runtime(tmp_path, heartbeat_age=30)
    with pytest.raises(StrategyStale):
        build(assembler)


def test_stale_market_quote_fails_before_risk_engine(tmp_path):
    from bigqmt_autotrader.market_data import MarketDataStale

    _, assembler = setup_runtime(tmp_path, quote_age=30)
    with pytest.raises(MarketDataStale):
        build(assembler)


def test_unhealthy_runtime_facts_are_preserved_for_deterministic_risk_rejection(tmp_path):
    _, assembler = setup_runtime(tmp_path)
    bad_health = RuntimeHealth(
        database_healthy=True,
        oms_healthy=True,
        leader_held=True,
        reconciliation_complete=True,
        qmt_healthy=False,
        market_data_healthy=True,
        strategy_healthy=True,
    )
    snapshot = assembler.build(
        policy=policy(), trading_date=DAY, now=NOW, mode=RuntimeMode.SIMULATION,
        health=bad_health, market_open=True, global_ambiguity_block=False,
        blocked_symbols=frozenset(), account=account(), strategy=strategy(), security=security()
    )
    assert not snapshot.qmt_healthy

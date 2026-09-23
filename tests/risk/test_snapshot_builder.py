from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from bigqmt_autotrader.market_data import (
    MarketDataService,
    MarketDataStale,
    MarketDataUnavailable,
    MarketQuote,
)
from bigqmt_autotrader.risk import (
    AccountRiskSnapshot,
    RiskPolicy,
    RiskSnapshotBuilder,
    RuntimeMode,
    SecurityRiskReference,
    StrategyPolicy,
    StrategyRiskSnapshot,
)


TZ = timezone(timedelta(hours=8))
NOW = datetime(2026, 9, 23, 10, 30, tzinfo=TZ)


def policy() -> RiskPolicy:
    return RiskPolicy(
        rule_version="snapshot-builder-v1",
        expected_account_fingerprint="acct",
        permitted_execution_modes=frozenset({RuntimeMode.SIMULATION}),
        require_qmt_healthy=True,
        account_max_age_seconds=10,
        strategy_max_age_seconds=10,
        market_max_age_seconds=15,
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


def account() -> AccountRiskSnapshot:
    return AccountRiskSnapshot(
        account_fingerprint="acct",
        available_cash=Decimal("100000"),
        gross_exposure=Decimal("10000"),
        daily_pnl=Decimal("0"),
        daily_turnover=Decimal("1000"),
        daily_order_count=1,
        daily_cancel_count=0,
        observed_at=NOW - timedelta(seconds=1),
    )


def strategy() -> StrategyRiskSnapshot:
    return StrategyRiskSnapshot(
        strategy_id="s1",
        strategy_version="v1",
        gross_exposure=Decimal("10000"),
        security_gross_exposure=Decimal("10000"),
        daily_turnover=Decimal("1000"),
        position_count=1,
        heartbeat_at=NOW - timedelta(seconds=1),
    )


def security() -> SecurityRiskReference:
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


def quote(*, broker_age: int = 1, observed_age: int = 0) -> MarketQuote:
    return MarketQuote(
        symbol="510300.SH",
        last_price=Decimal("4.640"),
        broker_time=NOW - timedelta(seconds=broker_age),
        observed_at=NOW - timedelta(seconds=observed_age),
        source="qmt_tick",
    )


def build(service: MarketDataService):
    return RiskSnapshotBuilder(service).build(
        policy=policy(),
        now=NOW,
        mode=RuntimeMode.SIMULATION,
        database_healthy=True,
        oms_healthy=True,
        leader_held=True,
        reconciliation_complete=True,
        qmt_healthy=True,
        market_open=True,
        global_ambiguity_block=False,
        blocked_symbols=frozenset(),
        account=account(),
        strategy=strategy(),
        security=security(),
    )


def test_builder_sources_reference_price_only_from_market_data_service():
    service = MarketDataService()
    service.ingest(quote())

    snapshot = build(service)

    assert snapshot.security.symbol == "510300.SH"
    assert snapshot.security.reference_price == Decimal("4.640")
    assert snapshot.security.observed_at == NOW - timedelta(seconds=1)
    assert snapshot.account is account() or snapshot.account == account()
    assert snapshot.strategy == strategy()


def test_builder_fails_before_risk_evaluation_when_quote_is_missing():
    service = MarketDataService()

    with pytest.raises(MarketDataUnavailable):
        build(service)


def test_builder_fails_before_risk_evaluation_when_broker_tick_is_stale():
    service = MarketDataService()
    service.ingest(quote(broker_age=30))

    with pytest.raises(MarketDataStale, match="broker quote"):
        build(service)


def test_builder_fails_when_local_observation_is_stale():
    service = MarketDataService()
    service.ingest(quote(observed_age=30))

    with pytest.raises(MarketDataStale, match="local observation"):
        build(service)


def test_builder_uses_policy_market_freshness_window():
    service = MarketDataService()
    service.ingest(quote(broker_age=12))
    strict = replace(policy(), market_max_age_seconds=10)

    with pytest.raises(MarketDataStale):
        RiskSnapshotBuilder(service).build(
            policy=strict,
            now=NOW,
            mode=RuntimeMode.SIMULATION,
            database_healthy=True,
            oms_healthy=True,
            leader_held=True,
            reconciliation_complete=True,
            qmt_healthy=True,
            market_open=True,
            global_ambiguity_block=False,
            blocked_symbols=frozenset(),
            account=account(),
            strategy=strategy(),
            security=security(),
        )

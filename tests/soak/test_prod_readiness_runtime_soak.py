from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from bigqmt_autotrader.market_data import MarketDataService, MarketQuote
from bigqmt_autotrader.oms import connect_database, initialize_database
from bigqmt_autotrader.operations import (
    HealthComponent,
    HealthObservation,
    HealthRegistry,
    OperationsControl,
    RuntimeModeController,
)
from bigqmt_autotrader.risk import DailyRiskLedger, RuntimeMode
from bigqmt_autotrader.strategy_api import StrategyHeartbeat, StrategyRuntimeService


TZ = timezone(timedelta(hours=8))
START = datetime(2026, 9, 23, 9, 30, tzinfo=TZ)
DAY = date(2026, 9, 23)


def observe_all_healthy(registry, now):
    for component in HealthComponent:
        registry.observe(
            HealthObservation(
                component=component,
                healthy=True,
                observed_at=now,
            )
        )


def test_quote_and_strategy_streams_remain_monotonic_over_many_cycles():
    market = MarketDataService()
    strategy = StrategyRuntimeService()

    for index in range(1, 1001):
        now = START + timedelta(seconds=index)
        market.ingest(
            MarketQuote(
                symbol="510300.SH",
                last_price=Decimal("4.000") + Decimal(index) / Decimal("100000"),
                broker_time=now,
                observed_at=now,
                source="soak",
            )
        )
        strategy.ingest_heartbeat(
            StrategyHeartbeat(
                strategy_id="s1",
                strategy_version="v1",
                session_id="strategy-session",
                sequence=index,
                observed_at=now,
            )
        )

    final_now = START + timedelta(seconds=1000)
    quote = market.latest("510300.SH", now=final_now, max_age_seconds=1)
    heartbeat = strategy.require_fresh(
        strategy_id="s1",
        strategy_version="v1",
        now=final_now,
        max_age_seconds=1,
    )

    assert market.symbols() == ("510300.SH",)
    assert quote.broker_time == final_now
    assert heartbeat.sequence == 1000


def test_duplicate_daily_facts_do_not_inflate_limits_under_replay_soak(tmp_path):
    conn = connect_database(tmp_path / "ledger.sqlite3")
    initialize_database(conn)
    ledger = DailyRiskLedger(conn)
    now = START

    for _ in range(1000):
        ledger.record_order_submit(
            event_key="submit-1",
            account_fingerprint="acct",
            strategy_id="s1",
            trading_date=DAY,
            observed_at=now,
            source_ref="cmd-1",
        )
        ledger.record_trade(
            event_key="trade-1",
            account_fingerprint="acct",
            strategy_id="s1",
            trading_date=DAY,
            notional=Decimal("464"),
            observed_at=now,
            source_ref="deal-1",
        )
    ledger.record_pnl_snapshot(
        snapshot_key="pnl-1",
        account_fingerprint="acct",
        trading_date=DAY,
        daily_pnl=Decimal("1.23"),
        observed_at=now,
        source="account_query",
    )

    totals = ledger.totals(account_fingerprint="acct", trading_date=DAY)
    assert totals.daily_order_count == 1
    assert totals.daily_turnover == Decimal("464")


def test_repeated_runtime_restarts_never_restore_mutation_authority(tmp_path):
    path = tmp_path / "mode.sqlite3"
    for index in range(20):
        conn = connect_database(path)
        initialize_database(conn)
        now = START + timedelta(minutes=index)
        modes = RuntimeModeController(
            conn,
            runtime_session_id=f"host-{index}",
            started_at=now,
        )
        assert modes.mode is RuntimeMode.DISABLED

        health = HealthRegistry()
        observe_all_healthy(health, now)
        control = OperationsControl(modes=modes, health=health)
        control.enter_observe(
            request_id=f"observe-{index}",
            actor="soak",
            reason="preflight",
            now=now,
            max_age_seconds=5,
        )
        control.arm_simulation(
            request_id=f"sim-{index}",
            actor="soak",
            reason="arm",
            now=now,
            max_age_seconds=5,
        )
        assert modes.mode is RuntimeMode.SIMULATION
        conn.close()

    conn = connect_database(path)
    initialize_database(conn)
    final = RuntimeModeController(
        conn,
        runtime_session_id="host-final",
        started_at=START + timedelta(hours=1),
    )
    assert final.mode is RuntimeMode.DISABLED


def test_health_loss_repeatedly_halts_without_live_mode_escape(tmp_path):
    conn = connect_database(tmp_path / "health.sqlite3")
    initialize_database(conn)

    for cycle in range(10):
        now = START + timedelta(seconds=cycle * 3)
        modes = RuntimeModeController(
            conn,
            runtime_session_id=f"health-host-{cycle}",
            started_at=now,
        )
        registry = HealthRegistry()
        observe_all_healthy(registry, now)
        control = OperationsControl(modes=modes, health=registry)
        control.enter_observe(
            request_id=f"observe-{cycle}",
            actor="soak",
            reason="preflight",
            now=now,
            max_age_seconds=2,
        )
        control.arm_simulation(
            request_id=f"sim-{cycle}",
            actor="soak",
            reason="arm",
            now=now,
            max_age_seconds=2,
        )

        broken_at = now + timedelta(seconds=1)
        registry.observe(
            HealthObservation(
                component=HealthComponent.QMT,
                healthy=False,
                observed_at=broken_at,
                detail="synthetic disconnect",
            )
        )
        assert control.enforce_health(
            request_id=f"halt-{cycle}",
            now=broken_at,
            max_age_seconds=2,
        )
        assert modes.mode is RuntimeMode.HALTED
        assert modes.mode not in {RuntimeMode.LIVE_CANARY, RuntimeMode.LIVE_ARMED}

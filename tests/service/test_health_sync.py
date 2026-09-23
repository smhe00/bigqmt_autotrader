from datetime import datetime, timedelta, timezone
from decimal import Decimal

from bigqmt_autotrader.market_data import MarketDataService, MarketQuote
from bigqmt_autotrader.operations import HealthComponent, HealthRegistry
from bigqmt_autotrader.qmt import IngressDisposition, QmtEvent
from bigqmt_autotrader.qmt.receiver import IngressResult
from bigqmt_autotrader.service import (
    RuntimeHealthSynchronizer,
    StrategyHealthRequirement,
)
from bigqmt_autotrader.strategy_api import (
    StrategyHeartbeat,
    StrategyRuntimeService,
)


TZ = timezone(timedelta(hours=8))
NOW = datetime(2026, 9, 23, 14, 30, tzinfo=TZ)
NOW_MS = int(NOW.timestamp() * 1000)
FP = "sha256:" + "a" * 64


def synchronizer():
    health = HealthRegistry()
    market = MarketDataService()
    strategies = StrategyRuntimeService()
    sync = RuntimeHealthSynchronizer(
        health=health,
        market_data=market,
        strategies=strategies,
        required_symbols=("510300.SH", "01810.SGT"),
        required_strategies=(
            StrategyHealthRequirement("s1", "v1"),
        ),
        market_max_age_seconds=5,
        strategy_max_age_seconds=5,
    )
    return health, market, strategies, sync


def event(*, sequence=1, event_type="account", timestamp_ms=NOW_MS):
    payload = {} if event_type != "snapshot" else {
        "account": [],
        "positions": [],
        "orders": [],
        "deals": [],
        "query_errors": [],
    }
    return QmtEvent.from_mapping(
        {
            "protocol_version": "0.2",
            "session_id": "session-1",
            "sequence": sequence,
            "timestamp_ms": timestamp_ms,
            "event_type": event_type,
            "source": "test",
            "account_fingerprint": FP,
            "account_type": "STOCK",
            "terminal_instance_id": "guojin_sim",
            "payload": payload,
        }
    )


def test_qmt_gap_marks_unhealthy_and_resync_snapshot_recovers():
    health, _, _, sync = synchronizer()

    sync.observe_qmt_ingress(
        IngressResult(
            disposition=IngressDisposition.GAP,
            event=event(sequence=10),
            needs_resync=True,
        )
    )
    first = health.snapshot(now=NOW, max_age_seconds=5)
    assert not first.runtime.qmt_healthy
    assert any(
        alert.component is HealthComponent.QMT
        and alert.reason == "INGRESS_GAP"
        for alert in first.alerts
    )

    recovered_at = NOW + timedelta(seconds=1)
    sync.observe_qmt_ingress(
        IngressResult(
            disposition=IngressDisposition.ACCEPTED,
            event=event(
                sequence=11,
                event_type="snapshot",
                timestamp_ms=int(recovered_at.timestamp() * 1000),
            ),
            needs_resync=False,
        )
    )
    second = health.snapshot(now=recovered_at, max_age_seconds=5)
    assert second.runtime.qmt_healthy


def test_duplicate_qmt_event_does_not_refresh_health_clock():
    health, _, _, sync = synchronizer()
    accepted_at = NOW - timedelta(seconds=4)
    sync.observe_qmt_ingress(
        IngressResult(
            disposition=IngressDisposition.ACCEPTED,
            event=event(timestamp_ms=int(accepted_at.timestamp() * 1000)),
            needs_resync=False,
        )
    )
    assert not sync.observe_qmt_ingress(
        IngressResult(
            disposition=IngressDisposition.DUPLICATE,
            event=event(timestamp_ms=NOW_MS),
            needs_resync=False,
        )
    )
    assert not health.snapshot(
        now=NOW + timedelta(seconds=2),
        max_age_seconds=5,
    ).runtime.qmt_healthy


def test_market_health_requires_every_required_symbol_fresh():
    health, market, _, sync = synchronizer()
    market.ingest(
        MarketQuote(
            symbol="510300.SH",
            last_price=Decimal("4.64"),
            broker_time=NOW - timedelta(seconds=1),
            observed_at=NOW,
            source="test",
        )
    )

    sync.refresh_market_data(now=NOW)
    first = health.snapshot(now=NOW, max_age_seconds=5)
    assert not first.runtime.market_data_healthy
    assert any(
        alert.component is HealthComponent.MARKET_DATA
        and "01810.SGT:MarketDataUnavailable" in alert.reason
        for alert in first.alerts
    )

    later = NOW + timedelta(seconds=1)
    market.ingest(
        MarketQuote(
            symbol="01810.SGT",
            last_price=Decimal("26.60"),
            broker_time=later,
            observed_at=later,
            source="test",
        )
    )
    market.ingest(
        MarketQuote(
            symbol="510300.SH",
            last_price=Decimal("4.65"),
            broker_time=later,
            observed_at=later,
            source="test",
        )
    )
    sync.refresh_market_data(now=later)
    assert health.snapshot(
        now=later,
        max_age_seconds=5,
    ).runtime.market_data_healthy


def test_strategy_health_requires_fresh_matching_heartbeat():
    health, _, strategies, sync = synchronizer()

    sync.refresh_strategies(now=NOW)
    assert not health.snapshot(
        now=NOW,
        max_age_seconds=5,
    ).runtime.strategy_healthy

    later = NOW + timedelta(seconds=1)
    strategies.ingest_heartbeat(
        StrategyHeartbeat(
            strategy_id="s1",
            strategy_version="v1",
            session_id="strategy-session",
            sequence=1,
            observed_at=later,
        )
    )
    sync.refresh_strategies(now=later)
    assert health.snapshot(
        now=later,
        max_age_seconds=5,
    ).runtime.strategy_healthy


def test_restart_does_not_reuse_previous_health_authority():
    first_health, market, strategies, first = synchronizer()
    now = NOW
    for symbol, price in (("510300.SH", "4.64"), ("01810.SGT", "26.60")):
        market.ingest(
            MarketQuote(
                symbol=symbol,
                last_price=Decimal(price),
                broker_time=now,
                observed_at=now,
                source="test",
            )
        )
    strategies.ingest_heartbeat(
        StrategyHeartbeat(
            strategy_id="s1",
            strategy_version="v1",
            session_id="strategy-session",
            sequence=1,
            observed_at=now,
        )
    )
    first.refresh_market_data(now=now)
    first.refresh_strategies(now=now)
    assert first_health.snapshot(
        now=now,
        max_age_seconds=5,
    ).runtime.market_data_healthy

    new_health = HealthRegistry()
    second = RuntimeHealthSynchronizer(
        health=new_health,
        market_data=market,
        strategies=strategies,
        required_symbols=("510300.SH", "01810.SGT"),
        required_strategies=(StrategyHealthRequirement("s1", "v1"),),
        market_max_age_seconds=5,
        strategy_max_age_seconds=5,
    )
    assert not new_health.snapshot(
        now=now,
        max_age_seconds=5,
    ).runtime.ready_for_mutation
    second.refresh_market_data(now=now)
    second.refresh_strategies(now=now)
    # DB/OMS/leader/reconciliation/QMT remain missing; health cannot become
    # mutation-ready just because market/strategy state survived elsewhere.
    assert not new_health.snapshot(
        now=now,
        max_age_seconds=5,
    ).runtime.ready_for_mutation

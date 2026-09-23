from datetime import datetime, timedelta, timezone

from bigqmt_autotrader.operations import (
    HealthComponent,
    HealthObservation,
    HealthRegistry,
)


TZ = timezone(timedelta(hours=8))
NOW = datetime(2026, 9, 23, 11, 30, tzinfo=TZ)


def healthy(component, *, age=0):
    return HealthObservation(
        component=component,
        healthy=True,
        observed_at=NOW - timedelta(seconds=age),
    )


def test_missing_health_facts_fail_closed():
    snapshot = HealthRegistry().snapshot(now=NOW, max_age_seconds=5)
    assert not snapshot.runtime.ready_for_mutation
    assert {alert.component for alert in snapshot.alerts} == set(HealthComponent)
    assert {alert.reason for alert in snapshot.alerts} == {"MISSING"}


def test_all_current_healthy_components_allow_mutation_health():
    registry = HealthRegistry()
    for component in HealthComponent:
        assert registry.observe(healthy(component))

    snapshot = registry.snapshot(now=NOW, max_age_seconds=5)

    assert snapshot.runtime.ready_for_mutation
    assert snapshot.alerts == ()


def test_stale_future_and_explicit_unhealthy_are_distinct_alerts():
    registry = HealthRegistry()
    for component in HealthComponent:
        registry.observe(healthy(component))

    registry.observe(
        HealthObservation(
            component=HealthComponent.QMT,
            healthy=True,
            observed_at=NOW + timedelta(seconds=1),
        )
    )
    registry.observe(
        HealthObservation(
            component=HealthComponent.MARKET_DATA,
            healthy=False,
            observed_at=NOW,
            detail="quote stream disconnected",
        )
    )
    registry.observe(
        HealthObservation(
            component=HealthComponent.STRATEGY,
            healthy=True,
            observed_at=NOW - timedelta(seconds=30),
        )
    )

    snapshot = registry.snapshot(now=NOW, max_age_seconds=5)
    alerts = {item.component: item.reason for item in snapshot.alerts}

    assert alerts[HealthComponent.QMT] == "FUTURE_DATED"
    assert alerts[HealthComponent.MARKET_DATA] == "quote stream disconnected"
    assert alerts[HealthComponent.STRATEGY] == "STALE"
    assert not snapshot.runtime.ready_for_mutation


def test_older_observation_cannot_overwrite_newer_health_fact():
    registry = HealthRegistry()
    current = healthy(HealthComponent.QMT)
    older_bad = HealthObservation(
        component=HealthComponent.QMT,
        healthy=False,
        observed_at=NOW - timedelta(seconds=1),
        detail="old disconnect",
    )

    assert registry.observe(current)
    assert not registry.observe(older_bad)
    snapshot = registry.snapshot(now=NOW, max_age_seconds=5)

    # Other components are missing, but QMT itself must remain healthy.
    assert snapshot.runtime.qmt_healthy


def test_registry_restart_does_not_reuse_old_health_authority():
    first = HealthRegistry()
    for component in HealthComponent:
        first.observe(healthy(component))
    assert first.snapshot(now=NOW, max_age_seconds=5).runtime.ready_for_mutation

    second = HealthRegistry()
    assert not second.snapshot(now=NOW, max_age_seconds=5).runtime.ready_for_mutation

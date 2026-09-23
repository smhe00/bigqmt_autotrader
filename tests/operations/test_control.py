from datetime import datetime, timedelta, timezone

import pytest

from bigqmt_autotrader.oms import connect_database, initialize_database
from bigqmt_autotrader.operations import (
    HealthComponent,
    HealthObservation,
    HealthRegistry,
    ModeTransitionDenied,
    OperationsControl,
    RuntimeModeController,
)
from bigqmt_autotrader.risk import RuntimeMode


TZ = timezone(timedelta(hours=8))
NOW = datetime(2026, 9, 23, 13, 45, tzinfo=TZ)


def build(tmp_path):
    conn = connect_database(tmp_path / "ops.sqlite3")
    initialize_database(conn)
    modes = RuntimeModeController(conn, runtime_session_id="host-1", started_at=NOW)
    health = HealthRegistry()
    return conn, health, OperationsControl(modes=modes, health=health)


def make_healthy(registry):
    for component in HealthComponent:
        registry.observe(
            HealthObservation(
                component=component,
                healthy=True,
                observed_at=NOW,
            )
        )


def test_observe_is_available_without_mutation_readiness(tmp_path):
    _, _, control = build(tmp_path)

    assert control.enter_observe(
        request_id="observe",
        actor="operator",
        reason="diagnostic",
        now=NOW,
        max_age_seconds=5,
    )
    status = control.status(now=NOW, max_age_seconds=5)
    assert status.mode is RuntimeMode.OBSERVE
    assert not status.ready_for_mutation


def test_simulation_arm_requires_all_health_components(tmp_path):
    _, health, control = build(tmp_path)
    control.enter_observe(
        request_id="observe",
        actor="operator",
        reason="preflight",
        now=NOW,
        max_age_seconds=5,
    )

    with pytest.raises(ModeTransitionDenied, match="not ready"):
        control.arm_simulation(
            request_id="sim-bad",
            actor="operator",
            reason="arm",
            now=NOW,
            max_age_seconds=5,
        )

    make_healthy(health)
    assert control.arm_simulation(
        request_id="sim-ok",
        actor="operator",
        reason="arm",
        now=NOW,
        max_age_seconds=5,
    )
    assert control.status(now=NOW, max_age_seconds=5).mode is RuntimeMode.SIMULATION


def test_emergency_halt_does_not_depend_on_health(tmp_path):
    _, health, control = build(tmp_path)
    make_healthy(health)
    control.enter_observe(
        request_id="observe",
        actor="operator",
        reason="preflight",
        now=NOW,
        max_age_seconds=5,
    )
    control.arm_simulation(
        request_id="sim",
        actor="operator",
        reason="arm",
        now=NOW,
        max_age_seconds=5,
    )
    health.clear()

    assert control.emergency_halt(
        request_id="halt",
        actor="operator",
        reason="manual kill switch",
        now=NOW + timedelta(seconds=1),
    )
    assert control.status(
        now=NOW + timedelta(seconds=1),
        max_age_seconds=5,
    ).mode is RuntimeMode.HALTED


def test_health_enforcement_auto_halts_simulation(tmp_path):
    _, health, control = build(tmp_path)
    make_healthy(health)
    control.enter_observe(
        request_id="observe",
        actor="operator",
        reason="preflight",
        now=NOW,
        max_age_seconds=5,
    )
    control.arm_simulation(
        request_id="sim",
        actor="operator",
        reason="arm",
        now=NOW,
        max_age_seconds=5,
    )
    health.observe(
        HealthObservation(
            component=HealthComponent.QMT,
            healthy=False,
            observed_at=NOW + timedelta(seconds=1),
            detail="terminal disconnected",
        )
    )

    assert control.enforce_health(
        request_id="auto-halt",
        now=NOW + timedelta(seconds=1),
        max_age_seconds=5,
    )
    status = control.status(
        now=NOW + timedelta(seconds=1),
        max_age_seconds=5,
    )
    assert status.mode is RuntimeMode.HALTED
    assert any(
        alert.component is HealthComponent.QMT and alert.reason == "terminal disconnected"
        for alert in status.alerts
    )


def test_operations_control_exposes_no_live_arm_method(tmp_path):
    _, _, control = build(tmp_path)
    assert not hasattr(control, "arm_live")
    assert not hasattr(control, "arm_live_canary")

from datetime import datetime, timedelta, timezone

from bigqmt_autotrader.oms import connect_database, initialize_database
from bigqmt_autotrader.operations import (
    HealthComponent,
    HealthObservation,
    HealthRegistry,
    OperationsControl,
    OperationsTelemetry,
    RuntimeModeController,
)
from bigqmt_autotrader.risk import RuntimeMode
from bigqmt_autotrader.service import RuntimeSupervisor


TZ = timezone(timedelta(hours=8))
NOW = datetime(2026, 9, 23, 15, 30, tzinfo=TZ)


def build(tmp_path):
    conn = connect_database(tmp_path / "supervisor.sqlite3")
    initialize_database(conn)
    modes = RuntimeModeController(
        conn,
        runtime_session_id="host-supervisor",
        started_at=NOW,
    )
    health = HealthRegistry()
    operations = OperationsControl(modes=modes, health=health)
    telemetry = OperationsTelemetry()
    supervisor = RuntimeSupervisor(
        operations=operations,
        telemetry=telemetry,
        health_max_age_seconds=5,
    )
    return modes, health, operations, supervisor


def make_healthy(health, observed_at):
    for component in HealthComponent:
        health.observe(
            HealthObservation(
                component=component,
                healthy=True,
                observed_at=observed_at,
            )
        )


def arm(health, operations):
    make_healthy(health, NOW)
    operations.enter_observe(
        request_id="observe",
        actor="test",
        reason="preflight",
        now=NOW,
        max_age_seconds=5,
    )
    operations.arm_simulation(
        request_id="sim",
        actor="test",
        reason="arm",
        now=NOW,
        max_age_seconds=5,
    )


def test_healthy_cycle_keeps_simulation_and_updates_metrics(tmp_path):
    modes, health, operations, supervisor = build(tmp_path)
    arm(health, operations)

    result = supervisor.tick(
        now=NOW,
        unknown_order_count=0,
        manual_review_count=0,
        halt_request_id="halt-1",
    )

    assert not result.auto_halted
    assert modes.mode is RuntimeMode.SIMULATION
    assert result.telemetry.mode is RuntimeMode.SIMULATION
    assert result.telemetry.ready_for_mutation
    assert result.telemetry.active_alerts == ()


def test_qmt_health_loss_auto_halts_and_surfaces_alert(tmp_path):
    modes, health, operations, supervisor = build(tmp_path)
    arm(health, operations)
    broken_at = NOW + timedelta(seconds=1)
    health.observe(
        HealthObservation(
            component=HealthComponent.QMT,
            healthy=False,
            observed_at=broken_at,
            detail="terminal disconnected",
        )
    )

    result = supervisor.tick(
        now=broken_at,
        unknown_order_count=0,
        manual_review_count=0,
        halt_request_id="halt-qmt",
    )

    assert result.auto_halted
    assert modes.mode is RuntimeMode.HALTED
    assert result.telemetry.mode is RuntimeMode.HALTED
    keys = {item.key for item in result.telemetry.active_alerts}
    assert "health:QMT" in keys
    assert "runtime:HALTED" in keys


def test_execution_ambiguity_alerts_do_not_mutate_mode_by_themselves(tmp_path):
    modes, health, operations, supervisor = build(tmp_path)
    arm(health, operations)

    result = supervisor.tick(
        now=NOW,
        unknown_order_count=2,
        manual_review_count=1,
        halt_request_id="halt-unused",
    )

    assert not result.auto_halted
    assert modes.mode is RuntimeMode.SIMULATION
    keys = {item.key for item in result.telemetry.active_alerts}
    assert keys == {"execution:UNKNOWN", "execution:MANUAL_REVIEW"}


def test_disabled_runtime_reports_health_but_never_auto_arms(tmp_path):
    modes, health, _operations, supervisor = build(tmp_path)
    make_healthy(health, NOW)

    result = supervisor.tick(
        now=NOW,
        unknown_order_count=0,
        manual_review_count=0,
        halt_request_id="halt-unused",
    )

    assert modes.mode is RuntimeMode.DISABLED
    assert result.telemetry.mode is RuntimeMode.DISABLED
    assert result.telemetry.ready_for_mutation
    assert not result.auto_halted

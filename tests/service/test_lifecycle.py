from datetime import datetime, timedelta, timezone

from bigqmt_autotrader.oms import connect_database, initialize_database
from bigqmt_autotrader.operations import (
    HealthComponent,
    HealthObservation,
    HealthRegistry,
    OperationsAlertJournal,
    OperationsControl,
    OperationsTelemetry,
    RuntimeModeController,
)
from bigqmt_autotrader.risk import RuntimeMode
from bigqmt_autotrader.service import RuntimeLifecycleController


TZ = timezone(timedelta(hours=8))
NOW = datetime(2026, 9, 23, 17, 0, tzinfo=TZ)


def build(tmp_path, *, session="host-1"):
    path = tmp_path / "lifecycle.sqlite3"
    conn = connect_database(path)
    initialize_database(conn)
    modes = RuntimeModeController(
        conn,
        runtime_session_id=session,
        started_at=NOW,
    )
    health = HealthRegistry()
    operations = OperationsControl(modes=modes, health=health)
    journal = OperationsAlertJournal(conn)
    telemetry = OperationsTelemetry(journal)
    lifecycle = RuntimeLifecycleController(
        operations=operations,
        telemetry=telemetry,
        runtime_session_id=session,
    )
    return path, conn, modes, health, operations, journal, telemetry, lifecycle


def make_healthy(health, at=NOW):
    for component in HealthComponent:
        health.observe(
            HealthObservation(
                component=component,
                healthy=True,
                observed_at=at,
            )
        )


def arm_simulation(health, operations):
    make_healthy(health)
    operations.enter_observe(
        request_id="observe",
        actor="test",
        reason="preflight",
        now=NOW,
        max_age_seconds=5,
    )
    operations.arm_simulation(
        request_id="simulation",
        actor="test",
        reason="arm",
        now=NOW,
        max_age_seconds=5,
    )


def test_shutdown_forces_halted_and_persists_alert(tmp_path):
    _, conn, modes, health, operations, journal, _, lifecycle = build(tmp_path)
    arm_simulation(health, operations)

    result = lifecycle.shutdown(
        now=NOW + timedelta(seconds=1),
        reason="service stop",
    )

    assert result.changed
    assert result.mode is RuntimeMode.HALTED
    assert modes.mode is RuntimeMode.HALTED
    assert "runtime:HALTED" in {item.key for item in result.telemetry.active_alerts}
    active = journal.active_alerts()
    assert [item.key for item in active] == ["runtime:HALTED"]

    row = conn.execute(
        """
        SELECT from_mode, to_mode, actor, reason
        FROM runtime_mode_transitions
        WHERE request_id='shutdown:host-1'
        """
    ).fetchone()
    assert tuple(row) == (
        "SIMULATION",
        "HALTED",
        "runtime-lifecycle",
        "service stop",
    )


def test_exact_shutdown_replay_is_idempotent(tmp_path):
    _, conn, _, _, _, journal, _, lifecycle = build(tmp_path)
    at = NOW + timedelta(seconds=1)

    first = lifecycle.shutdown(now=at)
    second = lifecycle.shutdown(now=at)

    assert first.changed
    assert not second.changed
    assert len(journal.events_for("runtime:HALTED")) == 1
    count = conn.execute(
        """
        SELECT COUNT(*) FROM runtime_mode_transitions
        WHERE request_id='shutdown:host-1'
        """
    ).fetchone()[0]
    assert count == 1


def test_restart_never_restores_old_mutation_mode(tmp_path):
    path, conn, modes, health, operations, _, _, lifecycle = build(tmp_path)
    arm_simulation(health, operations)
    lifecycle.shutdown(now=NOW + timedelta(seconds=1))
    assert modes.mode is RuntimeMode.HALTED
    conn.close()

    conn = connect_database(path)
    initialize_database(conn)
    restarted_modes = RuntimeModeController(
        conn,
        runtime_session_id="host-2",
        started_at=NOW + timedelta(minutes=1),
    )
    restarted_journal = OperationsAlertJournal(conn)
    restarted_telemetry = OperationsTelemetry(restarted_journal)

    assert restarted_modes.mode is RuntimeMode.DISABLED
    assert not restarted_telemetry.snapshot().ready_for_mutation
    assert "runtime:HALTED" in {
        item.key for item in restarted_telemetry.snapshot().active_alerts
    }


def test_shutdown_from_disabled_is_still_a_durable_safe_terminal(tmp_path):
    _, _, modes, _, _, journal, _, lifecycle = build(tmp_path)

    result = lifecycle.shutdown(now=NOW + timedelta(seconds=1))

    assert result.changed
    assert modes.mode is RuntimeMode.HALTED
    assert [item.key for item in journal.active_alerts()] == ["runtime:HALTED"]

from datetime import datetime, timedelta, timezone

from bigqmt_autotrader.oms import connect_database, initialize_database
from bigqmt_autotrader.operations import (
    HealthAlert,
    HealthComponent,
    HealthSnapshot,
    OperationsAlertJournal,
    OperationsTelemetry,
    RuntimeHealth,
)
from bigqmt_autotrader.risk import RuntimeMode


TZ = timezone(timedelta(hours=8))
NOW = datetime(2026, 9, 23, 15, 0, tzinfo=TZ)


def runtime_health(*, qmt=True, market=True, strategy=True):
    return RuntimeHealth(
        database_healthy=True,
        oms_healthy=True,
        leader_held=True,
        reconciliation_complete=True,
        qmt_healthy=qmt,
        market_data_healthy=market,
        strategy_healthy=strategy,
    )


def test_health_alerts_are_deduplicated_and_resolved():
    telemetry = OperationsTelemetry()
    bad = HealthSnapshot(
        runtime=runtime_health(qmt=False),
        alerts=(HealthAlert(HealthComponent.QMT, "terminal disconnected"),),
    )
    telemetry.sync_health(bad, observed_at=NOW)
    telemetry.sync_health(bad, observed_at=NOW + timedelta(seconds=1))

    snap = telemetry.snapshot()
    assert len(snap.active_alerts) == 1
    alert = snap.active_alerts[0]
    assert alert.key == "health:QMT"
    assert alert.detail == "terminal disconnected"
    assert alert.occurrences == 2
    assert not snap.ready_for_mutation

    healthy = HealthSnapshot(runtime=runtime_health(), alerts=())
    telemetry.sync_health(healthy, observed_at=NOW + timedelta(seconds=2))
    snap = telemetry.snapshot()
    assert snap.active_alerts == ()
    assert snap.ready_for_mutation


def test_old_health_snapshot_cannot_resolve_newer_alert():
    telemetry = OperationsTelemetry()
    telemetry.sync_health(
        HealthSnapshot(
            runtime=runtime_health(qmt=False),
            alerts=(HealthAlert(HealthComponent.QMT, "disconnect"),),
        ),
        observed_at=NOW + timedelta(seconds=2),
    )
    telemetry.sync_health(
        HealthSnapshot(runtime=runtime_health(), alerts=()),
        observed_at=NOW + timedelta(seconds=1),
    )

    assert telemetry.snapshot().active_alerts[0].key == "health:QMT"


def test_halted_mode_is_an_alert_and_nonhalted_resolves_it():
    telemetry = OperationsTelemetry()
    telemetry.sync_mode(RuntimeMode.HALTED, observed_at=NOW)
    snap = telemetry.snapshot()
    assert snap.mode is RuntimeMode.HALTED
    assert [item.key for item in snap.active_alerts] == ["runtime:HALTED"]

    telemetry.sync_mode(RuntimeMode.DISABLED, observed_at=NOW + timedelta(seconds=1))
    assert telemetry.snapshot().active_alerts == ()


def test_execution_ambiguity_tracks_counts_and_resolves():
    telemetry = OperationsTelemetry()
    telemetry.sync_execution_ambiguity(
        unknown_order_count=2,
        manual_review_count=1,
        observed_at=NOW,
    )
    snap = telemetry.snapshot()
    assert snap.unknown_order_count == 2
    assert snap.manual_review_count == 1
    assert {item.key for item in snap.active_alerts} == {
        "execution:UNKNOWN",
        "execution:MANUAL_REVIEW",
    }

    telemetry.sync_execution_ambiguity(
        unknown_order_count=0,
        manual_review_count=0,
        observed_at=NOW + timedelta(seconds=1),
    )
    snap = telemetry.snapshot()
    assert snap.active_alerts == ()
    assert snap.unknown_order_count == 0
    assert snap.manual_review_count == 0


def test_restart_does_not_reuse_old_alert_or_health_authority():
    first = OperationsTelemetry()
    first.sync_mode(RuntimeMode.HALTED, observed_at=NOW)
    first.sync_execution_ambiguity(
        unknown_order_count=1,
        manual_review_count=1,
        observed_at=NOW,
    )
    assert len(first.snapshot().active_alerts) == 3

    second = OperationsTelemetry()
    snap = second.snapshot()
    assert snap.mode is RuntimeMode.DISABLED
    assert not snap.ready_for_mutation
    assert snap.active_alerts == ()


def test_persistent_telemetry_restores_alert_visibility_not_health_authority(tmp_path):
    path = tmp_path / "telemetry.sqlite3"
    conn = connect_database(path)
    initialize_database(conn)
    first = OperationsTelemetry(OperationsAlertJournal(conn))
    first.sync_mode(RuntimeMode.HALTED, observed_at=NOW)
    first.sync_execution_ambiguity(
        unknown_order_count=1,
        manual_review_count=0,
        observed_at=NOW,
    )
    conn.close()

    conn = connect_database(path)
    initialize_database(conn)
    second = OperationsTelemetry(OperationsAlertJournal(conn))
    snap = second.snapshot()

    assert snap.mode is RuntimeMode.DISABLED
    assert not snap.ready_for_mutation
    assert {item.key for item in snap.active_alerts} == {
        "runtime:HALTED",
        "execution:UNKNOWN",
    }


def test_persistent_resolution_survives_restart(tmp_path):
    path = tmp_path / "resolved.sqlite3"
    conn = connect_database(path)
    initialize_database(conn)
    telemetry = OperationsTelemetry(OperationsAlertJournal(conn))
    telemetry.sync_mode(RuntimeMode.HALTED, observed_at=NOW)
    telemetry.sync_mode(RuntimeMode.DISABLED, observed_at=NOW + timedelta(seconds=1))
    conn.close()

    conn = connect_database(path)
    initialize_database(conn)
    restarted = OperationsTelemetry(OperationsAlertJournal(conn))
    assert restarted.snapshot().active_alerts == ()

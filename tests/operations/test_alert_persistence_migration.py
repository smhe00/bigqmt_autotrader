from datetime import datetime, timedelta, timezone
import shutil

import bigqmt_autotrader.oms.db as oms_db

from bigqmt_autotrader.oms import (
    SUPPORTED_SCHEMA_VERSION,
    connect_database,
    current_schema_version,
    initialize_database,
)
from bigqmt_autotrader.operations import (
    OperationsAlertJournal,
    create_database_backup,
)


TZ = timezone(timedelta(hours=8))
NOW = datetime(2026, 9, 23, 16, 30, tzinfo=TZ)


def build_v10_database(path):
    conn = connect_database(path)
    assert current_schema_version(conn) == 0
    for version in range(1, 11):
        oms_db._apply_migration(conn, version, oms_db._migration_text(version))
    assert current_schema_version(conn) == 10
    return conn


def test_real_packaged_v10_database_upgrades_to_v11_without_losing_existing_state(tmp_path):
    conn = build_v10_database(tmp_path / "upgrade.sqlite3")
    conn.execute(
        """
        INSERT INTO runtime_mode_transitions(
            request_id, runtime_session_id, from_mode, to_mode,
            actor, reason, changed_at
        ) VALUES(?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "pre-v11-transition",
            "host-v10",
            "DISABLED",
            "OBSERVE",
            "test",
            "existing v10 row",
            NOW.astimezone(timezone.utc).isoformat(),
        ),
    )

    initialize_database(conn)

    assert current_schema_version(conn) == SUPPORTED_SCHEMA_VERSION == 11
    row = conn.execute(
        """
        SELECT runtime_session_id, from_mode, to_mode, reason
        FROM runtime_mode_transitions
        WHERE request_id='pre-v11-transition'
        """
    ).fetchone()
    assert tuple(row) == (
        "host-v10",
        "DISABLED",
        "OBSERVE",
        "existing v10 row",
    )
    assert conn.execute(
        "SELECT COUNT(*) FROM operations_alert_events"
    ).fetchone()[0] == 0
    assert conn.execute(
        "SELECT COUNT(*) FROM operations_alert_state"
    ).fetchone()[0] == 0


def test_v11_upgrade_is_idempotent_after_restart(tmp_path):
    path = tmp_path / "restart-upgrade.sqlite3"
    conn = build_v10_database(path)
    initialize_database(conn)
    conn.close()

    conn = connect_database(path)
    initialize_database(conn)

    versions = [
        row["version"]
        for row in conn.execute(
            "SELECT version FROM schema_meta ORDER BY version"
        ).fetchall()
    ]
    assert versions == list(range(1, 12))


def test_alert_log_and_current_state_survive_verified_backup_restore(tmp_path):
    source_path = tmp_path / "source.sqlite3"
    conn = connect_database(source_path)
    initialize_database(conn)
    journal = OperationsAlertJournal(conn)

    journal.record_active(
        key="health:QMT",
        severity="ERROR",
        detail="terminal disconnected",
        observed_at=NOW,
        source="health",
    )
    journal.record_active(
        key="health:QMT",
        severity="ERROR",
        detail="terminal disconnected",
        observed_at=NOW + timedelta(seconds=1),
        source="health",
    )
    journal.record_active(
        key="execution:UNKNOWN",
        severity="ERROR",
        detail="1 unresolved UNKNOWN order(s)",
        observed_at=NOW,
        source="execution",
    )
    journal.record_resolved(
        key="execution:UNKNOWN",
        observed_at=NOW + timedelta(seconds=1),
        source="execution",
    )

    backup = create_database_backup(
        conn,
        tmp_path / "backup.sqlite3",
        expected_schema_version=SUPPORTED_SCHEMA_VERSION,
    )
    assert backup.schema_version == 11
    conn.close()

    restored_path = tmp_path / "restored.sqlite3"
    shutil.copy2(backup.path, restored_path)
    restored_conn = connect_database(restored_path)
    initialize_database(restored_conn)
    restored = OperationsAlertJournal(restored_conn)

    active = restored.active_alerts()
    assert len(active) == 1
    assert active[0].key == "health:QMT"
    assert active[0].occurrences == 2
    assert len(restored.events_for("health:QMT")) == 2
    assert len(restored.events_for("execution:UNKNOWN")) == 2


def test_exact_event_replay_after_restore_remains_idempotent(tmp_path):
    source = connect_database(tmp_path / "source.sqlite3")
    initialize_database(source)
    journal = OperationsAlertJournal(source)
    journal.record_active(
        key="runtime:HALTED",
        severity="ERROR",
        detail="runtime is HALTED",
        observed_at=NOW,
        source="mode",
    )
    backup = create_database_backup(
        source,
        tmp_path / "backup.sqlite3",
        expected_schema_version=SUPPORTED_SCHEMA_VERSION,
    )
    source.close()

    restored = connect_database(backup.path)
    initialize_database(restored)
    journal = OperationsAlertJournal(restored)

    before = journal.active_alerts()[0]
    replay = journal.record_active(
        key="runtime:HALTED",
        severity="ERROR",
        detail="runtime is HALTED",
        observed_at=NOW,
        source="mode",
    )
    after = journal.active_alerts()[0]

    assert replay == before == after
    assert after.occurrences == 1
    assert len(journal.events_for("runtime:HALTED")) == 1


def test_resolved_state_remains_resolved_across_restart_and_can_reopen_cleanly(tmp_path):
    path = tmp_path / "resolve.sqlite3"
    conn = connect_database(path)
    initialize_database(conn)
    journal = OperationsAlertJournal(conn)
    journal.record_active(
        key="health:MARKET_DATA",
        severity="ERROR",
        detail="STALE",
        observed_at=NOW,
        source="health",
    )
    journal.record_resolved(
        key="health:MARKET_DATA",
        observed_at=NOW + timedelta(seconds=1),
        source="health",
    )
    conn.close()

    conn = connect_database(path)
    initialize_database(conn)
    journal = OperationsAlertJournal(conn)
    assert journal.active_alerts() == ()

    reopened = journal.record_active(
        key="health:MARKET_DATA",
        severity="ERROR",
        detail="STALE",
        observed_at=NOW + timedelta(seconds=2),
        source="health",
    )
    assert reopened.occurrences == 1
    assert len(journal.events_for("health:MARKET_DATA")) == 3


def test_v11_foreign_key_and_unique_event_time_constraints_are_present(tmp_path):
    conn = connect_database(tmp_path / "shape.sqlite3")
    initialize_database(conn)

    foreign_keys = conn.execute(
        "PRAGMA foreign_key_list(operations_alert_state)"
    ).fetchall()
    assert any(
        row["table"] == "operations_alert_events"
        and row["from"] == "last_event_id"
        and row["to"] == "event_id"
        for row in foreign_keys
    )

    indexes = {
        row["name"]: row["sql"]
        for row in conn.execute(
            """
            SELECT name, sql
            FROM sqlite_master
            WHERE type='index' AND tbl_name='operations_alert_events'
            """
        ).fetchall()
    }
    assert "idx_operations_alert_events_key_time" in indexes
    assert "UNIQUE INDEX" in indexes["idx_operations_alert_events_key_time"].upper()

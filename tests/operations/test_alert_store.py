from datetime import datetime, timedelta, timezone

import pytest

from bigqmt_autotrader.oms import connect_database, initialize_database
from bigqmt_autotrader.operations import (
    AlertEventConflict,
    OperationsAlertJournal,
    PersistedAlertStatus,
)


TZ = timezone(timedelta(hours=8))
NOW = datetime(2026, 9, 23, 16, 10, tzinfo=TZ)


def journal(tmp_path):
    conn = connect_database(tmp_path / "alerts.sqlite3")
    initialize_database(conn)
    return conn, OperationsAlertJournal(conn)


def test_active_event_replay_is_idempotent(tmp_path):
    _, store = journal(tmp_path)

    first = store.record_active(
        key="health:QMT",
        severity="ERROR",
        detail="terminal disconnected",
        observed_at=NOW,
        source="health",
    )
    second = store.record_active(
        key="health:QMT",
        severity="ERROR",
        detail="terminal disconnected",
        observed_at=NOW,
        source="health",
    )

    assert first == second
    assert first.status is PersistedAlertStatus.ACTIVE
    assert first.occurrences == 1
    assert len(store.events_for("health:QMT")) == 1


def test_repeated_new_observation_increments_occurrences(tmp_path):
    _, store = journal(tmp_path)
    store.record_active(
        key="health:QMT",
        severity="ERROR",
        detail="terminal disconnected",
        observed_at=NOW,
        source="health",
    )
    later = store.record_active(
        key="health:QMT",
        severity="ERROR",
        detail="terminal disconnected",
        observed_at=NOW + timedelta(seconds=1),
        source="health",
    )

    assert later.occurrences == 2
    assert later.first_seen_at == NOW.astimezone(timezone.utc)
    assert later.last_seen_at == (NOW + timedelta(seconds=1)).astimezone(timezone.utc)
    assert len(store.events_for("health:QMT")) == 2


def test_resolve_and_reopen_are_durable_episodes(tmp_path):
    _, store = journal(tmp_path)
    store.record_active(
        key="runtime:HALTED",
        severity="ERROR",
        detail="runtime is HALTED",
        observed_at=NOW,
        source="mode",
    )
    resolved = store.record_resolved(
        key="runtime:HALTED",
        observed_at=NOW + timedelta(seconds=1),
        source="mode",
    )
    assert resolved is not None
    assert resolved.status is PersistedAlertStatus.RESOLVED
    assert store.active_alerts() == ()

    reopened = store.record_active(
        key="runtime:HALTED",
        severity="ERROR",
        detail="runtime is HALTED",
        observed_at=NOW + timedelta(seconds=2),
        source="mode",
    )
    assert reopened.status is PersistedAlertStatus.ACTIVE
    assert reopened.occurrences == 1
    assert reopened.first_seen_at == (NOW + timedelta(seconds=2)).astimezone(timezone.utc)
    assert len(store.events_for("runtime:HALTED")) == 3


def test_conflicting_event_id_fails_closed(tmp_path):
    _, store = journal(tmp_path)
    store.record_active(
        key="health:QMT",
        severity="ERROR",
        detail="disconnect",
        observed_at=NOW,
        source="health",
        event_id="fixed-event",
    )
    with pytest.raises(AlertEventConflict, match="event_id reused"):
        store.record_active(
            key="health:QMT",
            severity="ERROR",
            detail="different detail",
            observed_at=NOW + timedelta(seconds=1),
            source="health",
            event_id="fixed-event",
        )


def test_same_key_timestamp_conflict_fails_closed(tmp_path):
    _, store = journal(tmp_path)
    store.record_active(
        key="health:QMT",
        severity="ERROR",
        detail="disconnect",
        observed_at=NOW,
        source="health",
    )
    with pytest.raises(AlertEventConflict, match="same alert key/timestamp"):
        store.record_resolved(
            key="health:QMT",
            observed_at=NOW,
            source="health",
        )


def test_late_historical_event_is_logged_but_cannot_rewind_state(tmp_path):
    _, store = journal(tmp_path)
    newest = store.record_active(
        key="health:QMT",
        severity="ERROR",
        detail="newest",
        observed_at=NOW + timedelta(seconds=2),
        source="health",
    )
    late = store.record_active(
        key="health:QMT",
        severity="ERROR",
        detail="historical",
        observed_at=NOW + timedelta(seconds=1),
        source="health",
    )

    assert late == newest
    assert len(store.events_for("health:QMT")) == 2
    assert store.active_alerts()[0].detail == "newest"


def test_alert_state_survives_connection_restart(tmp_path):
    path = tmp_path / "alerts.sqlite3"
    conn = connect_database(path)
    initialize_database(conn)
    first = OperationsAlertJournal(conn)
    first.record_active(
        key="execution:UNKNOWN",
        severity="ERROR",
        detail="2 unresolved UNKNOWN order(s)",
        observed_at=NOW,
        source="execution",
    )
    conn.close()

    conn = connect_database(path)
    initialize_database(conn)
    second = OperationsAlertJournal(conn)
    active = second.active_alerts()

    assert len(active) == 1
    assert active[0].key == "execution:UNKNOWN"
    assert active[0].occurrences == 1

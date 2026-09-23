from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Iterator


class AlertEventConflict(RuntimeError):
    pass


class PersistedAlertStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RESOLVED = "RESOLVED"


@dataclass(frozen=True)
class PersistedAlertState:
    key: str
    status: PersistedAlertStatus
    severity: str
    detail: str
    first_seen_at: datetime
    last_seen_at: datetime
    occurrences: int
    resolved_at: datetime | None
    last_event_id: str


def _require_nonempty(name: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be non-empty")


def _require_aware(name: str, value: datetime) -> None:
    if not isinstance(value, datetime):
        raise TypeError(f"{name} must be datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def _utc_iso(value: datetime) -> str:
    _require_aware("observed_at", value)
    return value.astimezone(timezone.utc).isoformat()


def _parse_utc(value: str | None) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise AlertEventConflict("stored alert timestamp is not timezone-aware")
    return parsed.astimezone(timezone.utc)


def _semantic_digest(
    *,
    alert_key: str,
    event_type: str,
    severity: str | None,
    detail: str | None,
    observed_at: str,
    source: str,
) -> str:
    payload = json.dumps(
        {
            "alert_key": alert_key,
            "event_type": event_type,
            "severity": severity,
            "detail": detail,
            "observed_at": observed_at,
            "source": source,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _deterministic_event_id(semantic_digest: str) -> str:
    return "alert-" + semantic_digest.removeprefix("sha256:")[:48]


@contextmanager
def _transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.rollback()
        raise
    else:
        conn.commit()


class OperationsAlertJournal:
    """Durable append-only alert event log plus current alert state.

    Event identity is deterministic by default. Exact replay is a no-op.
    Conflicting reuse of an event id or two different facts for the same alert
    timestamp fails closed. Late historical events are retained in the event
    log but never rewind the current state.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        if not isinstance(conn, sqlite3.Connection):
            raise TypeError("conn must be sqlite3.Connection")
        self.conn = conn

    def record_active(
        self,
        *,
        key: str,
        severity: str,
        detail: str,
        observed_at: datetime,
        source: str,
        event_id: str | None = None,
    ) -> PersistedAlertState:
        _require_nonempty("key", key)
        _require_nonempty("severity", severity)
        _require_nonempty("detail", detail)
        _require_aware("observed_at", observed_at)
        _require_nonempty("source", source)
        observed_text = _utc_iso(observed_at)
        digest = _semantic_digest(
            alert_key=key,
            event_type=PersistedAlertStatus.ACTIVE.value,
            severity=severity,
            detail=detail,
            observed_at=observed_text,
            source=source,
        )
        event_id = event_id or _deterministic_event_id(digest)
        _require_nonempty("event_id", event_id)

        with _transaction(self.conn):
            duplicate = self._insert_event(
                event_id=event_id,
                key=key,
                event_type=PersistedAlertStatus.ACTIVE,
                severity=severity,
                detail=detail,
                observed_at=observed_text,
                source=source,
                semantic_digest=digest,
            )
            state = self._state_row(key)
            if duplicate:
                if state is None:
                    raise AlertEventConflict("duplicate ACTIVE event has no current state")
                return self._decode_state(state)

            if state is not None and observed_text < state["last_seen_at"]:
                return self._decode_state(state)

            if state is None or state["status"] == PersistedAlertStatus.RESOLVED.value:
                first_seen = observed_text
                occurrences = 1
            else:
                first_seen = state["first_seen_at"]
                occurrences = int(state["occurrences"]) + 1

            self.conn.execute(
                """
                INSERT INTO operations_alert_state(
                    alert_key, status, severity, detail, first_seen_at,
                    last_seen_at, occurrences, resolved_at, last_event_id
                ) VALUES(?, 'ACTIVE', ?, ?, ?, ?, ?, NULL, ?)
                ON CONFLICT(alert_key) DO UPDATE SET
                    status='ACTIVE',
                    severity=excluded.severity,
                    detail=excluded.detail,
                    first_seen_at=excluded.first_seen_at,
                    last_seen_at=excluded.last_seen_at,
                    occurrences=excluded.occurrences,
                    resolved_at=NULL,
                    last_event_id=excluded.last_event_id
                """,
                (
                    key,
                    severity,
                    detail,
                    first_seen,
                    observed_text,
                    occurrences,
                    event_id,
                ),
            )
            return self._decode_state(self._state_row_required(key))

    def record_resolved(
        self,
        *,
        key: str,
        observed_at: datetime,
        source: str,
        event_id: str | None = None,
    ) -> PersistedAlertState | None:
        _require_nonempty("key", key)
        _require_aware("observed_at", observed_at)
        _require_nonempty("source", source)
        observed_text = _utc_iso(observed_at)
        digest = _semantic_digest(
            alert_key=key,
            event_type=PersistedAlertStatus.RESOLVED.value,
            severity=None,
            detail=None,
            observed_at=observed_text,
            source=source,
        )
        event_id = event_id or _deterministic_event_id(digest)
        _require_nonempty("event_id", event_id)

        with _transaction(self.conn):
            duplicate = self._insert_event(
                event_id=event_id,
                key=key,
                event_type=PersistedAlertStatus.RESOLVED,
                severity=None,
                detail=None,
                observed_at=observed_text,
                source=source,
                semantic_digest=digest,
            )
            state = self._state_row(key)
            if duplicate:
                return None if state is None else self._decode_state(state)
            if state is None:
                return None
            if observed_text < state["last_seen_at"]:
                return self._decode_state(state)

            self.conn.execute(
                """
                UPDATE operations_alert_state
                SET status='RESOLVED',
                    last_seen_at=?,
                    resolved_at=?,
                    last_event_id=?
                WHERE alert_key=?
                """,
                (observed_text, observed_text, event_id, key),
            )
            return self._decode_state(self._state_row_required(key))

    def active_alerts(self) -> tuple[PersistedAlertState, ...]:
        rows = self.conn.execute(
            """
            SELECT * FROM operations_alert_state
            WHERE status='ACTIVE'
            ORDER BY alert_key
            """
        ).fetchall()
        return tuple(self._decode_state(row) for row in rows)

    def events_for(self, key: str) -> tuple[sqlite3.Row, ...]:
        _require_nonempty("key", key)
        return tuple(
            self.conn.execute(
                """
                SELECT * FROM operations_alert_events
                WHERE alert_key=?
                ORDER BY observed_at, event_id
                """,
                (key,),
            ).fetchall()
        )

    def _insert_event(
        self,
        *,
        event_id: str,
        key: str,
        event_type: PersistedAlertStatus,
        severity: str | None,
        detail: str | None,
        observed_at: str,
        source: str,
        semantic_digest: str,
    ) -> bool:
        existing = self.conn.execute(
            "SELECT * FROM operations_alert_events WHERE event_id=?",
            (event_id,),
        ).fetchone()
        identity = (
            key,
            event_type.value,
            severity,
            detail,
            observed_at,
            source,
            semantic_digest,
        )
        if existing is not None:
            stored = (
                existing["alert_key"],
                existing["event_type"],
                existing["severity"],
                existing["detail"],
                existing["observed_at"],
                existing["source"],
                existing["semantic_digest"],
            )
            if stored != identity:
                raise AlertEventConflict("event_id reused with different alert semantics")
            return True

        same_time = self.conn.execute(
            """
            SELECT event_id, semantic_digest
            FROM operations_alert_events
            WHERE alert_key=? AND observed_at=?
            """,
            (key, observed_at),
        ).fetchone()
        if same_time is not None:
            if same_time["semantic_digest"] != semantic_digest:
                raise AlertEventConflict(
                    "conflicting alert facts share the same alert key/timestamp"
                )
            return True

        self.conn.execute(
            """
            INSERT INTO operations_alert_events(
                event_id, alert_key, event_type, severity, detail,
                observed_at, source, semantic_digest
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                key,
                event_type.value,
                severity,
                detail,
                observed_at,
                source,
                semantic_digest,
            ),
        )
        return False

    def _state_row(self, key: str):
        return self.conn.execute(
            "SELECT * FROM operations_alert_state WHERE alert_key=?",
            (key,),
        ).fetchone()

    def _state_row_required(self, key: str):
        row = self._state_row(key)
        if row is None:
            raise AlertEventConflict("alert state disappeared inside transaction")
        return row

    @staticmethod
    def _decode_state(row: sqlite3.Row) -> PersistedAlertState:
        return PersistedAlertState(
            key=row["alert_key"],
            status=PersistedAlertStatus(row["status"]),
            severity=row["severity"],
            detail=row["detail"],
            first_seen_at=_parse_utc(row["first_seen_at"]),
            last_seen_at=_parse_utc(row["last_seen_at"]),
            occurrences=int(row["occurrences"]),
            resolved_at=_parse_utc(row["resolved_at"]),
            last_event_id=row["last_event_id"],
        )

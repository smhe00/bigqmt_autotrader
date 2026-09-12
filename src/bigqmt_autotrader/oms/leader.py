from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from .db import transaction


class OmsLeaderUnavailable(RuntimeError):
    pass


class OmsLeaderLost(RuntimeError):
    pass


@dataclass(frozen=True)
class LeaderLease:
    session_id: str
    lease_token: str
    epoch: int
    expires_at: datetime


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_utc(value: datetime | None) -> datetime:
    value = value or _utc_now()
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("leader clock must be timezone-aware")
    return value.astimezone(timezone.utc)


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(timezone.utc)


class LeaderCoordinator:
    """SQLite-backed cooperative leader lease with fencing epoch.

    This is the P1 single-machine OMS ownership guard. It intentionally fails
    closed when an unexpired owner exists. Expired leases may be taken over,
    which increments the fencing epoch so the old owner can no longer pass
    `assert_held()` or renew its lease.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def acquire(
        self,
        session_id: str,
        *,
        lease_seconds: int = 30,
        now: datetime | None = None,
    ) -> LeaderLease:
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")

        now_utc = _normalize_utc(now)
        expires_at = now_utc + timedelta(seconds=lease_seconds)
        token = str(uuid4())

        with transaction(self.conn):
            row = self.conn.execute(
                "SELECT session_id, lease_token, epoch, expires_at FROM oms_leader WHERE singleton=1"
            ).fetchone()

            if row is None:
                epoch = 1
                self.conn.execute(
                    """
                    INSERT INTO oms_leader(
                        singleton, session_id, lease_token, epoch,
                        acquired_at, heartbeat_at, expires_at
                    ) VALUES(1, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        session_id,
                        token,
                        epoch,
                        now_utc.isoformat(),
                        now_utc.isoformat(),
                        expires_at.isoformat(),
                    ),
                )
            else:
                current_expiry = _parse_time(row["expires_at"])
                if current_expiry > now_utc:
                    raise OmsLeaderUnavailable(
                        f"OMS leader lease is held by session {row['session_id']} "
                        f"until {current_expiry.isoformat()}"
                    )
                epoch = int(row["epoch"]) + 1
                self.conn.execute(
                    """
                    UPDATE oms_leader
                    SET session_id=?, lease_token=?, epoch=?,
                        acquired_at=?, heartbeat_at=?, expires_at=?
                    WHERE singleton=1
                    """,
                    (
                        session_id,
                        token,
                        epoch,
                        now_utc.isoformat(),
                        now_utc.isoformat(),
                        expires_at.isoformat(),
                    ),
                )

        return LeaderLease(
            session_id=session_id,
            lease_token=token,
            epoch=epoch,
            expires_at=expires_at,
        )

    def assert_held(self, lease: LeaderLease, *, now: datetime | None = None) -> None:
        now_utc = _normalize_utc(now)
        row = self.conn.execute(
            "SELECT session_id, lease_token, epoch, expires_at FROM oms_leader WHERE singleton=1"
        ).fetchone()
        if row is None:
            raise OmsLeaderLost("OMS leader row is missing")

        matches = (
            row["session_id"] == lease.session_id
            and row["lease_token"] == lease.lease_token
            and int(row["epoch"]) == lease.epoch
        )
        if not matches:
            raise OmsLeaderLost("OMS leader lease was fenced by another session")

        if _parse_time(row["expires_at"]) <= now_utc:
            raise OmsLeaderLost("OMS leader lease has expired")

    def heartbeat(
        self,
        lease: LeaderLease,
        *,
        lease_seconds: int = 30,
        now: datetime | None = None,
    ) -> LeaderLease:
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        now_utc = _normalize_utc(now)
        expires_at = now_utc + timedelta(seconds=lease_seconds)

        with transaction(self.conn):
            row = self.conn.execute(
                "SELECT session_id, lease_token, epoch, expires_at FROM oms_leader WHERE singleton=1"
            ).fetchone()
            if row is None:
                raise OmsLeaderLost("OMS leader row is missing")
            if (
                row["session_id"] != lease.session_id
                or row["lease_token"] != lease.lease_token
                or int(row["epoch"]) != lease.epoch
            ):
                raise OmsLeaderLost("OMS leader lease was fenced by another session")
            if _parse_time(row["expires_at"]) <= now_utc:
                raise OmsLeaderLost("expired OMS leader lease cannot be resurrected")

            self.conn.execute(
                """
                UPDATE oms_leader
                SET heartbeat_at=?, expires_at=?
                WHERE singleton=1 AND session_id=? AND lease_token=? AND epoch=?
                """,
                (
                    now_utc.isoformat(),
                    expires_at.isoformat(),
                    lease.session_id,
                    lease.lease_token,
                    lease.epoch,
                ),
            )

        return LeaderLease(
            session_id=lease.session_id,
            lease_token=lease.lease_token,
            epoch=lease.epoch,
            expires_at=expires_at,
        )

    def release(self, lease: LeaderLease) -> bool:
        with transaction(self.conn):
            cursor = self.conn.execute(
                """
                DELETE FROM oms_leader
                WHERE singleton=1 AND session_id=? AND lease_token=? AND epoch=?
                """,
                (lease.session_id, lease.lease_token, lease.epoch),
            )
            return cursor.rowcount == 1

    def current_epoch(self) -> int | None:
        row = self.conn.execute("SELECT epoch FROM oms_leader WHERE singleton=1").fetchone()
        return None if row is None else int(row["epoch"])

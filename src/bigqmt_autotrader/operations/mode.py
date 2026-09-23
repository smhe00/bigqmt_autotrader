from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Iterator

from bigqmt_autotrader.risk import RuntimeMode


class ModeTransitionError(RuntimeError):
    pass


class ModeTransitionDenied(ModeTransitionError):
    pass


class ModeTransitionConflict(ModeTransitionError):
    pass


def _require_nonempty(name: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


def _require_aware(name: str, value: datetime) -> None:
    if not isinstance(value, datetime):
        raise TypeError(f"{name} must be datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def _utc_iso(value: datetime) -> str:
    _require_aware("changed_at", value)
    return value.astimezone(timezone.utc).isoformat()


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


@dataclass(frozen=True)
class RuntimeHealth:
    database_healthy: bool
    oms_healthy: bool
    leader_held: bool
    reconciliation_complete: bool
    qmt_healthy: bool
    market_data_healthy: bool
    strategy_healthy: bool

    def __post_init__(self) -> None:
        for name in (
            "database_healthy",
            "oms_healthy",
            "leader_held",
            "reconciliation_complete",
            "qmt_healthy",
            "market_data_healthy",
            "strategy_healthy",
        ):
            if not isinstance(getattr(self, name), bool):
                raise TypeError(f"{name} must be bool")

    @property
    def ready_for_mutation(self) -> bool:
        return all(
            (
                self.database_healthy,
                self.oms_healthy,
                self.leader_held,
                self.reconciliation_complete,
                self.qmt_healthy,
                self.market_data_healthy,
                self.strategy_healthy,
            )
        )


class RuntimeModeController:
    """Fail-closed runtime mode state with durable transition audit.

    Runtime authority is deliberately not restored from SQLite. Every process
    start begins in DISABLED even if a prior runtime reached SIMULATION.
    Live modes remain forbidden until a separate production Gate expands them.
    """

    _LIVE_MODES = frozenset({RuntimeMode.LIVE_CANARY, RuntimeMode.LIVE_ARMED})

    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        runtime_session_id: str,
        started_at: datetime,
    ) -> None:
        if not isinstance(conn, sqlite3.Connection):
            raise TypeError("conn must be sqlite3.Connection")
        _require_nonempty("runtime_session_id", runtime_session_id)
        _require_aware("started_at", started_at)
        self.conn = conn
        self.runtime_session_id = runtime_session_id
        self._mode = RuntimeMode.DISABLED
        self._write_guard: Callable[[], None] | None = None
        self._record_transition(
            request_id=f"startup:{runtime_session_id}",
            from_mode=RuntimeMode.DISABLED,
            to_mode=RuntimeMode.DISABLED,
            actor="system",
            reason="runtime start defaults to DISABLED",
            changed_at=started_at,
        )

    @property
    def mode(self) -> RuntimeMode:
        return self._mode

    def bind_write_guard(self, write_guard: Callable[[], None]) -> None:
        if not callable(write_guard):
            raise TypeError("write_guard must be callable")
        self._write_guard = write_guard

    def _guard_write_in_tx(self) -> None:
        if not self.conn.in_transaction:
            raise RuntimeError("write guard requires active transaction")
        if self._write_guard is not None:
            self._write_guard()

    def request_mode(
        self,
        *,
        request_id: str,
        target: RuntimeMode,
        actor: str,
        reason: str,
        changed_at: datetime,
        health: RuntimeHealth,
    ) -> bool:
        if not isinstance(target, RuntimeMode):
            raise TypeError("target must be RuntimeMode")
        if not isinstance(health, RuntimeHealth):
            raise TypeError("health must be RuntimeHealth")
        _require_nonempty("request_id", request_id)
        _require_nonempty("actor", actor)
        _require_nonempty("reason", reason)
        _require_aware("changed_at", changed_at)

        prior = self._find_request(request_id)
        if prior is not None:
            expected = (
                self.runtime_session_id,
                target.value,
                actor,
                reason,
                _utc_iso(changed_at),
            )
            stored = (
                prior["runtime_session_id"],
                prior["to_mode"],
                prior["actor"],
                prior["reason"],
                prior["changed_at"],
            )
            if stored != expected or self._mode.value != prior["to_mode"]:
                raise ModeTransitionConflict("request_id replay does not match current runtime state")
            return False

        if target in self._LIVE_MODES:
            raise ModeTransitionDenied("live modes require a separate production Gate")
        if target is RuntimeMode.HALTED:
            raise ModeTransitionDenied("use halt() for HALTED transitions")

        current = self._mode
        if current is RuntimeMode.HALTED and target is not RuntimeMode.DISABLED:
            raise ModeTransitionDenied("HALTED may only transition to DISABLED")

        allowed = {
            RuntimeMode.DISABLED: {RuntimeMode.DISABLED, RuntimeMode.OBSERVE},
            RuntimeMode.OBSERVE: {
                RuntimeMode.DISABLED,
                RuntimeMode.OBSERVE,
                RuntimeMode.SHADOW,
                RuntimeMode.SIMULATION,
            },
            RuntimeMode.SHADOW: {
                RuntimeMode.DISABLED,
                RuntimeMode.OBSERVE,
                RuntimeMode.SHADOW,
                RuntimeMode.SIMULATION,
            },
            RuntimeMode.SIMULATION: {
                RuntimeMode.DISABLED,
                RuntimeMode.OBSERVE,
                RuntimeMode.SIMULATION,
            },
            RuntimeMode.HALTED: {RuntimeMode.DISABLED},
        }
        if target not in allowed[current]:
            raise ModeTransitionDenied(f"transition {current.value}->{target.value} is not allowed")
        if target in {RuntimeMode.SHADOW, RuntimeMode.SIMULATION} and not health.ready_for_mutation:
            raise ModeTransitionDenied("runtime health prerequisites are not satisfied")

        changed = self._record_transition(
            request_id=request_id,
            from_mode=current,
            to_mode=target,
            actor=actor,
            reason=reason,
            changed_at=changed_at,
        )
        if changed:
            self._mode = target
        return changed

    def halt(
        self,
        *,
        request_id: str,
        actor: str,
        reason: str,
        changed_at: datetime,
    ) -> bool:
        _require_nonempty("request_id", request_id)
        _require_nonempty("actor", actor)
        _require_nonempty("reason", reason)
        _require_aware("changed_at", changed_at)

        prior = self._find_request(request_id)
        if prior is not None:
            expected = (
                self.runtime_session_id,
                RuntimeMode.HALTED.value,
                actor,
                reason,
                _utc_iso(changed_at),
            )
            stored = (
                prior["runtime_session_id"],
                prior["to_mode"],
                prior["actor"],
                prior["reason"],
                prior["changed_at"],
            )
            if stored != expected or self._mode is not RuntimeMode.HALTED:
                raise ModeTransitionConflict("halt request replay does not match current runtime state")
            return False

        current = self._mode
        changed = self._record_transition(
            request_id=request_id,
            from_mode=current,
            to_mode=RuntimeMode.HALTED,
            actor=actor,
            reason=reason,
            changed_at=changed_at,
        )
        if changed:
            self._mode = RuntimeMode.HALTED
        return changed

    def enforce_health(
        self,
        *,
        request_id: str,
        health: RuntimeHealth,
        changed_at: datetime,
    ) -> bool:
        if not isinstance(health, RuntimeHealth):
            raise TypeError("health must be RuntimeHealth")
        if self._mode is RuntimeMode.SIMULATION and not health.ready_for_mutation:
            return self.halt(
                request_id=request_id,
                actor="health-monitor",
                reason="mutation runtime health prerequisite lost",
                changed_at=changed_at,
            )
        return False

    def _find_request(self, request_id: str):
        return self.conn.execute(
            """
            SELECT runtime_session_id, from_mode, to_mode, actor, reason, changed_at
            FROM runtime_mode_transitions WHERE request_id=?
            """,
            (request_id,),
        ).fetchone()

    def _record_transition(
        self,
        *,
        request_id: str,
        from_mode: RuntimeMode,
        to_mode: RuntimeMode,
        actor: str,
        reason: str,
        changed_at: datetime,
    ) -> bool:
        identity = (
            self.runtime_session_id,
            from_mode.value,
            to_mode.value,
            actor,
            reason,
            _utc_iso(changed_at),
        )
        with _transaction(self.conn):
            self._guard_write_in_tx()
            row = self._find_request(request_id)
            if row is not None:
                if tuple(row) != identity:
                    raise ModeTransitionConflict("request_id reused with different transition")
                return False
            self.conn.execute(
                """
                INSERT INTO runtime_mode_transitions(
                    request_id, runtime_session_id, from_mode, to_mode, actor, reason, changed_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?)
                """,
                (request_id,) + identity,
            )
            return True

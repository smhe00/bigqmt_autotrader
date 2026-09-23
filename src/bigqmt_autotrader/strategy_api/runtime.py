from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

from bigqmt_autotrader.domain import OrderIntent


class StrategyRuntimeError(RuntimeError):
    pass


class StrategyUnavailable(StrategyRuntimeError):
    pass


class StrategyStale(StrategyRuntimeError):
    pass


class StrategyIdentityMismatch(StrategyRuntimeError):
    pass


class HeartbeatUpdateResult(str, Enum):
    APPLIED = "APPLIED"
    DUPLICATE = "DUPLICATE"
    STALE_IGNORED = "STALE_IGNORED"


def _require_nonempty(name: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


def _require_aware(name: str, value: datetime) -> None:
    if not isinstance(value, datetime):
        raise TypeError(f"{name} must be datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


@dataclass(frozen=True)
class StrategyHeartbeat:
    strategy_id: str
    strategy_version: str
    session_id: str
    sequence: int
    observed_at: datetime

    def __post_init__(self) -> None:
        _require_nonempty("strategy_id", self.strategy_id)
        _require_nonempty("strategy_version", self.strategy_version)
        _require_nonempty("session_id", self.session_id)
        if isinstance(self.sequence, bool) or not isinstance(self.sequence, int) or self.sequence <= 0:
            raise ValueError("sequence must be a positive integer")
        _require_aware("observed_at", self.observed_at)


class StrategyRuntimeService:
    """Fail-closed in-memory strategy liveness boundary.

    Heartbeats are intentionally not persisted as execution authority. After
    Host restart a strategy must establish a new live heartbeat before its
    intents can be considered fresh.
    """

    def __init__(self) -> None:
        self._heartbeats: dict[str, StrategyHeartbeat] = {}

    def ingest_heartbeat(self, heartbeat: StrategyHeartbeat) -> HeartbeatUpdateResult:
        if not isinstance(heartbeat, StrategyHeartbeat):
            raise TypeError("heartbeat must be StrategyHeartbeat")
        previous = self._heartbeats.get(heartbeat.strategy_id)
        if previous is None:
            self._heartbeats[heartbeat.strategy_id] = heartbeat
            return HeartbeatUpdateResult.APPLIED

        if heartbeat.session_id == previous.session_id:
            if heartbeat.sequence < previous.sequence:
                return HeartbeatUpdateResult.STALE_IGNORED
            if heartbeat.sequence == previous.sequence:
                if heartbeat == previous:
                    return HeartbeatUpdateResult.DUPLICATE
                return HeartbeatUpdateResult.STALE_IGNORED
            if heartbeat.observed_at < previous.observed_at:
                return HeartbeatUpdateResult.STALE_IGNORED
        else:
            # A new process/session is accepted only if its observation is
            # strictly newer. Sequence numbers are session-local.
            if heartbeat.observed_at <= previous.observed_at:
                return HeartbeatUpdateResult.STALE_IGNORED

        self._heartbeats[heartbeat.strategy_id] = heartbeat
        return HeartbeatUpdateResult.APPLIED

    def require_fresh(
        self,
        *,
        strategy_id: str,
        strategy_version: str,
        now: datetime,
        max_age_seconds: int,
    ) -> StrategyHeartbeat:
        _require_nonempty("strategy_id", strategy_id)
        _require_nonempty("strategy_version", strategy_version)
        _require_aware("now", now)
        if isinstance(max_age_seconds, bool) or not isinstance(max_age_seconds, int):
            raise TypeError("max_age_seconds must be int")
        if max_age_seconds <= 0:
            raise ValueError("max_age_seconds must be > 0")

        heartbeat = self._heartbeats.get(strategy_id)
        if heartbeat is None:
            raise StrategyUnavailable(f"no live heartbeat for {strategy_id}")
        if heartbeat.strategy_version != strategy_version:
            raise StrategyIdentityMismatch(
                f"heartbeat version {heartbeat.strategy_version} does not match {strategy_version}"
            )
        if heartbeat.observed_at > now:
            raise StrategyStale(f"heartbeat for {strategy_id} is future-dated")
        if now - heartbeat.observed_at > timedelta(seconds=max_age_seconds):
            raise StrategyStale(f"heartbeat for {strategy_id} is stale")
        return heartbeat

    def authorize_intent(
        self,
        intent: OrderIntent,
        *,
        now: datetime,
        max_age_seconds: int,
    ) -> StrategyHeartbeat:
        if not isinstance(intent, OrderIntent):
            raise TypeError("intent must be OrderIntent")
        return self.require_fresh(
            strategy_id=intent.strategy_id,
            strategy_version=intent.strategy_version,
            now=now,
            max_age_seconds=max_age_seconds,
        )

    def clear(self) -> None:
        self._heartbeats.clear()

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from bigqmt_autotrader.risk import RuntimeMode

from .health import HealthAlert, HealthRegistry
from .mode import ModeTransitionDenied, RuntimeModeController


@dataclass(frozen=True)
class OperationsStatus:
    mode: RuntimeMode
    ready_for_mutation: bool
    alerts: tuple[HealthAlert, ...]


class OperationsControl:
    """Narrow human/automation control surface for runtime safety.

    No live-arm method exists here. Production LIVE_CANARY/LIVE_ARMED remains
    behind a future independently gated control surface.
    """

    def __init__(
        self,
        *,
        modes: RuntimeModeController,
        health: HealthRegistry,
    ) -> None:
        if not isinstance(modes, RuntimeModeController):
            raise TypeError("modes must be RuntimeModeController")
        if not isinstance(health, HealthRegistry):
            raise TypeError("health must be HealthRegistry")
        self._modes = modes
        self._health = health

    def status(self, *, now: datetime, max_age_seconds: int) -> OperationsStatus:
        snapshot = self._health.snapshot(now=now, max_age_seconds=max_age_seconds)
        return OperationsStatus(
            mode=self._modes.mode,
            ready_for_mutation=snapshot.runtime.ready_for_mutation,
            alerts=snapshot.alerts,
        )

    def enter_observe(
        self,
        *,
        request_id: str,
        actor: str,
        reason: str,
        now: datetime,
        max_age_seconds: int,
    ) -> bool:
        snapshot = self._health.snapshot(now=now, max_age_seconds=max_age_seconds)
        return self._modes.request_mode(
            request_id=request_id,
            target=RuntimeMode.OBSERVE,
            actor=actor,
            reason=reason,
            changed_at=now,
            health=snapshot.runtime,
        )

    def arm_simulation(
        self,
        *,
        request_id: str,
        actor: str,
        reason: str,
        now: datetime,
        max_age_seconds: int,
    ) -> bool:
        snapshot = self._health.snapshot(now=now, max_age_seconds=max_age_seconds)
        if not snapshot.runtime.ready_for_mutation:
            raise ModeTransitionDenied("runtime health is not ready for simulation")
        return self._modes.request_mode(
            request_id=request_id,
            target=RuntimeMode.SIMULATION,
            actor=actor,
            reason=reason,
            changed_at=now,
            health=snapshot.runtime,
        )

    def emergency_halt(
        self,
        *,
        request_id: str,
        actor: str,
        reason: str,
        now: datetime,
    ) -> bool:
        return self._modes.halt(
            request_id=request_id,
            actor=actor,
            reason=reason,
            changed_at=now,
        )

    def enforce_health(
        self,
        *,
        request_id: str,
        now: datetime,
        max_age_seconds: int,
    ) -> bool:
        snapshot = self._health.snapshot(now=now, max_age_seconds=max_age_seconds)
        return self._modes.enforce_health(
            request_id=request_id,
            health=snapshot.runtime,
            changed_at=now,
        )

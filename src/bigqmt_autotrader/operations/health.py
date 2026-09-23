from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

from .mode import RuntimeHealth


class HealthComponent(str, Enum):
    DATABASE = "DATABASE"
    OMS = "OMS"
    LEADER = "LEADER"
    RECONCILIATION = "RECONCILIATION"
    QMT = "QMT"
    MARKET_DATA = "MARKET_DATA"
    STRATEGY = "STRATEGY"


@dataclass(frozen=True)
class HealthObservation:
    component: HealthComponent
    healthy: bool
    observed_at: datetime
    detail: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.component, HealthComponent):
            raise TypeError("component must be HealthComponent")
        if not isinstance(self.healthy, bool):
            raise TypeError("healthy must be bool")
        if not isinstance(self.observed_at, datetime):
            raise TypeError("observed_at must be datetime")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        if not isinstance(self.detail, str):
            raise TypeError("detail must be str")


@dataclass(frozen=True)
class HealthAlert:
    component: HealthComponent
    reason: str


@dataclass(frozen=True)
class HealthSnapshot:
    runtime: RuntimeHealth
    alerts: tuple[HealthAlert, ...]


class HealthRegistry:
    """In-memory fail-closed runtime health registry.

    Health observations are intentionally ephemeral. A Host restart starts with
    no trusted health facts; every required component must report again before a
    mutation-capable runtime mode can be armed.
    """

    def __init__(self) -> None:
        self._observations: dict[HealthComponent, HealthObservation] = {}

    def observe(self, observation: HealthObservation) -> bool:
        if not isinstance(observation, HealthObservation):
            raise TypeError("observation must be HealthObservation")
        previous = self._observations.get(observation.component)
        if previous is not None and observation.observed_at <= previous.observed_at:
            if observation == previous:
                return False
            return False
        self._observations[observation.component] = observation
        return True

    def snapshot(self, *, now: datetime, max_age_seconds: int) -> HealthSnapshot:
        if not isinstance(now, datetime):
            raise TypeError("now must be datetime")
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        if isinstance(max_age_seconds, bool) or not isinstance(max_age_seconds, int):
            raise TypeError("max_age_seconds must be int")
        if max_age_seconds <= 0:
            raise ValueError("max_age_seconds must be > 0")

        values: dict[HealthComponent, bool] = {}
        alerts: list[HealthAlert] = []
        max_age = timedelta(seconds=max_age_seconds)

        for component in HealthComponent:
            observation = self._observations.get(component)
            if observation is None:
                values[component] = False
                alerts.append(HealthAlert(component, "MISSING"))
                continue
            if observation.observed_at > now:
                values[component] = False
                alerts.append(HealthAlert(component, "FUTURE_DATED"))
                continue
            if now - observation.observed_at > max_age:
                values[component] = False
                alerts.append(HealthAlert(component, "STALE"))
                continue
            if not observation.healthy:
                values[component] = False
                alerts.append(
                    HealthAlert(
                        component,
                        observation.detail.strip() or "UNHEALTHY",
                    )
                )
                continue
            values[component] = True

        runtime = RuntimeHealth(
            database_healthy=values[HealthComponent.DATABASE],
            oms_healthy=values[HealthComponent.OMS],
            leader_held=values[HealthComponent.LEADER],
            reconciliation_complete=values[HealthComponent.RECONCILIATION],
            qmt_healthy=values[HealthComponent.QMT],
            market_data_healthy=values[HealthComponent.MARKET_DATA],
            strategy_healthy=values[HealthComponent.STRATEGY],
        )
        return HealthSnapshot(runtime=runtime, alerts=tuple(alerts))

    def clear(self) -> None:
        self._observations.clear()

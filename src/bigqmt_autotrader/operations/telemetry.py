from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from bigqmt_autotrader.risk import RuntimeMode

from .health import HealthAlert, HealthSnapshot


class AlertSeverity(str, Enum):
    WARNING = "WARNING"
    ERROR = "ERROR"


@dataclass(frozen=True)
class ActiveAlert:
    key: str
    severity: AlertSeverity
    detail: str
    first_seen_at: datetime
    last_seen_at: datetime
    occurrences: int

    def __post_init__(self) -> None:
        if not isinstance(self.key, str) or not self.key:
            raise ValueError("key must be non-empty")
        if not isinstance(self.severity, AlertSeverity):
            raise TypeError("severity must be AlertSeverity")
        if not isinstance(self.detail, str) or not self.detail:
            raise ValueError("detail must be non-empty")
        for name in ("first_seen_at", "last_seen_at"):
            value = getattr(self, name)
            if not isinstance(value, datetime):
                raise TypeError(f"{name} must be datetime")
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{name} must be timezone-aware")
        if self.last_seen_at < self.first_seen_at:
            raise ValueError("last_seen_at cannot precede first_seen_at")
        if isinstance(self.occurrences, bool) or not isinstance(self.occurrences, int) or self.occurrences <= 0:
            raise ValueError("occurrences must be a positive integer")


@dataclass(frozen=True)
class TelemetrySnapshot:
    mode: RuntimeMode
    ready_for_mutation: bool
    active_alerts: tuple[ActiveAlert, ...]
    unknown_order_count: int
    manual_review_count: int


class OperationsTelemetry:
    """Ephemeral, replay-safe runtime metrics and alert state.

    Alerts are derived from authoritative runtime facts. They never create
    trading authority and are intentionally reconstructed after Host restart.
    """

    def __init__(self) -> None:
        self._alerts: dict[str, ActiveAlert] = {}
        self._mode = RuntimeMode.DISABLED
        self._ready_for_mutation = False
        self._unknown_order_count = 0
        self._manual_review_count = 0
        self._last_health_sync: datetime | None = None
        self._last_execution_sync: datetime | None = None
        self._last_mode_sync: datetime | None = None

    @staticmethod
    def _require_aware(name: str, value: datetime) -> None:
        if not isinstance(value, datetime):
            raise TypeError(f"{name} must be datetime")
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{name} must be timezone-aware")

    @staticmethod
    def _validate_count(name: str, value: int) -> None:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{name} must be a non-negative integer")

    def _upsert(
        self,
        *,
        key: str,
        severity: AlertSeverity,
        detail: str,
        observed_at: datetime,
    ) -> None:
        current = self._alerts.get(key)
        if current is not None and observed_at < current.last_seen_at:
            return
        if current is not None:
            self._alerts[key] = ActiveAlert(
                key=key,
                severity=severity,
                detail=detail,
                first_seen_at=current.first_seen_at,
                last_seen_at=observed_at,
                occurrences=current.occurrences + 1,
            )
        else:
            self._alerts[key] = ActiveAlert(
                key=key,
                severity=severity,
                detail=detail,
                first_seen_at=observed_at,
                last_seen_at=observed_at,
                occurrences=1,
            )

    def _resolve_prefix(self, prefix: str, keep: set[str]) -> None:
        for key in tuple(self._alerts):
            if key.startswith(prefix) and key not in keep:
                del self._alerts[key]

    def sync_health(self, snapshot: HealthSnapshot, *, observed_at: datetime) -> None:
        if not isinstance(snapshot, HealthSnapshot):
            raise TypeError("snapshot must be HealthSnapshot")
        self._require_aware("observed_at", observed_at)
        if self._last_health_sync is not None and observed_at < self._last_health_sync:
            return
        self._last_health_sync = observed_at
        self._ready_for_mutation = snapshot.runtime.ready_for_mutation

        keep: set[str] = set()
        for item in snapshot.alerts:
            if not isinstance(item, HealthAlert):
                raise TypeError("snapshot alerts must be HealthAlert")
            key = f"health:{item.component.value}"
            keep.add(key)
            self._upsert(
                key=key,
                severity=AlertSeverity.ERROR,
                detail=item.reason,
                observed_at=observed_at,
            )
        self._resolve_prefix("health:", keep)

    def sync_mode(self, mode: RuntimeMode, *, observed_at: datetime) -> None:
        if not isinstance(mode, RuntimeMode):
            raise TypeError("mode must be RuntimeMode")
        self._require_aware("observed_at", observed_at)
        if self._last_mode_sync is not None and observed_at < self._last_mode_sync:
            return
        self._last_mode_sync = observed_at
        self._mode = mode
        if mode is RuntimeMode.HALTED:
            self._upsert(
                key="runtime:HALTED",
                severity=AlertSeverity.ERROR,
                detail="runtime is HALTED",
                observed_at=observed_at,
            )
        else:
            self._alerts.pop("runtime:HALTED", None)

    def sync_execution_ambiguity(
        self,
        *,
        unknown_order_count: int,
        manual_review_count: int,
        observed_at: datetime,
    ) -> None:
        self._validate_count("unknown_order_count", unknown_order_count)
        self._validate_count("manual_review_count", manual_review_count)
        self._require_aware("observed_at", observed_at)
        if self._last_execution_sync is not None and observed_at < self._last_execution_sync:
            return
        self._last_execution_sync = observed_at
        self._unknown_order_count = unknown_order_count
        self._manual_review_count = manual_review_count

        if unknown_order_count:
            self._upsert(
                key="execution:UNKNOWN",
                severity=AlertSeverity.ERROR,
                detail=f"{unknown_order_count} unresolved UNKNOWN order(s)",
                observed_at=observed_at,
            )
        else:
            self._alerts.pop("execution:UNKNOWN", None)

        if manual_review_count:
            self._upsert(
                key="execution:MANUAL_REVIEW",
                severity=AlertSeverity.ERROR,
                detail=f"{manual_review_count} order(s) require manual review",
                observed_at=observed_at,
            )
        else:
            self._alerts.pop("execution:MANUAL_REVIEW", None)

    def snapshot(self) -> TelemetrySnapshot:
        return TelemetrySnapshot(
            mode=self._mode,
            ready_for_mutation=self._ready_for_mutation,
            active_alerts=tuple(
                self._alerts[key] for key in sorted(self._alerts)
            ),
            unknown_order_count=self._unknown_order_count,
            manual_review_count=self._manual_review_count,
        )

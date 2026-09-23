from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from bigqmt_autotrader.operations import (
    HealthSnapshot,
    OperationsControl,
    OperationsTelemetry,
    TelemetrySnapshot,
)
from bigqmt_autotrader.risk import RuntimeMode


@dataclass(frozen=True)
class SupervisorCycleResult:
    auto_halted: bool
    telemetry: TelemetrySnapshot


class RuntimeSupervisor:
    """One deterministic operations cycle for health enforcement and telemetry.

    The supervisor has no broker mutation dependency. Its only state-changing
    authority is the existing RuntimeModeController HALT path exposed through
    OperationsControl.
    """

    def __init__(
        self,
        *,
        operations: OperationsControl,
        telemetry: OperationsTelemetry,
        health_max_age_seconds: int,
    ) -> None:
        if not isinstance(operations, OperationsControl):
            raise TypeError("operations must be OperationsControl")
        if not isinstance(telemetry, OperationsTelemetry):
            raise TypeError("telemetry must be OperationsTelemetry")
        if (
            isinstance(health_max_age_seconds, bool)
            or not isinstance(health_max_age_seconds, int)
            or health_max_age_seconds <= 0
        ):
            raise ValueError("health_max_age_seconds must be a positive integer")
        self._operations = operations
        self._telemetry = telemetry
        self._health_max_age_seconds = health_max_age_seconds

    def tick(
        self,
        *,
        now: datetime,
        unknown_order_count: int,
        manual_review_count: int,
        halt_request_id: str,
    ) -> SupervisorCycleResult:
        status = self._operations.status(
            now=now,
            max_age_seconds=self._health_max_age_seconds,
        )
        health_snapshot = HealthSnapshot(
            runtime=status.health,
            alerts=status.alerts,
        )
        self._telemetry.sync_health(health_snapshot, observed_at=now)
        self._telemetry.sync_mode(status.mode, observed_at=now)
        self._telemetry.sync_execution_ambiguity(
            unknown_order_count=unknown_order_count,
            manual_review_count=manual_review_count,
            observed_at=now,
        )

        auto_halted = False
        if status.mode is RuntimeMode.SIMULATION and not status.ready_for_mutation:
            auto_halted = self._operations.enforce_health(
                request_id=halt_request_id,
                now=now,
                max_age_seconds=self._health_max_age_seconds,
            )
            if auto_halted:
                self._telemetry.sync_mode(RuntimeMode.HALTED, observed_at=now)

        return SupervisorCycleResult(
            auto_halted=auto_halted,
            telemetry=self._telemetry.snapshot(),
        )

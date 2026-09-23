from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from bigqmt_autotrader.operations import (
    OperationsControl,
    OperationsTelemetry,
    TelemetrySnapshot,
)
from bigqmt_autotrader.risk import RuntimeMode


@dataclass(frozen=True)
class RuntimeShutdownResult:
    changed: bool
    mode: RuntimeMode
    telemetry: TelemetrySnapshot


class RuntimeLifecycleController:
    """Fail-closed process lifecycle boundary.

    Shutdown never calls a broker API. It records an explicit HALTED transition
    and mirrors that terminal state into durable operations telemetry. A later
    process start still begins from DISABLED through RuntimeModeController.
    """

    def __init__(
        self,
        *,
        operations: OperationsControl,
        telemetry: OperationsTelemetry,
        runtime_session_id: str,
    ) -> None:
        if not isinstance(operations, OperationsControl):
            raise TypeError("operations must be OperationsControl")
        if not isinstance(telemetry, OperationsTelemetry):
            raise TypeError("telemetry must be OperationsTelemetry")
        if not isinstance(runtime_session_id, str) or not runtime_session_id.strip():
            raise ValueError("runtime_session_id must be non-empty")
        self._operations = operations
        self._telemetry = telemetry
        self._runtime_session_id = runtime_session_id

    def shutdown(
        self,
        *,
        now: datetime,
        reason: str = "runtime shutdown",
    ) -> RuntimeShutdownResult:
        if not isinstance(now, datetime):
            raise TypeError("now must be datetime")
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("reason must be non-empty")

        changed = self._operations.emergency_halt(
            request_id=f"shutdown:{self._runtime_session_id}",
            actor="runtime-lifecycle",
            reason=reason,
            now=now,
        )
        self._telemetry.sync_mode(RuntimeMode.HALTED, observed_at=now)
        snapshot = self._telemetry.snapshot()
        return RuntimeShutdownResult(
            changed=changed,
            mode=RuntimeMode.HALTED,
            telemetry=snapshot,
        )

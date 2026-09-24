from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

from bigqmt_autotrader.core import ExecutionPort, OrderIntent, SubmitResult
from bigqmt_autotrader.risk import RiskPolicy, RiskSnapshot, evaluate_risk


class RiskManagedOms:
    """Production Runtime adapter that owns policy evaluation above Core OMS."""

    def __init__(
        self,
        execution: ExecutionPort,
        policy: RiskPolicy,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not isinstance(execution, ExecutionPort):
            raise TypeError("execution must satisfy ExecutionPort")
        if not isinstance(policy, RiskPolicy):
            raise TypeError("policy must be RiskPolicy")
        self._execution = execution
        self._policy = policy
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def submit_intent(self, intent: OrderIntent, snapshot: RiskSnapshot) -> SubmitResult:
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("RiskManagedOms clock must be timezone-aware")
        evaluation = evaluate_risk(intent, snapshot, self._policy, now=now)
        return self._execution.submit_authorized(
            intent,
            evaluation.decision,
            evaluation=evaluation,
        )

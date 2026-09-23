from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

from bigqmt_autotrader.domain import OrderIntent
from bigqmt_autotrader.oms import OfflineOms, SubmitResult
from bigqmt_autotrader.risk import RiskPolicy, RiskSnapshot, evaluate_risk


class RiskManagedOms:
    """Production Runtime adapter that owns policy evaluation above Core OMS."""

    def __init__(
        self,
        oms: OfflineOms,
        policy: RiskPolicy,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not isinstance(oms, OfflineOms):
            raise TypeError("oms must be OfflineOms")
        if not isinstance(policy, RiskPolicy):
            raise TypeError("policy must be RiskPolicy")
        self._oms = oms
        self._policy = policy
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def submit_intent(self, intent: OrderIntent, snapshot: RiskSnapshot) -> SubmitResult:
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("RiskManagedOms clock must be timezone-aware")
        evaluation = evaluate_risk(intent, snapshot, self._policy, now=now)
        return self._oms.submit_authorized_intent(
            intent,
            evaluation.decision,
            risk_evaluation=evaluation,
        )

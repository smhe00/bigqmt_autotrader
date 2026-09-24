from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from bigqmt_autotrader.domain import OrderIntent, OrderStatus, RiskDecision
from bigqmt_autotrader.oms import BrokerEvidenceV1, CancelResult, SubmitResult


@runtime_checkable
class ExecutionPort(Protocol):
    """Stable public execution contract consumed by Production Runtime."""

    @property
    def reconciled(self) -> bool: ...

    def recover(self) -> None: ...

    def submit(self, intent: OrderIntent) -> SubmitResult: ...

    def submit_authorized(
        self,
        intent: OrderIntent,
        decision: RiskDecision,
        *,
        evaluation: Any | None = None,
    ) -> SubmitResult: ...

    def cancel(
        self,
        account_fingerprint: str,
        client_order_id: str,
    ) -> CancelResult: ...

    def status(
        self,
        account_fingerprint: str,
        client_order_id: str,
    ) -> OrderStatus: ...

    def ingest_evidence(self, evidence: BrokerEvidenceV1) -> OrderStatus: ...

    def close(self) -> None: ...

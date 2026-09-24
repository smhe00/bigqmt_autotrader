from __future__ import annotations

from typing import Protocol, runtime_checkable

from bigqmt_autotrader.domain import OrderIntent, OrderStatus


class SubmitOutcomeUnknown(RuntimeError):
    """A submit may have crossed the broker boundary but its outcome is unknown."""


class CancelOutcomeUnknown(RuntimeError):
    """A cancel may have crossed the broker boundary but its outcome is unknown."""


@runtime_checkable
class BrokerOrderObservation(Protocol):
    """Broker-neutral lifecycle observation returned by an ExecutionDriver query."""

    broker_order_id: str
    status: OrderStatus
    filled_quantity: int


@runtime_checkable
class ExecutionDriver(Protocol):
    """Minimal broker-neutral side-effect port owned by Execution Core."""

    def submit_limit_order(self, intent: OrderIntent) -> object:
        ...

    def cancel_order(self, account_fingerprint: str, client_order_id: str) -> object:
        ...

    def query_by_client_order_id(
        self,
        account_fingerprint: str,
        client_order_id: str,
    ) -> BrokerOrderObservation | None:
        ...

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from bigqmt_autotrader.domain import OrderIntent, OrderStatus


class SubmitOutcomeUnknown(RuntimeError):
    pass


class DuplicateBrokerSubmit(RuntimeError):
    pass


class SubmitFailureMode(str, Enum):
    NONE = "NONE"
    TIMEOUT_BEFORE_ACCEPT = "TIMEOUT_BEFORE_ACCEPT"
    TIMEOUT_AFTER_ACCEPT = "TIMEOUT_AFTER_ACCEPT"


@dataclass(frozen=True)
class SimulatedOrderEvidence:
    broker_order_id: str
    status: OrderStatus
    filled_quantity: int = 0


class SimulatedDriver:
    """Deterministic in-memory broker oracle for P1 only."""

    def __init__(self) -> None:
        self._orders: dict[tuple[str, str], SimulatedOrderEvidence] = {}
        self._submit_calls: dict[tuple[str, str], int] = {}
        self._next_failure = SubmitFailureMode.NONE
        self._sequence = 0

    def fail_next_submit(self, mode: SubmitFailureMode) -> None:
        self._next_failure = mode

    def submit_limit_order(self, intent: OrderIntent) -> SimulatedOrderEvidence:
        key = (intent.account_fingerprint, intent.client_order_id)
        self._submit_calls[key] = self._submit_calls.get(key, 0) + 1
        if self._submit_calls[key] > 1:
            raise DuplicateBrokerSubmit(f"duplicate simulated submit: {key}")

        mode = self._next_failure
        self._next_failure = SubmitFailureMode.NONE
        if mode is SubmitFailureMode.TIMEOUT_BEFORE_ACCEPT:
            raise SubmitOutcomeUnknown("simulated timeout before broker acceptance")

        self._sequence += 1
        evidence = SimulatedOrderEvidence(
            broker_order_id=f"SIM-{self._sequence:08d}",
            status=OrderStatus.ACKNOWLEDGED,
        )
        self._orders[key] = evidence

        if mode is SubmitFailureMode.TIMEOUT_AFTER_ACCEPT:
            raise SubmitOutcomeUnknown("simulated response loss after broker acceptance")
        return evidence

    def query_by_client_order_id(
        self, account_fingerprint: str, client_order_id: str
    ) -> SimulatedOrderEvidence | None:
        return self._orders.get((account_fingerprint, client_order_id))

    def submit_call_count(self, account_fingerprint: str, client_order_id: str) -> int:
        return self._submit_calls.get((account_fingerprint, client_order_id), 0)

    def set_order_status(
        self,
        account_fingerprint: str,
        client_order_id: str,
        status: OrderStatus,
        *,
        filled_quantity: int = 0,
    ) -> None:
        key = (account_fingerprint, client_order_id)
        current = self._orders[key]
        self._orders[key] = SimulatedOrderEvidence(
            broker_order_id=current.broker_order_id,
            status=status,
            filled_quantity=filled_quantity,
        )

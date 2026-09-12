from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from bigqmt_autotrader.domain import OrderIntent, OrderStatus


class SubmitOutcomeUnknown(RuntimeError):
    pass


class CancelOutcomeUnknown(RuntimeError):
    pass


class SimulatedProcessCrash(BaseException):
    """Test-only hard process-loss sentinel.

    It intentionally inherits directly from BaseException so normal OMS
    exception handling must not convert a simulated process death into a
    recoverable in-process error. Tests catch it at the process boundary.
    """


class DuplicateBrokerSubmit(RuntimeError):
    pass


class DuplicateBrokerCancel(RuntimeError):
    pass


class SubmitFailureMode(str, Enum):
    NONE = "NONE"
    TIMEOUT_BEFORE_ACCEPT = "TIMEOUT_BEFORE_ACCEPT"
    TIMEOUT_AFTER_ACCEPT = "TIMEOUT_AFTER_ACCEPT"
    CRASH_BEFORE_ACCEPT = "CRASH_BEFORE_ACCEPT"
    CRASH_AFTER_ACCEPT = "CRASH_AFTER_ACCEPT"


class CancelFailureMode(str, Enum):
    NONE = "NONE"
    TIMEOUT_BEFORE_ACCEPT = "TIMEOUT_BEFORE_ACCEPT"
    TIMEOUT_AFTER_ACCEPT = "TIMEOUT_AFTER_ACCEPT"
    CRASH_BEFORE_ACCEPT = "CRASH_BEFORE_ACCEPT"
    CRASH_AFTER_ACCEPT = "CRASH_AFTER_ACCEPT"


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
        self._cancel_calls: dict[tuple[str, str], int] = {}
        self._next_submit_failure = SubmitFailureMode.NONE
        self._next_cancel_failure = CancelFailureMode.NONE
        self._sequence = 0

    def fail_next_submit(self, mode: SubmitFailureMode) -> None:
        self._next_submit_failure = mode

    def fail_next_cancel(self, mode: CancelFailureMode) -> None:
        self._next_cancel_failure = mode

    def submit_limit_order(self, intent: OrderIntent) -> SimulatedOrderEvidence:
        key = (intent.account_fingerprint, intent.client_order_id)
        self._submit_calls[key] = self._submit_calls.get(key, 0) + 1
        if self._submit_calls[key] > 1:
            raise DuplicateBrokerSubmit(f"duplicate simulated submit: {key}")

        mode = self._next_submit_failure
        self._next_submit_failure = SubmitFailureMode.NONE
        if mode is SubmitFailureMode.TIMEOUT_BEFORE_ACCEPT:
            raise SubmitOutcomeUnknown("simulated timeout before broker acceptance")
        if mode is SubmitFailureMode.CRASH_BEFORE_ACCEPT:
            raise SimulatedProcessCrash("simulated process crash before broker acceptance")

        self._sequence += 1
        evidence = SimulatedOrderEvidence(
            broker_order_id=f"SIM-{self._sequence:08d}",
            status=OrderStatus.ACKNOWLEDGED,
        )
        self._orders[key] = evidence

        if mode is SubmitFailureMode.TIMEOUT_AFTER_ACCEPT:
            raise SubmitOutcomeUnknown("simulated response loss after broker acceptance")
        if mode is SubmitFailureMode.CRASH_AFTER_ACCEPT:
            raise SimulatedProcessCrash("simulated process crash after broker acceptance")
        return evidence

    def cancel_order(self, account_fingerprint: str, client_order_id: str) -> SimulatedOrderEvidence:
        key = (account_fingerprint, client_order_id)
        self._cancel_calls[key] = self._cancel_calls.get(key, 0) + 1
        if self._cancel_calls[key] > 1:
            raise DuplicateBrokerCancel(f"duplicate simulated cancel: {key}")

        current = self._orders[key]
        mode = self._next_cancel_failure
        self._next_cancel_failure = CancelFailureMode.NONE
        if mode is CancelFailureMode.TIMEOUT_BEFORE_ACCEPT:
            raise CancelOutcomeUnknown("simulated timeout before cancel acceptance")
        if mode is CancelFailureMode.CRASH_BEFORE_ACCEPT:
            raise SimulatedProcessCrash("simulated process crash before cancel acceptance")

        evidence = SimulatedOrderEvidence(
            broker_order_id=current.broker_order_id,
            status=OrderStatus.CANCELLED,
            filled_quantity=current.filled_quantity,
        )
        self._orders[key] = evidence

        if mode is CancelFailureMode.TIMEOUT_AFTER_ACCEPT:
            raise CancelOutcomeUnknown("simulated response loss after cancel acceptance")
        if mode is CancelFailureMode.CRASH_AFTER_ACCEPT:
            raise SimulatedProcessCrash("simulated process crash after cancel acceptance")
        return evidence

    def query_by_client_order_id(
        self, account_fingerprint: str, client_order_id: str
    ) -> SimulatedOrderEvidence | None:
        return self._orders.get((account_fingerprint, client_order_id))

    def submit_call_count(self, account_fingerprint: str, client_order_id: str) -> int:
        return self._submit_calls.get((account_fingerprint, client_order_id), 0)

    def cancel_call_count(self, account_fingerprint: str, client_order_id: str) -> int:
        return self._cancel_calls.get((account_fingerprint, client_order_id), 0)

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

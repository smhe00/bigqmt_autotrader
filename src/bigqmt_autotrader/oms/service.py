from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from bigqmt_autotrader.domain import OrderIntent, OrderStatus, RiskDecision
from bigqmt_autotrader.drivers.simulated import (
    CancelOutcomeUnknown,
    SimulatedDriver,
    SubmitOutcomeUnknown,
)

from .repository import OmsRepository


class OmsNotReconciled(RuntimeError):
    pass


@dataclass(frozen=True)
class SubmitResult:
    status: OrderStatus
    broker_order_id: str | None = None


@dataclass(frozen=True)
class CancelResult:
    status: OrderStatus
    broker_order_id: str | None = None


class OfflineOms:
    """P1 single-process/single-writer OMS against a simulated driver only."""

    def __init__(self, repository: OmsRepository, driver: SimulatedDriver) -> None:
        self.repository = repository
        self.driver = driver
        self.session_id = str(uuid4())
        self.repository.start_session(self.session_id)
        self._reconciled = False

    @property
    def reconciled(self) -> bool:
        return self._reconciled

    def recover(self) -> None:
        for row in self.repository.list_recovery_candidates():
            account = row["account_fingerprint"]
            client_order_id = row["client_order_id"]
            status = OrderStatus(row["status"])
            cancel_unresolved = bool(row["cancel_call_started"]) and not bool(
                row["cancel_outcome_resolved"]
            )

            if status is OrderStatus.SUBMITTING:
                self.repository.transition_order(
                    account,
                    client_order_id,
                    OrderStatus.UNKNOWN,
                    event_type="STARTUP_SUBMIT_AMBIGUITY",
                    evidence={"reason": "submit reservation existed at restart"},
                )
                status = OrderStatus.UNKNOWN

            # Execution state and cancel-attempt state are orthogonal. A partial
            # fill callback may have replaced CANCEL_PENDING in the aggregate
            # order state while the cancel outcome was still unresolved. Restore
            # the pending-cancel marker before entering UNKNOWN/reconciliation.
            if cancel_unresolved and status in {
                OrderStatus.ACKNOWLEDGED,
                OrderStatus.PARTIALLY_FILLED,
            }:
                self.repository.transition_order(
                    account,
                    client_order_id,
                    OrderStatus.CANCEL_PENDING,
                    event_type="STARTUP_RESTORE_CANCEL_PENDING",
                    evidence={"reason": "durable cancel attempt remains unresolved"},
                )
                status = OrderStatus.CANCEL_PENDING

            if cancel_unresolved and status in {
                OrderStatus.FILLED,
                OrderStatus.CANCELLED,
                OrderStatus.REJECTED,
            }:
                self.repository.transition_order(
                    account,
                    client_order_id,
                    status,
                    event_type="STARTUP_CANCEL_ALREADY_TERMINAL",
                    evidence={"reason": "terminal broker lifecycle resolves cancel ambiguity"},
                    cancel_outcome_resolved=True,
                )
                continue

            if status is OrderStatus.CANCEL_PENDING:
                self.repository.transition_order(
                    account,
                    client_order_id,
                    OrderStatus.UNKNOWN,
                    event_type="STARTUP_CANCEL_AMBIGUITY",
                    evidence={
                        "reason": "cancel reservation existed at restart",
                        "cancel_call_started": bool(row["cancel_call_started"]),
                    },
                )
                status = OrderStatus.UNKNOWN

            if status is OrderStatus.UNKNOWN:
                self.repository.transition_order(
                    account,
                    client_order_id,
                    OrderStatus.RECONCILING,
                    event_type="STARTUP_RECONCILE_BEGIN",
                )
                status = OrderStatus.RECONCILING

            evidence = self.driver.query_by_client_order_id(account, client_order_id)
            if evidence is None:
                self.repository.transition_order(
                    account,
                    client_order_id,
                    OrderStatus.MANUAL_REVIEW,
                    event_type="RECONCILE_NOT_FOUND",
                    evidence={"policy": "do_not_resubmit_or_recancel"},
                    cancel_outcome_resolved=True if cancel_unresolved else None,
                )
            else:
                self.repository.transition_order(
                    account,
                    client_order_id,
                    evidence.status,
                    event_type="RECONCILE_BROKER_EVIDENCE",
                    evidence={"broker_order_id": evidence.broker_order_id},
                    broker_order_id=evidence.broker_order_id,
                    filled_quantity=evidence.filled_quantity,
                    cancel_outcome_resolved=True if cancel_unresolved else None,
                )

        self.repository.mark_session_reconciled(self.session_id)
        self._reconciled = True

    def submit_intent(self, intent: OrderIntent, decision: RiskDecision) -> SubmitResult:
        if not self._reconciled:
            raise OmsNotReconciled("startup reconciliation must complete before new intents")

        self.repository.create_intent(intent)
        status = self.repository.record_risk_decision(
            intent.account_fingerprint, intent.client_order_id, decision
        )
        if status is OrderStatus.RISK_REJECTED:
            return SubmitResult(status=status)

        # This commit happens before the simulated side effect. Once reserved,
        # this client order identity is never automatically submitted again.
        self.repository.prepare_submit(intent.account_fingerprint, intent.client_order_id)

        try:
            ack = self.driver.submit_limit_order(intent)
        except SubmitOutcomeUnknown as exc:
            self.repository.transition_order(
                intent.account_fingerprint,
                intent.client_order_id,
                OrderStatus.UNKNOWN,
                event_type="SUBMIT_OUTCOME_UNKNOWN",
                evidence={"error": str(exc)},
            )
            return SubmitResult(status=OrderStatus.UNKNOWN)
        except BaseException as exc:
            self.repository.transition_order(
                intent.account_fingerprint,
                intent.client_order_id,
                OrderStatus.UNKNOWN,
                event_type="SUBMIT_EXCEPTION_UNKNOWN",
                evidence={"error_type": type(exc).__name__},
            )
            return SubmitResult(status=OrderStatus.UNKNOWN)

        self.repository.transition_order(
            intent.account_fingerprint,
            intent.client_order_id,
            OrderStatus.ACKNOWLEDGED,
            event_type="SUBMIT_ACK",
            evidence={"broker_order_id": ack.broker_order_id},
            broker_order_id=ack.broker_order_id,
        )
        return SubmitResult(status=OrderStatus.ACKNOWLEDGED, broker_order_id=ack.broker_order_id)

    def cancel_order(self, account_fingerprint: str, client_order_id: str) -> CancelResult:
        if not self._reconciled:
            raise OmsNotReconciled("startup reconciliation must complete before cancellation")

        self.repository.prepare_cancel(account_fingerprint, client_order_id)

        try:
            ack = self.driver.cancel_order(account_fingerprint, client_order_id)
        except CancelOutcomeUnknown as exc:
            self.repository.transition_order(
                account_fingerprint,
                client_order_id,
                OrderStatus.UNKNOWN,
                event_type="CANCEL_OUTCOME_UNKNOWN",
                evidence={"error": str(exc)},
            )
            return CancelResult(status=OrderStatus.UNKNOWN)
        except BaseException as exc:
            self.repository.transition_order(
                account_fingerprint,
                client_order_id,
                OrderStatus.UNKNOWN,
                event_type="CANCEL_EXCEPTION_UNKNOWN",
                evidence={"error_type": type(exc).__name__},
            )
            return CancelResult(status=OrderStatus.UNKNOWN)

        self.repository.transition_order(
            account_fingerprint,
            client_order_id,
            OrderStatus.CANCELLED,
            event_type="CANCEL_ACK",
            evidence={"broker_order_id": ack.broker_order_id},
            broker_order_id=ack.broker_order_id,
            filled_quantity=ack.filled_quantity,
            cancel_outcome_resolved=True,
        )
        return CancelResult(status=OrderStatus.CANCELLED, broker_order_id=ack.broker_order_id)

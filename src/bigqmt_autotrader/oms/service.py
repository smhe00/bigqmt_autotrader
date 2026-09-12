from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from bigqmt_autotrader.domain import OrderIntent, OrderStatus, RiskDecision
from bigqmt_autotrader.drivers.simulated import SimulatedDriver, SubmitOutcomeUnknown

from .repository import OmsRepository


class OmsNotReconciled(RuntimeError):
    pass


@dataclass(frozen=True)
class SubmitResult:
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

            if status is OrderStatus.SUBMITTING:
                self.repository.transition_order(
                    account,
                    client_order_id,
                    OrderStatus.UNKNOWN,
                    event_type="STARTUP_SUBMIT_AMBIGUITY",
                    evidence={"reason": "submit reservation existed at restart"},
                )
                status = OrderStatus.UNKNOWN

            if status is OrderStatus.UNKNOWN:
                self.repository.transition_order(
                    account,
                    client_order_id,
                    OrderStatus.RECONCILING,
                    event_type="STARTUP_RECONCILE_BEGIN",
                )

            evidence = self.driver.query_by_client_order_id(account, client_order_id)
            if evidence is None:
                self.repository.transition_order(
                    account,
                    client_order_id,
                    OrderStatus.MANUAL_REVIEW,
                    event_type="RECONCILE_NOT_FOUND",
                    evidence={"policy": "do_not_resubmit"},
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
            # After the side-effect boundary any unexpected error is ambiguous.
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

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable
from uuid import uuid4

from bigqmt_autotrader.domain import OrderIntent, OrderStatus, RiskDecision
from bigqmt_autotrader.drivers.simulated import (
    CancelOutcomeUnknown,
    SimulatedDriver,
    SubmitOutcomeUnknown,
)

from .leader import LeaderCoordinator, LeaderLease
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
    """P1 single-machine OMS against a simulated driver only.

    Construction acquires the SQLite-backed OMS leader lease. The surrounding
    service loop must heartbeat before the lease expires. Every recovery and
    broker side-effect path verifies the fencing token and fails closed if
    ownership was lost.
    """

    def __init__(
        self,
        repository: OmsRepository,
        driver: SimulatedDriver,
        *,
        leader_lease_seconds: int = 30,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if leader_lease_seconds <= 0:
            raise ValueError("leader_lease_seconds must be positive")

        self.repository = repository
        self.driver = driver
        self.session_id = str(uuid4())
        self._reconciled = False
        self._leader_lease_seconds = leader_lease_seconds
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._leader = LeaderCoordinator(repository.conn)
        self._closed = False

        self._leader_lease = self._leader.acquire(
            self.session_id,
            lease_seconds=self._leader_lease_seconds,
            now=self._now(),
        )
        try:
            self.repository.start_session(self.session_id)
        except BaseException:
            self._leader.release(self._leader_lease)
            raise

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("OMS clock must return timezone-aware datetime")
        return value

    @property
    def reconciled(self) -> bool:
        return self._reconciled

    @property
    def leader_lease(self) -> LeaderLease:
        return self._leader_lease

    def assert_leader(self) -> None:
        if self._closed:
            raise RuntimeError("OMS instance is closed")
        self._leader.assert_held(self._leader_lease, now=self._now())

    def heartbeat(self) -> LeaderLease:
        if self._closed:
            raise RuntimeError("OMS instance is closed")
        self._leader_lease = self._leader.heartbeat(
            self._leader_lease,
            lease_seconds=self._leader_lease_seconds,
            now=self._now(),
        )
        return self._leader_lease

    def close(self) -> None:
        if self._closed:
            return
        self._leader.release(self._leader_lease)
        self._closed = True
        self._reconciled = False

    def recover(self) -> None:
        self.assert_leader()
        for row in self.repository.list_recovery_candidates():
            # Keep a long reconciliation pass from silently running past its
            # lease. Heartbeat refuses to resurrect an already-expired lease.
            self.heartbeat()

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

            self.assert_leader()
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

        self.assert_leader()
        self.repository.mark_session_reconciled(self.session_id)
        self._reconciled = True
        self.heartbeat()

    def submit_intent(self, intent: OrderIntent, decision: RiskDecision) -> SubmitResult:
        self.assert_leader()
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

        # Re-check the fencing token after the durable reservation and as close
        # as possible to the external side effect. If ownership was lost, the
        # order remains SUBMITTING and the new leader must reconcile it; the old
        # leader never calls the broker.
        self.assert_leader()
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
        self.assert_leader()
        if not self._reconciled:
            raise OmsNotReconciled("startup reconciliation must complete before cancellation")

        self.repository.prepare_cancel(account_fingerprint, client_order_id)

        # Same fencing rule as submit: a lost leader leaves the durable cancel
        # reservation unresolved for the successor to reconcile, never recancel.
        self.assert_leader()
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

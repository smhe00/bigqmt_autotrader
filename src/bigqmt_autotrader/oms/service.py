from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Mapping
from uuid import uuid4

from bigqmt_autotrader.domain import OrderIntent, OrderStatus, RiskDecision
from bigqmt_autotrader.drivers.simulated import (
    CancelOutcomeUnknown,
    SimulatedDriver,
    SubmitOutcomeUnknown,
)
from bigqmt_autotrader.risk import RiskEvaluation, RiskPolicy, RiskSnapshot, evaluate_risk

from .evidence import EvidenceIngestResult, EvidenceJournal
from .leader import LeaderCoordinator, LeaderLease
from .repository import OmsRepository


class OmsNotReconciled(RuntimeError):
    pass


class RecoveryInvariantViolation(RuntimeError):
    pass


@dataclass(frozen=True)
class SubmitResult:
    status: OrderStatus
    broker_order_id: str | None = None
    risk_evaluation: RiskEvaluation | None = None


@dataclass(frozen=True)
class CancelResult:
    status: OrderStatus
    broker_order_id: str | None = None


class OfflineOms:
    """Single-machine OMS with P1 persistence and P2 pre-trade risk ownership.

    Construction acquires the SQLite-backed OMS leader lease. Every repository
    write, recovery operation, broker side effect and callback/evidence write is
    fenced by the current lease token. Public order submission evaluates risk
    inside the OMS; callers cannot supply an already-accepted RiskDecision.
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
        self.repository.bind_write_guard(self.assert_leader)
        try:
            self.repository.start_session(self.session_id)
        except BaseException:
            self._leader.release(self._leader_lease)
            raise

        self._evidence_journal = EvidenceJournal(
            repository,
            write_guard=self.assert_leader,
        )

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

    def ingest_broker_evidence(
        self,
        *,
        source: str,
        source_event_id: str | None,
        account_fingerprint: str,
        client_order_id: str,
        evidence_type: str,
        requested_status: OrderStatus,
        filled_quantity: int,
        broker_order_id: str | None = None,
        payload: Mapping[str, Any] | None = None,
        observed_at: datetime | None = None,
    ) -> EvidenceIngestResult:
        return self._evidence_journal.ingest(
            source=source,
            source_event_id=source_event_id,
            account_fingerprint=account_fingerprint,
            client_order_id=client_order_id,
            evidence_type=evidence_type,
            requested_status=requested_status,
            filled_quantity=filled_quantity,
            broker_order_id=broker_order_id,
            payload=payload,
            observed_at=observed_at,
        )

    def list_broker_evidence(self, account_fingerprint: str, client_order_id: str):
        return self._evidence_journal.list_observations(account_fingerprint, client_order_id)

    def recover(self) -> None:
        self.assert_leader()
        for row in self.repository.list_recovery_candidates():
            self.heartbeat()

            account = row["account_fingerprint"]
            client_order_id = row["client_order_id"]
            status = OrderStatus(row["status"])
            submit_started = bool(row["submit_call_started"])
            cancel_started = bool(row["cancel_call_started"])
            cancel_unresolved = cancel_started and not bool(row["cancel_outcome_resolved"])

            if status in {OrderStatus.CREATED, OrderStatus.RISK_ACCEPTED}:
                if submit_started or cancel_started or row["broker_order_id"] is not None:
                    raise RecoveryInvariantViolation(
                        f"pre-submit state {status.value} has impossible side-effect evidence "
                        f"for {client_order_id}"
                    )
                self.repository.transition_order(
                    account,
                    client_order_id,
                    OrderStatus.ABORTED,
                    event_type="STARTUP_PRE_SUBMIT_ABORT",
                    evidence={
                        "reason": "restart found durable pre-side-effect orphan",
                        "policy": "abort_and_require_new_intent_and_risk",
                    },
                )
                continue

            if status is OrderStatus.SUBMITTING:
                if not submit_started:
                    raise RecoveryInvariantViolation(
                        f"SUBMITTING without submit reservation: {client_order_id}"
                    )
                self.repository.transition_order(
                    account,
                    client_order_id,
                    OrderStatus.UNKNOWN,
                    event_type="STARTUP_SUBMIT_AMBIGUITY",
                    evidence={"reason": "submit reservation existed at restart"},
                )
                status = OrderStatus.UNKNOWN

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
                if not cancel_started:
                    raise RecoveryInvariantViolation(
                        f"CANCEL_PENDING without cancel reservation: {client_order_id}"
                    )
                self.repository.transition_order(
                    account,
                    client_order_id,
                    OrderStatus.UNKNOWN,
                    event_type="STARTUP_CANCEL_AMBIGUITY",
                    evidence={
                        "reason": "cancel reservation existed at restart",
                        "cancel_call_started": True,
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
            self.assert_leader()
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

        self.heartbeat()
        self.repository.mark_session_reconciled(self.session_id)
        self.assert_leader()
        self._reconciled = True

    def submit_intent(
        self,
        intent: OrderIntent,
        risk_snapshot: RiskSnapshot,
        risk_policy: RiskPolicy,
    ) -> SubmitResult:
        """Public submit path: risk is evaluated inside the OMS.

        A caller supplies facts/policy, never an accepted RiskDecision. Leader and
        startup-reconciliation gates are independently enforced by the OMS before
        any risk decision can become durable execution authority.
        """
        self.assert_leader()
        if not self._reconciled:
            raise OmsNotReconciled("startup reconciliation must complete before new intents")
        evaluation = evaluate_risk(
            intent,
            risk_snapshot,
            risk_policy,
            now=self._now(),
        )
        return self._submit_decided_intent(
            intent,
            evaluation.decision,
            risk_evaluation=evaluation,
        )

    def _submit_decided_intent(
        self,
        intent: OrderIntent,
        decision: RiskDecision,
        *,
        risk_evaluation: RiskEvaluation | None = None,
    ) -> SubmitResult:
        """Internal/test hook after deterministic risk evaluation.

        Production source code may call this method only from ``submit_intent``.
        P1 tests use it to isolate persistence/recovery behavior from P2 rules.
        """
        self.assert_leader()
        if not self._reconciled:
            raise OmsNotReconciled("startup reconciliation must complete before new intents")

        self.repository.create_intent(intent)
        status = self.repository.record_risk_decision(
            intent.account_fingerprint, intent.client_order_id, decision
        )
        if status is OrderStatus.RISK_REJECTED:
            return SubmitResult(status=status, risk_evaluation=risk_evaluation)

        self.repository.prepare_submit(intent.account_fingerprint, intent.client_order_id)
        self.assert_leader()
        try:
            ack = self.driver.submit_limit_order(intent)
        except SubmitOutcomeUnknown as exc:
            self.assert_leader()
            self.repository.transition_order(
                intent.account_fingerprint,
                intent.client_order_id,
                OrderStatus.UNKNOWN,
                event_type="SUBMIT_OUTCOME_UNKNOWN",
                evidence={"error": str(exc)},
            )
            return SubmitResult(status=OrderStatus.UNKNOWN, risk_evaluation=risk_evaluation)
        except Exception as exc:
            self.assert_leader()
            self.repository.transition_order(
                intent.account_fingerprint,
                intent.client_order_id,
                OrderStatus.UNKNOWN,
                event_type="SUBMIT_EXCEPTION_UNKNOWN",
                evidence={"error_type": type(exc).__name__},
            )
            return SubmitResult(status=OrderStatus.UNKNOWN, risk_evaluation=risk_evaluation)

        self.assert_leader()
        self.repository.transition_order(
            intent.account_fingerprint,
            intent.client_order_id,
            OrderStatus.ACKNOWLEDGED,
            event_type="SUBMIT_ACK",
            evidence={"broker_order_id": ack.broker_order_id},
            broker_order_id=ack.broker_order_id,
        )
        return SubmitResult(
            status=OrderStatus.ACKNOWLEDGED,
            broker_order_id=ack.broker_order_id,
            risk_evaluation=risk_evaluation,
        )

    def cancel_order(self, account_fingerprint: str, client_order_id: str) -> CancelResult:
        self.assert_leader()
        if not self._reconciled:
            raise OmsNotReconciled("startup reconciliation must complete before cancellation")

        self.repository.prepare_cancel(account_fingerprint, client_order_id)
        self.assert_leader()
        try:
            ack = self.driver.cancel_order(account_fingerprint, client_order_id)
        except CancelOutcomeUnknown as exc:
            self.assert_leader()
            self.repository.transition_order(
                account_fingerprint,
                client_order_id,
                OrderStatus.UNKNOWN,
                event_type="CANCEL_OUTCOME_UNKNOWN",
                evidence={"error": str(exc)},
            )
            return CancelResult(status=OrderStatus.UNKNOWN)
        except Exception as exc:
            self.assert_leader()
            self.repository.transition_order(
                account_fingerprint,
                client_order_id,
                OrderStatus.UNKNOWN,
                event_type="CANCEL_EXCEPTION_UNKNOWN",
                evidence={"error_type": type(exc).__name__},
            )
            return CancelResult(status=OrderStatus.UNKNOWN)

        self.assert_leader()
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

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Mapping
from uuid import uuid4

from bigqmt_autotrader.domain import OrderIntent, OrderStatus, RiskDecision
from bigqmt_autotrader.ports import (
    BrokerOrderObservation,
    CancelOutcomeUnknown,
    ExecutionDriver,
    SubmitOutcomeUnknown,
)
from .authorization import core_execution_decision
from .broker_evidence_v1 import (
    BrokerEvidenceSourceKind,
    BrokerEvidenceType,
    BrokerEvidenceV1,
)
from .command_results import CommandResultIngestResult, QmtCommandResultJournal
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
    risk_evaluation: object | None = None


@dataclass(frozen=True)
class CancelResult:
    status: OrderStatus
    broker_order_id: str | None = None


class OfflineOms:
    """Single-machine Execution Core OMS.

    Construction acquires the SQLite-backed OMS leader lease. Every repository
    write, recovery operation, broker side effect and callback/evidence write is
    fenced by the current lease token. Core submission does not import or own
    Production Risk; a Runtime wrapper may supply a durable authorization.
    """

    def __init__(
        self,
        repository: OmsRepository,
        driver: ExecutionDriver,
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
        self._command_result_journal = QmtCommandResultJournal(
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
        self, evidence: BrokerEvidenceV1
    ) -> EvidenceIngestResult:
        return self._evidence_journal.ingest(evidence)

    def list_broker_evidence(self, account_fingerprint: str, client_order_id: str):
        return self._evidence_journal.list_observations(account_fingerprint, client_order_id)

    def _ingest_active_query_evidence(
        self,
        account_fingerprint: str,
        client_order_id: str,
        query_evidence: BrokerOrderObservation,
        *,
        reason: str,
    ) -> EvidenceIngestResult:
        evidence_type = {
            OrderStatus.ACKNOWLEDGED: BrokerEvidenceType.ORDER_ACCEPTED,
            OrderStatus.PARTIALLY_FILLED: BrokerEvidenceType.PARTIAL_FILL,
            OrderStatus.FILLED: BrokerEvidenceType.FULL_FILL,
            OrderStatus.CANCELLED: BrokerEvidenceType.ORDER_CANCELLED,
            OrderStatus.REJECTED: BrokerEvidenceType.ORDER_REJECTED,
        }.get(query_evidence.status)
        if evidence_type is None:
            raise RecoveryInvariantViolation(
                f"active query returned non-broker lifecycle status {query_evidence.status.value}"
            )
        observed_at_ms = int(self._now().timestamp() * 1000)
        return self._evidence_journal.ingest(BrokerEvidenceV1.build(
            source="simulated-driver-active-query",
            source_kind=BrokerEvidenceSourceKind.ACTIVE_ORDER_QUERY,
            source_event_id=self.session_id + ":" + reason + ":" + client_order_id,
            mapper_profile="simulated-driver-query-v1",
            account_fingerprint=account_fingerprint,
            client_order_id=client_order_id,
            broker_token=None,
            broker_order_id=query_evidence.broker_order_id,
            order_ref=None,
            trade_id=None,
            evidence_type=evidence_type,
            requested_status=query_evidence.status,
            filled_quantity=query_evidence.filled_quantity,
            observed_at_ms=observed_at_ms,
            raw_payload_ref="simulated://active-order-query/" + client_order_id,
            raw_status=None,
        ))

    def ingest_qmt_command_result(
        self,
        *,
        qmt_session_id: str,
        qmt_sequence: int,
        account_fingerprint: str,
        payload: Mapping[str, Any],
        observed_at: datetime,
    ) -> CommandResultIngestResult:
        """Persist execution-plane evidence and begin conservative reconciliation.

        This entry point deliberately cannot accept a requested broker status.
        Consequently SHADOW_ACCEPTED has no path to ACKNOWLEDGED.
        """
        return self._command_result_journal.ingest(
            qmt_session_id=qmt_session_id,
            qmt_sequence=qmt_sequence,
            account_fingerprint=account_fingerprint,
            payload=payload,
            observed_at=observed_at,
        )

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
                self._ingest_active_query_evidence(
                    account, client_order_id, evidence, reason="startup-recovery"
                )
                if cancel_unresolved:
                    self.repository.transition_order(
                        account,
                        client_order_id,
                        self.repository.get_status(account, client_order_id),
                        event_type="RECONCILE_CANCEL_AMBIGUITY_RESOLVED",
                        cancel_outcome_resolved=True,
                    )

        self.heartbeat()
        self.repository.mark_session_reconciled(self.session_id)
        self.assert_leader()
        self._reconciled = True

    def submit_intent(
        self,
        intent: OrderIntent,
        decision: RiskDecision | None = None,
    ) -> SubmitResult:
        """Minimal Core submit path.

        With no external authorization, Core records a deterministic
        execution-only authorization and proceeds. Production Runtime performs
        policy evaluation above this layer and calls submit_authorized_intent.
        """
        authorization = decision or core_execution_decision(intent, now=self._now())
        return self.submit_authorized_intent(intent, authorization)

    def submit_authorized_intent(
        self,
        intent: OrderIntent,
        decision: RiskDecision,
        *,
        risk_evaluation: object | None = None,
    ) -> SubmitResult:
        """Execute one already-authorized intent without owning policy logic."""
        if not isinstance(decision, RiskDecision):
            raise TypeError("decision must be RiskDecision")
        return self._submit_decided_intent(
            intent,
            decision,
            risk_evaluation=risk_evaluation,
        )

    def _submit_decided_intent(
        self,
        intent: OrderIntent,
        decision: RiskDecision,
        *,
        risk_evaluation: object | None = None,
    ) -> SubmitResult:
        """Durable execution hook after authorization is established."""
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
            self.driver.submit_limit_order(intent)
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
            OrderStatus.UNKNOWN,
            event_type="SUBMIT_API_RETURNED_LIFECYCLE_UNKNOWN",
            evidence={"transport_returned": True},
        )
        self.repository.transition_order(
            intent.account_fingerprint,
            intent.client_order_id,
            OrderStatus.RECONCILING,
            event_type="SUBMIT_ACTIVE_QUERY_BEGIN",
        )
        self.assert_leader()
        query_evidence = self.driver.query_by_client_order_id(
            intent.account_fingerprint, intent.client_order_id
        )
        self.assert_leader()
        if query_evidence is None:
            return SubmitResult(status=OrderStatus.RECONCILING, risk_evaluation=risk_evaluation)
        applied = self._ingest_active_query_evidence(
            intent.account_fingerprint,
            intent.client_order_id,
            query_evidence,
            reason="post-submit",
        )
        return SubmitResult(
            status=applied.status,
            broker_order_id=query_evidence.broker_order_id,
            risk_evaluation=risk_evaluation,
        )

    def cancel_order(self, account_fingerprint: str, client_order_id: str) -> CancelResult:
        self.assert_leader()
        if not self._reconciled:
            raise OmsNotReconciled("startup reconciliation must complete before cancellation")

        self.repository.prepare_cancel(account_fingerprint, client_order_id)
        self.assert_leader()
        try:
            self.driver.cancel_order(account_fingerprint, client_order_id)
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
            OrderStatus.UNKNOWN,
            event_type="CANCEL_API_RETURNED_LIFECYCLE_UNKNOWN",
            evidence={"transport_returned": True},
        )
        self.repository.transition_order(
            account_fingerprint,
            client_order_id,
            OrderStatus.RECONCILING,
            event_type="CANCEL_ACTIVE_QUERY_BEGIN",
        )
        self.assert_leader()
        query_evidence = self.driver.query_by_client_order_id(account_fingerprint, client_order_id)
        self.assert_leader()
        if query_evidence is None:
            return CancelResult(status=OrderStatus.RECONCILING)
        applied = self._ingest_active_query_evidence(
            account_fingerprint,
            client_order_id,
            query_evidence,
            reason="post-cancel",
        )
        self.repository.transition_order(
            account_fingerprint,
            client_order_id,
            applied.status,
            event_type="CANCEL_ACTIVE_QUERY_RESOLVED",
            cancel_outcome_resolved=True,
        )
        return CancelResult(status=applied.status, broker_order_id=query_evidence.broker_order_id)

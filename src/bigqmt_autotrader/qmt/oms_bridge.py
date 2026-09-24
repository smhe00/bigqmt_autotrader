from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from bigqmt_autotrader.domain import OrderStatus, TransitionDisposition

from bigqmt_autotrader.oms.service import OfflineOms
from .command_results import CommandResultConflict, QmtCommandResultJournal


class QmtCommandResultInvariantViolation(RuntimeError):
    """A QMT transport result violates the current P4 shadow safety contract."""


@dataclass(frozen=True)
class QmtCommandResultIngestResult:
    status: OrderStatus
    disposition: TransitionDisposition
    command_id: str
    result_status: str


_ALLOWED_COMMAND_TYPES = frozenset({"SUBMIT_LIMIT", "CANCEL_ORDER"})
_ALLOWED_SHADOW_RESULTS = frozenset(
    {
        "SHADOW_ACCEPTED",
        "REJECTED_EXPIRED",
        "UNKNOWN_ORPHANED",
    }
)
_ALLOWED_LIVE_CANARY_RESULTS = frozenset(
    {
        "LIVE_CANARY_SUBMIT_CALL_RETURNED",
        "LIVE_CANARY_CANCEL_SIGNAL_SENT",
        "LIVE_CANARY_CANCEL_NOT_CANCELLABLE",
        "LIVE_CANARY_CANCEL_NOT_SENT",
        "LIVE_CANARY_MUTATION_UNKNOWN",
        "LIVE_CANARY_ORPHANED_UNKNOWN",
        "REJECTED_SAFETY_GATE",
        "REJECTED_EXPIRED",
    }
)
_LIVE_SIDE_EFFECT_RESULTS = frozenset(
    {
        "LIVE_CANARY_SUBMIT_CALL_RETURNED",
        "LIVE_CANARY_CANCEL_SIGNAL_SENT",
        "LIVE_CANARY_CANCEL_NOT_SENT",
        "LIVE_CANARY_MUTATION_UNKNOWN",
        "LIVE_CANARY_ORPHANED_UNKNOWN",
    }
)


class OmsQmtCommandResultSink:
    """Record QMT execution-transport results without fabricating broker facts.

    `SHADOW_ACCEPTED` proves only that the QMT bridge claimed and parsed a
    durable command. It is *not* broker acknowledgement. The sink therefore
    never promotes an order to ACKNOWLEDGED/CANCELLED/FILLED. If a result races
    the synchronous driver exception while the durable aggregate is still in
    SUBMITTING/CANCEL_PENDING, it may only converge that ambiguous side-effect
    boundary to UNKNOWN. A later SHADOW_ACCEPTED may only begin RECONCILING.
    Actual lifecycle progress remains exclusively owned by calibrated
    ORDER/DEAL/query broker evidence.
    """

    def __init__(self, oms: OfflineOms) -> None:
        self.oms = oms
        self._journal = QmtCommandResultJournal(
            oms.repository,
            write_guard=oms.assert_leader,
        )

    def ingest_execution_command_result(
        self,
        *,
        source_event_id: str,
        account_fingerprint: str,
        command_id: str,
        command_type: str,
        client_order_id: str,
        broker_token: str | None,
        result_status: str,
        execution_mode: str,
        live_side_effect: bool,
        payload: Mapping[str, Any] | None = None,
        observed_at: datetime | None = None,
    ) -> QmtCommandResultIngestResult:
        self.oms.assert_leader()

        if execution_mode == "SHADOW":
            allowed_results = _ALLOWED_SHADOW_RESULTS
            expected_side_effect = False
        elif execution_mode == "LIVE_CANARY":
            allowed_results = _ALLOWED_LIVE_CANARY_RESULTS
            expected_side_effect = result_status in _LIVE_SIDE_EFFECT_RESULTS
        else:
            raise QmtCommandResultInvariantViolation("unsupported execution mode")
        if live_side_effect is not expected_side_effect:
            raise QmtCommandResultInvariantViolation(
                "command_result live side-effect flag is inconsistent"
            )
        if command_type not in _ALLOWED_COMMAND_TYPES:
            raise QmtCommandResultInvariantViolation(
                "order command-result sink received unsupported command type"
            )
        if result_status not in allowed_results:
            raise QmtCommandResultInvariantViolation(
                "unsupported command result status"
            )
        if not command_id or not source_event_id or not client_order_id:
            raise QmtCommandResultInvariantViolation("command identity is incomplete")
        if not isinstance(broker_token, str) or not broker_token.startswith("BQ") or len(broker_token) >= 24:
            raise QmtCommandResultInvariantViolation("invalid broker token")

        session_id, separator, sequence_text = source_event_id.rpartition(":")
        try:
            sequence = int(sequence_text)
        except ValueError as exc:
            raise QmtCommandResultInvariantViolation(
                "source_event_id must end with a positive QMT sequence"
            ) from exc
        if not separator or not session_id or sequence <= 0:
            raise QmtCommandResultInvariantViolation(
                "source_event_id must contain QMT session and sequence"
            )

        normalized_payload = dict(payload or {})
        normalized_payload.update(
            {
                "command_id": command_id,
                "command_type": command_type,
                "client_order_id": client_order_id,
                "broker_token": broker_token,
                "result_status": result_status,
                "execution_mode": execution_mode,
                "live_side_effect": live_side_effect,
            }
        )
        try:
            journal_result = self._journal.ingest(
                qmt_session_id=session_id,
                qmt_sequence=sequence,
                account_fingerprint=account_fingerprint,
                payload=normalized_payload,
                observed_at=observed_at or datetime.now(timezone.utc),
            )
        except (ValueError, CommandResultConflict) as exc:
            raise QmtCommandResultInvariantViolation(str(exc)) from exc

        if journal_result.order_status is None:
            raise QmtCommandResultInvariantViolation(
                "order command result did not produce an OMS reconciliation record"
            )
        disposition = (
            journal_result.disposition
            if journal_result.disposition is not None
            else TransitionDisposition.DUPLICATE_IGNORED
        )
        return QmtCommandResultIngestResult(
            status=journal_result.order_status,
            disposition=disposition,
            command_id=command_id,
            result_status=result_status,
        )

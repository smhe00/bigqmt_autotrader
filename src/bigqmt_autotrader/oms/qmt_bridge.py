from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

from bigqmt_autotrader.domain import OrderStatus, TransitionDisposition

from .service import OfflineOms


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


class OmsQmtCommandResultSink:
    """Record QMT execution-transport results without fabricating broker facts.

    `SHADOW_ACCEPTED` proves only that the QMT bridge claimed and parsed a
    durable command. It is *not* broker acknowledgement. The sink therefore
    never promotes an order to ACKNOWLEDGED/CANCELLED/FILLED. If a result races
    the synchronous driver exception while the durable aggregate is still in
    SUBMITTING/CANCEL_PENDING, it may only converge that ambiguous side-effect
    boundary to UNKNOWN. Actual lifecycle progress remains exclusively owned by
    calibrated ORDER/DEAL/query broker evidence.
    """

    def __init__(self, oms: OfflineOms) -> None:
        self.oms = oms

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

        if execution_mode != "SHADOW":
            raise QmtCommandResultInvariantViolation(
                "P4 command-result sink accepts SHADOW execution only"
            )
        if live_side_effect is not False:
            raise QmtCommandResultInvariantViolation(
                "P4 shadow command_result cannot claim a live broker side effect"
            )
        if command_type not in _ALLOWED_COMMAND_TYPES:
            raise QmtCommandResultInvariantViolation(
                "order command-result sink received unsupported command type"
            )
        if result_status not in _ALLOWED_SHADOW_RESULTS:
            raise QmtCommandResultInvariantViolation(
                "unsupported P4 shadow command result status"
            )
        if not command_id or not source_event_id or not client_order_id:
            raise QmtCommandResultInvariantViolation("command identity is incomplete")
        if not isinstance(broker_token, str) or not broker_token.startswith("BQ") or len(broker_token) >= 24:
            raise QmtCommandResultInvariantViolation("invalid broker token")

        current = self.oms.repository.get_status(account_fingerprint, client_order_id)

        if command_type == "SUBMIT_LIMIT" and current in {
            OrderStatus.CREATED,
            OrderStatus.RISK_ACCEPTED,
        }:
            raise QmtCommandResultInvariantViolation(
                "submit command_result observed before durable submit reservation"
            )
        if command_type == "CANCEL_ORDER" and current in {
            OrderStatus.CREATED,
            OrderStatus.RISK_ACCEPTED,
            OrderStatus.SUBMITTING,
        }:
            raise QmtCommandResultInvariantViolation(
                "cancel command_result observed before durable cancel eligibility"
            )

        target = current
        if command_type == "SUBMIT_LIMIT" and current is OrderStatus.SUBMITTING:
            target = OrderStatus.UNKNOWN
        elif command_type == "CANCEL_ORDER" and current is OrderStatus.CANCEL_PENDING:
            target = OrderStatus.UNKNOWN

        event_evidence: dict[str, Any] = {
            "source": "qmt_command_result",
            "source_event_id": source_event_id,
            "command_id": command_id,
            "command_type": command_type,
            "broker_token": broker_token,
            "result_status": result_status,
            "execution_mode": execution_mode,
            "live_side_effect": False,
            "broker_evidence": False,
        }
        if observed_at is not None:
            event_evidence["observed_at"] = observed_at.isoformat()
        if payload:
            event_evidence["payload"] = dict(payload)

        outcome = self.oms.repository.transition_order(
            account_fingerprint,
            client_order_id,
            target,
            event_type="QMT_COMMAND_RESULT_" + result_status,
            evidence=event_evidence,
        )
        return QmtCommandResultIngestResult(
            status=outcome.current,
            disposition=outcome.disposition,
            command_id=command_id,
            result_status=result_status,
        )

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from bigqmt_autotrader.domain import OrderStatus, TransitionDisposition
from bigqmt_autotrader.qmt.commands import broker_token_for

from .db import transaction
from .repository import OmsRepository


class CommandResultConflict(RuntimeError):
    pass


@dataclass(frozen=True)
class CommandResultIngestResult:
    duplicate: bool
    order_status: OrderStatus | None
    disposition: TransitionDisposition | None


_COMMAND_TYPES = {"SUBMIT_LIMIT", "CANCEL_ORDER", "REQUEST_SNAPSHOT"}
_RESULT_STATUSES = {
    "SHADOW_ACCEPTED",
    "SNAPSHOT_EMITTED",
    "REJECTED_EXPIRED",
    "UNKNOWN_ORPHANED",
    "LIVE_CANARY_SUBMIT_CALL_RETURNED",
    "LIVE_CANARY_CANCEL_SIGNAL_SENT",
    "LIVE_CANARY_CANCEL_NOT_CANCELLABLE",
    "LIVE_CANARY_CANCEL_NOT_SENT",
    "LIVE_CANARY_MUTATION_UNKNOWN",
    "LIVE_CANARY_ORPHANED_UNKNOWN",
    "REJECTED_SAFETY_GATE",
    "SIMULATION_SUBMIT_CALL_RETURNED",
    "SIMULATION_CANCEL_SIGNAL_SENT",
    "SIMULATION_CANCEL_NOT_CANCELLABLE",
    "SIMULATION_CANCEL_NOT_SENT",
    "SIMULATION_MUTATION_UNKNOWN",
    "SIMULATION_ORPHANED_UNKNOWN",
}

_LIVE_SIDE_EFFECT_STATUSES = {
    "LIVE_CANARY_SUBMIT_CALL_RETURNED",
    "LIVE_CANARY_CANCEL_SIGNAL_SENT",
    "LIVE_CANARY_CANCEL_NOT_SENT",
    "LIVE_CANARY_MUTATION_UNKNOWN",
    "LIVE_CANARY_ORPHANED_UNKNOWN",
}

_SIMULATION_SIDE_EFFECT_STATUSES = {
    "SIMULATION_SUBMIT_CALL_RETURNED",
    "SIMULATION_CANCEL_SIGNAL_SENT",
    "SIMULATION_CANCEL_NOT_SENT",
    "SIMULATION_MUTATION_UNKNOWN",
    "SIMULATION_ORPHANED_UNKNOWN",
}


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class QmtCommandResultJournal:
    """Durably joins QMT execution-plane results to OMS reconciliation.

    This journal is intentionally separate from broker evidence. In P4 every
    accepted result must be SHADOW with ``live_side_effect=False``. A
    SHADOW_ACCEPTED order command can begin reconciliation of an UNKNOWN order,
    but cannot create broker identity or ACKNOWLEDGED/CANCELLED state.
    """

    def __init__(self, repository: OmsRepository, *, write_guard: Callable[[], None]) -> None:
        self.repository = repository
        self.conn = repository.conn
        self._write_guard = write_guard

    def ingest(
        self,
        *,
        qmt_session_id: str,
        qmt_sequence: int,
        account_fingerprint: str,
        payload: Mapping[str, Any],
        observed_at: datetime,
    ) -> CommandResultIngestResult:
        command_id = payload.get("command_id")
        command_type = payload.get("command_type")
        client_order_id = payload.get("client_order_id")
        broker_token = payload.get("broker_token")
        result_status = payload.get("result_status")
        execution_mode = payload.get("execution_mode")
        live_side_effect = payload.get("live_side_effect")

        if command_type not in _COMMAND_TYPES or result_status not in _RESULT_STATUSES:
            raise ValueError("unsupported QMT command result")
        if execution_mode == "SHADOW":
            if live_side_effect is not False:
                raise ValueError("SHADOW command result cannot claim a live side effect")
        elif execution_mode == "LIVE_CANARY":
            if live_side_effect is not (result_status in _LIVE_SIDE_EFFECT_STATUSES):
                raise ValueError("LIVE_CANARY side-effect flag is inconsistent")
        elif execution_mode == "SIMULATION_CALIBRATION":
            if live_side_effect is not (result_status in _SIMULATION_SIDE_EFFECT_STATUSES):
                raise ValueError("SIMULATION_CALIBRATION side-effect flag is inconsistent")
        else:
            raise ValueError("unsupported command result execution mode")
        if not isinstance(command_id, str) or not command_id:
            raise ValueError("command_id must be non-empty")
        if not isinstance(qmt_session_id, str) or not qmt_session_id:
            raise ValueError("qmt_session_id must be non-empty")
        if isinstance(qmt_sequence, bool) or not isinstance(qmt_sequence, int) or qmt_sequence <= 0:
            raise ValueError("qmt_sequence must be positive")
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")

        if command_type == "REQUEST_SNAPSHOT":
            if client_order_id is not None or broker_token is not None:
                raise ValueError("snapshot result cannot carry order identity")
        else:
            if not isinstance(client_order_id, str) or not client_order_id:
                raise ValueError("order command result requires client_order_id")
            expected = broker_token_for(account_fingerprint, client_order_id)
            if broker_token != expected:
                raise ValueError("command result broker_token does not match durable order identity")

        logical = {
            "qmt_session_id": qmt_session_id,
            "qmt_sequence": qmt_sequence,
            "account_fingerprint": account_fingerprint,
            "payload": dict(payload),
        }
        payload_json = _canonical_json(dict(payload))
        fingerprint = hashlib.sha256(_canonical_json(logical).encode("utf-8")).hexdigest()
        observed_iso = observed_at.astimezone(timezone.utc).isoformat()

        with transaction(self.conn):
            self._write_guard()
            existing = self.conn.execute(
                "SELECT fingerprint FROM qmt_command_results WHERE command_id=?",
                (command_id,),
            ).fetchone()
            if existing is not None:
                if existing["fingerprint"] != fingerprint:
                    raise CommandResultConflict("command_id reused with different QMT result")
                status = None
                if client_order_id is not None:
                    status = self.repository._get_status_in_tx(
                        account_fingerprint, client_order_id
                    )
                return CommandResultIngestResult(True, status, None)

            sequence_row = self.conn.execute(
                "SELECT command_id, fingerprint FROM qmt_command_results "
                "WHERE qmt_session_id=? AND qmt_sequence=?",
                (qmt_session_id, qmt_sequence),
            ).fetchone()
            if sequence_row is not None:
                raise CommandResultConflict("QMT session sequence reused by another command result")

            self.conn.execute(
                """
                INSERT INTO qmt_command_results(
                    command_id, fingerprint, qmt_session_id, qmt_sequence,
                    account_fingerprint, client_order_id, command_type,
                    broker_token, result_status, execution_mode, live_side_effect,
                    payload_json, observed_at, ingested_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    command_id,
                    fingerprint,
                    qmt_session_id,
                    qmt_sequence,
                    account_fingerprint,
                    client_order_id,
                    command_type,
                    broker_token,
                    result_status,
                    execution_mode,
                    int(live_side_effect),
                    payload_json,
                    observed_iso,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )

            if client_order_id is None:
                return CommandResultIngestResult(False, None, None)

            begin_reconciling = result_status == "SHADOW_ACCEPTED" or execution_mode == "SIMULATION_CALIBRATION" or (
                execution_mode == "LIVE_CANARY"
                and result_status not in {"REJECTED_SAFETY_GATE", "REJECTED_EXPIRED"}
            )
            outcome = self.repository.record_command_reconciliation_in_tx(
                account_fingerprint,
                client_order_id,
                event_type="QMT_COMMAND_RESULT_" + result_status,
                evidence={
                    "command_id": command_id,
                    "command_type": command_type,
                    "qmt_session_id": qmt_session_id,
                    "qmt_sequence": qmt_sequence,
                    "broker_token": broker_token,
                    "execution_mode": execution_mode,
                    "live_side_effect": live_side_effect,
                    "broker_evidence": False,
                    "evidence_class": "EXECUTION_PLANE_NOT_BROKER_ACK",
                },
                begin_reconciling=begin_reconciling,
            )
            if (
                outcome.previous is not OrderStatus.ACKNOWLEDGED
                and outcome.current is OrderStatus.ACKNOWLEDGED
            ):
                raise AssertionError("command_result must never promote OMS to ACKNOWLEDGED")
            return CommandResultIngestResult(False, outcome.current, outcome.disposition)

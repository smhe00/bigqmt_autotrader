from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from bigqmt_autotrader.domain import OrderIntent, OrderStatus, TransitionDisposition
from bigqmt_autotrader.oms.command_results import QmtCommandResultJournal
from bigqmt_autotrader.oms.db import transaction
from bigqmt_autotrader.oms.db import connect_database, initialize_database
from bigqmt_autotrader.oms.evidence import EvidenceJournal
from bigqmt_autotrader.oms.leader import LeaderCoordinator
from bigqmt_autotrader.oms.repository import OmsRepository, QmtDurableIdentityConflict
from bigqmt_autotrader.risk import RiskEvaluation, RiskPolicy, RiskSnapshot, evaluate_risk

from .commands import (
    QmtCommand,
    QmtCommandSpool,
    QmtCommandType,
    broker_token_for,
    decode_command_frame,
    encode_command_frame,
)
from .guojin_evidence import GuojinSimEvidenceMapper
from .instances import QmtInstance


AUTHORIZED_GUOJIN_SIM_FINGERPRINT = (
    "sha256:ff266d673e28fbba5da4bfe2c68975f75b6a9fb5b89014503409b2b014ce0702"
)
AUTHORIZED_GUOJIN_SIM_BUILD = "p5-simulation-calibration-8"


@dataclass(frozen=True)
class GuojinSimExecutionResult:
    """Result of Host-owned simulation dispatch, never broker lifecycle proof."""

    status: OrderStatus
    command_id: str | None
    dispatched: bool
    risk_evaluation: RiskEvaluation | None = None
    terminal_noop: bool = False


def _deterministic_command_id(*parts: str) -> str:
    digest = hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()
    return "simoms-" + digest[:48]


class GuojinSimOmsRuntime:
    """The single Host-owned OMS writer for the explicitly pinned simulator.

    The runtime persists an immutable QMT command frame *before* it is placed
    in the spool.  Filesystem publication is then recoverable by deterministic
    command identity.  It deliberately treats all command results as control
    plane evidence; calibrated ORDER/DEAL/query evidence remains lifecycle
    authority.
    """

    def __init__(self, instance: QmtInstance) -> None:
        if not guojin_sim_oms_authorized(instance, allow_simulation_mutation=True):
            raise ValueError("guojin_sim OMS runtime authorization failed")
        self.instance = instance
        self.database_path = instance.root / "host_oms.sqlite3"
        self.conn = connect_database(self.database_path)
        initialize_database(self.conn)
        self.repository = OmsRepository(self.conn)
        self._leader = LeaderCoordinator(self.conn)
        self._lease_seconds = 30
        self._lease = self._leader.acquire(
            "qmt-host:" + instance.session_id,
            lease_seconds=self._lease_seconds,
        )
        self._closed = False
        self._last_heartbeat = time.monotonic()
        self.repository.bind_write_guard(self.assert_leader)
        self.evidence_journal = EvidenceJournal(
            self.repository, write_guard=self.assert_leader
        )
        self.command_result_journal = QmtCommandResultJournal(
            self.repository, write_guard=self.assert_leader
        )
        self.command_spool = QmtCommandSpool(instance.root)
        self.mapper = GuojinSimEvidenceMapper(
            account_fingerprint=instance.account_fingerprint
        )
        try:
            self.restore_persisted_identities()
            self.refresh_identities()
            self._restore_dispatch_plan_identities()
            self._validate_dispatch_invariants()
            self.recover_dispatches()
        except BaseException:
            self.close()
            raise

    def assert_leader(self) -> None:
        if self._closed:
            raise RuntimeError("guojin_sim OMS runtime is closed")
        self._leader.assert_held(self._lease)

    def maintain(self) -> None:
        if time.monotonic() - self._last_heartbeat >= 10.0:
            self._lease = self._leader.heartbeat(
                self._lease, lease_seconds=self._lease_seconds
            )
            self._last_heartbeat = time.monotonic()

    def restore_persisted_identities(self) -> int:
        """Re-register trusted OMS identities across QMT session rollover."""
        rows = self.conn.execute(
            """
            SELECT account_fingerprint, client_order_id, broker_token, symbol, quantity
            FROM qmt_durable_command_identities ORDER BY command_id
            """
        ).fetchall()
        for row in rows:
            if row["account_fingerprint"] != self.instance.account_fingerprint:
                raise QmtDurableIdentityConflict("OMS database account fingerprint changed")
            token = self.mapper.register_order(
                client_order_id=row["client_order_id"],
                symbol=row["symbol"],
                quantity=int(row["quantity"]),
            )
            if token != row["broker_token"]:
                raise QmtDurableIdentityConflict("persisted OMS broker token mismatch")
        return len(rows)

    def refresh_identities(self) -> int:
        candidates = []
        raw_by_command = {}
        by_client = {}
        by_command = {}
        validator = GuojinSimEvidenceMapper(
            account_fingerprint=self.instance.account_fingerprint
        )
        for state in ("processed", "unknown"):
            directory = self.instance.root / "commands" / state
            if not directory.is_dir():
                continue
            for path in sorted(directory.glob("*.json")):
                raw = path.read_bytes()
                command = decode_command_frame(raw)
                if path.name != command.command_id + ".json":
                    raise ValueError("durable command filename/identity mismatch")
                if command.command_type is not QmtCommandType.SUBMIT_LIMIT:
                    continue
                payload = command.payload
                if (
                    command.account_fingerprint != self.instance.account_fingerprint
                    or payload.get("simulation_calibration") is not True
                    or payload.get("expected_qmt_session_id") != self.instance.session_id
                ):
                    continue
                quantity = payload.get("quantity")
                if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity > 100:
                    raise ValueError("durable simulation quantity exceeds Host boundary")
                assert command.client_order_id is not None
                assert command.broker_token is not None
                if command.broker_token != broker_token_for(
                    command.account_fingerprint, command.client_order_id
                ):
                    raise ValueError("durable command broker token mismatch")
                registered_token = validator.register_order(
                    client_order_id=command.client_order_id,
                    symbol=str(payload["symbol"]),
                    quantity=quantity,
                )
                if registered_token != command.broker_token:
                    raise ValueError("mapper token differs from durable command token")
                candidate = dict(
                    command_id=command.command_id,
                    account_fingerprint=command.account_fingerprint,
                    qmt_session_id=self.instance.session_id,
                    client_order_id=command.client_order_id,
                    broker_token=command.broker_token,
                    symbol=str(payload["symbol"]),
                    side=str(payload["side"]),
                    quantity=quantity,
                    limit_price=str(payload["limit_price"]),
                    command_state=state,
                    command_digest="sha256:" + hashlib.sha256(raw).hexdigest(),
                    created_ms=command.created_ms,
                    expires_ms=command.expires_ms,
                )
                previous = by_client.get(command.client_order_id)
                if previous is not None and previous != candidate:
                    raise QmtDurableIdentityConflict("conflicting durable client identity")
                previous = by_command.get(command.command_id)
                if previous is not None and previous != candidate:
                    raise QmtDurableIdentityConflict("conflicting durable command identity")
                by_client[command.client_order_id] = candidate
                by_command[command.command_id] = candidate
                raw_by_command[command.command_id] = raw
                candidates.append(candidate)

        # Detect every file/OMS conflict before importing even the first new
        # identity.  A bad durable record cannot leave a partially imported
        # batch, nor teach the live mapper a callback-derived identity.
        for candidate in candidates:
            row = self.conn.execute(
                """
                SELECT * FROM qmt_durable_command_identities
                WHERE command_id=? OR (account_fingerprint=? AND client_order_id=?)
                   OR (account_fingerprint=? AND broker_token=?)
                """,
                (
                    candidate["command_id"], candidate["account_fingerprint"],
                    candidate["client_order_id"], candidate["account_fingerprint"],
                    candidate["broker_token"],
                ),
            ).fetchone()
            if row is None:
                prior_intent = self.conn.execute(
                    """
                    SELECT 1 FROM order_intents
                    WHERE account_fingerprint=? AND client_order_id=?
                    """,
                    (candidate["account_fingerprint"], candidate["client_order_id"]),
                ).fetchone()
                if prior_intent is not None:
                    dispatch = self.conn.execute(
                        """SELECT * FROM qmt_execution_dispatches
                           WHERE command_id=? AND account_fingerprint=?
                             AND client_order_id=? AND command_type='SUBMIT_LIMIT'""",
                        (
                            candidate["command_id"],
                            candidate["account_fingerprint"],
                            candidate["client_order_id"],
                        ),
                    ).fetchone()
                    if (
                        dispatch is None
                        or dispatch["qmt_session_id"] != candidate["qmt_session_id"]
                        or dispatch["broker_token"] != candidate["broker_token"]
                        or dispatch["frame_digest"] != candidate["command_digest"]
                        or bytes(dispatch["frame_blob"]) != raw_by_command[candidate["command_id"]]
                    ):
                        raise QmtDurableIdentityConflict(
                            "OMS order exists without matching durable dispatch authority"
                        )
                continue
            fields = (
                "command_id", "account_fingerprint", "qmt_session_id",
                "client_order_id", "broker_token", "symbol", "side",
                "quantity", "limit_price", "command_digest", "created_ms",
                "expires_ms",
            )
            if any(row[field] != candidate[field] for field in fields):
                raise QmtDurableIdentityConflict("conflicting durable QMT command identity")
            if row["command_state"] != candidate["command_state"] and not (
                row["command_state"] == "unknown"
                and candidate["command_state"] == "processed"
            ):
                raise QmtDurableIdentityConflict("conflicting durable command state")

        imported = 0
        for candidate in candidates:
            existing_order = self.conn.execute(
                """SELECT 1 FROM order_intents
                   WHERE account_fingerprint=? AND client_order_id=?""",
                (candidate["account_fingerprint"], candidate["client_order_id"]),
            ).fetchone()
            imported += int(
                self.repository.register_qmt_durable_submit(
                    **candidate,
                    allow_existing_order_from_dispatch=existing_order is not None,
                )
            )
            self.mapper.register_order(
                client_order_id=candidate["client_order_id"],
                symbol=candidate["symbol"],
                quantity=candidate["quantity"],
            )
        return imported

    def _restore_dispatch_plan_identities(self) -> int:
        """Restore mapper identities from Host-owned immutable submit plans."""
        rows = self.conn.execute(
            """SELECT * FROM qmt_execution_dispatches
               WHERE account_fingerprint=? AND qmt_session_id=?
                 AND command_type='SUBMIT_LIMIT'
                 AND dispatch_state != 'MANUAL_REVIEW'
               ORDER BY created_ms, command_id""",
            (self.instance.account_fingerprint, self.instance.session_id),
        ).fetchall()
        restored = 0
        for row in rows:
            raw = bytes(row["frame_blob"])
            command = decode_command_frame(raw)
            if (
                row["frame_digest"] != self._digest(raw)
                or command.command_id != row["command_id"]
                or command.account_fingerprint != self.instance.account_fingerprint
                or command.client_order_id != row["client_order_id"]
                or command.broker_token != row["broker_token"]
                or command.payload.get("simulation_calibration") is not True
                or command.payload.get("expected_qmt_session_id") != self.instance.session_id
            ):
                raise QmtDurableIdentityConflict(
                    "immutable dispatch plan cannot restore trusted mapper identity"
                )
            token = self.mapper.register_order(
                client_order_id=command.client_order_id,
                symbol=str(command.payload["symbol"]),
                quantity=int(command.payload["quantity"]),
            )
            if token != command.broker_token:
                raise QmtDurableIdentityConflict(
                    "dispatch-plan mapper token differs from durable broker token"
                )
            restored += 1
        return restored

    def ingest_broker_evidence(self, evidence):
        return self.evidence_journal.ingest(evidence)

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
    ):
        """Persist simulation control-plane result without creating a broker fact."""
        session_id, separator, sequence_text = source_event_id.rpartition(":")
        if not separator or not session_id:
            raise ValueError("simulation command result source identity is invalid")
        try:
            sequence = int(sequence_text)
        except ValueError as exc:
            raise ValueError("simulation command result sequence is invalid") from exc
        if account_fingerprint != self.instance.account_fingerprint:
            raise ValueError("simulation command result account mismatch")
        if execution_mode != "SIMULATION_CALIBRATION":
            raise ValueError("simulation runtime refuses non-simulation command result")
        result = self.command_result_journal.ingest(
            qmt_session_id=session_id,
            qmt_sequence=sequence,
            account_fingerprint=account_fingerprint,
            payload=dict(payload or {}),
            observed_at=observed_at or datetime.now(timezone.utc),
        )
        self._observe_command_result_dispatch(command_id, result_status)
        return result

    def execute_intent(
        self,
        intent: OrderIntent,
        risk_snapshot: RiskSnapshot,
        risk_policy: RiskPolicy,
    ) -> GuojinSimExecutionResult:
        """Evaluate risk internally and dispatch one durable simulation submit."""
        self.assert_leader()
        self.maintain()
        if intent.account_fingerprint != self.instance.account_fingerprint:
            raise ValueError("intent account does not match the pinned simulator")
        evaluation = evaluate_risk(
            intent, risk_snapshot, risk_policy, now=datetime.now(timezone.utc)
        )
        existing = self._dispatch_for_order(intent.client_order_id, "SUBMIT_LIMIT")
        if existing is not None:
            command = self._build_submit_command(intent)
            if existing["frame_digest"] != self._digest(encode_command_frame(command)):
                raise QmtDurableIdentityConflict("same client order has a conflicting dispatch frame")
            self._recover_dispatch(existing)
            return GuojinSimExecutionResult(
                status=self.repository.get_status(intent.account_fingerprint, intent.client_order_id),
                command_id=existing["command_id"],
                dispatched=False,
                risk_evaluation=evaluation,
            )

        self.repository.create_intent(intent)
        status = self.repository.record_risk_decision(
            intent.account_fingerprint, intent.client_order_id, evaluation.decision
        )
        if not evaluation.decision.accepted:
            return GuojinSimExecutionResult(
                status=status, command_id=None, dispatched=False, risk_evaluation=evaluation
            )

        command = self._build_submit_command(intent)
        row = self._reserve_and_persist_dispatch(
            command, broker_order_id=None, cancel=False
        )
        # Mapper identity is learned only after the atomic reservation+plan
        # transaction commits; callbacks never manufacture this join key.
        self.mapper.register_order(
            client_order_id=intent.client_order_id,
            symbol=intent.symbol,
            quantity=intent.quantity,
        )
        self._recover_dispatch(row)
        return GuojinSimExecutionResult(
            status=self.repository.get_status(intent.account_fingerprint, intent.client_order_id),
            command_id=command.command_id,
            dispatched=True,
            risk_evaluation=evaluation,
        )

    def cancel_intent(self, client_order_id: str) -> GuojinSimExecutionResult:
        """Publish at most one exact-token cancellation for a trusted order."""
        self.assert_leader()
        self.maintain()
        order = self.repository.get_order_row(
            self.instance.account_fingerprint, client_order_id
        )
        status = OrderStatus(order["status"])
        if status in {OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED,
                      OrderStatus.ABORTED, OrderStatus.MANUAL_REVIEW}:
            return GuojinSimExecutionResult(
                status=status, command_id=None, dispatched=False, terminal_noop=True
            )
        existing = self._dispatch_for_order(client_order_id, "CANCEL_ORDER")
        if existing is not None:
            self._recover_dispatch(existing)
            return GuojinSimExecutionResult(
                status=self.repository.get_status(self.instance.account_fingerprint, client_order_id),
                command_id=existing["command_id"], dispatched=False
            )
        if status not in {OrderStatus.ACKNOWLEDGED, OrderStatus.PARTIALLY_FILLED}:
            raise RuntimeError("cancel is blocked until trusted broker evidence makes it cancellable")
        broker_order_id = order["broker_order_id"]
        if not isinstance(broker_order_id, str) or not broker_order_id:
            raise RuntimeError("cancel requires trusted persistent broker_order_id")
        command = self._build_cancel_command(client_order_id, broker_order_id)
        row = self._reserve_and_persist_dispatch(
            command, broker_order_id=broker_order_id, cancel=True
        )
        self._recover_dispatch(row)
        return GuojinSimExecutionResult(
            status=self.repository.get_status(self.instance.account_fingerprint, client_order_id),
            command_id=command.command_id, dispatched=True
        )

    def _validate_dispatch_invariants(self) -> None:
        """Fail closed on durable side-effect reservations with no matching plan."""
        self.assert_leader()
        rows = self.conn.execute(
            """SELECT client_order_id, status, submit_call_started,
                      cancel_call_started, cancel_outcome_resolved
               FROM broker_orders
               WHERE account_fingerprint=?""",
            (self.instance.account_fingerprint,),
        ).fetchall()
        for row in rows:
            client_order_id = row["client_order_id"]
            status = OrderStatus(row["status"])
            if status is OrderStatus.SUBMITTING and bool(row["submit_call_started"]):
                dispatch = self._dispatch_for_order(client_order_id, "SUBMIT_LIMIT")
                if dispatch is None or dispatch["qmt_session_id"] != self.instance.session_id:
                    self._mark_invariant_manual_review(
                        client_order_id,
                        event_type="QMT_SUBMIT_RESERVATION_WITHOUT_DISPATCH",
                        reason="submit reservation has no current-session immutable dispatch plan",
                    )
                    continue
            if (
                bool(row["cancel_call_started"])
                and not bool(row["cancel_outcome_resolved"])
                and status in {
                    OrderStatus.ACKNOWLEDGED,
                    OrderStatus.PARTIALLY_FILLED,
                    OrderStatus.CANCEL_PENDING,
                }
            ):
                dispatch = self._dispatch_for_order(client_order_id, "CANCEL_ORDER")
                if dispatch is None or dispatch["qmt_session_id"] != self.instance.session_id:
                    self._mark_invariant_manual_review(
                        client_order_id,
                        event_type="QMT_CANCEL_RESERVATION_WITHOUT_DISPATCH",
                        reason="cancel reservation has no current-session immutable dispatch plan",
                        cancel_outcome_resolved=True,
                    )

    def _mark_invariant_manual_review(
        self,
        client_order_id: str,
        *,
        event_type: str,
        reason: str,
        command_id: str | None = None,
        cancel_outcome_resolved: bool | None = None,
    ) -> None:
        with transaction(self.conn):
            self.repository.mark_manual_review_in_tx(
                self.instance.account_fingerprint,
                client_order_id,
                event_type=event_type,
                reason=reason,
                evidence={"command_id": command_id} if command_id is not None else {},
                cancel_outcome_resolved=cancel_outcome_resolved,
            )

    def _fail_dispatch_manual_review(
        self,
        row,
        command: QmtCommand,
        *,
        event_type: str,
        reason: str,
    ) -> None:
        with transaction(self.conn):
            self.repository._guard_write_in_tx()
            self.conn.execute(
                """UPDATE qmt_execution_dispatches
                   SET dispatch_state='MANUAL_REVIEW'
                   WHERE command_id=?""",
                (command.command_id,),
            )
            self.repository.mark_manual_review_in_tx(
                command.account_fingerprint,
                command.client_order_id,
                event_type=event_type,
                reason=reason,
                evidence={"command_id": command.command_id, "dispatch_state": row["dispatch_state"]},
                cancel_outcome_resolved=(
                    True if command.command_type is QmtCommandType.CANCEL_ORDER else None
                ),
            )

    def recover_dispatches(self) -> int:
        """Complete only provably pre-publication plans; never blind-retry."""
        self.assert_leader()
        rows = self.conn.execute(
            """SELECT * FROM qmt_execution_dispatches
               WHERE qmt_session_id=? AND dispatch_state != 'MANUAL_REVIEW'
               ORDER BY created_ms, command_id""",
            (self.instance.session_id,),
        ).fetchall()
        for row in rows:
            self._recover_dispatch(row)
        return len(rows)

    def _build_submit_command(self, intent: OrderIntent) -> QmtCommand:
        created_ms = int(intent.created_at.timestamp() * 1000)
        expires_ms = int(intent.expires_at.timestamp() * 1000)
        return QmtCommand(
            command_id=_deterministic_command_id(
                "submit", self.instance.account_fingerprint, self.instance.session_id,
                intent.client_order_id,
            ),
            created_ms=created_ms,
            expires_ms=expires_ms,
            account_fingerprint=self.instance.account_fingerprint,
            command_type=QmtCommandType.SUBMIT_LIMIT,
            client_order_id=intent.client_order_id,
            broker_token=broker_token_for(self.instance.account_fingerprint, intent.client_order_id),
            payload={
                "symbol": intent.symbol,
                "side": intent.side.value,
                "quantity": intent.quantity,
                "limit_price": str(intent.limit_price),
                "simulation_calibration": True,
                "expected_qmt_session_id": self.instance.session_id,
            },
        )

    def _build_cancel_command(self, client_order_id: str, broker_order_id: str) -> QmtCommand:
        now_ms = int(time.time() * 1000)
        return QmtCommand(
            command_id=_deterministic_command_id(
                "cancel", self.instance.account_fingerprint, self.instance.session_id,
                client_order_id, broker_order_id,
            ),
            created_ms=now_ms,
            expires_ms=now_ms + 30_000,
            account_fingerprint=self.instance.account_fingerprint,
            command_type=QmtCommandType.CANCEL_ORDER,
            client_order_id=client_order_id,
            broker_token=broker_token_for(self.instance.account_fingerprint, client_order_id),
            payload={
                "broker_order_id": broker_order_id,
                "simulation_calibration": True,
                "expected_qmt_session_id": self.instance.session_id,
            },
        )

    @staticmethod
    def _digest(raw: bytes) -> str:
        return "sha256:" + hashlib.sha256(raw).hexdigest()

    def _dispatch_for_order(self, client_order_id: str, command_type: str):
        return self.conn.execute(
            """SELECT * FROM qmt_execution_dispatches
               WHERE account_fingerprint=? AND client_order_id=? AND command_type=?""",
            (self.instance.account_fingerprint, client_order_id, command_type),
        ).fetchone()

    def _persist_dispatch_in_tx(
        self,
        command: QmtCommand,
        *,
        broker_order_id: str | None,
        raw: bytes | None = None,
        digest: str | None = None,
    ):
        if not self.conn.in_transaction:
            raise RuntimeError("_persist_dispatch_in_tx requires an active transaction")
        self.repository._guard_write_in_tx()
        raw = encode_command_frame(command) if raw is None else raw
        digest = self._digest(raw) if digest is None else digest
        existing = self.conn.execute(
            "SELECT * FROM qmt_execution_dispatches WHERE command_id=?",
            (command.command_id,),
        ).fetchone()
        if existing is not None:
            if existing["frame_digest"] != digest or bytes(existing["frame_blob"]) != raw:
                raise QmtDurableIdentityConflict("command identity has a conflicting frame")
            return existing
        self.conn.execute(
            """INSERT INTO qmt_execution_dispatches(
                   command_id, account_fingerprint, client_order_id, command_type,
                   qmt_session_id, broker_token, broker_order_id, frame_digest, frame_blob,
                   dispatch_state, created_ms, expires_ms, published_at
               ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, 'PLANNED', ?, ?, NULL)""",
            (
                command.command_id, command.account_fingerprint, command.client_order_id,
                command.command_type.value, self.instance.session_id, command.broker_token,
                broker_order_id, digest, raw, command.created_ms, command.expires_ms,
            ),
        )
        self.repository._insert_event(
            command.account_fingerprint, command.client_order_id,
            event_type="QMT_DISPATCH_PLAN_COMMITTED", from_status=None,
            to_status=self.repository._get_status_in_tx(
                command.account_fingerprint, command.client_order_id
            ),
            disposition=TransitionDisposition.APPLIED,
            evidence={"command_id": command.command_id, "frame_digest": digest,
                      "command_type": command.command_type.value},
        )
        return self.conn.execute(
            "SELECT * FROM qmt_execution_dispatches WHERE command_id=?",
            (command.command_id,),
        ).fetchone()

    def _reserve_and_persist_dispatch(
        self,
        command: QmtCommand,
        *,
        broker_order_id: str | None,
        cancel: bool,
    ):
        raw = encode_command_frame(command)
        digest = self._digest(raw)
        with transaction(self.conn):
            self.repository._guard_write_in_tx()
            if cancel:
                self.repository.prepare_cancel_in_tx(
                    command.account_fingerprint, command.client_order_id
                )
            else:
                self.repository.prepare_submit_in_tx(
                    command.account_fingerprint, command.client_order_id
                )
            row = self._persist_dispatch_in_tx(
                command,
                broker_order_id=broker_order_id,
                raw=raw,
                digest=digest,
            )
        return row

    def _set_dispatch_state(self, command_id: str, state: str) -> None:
        with transaction(self.conn):
            self.repository._guard_write_in_tx()
            self.conn.execute(
                """UPDATE qmt_execution_dispatches
                   SET dispatch_state=?, published_at=CASE WHEN ?='PUBLISHED' THEN ? ELSE published_at END
                   WHERE command_id=?""",
                (state, state, datetime.now(timezone.utc).isoformat(), command_id),
            )

    def _recover_dispatch(self, row) -> None:
        self.assert_leader()
        raw = bytes(row["frame_blob"])
        command = decode_command_frame(raw)
        if (
            row["account_fingerprint"] != self.instance.account_fingerprint
            or command.account_fingerprint != self.instance.account_fingerprint
            or row["client_order_id"] != command.client_order_id
            or row["command_id"] != command.command_id
            or row["command_type"] != command.command_type.value
            or row["qmt_session_id"] != self.instance.session_id
            or command.payload.get("expected_qmt_session_id") != self.instance.session_id
            or row["frame_digest"] != self._digest(raw)
        ):
            raise QmtDurableIdentityConflict("dispatch identity changed during recovery")
        located = self.command_spool.locate(command.command_id)
        state = row["dispatch_state"]
        if state == "PLANNED" and located is None:
            if command.expires_ms <= int(time.time() * 1000):
                self._fail_dispatch_manual_review(
                    row,
                    command,
                    event_type="QMT_DISPATCH_EXPIRED_BEFORE_PUBLICATION",
                    reason="planned command expired before any durable spool publication",
                )
                return
            # Command-state files are retained independently from the event
            # archiver. For a PLANNED row, absence across every command state
            # therefore proves that publication has not occurred.
            self.command_spool.publish(command)
            self._set_dispatch_state(command.command_id, "PUBLISHED")
            self._begin_reconciliation(command)
            return
        if located is None:
            if state in {
                "PUBLISHED", "OBSERVED_CLAIMED", "OBSERVED_PROCESSED",
                "OBSERVED_REJECTED", "UNKNOWN",
            }:
                self._fail_dispatch_manual_review(
                    row,
                    command,
                    event_type="QMT_DISPATCH_HISTORY_AMBIGUOUS",
                    reason="previously published command is absent from retained command history",
                )
            return
        observed, path = located
        if path.read_bytes() != raw:
            raise QmtDurableIdentityConflict("spool frame differs from durable dispatch plan")
        mapped = {
            "inbox": "PUBLISHED", "claimed": "OBSERVED_CLAIMED",
            "processed": "OBSERVED_PROCESSED", "rejected": "OBSERVED_REJECTED",
            "unknown": "UNKNOWN",
        }[observed]
        if state != mapped:
            self._set_dispatch_state(command.command_id, mapped)
        self._begin_reconciliation(command)

    def _begin_reconciliation(self, command: QmtCommand) -> None:
        current = self.repository.get_status(command.account_fingerprint, command.client_order_id)
        if current in {OrderStatus.SUBMITTING, OrderStatus.CANCEL_PENDING}:
            self.repository.transition_order(
                command.account_fingerprint, command.client_order_id, OrderStatus.UNKNOWN,
                event_type="QMT_COMMAND_PUBLISHED_LIFECYCLE_UNKNOWN",
                evidence={"command_id": command.command_id, "broker_evidence": False},
            )
            current = OrderStatus.UNKNOWN
        if current is OrderStatus.UNKNOWN:
            self.repository.transition_order(
                command.account_fingerprint, command.client_order_id, OrderStatus.RECONCILING,
                event_type="QMT_COMMAND_RECONCILIATION_BEGIN",
                evidence={"command_id": command.command_id, "broker_evidence": False},
            )

    def _observe_command_result_dispatch(self, command_id: str, result_status: str) -> None:
        row = self.conn.execute(
            "SELECT * FROM qmt_execution_dispatches WHERE command_id=?", (command_id,)
        ).fetchone()
        if row is None:
            return
        if result_status in {"SIMULATION_MUTATION_UNKNOWN", "SIMULATION_ORPHANED_UNKNOWN"}:
            self._set_dispatch_state(command_id, "UNKNOWN")
        elif result_status == "REJECTED_EXPIRED":
            self._set_dispatch_state(command_id, "OBSERVED_REJECTED")

    def close(self) -> None:
        if self._closed:
            return
        try:
            self._leader.release(self._lease)
        finally:
            self._closed = True
            self.conn.close()


def guojin_sim_oms_authorized(
    instance: QmtInstance | None, *, allow_simulation_mutation: bool
) -> bool:
    return bool(
        instance is not None
        and allow_simulation_mutation
        and instance.instance_id == "guojin_sim"
        and instance.execution_mode == "SIMULATION_CALIBRATION"
        and instance.simulation_only is True
        and instance.trading_enabled is True
        and instance.live_submit is True
        and instance.live_cancel is True
        and instance.account_type == "STOCK"
        and instance.account_fingerprint == AUTHORIZED_GUOJIN_SIM_FINGERPRINT
        and instance.bridge_build == AUTHORIZED_GUOJIN_SIM_BUILD
        and bool(instance.session_id)
    )

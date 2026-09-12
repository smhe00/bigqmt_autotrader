from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Iterable

from bigqmt_autotrader.domain import (
    DuplicateClientOrderId,
    OrderIntent,
    OrderStatus,
    RiskDecision,
    TransitionDisposition,
    transition,
)

from .db import transaction


class OrderNotFound(KeyError):
    pass


class SubmitAlreadyStarted(RuntimeError):
    pass


class CancelAlreadyStarted(RuntimeError):
    pass


class BrokerFactConflict(RuntimeError):
    pass


class BrokerOrderIdMismatch(BrokerFactConflict):
    pass


class InvalidFilledQuantity(BrokerFactConflict):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class OmsRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def start_session(self, session_id: str) -> None:
        with transaction(self.conn):
            self.conn.execute(
                "INSERT INTO runtime_sessions(session_id, started_at, reconciled_at) VALUES(?, ?, NULL)",
                (session_id, _utc_now()),
            )

    def mark_session_reconciled(self, session_id: str) -> None:
        with transaction(self.conn):
            self.conn.execute(
                "UPDATE runtime_sessions SET reconciled_at=? WHERE session_id=?",
                (_utc_now(), session_id),
            )

    def create_intent(self, intent: OrderIntent) -> None:
        with transaction(self.conn):
            try:
                self.conn.execute(
                    """
                    INSERT INTO order_intents(
                        account_fingerprint, client_order_id, strategy_id, strategy_version,
                        symbol, side, order_type, quantity, limit_price, created_at,
                        expires_at, signal_id, reason_code
                    ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        intent.account_fingerprint,
                        intent.client_order_id,
                        intent.strategy_id,
                        intent.strategy_version,
                        intent.symbol,
                        intent.side.value,
                        intent.order_type.value,
                        intent.quantity,
                        str(intent.limit_price),
                        intent.created_at.isoformat(),
                        intent.expires_at.isoformat(),
                        intent.signal_id,
                        intent.reason_code,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise DuplicateClientOrderId(intent.client_order_id) from exc
            self.conn.execute(
                """
                INSERT INTO broker_orders(
                    account_fingerprint, client_order_id, status, broker_order_id,
                    filled_quantity, submit_call_started, cancel_call_started,
                    cancel_outcome_resolved, updated_at
                ) VALUES(?, ?, ?, NULL, 0, 0, 0, 0, ?)
                """,
                (
                    intent.account_fingerprint,
                    intent.client_order_id,
                    OrderStatus.CREATED.value,
                    _utc_now(),
                ),
            )
            self._insert_event(
                intent.account_fingerprint,
                intent.client_order_id,
                event_type="INTENT_CREATED",
                from_status=None,
                to_status=OrderStatus.CREATED,
                disposition=TransitionDisposition.APPLIED,
                evidence={"signal_id": intent.signal_id},
            )

    def record_risk_decision(
        self, account_fingerprint: str, client_order_id: str, decision: RiskDecision
    ) -> OrderStatus:
        with transaction(self.conn):
            self.conn.execute(
                """
                INSERT INTO risk_decisions(
                    account_fingerprint, client_order_id, accepted, reason_code,
                    rule_version, snapshot_hash, decided_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    account_fingerprint,
                    client_order_id,
                    int(decision.accepted),
                    decision.reason_code.value,
                    decision.rule_version,
                    decision.snapshot_hash,
                    decision.decided_at.isoformat(),
                ),
            )
            target = OrderStatus.RISK_ACCEPTED if decision.accepted else OrderStatus.RISK_REJECTED
            outcome = self._transition_in_tx(
                account_fingerprint,
                client_order_id,
                target,
                event_type="RISK_DECISION",
                evidence={"reason_code": decision.reason_code.value},
            )
            return outcome.current

    def prepare_submit(self, account_fingerprint: str, client_order_id: str) -> None:
        """Commit SUBMITTING plus submit-call reservation before any side effect."""
        with transaction(self.conn):
            current = self._get_status_in_tx(account_fingerprint, client_order_id)
            outcome = transition(current, OrderStatus.SUBMITTING)
            if not outcome.changed:
                raise SubmitAlreadyStarted(client_order_id)
            cursor = self.conn.execute(
                """
                UPDATE broker_orders
                SET status=?, submit_call_started=1, updated_at=?
                WHERE account_fingerprint=? AND client_order_id=? AND submit_call_started=0
                """,
                (
                    OrderStatus.SUBMITTING.value,
                    _utc_now(),
                    account_fingerprint,
                    client_order_id,
                ),
            )
            if cursor.rowcount != 1:
                raise SubmitAlreadyStarted(client_order_id)
            self._insert_event(
                account_fingerprint,
                client_order_id,
                event_type="SUBMIT_RESERVED",
                from_status=current,
                to_status=OrderStatus.SUBMITTING,
                disposition=outcome.disposition,
                evidence={"submit_call_started": True},
            )

    def prepare_cancel(self, account_fingerprint: str, client_order_id: str) -> None:
        """Commit CANCEL_PENDING plus cancel-call reservation before side effect."""
        with transaction(self.conn):
            current = self._get_status_in_tx(account_fingerprint, client_order_id)
            outcome = transition(current, OrderStatus.CANCEL_PENDING)
            if not outcome.changed:
                raise CancelAlreadyStarted(client_order_id)
            cursor = self.conn.execute(
                """
                UPDATE broker_orders
                SET status=?, cancel_call_started=1, cancel_outcome_resolved=0, updated_at=?
                WHERE account_fingerprint=? AND client_order_id=? AND cancel_call_started=0
                """,
                (
                    OrderStatus.CANCEL_PENDING.value,
                    _utc_now(),
                    account_fingerprint,
                    client_order_id,
                ),
            )
            if cursor.rowcount != 1:
                raise CancelAlreadyStarted(client_order_id)
            self._insert_event(
                account_fingerprint,
                client_order_id,
                event_type="CANCEL_RESERVED",
                from_status=current,
                to_status=OrderStatus.CANCEL_PENDING,
                disposition=outcome.disposition,
                evidence={"cancel_call_started": True, "cancel_outcome_resolved": False},
            )

    def transition_order(
        self,
        account_fingerprint: str,
        client_order_id: str,
        target: OrderStatus,
        *,
        event_type: str,
        evidence: dict[str, Any] | None = None,
        broker_order_id: str | None = None,
        filled_quantity: int | None = None,
        cancel_outcome_resolved: bool | None = None,
    ):
        with transaction(self.conn):
            return self._transition_in_tx(
                account_fingerprint,
                client_order_id,
                target,
                event_type=event_type,
                evidence=evidence or {},
                broker_order_id=broker_order_id,
                filled_quantity=filled_quantity,
                cancel_outcome_resolved=cancel_outcome_resolved,
            )

    def _transition_in_tx(
        self,
        account_fingerprint: str,
        client_order_id: str,
        target: OrderStatus,
        *,
        event_type: str,
        evidence: dict[str, Any],
        broker_order_id: str | None = None,
        filled_quantity: int | None = None,
        cancel_outcome_resolved: bool | None = None,
    ):
        context = self._get_order_context_in_tx(account_fingerprint, client_order_id)
        current = OrderStatus(context["status"])
        current_broker_order_id = context["broker_order_id"]
        current_filled = int(context["filled_quantity"])
        order_quantity = int(context["quantity"])

        if broker_order_id is not None:
            if current_broker_order_id not in (None, broker_order_id):
                raise BrokerOrderIdMismatch(
                    f"broker order identity changed for {client_order_id}: "
                    f"{current_broker_order_id!r} -> {broker_order_id!r}"
                )

        effective_filled = current_filled
        normalized_target = target
        if filled_quantity is not None:
            if isinstance(filled_quantity, bool) or not isinstance(filled_quantity, int):
                raise TypeError("filled_quantity must be an integer")
            if filled_quantity < 0 or filled_quantity > order_quantity:
                raise InvalidFilledQuantity(
                    f"filled_quantity {filled_quantity} is outside [0, {order_quantity}]"
                )
            effective_filled = max(current_filled, filled_quantity)
            normalized_target = self._normalize_broker_status(
                target,
                effective_filled=effective_filled,
                order_quantity=order_quantity,
            )

        outcome = transition(current, normalized_target)

        fields: list[str] = []
        values: list[Any] = []
        if outcome.changed:
            fields.extend(["status=?", "updated_at=?"])
            values.extend([outcome.current.value, _utc_now()])
        if broker_order_id is not None and current_broker_order_id is None:
            fields.append("broker_order_id=?")
            values.append(broker_order_id)
        if effective_filled != current_filled:
            fields.append("filled_quantity=?")
            values.append(effective_filled)
        if cancel_outcome_resolved is not None:
            fields.append("cancel_outcome_resolved=?")
            values.append(int(cancel_outcome_resolved))
        if fields:
            values.extend([account_fingerprint, client_order_id])
            self.conn.execute(
                "UPDATE broker_orders SET " + ", ".join(fields)
                + " WHERE account_fingerprint=? AND client_order_id=?",
                tuple(values),
            )

        event_evidence = dict(evidence)
        if filled_quantity is not None:
            event_evidence.setdefault("reported_filled_quantity", filled_quantity)
            event_evidence.setdefault("effective_filled_quantity", effective_filled)
        if normalized_target is not target:
            event_evidence.setdefault("reported_status", target.value)
            event_evidence.setdefault("normalized_status", normalized_target.value)

        self._insert_event(
            account_fingerprint,
            client_order_id,
            event_type=event_type,
            from_status=current,
            to_status=outcome.current,
            disposition=outcome.disposition,
            evidence=event_evidence,
        )
        return outcome

    @staticmethod
    def _normalize_broker_status(
        target: OrderStatus,
        *,
        effective_filled: int,
        order_quantity: int,
    ) -> OrderStatus:
        if target is OrderStatus.FILLED and effective_filled != order_quantity:
            raise InvalidFilledQuantity(
                "FILLED broker status requires filled_quantity equal to order quantity"
            )
        if target is OrderStatus.REJECTED and effective_filled != 0:
            raise InvalidFilledQuantity(
                "REJECTED broker status cannot coexist with a positive filled quantity"
            )

        if target in {OrderStatus.ACKNOWLEDGED, OrderStatus.PARTIALLY_FILLED}:
            if effective_filled == order_quantity:
                return OrderStatus.FILLED
            if effective_filled > 0:
                return OrderStatus.PARTIALLY_FILLED
            if target is OrderStatus.PARTIALLY_FILLED:
                raise InvalidFilledQuantity(
                    "PARTIALLY_FILLED broker status requires a positive filled quantity"
                )
        return target

    def get_status(self, account_fingerprint: str, client_order_id: str) -> OrderStatus:
        row = self.conn.execute(
            "SELECT status FROM broker_orders WHERE account_fingerprint=? AND client_order_id=?",
            (account_fingerprint, client_order_id),
        ).fetchone()
        if row is None:
            raise OrderNotFound(client_order_id)
        return OrderStatus(row["status"])

    def get_order_row(self, account_fingerprint: str, client_order_id: str) -> sqlite3.Row:
        row = self.conn.execute(
            "SELECT * FROM broker_orders WHERE account_fingerprint=? AND client_order_id=?",
            (account_fingerprint, client_order_id),
        ).fetchone()
        if row is None:
            raise OrderNotFound(client_order_id)
        return row

    def list_recovery_candidates(self) -> Iterable[sqlite3.Row]:
        status_values = (
            OrderStatus.SUBMITTING.value,
            OrderStatus.CANCEL_PENDING.value,
            OrderStatus.UNKNOWN.value,
            OrderStatus.RECONCILING.value,
        )
        return self.conn.execute(
            """
            SELECT * FROM broker_orders
            WHERE status IN (?, ?, ?, ?)
               OR (cancel_call_started=1 AND cancel_outcome_resolved=0)
            ORDER BY rowid
            """,
            status_values,
        ).fetchall()

    def list_events(self, account_fingerprint: str, client_order_id: str):
        return self.conn.execute(
            """
            SELECT * FROM order_events
            WHERE account_fingerprint=? AND client_order_id=?
            ORDER BY event_id
            """,
            (account_fingerprint, client_order_id),
        ).fetchall()

    def _get_status_in_tx(self, account_fingerprint: str, client_order_id: str) -> OrderStatus:
        row = self.conn.execute(
            "SELECT status FROM broker_orders WHERE account_fingerprint=? AND client_order_id=?",
            (account_fingerprint, client_order_id),
        ).fetchone()
        if row is None:
            raise OrderNotFound(client_order_id)
        return OrderStatus(row["status"])

    def _get_order_context_in_tx(
        self, account_fingerprint: str, client_order_id: str
    ) -> sqlite3.Row:
        row = self.conn.execute(
            """
            SELECT b.status, b.broker_order_id, b.filled_quantity, i.quantity
            FROM broker_orders b
            JOIN order_intents i
              ON i.account_fingerprint=b.account_fingerprint
             AND i.client_order_id=b.client_order_id
            WHERE b.account_fingerprint=? AND b.client_order_id=?
            """,
            (account_fingerprint, client_order_id),
        ).fetchone()
        if row is None:
            raise OrderNotFound(client_order_id)
        return row

    def _insert_event(
        self,
        account_fingerprint: str,
        client_order_id: str,
        *,
        event_type: str,
        from_status: OrderStatus | None,
        to_status: OrderStatus,
        disposition: TransitionDisposition,
        evidence: dict[str, Any],
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO order_events(
                account_fingerprint, client_order_id, event_type, from_status,
                to_status, disposition, evidence_json, created_at
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                account_fingerprint,
                client_order_id,
                event_type,
                None if from_status is None else from_status.value,
                to_status.value,
                disposition.value,
                json.dumps(evidence, sort_keys=True, separators=(",", ":")),
                _utc_now(),
            ),
        )

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from bigqmt_autotrader.domain import (
    InvalidTransition,
    OrderStatus,
    TransitionDisposition,
    transition,
)

from .db import transaction


class BrokerEvidenceConflict(RuntimeError):
    pass


@dataclass(frozen=True)
class EvidenceIngestResult:
    fingerprint: str
    duplicate: bool
    status: OrderStatus
    disposition: TransitionDisposition


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def evidence_fingerprint(
    *,
    source: str,
    source_event_id: str | None,
    account_fingerprint: str,
    client_order_id: str,
    evidence_type: str,
    broker_order_id: str | None,
    requested_status: OrderStatus,
    filled_quantity: int,
) -> str:
    logical = {
        "source": source,
        "source_event_id": source_event_id,
        "account_fingerprint": account_fingerprint,
        "client_order_id": client_order_id,
        "evidence_type": evidence_type,
        "broker_order_id": broker_order_id,
        "requested_status": requested_status.value,
        "filled_quantity": filled_quantity,
    }
    return hashlib.sha256(_canonical_json(logical).encode("utf-8")).hexdigest()


class EvidenceJournal:
    """Durable broker evidence ingestion with dedup and monotonic aggregation.

    Every observation is retained. A logical fingerprint is evaluated against
    the order state at most once. Exact replay therefore remains auditable but
    cannot repeat a state transition. Conflicting reuse of a broker/source event
    identity is recorded and then raised fail-closed.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def ingest(
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
        if not source:
            raise ValueError("source must be non-empty")
        if not evidence_type:
            raise ValueError("evidence_type must be non-empty")
        if isinstance(filled_quantity, bool) or not isinstance(filled_quantity, int):
            raise TypeError("filled_quantity must be an integer")
        if filled_quantity < 0:
            raise ValueError("filled_quantity cannot be negative")

        source_event_id = source_event_id or None
        observed = observed_at or _utc_now()
        if observed.tzinfo is None or observed.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        observed_iso = observed.astimezone(timezone.utc).isoformat()
        payload_json = _canonical_json(payload or {})
        fingerprint = evidence_fingerprint(
            source=source,
            source_event_id=source_event_id,
            account_fingerprint=account_fingerprint,
            client_order_id=client_order_id,
            evidence_type=evidence_type,
            broker_order_id=broker_order_id,
            requested_status=requested_status,
            filled_quantity=filled_quantity,
        )

        conflict: str | None = None
        result: EvidenceIngestResult | None = None

        with transaction(self.conn):
            identity_row = None
            if source_event_id is not None:
                identity_row = self.conn.execute(
                    """
                    SELECT * FROM broker_evidence_keys
                    WHERE source=? AND source_event_id=?
                    """,
                    (source, source_event_id),
                ).fetchone()

            if identity_row is not None and identity_row["fingerprint"] != fingerprint:
                conflict = "source_event_id_reused_with_different_evidence"
                self._insert_observation(
                    fingerprint=fingerprint,
                    source=source,
                    source_event_id=source_event_id,
                    account_fingerprint=account_fingerprint,
                    client_order_id=client_order_id,
                    evidence_type=evidence_type,
                    broker_order_id=broker_order_id,
                    requested_status=requested_status,
                    filled_quantity=filled_quantity,
                    classification="CONFLICT",
                    payload_json=payload_json,
                    observed_at=observed_iso,
                )
            else:
                key_row = self.conn.execute(
                    "SELECT * FROM broker_evidence_keys WHERE fingerprint=?",
                    (fingerprint,),
                ).fetchone()

                if key_row is not None:
                    classification = "DUPLICATE" if key_row["accepted"] else "CONFLICT_DUPLICATE"
                    self._insert_observation(
                        fingerprint=fingerprint,
                        source=source,
                        source_event_id=source_event_id,
                        account_fingerprint=account_fingerprint,
                        client_order_id=client_order_id,
                        evidence_type=evidence_type,
                        broker_order_id=broker_order_id,
                        requested_status=requested_status,
                        filled_quantity=filled_quantity,
                        classification=classification,
                        payload_json=payload_json,
                        observed_at=observed_iso,
                    )
                    current = self._current_status(account_fingerprint, client_order_id)
                    if not key_row["accepted"]:
                        conflict = key_row["conflict_reason"] or "previous_evidence_conflict"
                    else:
                        result = EvidenceIngestResult(
                            fingerprint=fingerprint,
                            duplicate=True,
                            status=current,
                            disposition=TransitionDisposition(key_row["result_disposition"]),
                        )
                else:
                    context = self._order_context(account_fingerprint, client_order_id)
                    current = OrderStatus(context["status"])
                    current_broker_id = context["broker_order_id"]
                    current_filled = int(context["filled_quantity"])
                    order_quantity = int(context["quantity"])

                    if broker_order_id is not None and current_broker_id not in (None, broker_order_id):
                        conflict = "broker_order_id_mismatch"
                    elif filled_quantity > order_quantity:
                        conflict = "filled_quantity_exceeds_order_quantity"
                    else:
                        try:
                            outcome = transition(current, requested_status)
                        except InvalidTransition:
                            conflict = "illegal_state_evidence"
                        else:
                            effective_filled = max(current_filled, filled_quantity)
                            fields: list[str] = []
                            values: list[Any] = []
                            if outcome.changed:
                                fields.extend(["status=?", "updated_at=?"])
                                values.extend([outcome.current.value, observed_iso])
                            if current_broker_id is None and broker_order_id is not None:
                                fields.append("broker_order_id=?")
                                values.append(broker_order_id)
                            if effective_filled != current_filled:
                                fields.append("filled_quantity=?")
                                values.append(effective_filled)
                            if fields:
                                values.extend([account_fingerprint, client_order_id])
                                self.conn.execute(
                                    "UPDATE broker_orders SET " + ", ".join(fields)
                                    + " WHERE account_fingerprint=? AND client_order_id=?",
                                    tuple(values),
                                )

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
                                    "BROKER_EVIDENCE_" + evidence_type,
                                    current.value,
                                    outcome.current.value,
                                    outcome.disposition.value,
                                    _canonical_json(
                                        {
                                            "fingerprint": fingerprint,
                                            "source": source,
                                            "source_event_id": source_event_id,
                                            "broker_order_id": broker_order_id,
                                            "filled_quantity": filled_quantity,
                                        }
                                    ),
                                    observed_iso,
                                ),
                            )

                            self.conn.execute(
                                """
                                INSERT INTO broker_evidence_keys(
                                    fingerprint, source, source_event_id, accepted,
                                    result_disposition, conflict_reason, first_observed_at
                                ) VALUES(?, ?, ?, 1, ?, NULL, ?)
                                """,
                                (
                                    fingerprint,
                                    source,
                                    source_event_id,
                                    outcome.disposition.value,
                                    observed_iso,
                                ),
                            )
                            self._insert_observation(
                                fingerprint=fingerprint,
                                source=source,
                                source_event_id=source_event_id,
                                account_fingerprint=account_fingerprint,
                                client_order_id=client_order_id,
                                evidence_type=evidence_type,
                                broker_order_id=broker_order_id,
                                requested_status=requested_status,
                                filled_quantity=filled_quantity,
                                classification="NEW",
                                payload_json=payload_json,
                                observed_at=observed_iso,
                            )
                            result = EvidenceIngestResult(
                                fingerprint=fingerprint,
                                duplicate=False,
                                status=outcome.current,
                                disposition=outcome.disposition,
                            )

                    if conflict is not None:
                        self.conn.execute(
                            """
                            INSERT INTO broker_evidence_keys(
                                fingerprint, source, source_event_id, accepted,
                                result_disposition, conflict_reason, first_observed_at
                            ) VALUES(?, ?, ?, 0, NULL, ?, ?)
                            """,
                            (
                                fingerprint,
                                source,
                                source_event_id,
                                conflict,
                                observed_iso,
                            ),
                        )
                        self._insert_observation(
                            fingerprint=fingerprint,
                            source=source,
                            source_event_id=source_event_id,
                            account_fingerprint=account_fingerprint,
                            client_order_id=client_order_id,
                            evidence_type=evidence_type,
                            broker_order_id=broker_order_id,
                            requested_status=requested_status,
                            filled_quantity=filled_quantity,
                            classification="CONFLICT",
                            payload_json=payload_json,
                            observed_at=observed_iso,
                        )

        if conflict is not None:
            raise BrokerEvidenceConflict(conflict)
        assert result is not None
        return result

    def list_observations(self, account_fingerprint: str, client_order_id: str):
        return self.conn.execute(
            """
            SELECT * FROM broker_evidence_observations
            WHERE account_fingerprint=? AND client_order_id=?
            ORDER BY observation_id
            """,
            (account_fingerprint, client_order_id),
        ).fetchall()

    def _current_status(self, account_fingerprint: str, client_order_id: str) -> OrderStatus:
        row = self.conn.execute(
            "SELECT status FROM broker_orders WHERE account_fingerprint=? AND client_order_id=?",
            (account_fingerprint, client_order_id),
        ).fetchone()
        if row is None:
            raise KeyError(client_order_id)
        return OrderStatus(row["status"])

    def _order_context(self, account_fingerprint: str, client_order_id: str) -> sqlite3.Row:
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
            raise KeyError(client_order_id)
        return row

    def _insert_observation(
        self,
        *,
        fingerprint: str,
        source: str,
        source_event_id: str | None,
        account_fingerprint: str,
        client_order_id: str,
        evidence_type: str,
        broker_order_id: str | None,
        requested_status: OrderStatus,
        filled_quantity: int,
        classification: str,
        payload_json: str,
        observed_at: str,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO broker_evidence_observations(
                fingerprint, source, source_event_id, account_fingerprint,
                client_order_id, evidence_type, broker_order_id, requested_status,
                filled_quantity, classification, payload_json, observed_at
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                fingerprint,
                source,
                source_event_id,
                account_fingerprint,
                client_order_id,
                evidence_type,
                broker_order_id,
                requested_status.value,
                filled_quantity,
                classification,
                payload_json,
                observed_at,
            ),
        )

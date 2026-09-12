from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from bigqmt_autotrader.domain import (
    InvalidTransition,
    OrderStatus,
    TransitionDisposition,
)

from .db import transaction
from .repository import BrokerOrderIdMismatch, InvalidFilledQuantity, OmsRepository


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
    """Durable broker evidence ingestion under the active OMS leader fence.

    Every observation is retained. A logical fingerprint is evaluated against
    the order state at most once. Exact replay therefore remains auditable but
    cannot repeat a state transition. Conflicting reuse of a broker/source event
    identity is recorded and then raised fail-closed.

    The required ``write_guard`` is invoked *after* ``BEGIN IMMEDIATE``. Because
    SQLite excludes another writer until this transaction commits or rolls back,
    a successful leader-fence check is atomic with journal and aggregate writes.
    Broker facts are merged through ``OmsRepository.merge_broker_fact_in_tx`` so
    callbacks and active reconciliation cannot diverge on status/fill rules.
    """

    def __init__(
        self,
        repository: OmsRepository,
        *,
        write_guard: Callable[[], None],
    ) -> None:
        if not callable(write_guard):
            raise TypeError("write_guard must be callable")
        self.repository = repository
        self.conn = repository.conn
        self._write_guard = write_guard

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
            # BEGIN IMMEDIATE has already acquired the single SQLite writer slot.
            # Check the leader token inside that critical section so a successor
            # cannot take over between fencing validation and evidence commit.
            self._write_guard()

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
                    try:
                        outcome = self.repository.merge_broker_fact_in_tx(
                            account_fingerprint,
                            client_order_id,
                            requested_status,
                            event_type="BROKER_EVIDENCE_" + evidence_type,
                            evidence={
                                "fingerprint": fingerprint,
                                "source": source,
                                "source_event_id": source_event_id,
                                "broker_order_id": broker_order_id,
                                "filled_quantity": filled_quantity,
                            },
                            broker_order_id=broker_order_id,
                            filled_quantity=filled_quantity,
                        )
                    except BrokerOrderIdMismatch:
                        conflict = "broker_order_id_mismatch"
                    except InvalidFilledQuantity as exc:
                        conflict = self._filled_conflict_reason(exc, filled_quantity)
                    except InvalidTransition:
                        conflict = "illegal_state_evidence"
                    else:
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

    @staticmethod
    def _filled_conflict_reason(exc: InvalidFilledQuantity, filled_quantity: int) -> str:
        message = str(exc)
        if "outside" in message:
            return "filled_quantity_exceeds_order_quantity"
        if message.startswith("FILLED broker status"):
            return "filled_status_quantity_mismatch"
        if message.startswith("REJECTED broker status"):
            return "rejected_with_positive_fill"
        if message.startswith("PARTIALLY_FILLED broker status"):
            return "partial_fill_requires_positive_quantity"
        return "invalid_filled_quantity"

    def _current_status(self, account_fingerprint: str, client_order_id: str) -> OrderStatus:
        row = self.conn.execute(
            "SELECT status FROM broker_orders WHERE account_fingerprint=? AND client_order_id=?",
            (account_fingerprint, client_order_id),
        ).fetchone()
        if row is None:
            raise KeyError(client_order_id)
        return OrderStatus(row["status"])

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

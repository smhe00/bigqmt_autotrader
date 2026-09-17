from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Callable

from bigqmt_autotrader.domain import InvalidTransition, OrderStatus, TransitionDisposition

from .broker_evidence_v1 import BrokerEvidenceV1
from .db import transaction
from .repository import (
    BrokerLifecycleConflict,
    BrokerOrderIdMismatch,
    InvalidFilledQuantity,
    OmsRepository,
)


class BrokerEvidenceConflict(RuntimeError):
    pass


@dataclass(frozen=True)
class EvidenceIngestResult:
    fingerprint: str
    duplicate: bool
    status: OrderStatus
    disposition: TransitionDisposition


def evidence_fingerprint(evidence: BrokerEvidenceV1) -> str:
    identity = {
        "source": evidence.source,
        "account_fingerprint": evidence.account_fingerprint,
        "source_event_id": evidence.source_event_id,
        "semantic_digest": evidence.semantic_digest,
    }
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class EvidenceJournal:
    """Durably apply only validated BrokerEvidence v1 facts."""

    def __init__(self, repository: OmsRepository, *, write_guard: Callable[[], None]) -> None:
        if not callable(write_guard):
            raise TypeError("write_guard must be callable")
        self.repository = repository
        self.conn = repository.conn
        self._write_guard = write_guard

    def ingest(self, evidence: BrokerEvidenceV1) -> EvidenceIngestResult:
        if not isinstance(evidence, BrokerEvidenceV1):
            raise TypeError("EvidenceJournal accepts only BrokerEvidenceV1")

        fingerprint = evidence_fingerprint(evidence)
        observed_at = str(evidence.observed_at_ms)
        payload_json = json.dumps(
            evidence.to_mapping(), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        conflict: str | None = None
        conflict_fill: int | None = None
        result: EvidenceIngestResult | None = None

        with transaction(self.conn):
            self._write_guard()
            identity_row = self.conn.execute(
                """
                SELECT * FROM broker_evidence_keys
                WHERE source=? AND account_fingerprint=? AND source_event_id=?
                """,
                (evidence.source, evidence.account_fingerprint, evidence.source_event_id),
            ).fetchone()

            if identity_row is not None and identity_row["semantic_digest"] != evidence.semantic_digest:
                conflict = "source_event_id_reused_with_different_evidence"
                self._insert_observation(
                    fingerprint, evidence, "CONFLICT", payload_json, observed_at
                )
                original = self.conn.execute(
                    """
                    SELECT account_fingerprint, client_order_id
                    FROM broker_evidence_observations
                    WHERE fingerprint=? ORDER BY observation_id LIMIT 1
                    """,
                    (identity_row["fingerprint"],),
                ).fetchone()
                if original is not None:
                    self.repository.mark_broker_conflict_manual_review_in_tx(
                        original["account_fingerprint"],
                        original["client_order_id"],
                        reason=conflict,
                        evidence={
                            "source": evidence.source,
                            "source_event_id": evidence.source_event_id,
                            "conflicting_client_order_id": evidence.client_order_id,
                        },
                    )
                new_identity = (evidence.account_fingerprint, evidence.client_order_id)
                original_identity = None if original is None else (
                    original["account_fingerprint"], original["client_order_id"]
                )
                if new_identity != original_identity:
                    self.repository.mark_broker_conflict_manual_review_in_tx(
                        evidence.account_fingerprint,
                        evidence.client_order_id,
                        reason=conflict,
                        evidence={
                            "source": evidence.source,
                            "source_event_id": evidence.source_event_id,
                            "original_client_order_id": None
                            if original is None
                            else original["client_order_id"],
                        },
                    )
            else:
                key_row = self.conn.execute(
                    "SELECT * FROM broker_evidence_keys WHERE fingerprint=?", (fingerprint,)
                ).fetchone()
                if key_row is not None:
                    classification = "DUPLICATE" if key_row["accepted"] else "CONFLICT_DUPLICATE"
                    self._insert_observation(
                        fingerprint, evidence, classification, payload_json, observed_at
                    )
                    current = self._current_status(
                        evidence.account_fingerprint, evidence.client_order_id
                    )
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
                            evidence.account_fingerprint,
                            evidence.client_order_id,
                            evidence.requested_status,
                            event_type="BROKER_EVIDENCE_" + evidence.evidence_type.value,
                            evidence={
                                "fingerprint": fingerprint,
                                "source": evidence.source,
                                "source_kind": evidence.source_kind.value,
                                "source_event_id": evidence.source_event_id,
                                "mapper_profile": evidence.mapper_profile,
                                "semantic_digest": evidence.semantic_digest,
                                "broker_order_id": evidence.broker_order_id,
                                "filled_quantity": evidence.filled_quantity,
                            },
                            broker_order_id=evidence.broker_order_id,
                            filled_quantity=evidence.filled_quantity,
                        )
                    except BrokerOrderIdMismatch:
                        conflict = "broker_order_id_mismatch"
                    except BrokerLifecycleConflict as exc:
                        conflict = "terminal_broker_fact_conflict: " + str(exc)
                        conflict_fill = evidence.filled_quantity
                    except InvalidFilledQuantity as exc:
                        conflict = self._filled_conflict_reason(exc)
                    except InvalidTransition:
                        conflict = "illegal_state_evidence"
                    else:
                        self._insert_key(
                            fingerprint, evidence, True, outcome.disposition.value, None, observed_at
                        )
                        self._insert_observation(
                            fingerprint, evidence, "NEW", payload_json, observed_at
                        )
                        result = EvidenceIngestResult(
                            fingerprint=fingerprint,
                            duplicate=False,
                            status=outcome.current,
                            disposition=outcome.disposition,
                        )

                    if conflict is not None:
                        self._insert_key(fingerprint, evidence, False, None, conflict, observed_at)
                        self._insert_observation(
                            fingerprint, evidence, "CONFLICT", payload_json, observed_at
                        )
                        self.repository.mark_broker_conflict_manual_review_in_tx(
                            evidence.account_fingerprint,
                            evidence.client_order_id,
                            reason=conflict,
                            evidence={
                                "source": evidence.source,
                                "source_event_id": evidence.source_event_id,
                                "semantic_digest": evidence.semantic_digest,
                            },
                            filled_quantity=conflict_fill,
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

    @staticmethod
    def _filled_conflict_reason(exc: InvalidFilledQuantity) -> str:
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

    def _insert_key(
        self,
        fingerprint: str,
        evidence: BrokerEvidenceV1,
        accepted: bool,
        disposition: str | None,
        conflict_reason: str | None,
        observed_at: str,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO broker_evidence_keys(
                fingerprint, source, source_event_id, accepted,
                result_disposition, conflict_reason, first_observed_at,
                account_fingerprint, semantic_digest
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                fingerprint,
                evidence.source,
                evidence.source_event_id,
                int(accepted),
                disposition,
                conflict_reason,
                observed_at,
                evidence.account_fingerprint,
                evidence.semantic_digest,
            ),
        )

    def _insert_observation(
        self,
        fingerprint: str,
        evidence: BrokerEvidenceV1,
        classification: str,
        payload_json: str,
        observed_at: str,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO broker_evidence_observations(
                fingerprint, source, source_event_id, account_fingerprint,
                client_order_id, evidence_type, broker_order_id, requested_status,
                filled_quantity, classification, payload_json, observed_at,
                source_kind, mapper_profile, semantic_digest, broker_token,
                order_ref, trade_id, raw_payload_ref, raw_status_json
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                fingerprint,
                evidence.source,
                evidence.source_event_id,
                evidence.account_fingerprint,
                evidence.client_order_id,
                evidence.evidence_type.value,
                evidence.broker_order_id,
                evidence.requested_status.value,
                evidence.filled_quantity,
                classification,
                payload_json,
                observed_at,
                evidence.source_kind.value,
                evidence.mapper_profile,
                evidence.semantic_digest,
                evidence.broker_token,
                evidence.order_ref,
                evidence.trade_id,
                evidence.raw_payload_ref,
                None
                if evidence.raw_status is None
                else json.dumps(evidence.raw_status, sort_keys=True, separators=(",", ":")),
            ),
        )

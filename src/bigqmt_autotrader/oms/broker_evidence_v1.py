from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

from bigqmt_autotrader.domain import OrderStatus


_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_TOKEN_RE = re.compile(r"^[A-Za-z0-9._:-]+$")


class BrokerEvidenceSourceKind(str, Enum):
    ORDER_CALLBACK = "ORDER_CALLBACK"
    DEAL_CALLBACK = "DEAL_CALLBACK"
    ACTIVE_ORDER_QUERY = "ACTIVE_ORDER_QUERY"
    ACTIVE_DEAL_QUERY = "ACTIVE_DEAL_QUERY"


class BrokerEvidenceType(str, Enum):
    ORDER_ACCEPTED = "ORDER_ACCEPTED"
    PARTIAL_FILL = "PARTIAL_FILL"
    FULL_FILL = "FULL_FILL"
    ORDER_CANCELLED = "ORDER_CANCELLED"
    ORDER_REJECTED = "ORDER_REJECTED"


_STATUS_BY_TYPE = {
    BrokerEvidenceType.ORDER_ACCEPTED: OrderStatus.ACKNOWLEDGED,
    BrokerEvidenceType.PARTIAL_FILL: OrderStatus.PARTIALLY_FILLED,
    BrokerEvidenceType.FULL_FILL: OrderStatus.FILLED,
    BrokerEvidenceType.ORDER_CANCELLED: OrderStatus.CANCELLED,
    BrokerEvidenceType.ORDER_REJECTED: OrderStatus.REJECTED,
}


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def broker_evidence_semantic_digest(value: Mapping[str, Any]) -> str:
    """Digest the normalized semantic fact, excluding transport/audit metadata."""
    semantic = {
        key: value.get(key)
        for key in (
            "evidence_version",
            "source",
            "source_kind",
            "mapper_profile",
            "account_fingerprint",
            "client_order_id",
            "broker_token",
            "broker_order_id",
            "order_ref",
            "trade_id",
            "evidence_type",
            "requested_status",
            "filled_quantity",
            "raw_status",
            "route_account_type",
            "route_account_fingerprint",
        )
    }
    encoded = _canonical_json(semantic).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class BrokerEvidenceV1:
    evidence_version: str
    source: str
    source_kind: BrokerEvidenceSourceKind
    source_event_id: str
    mapper_profile: str
    semantic_digest: str
    account_fingerprint: str
    client_order_id: str
    broker_token: str | None
    broker_order_id: str | None
    order_ref: str | None
    trade_id: str | None
    evidence_type: BrokerEvidenceType
    requested_status: OrderStatus
    filled_quantity: int
    observed_at_ms: int
    raw_payload_ref: str
    raw_status: Mapping[str, str | int | None] | None = None
    route_account_type: str | None = None
    route_account_fingerprint: str | None = None

    def __post_init__(self) -> None:
        if self.evidence_version != "1":
            raise ValueError("evidence_version must be '1'")
        if not isinstance(self.source_kind, BrokerEvidenceSourceKind):
            raise TypeError("source_kind must be BrokerEvidenceSourceKind")
        if not isinstance(self.evidence_type, BrokerEvidenceType):
            raise TypeError("evidence_type must be BrokerEvidenceType")
        if not isinstance(self.requested_status, OrderStatus):
            raise TypeError("requested_status must be OrderStatus")
        for name, value, limit in (
            ("source", self.source, 128),
            ("source_event_id", self.source_event_id, 256),
            ("mapper_profile", self.mapper_profile, 128),
            ("client_order_id", self.client_order_id, 128),
            ("raw_payload_ref", self.raw_payload_ref, 512),
        ):
            if not isinstance(value, str) or not value or len(value) > limit:
                raise ValueError(f"invalid {name}")
        if not _SHA256_RE.fullmatch(self.account_fingerprint):
            raise ValueError("invalid account_fingerprint")
        if not _SHA256_RE.fullmatch(self.semantic_digest):
            raise ValueError("invalid semantic_digest")
        if self.broker_token is not None and (
            not self.broker_token
            or len(self.broker_token) > 64
            or not _TOKEN_RE.fullmatch(self.broker_token)
        ):
            raise ValueError("invalid broker_token")
        for name, value in (
            ("broker_order_id", self.broker_order_id),
            ("order_ref", self.order_ref),
            ("trade_id", self.trade_id),
        ):
            if value is not None and (not isinstance(value, str) or not value or len(value) > 128):
                raise ValueError(f"invalid {name}")
        if isinstance(self.filled_quantity, bool) or not isinstance(self.filled_quantity, int):
            raise TypeError("filled_quantity must be an integer")
        if self.filled_quantity < 0:
            raise ValueError("filled_quantity cannot be negative")
        if isinstance(self.observed_at_ms, bool) or not isinstance(self.observed_at_ms, int):
            raise TypeError("observed_at_ms must be an integer")
        if self.observed_at_ms <= 0:
            raise ValueError("observed_at_ms must be positive")
        if self.raw_status is not None:
            if not isinstance(self.raw_status, Mapping):
                raise TypeError("raw_status must be a mapping")
            if set(self.raw_status) - {"order_status", "submit_status"}:
                raise ValueError("raw_status contains unknown fields")
            if any(
                value is not None and not isinstance(value, (str, int))
                or isinstance(value, bool)
                for value in self.raw_status.values()
            ):
                raise TypeError("raw_status values must be string, integer, or null")
        if (self.route_account_type is None) != (self.route_account_fingerprint is None):
            raise ValueError("route account identity must be complete")
        if self.route_account_type is not None:
            if self.route_account_type not in {"STOCK", "HUGANGTONG", "SHENGANGTONG"}:
                raise ValueError("unsupported route_account_type")
            if not _SHA256_RE.fullmatch(self.route_account_fingerprint or ""):
                raise ValueError("invalid route_account_fingerprint")
        if self.requested_status is not _STATUS_BY_TYPE[self.evidence_type]:
            raise ValueError("evidence_type and requested_status disagree")
        if self.source_kind in {
            BrokerEvidenceSourceKind.DEAL_CALLBACK,
            BrokerEvidenceSourceKind.ACTIVE_DEAL_QUERY,
        } and self.evidence_type not in {
            BrokerEvidenceType.PARTIAL_FILL,
            BrokerEvidenceType.FULL_FILL,
        }:
            raise ValueError("deal sources have fill-only authority")
        if self.source_kind is BrokerEvidenceSourceKind.DEAL_CALLBACK and self.trade_id is None:
            raise ValueError("DEAL_CALLBACK requires trade_id")
        if self.evidence_type is BrokerEvidenceType.ORDER_ACCEPTED:
            if self.broker_order_id is None or self.filled_quantity != 0:
                raise ValueError("ORDER_ACCEPTED requires broker_order_id and zero fill")
        elif self.evidence_type in {
            BrokerEvidenceType.PARTIAL_FILL,
            BrokerEvidenceType.FULL_FILL,
        }:
            if self.broker_order_id is None or self.filled_quantity <= 0:
                raise ValueError("fill evidence requires broker_order_id and positive fill")
        elif self.evidence_type is BrokerEvidenceType.ORDER_CANCELLED:
            if self.broker_order_id is None:
                raise ValueError("ORDER_CANCELLED requires broker_order_id")
        elif self.evidence_type is BrokerEvidenceType.ORDER_REJECTED:
            if self.filled_quantity != 0:
                raise ValueError("ORDER_REJECTED requires zero fill")

        expected_digest = broker_evidence_semantic_digest(self.to_mapping(include_digest=False))
        if self.semantic_digest != expected_digest:
            raise ValueError("semantic_digest does not match normalized evidence")

    def to_mapping(self, *, include_digest: bool = True) -> dict[str, Any]:
        value: dict[str, Any] = {
            "evidence_version": self.evidence_version,
            "source": self.source,
            "source_kind": self.source_kind.value,
            "source_event_id": self.source_event_id,
            "mapper_profile": self.mapper_profile,
            "account_fingerprint": self.account_fingerprint,
            "client_order_id": self.client_order_id,
            "broker_token": self.broker_token,
            "broker_order_id": self.broker_order_id,
            "order_ref": self.order_ref,
            "trade_id": self.trade_id,
            "evidence_type": self.evidence_type.value,
            "requested_status": self.requested_status.value,
            "filled_quantity": self.filled_quantity,
            "observed_at_ms": self.observed_at_ms,
            "raw_payload_ref": self.raw_payload_ref,
        }
        if include_digest:
            value["semantic_digest"] = self.semantic_digest
        if self.raw_status is not None:
            value["raw_status"] = dict(self.raw_status)
        if self.route_account_type is not None:
            value["route_account_type"] = self.route_account_type
            value["route_account_fingerprint"] = self.route_account_fingerprint
        return value

    @classmethod
    def build(cls, **values: Any) -> "BrokerEvidenceV1":
        normalized = dict(values)
        normalized.setdefault("evidence_version", "1")
        source_kind = normalized.get("source_kind")
        if isinstance(source_kind, str):
            normalized["source_kind"] = BrokerEvidenceSourceKind(source_kind)
        evidence_type = normalized.get("evidence_type")
        if isinstance(evidence_type, str):
            normalized["evidence_type"] = BrokerEvidenceType(evidence_type)
        requested_status = normalized.get("requested_status")
        if isinstance(requested_status, str):
            normalized["requested_status"] = OrderStatus(requested_status)
        digest_input = dict(normalized)
        digest_input["source_kind"] = normalized["source_kind"].value
        digest_input["evidence_type"] = normalized["evidence_type"].value
        digest_input["requested_status"] = normalized["requested_status"].value
        normalized.setdefault("semantic_digest", broker_evidence_semantic_digest(digest_input))
        return cls(**normalized)

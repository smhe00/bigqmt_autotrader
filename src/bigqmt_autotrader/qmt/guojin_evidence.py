from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Mapping

from bigqmt_autotrader.domain import OrderStatus
from bigqmt_autotrader.oms.broker_evidence_v1 import (
    BrokerEvidenceSourceKind,
    BrokerEvidenceType,
    BrokerEvidenceV1,
)

from .calibration import broker_token_from_remark
from .commands import broker_token_for
from .protocol import QmtEvent


@dataclass(frozen=True)
class GuojinMapperProfile:
    name: str
    source: str
    terminal_instance_id: str
    evidence_enabled: bool


GUOJIN_SIM_PROFILE = GuojinMapperProfile(
    name="qmt-guojin-sim-20260917-v1",
    source="qmt:guojin_sim",
    terminal_instance_id="guojin_sim",
    evidence_enabled=True,
)
GUOJIN_PRODUCTION_PROFILE = GuojinMapperProfile(
    name="qmt-guojin-prod-calibration-pending-v1",
    source="qmt:guojin",
    terminal_instance_id="guojin",
    evidence_enabled=False,
)
GUOJIN_SIM_MAPPER_PROFILE = GUOJIN_SIM_PROFILE.name
GUOJIN_SIM_SOURCE = GUOJIN_SIM_PROFILE.source
GUOJIN_PRODUCTION_MAPPER_PROFILE = GUOJIN_PRODUCTION_PROFILE.name
GUOJIN_PRODUCTION_SOURCE = GUOJIN_PRODUCTION_PROFILE.source
_ACCOUNT_FINGERPRINT_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


@dataclass(frozen=True)
class GuojinMapperRejection:
    session_id: str
    sequence: int
    event_type: str
    row_index: int | None
    reason: str


@dataclass(frozen=True)
class GuojinSnapshotEvidenceBatch:
    evidence: tuple[BrokerEvidenceV1, ...]
    rejected_rows: int


@dataclass
class _RegisteredOrder:
    client_order_id: str
    broker_token: str
    symbol: str
    quantity: int
    broker_order_id: str | None = None


class GuojinEvidenceMapper:
    """Profile-driven Guojin raw fact mapper with strict terminal identity.

    A profile may be evidence-enabled only after its raw broker semantics have
    been independently calibrated.  Observe-only profiles still validate
    terminal/account/token/symbol identity but never emit BrokerEvidenceV1.
    """

    def __init__(
        self,
        *,
        account_fingerprint: str,
        profile: GuojinMapperProfile,
    ) -> None:
        if _ACCOUNT_FINGERPRINT_RE.fullmatch(account_fingerprint) is None:
            raise ValueError("account_fingerprint must be a sha256 fingerprint")
        if not isinstance(profile, GuojinMapperProfile):
            raise TypeError("profile must be GuojinMapperProfile")
        self.account_fingerprint = account_fingerprint
        self.profile = profile
        self._orders_by_token: dict[str, _RegisteredOrder] = {}
        self._trades: dict[tuple[str, str], int] = {}
        self.rejections: list[GuojinMapperRejection] = []

    def register_order(self, *, client_order_id: str, symbol: str, quantity: int) -> str:
        if not isinstance(client_order_id, str) or not client_order_id:
            raise ValueError("client_order_id must be non-empty")
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
            raise ValueError("quantity must be a positive integer")
        if not isinstance(symbol, str) or not symbol:
            raise ValueError("symbol must be non-empty")
        token = broker_token_for(self.account_fingerprint, client_order_id)
        incoming = _RegisteredOrder(client_order_id, token, symbol, quantity)
        existing = self._orders_by_token.get(token)
        if existing is not None and (
            existing.client_order_id != client_order_id
            or existing.symbol != symbol
            or existing.quantity != quantity
        ):
            raise ValueError("broker token reused for conflicting durable order identity")
        if existing is None:
            self._orders_by_token[token] = incoming
        return token

    def __call__(self, event: QmtEvent) -> BrokerEvidenceV1 | None:
        if event.event_type not in {"order", "deal"}:
            raise ValueError("Guojin mapper accepts callback ORDER/DEAL events only")
        return self._map_payload(
            event,
            event_type=event.event_type,
            payload=event.payload,
            row_index=None,
            source_kind=(
                BrokerEvidenceSourceKind.ORDER_CALLBACK
                if event.event_type == "order"
                else BrokerEvidenceSourceKind.DEAL_CALLBACK
            ),
        )

    def map_snapshot(self, event: QmtEvent) -> GuojinSnapshotEvidenceBatch:
        if event.event_type != "snapshot" or event.source != "active_query":
            raise ValueError("Guojin snapshot mapper requires an active-query snapshot")
        before = len(self.rejections)
        mapped: list[BrokerEvidenceV1] = []
        for event_type, key, kind in (
            ("order", "orders", BrokerEvidenceSourceKind.ACTIVE_ORDER_QUERY),
            ("deal", "deals", BrokerEvidenceSourceKind.ACTIVE_DEAL_QUERY),
        ):
            rows = event.payload.get(key)
            if not isinstance(rows, list):
                self._reject(event, event_type, None, "ROWS_NOT_LIST")
                continue
            for row_index, row in enumerate(rows):
                if not isinstance(row, Mapping):
                    self._reject(event, event_type, row_index, "ROW_NOT_OBJECT")
                    continue
                candidate = self._map_payload(
                    event,
                    event_type=event_type,
                    payload=row,
                    row_index=row_index,
                    source_kind=kind,
                )
                if candidate is not None:
                    mapped.append(candidate)
        return GuojinSnapshotEvidenceBatch(
            evidence=tuple(mapped),
            rejected_rows=len(self.rejections) - before,
        )

    def _map_payload(
        self,
        event: QmtEvent,
        *,
        event_type: str,
        payload: Mapping[str, Any],
        row_index: int | None,
        source_kind: BrokerEvidenceSourceKind,
    ) -> BrokerEvidenceV1 | None:
        identity = self._identity(event, event_type, row_index, payload)
        if identity is None:
            return None
        if not self.profile.evidence_enabled:
            self._reject(event, event_type, row_index, "PROFILE_EVIDENCE_DISABLED")
            return None
        if event_type == "order":
            return self._map_order(event, payload, row_index, source_kind, identity)
        return self._map_deal(event, payload, row_index, source_kind, identity)

    def _identity(
        self,
        event: QmtEvent,
        event_type: str,
        row_index: int | None,
        payload: Mapping[str, Any],
    ) -> _RegisteredOrder | None:
        if event.terminal_instance_id != self.profile.terminal_instance_id:
            self._reject(event, event_type, row_index, "TERMINAL_INSTANCE_MISMATCH")
            return None
        if event.account_fingerprint != self.account_fingerprint:
            self._reject(event, event_type, row_index, "ACCOUNT_MISMATCH")
            return None
        if event.account_type != "STOCK":
            self._reject(event, event_type, row_index, "ACCOUNT_TYPE_MISMATCH")
            return None
        raw_token = payload.get("remark")
        token = broker_token_from_remark(raw_token)
        if token is None:
            self._reject(event, event_type, row_index, "MISSING_OR_MALFORMED_TOKEN")
            return None
        identity = self._orders_by_token.get(token)
        if identity is None:
            self._reject(event, event_type, row_index, "UNREGISTERED_TOKEN")
            return None
        if token != broker_token_for(self.account_fingerprint, identity.client_order_id):
            self._reject(event, event_type, row_index, "TOKEN_IDENTITY_MISMATCH")
            return None
        if payload.get("symbol") != identity.symbol:
            self._reject(event, event_type, row_index, "SYMBOL_MISMATCH")
            return None
        if event.source == "active_query":
            route_type = payload.get("route_account_type")
            route_fingerprint = payload.get("route_account_fingerprint")
            if route_type not in {"STOCK", "HUGANGTONG", "SHENGANGTONG"}:
                self._reject(event, event_type, row_index, "MISSING_ROUTE_ACCOUNT_TYPE")
                return None
            if (
                not isinstance(route_fingerprint, str)
                or _ACCOUNT_FINGERPRINT_RE.fullmatch(route_fingerprint) is None
            ):
                self._reject(event, event_type, row_index, "MISSING_ROUTE_ACCOUNT_FINGERPRINT")
                return None
        return identity

    def _map_order(
        self,
        event: QmtEvent,
        payload: Mapping[str, Any],
        row_index: int | None,
        source_kind: BrokerEvidenceSourceKind,
        identity: _RegisteredOrder,
    ) -> BrokerEvidenceV1 | None:
        status = _integer(payload, "status_code")
        submit = _integer(payload, "submit_status_code")
        original = _integer(payload, "original_quantity")
        filled = _integer(payload, "filled_quantity")
        remaining = _integer(payload, "remaining_quantity")
        broker_order_id = _text(payload, "broker_order_id")
        if submit != 51 or original != identity.quantity or filled is None:
            self._reject(event, "order", row_index, "UNCALIBRATED_ORDER_SHAPE")
            return None
        evidence_type: BrokerEvidenceType
        requested_status: OrderStatus
        if status == 50:
            if broker_order_id is None or filled != 0 or remaining != identity.quantity:
                self._reject(event, "order", row_index, "ORDER_ACCEPTED_NOT_SETTLED")
                return None
            evidence_type = BrokerEvidenceType.ORDER_ACCEPTED
            requested_status = OrderStatus.ACKNOWLEDGED
        elif status == 54:
            if (
                broker_order_id is None
                or filled != 0
                or remaining != identity.quantity
            ):
                self._reject(event, "order", row_index, "INVALID_CANCELLED_QUANTITY")
                return None
            evidence_type = BrokerEvidenceType.ORDER_CANCELLED
            requested_status = OrderStatus.CANCELLED
        elif status == 56:
            if broker_order_id is None or filled != identity.quantity:
                self._reject(event, "order", row_index, "INVALID_FULL_FILL_QUANTITY")
                return None
            evidence_type = BrokerEvidenceType.FULL_FILL
            requested_status = OrderStatus.FILLED
        elif status == 57:
            if filled != 0:
                self._reject(event, "order", row_index, "REJECTED_ORDER_HAS_FILL")
                return None
            evidence_type = BrokerEvidenceType.ORDER_REJECTED
            requested_status = OrderStatus.REJECTED
        else:
            self._reject(event, "order", row_index, "UNKNOWN_ORDER_STATUS")
            return None

        if broker_order_id is not None and not self._bind_broker_order_id(
            event, row_index, identity, broker_order_id
        ):
            return None

        return self._build(
            event,
            payload,
            row_index=row_index,
            source_kind=source_kind,
            identity=identity,
            broker_order_id=broker_order_id,
            trade_id=None,
            evidence_type=evidence_type,
            requested_status=requested_status,
            filled_quantity=filled,
            raw_status={"order_status": status, "submit_status": submit},
        )

    def _map_deal(
        self,
        event: QmtEvent,
        payload: Mapping[str, Any],
        row_index: int | None,
        source_kind: BrokerEvidenceSourceKind,
        identity: _RegisteredOrder,
    ) -> BrokerEvidenceV1 | None:
        broker_order_id = _text(payload, "broker_order_id")
        trade_id = _text(payload, "trade_id")
        quantity = _integer(payload, "quantity")
        if broker_order_id is None or trade_id is None or quantity is None or quantity <= 0:
            self._reject(event, "deal", row_index, "INCOMPLETE_DEAL_IDENTITY")
            return None
        trade_key = (identity.broker_token, trade_id)
        previous = self._trades.get(trade_key)
        if previous is not None and previous != quantity:
            self._reject(event, "deal", row_index, "TRADE_ID_CONFLICT")
            return None
        prospective = dict(self._trades)
        prospective.setdefault(trade_key, quantity)
        cumulative = sum(
            deal_quantity for (token, _), deal_quantity in prospective.items()
            if token == identity.broker_token
        )
        if cumulative > identity.quantity:
            self._reject(event, "deal", row_index, "CUMULATIVE_FILL_EXCEEDS_ORDER")
            return None
        if not self._bind_broker_order_id(event, row_index, identity, broker_order_id):
            return None
        self._trades.setdefault(trade_key, quantity)
        evidence_type = (
            BrokerEvidenceType.FULL_FILL
            if cumulative == identity.quantity
            else BrokerEvidenceType.PARTIAL_FILL
        )
        requested_status = (
            OrderStatus.FILLED
            if evidence_type is BrokerEvidenceType.FULL_FILL
            else OrderStatus.PARTIALLY_FILLED
        )
        return self._build(
            event,
            payload,
            row_index=row_index,
            source_kind=source_kind,
            identity=identity,
            broker_order_id=broker_order_id,
            trade_id=trade_id,
            evidence_type=evidence_type,
            requested_status=requested_status,
            filled_quantity=cumulative,
            raw_status=None,
        )

    def _bind_broker_order_id(
        self,
        event: QmtEvent,
        row_index: int | None,
        identity: _RegisteredOrder,
        broker_order_id: str,
    ) -> bool:
        if identity.broker_order_id is None:
            identity.broker_order_id = broker_order_id
            return True
        if identity.broker_order_id != broker_order_id:
            self._reject(event, event.event_type, row_index, "BROKER_ORDER_ID_CONFLICT")
            return False
        return True

    def _build(
        self,
        event: QmtEvent,
        payload: Mapping[str, Any],
        *,
        row_index: int | None,
        source_kind: BrokerEvidenceSourceKind,
        identity: _RegisteredOrder,
        broker_order_id: str | None,
        trade_id: str | None,
        evidence_type: BrokerEvidenceType,
        requested_status: OrderStatus,
        filled_quantity: int,
        raw_status: Mapping[str, str | int | None] | None,
    ) -> BrokerEvidenceV1:
        row_type = (
            "order"
            if source_kind is BrokerEvidenceSourceKind.ACTIVE_ORDER_QUERY
            else "deal"
        )
        suffix = "" if row_index is None else f"/{row_type}/{row_index}"
        return BrokerEvidenceV1.build(
            source=self.profile.source,
            source_kind=source_kind,
            source_event_id=f"{event.session_id}:{event.sequence}{suffix}",
            mapper_profile=self.profile.name,
            account_fingerprint=event.account_fingerprint,
            client_order_id=identity.client_order_id,
            broker_token=identity.broker_token,
            broker_order_id=broker_order_id,
            order_ref=_text(payload, "order_ref"),
            trade_id=trade_id,
            evidence_type=evidence_type,
            requested_status=requested_status,
            filled_quantity=filled_quantity,
            observed_at_ms=event.timestamp_ms,
            raw_payload_ref=(
                f"qmt://{self.profile.terminal_instance_id}/{event.session_id}/{event.sequence}{suffix}"
            ),
            raw_status=raw_status,
            route_account_type=(
                _text(payload, "route_account_type") if event.source == "active_query" else None
            ),
            route_account_fingerprint=(
                _text(payload, "route_account_fingerprint")
                if event.source == "active_query"
                else None
            ),
        )

    def _reject(
        self,
        event: QmtEvent,
        event_type: str,
        row_index: int | None,
        reason: str,
    ) -> None:
        self.rejections.append(
            GuojinMapperRejection(
                session_id=event.session_id,
                sequence=event.sequence,
                event_type=event_type,
                row_index=row_index,
                reason=reason,
            )
        )


class GuojinSimEvidenceMapper(GuojinEvidenceMapper):
    def __init__(self, *, account_fingerprint: str) -> None:
        super().__init__(
            account_fingerprint=account_fingerprint,
            profile=GUOJIN_SIM_PROFILE,
        )


class GuojinProductionEvidenceMapper(GuojinEvidenceMapper):
    """Observe-only production mapper until a later calibration Gate enables evidence."""

    def __init__(self, *, account_fingerprint: str) -> None:
        super().__init__(
            account_fingerprint=account_fingerprint,
            profile=GUOJIN_PRODUCTION_PROFILE,
        )


def _text(payload: Mapping[str, Any], key: str) -> str | None:
    value = payload.get(key)
    return value if isinstance(value, str) and value else None


def _integer(payload: Mapping[str, Any], key: str) -> int | None:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value

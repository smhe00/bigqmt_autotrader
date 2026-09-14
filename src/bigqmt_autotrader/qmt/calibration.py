from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Mapping

from .commands import broker_token_for
from .protocol import QmtEvent


_BROKER_TOKEN_RE = re.compile(r"^BQ[0-9a-f]{20}$")


def broker_token_from_remark(value: Any) -> str | None:
    """Return a calibrated P4 broker token only for the exact remark format.

    No fuzzy parsing is permitted. A future live bridge is expected to place the
    22-character `BQ` token in QMT userOrderId, which QMT exposes as
    `m_strRemark`. Until real/simulation broker mutation is separately
    authorized, this helper is observation-only.
    """
    if not isinstance(value, str):
        return None
    return value if _BROKER_TOKEN_RE.fullmatch(value) else None


@dataclass(frozen=True)
class QmtOrderDealCalibrationRecord:
    event_type: str
    source_event_id: str
    symbol: str | None
    broker_token: str | None
    remark: str | None
    broker_order_id: str | None
    order_ref: str | None
    trade_id: str | None
    status_code: int | None
    submit_status_code: int | None
    original_quantity: int | None
    filled_quantity: int | None
    deal_quantity: int | None


def order_deal_calibration_record(event: QmtEvent) -> QmtOrderDealCalibrationRecord:
    """Project a raw QMT ORDER/DEAL event into a calibration record.

    The projection deliberately does not map QMT status codes into OrderStatus.
    That mapping must be established from observed Guojin QMT behavior before it
    can become broker evidence.
    """
    if event.event_type not in {"order", "deal"}:
        raise ValueError("calibration record requires an ORDER or DEAL event")
    payload = event.payload
    remark = payload.get("remark")
    return QmtOrderDealCalibrationRecord(
        event_type=event.event_type,
        source_event_id=event.session_id + ":" + str(event.sequence),
        symbol=payload.get("symbol") if isinstance(payload.get("symbol"), str) else None,
        broker_token=broker_token_from_remark(remark),
        remark=remark if isinstance(remark, str) else None,
        broker_order_id=(
            payload.get("broker_order_id")
            if isinstance(payload.get("broker_order_id"), str)
            else None
        ),
        order_ref=payload.get("order_ref") if isinstance(payload.get("order_ref"), str) else None,
        trade_id=payload.get("trade_id") if isinstance(payload.get("trade_id"), str) else None,
        status_code=(
            payload.get("status_code") if isinstance(payload.get("status_code"), int) else None
        ),
        submit_status_code=(
            payload.get("submit_status_code")
            if isinstance(payload.get("submit_status_code"), int)
            else None
        ),
        original_quantity=(
            payload.get("original_quantity")
            if isinstance(payload.get("original_quantity"), int)
            else None
        ),
        filled_quantity=(
            payload.get("filled_quantity")
            if isinstance(payload.get("filled_quantity"), int)
            else None
        ),
        deal_quantity=(
            payload.get("quantity") if isinstance(payload.get("quantity"), int) else None
        ),
    )


@dataclass(frozen=True)
class BrokerTokenCalibrationRecord:
    session_id: str
    sequence: int
    event_type: str
    source: str
    row_index: int | None
    account_fingerprint: str
    disposition: str
    remark: str | None
    client_order_id: str | None
    broker_order_id: str | None
    trade_id: str | None
    status_code: int | None
    submit_status_code: int | None
    filled_quantity: int | None
    quantity: int | None


class QmtBrokerTokenCalibration:
    """Correlate exact known tokens without producing OMS broker evidence."""

    def __init__(self) -> None:
        self._by_token: dict[str, tuple[str, str]] = {}
        self.records: list[BrokerTokenCalibrationRecord] = []

    def register(self, account_fingerprint: str, client_order_id: str) -> str:
        token = broker_token_for(account_fingerprint, client_order_id)
        identity = (account_fingerprint, client_order_id)
        existing = self._by_token.get(token)
        if existing is not None and existing != identity:
            raise ValueError("broker_token collision across durable OMS identities")
        self._by_token[token] = identity
        return token

    def __call__(self, event: QmtEvent) -> BrokerTokenCalibrationRecord:
        return self.observe(event)

    def observe(self, event: QmtEvent) -> BrokerTokenCalibrationRecord:
        if event.event_type not in {"order", "deal"}:
            raise ValueError("broker-token calibration accepts only ORDER/DEAL events")
        return self._observe_payload(
            event,
            event_type=event.event_type,
            source=event.source,
            row_index=None,
            payload=event.payload,
        )

    def observe_snapshot(self, event: QmtEvent) -> tuple[BrokerTokenCalibrationRecord, ...]:
        if event.event_type != "snapshot":
            raise ValueError("snapshot calibration requires a snapshot event")
        records: list[BrokerTokenCalibrationRecord] = []
        for event_type, key in (("order", "orders"), ("deal", "deals")):
            rows = event.payload.get(key, [])
            if not isinstance(rows, list):
                raise ValueError("snapshot ORDER/DEAL rows must be lists")
            for row_index, row in enumerate(rows):
                if not isinstance(row, Mapping):
                    raise ValueError("snapshot ORDER/DEAL row must be an object")
                records.append(
                    self._observe_payload(
                        event,
                        event_type=event_type,
                        source="snapshot",
                        row_index=row_index,
                        payload=row,
                    )
                )
        return tuple(records)

    def _observe_payload(
        self,
        event: QmtEvent,
        *,
        event_type: str,
        source: str,
        row_index: int | None,
        payload: Mapping[str, Any],
    ) -> BrokerTokenCalibrationRecord:
        raw_remark = payload.get("remark")
        remark = raw_remark if isinstance(raw_remark, str) and raw_remark else None
        identity = self._by_token.get(remark or "")
        if remark is None:
            disposition = "MISSING_REMARK"
        elif broker_token_from_remark(remark) is None:
            disposition = "MALFORMED_REMARK"
        elif identity is None:
            disposition = "UNREGISTERED_TOKEN"
        elif identity[0] != event.account_fingerprint:
            disposition = "ACCOUNT_MISMATCH"
            identity = None
        else:
            disposition = "MATCHED_KNOWN_TOKEN"

        record = BrokerTokenCalibrationRecord(
            session_id=event.session_id,
            sequence=event.sequence,
            event_type=event_type,
            source=source,
            row_index=row_index,
            account_fingerprint=event.account_fingerprint,
            disposition=disposition,
            remark=remark,
            client_order_id=None if identity is None else identity[1],
            broker_order_id=_text(payload, "broker_order_id"),
            trade_id=_text(payload, "trade_id"),
            status_code=_integer(payload, "status_code"),
            submit_status_code=_integer(payload, "submit_status_code"),
            filled_quantity=_integer(payload, "filled_quantity"),
            quantity=_integer(payload, "quantity"),
        )
        self.records.append(record)
        return record

    def summary(self) -> Mapping[str, Any]:
        counts: dict[str, int] = {}
        for record in self.records:
            counts[record.disposition] = counts.get(record.disposition, 0) + 1
        return {
            "observations": len(self.records),
            "dispositions": counts,
            "broker_evidence_mapping_enabled": False,
            "live_submit": False,
            "live_cancel": False,
        }


def _text(payload: Mapping[str, Any], key: str) -> str | None:
    value = payload.get(key)
    return value if isinstance(value, str) and value else None


def _integer(payload: Mapping[str, Any], key: str) -> int | None:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value

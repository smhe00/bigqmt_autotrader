from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

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

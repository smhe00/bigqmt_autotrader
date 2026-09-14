from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Mapping

from .protocol import QmtEvent


_BROKER_TOKEN_RE = re.compile(r"^BQ[0-9a-f]{20}$")


@dataclass(frozen=True)
class QmtOrderDealObservation:
    event_type: str
    broker_token: str | None
    broker_order_id: str | None
    order_ref: str | None
    trade_id: str | None
    status_code: int | None
    submit_status_code: int | None
    filled_quantity: int | None
    remaining_quantity: int | None
    symbol: str | None
    payload: Mapping[str, Any]

    @property
    def token_correlated(self) -> bool:
        return self.broker_token is not None


def broker_token_from_remark(value: object) -> str | None:
    """Return a calibrated P4 broker token only when the remark matches exactly.

    This helper deliberately performs no fuzzy parsing. QMT `m_strRemark` is the
    proposed durable correlation field for P4, so accepting partial or decorated
    values would weaken identity guarantees.
    """
    if not isinstance(value, str):
        return None
    return value if _BROKER_TOKEN_RE.fullmatch(value) else None


def observe_order_or_deal(event: QmtEvent) -> QmtOrderDealObservation | None:
    """Extract read-only correlation facts from normalized ORDER/DEAL events.

    No OMS lifecycle state is inferred here. In particular, numeric QMT status
    codes are retained as calibration evidence until a Guojin-specific mapping
    has been observed and reviewed from real callbacks/query results.
    """
    if event.event_type not in {"order", "deal"}:
        return None
    payload = event.payload
    return QmtOrderDealObservation(
        event_type=event.event_type,
        broker_token=broker_token_from_remark(payload.get("remark")),
        broker_order_id=_text(payload.get("broker_order_id")),
        order_ref=_text(payload.get("order_ref")),
        trade_id=_text(payload.get("trade_id")),
        status_code=_int_or_none(payload.get("status_code")),
        submit_status_code=_int_or_none(payload.get("submit_status_code")),
        filled_quantity=_int_or_none(payload.get("filled_quantity")),
        remaining_quantity=_int_or_none(payload.get("remaining_quantity")),
        symbol=_text(payload.get("symbol")),
        payload=dict(payload),
    )


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _int_or_none(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value

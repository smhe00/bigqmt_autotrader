from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum


def _require_nonempty(name: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


def _require_aware(name: str, value: datetime) -> None:
    if not isinstance(value, datetime):
        raise TypeError(f"{name} must be datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def _require_positive_decimal(name: str, value: Decimal) -> None:
    if not isinstance(value, Decimal):
        raise TypeError(f"{name} must be decimal.Decimal; binary float is forbidden")
    if not value.is_finite() or value <= Decimal("0"):
        raise ValueError(f"{name} must be finite and > 0")


class QuoteUpdateResult(str, Enum):
    APPLIED = "APPLIED"
    DUPLICATE = "DUPLICATE"
    STALE_IGNORED = "STALE_IGNORED"


@dataclass(frozen=True)
class MarketQuote:
    """Normalized exact-symbol quote admitted into Host market-data state.

    ``broker_time`` is the authoritative market timestamp supplied by the
    upstream market-data source. ``observed_at`` is the Host-local time when
    that exact quote was observed. Production freshness requires both clocks
    to be recent and non-future-dated.
    """

    symbol: str
    last_price: Decimal
    broker_time: datetime
    observed_at: datetime
    source: str

    def __post_init__(self) -> None:
        _require_nonempty("symbol", self.symbol)
        _require_positive_decimal("last_price", self.last_price)
        _require_aware("broker_time", self.broker_time)
        _require_aware("observed_at", self.observed_at)
        _require_nonempty("source", self.source)

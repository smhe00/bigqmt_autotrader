from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Optional

from .codes import RiskReasonCode
from .states import OrderStatus, OrderType, Side


def _require_nonempty(name: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


def _require_positive_int(name: str, value: int) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")


def _require_decimal(name: str, value: Decimal) -> None:
    if not isinstance(value, Decimal):
        raise TypeError(f"{name} must be decimal.Decimal; binary float is forbidden")
    if not value.is_finite() or value <= Decimal("0"):
        raise ValueError(f"{name} must be finite and > 0")


def _require_aware(name: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


@dataclass(frozen=True)
class OrderIntent:
    client_order_id: str
    strategy_id: str
    strategy_version: str
    account_fingerprint: str
    symbol: str
    side: Side
    quantity: int
    limit_price: Decimal
    created_at: datetime
    expires_at: datetime
    signal_id: str
    reason_code: str
    order_type: OrderType = OrderType.LIMIT

    def __post_init__(self) -> None:
        for name in (
            "client_order_id",
            "strategy_id",
            "strategy_version",
            "account_fingerprint",
            "symbol",
            "signal_id",
            "reason_code",
        ):
            _require_nonempty(name, getattr(self, name))
        if self.order_type is not OrderType.LIMIT:
            raise ValueError("P0 contract permits LIMIT orders only")
        _require_positive_int("quantity", self.quantity)
        _require_decimal("limit_price", self.limit_price)
        _require_aware("created_at", self.created_at)
        _require_aware("expires_at", self.expires_at)
        if self.expires_at <= self.created_at:
            raise ValueError("expires_at must be later than created_at")

    def is_expired(self, now: datetime) -> bool:
        _require_aware("now", now)
        return now >= self.expires_at


@dataclass(frozen=True)
class Order:
    client_order_id: str
    account_fingerprint: str
    symbol: str
    side: Side
    quantity: int
    limit_price: Decimal
    status: OrderStatus = OrderStatus.CREATED
    broker_order_id: Optional[str] = None
    filled_quantity: int = 0

    def __post_init__(self) -> None:
        _require_nonempty("client_order_id", self.client_order_id)
        _require_nonempty("account_fingerprint", self.account_fingerprint)
        _require_nonempty("symbol", self.symbol)
        _require_positive_int("quantity", self.quantity)
        _require_decimal("limit_price", self.limit_price)
        if not isinstance(self.filled_quantity, int) or isinstance(self.filled_quantity, bool):
            raise ValueError("filled_quantity must be an integer")
        if self.filled_quantity < 0 or self.filled_quantity > self.quantity:
            raise ValueError("filled_quantity must be in [0, quantity]")


@dataclass(frozen=True)
class Trade:
    trade_id: str
    client_order_id: str
    account_fingerprint: str
    symbol: str
    side: Side
    quantity: int
    price: Decimal
    traded_at: datetime

    def __post_init__(self) -> None:
        for name in ("trade_id", "client_order_id", "account_fingerprint", "symbol"):
            _require_nonempty(name, getattr(self, name))
        _require_positive_int("quantity", self.quantity)
        _require_decimal("price", self.price)
        _require_aware("traded_at", self.traded_at)


@dataclass(frozen=True)
class RiskDecision:
    accepted: bool
    reason_code: RiskReasonCode
    rule_version: str
    snapshot_hash: str
    decided_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.accepted, bool):
            raise TypeError("accepted must be bool")
        if not isinstance(self.reason_code, RiskReasonCode):
            raise TypeError("reason_code must be RiskReasonCode")
        for name in ("rule_version", "snapshot_hash"):
            _require_nonempty(name, getattr(self, name))
        _require_aware("decided_at", self.decided_at)

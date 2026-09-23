from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Iterable

from bigqmt_autotrader.domain import Side


class BrokerOrderOwnership(str, Enum):
    SYSTEM = "SYSTEM"
    EXTERNAL = "EXTERNAL"


class ExternalOrderFactConflict(RuntimeError):
    pass


@dataclass(frozen=True)
class ActiveBrokerOrderFact:
    """Broker-neutral fact for an order already known to be active.

    Broker-specific adapters are responsible for deciding whether a raw broker
    status is active. This layer never guesses raw status semantics.
    """

    source_event_id: str
    symbol: str
    side: Side
    quantity: int
    filled_quantity: int
    limit_price: Decimal
    broker_token: str | None
    observed_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.source_event_id, str) or not self.source_event_id:
            raise ValueError("source_event_id must be non-empty")
        if not isinstance(self.symbol, str) or not self.symbol:
            raise ValueError("symbol must be non-empty")
        if not isinstance(self.side, Side):
            raise TypeError("side must be Side")
        if isinstance(self.quantity, bool) or not isinstance(self.quantity, int) or self.quantity <= 0:
            raise ValueError("quantity must be a positive integer")
        if (
            isinstance(self.filled_quantity, bool)
            or not isinstance(self.filled_quantity, int)
            or self.filled_quantity < 0
            or self.filled_quantity >= self.quantity
        ):
            raise ValueError("active order filled_quantity must be in [0, quantity)")
        if not isinstance(self.limit_price, Decimal):
            raise TypeError("limit_price must be decimal.Decimal")
        if not self.limit_price.is_finite() or self.limit_price <= 0:
            raise ValueError("limit_price must be finite and > 0")
        if self.broker_token is not None and (
            not isinstance(self.broker_token, str) or not self.broker_token
        ):
            raise ValueError("broker_token must be non-empty when supplied")
        if not isinstance(self.observed_at, datetime):
            raise TypeError("observed_at must be datetime")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")

    @property
    def remaining_quantity(self) -> int:
        return self.quantity - self.filled_quantity

    @property
    def remaining_notional(self) -> Decimal:
        return self.limit_price * Decimal(self.remaining_quantity)


@dataclass(frozen=True)
class ClassifiedActiveOrder:
    fact: ActiveBrokerOrderFact
    ownership: BrokerOrderOwnership


@dataclass(frozen=True)
class ExternalOrderRiskSummary:
    blocked_symbols: frozenset[str]
    pending_buy_notional: Decimal
    external_order_count: int
    classified: tuple[ClassifiedActiveOrder, ...]

    @classmethod
    def empty(cls) -> "ExternalOrderRiskSummary":
        return cls(
            blocked_symbols=frozenset(),
            pending_buy_notional=Decimal("0"),
            external_order_count=0,
            classified=(),
        )

    def pending_buy_notional_for(self, symbol: str) -> Decimal:
        return sum(
            (
                item.fact.remaining_notional
                for item in self.classified
                if item.ownership is BrokerOrderOwnership.EXTERNAL
                and item.fact.side is Side.BUY
                and item.fact.symbol == symbol
            ),
            Decimal("0"),
        )


class ExternalOrderRiskClassifier:
    """Classify normalized active broker orders by durable system token ownership."""

    def __init__(self, *, registered_system_tokens: Iterable[str]) -> None:
        tokens = frozenset(registered_system_tokens)
        if any(not isinstance(value, str) or not value for value in tokens):
            raise ValueError("registered_system_tokens must contain non-empty strings")
        self._system_tokens = tokens

    def classify(
        self,
        facts: Iterable[ActiveBrokerOrderFact],
    ) -> ExternalOrderRiskSummary:
        seen: dict[str, ActiveBrokerOrderFact] = {}
        classified: list[ClassifiedActiveOrder] = []
        blocked: set[str] = set()
        pending_buy = Decimal("0")
        external_count = 0

        for fact in facts:
            if not isinstance(fact, ActiveBrokerOrderFact):
                raise TypeError("facts must contain ActiveBrokerOrderFact")
            previous = seen.get(fact.source_event_id)
            if previous is not None:
                if previous != fact:
                    raise ExternalOrderFactConflict(
                        "source_event_id reused for conflicting active order fact"
                    )
                continue
            seen[fact.source_event_id] = fact
            ownership = (
                BrokerOrderOwnership.SYSTEM
                if fact.broker_token is not None
                and fact.broker_token in self._system_tokens
                else BrokerOrderOwnership.EXTERNAL
            )
            classified.append(ClassifiedActiveOrder(fact=fact, ownership=ownership))
            if ownership is BrokerOrderOwnership.EXTERNAL:
                external_count += 1
                blocked.add(fact.symbol)
                if fact.side is Side.BUY:
                    pending_buy += fact.remaining_notional

        return ExternalOrderRiskSummary(
            blocked_symbols=frozenset(blocked),
            pending_buy_notional=pending_buy,
            external_order_count=external_count,
            classified=tuple(classified),
        )

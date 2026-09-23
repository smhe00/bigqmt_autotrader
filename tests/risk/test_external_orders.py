from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from bigqmt_autotrader.domain import Side
from bigqmt_autotrader.risk import (
    ActiveBrokerOrderFact,
    BrokerOrderOwnership,
    ExternalOrderFactConflict,
    ExternalOrderRiskClassifier,
)


NOW = datetime(2026, 9, 23, 14, 45, tzinfo=timezone(timedelta(hours=8)))


def fact(
    event_id: str,
    *,
    symbol: str = "510300.SH",
    side: Side = Side.BUY,
    token: str | None = None,
    price: str = "4.64",
    quantity: int = 100,
    filled: int = 0,
):
    return ActiveBrokerOrderFact(
        source_event_id=event_id,
        symbol=symbol,
        side=side,
        quantity=quantity,
        filled_quantity=filled,
        limit_price=Decimal(price),
        broker_token=token,
        observed_at=NOW,
    )


def test_registered_system_order_is_not_external_or_blocking():
    summary = ExternalOrderRiskClassifier(
        registered_system_tokens={"BQsystem"}
    ).classify([fact("order-1", token="BQsystem")])

    assert summary.external_order_count == 0
    assert summary.blocked_symbols == frozenset()
    assert summary.pending_buy_notional == Decimal("0")
    assert summary.classified[0].ownership is BrokerOrderOwnership.SYSTEM


def test_unknown_or_missing_token_is_external_and_blocks_symbol():
    summary = ExternalOrderRiskClassifier(
        registered_system_tokens={"BQsystem"}
    ).classify(
        [
            fact("order-1", token=None, filled=20),
            fact(
                "order-2",
                symbol="000001.SZ",
                side=Side.SELL,
                token="BQunknown",
                price="10",
            ),
        ]
    )

    assert summary.external_order_count == 2
    assert summary.blocked_symbols == frozenset({"510300.SH", "000001.SZ"})
    assert summary.pending_buy_notional == Decimal("371.20")
    assert summary.pending_buy_notional_for("510300.SH") == Decimal("371.20")
    assert summary.pending_buy_notional_for("000001.SZ") == Decimal("0")


def test_duplicate_same_fact_is_idempotent():
    item = fact("order-1", token=None)
    summary = ExternalOrderRiskClassifier(
        registered_system_tokens=set()
    ).classify([item, item])

    assert summary.external_order_count == 1
    assert len(summary.classified) == 1


def test_conflicting_same_source_event_fails_closed():
    classifier = ExternalOrderRiskClassifier(registered_system_tokens=set())
    with pytest.raises(ExternalOrderFactConflict):
        classifier.classify(
            [
                fact("order-1", price="4.64"),
                fact("order-1", price="4.65"),
            ]
        )


def test_active_fact_requires_unfilled_remaining_quantity():
    with pytest.raises(ValueError, match="active order"):
        fact("order-1", quantity=100, filled=100)

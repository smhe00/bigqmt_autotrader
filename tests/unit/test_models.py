from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from bigqmt_autotrader.domain import OrderIntent, Side


def make_intent(**overrides):
    created = datetime(2026, 9, 12, 9, 40, tzinfo=timezone(timedelta(hours=8)))
    values = {
        "client_order_id": "strategyA-20260912-000001",
        "strategy_id": "strategyA",
        "strategy_version": "git:abc1234",
        "account_fingerprint": "sha256:test",
        "symbol": "600000.SH",
        "side": Side.BUY,
        "quantity": 100,
        "limit_price": Decimal("10.23"),
        "created_at": created,
        "expires_at": created + timedelta(seconds=5),
        "signal_id": "signal-1",
        "reason_code": "TARGET_POSITION_REBALANCE",
    }
    values.update(overrides)
    return OrderIntent(**values)


def test_order_intent_accepts_decimal_price():
    intent = make_intent()
    assert intent.limit_price == Decimal("10.23")


def test_binary_float_price_is_rejected():
    with pytest.raises(TypeError, match="binary float is forbidden"):
        make_intent(limit_price=10.23)


def test_intent_expiry_is_deterministic():
    intent = make_intent()
    assert not intent.is_expired(intent.expires_at - timedelta(microseconds=1))
    assert intent.is_expired(intent.expires_at)


def test_naive_timestamps_are_rejected():
    with pytest.raises(ValueError, match="timezone-aware"):
        make_intent(created_at=datetime(2026, 9, 12, 9, 40))

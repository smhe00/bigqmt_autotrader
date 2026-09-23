from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from bigqmt_autotrader.market_data import (
    MarketDataService,
    MarketDataStale,
    MarketDataUnavailable,
    MarketQuote,
    QuoteUpdateResult,
)


NOW = datetime(2026, 9, 23, 9, 45, tzinfo=timezone(timedelta(hours=8)))


def quote(
    price: str = "451.8",
    *,
    symbol: str = "00700.HGT",
    broker_offset_seconds: int = -1,
    observed_offset_seconds: int = 0,
) -> MarketQuote:
    return MarketQuote(
        symbol=symbol,
        last_price=Decimal(price),
        broker_time=NOW + timedelta(seconds=broker_offset_seconds),
        observed_at=NOW + timedelta(seconds=observed_offset_seconds),
        source="qmt_tick",
    )


def test_latest_requires_both_broker_and_local_freshness():
    service = MarketDataService()
    service.ingest(quote())

    latest = service.latest("00700.HGT", now=NOW, max_age_seconds=15)

    assert latest.last_price == Decimal("451.8")


def test_new_local_observation_does_not_freshen_old_broker_tick():
    service = MarketDataService()
    service.ingest(
        MarketQuote(
            symbol="00700.HGT",
            last_price=Decimal("430.4"),
            broker_time=NOW - timedelta(days=1),
            observed_at=NOW,
            source="qmt_snapshot_refresh",
        )
    )

    with pytest.raises(MarketDataStale, match="broker quote"):
        service.latest("00700.HGT", now=NOW, max_age_seconds=15)


def test_stale_local_observation_is_rejected_even_if_broker_time_is_recent():
    service = MarketDataService()
    service.ingest(
        MarketQuote(
            symbol="510300.SH",
            last_price=Decimal("4.64"),
            broker_time=NOW - timedelta(seconds=1),
            observed_at=NOW - timedelta(seconds=30),
            source="qmt_tick",
        )
    )

    with pytest.raises(MarketDataStale, match="local observation"):
        service.latest("510300.SH", now=NOW, max_age_seconds=15)


def test_future_timestamps_fail_closed():
    service = MarketDataService()
    service.ingest(quote(broker_offset_seconds=1))

    with pytest.raises(MarketDataStale, match="future"):
        service.latest("00700.HGT", now=NOW, max_age_seconds=15)


def test_missing_symbol_is_unavailable():
    service = MarketDataService()

    with pytest.raises(MarketDataUnavailable):
        service.latest("00700.HGT", now=NOW, max_age_seconds=15)


def test_newer_broker_tick_replaces_older_tick():
    service = MarketDataService()
    older = quote(price="450.0", broker_offset_seconds=-2)
    newer = quote(price="451.8", broker_offset_seconds=-1)

    assert service.ingest(older) is QuoteUpdateResult.APPLIED
    assert service.ingest(newer) is QuoteUpdateResult.APPLIED
    assert service.latest("00700.HGT", now=NOW, max_age_seconds=15) == newer


def test_older_tick_is_ignored_after_newer_tick():
    service = MarketDataService()
    newer = quote(price="451.8", broker_offset_seconds=-1)
    older = quote(price="450.0", broker_offset_seconds=-2)

    assert service.ingest(newer) is QuoteUpdateResult.APPLIED
    assert service.ingest(older) is QuoteUpdateResult.STALE_IGNORED
    assert service.latest("00700.HGT", now=NOW, max_age_seconds=15) == newer


def test_same_broker_timestamp_same_price_is_duplicate():
    service = MarketDataService()
    first = quote()
    duplicate = MarketQuote(
        symbol=first.symbol,
        last_price=first.last_price,
        broker_time=first.broker_time,
        observed_at=NOW + timedelta(milliseconds=100),
        source=first.source,
    )

    assert service.ingest(first) is QuoteUpdateResult.APPLIED
    assert service.ingest(duplicate) is QuoteUpdateResult.DUPLICATE


def test_same_broker_timestamp_different_price_never_overwrites_first_fact():
    service = MarketDataService()
    first = quote(price="451.8")
    conflict = quote(price="452.0")

    assert service.ingest(first) is QuoteUpdateResult.APPLIED
    assert service.ingest(conflict) is QuoteUpdateResult.STALE_IGNORED
    assert service.latest("00700.HGT", now=NOW, max_age_seconds=15) == first


def test_market_quote_rejects_binary_float_price():
    with pytest.raises(TypeError, match="decimal.Decimal"):
        MarketQuote(
            symbol="510300.SH",
            last_price=4.64,
            broker_time=NOW,
            observed_at=NOW,
            source="test",
        )

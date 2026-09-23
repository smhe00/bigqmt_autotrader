from __future__ import annotations

from datetime import datetime, timedelta

from .models import MarketQuote, QuoteUpdateResult


class MarketDataError(RuntimeError):
    pass


class MarketDataUnavailable(MarketDataError):
    pass


class MarketDataStale(MarketDataError):
    pass


def _require_aware(name: str, value: datetime) -> None:
    if not isinstance(value, datetime):
        raise TypeError(f"{name} must be datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


class MarketDataService:
    """Small fail-closed Host cache for exact-symbol normalized quotes.

    The service deliberately does not know QMT wire formats. Market-data
    adapters must normalize exact-symbol evidence before calling ``ingest``.
    A newer local observation is insufficient to make an older broker tick
    fresh; broker time is monotonic authority.
    """

    def __init__(self) -> None:
        self._quotes: dict[str, MarketQuote] = {}

    def ingest(self, quote: MarketQuote) -> QuoteUpdateResult:
        if not isinstance(quote, MarketQuote):
            raise TypeError("quote must be MarketQuote")
        previous = self._quotes.get(quote.symbol)
        if previous is None:
            self._quotes[quote.symbol] = quote
            return QuoteUpdateResult.APPLIED

        if quote.broker_time < previous.broker_time:
            return QuoteUpdateResult.STALE_IGNORED

        if quote.broker_time == previous.broker_time:
            if quote.last_price == previous.last_price:
                return QuoteUpdateResult.DUPLICATE
            # Same broker timestamp carrying different price is ambiguous.
            # Preserve the first admitted fact instead of guessing ordering.
            return QuoteUpdateResult.STALE_IGNORED

        self._quotes[quote.symbol] = quote
        return QuoteUpdateResult.APPLIED

    def latest(
        self,
        symbol: str,
        *,
        now: datetime,
        max_age_seconds: int,
    ) -> MarketQuote:
        if not isinstance(symbol, str) or not symbol.strip():
            raise ValueError("symbol must be a non-empty string")
        _require_aware("now", now)
        if isinstance(max_age_seconds, bool) or not isinstance(max_age_seconds, int):
            raise TypeError("max_age_seconds must be int")
        if max_age_seconds <= 0:
            raise ValueError("max_age_seconds must be > 0")

        quote = self._quotes.get(symbol)
        if quote is None:
            raise MarketDataUnavailable(f"no quote for {symbol}")

        if quote.broker_time > now:
            raise MarketDataStale(f"broker timestamp for {symbol} is in the future")
        if quote.observed_at > now:
            raise MarketDataStale(f"local observation for {symbol} is in the future")

        max_age = timedelta(seconds=max_age_seconds)
        if now - quote.broker_time > max_age:
            raise MarketDataStale(f"broker quote for {symbol} is stale")
        if now - quote.observed_at > max_age:
            raise MarketDataStale(f"local observation for {symbol} is stale")

        return quote

    def clear(self) -> None:
        self._quotes.clear()

    def symbols(self) -> tuple[str, ...]:
        return tuple(sorted(self._quotes))

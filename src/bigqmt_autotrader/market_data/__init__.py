"""Host-side normalized market-data boundary."""

from .models import MarketQuote, QuoteUpdateResult
from .qmt_adapter import (
    QmtMarketDataAdapter,
    QmtMarketDataError,
    QmtTickIngestResult,
    QmtTickRejection,
)
from .service import (
    MarketDataError,
    MarketDataService,
    MarketDataUnavailable,
    MarketDataStale,
)

__all__ = [
    "MarketQuote",
    "QmtMarketDataAdapter",
    "QmtMarketDataError",
    "QmtTickIngestResult",
    "QmtTickRejection",
    "QuoteUpdateResult",
    "MarketDataError",
    "MarketDataUnavailable",
    "MarketDataStale",
    "MarketDataService",
]

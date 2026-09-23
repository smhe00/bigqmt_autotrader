from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from bigqmt_autotrader.qmt.protocol import QmtEvent

from .models import MarketQuote, QuoteUpdateResult
from .service import MarketDataService


class QmtMarketDataError(ValueError):
    pass


@dataclass(frozen=True)
class QmtTickRejection:
    symbol: str | None
    reason: str


@dataclass(frozen=True)
class QmtTickIngestResult:
    applied: int
    duplicate: int
    stale_ignored: int
    unobserved: int
    rejections: tuple[QmtTickRejection, ...]


def _epoch_ms(value: Any, *, name: str) -> datetime:
    if isinstance(value, bool):
        raise QmtMarketDataError(f"{name} must be epoch milliseconds")
    try:
        numeric = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise QmtMarketDataError(f"{name} must be epoch milliseconds") from exc
    if not numeric.is_finite() or numeric != numeric.to_integral_value() or numeric < Decimal("1000000000000"):
        raise QmtMarketDataError(f"{name} must be a 13-digit-or-later epoch-ms value")
    return datetime.fromtimestamp(int(numeric) / 1000.0, tz=timezone.utc)


def _positive_decimal(value: Any, *, name: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise QmtMarketDataError(f"{name} must be decimal-compatible") from exc
    if not result.is_finite() or result <= 0:
        raise QmtMarketDataError(f"{name} must be finite and > 0")
    return result


class QmtMarketDataAdapter:
    """Admit strict exact-symbol QMT tick evidence into MarketDataService.

    The adapter accepts only the bound account and terminal identity. Broker
    timestamp freshness remains authoritative after ingestion; a recent bridge
    observation cannot freshen an old broker tick.
    """

    def __init__(
        self,
        *,
        market_data: MarketDataService,
        expected_account_fingerprint: str,
        expected_terminal_instance_id: str,
    ) -> None:
        if not isinstance(market_data, MarketDataService):
            raise TypeError("market_data must be MarketDataService")
        if not isinstance(expected_account_fingerprint, str) or not expected_account_fingerprint:
            raise ValueError("expected_account_fingerprint must be non-empty")
        if not isinstance(expected_terminal_instance_id, str) or not expected_terminal_instance_id:
            raise ValueError("expected_terminal_instance_id must be non-empty")
        self._market_data = market_data
        self._account_fingerprint = expected_account_fingerprint
        self._terminal_instance_id = expected_terminal_instance_id

    def ingest(self, event: QmtEvent) -> QmtTickIngestResult:
        if not isinstance(event, QmtEvent):
            raise TypeError("event must be QmtEvent")
        if event.event_type != "instrument_tick_capabilities":
            raise QmtMarketDataError("event_type must be instrument_tick_capabilities")
        if event.account_fingerprint != self._account_fingerprint:
            raise QmtMarketDataError("account fingerprint mismatch")
        if event.terminal_instance_id != self._terminal_instance_id:
            raise QmtMarketDataError("terminal instance mismatch")

        applied = 0
        duplicate = 0
        stale_ignored = 0
        unobserved = 0
        rejections: list[QmtTickRejection] = []

        for record in event.payload["candidates"]:
            symbol = record.get("symbol")
            if record.get("tick_observed") is not True:
                unobserved += 1
                continue
            try:
                quote = self._normalize_candidate(record, event)
            except QmtMarketDataError as exc:
                rejections.append(
                    QmtTickRejection(
                        symbol=symbol if isinstance(symbol, str) else None,
                        reason=str(exc),
                    )
                )
                continue
            result = self._market_data.ingest(quote)
            if result is QuoteUpdateResult.APPLIED:
                applied += 1
            elif result is QuoteUpdateResult.DUPLICATE:
                duplicate += 1
            elif result is QuoteUpdateResult.STALE_IGNORED:
                stale_ignored += 1

        return QmtTickIngestResult(
            applied=applied,
            duplicate=duplicate,
            stale_ignored=stale_ignored,
            unobserved=unobserved,
            rejections=tuple(rejections),
        )

    def _normalize_candidate(
        self,
        record: Mapping[str, Any],
        event: QmtEvent,
    ) -> MarketQuote:
        symbol = record.get("symbol")
        if not isinstance(symbol, str) or not symbol:
            raise QmtMarketDataError("candidate symbol must be non-empty")

        evidence = record.get("evidence")
        if not isinstance(evidence, Mapping):
            raise QmtMarketDataError("observed candidate requires evidence")
        if evidence.get("exact_symbol") is not True:
            raise QmtMarketDataError("tick evidence is not exact-symbol")
        if evidence.get("requested_symbol") != symbol:
            raise QmtMarketDataError("requested symbol mismatch")
        if evidence.get("reported_symbol") != symbol:
            raise QmtMarketDataError("reported symbol mismatch")

        broker_time = _epoch_ms(evidence.get("tick_time"), name="tick_time")
        callback_ms = record.get("last_callback_ms")
        observed_at = _epoch_ms(
            callback_ms if callback_ms is not None else event.timestamp_ms,
            name="last_callback_ms",
        )
        last_price = _positive_decimal(
            evidence.get("last_price"),
            name="last_price",
        )
        evidence_source = record.get("evidence_source")
        if not isinstance(evidence_source, str) or not evidence_source:
            evidence_source = event.source

        return MarketQuote(
            symbol=symbol,
            last_price=last_price,
            broker_time=broker_time,
            observed_at=observed_at,
            source=f"qmt:{self._terminal_instance_id}:{evidence_source}",
        )

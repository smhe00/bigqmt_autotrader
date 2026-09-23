from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from bigqmt_autotrader.market_data import (
    MarketDataService,
    QmtMarketDataAdapter,
    QmtMarketDataError,
)
from bigqmt_autotrader.qmt import QmtEvent


FP = "sha256:" + "a" * 64
TZ = timezone(timedelta(hours=8))
NOW = datetime(2026, 9, 23, 14, 0, tzinfo=TZ)
NOW_MS = int(NOW.timestamp() * 1000)


def tick_event(
    *,
    symbol="01810.SGT",
    tick_time_ms=NOW_MS - 1000,
    callback_ms=NOW_MS,
    price="26.600",
    exact=True,
    terminal="guojin_sim",
    account=FP,
    tick_observed=True,
    source="snapshot_tick_refresh",
):
    evidence = {
        "requested_symbol": symbol,
        "reported_symbol": symbol if exact else "01810.HK",
        "exact_symbol": exact,
        "tick_time": tick_time_ms,
        "last_price": price,
    }
    return QmtEvent.from_mapping(
        {
            "protocol_version": "0.2",
            "session_id": "session-1",
            "sequence": 10,
            "timestamp_ms": NOW_MS,
            "event_type": "instrument_tick_capabilities",
            "source": source,
            "account_fingerprint": account,
            "account_type": "STOCK",
            "terminal_instance_id": terminal,
            "payload": {
                "candidates": [
                    {
                        "symbol": symbol,
                        "tick_observed": tick_observed,
                        "callback_count": 2 if tick_observed else 0,
                        "last_callback_ms": callback_ms,
                        "evidence_source": source,
                        "evidence": evidence,
                    }
                ],
                "observed_count": 1 if tick_observed else 0,
                "window_seconds": 5,
                "final": False,
            },
        }
    )


def adapter(service=None):
    service = service or MarketDataService()
    return service, QmtMarketDataAdapter(
        market_data=service,
        expected_account_fingerprint=FP,
        expected_terminal_instance_id="guojin_sim",
    )


def test_exact_qmt_tick_enters_market_data_service():
    service, ingest = adapter()

    result = ingest.ingest(tick_event())
    quote = service.latest("01810.SGT", now=NOW, max_age_seconds=5)

    assert result.applied == 1
    assert result.rejections == ()
    assert quote.last_price == Decimal("26.600")
    assert quote.broker_time == NOW - timedelta(seconds=1)
    assert quote.observed_at == NOW
    assert quote.source == "qmt:guojin_sim:snapshot_tick_refresh"


def test_account_and_terminal_identity_are_hard_boundaries():
    _, ingest = adapter()

    with pytest.raises(QmtMarketDataError, match="account fingerprint"):
        ingest.ingest(tick_event(account="sha256:" + "b" * 64))
    with pytest.raises(QmtMarketDataError, match="terminal instance"):
        ingest.ingest(tick_event(terminal="guojin"))


def test_non_exact_symbol_is_rejected_without_polluting_cache():
    service, ingest = adapter()

    result = ingest.ingest(tick_event(exact=False))

    assert result.applied == 0
    assert len(result.rejections) == 1
    assert service.symbols() == ()


def test_recent_callback_cannot_freshen_old_broker_tick():
    service, ingest = adapter()
    ingest.ingest(
        tick_event(
            tick_time_ms=NOW_MS - 24 * 60 * 60 * 1000,
            callback_ms=NOW_MS,
        )
    )

    from bigqmt_autotrader.market_data import MarketDataStale

    with pytest.raises(MarketDataStale, match="broker quote"):
        service.latest("01810.SGT", now=NOW, max_age_seconds=5)


def test_unobserved_candidate_is_ignored_not_rejected():
    service, ingest = adapter()

    result = ingest.ingest(tick_event(tick_observed=False))

    assert result.unobserved == 1
    assert result.rejections == ()
    assert service.symbols() == ()


def test_older_qmt_tick_cannot_replace_newer_quote():
    service, ingest = adapter()
    newer = tick_event(tick_time_ms=NOW_MS - 1000, price="26.60")
    older = tick_event(
        tick_time_ms=NOW_MS - 2000,
        callback_ms=NOW_MS + 100,
        price="26.50",
    )

    assert ingest.ingest(newer).applied == 1
    result = ingest.ingest(older)

    assert result.stale_ignored == 1
    assert service.latest("01810.SGT", now=NOW, max_age_seconds=5).last_price == Decimal("26.60")


@pytest.mark.parametrize("bad_time", [123, "not-time", None])
def test_ambiguous_tick_timestamp_is_rejected(bad_time):
    service, ingest = adapter()

    result = ingest.ingest(tick_event(tick_time_ms=bad_time))

    assert result.applied == 0
    assert len(result.rejections) == 1
    assert service.symbols() == ()

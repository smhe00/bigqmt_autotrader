from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from bigqmt_autotrader.oms import connect_database, initialize_database
from bigqmt_autotrader.risk import (
    DailyRiskFactConflict,
    DailyRiskLedger,
    DailyRiskSnapshotUnavailable,
)


TZ = timezone(timedelta(hours=8))
DAY = date(2026, 9, 23)
NOW = datetime(2026, 9, 23, 10, 0, tzinfo=TZ)


def ledger(tmp_path):
    conn = connect_database(tmp_path / "risk.sqlite3")
    initialize_database(conn)
    return conn, DailyRiskLedger(conn)


def test_daily_accounting_is_idempotent_and_decimal_exact(tmp_path):
    conn, store = ledger(tmp_path)
    common = dict(
        account_fingerprint="acct", strategy_id="s1", trading_date=DAY, observed_at=NOW
    )
    assert store.record_order_submit(event_key="submit-1", source_ref="cmd-1", **common)
    assert not store.record_order_submit(event_key="submit-1", source_ref="cmd-1", **common)
    assert store.record_cancel_request(event_key="cancel-1", source_ref="cmd-c1", **common)
    assert store.record_trade(
        event_key="trade-1", notional=Decimal("0.1"), source_ref="deal-1", **common
    )
    assert store.record_trade(
        event_key="trade-2", notional=Decimal("0.2"), source_ref="deal-2", **common
    )
    assert store.record_pnl_snapshot(
        snapshot_key="pnl-1", account_fingerprint="acct", trading_date=DAY,
        daily_pnl=Decimal("-12.34"), observed_at=NOW, source="account_query"
    )

    totals = store.totals(account_fingerprint="acct", trading_date=DAY)

    assert totals.daily_turnover == Decimal("0.3")
    assert totals.daily_order_count == 1
    assert totals.daily_cancel_count == 1
    assert totals.daily_pnl == Decimal("-12.34")
    assert store.strategy_turnover(account_fingerprint="acct", strategy_id="s1", trading_date=DAY) == Decimal("0.3")
    conn.close()


def test_daily_accounting_survives_database_restart(tmp_path):
    path = tmp_path / "restart.sqlite3"
    conn = connect_database(path)
    initialize_database(conn)
    first = DailyRiskLedger(conn)
    first.record_order_submit(
        event_key="submit-1", account_fingerprint="acct", strategy_id="s1",
        trading_date=DAY, observed_at=NOW, source_ref="cmd-1"
    )
    first.record_trade(
        event_key="trade-1", account_fingerprint="acct", strategy_id="s1",
        trading_date=DAY, notional=Decimal("464"), observed_at=NOW, source_ref="deal-1"
    )
    first.record_pnl_snapshot(
        snapshot_key="pnl-1", account_fingerprint="acct", trading_date=DAY,
        daily_pnl=Decimal("8.5"), observed_at=NOW, source="account_query"
    )
    conn.close()

    conn = connect_database(path)
    initialize_database(conn)
    second = DailyRiskLedger(conn)
    totals = second.totals(account_fingerprint="acct", trading_date=DAY)
    assert totals.daily_order_count == 1
    assert totals.daily_turnover == Decimal("464")
    assert totals.daily_pnl == Decimal("8.5")
    assert not second.record_trade(
        event_key="trade-1", account_fingerprint="acct", strategy_id="s1",
        trading_date=DAY, notional=Decimal("464"), observed_at=NOW, source_ref="deal-1"
    )


def test_reused_event_identity_with_different_fact_fails_closed(tmp_path):
    _, store = ledger(tmp_path)
    store.record_trade(
        event_key="trade-1", account_fingerprint="acct", strategy_id="s1",
        trading_date=DAY, notional=Decimal("100"), observed_at=NOW, source_ref="deal-1"
    )
    with pytest.raises(DailyRiskFactConflict):
        store.record_trade(
            event_key="trade-1", account_fingerprint="acct", strategy_id="s1",
            trading_date=DAY, notional=Decimal("101"), observed_at=NOW, source_ref="deal-1"
        )


def test_latest_pnl_uses_authoritative_observation_time_not_insert_order(tmp_path):
    _, store = ledger(tmp_path)
    later = NOW + timedelta(minutes=1)
    store.record_pnl_snapshot(
        snapshot_key="pnl-later", account_fingerprint="acct", trading_date=DAY,
        daily_pnl=Decimal("20"), observed_at=later, source="account_query"
    )
    store.record_pnl_snapshot(
        snapshot_key="pnl-earlier", account_fingerprint="acct", trading_date=DAY,
        daily_pnl=Decimal("10"), observed_at=NOW, source="account_query"
    )

    totals = store.totals(account_fingerprint="acct", trading_date=DAY)
    assert totals.daily_pnl == Decimal("20")
    assert totals.pnl_observed_at == later.astimezone(timezone.utc)


def test_same_pnl_timestamp_with_different_identity_fails_closed(tmp_path):
    _, store = ledger(tmp_path)
    store.record_pnl_snapshot(
        snapshot_key="pnl-1", account_fingerprint="acct", trading_date=DAY,
        daily_pnl=Decimal("10"), observed_at=NOW, source="account_query"
    )
    with pytest.raises(DailyRiskFactConflict):
        store.record_pnl_snapshot(
            snapshot_key="pnl-2", account_fingerprint="acct", trading_date=DAY,
            daily_pnl=Decimal("11"), observed_at=NOW, source="account_query"
        )


def test_missing_pnl_snapshot_fails_closed(tmp_path):
    _, store = ledger(tmp_path)
    with pytest.raises(DailyRiskSnapshotUnavailable):
        store.totals(account_fingerprint="acct", trading_date=DAY)


def test_write_guard_runs_inside_transaction(tmp_path):
    _, store = ledger(tmp_path)
    calls = []
    store.bind_write_guard(lambda: calls.append(True))
    store.record_order_submit(
        event_key="submit-1", account_fingerprint="acct", strategy_id="s1",
        trading_date=DAY, observed_at=NOW, source_ref="cmd-1"
    )
    assert calls == [True]

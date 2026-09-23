from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Callable, Iterator


class DailyRiskFactConflict(RuntimeError):
    pass


class DailyRiskSnapshotUnavailable(RuntimeError):
    pass


class DailyRiskEventType(str, Enum):
    ORDER_SUBMIT = "ORDER_SUBMIT"
    CANCEL_REQUEST = "CANCEL_REQUEST"
    TRADE = "TRADE"


@dataclass(frozen=True)
class DailyRiskTotals:
    account_fingerprint: str
    trading_date: date
    daily_pnl: Decimal
    daily_turnover: Decimal
    daily_order_count: int
    daily_cancel_count: int
    pnl_observed_at: datetime


def _require_nonempty(name: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


def _require_aware(name: str, value: datetime) -> None:
    if not isinstance(value, datetime):
        raise TypeError(f"{name} must be datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def _require_decimal(name: str, value: Decimal, *, positive: bool = False) -> None:
    if not isinstance(value, Decimal):
        raise TypeError(f"{name} must be decimal.Decimal; binary float is forbidden")
    if not value.is_finite():
        raise ValueError(f"{name} must be finite")
    if positive and value <= 0:
        raise ValueError(f"{name} must be > 0")


def _require_date(value: date) -> None:
    if not isinstance(value, date) or isinstance(value, datetime):
        raise TypeError("trading_date must be datetime.date")


def _utc_iso(value: datetime) -> str:
    _require_aware("observed_at", value)
    return value.astimezone(timezone.utc).isoformat()


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    _require_aware("stored observed_at", parsed)
    return parsed.astimezone(timezone.utc)


@contextmanager
def _transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.rollback()
        raise
    else:
        conn.commit()


class DailyRiskLedger:
    """Durable, replay-safe daily risk accounting.

    Callers must use durable upstream identities for ``event_key`` and
    ``snapshot_key`` (for example QMT command/trade/account-snapshot IDs).
    Replaying the same fact is a no-op; reusing an identity with different
    semantics fails closed.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        if not isinstance(conn, sqlite3.Connection):
            raise TypeError("conn must be sqlite3.Connection")
        self.conn = conn
        self._write_guard: Callable[[], None] | None = None

    def bind_write_guard(self, write_guard: Callable[[], None]) -> None:
        if not callable(write_guard):
            raise TypeError("write_guard must be callable")
        self._write_guard = write_guard

    def _guard_write_in_tx(self) -> None:
        if not self.conn.in_transaction:
            raise RuntimeError("write guard requires an active transaction")
        if self._write_guard is not None:
            self._write_guard()

    def record_order_submit(
        self,
        *,
        event_key: str,
        account_fingerprint: str,
        strategy_id: str,
        trading_date: date,
        observed_at: datetime,
        source_ref: str,
    ) -> bool:
        return self._record_event(
            event_key=event_key,
            account_fingerprint=account_fingerprint,
            strategy_id=strategy_id,
            trading_date=trading_date,
            event_type=DailyRiskEventType.ORDER_SUBMIT,
            notional=Decimal("0"),
            observed_at=observed_at,
            source_ref=source_ref,
        )

    def record_cancel_request(
        self,
        *,
        event_key: str,
        account_fingerprint: str,
        strategy_id: str,
        trading_date: date,
        observed_at: datetime,
        source_ref: str,
    ) -> bool:
        return self._record_event(
            event_key=event_key,
            account_fingerprint=account_fingerprint,
            strategy_id=strategy_id,
            trading_date=trading_date,
            event_type=DailyRiskEventType.CANCEL_REQUEST,
            notional=Decimal("0"),
            observed_at=observed_at,
            source_ref=source_ref,
        )

    def record_trade(
        self,
        *,
        event_key: str,
        account_fingerprint: str,
        strategy_id: str,
        trading_date: date,
        notional: Decimal,
        observed_at: datetime,
        source_ref: str,
    ) -> bool:
        _require_decimal("notional", notional, positive=True)
        return self._record_event(
            event_key=event_key,
            account_fingerprint=account_fingerprint,
            strategy_id=strategy_id,
            trading_date=trading_date,
            event_type=DailyRiskEventType.TRADE,
            notional=notional,
            observed_at=observed_at,
            source_ref=source_ref,
        )

    def _record_event(
        self,
        *,
        event_key: str,
        account_fingerprint: str,
        strategy_id: str,
        trading_date: date,
        event_type: DailyRiskEventType,
        notional: Decimal,
        observed_at: datetime,
        source_ref: str,
    ) -> bool:
        _require_nonempty("event_key", event_key)
        _require_nonempty("account_fingerprint", account_fingerprint)
        _require_nonempty("strategy_id", strategy_id)
        _require_date(trading_date)
        _require_decimal("notional", notional)
        _require_aware("observed_at", observed_at)
        _require_nonempty("source_ref", source_ref)
        identity = (
            account_fingerprint,
            strategy_id,
            trading_date.isoformat(),
            event_type.value,
            str(notional),
            _utc_iso(observed_at),
            source_ref,
        )
        with _transaction(self.conn):
            self._guard_write_in_tx()
            row = self.conn.execute(
                "SELECT account_fingerprint, strategy_id, trading_date, event_type, "
                "notional, observed_at, source_ref FROM daily_risk_events WHERE event_key=?",
                (event_key,),
            ).fetchone()
            if row is not None:
                stored = tuple(row)
                if stored != identity:
                    raise DailyRiskFactConflict("conflicting daily risk event identity")
                return False
            self.conn.execute(
                """
                INSERT INTO daily_risk_events(
                    event_key, account_fingerprint, strategy_id, trading_date,
                    event_type, notional, observed_at, source_ref
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (event_key,) + identity,
            )
            return True

    def record_pnl_snapshot(
        self,
        *,
        snapshot_key: str,
        account_fingerprint: str,
        trading_date: date,
        daily_pnl: Decimal,
        observed_at: datetime,
        source: str,
    ) -> bool:
        _require_nonempty("snapshot_key", snapshot_key)
        _require_nonempty("account_fingerprint", account_fingerprint)
        _require_date(trading_date)
        _require_decimal("daily_pnl", daily_pnl)
        _require_aware("observed_at", observed_at)
        _require_nonempty("source", source)
        identity = (
            account_fingerprint,
            trading_date.isoformat(),
            str(daily_pnl),
            _utc_iso(observed_at),
            source,
        )
        with _transaction(self.conn):
            self._guard_write_in_tx()
            row = self.conn.execute(
                """
                SELECT snapshot_key, account_fingerprint, trading_date, daily_pnl, observed_at, source
                FROM daily_risk_pnl_snapshots
                WHERE snapshot_key=? OR (account_fingerprint=? AND trading_date=? AND observed_at=?)
                """,
                (snapshot_key, account_fingerprint, trading_date.isoformat(), _utc_iso(observed_at)),
            ).fetchone()
            if row is not None:
                stored_identity = tuple(row)[1:]
                if row[0] != snapshot_key or stored_identity != identity:
                    raise DailyRiskFactConflict("conflicting daily PnL snapshot identity")
                return False
            self.conn.execute(
                """
                INSERT INTO daily_risk_pnl_snapshots(
                    snapshot_key, account_fingerprint, trading_date, daily_pnl, observed_at, source
                ) VALUES(?, ?, ?, ?, ?, ?)
                """,
                (snapshot_key,) + identity,
            )
            return True

    def totals(self, *, account_fingerprint: str, trading_date: date) -> DailyRiskTotals:
        _require_nonempty("account_fingerprint", account_fingerprint)
        _require_date(trading_date)
        date_text = trading_date.isoformat()
        rows = self.conn.execute(
            """
            SELECT event_type, notional FROM daily_risk_events
            WHERE account_fingerprint=? AND trading_date=?
            """,
            (account_fingerprint, date_text),
        ).fetchall()
        turnover = Decimal("0")
        order_count = 0
        cancel_count = 0
        for row in rows:
            event_type = row["event_type"]
            if event_type == DailyRiskEventType.TRADE.value:
                turnover += Decimal(row["notional"])
            elif event_type == DailyRiskEventType.ORDER_SUBMIT.value:
                order_count += 1
            elif event_type == DailyRiskEventType.CANCEL_REQUEST.value:
                cancel_count += 1

        pnl_row = self.conn.execute(
            """
            SELECT daily_pnl, observed_at FROM daily_risk_pnl_snapshots
            WHERE account_fingerprint=? AND trading_date=?
            ORDER BY observed_at DESC, snapshot_key DESC LIMIT 1
            """,
            (account_fingerprint, date_text),
        ).fetchone()
        if pnl_row is None:
            raise DailyRiskSnapshotUnavailable(
                f"no daily PnL snapshot for {account_fingerprint} on {date_text}"
            )

        return DailyRiskTotals(
            account_fingerprint=account_fingerprint,
            trading_date=trading_date,
            daily_pnl=Decimal(pnl_row["daily_pnl"]),
            daily_turnover=turnover,
            daily_order_count=order_count,
            daily_cancel_count=cancel_count,
            pnl_observed_at=_parse_utc(pnl_row["observed_at"]),
        )

    def strategy_turnover(
        self,
        *,
        account_fingerprint: str,
        strategy_id: str,
        trading_date: date,
    ) -> Decimal:
        _require_nonempty("account_fingerprint", account_fingerprint)
        _require_nonempty("strategy_id", strategy_id)
        _require_date(trading_date)
        rows = self.conn.execute(
            """
            SELECT notional FROM daily_risk_events
            WHERE account_fingerprint=? AND strategy_id=? AND trading_date=? AND event_type='TRADE'
            """,
            (account_fingerprint, strategy_id, trading_date.isoformat()),
        ).fetchall()
        return sum((Decimal(row["notional"]) for row in rows), Decimal("0"))

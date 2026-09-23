from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from enum import Enum
from zoneinfo import ZoneInfo


class TradingCalendarError(RuntimeError):
    pass


class TradingDateUnknown(TradingCalendarError):
    pass


class TradingSessionClosed(TradingCalendarError):
    pass


class Market(str, Enum):
    A_SHARE = "A_SHARE"
    HUGANGTONG = "HUGANGTONG"
    SHENGANGTONG = "SHENGANGTONG"


@dataclass(frozen=True, order=True)
class SessionWindow:
    start: time
    end: time

    def __post_init__(self) -> None:
        if not isinstance(self.start, time) or not isinstance(self.end, time):
            raise TypeError("start/end must be datetime.time")
        if self.start.tzinfo is not None or self.end.tzinfo is not None:
            raise ValueError("session window times must be timezone-naive local clock times")
        if self.start >= self.end:
            raise ValueError("session window start must be before end")

    def contains(self, value: time) -> bool:
        if value.tzinfo is not None:
            value = value.replace(tzinfo=None)
        return self.start <= value < self.end


@dataclass(frozen=True)
class TradingDaySchedule:
    trading_date: date
    market: Market
    windows: tuple[SessionWindow, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.trading_date, date) or isinstance(self.trading_date, datetime):
            raise TypeError("trading_date must be datetime.date")
        if not isinstance(self.market, Market):
            raise TypeError("market must be Market")
        if not isinstance(self.windows, tuple) or not self.windows:
            raise ValueError("windows must be a non-empty tuple")
        if not all(isinstance(item, SessionWindow) for item in self.windows):
            raise TypeError("windows must contain SessionWindow values")
        ordered = tuple(sorted(self.windows))
        if ordered != self.windows:
            raise ValueError("windows must be sorted")
        for previous, current in zip(self.windows, self.windows[1:]):
            if previous.end > current.start:
                raise ValueError("session windows may not overlap")


@dataclass(frozen=True)
class TradingSessionStatus:
    market: Market
    trading_date: date
    local_time: time
    known_trading_date: bool
    open: bool
    active_window: SessionWindow | None


class TradingCalendar:
    """Explicit configured trading calendar; unknown dates fail closed.

    No holiday assumptions or weekday inference are made here. Deployment
    configuration must explicitly supply each market/date schedule.
    """

    def __init__(
        self,
        *,
        timezone_name: str,
        schedules: tuple[TradingDaySchedule, ...],
    ) -> None:
        if not isinstance(timezone_name, str) or not timezone_name:
            raise ValueError("timezone_name must be non-empty")
        self.timezone = ZoneInfo(timezone_name)
        self._schedules: dict[tuple[Market, date], TradingDaySchedule] = {}
        for schedule in schedules:
            if not isinstance(schedule, TradingDaySchedule):
                raise TypeError("schedules must contain TradingDaySchedule")
            key = (schedule.market, schedule.trading_date)
            if key in self._schedules:
                raise ValueError(f"duplicate schedule for {schedule.market.value} {schedule.trading_date}")
            self._schedules[key] = schedule

    def status(self, market: Market, *, now: datetime) -> TradingSessionStatus:
        if not isinstance(market, Market):
            raise TypeError("market must be Market")
        if not isinstance(now, datetime):
            raise TypeError("now must be datetime")
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        local = now.astimezone(self.timezone)
        schedule = self._schedules.get((market, local.date()))
        if schedule is None:
            return TradingSessionStatus(
                market=market,
                trading_date=local.date(),
                local_time=local.timetz().replace(tzinfo=None),
                known_trading_date=False,
                open=False,
                active_window=None,
            )
        local_time = local.timetz().replace(tzinfo=None)
        active = next((window for window in schedule.windows if window.contains(local_time)), None)
        return TradingSessionStatus(
            market=market,
            trading_date=local.date(),
            local_time=local_time,
            known_trading_date=True,
            open=active is not None,
            active_window=active,
        )

    def require_open(self, market: Market, *, now: datetime) -> TradingSessionStatus:
        status = self.status(market, now=now)
        if not status.known_trading_date:
            raise TradingDateUnknown(
                f"no configured {market.value} schedule for {status.trading_date.isoformat()}"
            )
        if not status.open:
            raise TradingSessionClosed(
                f"{market.value} session is closed at {status.local_time.isoformat()}"
            )
        return status

    def configured_dates(self, market: Market) -> tuple[date, ...]:
        if not isinstance(market, Market):
            raise TypeError("market must be Market")
        return tuple(
            sorted(day for configured_market, day in self._schedules if configured_market is market)
        )

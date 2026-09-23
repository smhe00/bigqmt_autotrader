from datetime import date, datetime, time, timedelta, timezone

import pytest

from bigqmt_autotrader.service import (
    Market,
    SessionWindow,
    TradingCalendar,
    TradingDateUnknown,
    TradingDaySchedule,
    TradingSessionClosed,
)


CST = timezone(timedelta(hours=8))
DAY = date(2026, 9, 23)


def schedule(market, windows):
    return TradingDaySchedule(
        trading_date=DAY,
        market=market,
        windows=tuple(SessionWindow(time(*start), time(*end)) for start, end in windows),
    )


def calendar():
    return TradingCalendar(
        timezone_name="Asia/Shanghai",
        schedules=(
            schedule(
                Market.A_SHARE,
                (
                    ((9, 30), (11, 30)),
                    ((13, 0), (15, 0)),
                ),
            ),
            schedule(
                Market.HUGANGTONG,
                (
                    ((9, 30), (12, 0)),
                    ((13, 0), (16, 0)),
                ),
            ),
        ),
    )


def at(hour, minute):
    return datetime(2026, 9, 23, hour, minute, tzinfo=CST)


def test_a_share_lunch_break_is_closed():
    status = calendar().status(Market.A_SHARE, now=at(12, 0))
    assert status.known_trading_date
    assert not status.open
    with pytest.raises(TradingSessionClosed):
        calendar().require_open(Market.A_SHARE, now=at(12, 0))


def test_session_start_is_inclusive_and_end_is_exclusive():
    assert calendar().require_open(Market.A_SHARE, now=at(9, 30)).open
    with pytest.raises(TradingSessionClosed):
        calendar().require_open(Market.A_SHARE, now=at(11, 30))
    assert calendar().require_open(Market.A_SHARE, now=at(13, 0)).open
    with pytest.raises(TradingSessionClosed):
        calendar().require_open(Market.A_SHARE, now=at(15, 0))


def test_unknown_date_fails_closed_instead_of_assuming_weekday_is_open():
    next_day = datetime(2026, 9, 24, 10, 0, tzinfo=CST)
    status = calendar().status(Market.A_SHARE, now=next_day)
    assert not status.known_trading_date
    assert not status.open
    with pytest.raises(TradingDateUnknown):
        calendar().require_open(Market.A_SHARE, now=next_day)


def test_stock_connect_calendar_is_independent_from_a_share_calendar():
    value = calendar()
    assert not value.status(Market.A_SHARE, now=at(15, 30)).open
    assert value.require_open(Market.HUGANGTONG, now=at(15, 30)).open
    with pytest.raises(TradingDateUnknown):
        value.require_open(Market.SHENGANGTONG, now=at(10, 0))


def test_timezone_conversion_is_explicit():
    # 01:30 UTC is 09:30 Asia/Shanghai.
    utc = datetime(2026, 9, 23, 1, 30, tzinfo=timezone.utc)
    assert calendar().require_open(Market.A_SHARE, now=utc).open


def test_overlapping_windows_are_rejected():
    with pytest.raises(ValueError, match="overlap"):
        TradingDaySchedule(
            trading_date=DAY,
            market=Market.A_SHARE,
            windows=(
                SessionWindow(time(9, 30), time(11, 30)),
                SessionWindow(time(11, 0), time(12, 0)),
            ),
        )

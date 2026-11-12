"""Market calendar and session times for the wave setup strategy."""

from datetime import datetime, time, timedelta

import pandas as pd
import pytz
from pandas.tseries.holiday import (
    AbstractHolidayCalendar,
    Holiday,
    USMartinLutherKingJr,
    USPresidentsDay,
    nearest_workday,
)

from alpha_tech_tracker.op_momentum_strategy.contract_selector import _NYSEHolidayCalendar

ET = pytz.timezone("America/New_York")
MARKET_OPEN = time(9, 30)
PRE_OPEN_ALERT = time(9, 25)
REGULAR_CLOSE = time(16, 0)
EARLY_CLOSE = time(13, 0)
AFTER_CLOSE_MINUTES = 5
BAR_MINUTES = 5


def _now_et():
    return datetime.now(ET)


class _MarketHolidayCalendar(AbstractHolidayCalendar):
    """The repo's NYSE calendar plus the holidays it lacks (MLK, Presidents' Day, Juneteenth)."""

    rules = _NYSEHolidayCalendar.rules + [
        USMartinLutherKingJr,
        USPresidentsDay,
        Holiday("Juneteenth", month=6, day=19, start_date="2022-01-01", observance=nearest_workday),
    ]


_HOLIDAYS = _MarketHolidayCalendar()


def is_trading_day(day):
    if day.weekday() >= 5:
        return False
    return pd.Timestamp(day) not in _HOLIDAYS.holidays(start=f"{day.year}-01-01", end=f"{day.year}-12-31")


def previous_trading_day(day):
    day -= timedelta(days=1)
    while not is_trading_day(day):
        day -= timedelta(days=1)
    return day


def session_close(day):
    """13:00 on NYSE early-close days (July 3 Mon-Thu, the day after Thanksgiving, Dec 24 on a
    trading day), else 16:00."""
    if day.month == 7 and day.day == 3 and day.weekday() <= 3:
        return EARLY_CLOSE
    if day.month == 11 and day.weekday() == 4 and 23 <= day.day <= 29:
        return EARLY_CLOSE
    if day.month == 12 and day.day == 24 and is_trading_day(day):
        return EARLY_CLOSE
    return REGULAR_CLOSE


def period_start(timestamp):
    return timestamp.replace(second=0, microsecond=0) - timedelta(minutes=timestamp.minute % BAR_MINUTES)

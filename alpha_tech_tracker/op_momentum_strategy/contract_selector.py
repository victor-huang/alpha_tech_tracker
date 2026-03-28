import logging
from datetime import date, timedelta
from decimal import ROUND_HALF_UP

import pandas as pd
import pytz
from pandas.tseries.holiday import (
    AbstractHolidayCalendar,
    GoodFriday,
    Holiday,
    USLaborDay,
    USMemorialDay,
    USThanksgivingDay,
    nearest_workday,
)

from alpha_tech_tracker.trade_api.alpaca_client.client import AlpacaAPIClient

from .config import STRIKE_CALL_OFFSET, STRIKE_PUT_OFFSET
from .models import _D

logger = logging.getLogger(__name__)

ET = pytz.timezone("America/New_York")


class _NYSEHolidayCalendar(AbstractHolidayCalendar):
    rules = [
        Holiday("New Year's Day", month=1, day=1, observance=nearest_workday),
        GoodFriday,
        USMemorialDay,
        Holiday("Independence Day", month=7, day=4, observance=nearest_workday),
        USLaborDay,
        USThanksgivingDay,
        Holiday("Christmas Day", month=12, day=25, observance=nearest_workday),
    ]


_NYSE_CAL = _NYSEHolidayCalendar()


def _is_nyse_holiday(d: date) -> bool:
    holidays = _NYSE_CAL.holidays(start=f"{d.year}-01-01", end=f"{d.year}-12-31")
    return pd.Timestamp(d) in holidays


def _today() -> date:
    return date.today()


def _next_friday(ref_date: date) -> date:
    days_ahead = 4 - ref_date.weekday()
    if days_ahead <= 0:
        days_ahead += 7
    return ref_date + timedelta(days=days_ahead)


def _strike_increment(price) -> object:
    from decimal import Decimal

    price = _D(price)
    if price < _D("50"):
        return _D("1")
    if price <= _D("200"):
        return _D("5")
    return _D("10")


class OptionContractSelector:
    """Finds the nearest weekly option contract matching the signal."""

    def __init__(self, alpaca_client: AlpacaAPIClient):
        self._client = alpaca_client

    def select(self, ticker: str, signal: str, stock_price: float) -> str:
        stock_price = _D(stock_price)
        incr = _strike_increment(stock_price)
        if signal == "BULLISH":
            raw = (stock_price * STRIKE_CALL_OFFSET).quantize(
                incr, rounding=ROUND_HALF_UP
            )
            target_strike = (raw // incr) * incr
            option_type = "call"
        else:
            raw = (stock_price * STRIKE_PUT_OFFSET).quantize(
                incr, rounding=ROUND_HALF_UP
            )
            target_strike = -(-raw // incr) * incr
            option_type = "put"

        today = _today()
        friday = today if today.weekday() == 4 else _next_friday(today)
        expiry = friday - timedelta(days=1) if _is_nyse_holiday(friday) else friday
        logger.info(
            "%s %s signal: stock=%s target_strike=%s expiry=%s",
            ticker,
            signal,
            stock_price,
            target_strike,
            expiry,
        )

        search_low = (stock_price * _D("0.80")).quantize(incr, rounding=ROUND_HALF_UP)
        search_high = (stock_price * _D("1.20")).quantize(incr, rounding=ROUND_HALF_UP)
        contracts = self._client.get_options_contracts(
            underlying_symbol=ticker,
            expiration_date=expiry,
            option_type=option_type,
            strike_price_gte=str(search_low),
            strike_price_lte=str(search_high),
            limit=50,
        )

        if not contracts:
            raise RuntimeError(
                f"No {option_type} contracts found for {ticker} "
                f"expiry={expiry} strike~{target_strike} "
                f"(searched {search_low}–{search_high})"
            )

        best = min(contracts, key=lambda c: abs(_D(c["strike_price"]) - target_strike))
        logger.info(
            "Selected contract: %s strike=%s (target was %s)",
            best["symbol"],
            best["strike_price"],
            target_strike,
        )
        return best["symbol"]

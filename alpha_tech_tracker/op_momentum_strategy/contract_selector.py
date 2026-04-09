import logging
from datetime import date, timedelta
from decimal import ROUND_CEILING, ROUND_HALF_UP

import pandas as pd
import pytz
from alpaca.data.requests import OptionLatestQuoteRequest
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

_OPTION_CONTRACT_SELECTOR_SEARCH_RADIUS_INCREMENTS = 5


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


def _end_of_next_month(ref_date: date) -> date:
    """Return the last calendar day of the month after ref_date's month."""
    month = ref_date.month + 2
    year = ref_date.year
    if month > 12:
        month -= 12
        year += 1
    return date(year, month, 1) - timedelta(days=1)


def _strike_increment(price) -> object:
    price = _D(price)
    if price < _D("50"):
        return _D("1")
    if price <= _D("200"):
        return _D("5")
    return _D("10")


def _fetch_contracts_with_expiry_fallback(
    client: AlpacaAPIClient,
    ticker: str,
    option_type: str,
    search_low,
    search_high,
) -> tuple:
    """Fetch contracts for the nearest weekly expiry, falling back to monthly.

    Returns (contracts: list, expiry: date).
    """
    today = _today()
    friday = today if today.weekday() == 4 else _next_friday(today)
    expiry = friday - timedelta(days=1) if _is_nyse_holiday(friday) else friday

    contracts = client.get_options_contracts(
        underlying_symbol=ticker,
        expiration_date=expiry,
        option_type=option_type,
        strike_price_gte=str(search_low),
        strike_price_lte=str(search_high),
        limit=50,
    )

    if not contracts:
        end_date = _end_of_next_month(today)
        logger.info(
            "%s: no weekly contracts for %s — querying Alpaca for earliest "
            "available expiry up to %s",
            ticker,
            expiry,
            end_date,
        )
        all_contracts = client.get_options_contracts(
            underlying_symbol=ticker,
            expiration_date_gte=today,
            expiration_date_lte=end_date,
            option_type=option_type,
            strike_price_gte=str(search_low),
            strike_price_lte=str(search_high),
            limit=50,
        )
        if all_contracts:
            earliest = min(c["expiration_date"] for c in all_contracts)
            contracts = [c for c in all_contracts if c["expiration_date"] == earliest]
            expiry = date.fromisoformat(earliest)
            logger.info("%s: monthly fallback using expiry %s", ticker, expiry)

    return contracts, expiry


class ITMOptionContractSelector:
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

        logger.info(
            "%s %s signal: stock=%s target_strike=%s",
            ticker,
            signal,
            stock_price,
            target_strike,
        )

        radius = incr * _OPTION_CONTRACT_SELECTOR_SEARCH_RADIUS_INCREMENTS
        contracts, expiry = _fetch_contracts_with_expiry_fallback(
            self._client,
            ticker,
            option_type,
            target_strike - radius,
            target_strike + radius,
        )

        if not contracts:
            search_low = (stock_price * _D("0.80")).quantize(incr, rounding=ROUND_HALF_UP)
            search_high = (stock_price * _D("1.20")).quantize(incr, rounding=ROUND_HALF_UP)
            contracts, expiry = _fetch_contracts_with_expiry_fallback(
                self._client, ticker, option_type, search_low, search_high
            )
            logger.info(
                "%s %s: narrow search empty, broad fallback %s–%s, got %d contracts",
                ticker,
                signal,
                search_low,
                search_high,
                len(contracts),
            )

        logger.info(
            "%s %s expiry=%s target_strike=%s",
            ticker,
            signal,
            expiry,
            target_strike,
        )

        if not contracts:
            raise RuntimeError(
                f"No {option_type} contracts found for {ticker} "
                f"expiry={expiry} strike~{target_strike}"
            )

        best = min(contracts, key=lambda c: abs(_D(c["strike_price"]) - target_strike))
        logger.info(
            "Selected contract: %s strike=%s (target was %s)",
            best["symbol"],
            best["strike_price"],
            target_strike,
        )
        return best["symbol"]


class TimePremiumContractSelector:
    """Selects the deepest ITM strike where the per-day time premium rate falls
    at or below the DTE-adjusted threshold.

    Threshold = (time_premium_pct_cap / reference_dte) * dte * stock_price

    Example — stock=$300, time_premium_pct_cap=0.01, reference_dte=5:
      weekly (DTE=5): target = 0.01/5 * 5 * $300 = $3.00
      monthly (DTE=25): target = 0.01/5 * 25 * $300 = $15.00

    Algorithm (BULLISH/call example):
      1. Fetch all ITM call contracts (strikes from 70% to 100% of stock price).
      2. Sort near-ATM first (descending strike for calls, ascending for puts).
      3. Walk deeper ITM: compute time_premium = mid - intrinsic at each strike.
      4. Select the first strike where time_premium <= DTE-adjusted target.
      5. Fallback to deepest ITM contract if all time premiums stay above target.

    Mirrors ITMOptionContractSelector expiry logic: weekly → monthly fallback.
    """

    def __init__(
        self,
        client: AlpacaAPIClient,
        time_premium_pct_cap: float = 0.01,
        reference_dte: int = 5,
    ):
        self._client = client
        self._time_premium_pct_cap = _D(str(time_premium_pct_cap))
        self._reference_dte = _D(str(reference_dte))

    def select(self, ticker: str, signal: str, stock_price: float) -> str:
        stock_price = _D(str(stock_price))
        incr = _strike_increment(stock_price)

        if signal == "BULLISH":
            option_type = "call"
            # ITM calls have strike < stock_price
            search_low = (stock_price * _D("0.70")).quantize(incr, rounding=ROUND_HALF_UP)
            search_high = stock_price.quantize(incr, rounding=ROUND_HALF_UP)
        else:
            option_type = "put"
            # ITM puts have strike > stock_price
            search_low = stock_price.quantize(incr, rounding=ROUND_HALF_UP)
            search_high = (stock_price * _D("1.30")).quantize(incr, rounding=ROUND_HALF_UP)

        contracts, expiry = _fetch_contracts_with_expiry_fallback(
            self._client, ticker, option_type, search_low, search_high
        )
        dte = _D(str((expiry - _today()).days))
        daily_rate = self._time_premium_pct_cap / self._reference_dte
        target_premium = daily_rate * dte * stock_price
        logger.info(
            "%s %s signal: stock=%s expiry=%s dte=%s target_premium=%s contracts=%d",
            ticker,
            signal,
            stock_price,
            expiry,
            dte,
            target_premium,
            len(contracts),
        )

        if not contracts:
            raise RuntimeError(
                f"No {option_type} contracts found for {ticker} "
                f"expiry={expiry} strike range {search_low}–{search_high}"
            )

        # Sort near-ATM first so we walk from high time premium towards low
        if signal == "BULLISH":
            contracts.sort(key=lambda c: _D(str(c["strike_price"])), reverse=True)
        else:
            contracts.sort(key=lambda c: _D(str(c["strike_price"])))

        symbols = [c["symbol"] for c in contracts]
        quotes = self._fetch_quotes_batch(symbols)

        # Fallback: deepest ITM (last in sorted order)
        selected = contracts[-1]
        for contract in contracts:
            sym = contract["symbol"]
            quote = quotes.get(sym)
            if quote is None:
                continue
            bid = _D(str(quote.bid_price))
            ask = _D(str(quote.ask_price))
            mid = (bid + ask) / _D("2")
            if mid <= _D("0"):
                continue
            strike = _D(str(contract["strike_price"]))
            if signal == "BULLISH":
                intrinsic = max(_D("0"), stock_price - strike)
            else:
                intrinsic = max(_D("0"), strike - stock_price)
            time_premium = mid - intrinsic
            logger.debug(
                "%s strike=%s mid=%s intrinsic=%s time_premium=%s target=%s",
                sym,
                strike,
                mid,
                intrinsic,
                time_premium,
                target_premium,
            )
            if time_premium <= target_premium:
                selected = contract
                break

        logger.info(
            "TimePremium selected %s strike=%s (dte=%s target_premium=%s)",
            selected["symbol"],
            selected["strike_price"],
            dte,
            target_premium,
        )
        return selected["symbol"]

    def _fetch_quotes_batch(self, symbols: list) -> dict:
        try:
            return self._client._option_data_client.get_option_latest_quote(
                OptionLatestQuoteRequest(symbol_or_symbols=symbols)
            )
        except Exception:
            logger.warning(
                "Failed to batch-fetch option quotes for %d symbols", len(symbols)
            )
            return {}


class MockContractSelector:
    """Builds an OCC option symbol for replay mode — no API calls.

    BULLISH (call): strike = floor(stock_price × 0.90 / increment) × increment
    BEARISH (put):  strike = ceil(stock_price × 1.10 / increment) × increment
    Expiry: next Friday on or after ref_date.
    """

    _CALL_RATIO = _D("0.90")
    _PUT_RATIO = _D("1.10")

    def __init__(self, ref_date: date):
        self._ref_date = ref_date

    def select(self, ticker: str, signal: str, stock_price: float) -> str:
        stock_price = _D(str(stock_price))
        incr = _strike_increment(stock_price)

        if signal == "BULLISH":
            raw = stock_price * self._CALL_RATIO
            strike = (raw // incr) * incr
            cp = "C"
        else:
            raw = stock_price * self._PUT_RATIO
            strike = (raw / incr).to_integral_value(rounding=ROUND_CEILING) * incr
            cp = "P"

        expiry = _next_friday(self._ref_date)
        strike_int = int(strike * _D("1000"))
        symbol = f"{ticker}{expiry.strftime('%y%m%d')}{cp}{strike_int:08d}"
        logger.info(
            "MockContractSelector: %s %s stock=%s → %s (strike=%s expiry=%s)",
            ticker,
            signal,
            stock_price,
            symbol,
            strike,
            expiry,
        )
        return symbol

import argparse
import logging
from decimal import Decimal, ROUND_HALF_UP
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional

import pandas as pd
import pytz

from alpaca.data.live import StockDataStream
from alpaca.data.requests import OptionLatestQuoteRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.trading.requests import LimitOrderRequest, MarketOrderRequest

from alpha_tech_tracker.op_momentum_strategy.op_momentum_selector import (
    DEFAULT_TICKERS,
    ROLLING_LOOKBACK_DAYS,
    select_top_n,
)
from alpha_tech_tracker.trade_api.alpaca_client.client import (
    AlpacaAPIClient,
    APIInvalidArgumentError,
)

logger = logging.getLogger(__name__)

ET = pytz.timezone("America/New_York")


def _D(x) -> Decimal:
    """Convert any numeric value to Decimal via string to avoid float imprecision."""
    return Decimal(str(x))


TICKERS = DEFAULT_TICKERS
ACCOUNT_BUDGET = 25_000
MAX_ACTIVE_SYMBOLS = 2
OPENING_BARS = 3
STOP_PCT = _D("0.15")
STRIKE_CALL_OFFSET = _D("0.90")
STRIKE_PUT_OFFSET = _D("1.10")
CAPITAL_PER_SYMBOL = _D("0.45")
EOD_EXIT_TIME = "15:55"
MA_WARMUP_DAYS = 30
BEARISH_MA200 = False


# ---------------------------------------------------------------------------
# Signal event
# ---------------------------------------------------------------------------


@dataclass
class SignalEvent:
    ticker: str
    signal: str
    entry_price: Decimal
    stock_price: Decimal
    or_high: Decimal
    or_low: Decimal
    or_range: Decimal
    ma50_at_signal: Decimal


# ---------------------------------------------------------------------------
# Active position state
# ---------------------------------------------------------------------------


@dataclass
class ActivePosition:
    ticker: str
    signal: str
    option_symbol: str
    entry_order_id: str
    contracts: int
    entry_stock_price: Decimal
    or_high: Decimal
    or_low: Decimal
    or_range: Decimal
    hard_stop_price: Decimal
    fallback_price: Decimal
    hard_stop_armed: bool = False
    is_closed: bool = False
    exit_reason: str = ""


# ---------------------------------------------------------------------------
# 1. TickerSelector
# ---------------------------------------------------------------------------


class TickerSelector:
    """
    Selects the top N tickers using the momentum selector's composite scoring:
    60-day rolling EV gate + today's opening-range signal + composite score.

    If called before the opening range closes (pre-9:45 AM ET), today's intraday
    signals are not yet available. In that case the selector falls back to the
    previous trading day so the engine still gets a ranked list to watch.
    """

    def __init__(self, tickers: list, top_n: int):
        self._tickers = tickers
        self._top_n = top_n

    def select(self) -> list:
        today = datetime.now(ET).date()
        result = select_top_n(
            n=self._top_n,
            tickers=self._tickers,
            lookback_days=ROLLING_LOOKBACK_DAYS,
            opening_bars=OPENING_BARS,
            bearish_ma200=BEARISH_MA200,
            stop_pct=float(STOP_PCT),
            source="alpaca",
            target_date=today,
        )

        picks = result["picks"]

        if not picks:
            # Opening range hasn't closed yet — fall back to the most recent
            # trading day that has complete intraday data (yesterday or earlier).
            prev_day = today - timedelta(days=1)
            while prev_day.weekday() >= 5:  # skip weekends
                prev_day -= timedelta(days=1)
            logger.info(
                "No picks for today (%s) — falling back to %s for pre-market selection",
                today,
                prev_day,
            )
            result = select_top_n(
                n=self._top_n,
                tickers=self._tickers,
                lookback_days=ROLLING_LOOKBACK_DAYS,
                opening_bars=OPENING_BARS,
                bearish_ma200=BEARISH_MA200,
                stop_pct=float(STOP_PCT),
                source="alpaca",
                target_date=prev_day,
            )
            picks = result["picks"]

        selected = [p["ticker"] for p in picks]
        logger.info(
            "Selector picks: %s | no_signal: %s | negative_ev: %s",
            [{p["ticker"]: f"score={p['score']} ev={p['ev_trade']}%"} for p in picks],
            result.get("no_signal", []),
            result.get("negative_ev", []),
        )
        return selected


# ---------------------------------------------------------------------------
# 2. OptionContractSelector
# ---------------------------------------------------------------------------


def _next_friday(ref_date: date) -> date:
    days_ahead = 4 - ref_date.weekday()  # Friday = 4
    if days_ahead <= 0:
        days_ahead += 7
    return ref_date + timedelta(days=days_ahead)


def _strike_increment(price: Decimal) -> Decimal:
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
            target_strike = -(-raw // incr) * incr  # ceiling division
            option_type = "put"

        expiry = _next_friday(date.today())
        logger.info(
            "%s %s signal: stock=%s target_strike=%s expiry=%s",
            ticker,
            signal,
            stock_price,
            target_strike,
            expiry,
        )

        contracts = self._client.get_options_contracts(
            underlying_symbol=ticker,
            expiration_date=expiry,
            option_type=option_type,
            strike_price_gte=str(target_strike - incr),
            strike_price_lte=str(target_strike + incr),
            limit=20,
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


# ---------------------------------------------------------------------------
# 3. PositionSizer
# ---------------------------------------------------------------------------


class PositionSizer:
    """Computes contract quantity based on available buying power."""

    def __init__(self, alpaca_client: AlpacaAPIClient):
        self._client = alpaca_client

    def compute(self, option_symbol: str) -> tuple:
        account = self._client.get_accounts()
        buying_power = _D(account.get("buying_power", ACCOUNT_BUDGET))
        budget = buying_power * CAPITAL_PER_SYMBOL

        quote_resp = self._client._option_data_client.get_option_latest_quote(
            OptionLatestQuoteRequest(symbol_or_symbols=[option_symbol])
        )
        quote = quote_resp[option_symbol]
        bid = _D(quote.bid_price)
        ask = _D(quote.ask_price)
        mid = (bid + ask) / _D("2")

        if mid <= _D("0"):
            logger.warning(
                "Mid price is zero for %s, defaulting to 1 contract", option_symbol
            )
            return 1, ask

        contracts = max(1, int(budget / (mid * _D("100"))))
        limit_price = mid.quantize(_D("0.01"), rounding=ROUND_HALF_UP)
        logger.info(
            "%s: budget=%s mid=%s → %d contracts (cost=%s)",
            option_symbol,
            budget,
            mid,
            contracts,
            contracts * mid * _D("100"),
        )
        return contracts, limit_price


# ---------------------------------------------------------------------------
# 4. LiveSignalEngine
# ---------------------------------------------------------------------------


class LiveSignalEngine:
    """
    Watches live 5-min bars for a set of tickers.
    Fires SignalEvent callbacks after the opening range closes.
    """

    def __init__(
        self,
        tickers: list,
        api_key: str,
        secret_key: str,
        opening_bars: int = OPENING_BARS,
        bearish_ma200: bool = BEARISH_MA200,
        on_signal=None,
    ):
        self._tickers = tickers
        self._opening_bars = opening_bars
        self._bearish_ma200 = bearish_ma200
        self._on_signal = on_signal  # callable(SignalEvent)
        self._api_key = api_key
        self._secret_key = secret_key

        # rolling 5-min dataframes keyed by ticker
        self._history: dict = {}
        # opening bars collected today keyed by ticker
        self._opening_buf: dict = {t: [] for t in tickers}
        self._signal_fired: dict = {t: False for t in tickers}
        self._session_date = datetime.now(ET).date()
        self._stream: StockDataStream = None
        self._lock = threading.Lock()

    def _warmup(self):
        hist_client = StockHistoricalDataClient(self._api_key, self._secret_key)
        end_dt = datetime.now(ET)
        start_dt = end_dt - timedelta(days=MA_WARMUP_DAYS)

        request = StockBarsRequest(
            symbol_or_symbols=self._tickers,
            timeframe=TimeFrame(amount=5, unit=TimeFrameUnit.Minute),
            start=start_dt,
            end=end_dt,
        )
        bars = hist_client.get_stock_bars(request)
        all_df = bars.df

        for ticker in self._tickers:
            try:
                df = all_df.xs(ticker, level=0).copy()
                df.index = df.index.tz_convert(ET)
                df = df.between_time("09:30", "16:00")
                df.columns = [c.capitalize() for c in df.columns]
                df["MA20"] = df["Close"].rolling(20).mean()
                df["MA50"] = df["Close"].rolling(50).mean()
                df["MA200"] = df["Close"].rolling(200).mean()
                self._history[ticker] = df
                logger.info("Warmed up %s with %d bars", ticker, len(df))
            except KeyError:
                self._history[ticker] = pd.DataFrame(
                    columns=[
                        "Open",
                        "High",
                        "Low",
                        "Close",
                        "Volume",
                        "MA20",
                        "MA50",
                        "MA200",
                    ]
                )
                logger.warning("No warmup data for %s", ticker)

    def _append_bar(self, ticker: str, bar) -> pd.Series:
        new_row = pd.Series(
            {
                "Open": float(bar.open),
                "High": float(bar.high),
                "Low": float(bar.low),
                "Close": float(bar.close),
                "Volume": float(bar.volume),
            },
            name=bar.timestamp.astimezone(ET),
        )

        df = self._history.get(ticker, pd.DataFrame())
        self._history[ticker] = pd.concat([df, new_row.to_frame().T])
        df = self._history[ticker]
        df["MA20"] = df["Close"].rolling(20).mean()
        df["MA50"] = df["Close"].rolling(50).mean()
        df["MA200"] = df["Close"].rolling(200).mean()
        self._history[ticker] = df
        return df.iloc[-1]

    def _try_fire_signal(self, ticker: str, latest: pd.Series):
        buf = self._opening_buf[ticker]
        or_high = _D(max(b.high for b in buf))
        or_low = _D(min(b.low for b in buf))
        or_range = or_high - or_low
        midpoint = (or_high + or_low) / _D("2")
        bottom_30 = or_low + _D("0.20") * or_range

        close = _D(latest["Close"])
        ma20 = latest["MA20"]
        ma50 = latest["MA50"]
        ma200 = latest["MA200"]

        if pd.isna(ma20) or pd.isna(ma200):
            logger.info("%s: MA not ready, skipping signal", ticker)
            return

        ma20_d = _D(ma20)
        ma200_d = _D(ma200)

        bearish_ma_ok = close < ma20_d and (
            close < ma200_d if self._bearish_ma200 else True
        )

        if close > midpoint and close > ma20_d and close > ma200_d:
            signal = "BULLISH"
        elif close <= bottom_30 and bearish_ma_ok:
            signal = "BEARISH"
        else:
            logger.info(
                "%s: NEUTRAL — close=%s midpoint=%s or_low=%s bottom_30=%s",
                ticker,
                close,
                midpoint,
                or_low,
                bottom_30,
            )
            return

        ma50_val = _D(ma50) if not pd.isna(ma50) else close

        event = SignalEvent(
            ticker=ticker,
            signal=signal,
            entry_price=close,
            stock_price=close,
            or_high=or_high,
            or_low=or_low,
            or_range=or_range,
            ma50_at_signal=ma50_val,
        )
        logger.info(
            "SIGNAL %s %s close=%s or_high=%s or_low=%s",
            ticker,
            signal,
            close,
            or_high,
            or_low,
        )
        if self._on_signal:
            self._on_signal(event)

    async def _handle_bar(self, bar):
        ticker = bar.symbol
        if ticker not in self._tickers:
            return

        ts = bar.timestamp.astimezone(ET)
        today = datetime.now(ET).date()

        with self._lock:
            if ts.date() != today:
                return
            if self._signal_fired.get(ticker):
                # still append for MA50 tracking in PositionMonitor
                self._append_bar(ticker, bar)
                return

            market_open = ET.localize(
                datetime.combine(today, datetime.strptime("09:30", "%H:%M").time())
            )
            if ts < market_open:
                return

            latest = self._append_bar(ticker, bar)
            buf = self._opening_buf[ticker]

            if len(buf) < self._opening_bars:
                buf.append(bar)
                logger.debug(
                    "%s: opening bar %d/%d", ticker, len(buf), self._opening_bars
                )

            if len(buf) == self._opening_bars and not self._signal_fired[ticker]:
                self._signal_fired[ticker] = True
                self._try_fire_signal(ticker, latest)

    def get_latest_bar(self, ticker: str) -> Optional[pd.Series]:
        df = self._history.get(ticker)
        if df is None or df.empty:
            return None
        return df.iloc[-1]

    def start(self):
        logger.info("Warming up historical bars for %s", self._tickers)
        self._warmup()
        self._stream = StockDataStream(self._api_key, self._secret_key)
        self._stream.subscribe_bars(self._handle_bar, *self._tickers)
        logger.info("Starting live data stream for %s", self._tickers)
        thread = threading.Thread(target=self._stream.run, daemon=True)
        thread.start()

    def stop(self):
        if self._stream:
            self._stream.stop()


# ---------------------------------------------------------------------------
# 5. PositionMonitor
# ---------------------------------------------------------------------------


class PositionMonitor:
    """Monitors open option positions and exits on stop conditions."""

    def __init__(self, alpaca_client: AlpacaAPIClient, signal_engine: LiveSignalEngine):
        self._client = alpaca_client
        self._signal_engine = signal_engine
        self._positions: list = []
        self._lock = threading.Lock()

    def add_position(self, position: ActivePosition):
        with self._lock:
            self._positions.append(position)
            logger.info(
                "Tracking position: %s %s opt=%s contracts=%d",
                position.ticker,
                position.signal,
                position.option_symbol,
                position.contracts,
            )

    def on_bar(self, ticker: str):
        latest = self._signal_engine.get_latest_bar(ticker)
        if latest is None:
            return

        close = _D(latest["Close"])
        ma50 = latest.get("MA50")
        ma50_val = _D(ma50) if not pd.isna(ma50) else None

        with self._lock:
            for pos in self._positions:
                if pos.ticker != ticker or pos.is_closed:
                    continue
                self._evaluate_stop(pos, close, ma50_val)

    def _evaluate_stop(
        self, pos: ActivePosition, close: Decimal, ma50: Optional[Decimal]
    ):
        exit_reason = None

        if pos.signal == "BULLISH":
            if not pos.hard_stop_armed and close > pos.hard_stop_price:
                pos.hard_stop_armed = True
            if pos.hard_stop_armed and close <= pos.hard_stop_price:
                exit_reason = "hard_stop"
            elif not pos.hard_stop_armed and close <= pos.fallback_price:
                exit_reason = "fallback_20pct"
            elif ma50 is not None and close < ma50:
                exit_reason = "trailing_stop_ma50"
        else:
            if not pos.hard_stop_armed and close < pos.hard_stop_price:
                pos.hard_stop_armed = True
            if pos.hard_stop_armed and close >= pos.hard_stop_price:
                exit_reason = "hard_stop"
            elif not pos.hard_stop_armed and close >= pos.fallback_price:
                exit_reason = "fallback_20pct"
            elif ma50 is not None and close > ma50:
                exit_reason = "trailing_stop_ma50"

        if exit_reason:
            self._close_position(pos, exit_reason)

    def _close_position(self, pos: ActivePosition, reason: str):
        pos.is_closed = True
        pos.exit_reason = reason
        logger.info(
            "EXIT %s %s reason=%s opt=%s contracts=%d",
            pos.ticker,
            pos.signal,
            reason,
            pos.option_symbol,
            pos.contracts,
        )
        try:
            quote_resp = self._client._option_data_client.get_option_latest_quote(
                OptionLatestQuoteRequest(symbol_or_symbols=[pos.option_symbol])
            )
            quote = quote_resp[pos.option_symbol]
            bid = _D(quote.bid_price)
            ask = _D(quote.ask_price)
            fallback = (ask * _D("0.98")).quantize(_D("0.01"), rounding=ROUND_HALF_UP)
            exit_limit = bid.quantize(_D("0.01"), rounding=ROUND_HALF_UP) or fallback
        except Exception:
            logger.exception(
                "Could not fetch exit quote for %s, using market order",
                pos.option_symbol,
            )
            exit_limit = None

        try:
            if exit_limit:
                order = self._client.place_option_order(
                    symbol=pos.ticker,
                    option_key=None,
                    price=float(exit_limit),
                    price_type="LIMIT",
                    option_type="CALL" if pos.signal == "BULLISH" else "PUT",
                    order_action="SELL_CLOSE",
                    quantity=pos.contracts,
                    _option_symbol_override=pos.option_symbol,
                )
            else:
                order = self._client.place_option_order(
                    symbol=pos.ticker,
                    option_key=None,
                    price_type="MARKET",
                    option_type="CALL" if pos.signal == "BULLISH" else "PUT",
                    order_action="SELL_CLOSE",
                    quantity=pos.contracts,
                    _option_symbol_override=pos.option_symbol,
                )
            logger.info("Close order placed: %s", order.get("order_id"))
        except Exception:
            logger.exception("Failed to place close order for %s", pos.option_symbol)

    def close_all(self, reason: str = "end_of_day"):
        with self._lock:
            for pos in self._positions:
                if not pos.is_closed:
                    self._close_position(pos, reason)

    def print_summary(self):
        print(f"\n{'=' * 72}")
        print("  DAILY TRADE SUMMARY")
        print(f"{'=' * 72}")
        print(f"  {'Ticker':<7} {'Signal':<9} {'Option':<26} {'Qty':>4}  Exit Reason")
        print(f"  {'─' * 70}")
        for pos in self._positions:
            print(
                f"  {pos.ticker:<7} {pos.signal:<9} {pos.option_symbol:<26} "
                f"{pos.contracts:>4}  {pos.exit_reason or 'open'}"
            )
        print(f"{'=' * 72}\n")


# ---------------------------------------------------------------------------
# 6. OpMomentumTradeEngine — Orchestrator
# ---------------------------------------------------------------------------


class OpMomentumTradeEngine:
    """
    Main orchestrator for the opening-range momentum options strategy.

    Daily flow:
      1. Select top-2 tickers by 30-day return.
      2. Pre-warm historical bars for MA computation.
      3. Stream live 5-min bars; fire signal after opening range.
      4. On signal: select option contract, size position, place BUY order.
      5. Monitor stops intraday; close on hard stop, MA50 trail, or EOD.
    """

    def __init__(self, alpaca_client: AlpacaAPIClient, is_paper: bool = True):
        self._client = alpaca_client
        self._api_key = alpaca_client._api_key
        self._secret_key = alpaca_client._secret_key
        self._monitor: PositionMonitor = None
        self._signal_engine: LiveSignalEngine = None

    def _on_signal(self, event: SignalEvent):
        logger.info(
            "Handling signal: %s %s @ %.2f",
            event.ticker,
            event.signal,
            event.stock_price,
        )
        try:
            selector = OptionContractSelector(self._client)
            option_symbol = selector.select(
                event.ticker, event.signal, event.stock_price
            )
        except Exception:
            logger.exception("Could not select option contract for %s", event.ticker)
            return

        try:
            sizer = PositionSizer(self._client)
            contracts, limit_price = sizer.compute(option_symbol)
        except Exception:
            logger.exception("Could not size position for %s", option_symbol)
            return

        try:
            order = self._place_entry(
                ticker=event.ticker,
                signal=event.signal,
                option_symbol=option_symbol,
                contracts=contracts,
                limit_price=limit_price,
            )
        except Exception:
            logger.exception("Failed to place entry order for %s", option_symbol)
            return

        bull_hard_stop = event.or_high - STOP_PCT * event.or_range
        bear_hard_stop = event.or_low + STOP_PCT * event.or_range
        bull_fallback = event.or_high - _D("0.20") * event.or_range
        bear_fallback = event.or_low + _D("0.20") * event.or_range

        pos = ActivePosition(
            ticker=event.ticker,
            signal=event.signal,
            option_symbol=option_symbol,
            entry_order_id=order.get("order_id", ""),
            contracts=contracts,
            entry_stock_price=event.entry_price,
            or_high=event.or_high,
            or_low=event.or_low,
            or_range=event.or_range,
            hard_stop_price=bull_hard_stop
            if event.signal == "BULLISH"
            else bear_hard_stop,
            fallback_price=bull_fallback
            if event.signal == "BULLISH"
            else bear_fallback,
        )
        self._monitor.add_position(pos)

    def _place_entry(
        self,
        ticker: str,
        signal: str,
        option_symbol: str,
        contracts: int,
        limit_price: float,
    ) -> dict:
        option_type = "CALL" if signal == "BULLISH" else "PUT"
        logger.info(
            "Placing BUY_OPEN: %s %s %d @ %.2f",
            option_symbol,
            option_type,
            contracts,
            limit_price,
        )
        order = self._client.place_option_order(
            symbol=ticker,
            option_key=None,
            price=limit_price,
            price_type="LIMIT",
            option_type=option_type,
            order_action="BUY_OPEN",
            quantity=contracts,
            _option_symbol_override=option_symbol,
        )
        logger.info(
            "Entry order placed: id=%s status=%s",
            order.get("order_id"),
            order.get("status"),
        )
        return order

    def _monitor_loop(self, active_tickers: list):
        """Polls PositionMonitor on each new bar arrival, and forces EOD close."""
        eod_h, eod_m = [int(x) for x in EOD_EXIT_TIME.split(":")]
        while True:
            now = datetime.now(ET)
            if now.hour > eod_h or (now.hour == eod_h and now.minute >= eod_m):
                logger.info("EOD: force-closing all positions")
                self._monitor.close_all(reason="end_of_day")
                break

            for ticker in active_tickers:
                self._monitor.on_bar(ticker)
            time.sleep(30)

    def run(self, tickers_override: list = None):
        api_key = self._api_key
        secret_key = self._secret_key

        ticker_selector = TickerSelector(
            tickers=tickers_override or TICKERS,
            top_n=MAX_ACTIVE_SYMBOLS,
        )
        active_tickers = ticker_selector.select()
        print(f"\nActive tickers for today: {active_tickers}")

        self._signal_engine = LiveSignalEngine(
            tickers=active_tickers,
            api_key=api_key,
            secret_key=secret_key,
            opening_bars=OPENING_BARS,
            bearish_ma200=BEARISH_MA200,
            on_signal=self._on_signal,
        )
        self._monitor = PositionMonitor(self._client, self._signal_engine)

        self._signal_engine.start()

        monitor_thread = threading.Thread(
            target=self._monitor_loop, args=(active_tickers,), daemon=True
        )
        monitor_thread.start()
        monitor_thread.join()

        self._signal_engine.stop()
        self._monitor.print_summary()


# ---------------------------------------------------------------------------
# AlpacaAPIClient patch: support _option_symbol_override in place_option_order
# ---------------------------------------------------------------------------

_original_place_option_order = AlpacaAPIClient.place_option_order


def _patched_place_option_order(
    self,
    symbol,
    option_key=None,
    price=None,
    order_id=None,
    preview_order=None,
    price_type="LIMIT",
    option_type="CALL",
    order_action="BUY_OPEN",
    quantity=1,
    _option_symbol_override=None,
):
    """Extends place_option_order to accept a pre-built OCC symbol directly."""
    if _option_symbol_override:
        option_symbol = _option_symbol_override
    else:
        option_symbol = self._build_option_symbol(symbol, option_key, option_type)

    side_mapping = {
        "BUY_OPEN": "BUY",
        "BUY_CLOSE": "BUY",
        "SELL_OPEN": "SELL",
        "SELL_CLOSE": "SELL",
    }
    side = side_mapping.get(order_action, "BUY")

    if price_type.upper() == "SMART_MARKET":
        quote = self.get_option_quote(symbol, option_key, option_type=option_type)
        price_info = self.get_price_from_quote(quote)
        price = price_info["s-mid"]
        price_type = "LIMIT"

    order_side = OrderSide.BUY if side == "BUY" else OrderSide.SELL

    if price_type.upper() == "MARKET":
        order_data = MarketOrderRequest(
            symbol=option_symbol,
            qty=quantity,
            side=order_side,
            time_in_force=TimeInForce.DAY,
        )
    elif price_type.upper() == "LIMIT":
        if price is None:
            raise APIInvalidArgumentError(
                code="MISSING_LIMIT_PRICE",
                message="price is required for LIMIT orders",
            )
        order_data = LimitOrderRequest(
            symbol=option_symbol,
            qty=quantity,
            side=order_side,
            time_in_force=TimeInForce.DAY,
            limit_price=float(price),
        )
    else:
        raise APIInvalidArgumentError(
            code="INVALID_PRICE_TYPE",
            message=f"Unsupported price type: {price_type}",
        )

    order = self._trading_client.submit_order(order_data=order_data)
    return {
        "order_id": order.id,
        "client_order_id": order.client_order_id,
        "symbol": order.symbol,
        "quantity": float(order.qty),
        "filled_qty": float(order.filled_qty) if order.filled_qty else 0,
        "side": order.side.value,
        "type": order.type.value,
        "status": order.status.value,
        "limit_price": float(order.limit_price) if order.limit_price else None,
        "filled_avg_price": (
            float(order.filled_avg_price) if order.filled_avg_price else None
        ),
        "submitted_at": order.submitted_at,
        "raw_response": order,
    }


AlpacaAPIClient.place_option_order = _patched_place_option_order


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


def parse_args():
    parser = argparse.ArgumentParser(description="OpMomentum live trade engine")
    parser.add_argument(
        "--live",
        action="store_true",
        default=False,
        help="Use live trading account (default: paper trading)",
    )
    parser.add_argument(
        "--tickers",
        nargs="+",
        default=None,
        help="Override ticker universe, e.g. --tickers NVDA CRWD",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    client = AlpacaAPIClient(is_paper_trading=not args.live)
    engine = OpMomentumTradeEngine(alpaca_client=client, is_paper=not args.live)
    engine.run(tickers_override=args.tickers)

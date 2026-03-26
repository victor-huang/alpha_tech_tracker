import argparse
import json
import logging
import os
import signal
import sys
from decimal import Decimal, ROUND_HALF_UP
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional

import pandas as pd
import pytz

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.live import StockDataStream
from alpaca.data.enums import DataFeed
from alpaca.data.requests import OptionLatestQuoteRequest, StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.trading.requests import LimitOrderRequest, MarketOrderRequest

from alpha_tech_tracker.op_momentum_strategy.op_momentum_backtest import (
    build_bearish_regime_dates,
    fetch_bars,
)
from alpha_tech_tracker.op_momentum_strategy.op_momentum_selector import (
    DEFAULT_TICKERS,
    _safe_bars_end,
    score_ticker,
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
OPENING_START_TIME = "09:30"
STOP_PCT = _D("0.15")
STRIKE_CALL_OFFSET = _D("0.90")
STRIKE_PUT_OFFSET = _D("1.10")
CAPITAL_PER_SYMBOL = _D("0.45")
EOD_EXIT_TIME = "15:55"
MA_WARMUP_DAYS = 7
ROLLING_LOOKBACK_DAYS = 30
BEARISH_MA200 = False
SIGNAL_BUFFER_MINUTES = 2
TRAILING_MA = "ma20"
MAX_LOSS_PCT = None
ARMED_MA20_EXIT = False
REGIME_FILTER = False
REGIME_MA = 5
RANK_WEIGHTED_SIZING = False
RANK_WEIGHTS = [0.50, 0.30, 0.20]

_clicksend_cfg: dict = {}


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
# Aggregated 5-minute bar (built from live 1-minute bars)
# ---------------------------------------------------------------------------


@dataclass
class _FiveMinBar:
    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


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
    entry_time: Optional[datetime] = None
    exit_time: Optional[datetime] = None
    simulated_entry_mid: Optional[Decimal] = None
    simulated_exit_mid: Optional[Decimal] = None
    exit_order_id: Optional[str] = None
    entry_fill_price: Optional[Decimal] = None
    exit_fill_price: Optional[Decimal] = None


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

    def __init__(
        self,
        tickers: list,
        top_n: int,
        stop_pct: float = float(STOP_PCT),
        opening_start_time: str = OPENING_START_TIME,
    ):
        self._tickers = tickers
        self._top_n = top_n
        self._stop_pct = stop_pct
        self._opening_start_time = opening_start_time
        self.rolling_stats: dict = {}

    def select(self) -> list:
        today = datetime.now(ET).date()

        # Pre-fetch bars once — covers both the rolling lookback window and
        # the MA warmup window, so all select_top_n calls below reuse this data.
        fetch_start = today - timedelta(days=max(ROLLING_LOOKBACK_DAYS, 30) + 5)
        ticker_dfs = fetch_bars(
            self._tickers,
            fetch_start,
            _safe_bars_end(today),
            source="alpaca",
            allow_intraday=True,
        )

        result = select_top_n(
            n=self._top_n,
            tickers=self._tickers,
            lookback_days=ROLLING_LOOKBACK_DAYS,
            opening_bars=OPENING_BARS,
            bearish_ma200=BEARISH_MA200,
            stop_pct=self._stop_pct,
            source="alpaca",
            target_date=today,
            ticker_dfs=ticker_dfs,
            opening_start_time=self._opening_start_time,
        )
        self.rolling_stats = result.get("rolling_stats", {})

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
                stop_pct=self._stop_pct,
                source="alpaca",
                target_date=prev_day,
                ticker_dfs=ticker_dfs,
                opening_start_time=self._opening_start_time,
            )
            self.rolling_stats = result.get("rolling_stats", {})
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

        # Fetch contracts over a ±20% range around the current stock price so we
        # always capture available strikes regardless of their spacing, then pick
        # the one closest to our computed target.
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


# ---------------------------------------------------------------------------
# 3. PositionSizer
# ---------------------------------------------------------------------------


class PositionSizer:
    """Computes contract quantity based on available buying power."""

    def __init__(self, alpaca_client: AlpacaAPIClient):
        self._client = alpaca_client

    def compute(self, option_symbol: str, capital_weight: Decimal = _D("1")) -> tuple:
        account = self._client.get_accounts()
        buying_power = _D(account.get("buying_power", ACCOUNT_BUDGET))
        budget = buying_power * CAPITAL_PER_SYMBOL * capital_weight

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
            "%s: budget=%s (weight=%.2f) mid=%s → %d contracts (cost=%s)",
            option_symbol,
            budget,
            float(capital_weight),
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
        opening_start_time: str = OPENING_START_TIME,
        regime_filter: bool = REGIME_FILTER,
        regime_ma: int = REGIME_MA,
    ):
        self._tickers = tickers
        self._opening_bars = opening_bars
        self._bearish_ma200 = bearish_ma200
        self._opening_start_time = opening_start_time
        self._opening_start = datetime.strptime(opening_start_time, "%H:%M").time()
        self._on_signal = on_signal  # callable(SignalEvent)
        self._regime_filter = regime_filter
        self._regime_ma = regime_ma
        self._bearish_regime_dates: set = set()
        self._api_key = api_key
        self._secret_key = secret_key

        # rolling 5-min dataframes keyed by ticker
        self._history: dict = {}
        # opening 5-min bars collected today keyed by ticker
        self._opening_buf: dict = {t: [] for t in tickers}
        self._signal_fired: dict = {t: False for t in tickers}
        # 1-min bar accumulator for building synthetic 5-min bars
        self._minute_buf: dict = {
            t: {"period_start": None, "bars": []} for t in tickers
        }
        # flag so we only kick off one historical catchup per session
        self._opening_catchup_done: bool = False
        self._session_date = datetime.now(ET).date()
        self._stream: StockDataStream = None
        self._lock = threading.Lock()

    def _warmup(self):
        hist_client = StockHistoricalDataClient(self._api_key, self._secret_key)
        now_et = datetime.now(ET)
        market_open = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
        if now_et >= market_open:
            end_dt = now_et
        else:
            prev = now_et.date() - timedelta(days=1)
            while prev.weekday() >= 5:
                prev -= timedelta(days=1)
            end_dt = ET.localize(
                datetime.combine(prev, datetime.strptime("16:00", "%H:%M").time())
            )
        start_dt = end_dt - timedelta(days=MA_WARMUP_DAYS)

        logger.info(
            "Fetching historical 5-min bars for %d tickers: %s to %s",
            len(self._tickers),
            start_dt.strftime("%Y-%m-%d %H:%M ET"),
            end_dt.strftime("%Y-%m-%d %H:%M ET"),
        )
        request = StockBarsRequest(
            symbol_or_symbols=self._tickers,
            timeframe=TimeFrame(amount=5, unit=TimeFrameUnit.Minute),
            start=start_dt,
            end=end_dt,
            feed=DataFeed.IEX,
        )
        bars = hist_client.get_stock_bars(request)
        all_df = bars.df
        logger.info("Historical fetch complete — processing bars per ticker")

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
                last_close = df["Close"].iloc[-1] if not df.empty else float("nan")
                logger.info(
                    "Warmed up %-6s — %d bars, last close=%.2f",
                    ticker,
                    len(df),
                    last_close,
                )
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

        if (
            signal == "BULLISH"
            and datetime.now(ET).date() in self._bearish_regime_dates
        ):
            logger.info(
                "%s: BULLISH signal suppressed by regime filter (QQQ bearish)", ticker
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

    def _aggregate_bars(
        self, ticker: str, period_start: datetime, bars: list
    ) -> _FiveMinBar:
        return _FiveMinBar(
            symbol=ticker,
            timestamp=period_start,
            open=float(bars[0].open),
            high=max(float(b.high) for b in bars),
            low=min(float(b.low) for b in bars),
            close=float(bars[-1].close),
            volume=sum(float(b.volume) for b in bars),
        )

    def _process_five_min_bar(self, bar: _FiveMinBar):
        ticker = bar.symbol
        if self._signal_fired.get(ticker):
            # Keep appending for MA50 tracking used by PositionMonitor
            self._append_bar(ticker, bar)
            return

        latest = self._append_bar(ticker, bar)

        bar_time = bar.timestamp.astimezone(ET).time()
        if bar_time < self._opening_start:
            # Bar is before the opening window — update history for MAs but
            # do not count toward the opening range buffer.
            return

        buf = self._opening_buf[ticker]

        if len(buf) < self._opening_bars:
            buf.append(bar)
            logger.debug("%s: opening bar %d/%d", ticker, len(buf), self._opening_bars)

        if len(buf) == self._opening_bars and not self._signal_fired[ticker]:
            self._signal_fired[ticker] = True
            self._try_fire_signal(ticker, latest)

    def _catch_up_all_opening_bars(self, today):
        """
        Fetch today's opening-range 5-min bars from the historical API and
        replay them so that any ticker whose opening buffer was incomplete due
        to a stream gap can still fire its signal.
        """
        or_start = ET.localize(datetime.combine(today, self._opening_start))
        or_end = or_start + timedelta(minutes=self._opening_bars * 5)
        logger.info(
            "Catching up opening bars for all tickers (%s–%s ET)",
            or_start.strftime("%H:%M"),
            or_end.strftime("%H:%M"),
        )
        hist_client = StockHistoricalDataClient(self._api_key, self._secret_key)
        request = StockBarsRequest(
            symbol_or_symbols=self._tickers,
            timeframe=TimeFrame(amount=5, unit=TimeFrameUnit.Minute),
            start=or_start,
            end=or_end,
            feed=DataFeed.IEX,
        )
        try:
            bars = hist_client.get_stock_bars(request)
            all_df = bars.df
        except Exception:
            logger.exception("Failed to fetch opening bar catchup data")
            return

        for ticker in self._tickers:
            if self._signal_fired.get(ticker):
                continue
            try:
                tick_df = all_df.xs(ticker, level=0).copy()
            except KeyError:
                logger.warning("No catchup data for %s", ticker)
                continue
            tick_df.index = tick_df.index.tz_convert(ET)
            tick_df.columns = [c.capitalize() for c in tick_df.columns]

            for ts, row in tick_df.iterrows():
                synthetic = _FiveMinBar(
                    symbol=ticker,
                    timestamp=ts,
                    open=float(row["Open"]),
                    high=float(row["High"]),
                    low=float(row["Low"]),
                    close=float(row["Close"]),
                    volume=float(row["Volume"]),
                )
                with self._lock:
                    existing = self._history.get(ticker, pd.DataFrame())
                    if not existing.empty and ts in existing.index:
                        continue  # already have this bar from live stream
                    self._process_five_min_bar(synthetic)

            logger.info(
                "Catchup: %s has %d/%d opening bars",
                ticker,
                len(self._opening_buf.get(ticker, [])),
                self._opening_bars,
            )

    async def _handle_bar(self, bar):
        ticker = bar.symbol
        if ticker not in self._tickers:
            return

        ts = bar.timestamp.astimezone(ET)
        today = datetime.now(ET).date()

        with self._lock:
            if ts.date() != today:
                return

            actual_market_open = ET.localize(
                datetime.combine(today, datetime.strptime("09:30", "%H:%M").time())
            )
            if ts < actual_market_open:
                return

            # If we're past the opening range close and any ticker's buffer is
            # still incomplete (e.g. stream dropped during the opening window),
            # kick off a one-time historical catchup in a background thread.
            or_open = ET.localize(datetime.combine(today, self._opening_start))
            or_close = or_open + timedelta(minutes=self._opening_bars * 5)
            if ts >= or_close and not self._opening_catchup_done:
                any_incomplete = any(
                    not self._signal_fired.get(t)
                    and len(self._opening_buf.get(t, [])) < self._opening_bars
                    for t in self._tickers
                )
                if any_incomplete:
                    self._opening_catchup_done = True
                    logger.info(
                        "Opening range closed but buffers incomplete — starting historical catchup"
                    )
                    threading.Thread(
                        target=self._catch_up_all_opening_bars,
                        args=(today,),
                        daemon=True,
                    ).start()

            logger.debug(
                "1-min bar  %-6s  %s  O=%.2f H=%.2f L=%.2f C=%.2f  vol=%d",
                ticker,
                ts.strftime("%H:%M"),
                float(bar.open),
                float(bar.high),
                float(bar.low),
                float(bar.close),
                int(bar.volume),
            )

            # Determine which 5-min period this 1-min bar belongs to
            period_start = ts.replace(second=0, microsecond=0) - timedelta(
                minutes=ts.minute % 5
            )
            mbuf = self._minute_buf.setdefault(
                ticker, {"period_start": None, "bars": []}
            )

            if mbuf["period_start"] is None:
                mbuf["period_start"] = period_start

            if period_start == mbuf["period_start"]:
                mbuf["bars"].append(bar)
            else:
                # New 5-min period started: finalize and process the previous one
                if mbuf["bars"]:
                    five_min_bar = self._aggregate_bars(
                        ticker, mbuf["period_start"], mbuf["bars"]
                    )
                    logger.info(
                        "5-min bar  %-6s  %s  O=%.2f H=%.2f L=%.2f C=%.2f  (%d 1-min bars)",
                        ticker,
                        mbuf["period_start"].strftime("%H:%M"),
                        five_min_bar.open,
                        five_min_bar.high,
                        five_min_bar.low,
                        five_min_bar.close,
                        len(mbuf["bars"]),
                    )
                    self._process_five_min_bar(five_min_bar)
                mbuf["period_start"] = period_start
                mbuf["bars"] = [bar]

    def get_latest_bar(self, ticker: str) -> Optional[pd.Series]:
        df = self._history.get(ticker)
        if df is None or df.empty:
            return None
        return df.iloc[-1]

    def start(self):
        logger.info("Warming up historical bars for %s", self._tickers)
        self._warmup()
        if self._regime_filter:
            today = datetime.now(ET).date()
            lookback_start = today - timedelta(days=self._regime_ma * 3 + 10)
            self._bearish_regime_dates = build_bearish_regime_dates(
                lookback_start, today, regime_ma=self._regime_ma
            )
            logger.info(
                "Regime filter ON (QQQ MA%d): %d bearish dates in lookback",
                self._regime_ma,
                len(self._bearish_regime_dates),
            )
        self._stream = StockDataStream(
            self._api_key,
            self._secret_key,
            websocket_params={"ping_interval": 20, "ping_timeout": 40},
        )
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


def _place_with_fill_escalation(
    client: AlpacaAPIClient,
    ticker: str,
    option_symbol: str,
    option_type: str,
    contracts: int,
    order_action: str,
) -> dict:
    """
    Place a limit order at mid price, then escalate if unfilled:
      - After 60s unfilled: cancel + re-place at ask (buy) or bid (sell)
      - After another 60s unfilled: cancel + market order
    """
    is_buy = order_action == "BUY_OPEN"

    def _fetch_mid_bid_ask():
        quote_resp = client._option_data_client.get_option_latest_quote(
            OptionLatestQuoteRequest(symbol_or_symbols=[option_symbol])
        )
        q = quote_resp[option_symbol]
        bid = _D(q.bid_price)
        ask = _D(q.ask_price)
        mid = (bid + ask) / _D("2")
        return bid, ask, mid

    def _place_limit(price: Decimal) -> dict:
        rounded = price.quantize(_D("0.01"), rounding=ROUND_HALF_UP)
        return client.place_option_order(
            symbol=ticker,
            option_key=None,
            price=float(rounded),
            price_type="LIMIT",
            option_type=option_type,
            order_action=order_action,
            quantity=contracts,
            _option_symbol_override=option_symbol,
        )

    def _place_market() -> dict:
        return client.place_option_order(
            symbol=ticker,
            option_key=None,
            price_type="MARKET",
            option_type=option_type,
            order_action=order_action,
            quantity=contracts,
            _option_symbol_override=option_symbol,
        )

    def _is_filled(order_id: str) -> bool:
        try:
            status = client.order_status(order_id)
            return status.get("status") == "filled"
        except Exception:
            return False

    def _cancel_safely(order_id: str):
        try:
            client.cancel_order(order_id)
        except Exception:
            logger.warning(
                "Could not cancel order %s (may already be filled)", order_id
            )

    # Step 1: limit at mid
    try:
        bid, ask, mid = _fetch_mid_bid_ask()
        logger.info(
            "FILL_ESC step1 %s %s: bid=%s ask=%s mid=%s",
            order_action,
            option_symbol,
            bid,
            ask,
            mid.quantize(_D("0.01"), rounding=ROUND_HALF_UP),
        )
    except Exception:
        logger.warning(
            "Could not fetch quote for %s, falling back to market", option_symbol
        )
        return _place_market()

    order = _place_limit(mid)
    order_id = order.get("order_id")
    logger.info("FILL_ESC step1 order placed: id=%s", order_id)

    time.sleep(60)
    if _is_filled(order_id):
        logger.info("FILL_ESC step1 filled: %s", order_id)
        return order

    # Step 2: cancel + limit at ask (buy) or bid (sell)
    _cancel_safely(order_id)
    try:
        bid, ask, mid = _fetch_mid_bid_ask()
        aggressive_price = ask if is_buy else bid
        logger.info(
            "FILL_ESC step2 %s %s: aggressive_price=%s",
            order_action,
            option_symbol,
            aggressive_price.quantize(_D("0.01"), rounding=ROUND_HALF_UP),
        )
    except Exception:
        logger.warning(
            "Could not fetch quote for step2 %s, using market", option_symbol
        )
        return _place_market()

    order = _place_limit(aggressive_price)
    order_id = order.get("order_id")
    logger.info("FILL_ESC step2 order placed: id=%s", order_id)

    time.sleep(60)
    if _is_filled(order_id):
        logger.info("FILL_ESC step2 filled: %s", order_id)
        return order

    # Step 3: cancel + market
    _cancel_safely(order_id)
    logger.info(
        "FILL_ESC step3 %s %s: placing market order", order_action, option_symbol
    )
    order = _place_market()
    logger.info("FILL_ESC step3 market order placed: id=%s", order.get("order_id"))
    return order


class PositionMonitor:
    """Monitors open option positions and exits on stop conditions."""

    def __init__(
        self,
        alpaca_client: AlpacaAPIClient,
        signal_engine: LiveSignalEngine,
        simulate: bool = False,
        trailing_ma: str = TRAILING_MA,
        max_loss_pct: Optional[float] = MAX_LOSS_PCT,
        armed_ma20_exit: bool = ARMED_MA20_EXIT,
    ):
        self._client = alpaca_client
        self._signal_engine = signal_engine
        self._simulate = simulate
        self._trailing_ma = trailing_ma
        self._max_loss_pct = max_loss_pct
        self._armed_ma20_exit = armed_ma20_exit
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
        ma20 = latest.get("MA20")
        ma20_val = _D(ma20) if ma20 is not None and not pd.isna(ma20) else None
        ma50 = latest.get("MA50")
        ma50_val = _D(ma50) if ma50 is not None and not pd.isna(ma50) else None

        with self._lock:
            for pos in self._positions:
                if pos.ticker != ticker or pos.is_closed:
                    continue
                self._evaluate_stop(pos, close, ma20_val, ma50_val)

    def _evaluate_stop(
        self,
        pos: ActivePosition,
        close: Decimal,
        ma20: Optional[Decimal],
        ma50: Optional[Decimal],
    ):
        exit_reason = None

        # Max loss guard — highest priority, checked before all other exits
        if self._max_loss_pct is not None:
            entry = pos.entry_stock_price
            loss_pct = (
                (entry - close) / entry
                if pos.signal == "BULLISH"
                else (close - entry) / entry
            )
            if loss_pct >= _D(str(self._max_loss_pct)):
                self._close_position(pos, "max_loss")
                return

        if pos.signal == "BULLISH":
            if not pos.hard_stop_armed and close > pos.hard_stop_price:
                pos.hard_stop_armed = True
            if pos.hard_stop_armed and self._armed_ma20_exit:
                if ma20 is not None:
                    if close < ma20:
                        exit_reason = "trailing_stop_ma20"
                elif close <= pos.hard_stop_price:
                    exit_reason = "hard_stop"
            elif pos.hard_stop_armed and close <= pos.hard_stop_price:
                exit_reason = "hard_stop"
            elif not pos.hard_stop_armed and close <= pos.fallback_price:
                exit_reason = "fallback_20pct"
            elif (
                self._trailing_ma in ("ma20", "both")
                and ma20 is not None
                and ma20 > pos.hard_stop_price
                and close < ma20
            ):
                exit_reason = "trailing_stop_ma20"
            elif (
                self._trailing_ma in ("ma50", "both")
                and ma50 is not None
                and ma50 > pos.hard_stop_price
                and close < ma50
            ):
                exit_reason = "trailing_stop_ma50"
        else:
            if not pos.hard_stop_armed and close < pos.hard_stop_price:
                pos.hard_stop_armed = True
            if pos.hard_stop_armed and self._armed_ma20_exit:
                if ma20 is not None:
                    if close > ma20:
                        exit_reason = "trailing_stop_ma20"
                elif close >= pos.hard_stop_price:
                    exit_reason = "hard_stop"
            elif pos.hard_stop_armed and close >= pos.hard_stop_price:
                exit_reason = "hard_stop"
            elif not pos.hard_stop_armed and close >= pos.fallback_price:
                exit_reason = "fallback_20pct"
            elif (
                self._trailing_ma in ("ma20", "both")
                and ma20 is not None
                and ma20 < pos.or_low
                and close > ma20
            ):
                exit_reason = "trailing_stop_ma20"
            elif (
                self._trailing_ma in ("ma50", "both")
                and ma50 is not None
                and ma50 < pos.or_low
                and close > ma50
            ):
                exit_reason = "trailing_stop_ma50"

        if exit_reason:
            self._close_position(pos, exit_reason)

    def _close_position(self, pos: ActivePosition, reason: str):
        pos.is_closed = True
        pos.exit_reason = reason
        pos.exit_time = datetime.now(ET)
        logger.info(
            "EXIT %s %s reason=%s opt=%s contracts=%d",
            pos.ticker,
            pos.signal,
            reason,
            pos.option_symbol,
            pos.contracts,
        )
        mid = None
        exit_limit = None
        try:
            quote_resp = self._client._option_data_client.get_option_latest_quote(
                OptionLatestQuoteRequest(symbol_or_symbols=[pos.option_symbol])
            )
            quote = quote_resp[pos.option_symbol]
            bid = _D(quote.bid_price)
            ask = _D(quote.ask_price)
            mid = (bid + ask) / _D("2")
            logger.info(
                "EXIT QUOTE %s: bid=%s ask=%s mid=%s",
                pos.option_symbol,
                bid,
                ask,
                mid.quantize(_D("0.01"), rounding=ROUND_HALF_UP),
            )
            fallback = (ask * _D("0.98")).quantize(_D("0.01"), rounding=ROUND_HALF_UP)
            exit_limit = bid.quantize(_D("0.01"), rounding=ROUND_HALF_UP) or fallback
        except Exception:
            logger.exception(
                "Could not fetch exit quote for %s, using market order",
                pos.option_symbol,
            )

        if self._simulate:
            sim_mid = (
                mid.quantize(_D("0.01"), rounding=ROUND_HALF_UP)
                if mid is not None
                else _D("0")
            )
            pos.simulated_exit_mid = sim_mid
            _send_sms(
                f"[SIMULATE] SELL {pos.option_symbol} x{pos.contracts} reason={reason} @ ~{sim_mid}"
            )
            logger.info(
                "SIMULATE SELL_CLOSE %s contracts=%d simulated_fill=%.2f (no order placed)",
                pos.option_symbol,
                pos.contracts,
                sim_mid,
            )
            return

        try:
            option_type = "CALL" if pos.signal == "BULLISH" else "PUT"
            logger.info(
                "Placing SELL_CLOSE with fill escalation: %s %d contracts",
                pos.option_symbol,
                pos.contracts,
            )
            _send_sms(
                f"SELL {pos.option_symbol} x{pos.contracts} reason={reason} closing {pos.ticker}"
            )
            order = _place_with_fill_escalation(
                client=self._client,
                ticker=pos.ticker,
                option_symbol=pos.option_symbol,
                option_type=option_type,
                contracts=pos.contracts,
                order_action="SELL_CLOSE",
            )
            pos.exit_order_id = order.get("order_id")
            logger.info("Close order placed: %s", pos.exit_order_id)
        except Exception:
            logger.exception("Failed to place close order for %s", pos.option_symbol)

    def close_all(self, reason: str = "end_of_day"):
        with self._lock:
            for pos in self._positions:
                if not pos.is_closed:
                    self._close_position(pos, reason)

    def _fetch_option_mid(self, option_symbol: str) -> Optional[Decimal]:
        try:
            resp = self._client._option_data_client.get_option_latest_quote(
                OptionLatestQuoteRequest(symbol_or_symbols=[option_symbol])
            )
            q = resp[option_symbol]
            return (_D(q.bid_price) + _D(q.ask_price)) / _D("2")
        except Exception:
            return None

    def _refresh_fill_prices(self, positions: list):
        """Lazily fetch and cache order fill prices for live-mode positions."""
        for p in positions:
            if p.entry_fill_price is None and p.entry_order_id:
                try:
                    s = self._client.order_status(p.entry_order_id)
                    if s.get("filled_avg_price") is not None:
                        p.entry_fill_price = _D(str(s["filled_avg_price"]))
                except Exception:
                    pass
            if p.is_closed and p.exit_fill_price is None and p.exit_order_id:
                try:
                    s = self._client.order_status(p.exit_order_id)
                    if s.get("filled_avg_price") is not None:
                        p.exit_fill_price = _D(str(s["filled_avg_price"]))
                except Exception:
                    pass

    def print_status(self):
        now = datetime.now(ET)
        with self._lock:
            open_pos = [p for p in self._positions if not p.is_closed]
            closed_pos = [p for p in self._positions if p.is_closed]

        has_sim = any(p.simulated_entry_mid is not None for p in self._positions)

        if not has_sim:
            self._refresh_fill_prices(open_pos + closed_pos)

        def _fmt(dt: Optional[datetime]) -> str:
            return dt.strftime("%H:%M") if dt else "—"

        def _pnl(
            entry: Optional[Decimal],
            exit_: Optional[Decimal],
            signal: str,
            contracts: int,
        ) -> Optional[Decimal]:
            if entry is None or exit_ is None:
                return None
            raw = exit_ - entry
            return raw * _D(contracts) * _D("100")

        def _pnl_str(pnl: Optional[Decimal]) -> str:
            if pnl is None:
                return ""
            sign = "+" if pnl >= 0 else ""
            return f"  {sign}${pnl:.2f}"

        bar = "━" * 82
        sep = "─" * 80
        print(f"\n{bar}")
        print(
            f"  POSITION STATUS  {now.strftime('%H:%M ET')}  |  "
            f"open={len(open_pos)}  closed={len(closed_pos)}"
        )
        print(bar)

        if open_pos:
            print("  OPEN POSITIONS")
            print(f"  {sep}")
            for p in open_pos:
                if has_sim:
                    entry_price = p.simulated_entry_mid
                else:
                    entry_price = p.entry_fill_price
                    current_mid = self._fetch_option_mid(p.option_symbol)
                unrealized = (
                    _pnl(entry_price, p.simulated_entry_mid, p.signal, p.contracts)
                    if has_sim
                    else _pnl(entry_price, current_mid, p.signal, p.contracts)
                )
                entry_str = f"  entry=${entry_price:.2f}" if entry_price else ""
                unreal_str = (
                    f"  unreal={_pnl_str(unrealized).strip()}"
                    if unrealized is not None
                    else ""
                )
                print(
                    f"  {p.ticker:<7} {p.signal:<9} {p.option_symbol:<26} "
                    f"x{p.contracts}  in={_fmt(p.entry_time)}{entry_str}{unreal_str}"
                )
        else:
            print("  No open positions")

        if closed_pos:
            print(f"\n  CLOSED POSITIONS")
            print(f"  {sep}")
            total_pnl = _D("0")
            for p in closed_pos:
                if has_sim:
                    entry_price = p.simulated_entry_mid
                    exit_price = p.simulated_exit_mid
                else:
                    entry_price = p.entry_fill_price
                    exit_price = p.exit_fill_price
                pnl = _pnl(entry_price, exit_price, p.signal, p.contracts)
                if pnl is not None:
                    total_pnl += pnl
                print(
                    f"  {p.ticker:<7} {p.signal:<9} {p.option_symbol:<26} "
                    f"x{p.contracts}  {_fmt(p.entry_time)}→{_fmt(p.exit_time)}"
                    f"  {p.exit_reason}{_pnl_str(pnl)}"
                )
            any_pnl = any(
                (
                    _pnl(
                        p.simulated_entry_mid if has_sim else p.entry_fill_price,
                        p.simulated_exit_mid if has_sim else p.exit_fill_price,
                        p.signal,
                        p.contracts,
                    )
                )
                is not None
                for p in closed_pos
            )
            if any_pnl:
                sign = "+" if total_pnl >= 0 else ""
                print(f"  {sep}")
                print(f"  Running P&L: {sign}${total_pnl:.2f}")

        print(f"{bar}\n")

    def print_summary(self):
        has_sim = any(pos.simulated_entry_mid is not None for pos in self._positions)

        def _fmt_time(dt: Optional[datetime]) -> str:
            return dt.strftime("%H:%M") if dt else "—"

        if has_sim:
            width = 114
            print(f"\n{'=' * width}")
            print("  DAILY TRADE SUMMARY  [SIMULATE MODE]")
            print(f"{'=' * width}")
            print(
                f"  {'Ticker':<7} {'Signal':<9} {'Option':<26} {'Qty':>4}"
                f"  {'Entry':>5} {'Exit':>5}  {'EntryMid':>9} {'ExitMid':>9} {'Opt P&L':>10}  Exit Reason"
            )
            print(f"  {'─' * 112}")
            for pos in self._positions:
                entry_mid = pos.simulated_entry_mid
                exit_mid = pos.simulated_exit_mid
                if entry_mid is not None and exit_mid is not None:
                    raw_pnl = (
                        (exit_mid - entry_mid)
                        if pos.signal == "BULLISH"
                        else (entry_mid - exit_mid)
                    )
                    pnl_total = raw_pnl * _D(pos.contracts) * _D("100")
                    pnl_str = (
                        f"+${pnl_total:.2f}"
                        if pnl_total >= 0
                        else f"-${abs(pnl_total):.2f}"
                    )
                    entry_str = f"${entry_mid:.2f}"
                    exit_str = f"${exit_mid:.2f}"
                else:
                    pnl_str = entry_str = exit_str = "—"
                print(
                    f"  {pos.ticker:<7} {pos.signal:<9} {pos.option_symbol:<26} "
                    f"{pos.contracts:>4}"
                    f"  {_fmt_time(pos.entry_time):>5} {_fmt_time(pos.exit_time):>5}"
                    f"  {entry_str:>9} {exit_str:>9} {pnl_str:>10}"
                    f"  {pos.exit_reason or 'open'}"
                )
            print(f"{'=' * width}\n")
        else:
            width = 86
            print(f"\n{'=' * width}")
            print("  DAILY TRADE SUMMARY")
            print(f"{'=' * width}")
            print(
                f"  {'Ticker':<7} {'Signal':<9} {'Option':<26} {'Qty':>4}"
                f"  {'Entry':>5} {'Exit':>5}  Exit Reason"
            )
            print(f"  {'─' * 84}")
            for pos in self._positions:
                print(
                    f"  {pos.ticker:<7} {pos.signal:<9} {pos.option_symbol:<26} "
                    f"{pos.contracts:>4}"
                    f"  {_fmt_time(pos.entry_time):>5} {_fmt_time(pos.exit_time):>5}"
                    f"  {pos.exit_reason or 'open'}"
                )
            print(f"{'=' * width}\n")


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
      5. Monitor stops intraday; close on hard stop, MA trailing stop, or EOD.
    """

    def __init__(
        self,
        alpaca_client: AlpacaAPIClient,
        is_paper: bool = True,
        stop_pct: float = float(STOP_PCT),
        simulate: bool = False,
        opening_start_time: str = OPENING_START_TIME,
        trailing_ma: str = TRAILING_MA,
        max_loss_pct: Optional[float] = MAX_LOSS_PCT,
        armed_ma20_exit: bool = ARMED_MA20_EXIT,
        regime_filter: bool = REGIME_FILTER,
        regime_ma: int = REGIME_MA,
        rank_weighted_sizing: bool = RANK_WEIGHTED_SIZING,
    ):
        self._client = alpaca_client
        self._api_key = alpaca_client._api_key
        self._secret_key = alpaca_client._secret_key
        self._stop_pct = _D(str(stop_pct))
        self._simulate = simulate
        self._opening_start_time = opening_start_time
        self._trailing_ma = trailing_ma
        self._max_loss_pct = max_loss_pct
        self._armed_ma20_exit = armed_ma20_exit
        self._regime_filter = regime_filter
        self._regime_ma = regime_ma
        self._rank_weighted_sizing = rank_weighted_sizing
        self._monitor: PositionMonitor = None
        self._signal_engine: LiveSignalEngine = None
        self._pending_signals: dict = {}
        self._signal_lock = threading.Lock()
        self._rolling_stats: dict = {}
        self._signal_collection_deadline: Optional[datetime] = None
        self._open_position_count: int = 0

    def _enter_position(self, event: SignalEvent, rank: int = 0):
        """Select contract, size, place order, and register with position monitor."""
        logger.info(
            "Entering position: %s %s @ %.2f (rank=%d)",
            event.ticker,
            event.signal,
            float(event.stock_price),
            rank,
        )
        try:
            selector = OptionContractSelector(self._client)
            option_symbol = selector.select(
                event.ticker, event.signal, event.stock_price
            )
        except Exception:
            logger.exception("Could not select option contract for %s", event.ticker)
            with self._signal_lock:
                self._open_position_count -= 1
            return

        try:
            sizer = PositionSizer(self._client)
            if self._rank_weighted_sizing and rank < len(RANK_WEIGHTS):
                capital_weight = _D(str(RANK_WEIGHTS[rank]))
            else:
                capital_weight = _D("1")
            contracts, limit_price = sizer.compute(option_symbol, capital_weight)
        except Exception:
            logger.exception("Could not size position for %s", option_symbol)
            with self._signal_lock:
                self._open_position_count -= 1
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
            with self._signal_lock:
                self._open_position_count -= 1
            return

        bull_hard_stop = event.or_high - self._stop_pct * event.or_range
        bear_hard_stop = event.or_low + self._stop_pct * event.or_range
        bull_fallback = event.or_high - _D("0.20") * event.or_range
        bear_fallback = event.or_low + _D("0.20") * event.or_range

        sim_entry_mid = order.get("simulated_fill_mid") if self._simulate else None

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
            hard_stop_price=(
                bull_hard_stop if event.signal == "BULLISH" else bear_hard_stop
            ),
            fallback_price=(
                bull_fallback if event.signal == "BULLISH" else bear_fallback
            ),
            entry_time=datetime.now(ET),
            simulated_entry_mid=sim_entry_mid,
        )
        self._monitor.add_position(pos)

    def _on_signal(self, event: SignalEvent):
        now = datetime.now(ET)
        with self._signal_lock:
            if (
                self._signal_collection_deadline
                and now < self._signal_collection_deadline
            ):
                self._pending_signals[event.ticker] = event
                logger.info("Buffered signal: %s %s", event.ticker, event.signal)
                return
            if self._open_position_count >= MAX_ACTIVE_SYMBOLS:
                logger.info(
                    "Max positions reached (%d), skipping %s",
                    MAX_ACTIVE_SYMBOLS,
                    event.ticker,
                )
                return
            self._open_position_count += 1

        self._enter_position(event, rank=0)

    def _signal_selection_loop(self):
        """Wait for signal collection deadline, rank buffered signals, enter top N."""
        deadline = self._signal_collection_deadline
        logger.info(
            "Signal collection window open until %s ET",
            deadline.strftime("%H:%M:%S"),
        )
        while datetime.now(ET) < deadline:
            time.sleep(0.5)

        with self._signal_lock:
            pending = dict(self._pending_signals)
            self._pending_signals.clear()

        if not pending:
            logger.info("Signal collection window closed: no signals buffered")
            return

        logger.info(
            "Signal collection window closed: ranking %d buffered signal(s)",
            len(pending),
        )

        scored = []
        for ticker, event in pending.items():
            stats = self._rolling_stats.get(ticker, {})
            if stats.get("ev_trade", 0) <= 0:
                logger.info(
                    "Skipping %s: ev_trade=%.3f <= 0", ticker, stats.get("ev_trade", 0)
                )
                continue
            midpoint = (event.or_high + event.or_low) / _D("2")
            entry_vs_mid_pct = (
                float(abs(event.entry_price - midpoint) / midpoint * 100)
                if midpoint != 0
                else 0.0
            )
            or_range_pct = (
                float(event.or_range / event.entry_price * 100)
                if event.entry_price != 0
                else 0.0
            )
            sig_dict = {
                "entry_vs_mid_pct": entry_vs_mid_pct,
                "or_range_pct": or_range_pct,
            }
            score = score_ticker(sig_dict, stats)
            scored.append((score, ticker, event))
            logger.info(
                "Ranked %s: score=%.3f ev_trade=%.3f",
                ticker,
                score,
                stats.get("ev_trade", 0),
            )

        scored.sort(key=lambda x: x[0], reverse=True)

        for rank, (score, ticker, event) in enumerate(scored):
            with self._signal_lock:
                if self._open_position_count >= MAX_ACTIVE_SYMBOLS:
                    logger.info("Max positions reached, stopping selection")
                    break
                self._open_position_count += 1
            logger.info("Selecting %s from buffer (score=%.3f rank=%d)", ticker, score, rank)
            self._enter_position(event, rank=rank)

    def _place_entry(
        self,
        ticker: str,
        signal: str,
        option_symbol: str,
        contracts: int,
        limit_price: Decimal,
    ) -> dict:
        option_type = "CALL" if signal == "BULLISH" else "PUT"

        entry_mid = limit_price
        try:
            quote_resp = self._client._option_data_client.get_option_latest_quote(
                OptionLatestQuoteRequest(symbol_or_symbols=[option_symbol])
            )
            quote = quote_resp[option_symbol]
            bid = _D(quote.bid_price)
            ask = _D(quote.ask_price)
            entry_mid = (bid + ask) / _D("2")
            logger.info(
                "ENTRY QUOTE %s: bid=%s ask=%s mid=%s",
                option_symbol,
                bid,
                ask,
                entry_mid.quantize(_D("0.01"), rounding=ROUND_HALF_UP),
            )
        except Exception:
            logger.warning(
                "Could not fetch entry quote for %s, using sizer mid", option_symbol
            )

        if self._simulate:
            sim_mid = entry_mid.quantize(_D("0.01"), rounding=ROUND_HALF_UP)
            _send_sms(
                f"[SIMULATE] BUY {option_type} {option_symbol} x{contracts} @ ~{sim_mid}"
            )
            logger.info(
                "SIMULATE BUY_OPEN %s %s contracts=%d simulated_fill=%.2f (no order placed)",
                option_symbol,
                option_type,
                contracts,
                sim_mid,
            )
            return {
                "order_id": f"sim-{option_symbol}",
                "status": "simulated",
                "simulated_fill_mid": sim_mid,
            }

        logger.info(
            "Placing BUY_OPEN with fill escalation: %s %s %d",
            option_symbol,
            option_type,
            contracts,
        )
        _send_sms(f"BUY {option_type} {option_symbol} x{contracts} entering {ticker}")
        return _place_with_fill_escalation(
            client=self._client,
            ticker=ticker,
            option_symbol=option_symbol,
            option_type=option_type,
            contracts=contracts,
            order_action="BUY_OPEN",
        )

    def _monitor_loop(self, active_tickers: list):
        """Polls PositionMonitor on each new bar arrival, and forces EOD close."""
        eod_h, eod_m = [int(x) for x in EOD_EXIT_TIME.split(":")]
        last_status_print = datetime.now(ET)
        while True:
            now = datetime.now(ET)
            if now.hour > eod_h or (now.hour == eod_h and now.minute >= eod_m):
                logger.info("EOD: force-closing all positions")
                self._monitor.close_all(reason="end_of_day")
                break

            for ticker in active_tickers:
                self._monitor.on_bar(ticker)

            if (now - last_status_print).total_seconds() >= 300:
                self._monitor.print_status()
                last_status_print = now

            time.sleep(30)

    def run(self, tickers_override: list = None):
        api_key = self._api_key
        secret_key = self._secret_key

        all_tickers = tickers_override or TICKERS

        ticker_selector = TickerSelector(
            tickers=all_tickers,
            top_n=MAX_ACTIVE_SYMBOLS,
            stop_pct=float(self._stop_pct),
            opening_start_time=self._opening_start_time,
        )
        pre_market_picks = ticker_selector.select()
        self._rolling_stats = ticker_selector.rolling_stats
        print(f"\nPre-market top picks: {pre_market_picks}")
        print(f"Subscribing all {len(all_tickers)} tickers to live stream...")

        today = datetime.now(ET).date()
        opening_start = datetime.strptime(self._opening_start_time, "%H:%M").time()
        or_open_et = ET.localize(datetime.combine(today, opening_start))
        or_close_et = or_open_et + timedelta(minutes=OPENING_BARS * 5)
        self._signal_collection_deadline = or_close_et + timedelta(
            minutes=SIGNAL_BUFFER_MINUTES
        )
        logger.info(
            "Signal collection deadline: %s ET",
            self._signal_collection_deadline.strftime("%H:%M:%S"),
        )

        self._signal_engine = LiveSignalEngine(
            tickers=all_tickers,
            api_key=api_key,
            secret_key=secret_key,
            opening_bars=OPENING_BARS,
            bearish_ma200=BEARISH_MA200,
            on_signal=self._on_signal,
            opening_start_time=self._opening_start_time,
            regime_filter=self._regime_filter,
            regime_ma=self._regime_ma,
        )
        self._monitor = PositionMonitor(
            self._client,
            self._signal_engine,
            simulate=self._simulate,
            trailing_ma=self._trailing_ma,
            max_loss_pct=self._max_loss_pct,
            armed_ma20_exit=self._armed_ma20_exit,
        )

        self._signal_engine.start()

        selection_thread = threading.Thread(
            target=self._signal_selection_loop, daemon=True
        )
        selection_thread.start()

        monitor_thread = threading.Thread(
            target=self._monitor_loop, args=(all_tickers,), daemon=True
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
# Daemon helpers
# ---------------------------------------------------------------------------

_PID_FILE = os.path.expanduser("~/.op_momentum_daemon.pid")
_LOG_FILE = os.path.join(
    os.path.dirname(__file__), "..", "..", "logs", "op_momentum.log"
)
_CONFIG_FILE = os.path.join(os.path.dirname(__file__), "config.json")


def _load_config(config_file: str = _CONFIG_FILE):
    """
    Load credentials from config.json and inject them into the environment
    for any key not already set. Environment variables always take precedence.

    Config file format (alpha_tech_tracker/op_momentum_strategy/config.json):
        {
          "alpaca": {
            "api_key": "YOUR_KEY",
            "secret_key": "YOUR_SECRET"
          }
        }
    """
    if not os.path.exists(config_file):
        return

    with open(config_file) as f:
        cfg = json.load(f)

    alpaca = cfg.get("alpaca", {})
    mapping = {
        "api_key": "ALPACA_API_KEY",
        "secret_key": "ALPACA_SECRET_KEY",
    }
    for cfg_key, env_key in mapping.items():
        if alpaca.get(cfg_key) and not os.environ.get(env_key):
            os.environ[env_key] = alpaca[cfg_key]

    _clicksend_cfg.clear()
    _clicksend_cfg.update(cfg.get("clicksend", {}))


def _send_sms(message: str):
    if not _clicksend_cfg.get("enabled"):
        return
    username = _clicksend_cfg.get("username")
    api_key = _clicksend_cfg.get("api_key")
    to_num = _clicksend_cfg.get("to_number")
    if not all([username, api_key, to_num]):
        logger.debug("SMS skipped — clicksend config incomplete")
        return
    try:
        import clicksend_client

        configuration = clicksend_client.Configuration()
        configuration.username = username
        configuration.password = api_key
        api = clicksend_client.SMSApi(clicksend_client.ApiClient(configuration))
        sms = clicksend_client.SmsMessageCollection(
            messages=[clicksend_client.SmsMessage(to=to_num, body=message)]
        )
        api.sms_send_post(sms)
        logger.info("SMS sent: %s", message)
    except Exception:
        logger.warning("SMS failed", exc_info=True)


def _write_pid(pid_file: str):
    with open(pid_file, "w") as f:
        f.write(str(os.getpid()))


def _read_pid(pid_file: str):
    try:
        with open(pid_file) as f:
            return int(f.read().strip())
    except (FileNotFoundError, ValueError):
        return None


def _remove_pid(pid_file: str):
    try:
        os.remove(pid_file)
    except FileNotFoundError:
        pass


def _is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def _daemonize(log_file: str):
    """Double-fork to detach from terminal and run as a background daemon."""
    pid = os.fork()
    if pid > 0:
        sys.exit(0)

    os.setsid()

    pid = os.fork()
    if pid > 0:
        sys.exit(0)

    sys.stdout.flush()
    sys.stderr.flush()

    with open(os.devnull) as dev_null:
        os.dup2(dev_null.fileno(), sys.stdin.fileno())

    log_fd = open(log_file, "a")
    os.dup2(log_fd.fileno(), sys.stdout.fileno())
    os.dup2(log_fd.fileno(), sys.stderr.fileno())
    log_fd.close()


def _daemon_stop(pid_file: str, log_file: str):
    pid = _read_pid(pid_file)
    if pid is None or not _is_running(pid):
        print("Daemon is not running.")
        _remove_pid(pid_file)
        return

    print(f"Stopping daemon (PID {pid})...")
    os.kill(pid, signal.SIGTERM)

    for _ in range(20):
        time.sleep(0.5)
        if not _is_running(pid):
            break
    else:
        os.kill(pid, signal.SIGKILL)
        print(f"Daemon (PID {pid}) force-killed.")
        _remove_pid(pid_file)
        return

    _remove_pid(pid_file)
    print(f"Daemon stopped (PID {pid}).")


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


def parse_args():
    parser = argparse.ArgumentParser(description="OpMomentum live trade engine")
    parser.add_argument(
        "action",
        choices=["run", "start", "stop", "status", "restart"],
        help="run: foreground | start: daemon | stop | status | restart",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        default=False,
        help="Use live trading account (default: paper trading)",
    )
    parser.add_argument(
        "--simulate",
        action="store_true",
        default=False,
        help="Simulate order fills at mid bid/ask — no real orders placed",
    )
    parser.add_argument(
        "--tickers",
        nargs="+",
        default=None,
        help="Override ticker universe, e.g. --tickers NVDA CRWD",
    )
    parser.add_argument(
        "--stop-pct",
        type=float,
        default=float(STOP_PCT),
        help=f"Hard stop as fraction of OR range (default: {float(STOP_PCT)})",
    )
    parser.add_argument(
        "--trailing-ma",
        type=str,
        default=TRAILING_MA,
        choices=["ma20", "ma50", "both"],
        help="Trailing MA stop: ma20, ma50, or both (default: ma20)",
    )
    parser.add_argument(
        "--max-loss-pct",
        type=float,
        default=MAX_LOSS_PCT,
        help="Per-trade max loss as a fraction of entry stock price (e.g. 0.02 = 2%%). Default: disabled.",
    )
    parser.add_argument(
        "--armed-ma20-exit",
        action="store_true",
        default=ARMED_MA20_EXIT,
        help="Once hard stop is armed, use MA20 as trailing exit instead of hard_stop_price. Default: off.",
    )
    parser.add_argument(
        "--regime-filter",
        action="store_true",
        default=REGIME_FILTER,
        help="Suppress BULLISH signals on days when QQQ is below its N-day MA. Default: off.",
    )
    parser.add_argument(
        "--regime-ma",
        type=int,
        default=REGIME_MA,
        help=f"N-day MA period for QQQ regime filter (default: {REGIME_MA}).",
    )
    parser.add_argument(
        "--rank-weighted-sizing",
        action="store_true",
        default=RANK_WEIGHTED_SIZING,
        help=f"Weight position size by ticker rank using {RANK_WEIGHTS} (default: off).",
    )
    parser.add_argument(
        "--opening-start",
        type=str,
        default=OPENING_START_TIME,
        help=f"Opening window start time HH:MM ET (default: {OPENING_START_TIME})",
    )
    parser.add_argument(
        "--pid-file",
        type=str,
        default=_PID_FILE,
        help=f"PID file path (default: {_PID_FILE})",
    )
    parser.add_argument(
        "--log-file",
        type=str,
        default=_LOG_FILE,
        help=f"Log file path (default: {_LOG_FILE})",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    _load_config()

    if args.action == "run":
        logging.basicConfig(
            level=getattr(logging, args.log_level),
            format="%(asctime)s %(levelname)s %(name)s — %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        is_paper = not (args.live or args.simulate)
        client = AlpacaAPIClient(is_paper_trading=is_paper)
        engine = OpMomentumTradeEngine(
            alpaca_client=client,
            is_paper=is_paper,
            stop_pct=args.stop_pct,
            simulate=args.simulate,
            opening_start_time=args.opening_start,
            trailing_ma=args.trailing_ma,
            max_loss_pct=args.max_loss_pct,
            armed_ma20_exit=args.armed_ma20_exit,
            regime_filter=args.regime_filter,
            regime_ma=args.regime_ma,
            rank_weighted_sizing=args.rank_weighted_sizing,
        )
        engine.run(tickers_override=args.tickers)
        sys.exit(0)

    if args.action == "status":
        pid = _read_pid(args.pid_file)
        if pid and _is_running(pid):
            print(f"Daemon running (PID {pid}) — log: {args.log_file}")
        else:
            print("Daemon is not running.")
        sys.exit(0)

    if args.action == "stop":
        _daemon_stop(args.pid_file, args.log_file)
        sys.exit(0)

    if args.action == "restart":
        _daemon_stop(args.pid_file, args.log_file)

    # start / restart — check not already running
    existing_pid = _read_pid(args.pid_file)
    if existing_pid and _is_running(existing_pid):
        print(
            f"Daemon already running (PID {existing_pid}). Use 'restart' or 'stop' first."
        )
        sys.exit(1)

    print(f"Starting daemon — logs: {args.log_file}")
    _daemonize(args.log_file)

    # --- daemon process only beyond this point ---
    _write_pid(args.pid_file)

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.FileHandler(args.log_file)],
    )
    logger.info(
        "Daemon started — api_key_set=%s config_file=%s",
        bool(os.environ.get("ALPACA_API_KEY")),
        _CONFIG_FILE,
    )

    try:
        is_paper = not (args.live or args.simulate)
        client = AlpacaAPIClient(is_paper_trading=is_paper)
        engine = OpMomentumTradeEngine(
            alpaca_client=client,
            is_paper=is_paper,
            stop_pct=args.stop_pct,
            simulate=args.simulate,
            opening_start_time=args.opening_start,
            trailing_ma=args.trailing_ma,
            max_loss_pct=args.max_loss_pct,
            armed_ma20_exit=args.armed_ma20_exit,
            regime_filter=args.regime_filter,
            regime_ma=args.regime_ma,
            rank_weighted_sizing=args.rank_weighted_sizing,
        )
        engine.run(tickers_override=args.tickers)
    finally:
        _remove_pid(args.pid_file)

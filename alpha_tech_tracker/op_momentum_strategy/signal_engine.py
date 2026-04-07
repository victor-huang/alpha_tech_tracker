import logging
import threading
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
import pytz

from alpaca.data.enums import DataFeed
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.live import StockDataStream
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

from alpha_tech_tracker.op_momentum_strategy.op_momentum_backtest import (
    build_bearish_regime_dates,
)

from .bar_recorder import BarRecorder
from .config import (
    BEARISH_MA200,
    MA_WARMUP_DAYS,
    OPENING_BARS,
    OPENING_START_TIME,
    REGIME_FILTER,
    REGIME_MA,
)
from .models import SignalEvent, _D, _FiveMinBar
from .replay import _now_et

logger = logging.getLogger(__name__)

ET = pytz.timezone("America/New_York")


class LiveSignalEngine:
    """
    Watches live 5-min bars for a set of tickers.
    Fires SignalEvent callbacks after each window's opening range closes.

    Supports multiple intraday windows via the `windows` parameter. Each window is a dict:
        {"label": str, "opening_start": str, "opening_bars": int, "on_signal": callable}

    When `windows` is omitted, falls back to single-window mode using the legacy
    `opening_bars`, `opening_start_time`, and `on_signal` parameters.
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
        windows: list = None,
        bar_recorder: BarRecorder = None,
        or_bar_lookback: int = 3,
    ):
        self._tickers = tickers
        self._bearish_ma200 = bearish_ma200
        self._regime_filter = regime_filter
        self._regime_ma = regime_ma
        self._bearish_regime_dates: set = set()
        self._api_key = api_key
        self._secret_key = secret_key

        if windows:
            self._windows = [
                {
                    **w,
                    "_opening_start_t": datetime.strptime(
                        w["opening_start"], "%H:%M"
                    ).time(),
                }
                for w in windows
            ]
        else:
            self._windows = [
                {
                    "label": "W1",
                    "opening_start": opening_start_time,
                    "opening_bars": opening_bars,
                    "on_signal": on_signal,
                    "_opening_start_t": datetime.strptime(
                        opening_start_time, "%H:%M"
                    ).time(),
                }
            ]

        self._history: dict = {}
        self._opening_buf: dict = {
            w["label"]: {t: [] for t in tickers} for w in self._windows
        }
        self._signal_fired: dict = {
            w["label"]: {t: False for t in tickers} for w in self._windows
        }
        self._opening_catchup_done: dict = {w["label"]: False for w in self._windows}
        self._minute_buf: dict = {
            t: {"period_start": None, "bars": []} for t in tickers
        }
        self._or_bar_lookback = or_bar_lookback
        self._session_date = _now_et().date()
        self._stream: StockDataStream = None
        self._lock = threading.Lock()
        self._bar_recorder = bar_recorder

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

    def _try_fire_signal(self, ticker: str, latest: pd.Series, win: dict):
        buf = self._opening_buf[win["label"]][ticker]
        or_high = _D(max(b.high for b in buf))
        or_low = _D(min(b.low for b in buf))
        or_range = or_high - or_low
        # Apply or_bar_lookback adjustment: if the OR is unusually tight relative
        # to the N bars immediately before the window, expand effective_or_range to
        # match the backtest's stop/fallback price computation.
        effective_or_range = or_range
        if self._or_bar_lookback > 0:
            opening_start_t = win["_opening_start_t"]
            hist = self._history.get(ticker)
            if hist is not None and not hist.empty:
                today = _now_et().date()
                day_bars = hist[hist.index.date == today]
                pre_opening = day_bars[day_bars.index.time < opening_start_t].tail(
                    self._or_bar_lookback
                )
                if not pre_opening.empty:
                    avg_recent = float(
                        (pre_opening["High"] - pre_opening["Low"]).mean()
                    )
                    if float(or_range) < avg_recent / 4:
                        effective_or_range = _D(str(avg_recent))
        midpoint = (or_high + or_low) / _D("2")
        bottom_30 = or_low + _D("0.20") * or_range

        close = _D(latest["Close"])
        ma20 = latest["MA20"]
        ma50 = latest["MA50"]
        ma200 = latest["MA200"]

        if pd.isna(ma20) or pd.isna(ma200):
            logger.info("%s [%s]: MA not ready, skipping signal", ticker, win["label"])
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
                "%s [%s]: NEUTRAL — close=%s midpoint=%s or_low=%s bottom_30=%s",
                ticker,
                win["label"],
                close,
                midpoint,
                or_low,
                bottom_30,
            )
            return

        if (
            signal == "BULLISH"
            and _now_et().date() in self._bearish_regime_dates
        ):
            logger.info(
                "%s [%s]: BULLISH signal suppressed by regime filter (QQQ bearish)",
                ticker,
                win["label"],
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
            or_range=effective_or_range,
            ma50_at_signal=ma50_val,
        )
        logger.info(
            "SIGNAL [%s] %s %s close=%s or_high=%s or_low=%s",
            win["label"],
            ticker,
            signal,
            close,
            or_high,
            or_low,
        )
        on_signal = win.get("on_signal")
        if on_signal:
            on_signal(event)

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
        latest = self._append_bar(ticker, bar)

        bar_time = bar.timestamp.astimezone(ET).time()

        for win in self._windows:
            label = win["label"]
            if self._signal_fired[label].get(ticker):
                continue
            if bar_time < win["_opening_start_t"]:
                continue

            buf = self._opening_buf[label][ticker]
            if len(buf) < win["opening_bars"]:
                buf.append(bar)
                logger.debug(
                    "%s [%s]: opening bar %d/%d",
                    ticker,
                    label,
                    len(buf),
                    win["opening_bars"],
                )

            if len(buf) == win["opening_bars"]:
                self._signal_fired[label][ticker] = True
                self._try_fire_signal(ticker, latest, win)

    def _catch_up_opening_bars_for_window(self, today, win: dict):
        label = win["label"]
        or_start = ET.localize(datetime.combine(today, win["_opening_start_t"]))
        or_end = or_start + timedelta(minutes=win["opening_bars"] * 5)
        logger.info(
            "Catching up [%s] opening bars for all tickers (%s–%s ET)",
            label,
            or_start.strftime("%H:%M"),
            or_end.strftime("%H:%M"),
        )

        # OR bar period-start timestamps in chronological order
        or_bar_period_starts = [
            or_start + timedelta(minutes=i * 5)
            for i in range(win["opening_bars"])
        ]
        # For the most recent 2 OR bars, prefer client-side aggregated data from
        # _minute_buf rather than querying Alpaca, which may return a partial
        # in-progress bar before the period has fully closed.
        recent_periods = set(or_bar_period_starts[-2:])

        # Track which (ticker, period) pairs were actually injected in pass 1 so
        # that pass 2 only skips those — not periods that _minute_buf couldn't
        # serve (e.g. when the engine started late and _minute_buf has moved on
        # to a later period, leaving an earlier recent period uncovered).
        client_covered: dict = {}  # ticker -> set of period_ts

        for ticker in self._tickers:
            if self._signal_fired[label].get(ticker):
                continue
            for period_ts in sorted(recent_periods):
                with self._lock:
                    existing = self._history.get(ticker, pd.DataFrame())
                    if not existing.empty and period_ts in existing.index:
                        client_covered.setdefault(ticker, set()).add(period_ts)
                        continue
                    mbuf = self._minute_buf.get(
                        ticker, {"period_start": None, "bars": []}
                    )
                    if mbuf["period_start"] == period_ts and mbuf["bars"]:
                        five_min = self._aggregate_bars(
                            ticker, period_ts, mbuf["bars"]
                        )
                        logger.info(
                            "Catchup [%s]: %s using client-side bar at %s (%d 1-min bars)",
                            label,
                            ticker,
                            period_ts.strftime("%H:%M"),
                            len(mbuf["bars"]),
                        )
                        self._process_five_min_bar(five_min)
                        client_covered.setdefault(ticker, set()).add(period_ts)

        # Check which tickers still need Alpaca for bars not covered client-side
        tickers_need_api = [
            t
            for t in self._tickers
            if not self._signal_fired[label].get(t)
            and len(self._opening_buf[label].get(t, [])) < win["opening_bars"]
        ]
        if not tickers_need_api:
            logger.info(
                "Catchup [%s]: all tickers served from client-side data", label
            )
            for ticker in self._tickers:
                logger.info(
                    "Catchup [%s]: %s has %d/%d opening bars",
                    label,
                    ticker,
                    len(self._opening_buf[label].get(ticker, [])),
                    win["opening_bars"],
                )
            return

        hist_client = StockHistoricalDataClient(self._api_key, self._secret_key)
        request = StockBarsRequest(
            symbol_or_symbols=tickers_need_api,
            timeframe=TimeFrame(amount=5, unit=TimeFrameUnit.Minute),
            start=or_start,
            end=or_end,
            feed=DataFeed.IEX,
        )
        try:
            bars = hist_client.get_stock_bars(request)
            all_df = bars.df
        except Exception:
            logger.exception("Failed to fetch opening bar catchup data for [%s]", label)
            return

        for ticker in tickers_need_api:
            if self._signal_fired[label].get(ticker):
                continue
            try:
                tick_df = all_df.xs(ticker, level=0).copy()
            except KeyError:
                logger.warning("No catchup data for %s [%s]", ticker, label)
                continue
            tick_df.index = tick_df.index.tz_convert(ET)
            tick_df.columns = [c.capitalize() for c in tick_df.columns]

            for ts, row in tick_df.iterrows():
                # Skip only bars that were actually served from _minute_buf in
                # pass 1. If a recent period wasn't covered there (e.g. engine
                # started late and _minute_buf moved past it), Alpaca fills it.
                if ts in client_covered.get(ticker, set()):
                    continue
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
                        continue
                    self._process_five_min_bar(synthetic)

            logger.info(
                "Catchup [%s]: %s has %d/%d opening bars",
                label,
                ticker,
                len(self._opening_buf[label].get(ticker, [])),
                win["opening_bars"],
            )

    async def _handle_bar(self, bar):
        ticker = bar.symbol
        if ticker not in self._tickers:
            return

        ts = bar.timestamp.astimezone(ET)
        today = _now_et().date()

        with self._lock:
            if ts.date() != today:
                return

            actual_market_open = ET.localize(
                datetime.combine(today, datetime.strptime("09:30", "%H:%M").time())
            )
            if ts < actual_market_open:
                return

            for win in self._windows:
                label = win["label"]
                or_open = ET.localize(datetime.combine(today, win["_opening_start_t"]))
                or_close = or_open + timedelta(minutes=win["opening_bars"] * 5)
                if ts >= or_close and not self._opening_catchup_done[label]:
                    any_incomplete = any(
                        not self._signal_fired[label].get(t)
                        and len(self._opening_buf[label].get(t, []))
                        < win["opening_bars"]
                        for t in self._tickers
                    )
                    if any_incomplete:
                        self._opening_catchup_done[label] = True
                        logger.info(
                            "[%s] OR closed but buffers incomplete — starting historical catchup",
                            label,
                        )
                        threading.Thread(
                            target=self._catch_up_opening_bars_for_window,
                            args=(today, win),
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
            if self._bar_recorder:
                self._bar_recorder.record_1min(ticker, bar, today)

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
                    if self._bar_recorder:
                        self._bar_recorder.record_5min(ticker, five_min_bar, today)
                    self._process_five_min_bar(five_min_bar)
                mbuf["period_start"] = period_start
                mbuf["bars"] = [bar]

    def get_latest_bar(self, ticker: str) -> Optional[pd.Series]:
        df = self._history.get(ticker)
        if df is None or df.empty:
            return None
        return df.iloc[-1]

    def _warmup_from_cache(self, replay_date):
        """Populate _history with bars up to (but not including) `replay_date`."""
        from alpha_tech_tracker.op_momentum_strategy.op_momentum_backtest import fetch_bars

        start = replay_date - timedelta(days=220)
        end = replay_date - timedelta(days=1)
        logger.info(
            "Replay warmup: loading bars %s to %s for %d tickers",
            start,
            end,
            len(self._tickers),
        )
        bars_dict = fetch_bars(self._tickers, start, end, source="alpaca")
        # _stitch_cache may return a wider file (e.g. 2020–2026) that covers the
        # requested range.  Clip to strictly before replay_date so MA calculations
        # are not influenced by future bars.
        cutoff = pd.Timestamp(replay_date, tz="America/New_York")
        empty_cols = ["Open", "High", "Low", "Close", "Volume", "MA20", "MA50", "MA200"]
        for ticker, df in bars_dict.items():
            if df.empty:
                self._history[ticker] = pd.DataFrame(columns=empty_cols)
                logger.warning("No warmup data for %s", ticker)
                continue
            df = df.copy()
            df = df[df.index < cutoff]
            if df.empty:
                self._history[ticker] = pd.DataFrame(columns=empty_cols)
                logger.warning("No warmup data for %s after date clip", ticker)
                continue
            df["MA20"] = df["Close"].rolling(20).mean()
            df["MA50"] = df["Close"].rolling(50).mean()
            df["MA200"] = df["Close"].rolling(200).mean()
            self._history[ticker] = df
            logger.info(
                "Replay warmup %-6s — %d bars, last close=%.2f",
                ticker,
                len(df),
                df["Close"].iloc[-1],
            )

    def start_replay(self, replay_date):
        """Initialise for replay mode: warmup from cache + regime filter. No WebSocket."""
        self._session_date = replay_date
        self._warmup_from_cache(replay_date)
        if self._regime_filter:
            lookback_start = replay_date - timedelta(days=self._regime_ma * 3 + 10)
            self._bearish_regime_dates = build_bearish_regime_dates(
                lookback_start, replay_date, regime_ma=self._regime_ma
            )
            logger.info(
                "Replay regime filter ON (QQQ MA%d): %d bearish dates in lookback",
                self._regime_ma,
                len(self._bearish_regime_dates),
            )

    def start(self):
        logger.info("Warming up historical bars for %s", self._tickers)
        self._warmup()
        if self._regime_filter:
            today = _now_et().date()
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
            try:
                self._stream.stop()
            except AttributeError:
                pass

import argparse
import logging
import logging.handlers
import math
import os
import signal
import statistics
import sys
import time
from datetime import date, datetime, time as _dt_time, timedelta
from typing import Optional

import pandas as pd
import pytz

from alpaca.data.enums import DataFeed
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

from .config import _notify, disable_notifications
from .op_momentum_backtest import fetch_bars, fetch_daily_bars
from .op_momentum_selector import DEFAULT_TICKERS
from .replay import _now_et

logger = logging.getLogger(__name__)
ET = pytz.timezone("America/New_York")

_DEFAULT_OR_START = "09:30"
_DEFAULT_OR_BARS = 3
_EOD_TIME = "15:55"
_5MIN_WARMUP_DAYS = 30    # 30 calendar days guarantees 20 trading days for vol_20day_avg lookback
_DAILY_LOOKBACK_DAYS = 365  # ~260 trading days for daily MA200


# ─── MA helpers ───────────────────────────────────────────────────────────────


def _add_ma_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Add price rolling MA columns to a 5-min bar DataFrame."""
    df = df.copy()
    df["MA20"] = df["Close"].rolling(20, min_periods=1).mean()
    df["MA50"] = df["Close"].rolling(50, min_periods=1).mean()
    df["MA200"] = df["Close"].rolling(200, min_periods=1).mean()
    return df


def _add_daily_ma_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Add rolling MA columns to a daily bar DataFrame."""
    df = df.copy()
    df["DailyMA20"] = df["Close"].rolling(20, min_periods=1).mean()
    df["DailyMA50"] = df["Close"].rolling(50, min_periods=1).mean()
    df["DailyMA200"] = df["Close"].rolling(200, min_periods=1).mean()
    return df


def _get_prior_day_mas(daily_df: pd.DataFrame, target_date: date) -> dict:
    """Return daily MA values and prev_close from the last trading day before target_date."""
    empty = {"daily_ma20": None, "daily_ma50": None, "daily_ma200": None, "prev_close": None}
    if daily_df is None or daily_df.empty:
        return empty
    past = daily_df[daily_df.index < target_date]
    if past.empty:
        return empty
    row = past.iloc[-1]
    return {
        "daily_ma20": _nanfloat(row.get("DailyMA20")),
        "daily_ma50": _nanfloat(row.get("DailyMA50")),
        "daily_ma200": _nanfloat(row.get("DailyMA200")),
        "prev_close": _nanfloat(row.get("Close")),
    }


def _nanfloat(val) -> Optional[float]:
    if val is None:
        return None
    try:
        f = float(val)
        return None if pd.isna(f) else f
    except (TypeError, ValueError):
        return None


# ─── 1-min bar fetch (Alpaca, no cache, target date only) ─────────────────────


def _fetch_alpaca_1min_bars(tickers: list, target_date: date, feed: DataFeed = None) -> dict:
    """Fetch 1-min bars from Alpaca SIP for a single date. Not used in signals."""
    key_id = os.environ.get("ALPACA_API_KEY")
    secret_key = os.environ.get("ALPACA_SECRET_KEY")
    client = StockHistoricalDataClient(key_id, secret_key)
    effective_feed = feed if feed is not None else DataFeed.SIP
    start_dt = datetime.combine(target_date, datetime.min.time())
    end_dt = datetime.combine(target_date + timedelta(days=1), datetime.min.time())
    request = StockBarsRequest(
        symbol_or_symbols=tickers,
        timeframe=TimeFrame(amount=1, unit=TimeFrameUnit.Minute),
        start=start_dt,
        end=end_dt,
        feed=effective_feed,
    )
    bars = client.get_stock_bars(request)
    result = {}
    for ticker in tickers:
        if ticker in bars.df.index.get_level_values(0):
            df = bars.df.xs(ticker, level=0).copy()
            df.index = df.index.tz_convert("America/New_York")
            df.columns = [c.capitalize() for c in df.columns]
            df = df.between_time("09:30", "15:55")
            result[ticker] = df
        else:
            result[ticker] = pd.DataFrame()
    return result


# ─── Signal computation ────────────────────────────────────────────────────────


def compute_or_ma_signals(
    bars_5m,
    qqq_bars_5m,
    or_start,
    or_bars,
    target_date,
    daily_bars=None,
    collection_bars=3,
):
    """
    Scan 5-min bars for each ticker and return a list of signal dicts.

    The opening range (OR) is fixed at the close of the N-th bar. Signals are
    then evaluated per-bar for `collection_bars` bars starting from the OR close
    bar — the first bar on which all conditions are met fires the signal.

    Bull signal: close > OR_mid, any 5-min MA inside OR range, or_vol > vol_ma200.
    Bear signal: close < OR_mid, any 5-min MA inside OR range,
                 or_vol < vol_ma200 AND or_vol < vol_ma20.

    Args:
        bars_5m: {ticker: DataFrame} with MA20/MA50/MA200/VolMA20/VolMA200 columns
        qqq_bars_5m: QQQ 5-min DataFrame with VolMA200 column
        or_start: opening range start time string, e.g. "09:30"
        or_bars: number of 5-min bars that define the OR window
        target_date: date to evaluate
        daily_bars: optional {ticker: DataFrame} with DailyMA20/50/200 columns
        collection_bars: bars to scan for signals starting at OR close (default 3 = 15 min)

    Returns:
        list of signal dicts, one per ticker that fired
    """
    or_start_time = datetime.strptime(or_start, "%H:%M").time()
    qqq_context = _compute_qqq_context(
        qqq_bars_5m, target_date, or_start_time, or_bars, collection_bars
    )
    daily_bars = daily_bars or {}

    signals = []
    for ticker, df in bars_5m.items():
        sig = _scan_ticker(
            ticker, df, or_start_time, or_bars, target_date,
            qqq_context,
            daily_bars.get(ticker),
            collection_bars=collection_bars,
        )
        if sig is not None:
            signals.append(sig)
    return signals


def _compute_qqq_regime(qqq_df: pd.DataFrame, target_date: date, or_start_time, or_bars: int):
    """
    Classify QQQ's trend regime at the OR close bar using 5-min MA20/50/200.

    Returns one of: "Very Bullish", "Bullish", "Bearish", "Very Bearish", or None.

    Regime rules (evaluated at the last OR bar):
      Very Bullish  — close above MA20, MA50, and MA200
      Bullish       — close above MA200 but below MA20 and MA50
      Bearish       — close below all three MAs
      Very Bearish  — close below all three MAs AND MA20 and MA50 both sloping down
    """
    if qqq_df is None or qqq_df.empty:
        return None
    day = qqq_df[qqq_df.index.date == target_date]
    from_or = day[day.index.time >= or_start_time]
    if len(from_or) < or_bars:
        return None

    bar = from_or.iloc[or_bars - 1]
    close = _nanfloat(bar.get("Close"))
    ma20 = _nanfloat(bar.get("MA20"))
    ma50 = _nanfloat(bar.get("MA50"))
    ma200 = _nanfloat(bar.get("MA200"))
    if any(v is None for v in (close, ma20, ma50, ma200)):
        return None

    above_ma20 = close > ma20
    above_ma50 = close > ma50
    above_ma200 = close > ma200

    if above_ma20 and above_ma50 and above_ma200:
        return "Very Bullish"

    if above_ma200 and not above_ma20 and not above_ma50:
        return "Bullish"

    if not above_ma20 and not above_ma50 and not above_ma200:
        if or_bars >= 2:
            prev_bar = from_or.iloc[or_bars - 2]
            prev_ma20 = _nanfloat(prev_bar.get("MA20"))
            prev_ma50 = _nanfloat(prev_bar.get("MA50"))
            if (prev_ma20 is not None and ma20 < prev_ma20
                    and prev_ma50 is not None and ma50 < prev_ma50):
                return "Very Bearish"
        return "Bearish"

    return None


def _compute_qqq_context(qqq_df: pd.DataFrame, target_date: date,
                         or_start_time=None, or_bars: int = 3,
                         collection_bars: int = 3) -> dict:
    """Return QQQ volume ratio vs 20-day collection-window average, and trend regime."""
    empty = {"qqq_vol_ratio": None, "qqq_regime": None}
    if qqq_df is None or qqq_df.empty:
        return empty

    vol_ratio = None
    if or_start_time is not None:
        vol_20day_avg = _compute_collection_vol_20day_avg(
            qqq_df, or_start_time, or_bars, collection_bars, target_date
        )
        if vol_20day_avg is not None:
            day = qqq_df[qqq_df.index.date == target_date]
            from_or = day[day.index.time >= or_start_time] if not day.empty else day
            scan = from_or.iloc[or_bars - 1: or_bars - 1 + collection_bars]
            if not scan.empty:
                today_vol = float(scan["Volume"].mean())
                vol_ratio = today_vol / vol_20day_avg

    regime = None
    if or_start_time is not None:
        regime = _compute_qqq_regime(qqq_df, target_date, or_start_time, or_bars)

    return {"qqq_vol_ratio": vol_ratio, "qqq_regime": regime}


def _compute_collection_vol_20day_avg(
    df: pd.DataFrame,
    or_start_time,
    or_bars: int,
    collection_bars: int,
    target_date: date,
    lookback_days: int = 20,
    day_groups: dict = None,
) -> Optional[float]:
    """
    Compute the average volume across the collection window time slots over the
    past `lookback_days` trading days.

    The collection window starts at the OR close bar open time
    (or_start + (or_bars-1)*5 min) and covers `collection_bars` bars.
    Each prior trading day contributes the mean volume of bars in those same
    time slots, then the overall mean is returned.

    day_groups: optional pre-grouped {date: df_slice} dict. When provided,
    avoids the expensive df.index.date scan on every call (backtest fast path).
    """
    or_start_dt = datetime.combine(date.today(), or_start_time)
    collection_start = (or_start_dt + timedelta(minutes=(or_bars - 1) * 5)).time()
    collection_end = (
        or_start_dt + timedelta(minutes=(or_bars - 1 + collection_bars - 1) * 5)
    ).time()

    if day_groups is not None:
        prior_dates = sorted([d for d in day_groups if d < target_date], reverse=True)[:lookback_days]
    else:
        prior_dates = sorted(
            {d for d in df.index.date if d < target_date}, reverse=True
        )[:lookback_days]

    if not prior_dates:
        return None

    daily_avgs = []
    for d in prior_dates:
        day = day_groups[d] if day_groups is not None else df[df.index.date == d]
        if day is None or day.empty:
            continue
        window = day[
            (day.index.time >= collection_start) & (day.index.time <= collection_end)
        ]
        if not window.empty:
            daily_avgs.append(float(window["Volume"].mean()))

    return sum(daily_avgs) / len(daily_avgs) if daily_avgs else None


def _scan_ticker(
    ticker, df, or_start_time, or_bars, target_date, qqq_context, daily_df,
    collection_bars=3,
):
    """Return the first signal dict for ticker on target_date, or None.

    Signals are evaluated on `collection_bars` bars starting from the OR close bar
    (i.e. bars at indices or_bars-1 through or_bars-1+collection_bars-1).
    """
    if df is None or df.empty:
        return None

    day = df[df.index.date == target_date]
    if day.empty:
        return None

    from_or = day[day.index.time >= or_start_time]
    if len(from_or) < or_bars:
        logger.debug("%s %s: only %d OR bars (need %d)", ticker, target_date, len(from_or), or_bars)
        return None

    or_window = from_or.iloc[:or_bars]
    or_high = float(or_window["High"].max())
    or_low = float(or_window["Low"].min())
    or_mid = (or_high + or_low) / 2.0
    or_range = or_high - or_low
    or_vol = float(or_window["Volume"].mean())

    if or_range == 0:
        logger.warning("%s %s: OR range is 0, skipping", ticker, target_date)
        return None

    daily_mas = _get_prior_day_mas(daily_df, target_date)

    # Volume benchmark: mean of the collection window over the past 20 trading days
    vol_20day_avg = _compute_collection_vol_20day_avg(
        df, or_start_time, or_bars, collection_bars, target_date
    )
    if vol_20day_avg is None:
        logger.warning("%s %s: insufficient history for vol_20day_avg, skipping", ticker, target_date)
        return None

    scan_start = or_bars - 1
    scan_end = scan_start + collection_bars
    scan_bars = from_or.iloc[scan_start:scan_end]
    if scan_bars.empty:
        return None

    # collection_vol is computed incrementally per bar to avoid lookahead: on bar i we
    # only use volumes from bars 0..i of the collection window, matching live behaviour.
    for i, (idx, bar) in enumerate(scan_bars.iterrows()):
        collection_vol = float(scan_bars.iloc[: i + 1]["Volume"].mean())

        close = _nanfloat(bar.get("Close"))
        ma20 = _nanfloat(bar.get("MA20"))
        ma50 = _nanfloat(bar.get("MA50"))
        ma200 = _nanfloat(bar.get("MA200"))

        if close is None:
            continue

        overlapping_mas = [
            name for name, val in [("MA20", ma20), ("MA50", ma50), ("MA200", ma200)]
            if val is not None and or_low <= val <= or_high
        ]
        if not overlapping_mas:
            continue

        bull = close > or_mid and collection_vol > vol_20day_avg
        bear = (
            close < or_mid
            and collection_vol < vol_20day_avg
            and ma20 is not None and close < ma20
            and ma200 is not None and close < ma200
        )

        if not bull and not bear:
            continue

        return {
            "ticker": ticker,
            "direction": "BULL" if bull else "BEAR",
            "signal_bar_time": idx.strftime("%H:%M"),
            "or_high": round(or_high, 2),
            "or_low": round(or_low, 2),
            "or_mid": round(or_mid, 2),
            "or_range": round(or_range, 2),
            "close": round(close, 2),
            "overlapping_mas": overlapping_mas,
            "ma20_5m": round(ma20, 2) if ma20 is not None else None,
            "ma50_5m": round(ma50, 2) if ma50 is not None else None,
            "ma200_5m": round(ma200, 2) if ma200 is not None else None,
            "collection_vol": int(collection_vol),
            "vol_20day_avg": int(vol_20day_avg),
            "daily_ma20": daily_mas["daily_ma20"],
            "daily_ma50": daily_mas["daily_ma50"],
            "daily_ma200": daily_mas["daily_ma200"],
            "prev_close": daily_mas["prev_close"],
            "qqq_vol_ratio": qqq_context.get("qqq_vol_ratio"),
            "qqq_regime": qqq_context.get("qqq_regime"),
            "date": str(target_date),
        }
    return None


# ─── SMS formatting ────────────────────────────────────────────────────────────


def format_sms(sig: dict) -> str:
    direction = sig["direction"]
    ticker = sig["ticker"]
    or_low = sig["or_low"]
    or_high = sig["or_high"]
    or_mid = sig["or_mid"]
    close = sig["close"]
    bar_time = sig["signal_bar_time"]
    overlapping_mas = sig["overlapping_mas"]
    collection_vol = sig["collection_vol"]
    vol_20day_avg = sig["vol_20day_avg"]

    ma_str = "/".join(overlapping_mas)
    vol_ratio = f"{collection_vol / vol_20day_avg:.2f}x" if vol_20day_avg else "?"

    return (
        f"{direction} SIGNAL: {ticker} | "
        f"OR {or_low:.2f}-{or_high:.2f} (mid {or_mid:.2f}) | "
        f"{bar_time} close {close:.2f} | "
        f"{ma_str} in OR | vol {vol_ratio} 20dAvg"
    )


# ─── Backtest output ───────────────────────────────────────────────────────────


def _no_signal_reason(
    df: pd.DataFrame, or_start_time, or_bars: int, target_date: date, collection_bars: int = 3
) -> str:
    """Return a brief string explaining why no signal fired within the collection window."""
    if df is None or df.empty:
        return "no data"
    day = df[df.index.date == target_date]
    if day.empty:
        return "no data for date"
    from_or = day[day.index.time >= or_start_time]
    if len(from_or) < or_bars:
        return f"only {len(from_or)} OR bars"
    or_window = from_or.iloc[:or_bars]
    or_high = float(or_window["High"].max())
    or_low = float(or_window["Low"].min())
    if or_high == or_low:
        return "OR range = 0"
    or_mid = (or_high + or_low) / 2.0
    scan = from_or.iloc[or_bars - 1 : or_bars - 1 + collection_bars]
    if scan.empty:
        return "no scan bars"
    last_bar = scan.iloc[-1]
    close = _nanfloat(last_bar.get("Close"))
    if close is None:
        return "no close price"
    ma20 = _nanfloat(last_bar.get("MA20"))
    ma50 = _nanfloat(last_bar.get("MA50"))
    ma200 = _nanfloat(last_bar.get("MA200"))
    overlapping = [
        n for n, v in [("MA20", ma20), ("MA50", ma50), ("MA200", ma200)]
        if v is not None and or_low <= v <= or_high
    ]
    if not overlapping:
        return "no MA in OR range"
    vol_20day_avg = _compute_collection_vol_20day_avg(
        df, or_start_time, or_bars, collection_bars, target_date
    )
    if vol_20day_avg is None:
        return "no vol history"
    scan = from_or.iloc[or_bars - 1 : or_bars - 1 + collection_bars]
    collection_vol = float(scan["Volume"].mean()) if not scan.empty else None
    if collection_vol is None:
        return "no collection vol"
    ratio = collection_vol / vol_20day_avg
    if close > or_mid:
        return f"bull vol fail: {ratio:.2f}x 20dAvg (need >1.0x)"
    if ratio >= 1.0:
        return f"bear vol fail: {ratio:.2f}x 20dAvg (need <1.0x)"
    ma20 = _nanfloat(last_bar.get("MA20"))
    ma200 = _nanfloat(last_bar.get("MA200"))
    if ma20 is not None and close >= ma20:
        return f"bear MA fail: close {close:.2f} >= MA20 {ma20:.2f}"
    if ma200 is not None and close >= ma200:
        return f"bear MA fail: close {close:.2f} >= MA200 {ma200:.2f}"
    return "bear: no MA in OR range"


def _print_backtest_table(
    signals, all_tickers, bars_5m, or_start, or_bars, target_date, print_all,
    collection_bars=3,
):
    or_start_time = datetime.strptime(or_start, "%H:%M").time()
    def _signal_sort_key(s):
        prev = s.get("prev_close")
        up_pct = (s["close"] - prev) / prev * 100 if prev else 0.0
        ma_count = len(s.get("overlapping_mas") or [])
        vol_ratio = (
            s["collection_vol"] / s["vol_20day_avg"]
            if s.get("vol_20day_avg") else 0.0
        )
        return (-up_pct, -ma_count, -vol_ratio)

    sorted_signals = sorted(signals, key=_signal_sort_key)
    signal_map = {s["ticker"]: s for s in sorted_signals}

    print(f"\n{'='*88}")
    print(
        f"MA Open Range Momentum Screener — {target_date}  "
        f"OR: {or_start} / {or_bars} bars  Collection: {collection_bars} bars"
    )
    print(f"{'='*88}")
    print(
        f"{'Ticker':<8} {'Dir':<6} {'Signal at':<10} {'OR Low-High':<18} "
        f"{'Close':<8} {'Up%':<7} {'MAs in OR':<18} {'Vol/20dAvg':<10}"
    )
    print("-" * 88)

    tickers_to_show = list(signal_map.keys())
    if print_all:
        tickers_to_show += [t for t in all_tickers if t not in signal_map]

    for ticker in tickers_to_show:
        if ticker in signal_map:
            s = signal_map[ticker]
            or_str = f"{s['or_low']:.2f}-{s['or_high']:.2f}"
            ma_str = "/".join(s["overlapping_mas"])
            vol_ratio = (
                f"{s['collection_vol'] / s['vol_20day_avg']:.2f}x"
                if s.get("vol_20day_avg")
                else "?"
            )
            prev = s.get("prev_close")
            up_pct_str = (
                f"{(s['close'] - prev) / prev * 100:+.2f}%"
                if prev else "?"
            )
            print(
                f"{ticker:<8} {s['direction']:<6} {s['signal_bar_time']:<10} "
                f"{or_str:<18} {s['close']:<8.2f} {up_pct_str:<7} {ma_str:<18} {vol_ratio:<10}"
            )
        else:
            reason = _no_signal_reason(
                bars_5m.get(ticker), or_start_time, or_bars, target_date, collection_bars
            )
            print(f"{ticker:<8} {'--':<6} {'--':<10} {'--':<18} {'--':<8} {'--':<7} {reason}")

    bull_n = sum(1 for s in signals if s["direction"] == "BULL")
    bear_n = sum(1 for s in signals if s["direction"] == "BEAR")
    print(f"\nSignals: {len(signals)} total ({bull_n} BULL, {bear_n} BEAR)")

    if signals:
        regime = signals[0].get("qqq_regime")
        regime_str = regime if regime else "regime N/A"
        qqq_vol_ratio = signals[0].get("qqq_vol_ratio")
        vol_str = f"vol {qqq_vol_ratio:.2f}x 20dAvg" if qqq_vol_ratio is not None else "vol N/A"
        print(f"QQQ: {regime_str} | {vol_str}")


# ─── Backtest entry point ──────────────────────────────────────────────────────


def run_backtest(
    target_date,
    tickers,
    or_bars=_DEFAULT_OR_BARS,
    or_start=_DEFAULT_OR_START,
    collection_bars=3,
    source="alpaca",
    feed=None,
    print_all=False,
    enable_regime_engine=False,
    regime_data_dir="market_data/regime_state",
):
    """
    Fetch historical data for target_date and run the OR/MA signal scan.

    Returns a dict with keys: signals, bars_5m, bars_1m, daily_bars.
    SMS notifications are disabled in backtest mode.
    """
    disable_notifications()
    effective_feed = feed if feed is not None else DataFeed.SIP
    all_tickers = list(tickers) + (["QQQ"] if "QQQ" not in tickers else [])

    fetch_start_5m = target_date - timedelta(days=_5MIN_WARMUP_DAYS)
    print(f"Fetching 5-min bars ({fetch_start_5m} -> {target_date}) [{source}]...")
    bars_5m_raw = fetch_bars(
        all_tickers, fetch_start_5m, target_date, source, feed=effective_feed
    )
    bars_5m = {t: _add_ma_columns(df) for t, df in bars_5m_raw.items() if not df.empty}

    qqq_bars_5m = bars_5m.get("QQQ", pd.DataFrame())
    ticker_bars_5m = {t: df for t, df in bars_5m.items() if t != "QQQ"}

    daily_start = target_date - timedelta(days=_DAILY_LOOKBACK_DAYS)
    print(f"Fetching daily bars ({daily_start} -> {target_date})...")
    daily_bars_raw = fetch_daily_bars(
        all_tickers, daily_start, target_date, source=source, feed=effective_feed
    )
    daily_bars = {
        t: _add_daily_ma_columns(df)
        for t, df in daily_bars_raw.items()
        if not df.empty
    }

    print(f"Fetching 1-min bars for {target_date} (for future use)...")
    try:
        bars_1m = _fetch_alpaca_1min_bars(
            [t for t in tickers if t != "QQQ"], target_date, feed=effective_feed
        )
    except Exception as exc:
        logger.warning("1-min bar fetch failed: %s", exc)
        bars_1m = {}

    signals = compute_or_ma_signals(
        ticker_bars_5m,
        qqq_bars_5m,
        or_start,
        or_bars,
        target_date,
        daily_bars={t: daily_bars[t] for t in tickers if t in daily_bars},
        collection_bars=collection_bars,
    )

    ranked = _rank_tickers_by_eod_win_rate(ticker_bars_5m, target_date, or_start, or_bars)
    ranking_block = _format_top2_ranking(ranked, target_date, or_start, or_bars)
    wr_table = _format_ticker_win_rate_table(ranked)
    if ranking_block:
        print(ranking_block)
    if wr_table:
        print(wr_table)
    if ranking_block or wr_table:
        print()

    regime = None
    if enable_regime_engine:
        from .regime_engine import RegimeEngine  # noqa: PLC0415
        regime_engine = RegimeEngine(data_dir=regime_data_dir)
        yesterday = target_date - timedelta(days=1)
        regime_engine.compute_and_add_metrics(
            bars_5m, yesterday, or_start, or_bars, collection_bars
        )
        presession_top2_wr = (
            ranked[0][1]["win_rates"][None] / 100 if ranked else None
        )
        regime = regime_engine.get_current_regime(presession_top2_wr=presession_top2_wr)
        print(f"\n{'─'*60}")
        print(f"REGIME ENGINE  {target_date}")
        print(f"  Direction : {regime.direction}")
        print(f"  Hold      : {regime.hold_window or '—'}")
        print(f"  Type      : {regime.regime_type}")
        print(f"  Source    : {regime.source}")
        print(f"  Notes     : {regime.notes}")
        filtered = [s for s in signals if not _passes_regime_filter(s, regime)]
        passed   = [s for s in signals if _passes_regime_filter(s, regime)]
        if filtered:
            print(f"  Filtered  : {[s['ticker']+'/'+s['direction'] for s in filtered]}")
        print(f"  Passed    : {[s['ticker']+'/'+s['direction'] for s in passed] or '—'}")
        print(f"{'─'*60}\n")

    _print_backtest_table(
        signals, list(tickers), ticker_bars_5m, or_start, or_bars, target_date, print_all,
        collection_bars=collection_bars,
    )

    return {
        "signals": signals,
        "bars_5m": ticker_bars_5m,
        "bars_1m": bars_1m,
        "daily_bars": daily_bars,
        "regime": regime,
    }


def _count_collection_bars(df, or_start_time, or_bars, collection_bars, target_date):
    """Return how many collection bars have arrived so far for target_date."""
    if df is None or df.empty:
        return 0
    day = df[df.index.date == target_date]
    if day.empty:
        return 0
    from_or = day[day.index.time >= or_start_time]
    if len(from_or) < or_bars:
        return 0
    return min(len(from_or) - or_bars + 1, collection_bars)


# ─── Live polling entry point ──────────────────────────────────────────────────


def run_live(
    tickers,
    or_bars=_DEFAULT_OR_BARS,
    or_start=_DEFAULT_OR_START,
    collection_bars=3,
    market_data_client=None,
    poll_interval_sec=30,
    dry_run=False,
    enable_regime_engine=False,
    regime_data_dir="market_data/regime_state",
    _stop_after_iterations=None,
):
    """
    Poll live 5-min bars from TradeStation and fire SMS on OR/MA overlap signals.

    Signals are re-evaluated after each new bar (per-bar, not just at OR close).
    Each ticker fires at most once per session. A summary SMS is sent at EOD.
    """
    if dry_run:
        disable_notifications()

    or_start_time = datetime.strptime(or_start, "%H:%M").time()
    or_close_minutes = or_bars * 5
    eod_time = datetime.strptime(_EOD_TIME, "%H:%M").time()

    all_tickers = list(tickers) + (["QQQ"] if "QQQ" not in tickers else [])

    # Pre-warm from Alpaca historical data (prior days only — safe to cache)
    now_init = _now_et()
    print(f"Current ET time: {now_init.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    yesterday = (now_init - timedelta(days=1)).date()
    warmup_start = yesterday - timedelta(days=_5MIN_WARMUP_DAYS)
    daily_start = yesterday - timedelta(days=_DAILY_LOOKBACK_DAYS)

    print(f"Pre-fetching 5-min warmup bars ({warmup_start} -> {yesterday})...")
    warmup_raw = fetch_bars(all_tickers, warmup_start, yesterday, "alpaca", feed=DataFeed.SIP)
    warmup_bars = {t: df for t, df in warmup_raw.items() if not df.empty}

    print(f"Pre-fetching daily bars ({daily_start} -> {yesterday})...")
    daily_raw = fetch_daily_bars(
        all_tickers, daily_start, yesterday, source="alpaca", feed=DataFeed.SIP
    )
    daily_bars = {
        t: _add_daily_ma_columns(df)
        for t, df in daily_raw.items()
        if not df.empty
    }

    # Regime engine — lazy import to avoid circular dependency with regime_engine.py
    regime_engine = None
    regime = None
    if enable_regime_engine:
        from .regime_engine import RegimeEngine  # noqa: PLC0415
        regime_engine = RegimeEngine(data_dir=regime_data_dir)
        regime_engine.compute_and_add_metrics(
            warmup_bars, yesterday, or_start, or_bars, collection_bars
        )

    already_notified = set()
    tracking_alerted = {}   # ticker -> direction when 60% SMS was sent
    summary_sent = False
    session_signals = []
    current_day = None
    _iteration_count = 0

    or_close_str = (
        datetime.combine(now_init.date(), or_start_time) + timedelta(minutes=or_close_minutes)
    ).strftime("%H:%M")
    print(
        f"Live polling started. OR: {or_start}/{or_bars} bars "
        f"(closes {or_close_str} ET). "
        f"Poll: {poll_interval_sec}s. Dry-run: {dry_run}."
    )

    while True:
        now_et = _now_et()
        today = now_et.date()
        # Compute OR close time in ET for today
        or_close_dt = ET.localize(
            datetime.combine(today, or_start_time) + timedelta(minutes=or_close_minutes)
        )

        if current_day != today:
            current_day = today
            already_notified = set()
            tracking_alerted = {}
            summary_sent = False
            ranking_sent = False
            session_signals = []
            print(f"\n--- {today} (ET) ---")

        # 9:35 ranking: always fires once per day using warmup bars (prior days only)
        ranking_time = ET.localize(
            datetime.combine(today, datetime.strptime("09:25", "%H:%M").time())
        )
        if not ranking_sent and now_et >= ranking_time:
            warmup_ticker_bars = {t: df for t, df in warmup_bars.items() if t != "QQQ"}
            ranked = _rank_tickers_by_eod_win_rate(
                warmup_ticker_bars, today, or_start, or_bars
            )
            ranking_block = _format_top2_ranking(ranked, today, or_start, or_bars)
            wr_table = _format_ticker_win_rate_table(ranked)
            if ranking_block:
                print(ranking_block)
            if wr_table:
                print(wr_table)
            sms_parts = [p for p in [ranking_block, wr_table] if p]
            if regime_engine is not None:
                presession_top2_wr = (
                    ranked[0][1]["win_rates"][None] / 100 if ranked else None
                )
                regime = regime_engine.get_current_regime(presession_top2_wr=presession_top2_wr)
                regime_sms = f"Regime: {regime.direction} | Hold: {regime.hold_window} | {regime.notes}"
                logger.info("%s", regime_engine.summary_str())
                sms_parts.append(regime_sms)
            if sms_parts:
                _notify("\n".join(sms_parts))
            ranking_sent = True

        if now_et < or_close_dt:
            print(f"[{now_et.strftime('%H:%M:%S %Z')}] Waiting for OR to close at {or_close_dt.strftime('%H:%M')} ET...")
            _iteration_count += 1
            if _stop_after_iterations is not None and _iteration_count >= _stop_after_iterations:
                raise StopIteration
            time.sleep(poll_interval_sec)
            continue

        if now_et.time() >= eod_time:
            if not summary_sent:
                _send_session_summary(session_signals, today)
                summary_sent = True
            print(f"[{now_et.strftime('%H:%M:%S %Z')}] EOD — next poll in 60s")
            _iteration_count += 1
            if _stop_after_iterations is not None and _iteration_count >= _stop_after_iterations:
                raise StopIteration
            time.sleep(60)
            continue

        # Fetch today's live bars from TradeStation
        print(f"[{now_et.strftime('%H:%M:%S %Z')}] Fetching 5-min bars for {len(all_tickers)} tickers...")
        try:
            today_start = datetime.combine(today, datetime.min.time())
            today_end = datetime.combine(today + timedelta(days=1), datetime.min.time())
            today_raw = market_data_client.fetch_bars(all_tickers, today_start, today_end)
        except Exception as exc:
            logger.error("TradeStation bar fetch failed: %s", exc)
            time.sleep(poll_interval_sec)
            continue

        # Merge warmup + today, recompute rolling MAs
        merged_bars = {}
        for ticker in all_tickers:
            prior = warmup_bars.get(ticker, pd.DataFrame())
            today_df = today_raw.get(ticker, pd.DataFrame())
            if today_df.empty:
                merged = prior
            elif prior.empty:
                merged = today_df
            else:
                merged = pd.concat([prior, today_df])
                merged = merged[~merged.index.duplicated(keep="last")]
            if not merged.empty:
                merged_bars[ticker] = _add_ma_columns(merged)
                today_bar_count = len(today_raw.get(ticker, pd.DataFrame()))
                last_bar_time = merged_bars[ticker].index[-1].strftime("%H:%M") if not merged_bars[ticker].empty else "n/a"
                print(f"  {ticker}: {today_bar_count} today bars, last={last_bar_time}, total={len(merged_bars[ticker])}")

        qqq_bars_5m = merged_bars.get("QQQ", pd.DataFrame())
        ticker_bars_5m = {t: df for t, df in merged_bars.items() if t != "QQQ"}

        # Early notification: fire after 60% of collection bars arrive, then update every bar
        or_start_time_obj = datetime.strptime(or_start, "%H:%M").time()
        min_bars_to_notify = math.ceil(0.6 * collection_bars)
        for ticker in tickers:
            if ticker in already_notified:
                continue
            df = merged_bars.get(ticker)
            if df is None:
                continue
            n_bars = _count_collection_bars(df, or_start_time_obj, or_bars, collection_bars, today)
            if n_bars < min_bars_to_notify:
                print(f"  {ticker}: {n_bars}/{collection_bars} collection bars — waiting for {min_bars_to_notify}")
                continue
            # Evaluate signal on available bars (partial is fine)
            partial_signals = compute_or_ma_signals(
                {ticker: df},
                qqq_bars_5m,
                or_start,
                or_bars,
                today,
                daily_bars={ticker: daily_bars[ticker]} if ticker in daily_bars else {},
                collection_bars=n_bars,
            )
            if partial_signals:
                sig = partial_signals[0]
                direction = sig["direction"]
                bar_label = f"{n_bars}/{collection_bars} bars"
                if ticker not in tracking_alerted:
                    tracking_alerted[ticker] = direction
                    sms = (
                        f"EARLY {direction}: {ticker} at {sig['signal_bar_time']} "
                        f"({bar_label}) | close={sig['close']} OR_mid={sig['or_mid']} "
                        f"| {','.join(sig['overlapping_mas'])} in OR"
                    )
                    hist = _compute_hold_history(
                        merged_bars.get(ticker), today, or_start, or_bars
                    )
                    hist_line = _format_hold_history(hist)
                    if hist_line:
                        sms += f"\n{hist_line.strip()}"
                    print(f"[{now_et.strftime('%H:%M:%S %Z')}] {sms}")
                    _notify(sms)
                else:
                    print(
                        f"  [{now_et.strftime('%H:%M:%S %Z')}] UPDATE {direction} {ticker} "
                        f"{sig['signal_bar_time']} ({bar_label}): close={sig['close']}"
                    )
            else:
                print(
                    f"  [{now_et.strftime('%H:%M:%S %Z')}] WATCH {ticker} "
                    f"{n_bars}/{collection_bars} bars — no signal yet"
                )

        new_signals = compute_or_ma_signals(
            ticker_bars_5m,
            qqq_bars_5m,
            or_start,
            or_bars,
            today,
            daily_bars={t: daily_bars[t] for t in tickers if t in daily_bars},
            collection_bars=collection_bars,
        )

        for sig in new_signals:
            if sig["ticker"] not in already_notified:
                if regime is not None and not _passes_regime_filter(sig, regime):
                    logger.info(
                        "Regime filter: skipping %s %s signal (%s regime)",
                        sig["direction"], sig["ticker"], regime.direction,
                    )
                    continue
                already_notified.add(sig["ticker"])
                session_signals.append(sig)
                sms = format_sms(sig)
                hist = _compute_hold_history(
                    ticker_bars_5m.get(sig["ticker"]), today, or_start, or_bars
                )
                hist_line = _format_hold_history(hist)
                if hist_line:
                    sms += f"\n{hist_line.strip()}"
                if regime is not None:
                    hold_line = _regime_hold_line(regime)
                    if hold_line:
                        sms += f"\n{hold_line}"
                print(f"SIGNAL: {sms}")
                _notify(sms)

        _iteration_count += 1
        if _stop_after_iterations is not None and _iteration_count >= _stop_after_iterations:
            raise StopIteration

        time.sleep(poll_interval_sec)


def _passes_regime_filter(sig: dict, regime) -> bool:
    """Return False if the signal direction conflicts with the current regime."""
    direction = regime.direction
    if direction == "NO_POSITION":
        return False
    if direction == "SHORT" and sig["direction"] == "BULL":
        return False
    if direction == "LONG" and sig["direction"] == "BEAR":
        return False
    return True


def _regime_hold_line(regime) -> str:
    """Return a one-line hold annotation for the signal SMS, or empty string."""
    if not regime.hold_window:
        return ""
    return f"Hold: {regime.hold_window} [{regime.regime_type}]"


def _send_session_summary(signals: list, target_date: date):
    bull_n = sum(1 for s in signals if s["direction"] == "BULL")
    bear_n = sum(1 for s in signals if s["direction"] == "BEAR")
    regime = signals[0].get("qqq_regime") if signals else None
    qqq_str = f" | QQQ {regime}" if regime else ""
    msg = (
        f"OR Screener {target_date} | "
        f"{len(signals)} signals ({bull_n} BULL, {bear_n} BEAR)"
        f"{qqq_str}"
    )
    print(f"Summary: {msg}")
    _notify(msg)


# ─── Range analysis ───────────────────────────────────────────────────────────


# None = EOD sentinel
_HOLD_WINDOWS_MIN = [15, 30, 45, 60, 90, 120, 180, 240, 300, 360, 420, None]


def _hold_label(mins):
    """Return a short display label for a holding period."""
    if mins is None:
        return "EOD"
    if mins >= 60 and mins % 60 == 0:
        return f"+{mins // 60}h"
    if mins >= 60:
        h, m = divmod(mins, 60)
        return f"+{h}h{m}m"
    return f"+{mins}m"


_HIST_HOLD_MIN = [15, 30, 60, 120, 300, None]


def _forward_pct(day_df: pd.DataFrame, signal_time, signal_date: date, hold_min):
    """
    Return % change from signal bar close to the close N minutes later.
    hold_min=None means EOD — uses the last bar of the day.
    Falls back to the last available bar when exit time is past market close.
    """
    if day_df is None or day_df.empty or not hasattr(day_df.index, "time"):
        return None
    entry_bars = day_df[day_df.index.time == signal_time]
    if entry_bars.empty:
        return None
    entry_price = float(entry_bars.iloc[0]["Close"])
    if hold_min is None:
        exit_price = float(day_df.iloc[-1]["Close"])
    else:
        exit_time = (
            datetime.combine(signal_date, signal_time) + timedelta(minutes=hold_min)
        ).time()
        exit_bars = day_df[day_df.index.time >= exit_time]
        exit_price = float(exit_bars.iloc[0]["Close"] if not exit_bars.empty
                           else day_df.iloc[-1]["Close"])
    return (exit_price - entry_price) / entry_price * 100


def _compute_hold_history(df_5m, target_date, or_start, or_bars, lookback=20, day_groups=None):
    """
    For the past `lookback` trading days before target_date, compute the average
    forward return from the OR-close bar at +15m, +30m, +1h, +2h, and the average
    absolute daily move (|last_close - first_open| / first_open).
    Returns a dict or None if insufficient data.

    day_groups: optional pre-grouped {date: df_slice} dict. When provided,
    avoids the expensive df_5m.index.date scan on every call (backtest fast path).
    """
    if day_groups is None and (df_5m is None or df_5m.empty):
        return None
    # Anchor at the last OR bar (or_bars-1 bars in), matching _scan_ticker's first
    # collection bar — not the bar after OR closes.
    or_close_time = (
        datetime.strptime(or_start, "%H:%M") + timedelta(minutes=(or_bars - 1) * 5)
    ).time()

    if day_groups is not None:
        past_days = sorted([d for d in day_groups if d < target_date], reverse=True)[:lookback]
    else:
        past_days = sorted(
            {d for d in df_5m.index.date if d < target_date}, reverse=True
        )[:lookback]
    if not past_days:
        return None

    sums = {h: [] for h in _HIST_HOLD_MIN}
    daily_moves = []

    for day in past_days:
        day_df = day_groups[day] if day_groups is not None else df_5m[df_5m.index.date == day]
        if day_df.empty:
            continue
        entry_bars = day_df[day_df.index.time == or_close_time]
        if entry_bars.empty:
            continue
        entry_price = float(entry_bars.iloc[0]["Close"])
        for h in _HIST_HOLD_MIN:
            if h is None:
                exit_price = float(day_df.iloc[-1]["Close"])
                sums[h].append((exit_price - entry_price) / entry_price * 100)
            else:
                exit_time = (
                    datetime.combine(day, or_close_time) + timedelta(minutes=h)
                ).time()
                exit_bars = day_df[day_df.index.time >= exit_time]
                if not exit_bars.empty:
                    sums[h].append(
                        (float(exit_bars.iloc[0]["Close"]) - entry_price) / entry_price * 100
                    )
        first_open = float(day_df.iloc[0]["Open"])
        if first_open > 0:
            daily_moves.append(
                abs(float(day_df.iloc[-1]["Close"]) - first_open) / first_open * 100
            )

    holds = {h: (sum(v) / len(v)) for h, v in sums.items() if v}
    if not holds:
        return None
    win_rates = {
        h: 100 * sum(1 for x in v if x > 0) / len(v)
        for h, v in sums.items() if v
    }
    medians = {h: statistics.median(v) for h, v in sums.items() if v}
    eod_returns = sums.get(None, [])
    eod_range = (min(eod_returns), max(eod_returns)) if eod_returns else None
    return {
        "holds": holds,
        "win_rates": win_rates,
        "medians": medians,
        "eod_range": eod_range,
        "daily_move": sum(daily_moves) / len(daily_moves) if daily_moves else None,
        "n": len(past_days),
    }


def _format_hold_history(hist):
    """Format _compute_hold_history result into a compact annotation line."""
    if not hist:
        return None
    labels = {15: "+15m", 30: "+30m", 60: "+1h", 120: "+2h", 300: "+5h", None: "EOD"}
    parts = [
        f"{labels[h]} {hist['win_rates'][h]:.0f}%W {hist['holds'][h]:+.1f}%"
        for h in _HIST_HOLD_MIN
        if h in hist["holds"]
    ]
    daily = f"  |  avg daily ±{hist['daily_move']:.1f}%" if hist["daily_move"] else ""
    return f"  [{hist['n']}d hist: {('  '.join(parts))}{daily}]"



def _rank_tickers_by_eod_win_rate(ticker_bars_5m, target_date, or_start, or_bars, lookback=20,
                                   ticker_day_groups=None):
    """
    Compute hold history for every ticker and return the full list sorted by
    EOD win rate descending. Tickers with no computable history are excluded.

    ticker_day_groups: optional pre-grouped {ticker: {date: df_slice}} dict.
    When provided, passed down to _compute_hold_history to skip date scanning.
    """
    ranked = []
    for ticker, df in ticker_bars_5m.items():
        day_groups = ticker_day_groups.get(ticker) if ticker_day_groups is not None else None
        hist = _compute_hold_history(df, target_date, or_start, or_bars, lookback,
                                     day_groups=day_groups)
        if hist and None in hist["win_rates"]:
            ranked.append((ticker, hist))
    ranked.sort(key=lambda x: -x[1]["win_rates"][None])
    return ranked


def _format_top2_ranking(ranked, target_date, or_start, or_bars):
    """
    Format the top-2 tickers (by EOD win rate) into a display/SMS block.
    Shows win rate + median return at each hold window, plus EOD gain range.
    """
    labels = {15: "+15m", 30: "+30m", 60: "+1h", 120: "+2h", 300: "+5h", None: "EOD"}
    top2 = ranked[:2]
    if not top2:
        return None
    lines = [
        f"Pre-session top-2 (9:25, 20d EOD win rate) — {target_date}  "
        f"OR: {or_start}/{or_bars}b"
    ]
    for rank, (ticker, hist) in enumerate(top2, 1):
        parts = [
            f"{labels[h]} {hist['win_rates'][h]:.0f}%W {hist['medians'][h]:+.1f}%"
            for h in _HIST_HOLD_MIN
            if h in hist["medians"]
        ]
        eod_r = hist.get("eod_range")
        range_str = f"  EOD range {eod_r[0]:+.1f}% → {eod_r[1]:+.1f}%" if eod_r else ""
        lines.append(f"  #{rank} {ticker:<6} " + "  ".join(parts) + range_str)
    return "\n".join(lines)


def _format_ticker_win_rate_table(ranked):
    """
    Format all ranked tickers into a win-rate table showing win % and median
    return at each hold window, plus the EOD gain range. Sorted by EOD win rate.
    """
    if not ranked:
        return None
    labels = {15: "+15m", 30: "+30m", 60: "+1h", 120: "+2h", 300: "+5h", None: "EOD"}
    col_w = 12  # width per hold column "60%W +1.3%"
    header_cols = "  ".join(f"{labels[h]:>{col_w}}" for h in _HIST_HOLD_MIN)
    sep = "-" * (8 + 4 + len(_HIST_HOLD_MIN) * (col_w + 2) + 22)
    lines = [
        f"  {'Ticker':<6}  {'N':>2}  {header_cols}  {'EOD range':>18}",
        f"  {sep}",
    ]
    for ticker, hist in ranked:
        cols = "  ".join(
            f"{hist['win_rates'][h]:.0f}%W {hist['medians'][h]:+.1f}%".rjust(col_w)
            if h in hist["win_rates"] else f"{'—':>{col_w}}"
            for h in _HIST_HOLD_MIN
        )
        eod_r = hist.get("eod_range")
        range_str = f"{eod_r[0]:+.1f}% → {eod_r[1]:+.1f}%" if eod_r else "—"
        lines.append(f"  {ticker:<6}  {hist['n']:>2}  {cols}  {range_str:>18}")
    return "\n".join(lines)


def _build_presession_picks_rows(ticker_bars_5m, trading_days, or_start, or_bars):
    """
    For each trading day return the top-2 tickers (by 20d EOD win rate) with
    their actual forward returns from the OR-close bar — regardless of whether
    a signal fired. Used to build the pre-session performance table.
    """
    # Anchor at the last OR bar (or_bars-1 bars in), consistent with _compute_hold_history.
    or_close_time = (
        datetime.strptime(or_start, "%H:%M") + timedelta(minutes=(or_bars - 1) * 5)
    ).time()
    rows = []
    for day in trading_days:
        ranked = _rank_tickers_by_eod_win_rate(ticker_bars_5m, day, or_start, or_bars)
        for rank_idx, (ticker, _hist) in enumerate(ranked[:2], 1):
            day_df = ticker_bars_5m.get(ticker, pd.DataFrame())
            if not day_df.empty:
                day_df = day_df[day_df.index.date == day]
            entry_bars = day_df[day_df.index.time == or_close_time] if not day_df.empty else pd.DataFrame()
            if entry_bars.empty:
                continue
            entry_price = float(entry_bars.iloc[0]["Close"])
            row = {
                "date": day,
                "ticker": ticker,
                "rank": rank_idx,
                "signal_time": or_close_time.strftime("%H:%M"),
                "entry": entry_price,
            }
            for mins in _HOLD_WINDOWS_MIN:
                key = f"pct_{_hold_label(mins)}"
                row[key] = _forward_pct(day_df, or_close_time, day, mins)
            rows.append(row)
    return rows


def _window_label(or_start, or_bars):
    """Short label used in table and summary, e.g. '09:30/3b'."""
    return f"{or_start}/{or_bars}b"


def _print_summary_block(results_subset, label):
    """Print one summary block (one window or aggregate) for the given result rows."""
    n = len(results_subset)
    print(f"\n{label}  ({n} signal(s))")
    # Column widths: Hold=8, Count=6, WinRate=10(9+%), AvgGain=10(9+%), AvgWin=10(9+%),
    # AvgLoss=10(9+%), ProfitFactor=12, PosWtRet=26 — separators are 1 space each → 89 dashes
    print(f"  {'Hold':<8} {'Count':>6} {'Win Rate':>10} {'Avg Gain':>10} {'Avg Win':>10} {'Avg Loss':>10} {'ProfitFactor':>12} {'Position Weighted Return%':>26}")
    print("  " + "-" * 89)
    for mins in _HOLD_WINDOWS_MIN:
        key = f"pct_{_hold_label(mins)}"
        rows_with_pct = [r for r in results_subset if r.get(key) is not None]
        pcts = [r[key] for r in rows_with_pct]
        if not pcts:
            continue
        wins = [p for p in pcts if p > 0]
        losses = [p for p in pcts if p <= 0]
        win_rate = len(wins) / len(pcts) * 100
        avg_gain = sum(pcts) / len(pcts)
        avg_win = sum(wins) / len(wins) if wins else 0.0
        avg_loss = sum(losses) / len(losses) if losses else 0.0
        gross_loss = abs(sum(losses))
        profit_factor = sum(wins) / gross_loss if gross_loss > 0 else float("inf")
        profit_factor_str = f"{profit_factor:.2f}x" if profit_factor != float("inf") else "∞"
        # Portfolio return: equal capital per signal per day.
        # Average signals within each day first so a 6-signal day and a 1-signal day
        # contribute equally to the total, matching actual capital allocation.
        by_day = {}
        for r in rows_with_pct:
            by_day.setdefault(r["date"], []).append(r[key])
        port_ret = sum(sum(v) / len(v) for v in by_day.values())
        print(
            f"  {_hold_label(mins):<8} {len(pcts):>6} {win_rate:>9.1f}% "
            f"{avg_gain:>+9.2f}% {avg_win:>+9.2f}% {avg_loss:>+9.2f}% "
            f"{profit_factor_str:>12} {port_ret:>+25.2f}%"
        )


def run_range_analysis(
    start_date,
    end_date,
    tickers,
    windows=None,
    or_bars=_DEFAULT_OR_BARS,
    or_start=_DEFAULT_OR_START,
    collection_bars=3,
    min_vol_ratio=2.0,
    source="alpaca",
    feed=None,
):
    """
    Run OR/MA signal analysis over a date range. Filters to BULL signals with
    collection_vol >= min_vol_ratio * vol_20day_avg and reports forward P&L.

    windows: list of (or_start, or_bars) tuples. When provided, all windows
             are scanned per day and results are broken out per window in the
             summary. Falls back to [(or_start, or_bars)] if not supplied.
    """
    effective_windows = windows if windows else [(or_start, or_bars)]

    disable_notifications()
    effective_feed = feed if feed is not None else DataFeed.SIP
    all_tickers = list(tickers) + (["QQQ"] if "QQQ" not in tickers else [])

    warmup_start = start_date - timedelta(days=45)  # 45 calendar days ≥ 20 trading days even across holiday clusters
    daily_start = start_date - timedelta(days=_DAILY_LOOKBACK_DAYS)

    print(f"Fetching 5-min bars ({warmup_start} → {end_date}) [{source}]...")
    bars_5m_raw = fetch_bars(all_tickers, warmup_start, end_date, source, feed=effective_feed)
    bars_5m = {t: _add_ma_columns(df) for t, df in bars_5m_raw.items() if not df.empty}

    print(f"Fetching daily bars ({daily_start} → {end_date})...")
    daily_raw = fetch_daily_bars(all_tickers, daily_start, end_date, source=source, feed=effective_feed)
    daily_bars = {t: _add_daily_ma_columns(df) for t, df in daily_raw.items() if not df.empty}

    qqq_bars_5m = bars_5m.get("QQQ", pd.DataFrame())
    ticker_bars_5m = {t: df for t, df in bars_5m.items() if t != "QQQ"}

    trading_days = sorted({
        d for df in ticker_bars_5m.values()
        for d in df.index.date
        if start_date <= d <= end_date
    })

    col_w = 9
    # Window column width: max label length, at least 8
    win_col_w = max(len(_window_label(s, b)) for s, b in effective_windows)
    win_col_w = max(win_col_w, 8)
    table_width = 12 + 1 + 6 + 1 + win_col_w + 1 + 6 + 7 + 2 + 7 + 2 + len(_HOLD_WINDOWS_MIN) * (col_w + 2)
    header_cols = "  ".join(f"{_hold_label(m):>{col_w}}" for m in _HOLD_WINDOWS_MIN)

    # ── Pre-session rankings (separate section, outside signal table) ────────────
    win_labels_str = ", ".join(_window_label(s, b) for s, b in effective_windows)
    print(f"\n{'=' * table_width}")
    print(f"Pre-Session Rankings (9:25) — {start_date} to {end_date}  |  20d lookback")
    print(f"(Unconditional hold from OR close — no signal or vol filter)")
    print("=" * table_width)
    for day in trading_days:
        ranked = _rank_tickers_by_eod_win_rate(ticker_bars_5m, day, or_start, or_bars)
        ranking_block = _format_top2_ranking(ranked, day, or_start, or_bars)
        wr_table = _format_ticker_win_rate_table(ranked)
        if ranking_block:
            print(ranking_block)
        if wr_table:
            print(wr_table)

    # ── Pre-session top-2 performance table ──────────────────────────────────
    picks_rows = _build_presession_picks_rows(ticker_bars_5m, trading_days, or_start, or_bars)
    if picks_rows:
        print(f"\n{'=' * table_width}")
        print(
            f"Pre-Session Top-2 Performance — {start_date} to {end_date}  |  "
            f"Unconditional OR-close entry  |  OR: {or_start}/{or_bars}b"
        )
        print("=" * table_width)
        print(
            f"{'Date':<12} {'Ticker':<6} {'Rank':<5} {'At':<6} "
            f"{'Entry':>7}  {header_cols}"
        )
        print("-" * table_width)
        for row in picks_rows:
            hold_cols = []
            for mins in _HOLD_WINDOWS_MIN:
                pct = row.get(f"pct_{_hold_label(mins)}")
                if pct is None:
                    hold_cols.append(f"{'N/A':>{col_w}}")
                else:
                    tag = "W" if pct > 0 else "L"
                    hold_cols.append(f"{f'{pct:>+6.2f}%{tag}':>{col_w}}")
            print(
                f"{str(row['date']):<12} {row['ticker']:<6} {'#'+str(row['rank']):<5} "
                f"{row['signal_time']:<6} {row['entry']:>7.2f}  "
                + "  ".join(hold_cols)
            )
        n_picks = len(picks_rows)
        print(f"\n{'='*88}")
        print(f"Pre-session picks summary — {n_picks} pick(s) across {len(trading_days)} trading day(s)")
        _print_summary_block(picks_rows, "Top-2 picks (all days)")

    # ── Signal table ──────────────────────────────────────────────────────────
    print(f"\n{'=' * table_width}")
    print(
        f"Signal Analysis — {start_date} to {end_date}  |  BULL only  |  "
        f"Vol ≥ {min_vol_ratio:.1f}x 20dAvg"
    )
    print(
        f"Windows: {win_labels_str}  |  Collection: {collection_bars} bars  |  "
        f"Tickers: {len(tickers)}"
    )
    print("=" * table_width)
    print(
        f"{'Date':<12} {'Ticker':<6} {'Window':<{win_col_w}} {'At':<6} "
        f"{'Entry':>7}  {'Vol/20d':>7}  {header_cols}"
    )
    print("-" * table_width)

    results = []

    for day in trading_days:
        for w_start, w_bars in effective_windows:
            win_lbl = _window_label(w_start, w_bars)
            signals = compute_or_ma_signals(
                ticker_bars_5m, qqq_bars_5m, w_start, w_bars, day,
                daily_bars={t: daily_bars[t] for t in tickers if t in daily_bars},
                collection_bars=collection_bars,
            )
            qualifying = [
                s for s in signals
                if s["direction"] == "BULL"
                and s.get("vol_20day_avg")
                and s["collection_vol"] / s["vol_20day_avg"] >= min_vol_ratio
            ]
            for sig in qualifying:
                ticker = sig["ticker"]
                signal_time = datetime.strptime(sig["signal_bar_time"], "%H:%M").time()
                entry_price = sig["close"]
                vol_ratio = sig["collection_vol"] / sig["vol_20day_avg"]

                day_df = ticker_bars_5m.get(ticker, pd.DataFrame())
                day_df = day_df[day_df.index.date == day] if not day_df.empty else day_df

                row = {
                    "date": day,
                    "ticker": ticker,
                    "window": win_lbl,
                    "signal_time": sig["signal_bar_time"],
                    "entry": entry_price,
                    "vol_ratio": vol_ratio,
                }
                hold_cols = []
                for mins in _HOLD_WINDOWS_MIN:
                    key = f"pct_{_hold_label(mins)}"
                    pct = _forward_pct(day_df, signal_time, day, mins)
                    row[key] = pct
                    if pct is None:
                        hold_cols.append(f"{'N/A':>{col_w}}")
                    else:
                        tag = "W" if pct > 0 else "L"
                        cell = f"{pct:>+6.2f}%{tag}"
                        hold_cols.append(f"{cell:>{col_w}}")
                results.append(row)
                print(
                    f"{str(day):<12} {ticker:<6} {win_lbl:<{win_col_w}} "
                    f"{sig['signal_bar_time']:<6} "
                    f"{entry_price:>7.2f}  {vol_ratio:>6.2f}x  "
                    + "  ".join(hold_cols)
                )

    if not results:
        print("\nNo qualifying BULL signals found in date range.")
        return

    # Per-window summary blocks, then aggregate
    n = len(results)
    print(f"\n{'='*88}")
    print(f"Summary — {n} qualifying signal(s) across {len(trading_days)} trading day(s)")

    window_labels = [_window_label(s, b) for s, b in effective_windows]
    for win_lbl in window_labels:
        subset = [r for r in results if r["window"] == win_lbl]
        if subset:
            _print_summary_block(subset, f"Window {win_lbl}")

    if len(effective_windows) > 1:
        _print_summary_block(results, "All windows (aggregate)")


# ─── CLI ───────────────────────────────────────────────────────────────────────


_LOG_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "logs")
_PID_FILE = os.path.join(_LOG_DIR, "ma_or_screener.pid")


def _screener_log_file():
    return os.path.join(_LOG_DIR, f"ma_or_screener_{date.today()}.log")


# ─── Fast Win-Rate Selector Backtest ─────────────────────────────────────────


def _winrate_signal_day(ticker, df, day, or_start_time, or_bars, collection_bars, vol_20day_avg,
                        _day_df=None):
    """
    Scan one ticker for one trading day. Returns (signal, entry_price) or (None, None).

    Mirrors signal_engine._try_fire_win_rate_signal() exactly:
      BULLISH: close > OR_mid AND col_vol > vol_20day_avg AND any MA in [OR_low, OR_high]
      BEARISH: close < OR_mid AND col_vol < vol_20day_avg AND close < MA20
               AND (MA200 missing OR close < MA200) AND any MA in [OR_low, OR_high]

    Fires on the first qualifying bar in the collection window (no lookahead).
    col_vol is the incremental mean of volumes seen so far in the collection window,
    matching the live engine's cbuf accumulation.

    _day_df: pre-computed day slice to avoid repeated date filtering (optional, for perf).
    """
    day_df = _day_df if _day_df is not None else df[df.index.date == day]
    if day_df is None or day_df.empty:
        return None, None

    from_or = day_df[day_df.index.time >= or_start_time]
    if len(from_or) < or_bars:
        return None, None

    or_window = from_or.iloc[:or_bars]
    or_high = float(or_window["High"].max())
    or_low = float(or_window["Low"].min())
    or_range = or_high - or_low
    if or_range == 0:
        return None, None
    or_mid = (or_high + or_low) / 2.0

    # Collection window: last OR bar (index or_bars-1) + (collection_bars-1) extension bars
    scan_bars = from_or.iloc[or_bars - 1: or_bars - 1 + collection_bars]
    if scan_bars.empty:
        return None, None

    for i in range(len(scan_bars)):
        bar = scan_bars.iloc[i]
        col_vol = float(scan_bars.iloc[: i + 1]["Volume"].mean())
        close = float(bar["Close"])
        ma20 = bar.get("MA20")
        ma50 = bar.get("MA50")
        ma200 = bar.get("MA200")

        if pd.isna(ma20):
            continue

        overlapping_mas = [
            name
            for name, val in [("MA20", ma20), ("MA50", ma50), ("MA200", ma200)]
            if not pd.isna(val) and or_low <= float(val) <= or_high
        ]
        if not overlapping_mas:
            continue

        bull = close > or_mid and col_vol > vol_20day_avg
        ma200_f = float(ma200) if not pd.isna(ma200) else None
        bear = (
            close < or_mid
            and col_vol < vol_20day_avg
            and close < float(ma20)
            and (ma200_f is None or close < ma200_f)
        )

        if not bull and not bear:
            continue

        return ("BULLISH" if bull else "BEARISH"), close

    return None, None


def _winrate_exit_with_fallback(
    day_df, signal, or_high, or_low, or_range, entry_bar_idx, hold_minutes=None
):
    """
    Compute the exit price for a trade, mirroring PositionMonitor with stop_pct=0.

    With stop_pct=0:
      bull_hard_stop  = or_high   (arms when close > or_high)
      bull_fallback   = or_high - 0.20 × or_range  (fires when not armed and close <= fallback)
      bear_hard_stop  = or_low    (arms when close < or_low)
      bear_fallback   = or_low + 0.20 × or_range   (fires when not armed and close >= fallback)

    Scans bars from entry_bar_idx+1 onwards. Returns the exit price (override or last close).

    hold_minutes: if set (e.g. 15 for CAUTION/+15m regime-hold), the position exits at the
    first bar at or after entry_time + hold_minutes, matching the live engine's timed_exit.
    """
    if signal == "BULLISH":
        hard_stop = or_high
        fallback_price = or_high - 0.20 * or_range
    else:
        hard_stop = or_low
        fallback_price = or_low + 0.20 * or_range

    # Exclude the 15:55 bar — replay's BarReplayDriver uses strict < 15:55 cutoff,
    # so position_monitor.close_all() exits at the 15:50 bar close, not 15:55.
    eod_df = day_df[day_df.index.time < _dt_time(15, 55)]
    bars_after = eod_df.iloc[entry_bar_idx + 1:]

    # Compute timed exit cutoff if hold_minutes is specified.
    # hold_minutes is relative to entry bar open time (already adjusted for drain
    # delay at call site: +5 for scan_idx=0, +0 for scan_idx>=1).
    timed_exit_time = None
    if hold_minutes is not None and not bars_after.empty:
        entry_ts = day_df.index[entry_bar_idx]
        timed_exit_time = (
            datetime.combine(entry_ts.date(), entry_ts.time()) + timedelta(minutes=hold_minutes)
        ).time()
    hard_stop_armed = False

    for i in range(len(bars_after)):
        bar = bars_after.iloc[i]
        close = float(bar["Close"])
        bar_open = float(bar["Open"])
        bar_high = float(bar["High"])
        bar_low = float(bar["Low"])
        bar_time = bars_after.index[i].time()

        if signal == "BULLISH":
            if not hard_stop_armed and close > hard_stop:
                hard_stop_armed = True
            if hard_stop_armed and close <= hard_stop:
                # Hard stop: price broke above OR_high then came back to it.
                # Override: exit at hard_stop if bar reached it, else bar_open.
                return hard_stop if bar_high >= hard_stop else bar_open
            elif not hard_stop_armed and close <= fallback_price:
                # Fallback: price dropped adversely to/below fallback level.
                # Override: exit at fallback if bar's high reached fallback (gapped through),
                # else exit at close (bar opened and stayed below fallback, no better fill).
                return fallback_price if bar_high >= fallback_price else close
        else:  # BEARISH
            if not hard_stop_armed and close < hard_stop:
                hard_stop_armed = True
            if hard_stop_armed and close >= hard_stop:
                # Hard stop: price broke below OR_low then bounced back to it.
                return hard_stop if bar_low <= hard_stop else bar_open
            elif not hard_stop_armed and close >= fallback_price:
                # Fallback: price bounced adversely to/above fallback level.
                # Override: exit at fallback if bar's low reached it (gapped through),
                # else exit at bar_open (bar opened above fallback, fill at open).
                return fallback_price if bar_low <= fallback_price else bar_open

        # Timed exit: checked after stops so hard_stop/fallback take precedence on the same bar
        # (mirrors position_monitor._evaluate_stop order: stops → timed_exit).
        if timed_exit_time is not None and bar_time >= timed_exit_time:
            return close

    return float(eod_df.iloc[-1]["Close"])


def run_winrate_selector_backtest(
    tickers,
    start_date,
    end_date,
    or_start=_DEFAULT_OR_START,
    or_bars=_DEFAULT_OR_BARS,
    collection_bars=3,
    top_n=8,
    capital=80_000.0,
    feed="sip",
    lookback_days=60,
    use_regime_engine=True,
    verbose=False,
):
    """
    Fast in-process backtest mirroring the win-rate selector + regime-hold strategy.

    Replaces the per-day replay process approach. Loads all bars once, then loops
    over trading days computing pre-session rankings, regime direction, OR signals,
    and EOD P&L in a single Python process.

    Assumes: regime-hold (EOD exit), stop-pct=0, trailing-ma=none.
    Mirrors: WinRateTickerSelector, signal_engine._try_fire_win_rate_signal, RegimeEngine.
    """
    from .regime_engine import RegimeEngine

    effective_feed = DataFeed.SIP if feed == "sip" else DataFeed.IEX
    warmup_start = start_date - timedelta(days=lookback_days + 30)
    all_tickers_fetch = list(tickers) + (["QQQ"] if "QQQ" not in list(tickers) else [])

    print(f"Loading bars {warmup_start} → {end_date} for {len(all_tickers_fetch)} tickers ...")
    bars_raw = fetch_bars(all_tickers_fetch, warmup_start, end_date, "alpaca", feed=effective_feed)
    bars_5m = {t: _add_ma_columns(df) for t, df in bars_raw.items() if not df.empty}

    ticker_bars = {t: df for t, df in bars_5m.items() if t != "QQQ"}
    or_start_time = datetime.strptime(or_start, "%H:%M").time()

    # Pre-group bars by date for O(1) day slicing (avoids repeated df.index.date == day scans).
    ticker_day_groups = {}
    for t, df in ticker_bars.items():
        groups = {}
        for d, grp in df.groupby(df.index.date):
            groups[d] = grp
        ticker_day_groups[t] = groups

    trading_days = sorted({
        d
        for t_groups in ticker_day_groups.values()
        for d in t_groups
        if start_date <= d <= end_date
    })
    if not trading_days:
        print("No trading days found in range.")
        return {}

    print(f"Simulating {len(trading_days)} trading days ...")

    regime_engine_obj = RegimeEngine() if use_regime_engine else None
    daily_results = []

    for day_idx, day in enumerate(trading_days):
        # Mirror WinRateTickerSelector.fetch_bars() exactly:
        #   fetch_start = today - (lookback_days + 5)
        #   _trim_bars_to_range adds 7 extra days (= _CACHE_WARMUP_DAYS) before that start.
        # Net effective window: today - (lookback_days + 5 + 7) = today - (lookback_days + 12).
        # Use dict key filtering instead of df.index.date slicing to avoid datetime conversion.
        ranking_window_start = day - timedelta(days=lookback_days + 5 + 7)
        windowed_day_groups = {
            t: {d: grp for d, grp in groups.items() if d >= ranking_window_start}
            for t, groups in ticker_day_groups.items()
        }
        ranked = _rank_tickers_by_eod_win_rate(
            ticker_bars, day, or_start, or_bars, lookback_days,
            ticker_day_groups=windowed_day_groups,
        )

        if regime_engine_obj is not None:
            prev_day = trading_days[day_idx - 1] if day_idx > 0 else None
            if prev_day is not None:
                regime_engine_obj.compute_and_add_metrics(
                    bars_5m, prev_day, or_start, or_bars, collection_bars
                )
            # Match live engine: trade_engine.py calls get_current_regime(as_of_date=today)
            # with no presession_top2_wr. Passing it would trigger a pre-session NEUTRAL→LONG
            # override that the live engine never applies.
            regime = regime_engine_obj.get_current_regime(as_of_date=day)
            direction = regime.direction
        else:
            direction = "LONG"

        # Extract timed-exit window for CAUTION regime with --regime-hold.
        # CAUTION+15m exits 15 min after entry; CAUTION+EOD / other regimes use EOD.
        _regime_hold_minutes = {
            "+15m": 15, "+30m": 30, "+1h": 60, "+2h": 120, "+3h": 180, "+5h": 300,
            "EOD": None,
        }
        hold_mins = None
        if regime_engine_obj is not None and direction == "CAUTION":
            hold_mins = _regime_hold_minutes.get(getattr(regime, "hold_window", None))

        if direction == "NO_POSITION":
            daily_results.append({"date": day, "pnl": 0.0, "deployed": 0.0, "trades": []})
            continue

        # CAUTION: no direction filter (both BULLISH and BEARISH allowed), mirrors live engine.
        # SHORT: bottom-N by win rate (worst first).
        if direction == "SHORT":
            picks = [t for t, _ in list(reversed(ranked[-top_n:]))]
        else:
            picks = [t for t, _ in ranked[:top_n]]

        trades = []
        for ticker in picks:
            df = ticker_bars.get(ticker)
            if df is None:
                continue

            # Use 20-day vol lookback, matching signal_engine._compute_collection_vol_20day_avg default.
            vol_avg = _compute_collection_vol_20day_avg(
                df, or_start_time, or_bars, collection_bars, day,
                day_groups=ticker_day_groups.get(ticker),
            )
            if vol_avg is None:
                continue

            day_df = ticker_day_groups.get(ticker, {}).get(day)
            if day_df is None or day_df.empty:
                continue

            from_or = day_df[day_df.index.time >= or_start_time]
            if len(from_or) < or_bars:
                continue

            # Compute OR range once (reused for signal detection and fallback stop).
            or_window = from_or.iloc[:or_bars]
            or_h = float(or_window["High"].max())
            or_l = float(or_window["Low"].min())
            or_r = or_h - or_l
            if or_r == 0:
                continue

            signal, entry_price = _winrate_signal_day(
                ticker, df, day, or_start_time, or_bars, collection_bars, vol_avg,
                _day_df=day_df,
            )
            if signal is None:
                continue

            if direction == "LONG" and signal == "BEARISH":
                continue
            if direction == "SHORT" and signal == "BULLISH":
                continue

            # Find entry bar position in day_df without get_loc (O(log n) searchsorted).
            scan_bars = from_or.iloc[or_bars - 1: or_bars - 1 + collection_bars]
            entry_scan_idx = 0
            for si in range(len(scan_bars)):
                if abs(float(scan_bars.iloc[si]["Close"]) - entry_price) < 1e-6:
                    entry_scan_idx = si
                    break
            from_or_start = int(day_df.index.searchsorted(from_or.index[0]))
            entry_abs_idx = from_or_start + (or_bars - 1) + entry_scan_idx

            # Apply fallback_20pct stop (always active, mirrors PositionMonitor with stop_pct=0).
            # For CAUTION timed exit: live engine drain fires at OR close (or_bars*5m after start),
            # which is 1 bar (5 min) after scan[0] fires but the same bar for scan[i>=1].
            # Adjust hold_minutes to account for this drain delay when entry is on scan[0].
            if hold_mins is not None:
                drain_delay = 5 if entry_scan_idx == 0 else 0
                effective_hold = hold_mins + drain_delay
            else:
                effective_hold = None
            exit_price = _winrate_exit_with_fallback(
                day_df, signal, or_h, or_l, or_r, entry_abs_idx, hold_minutes=effective_hold
            )

            trades.append({
                "ticker": ticker,
                "signal": signal,
                "entry_price": entry_price,
                "exit_price": exit_price,
            })

        if not trades:
            daily_results.append({"date": day, "pnl": 0.0, "deployed": 0.0, "trades": []})
            continue

        # Mirror --fixed-signal-alloc: each slot always gets capital/top_n regardless
        # of how many signals fired. If only 3 of 8 picks fire, each still gets capital/8.
        slot_capital = capital / top_n
        day_pnl = 0.0
        for trade in trades:
            sign = 1 if trade["signal"] == "BULLISH" else -1
            pnl = (
                (trade["exit_price"] - trade["entry_price"])
                / trade["entry_price"]
                * slot_capital
                * sign
            )
            trade["pnl"] = pnl
            trade["slot_capital"] = slot_capital
            day_pnl += pnl

        daily_results.append({
            "date": day,
            "pnl": day_pnl,
            "deployed": slot_capital * len(trades),
            "trades": trades,
        })

    _print_winrate_backtest_summary(
        daily_results, capital, list(tickers),
        or_start, or_bars, collection_bars, top_n,
        start_date, end_date, verbose,
    )
    return {"daily": daily_results}


def _print_winrate_backtest_summary(
    daily_results, capital, tickers,
    or_start, or_bars, collection_bars, top_n,
    start_date, end_date, verbose,
):
    month_names = [
        "Jan", "Feb", "Mar", "Apr", "May", "Jun",
        "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
    ]

    months = {}
    total_deployed = 0.0
    trade_days = 0
    for r in daily_results:
        day = r["date"]
        mkey = f"{day.year}-{day.month:02d}"
        months[mkey] = months.get(mkey, 0.0) + r["pnl"]
        total_deployed += r["deployed"]
        if r["trades"]:
            trade_days += 1

    total_days = len(daily_results)
    total_pnl = sum(r["pnl"] for r in daily_results)
    avg_dep = total_deployed / total_days if total_days else 0.0
    util = total_deployed / (total_days * capital) if total_days and capital else 0.0

    ticker_preview = " ".join(tickers[:6])
    if len(tickers) > 6:
        ticker_preview += f" +{len(tickers) - 6} more"

    print()
    print("╔══ Win-Rate Selector Backtest ══════════════════════════════════════")
    print(f"║  Pool     : {ticker_preview}  ({len(tickers)} tickers)")
    print(f"║  Config   : {or_start}/{or_bars}b  collect={collection_bars}  top-{top_n}  ${capital:,.0f}  feed=sip")
    print(f"║  Period   : {start_date} → {end_date}  ({total_days} trading days)")
    print("╠══ MONTHLY ══════════════════════════════════════════════════════════")
    for mkey in sorted(months.keys()):
        mp = months[mkey]
        sign = "+" if mp >= 0 else ""
        m_idx = int(mkey.split("-")[1]) - 1
        yr = mkey.split("-")[0]
        print(f"║  {month_names[m_idx]} {yr}   {sign}${mp:>10,.2f}   ({sign}{mp / capital * 100:.1f}%)")

    days_with_dep = [(r["pnl"], r["deployed"]) for r in daily_results if r["deployed"] > 0]
    rodc_str = "n/a"
    dw_sharpe_str = "n/a"
    if days_with_dep:
        rodcs = [p / d for p, d in days_with_dep]
        rodc_str = f"{sum(rodcs) / len(rodcs) * 100:+.3f}%"
        if len(days_with_dep) >= 2:
            deps = [d for _, d in days_with_dep]
            avg_d = sum(deps) / len(deps)
            w = [d / avg_d for d in deps]
            w_sum = sum(w)
            w_mean = sum(wi * ri for wi, ri in zip(w, rodcs)) / w_sum
            w_var = sum(wi * (ri - w_mean) ** 2 for wi, ri in zip(w, rodcs)) / w_sum
            w_std = math.sqrt(w_var) if w_var > 0 else 0.0
            if w_std > 0:
                dw_sharpe_str = f"{w_mean / w_std * math.sqrt(252):.2f}"

    sign = "+" if total_pnl >= 0 else ""
    print("╠══ SUMMARY ══════════════════════════════════════════════════════════")
    print(f"║  Total       {total_days}d   {sign}${total_pnl:>10,.2f}   ({sign}{total_pnl / capital * 100:.1f}% on ${capital:,.0f})")
    print(f"║  Trade days  {trade_days} / {total_days}  ({trade_days / total_days * 100:.0f}%)")
    print(f"║  Avg deployed   ${avg_dep:>10,.0f}  |  util {util * 100:.1f}%")
    print(f"║  Mean RODC      {rodc_str}")
    print(f"║  DW-Sharpe      {dw_sharpe_str}")
    print("╚════════════════════════════════════════════════════════════════════")

    if verbose:
        print()
        print("── DAILY ──────────────────────────────────────────────────────────")
        for r in daily_results:
            pnl = r["pnl"]
            tickers_str = " ".join(t["ticker"] for t in r["trades"]) if r["trades"] else "—"
            day_name = r["date"].strftime("%a")
            sign2 = "+" if pnl >= 0 else ""
            print(
                f"  {r['date']} {day_name}"
                f"  [{tickers_str:<32}]"
                f"  {sign2}${pnl:>9,.2f}"
            )


def _make_log_handler(log_file):
    import re
    handler = logging.handlers.TimedRotatingFileHandler(
        log_file, when="midnight", backupCount=30, encoding="utf-8"
    )
    handler.namer = lambda name: re.sub(
        r'(ma_or_screener)_[\d-]+(\.log)\.(\d{4}-\d{2}-\d{2})$', r'\1_\3\2', name
    )
    return handler


def _write_pid(pid_file):
    with open(pid_file, "w") as f:
        f.write(str(os.getpid()))


def _read_pid(pid_file):
    try:
        with open(pid_file) as f:
            return int(f.read().strip())
    except (FileNotFoundError, ValueError):
        return None


def _remove_pid(pid_file):
    try:
        os.remove(pid_file)
    except FileNotFoundError:
        pass


def _is_running(pid):
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def _daemonize(log_file):
    """Double-fork to detach from terminal."""
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


def _daemon_stop(pid_file, log_file):
    pid = _read_pid(pid_file)
    if pid is None or not _is_running(pid):
        print("Screener daemon is not running.")
        _remove_pid(pid_file)
        return
    print(f"Stopping screener daemon (PID {pid})...")
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
    print(f"Screener daemon stopped (PID {pid}).")


def _setup_logging(log_file, level="INFO", foreground=False):
    fmt = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    root = logging.getLogger()
    root.setLevel(getattr(logging, level))
    root.handlers.clear()
    fh = _make_log_handler(log_file)
    fh.setFormatter(fmt)
    root.addHandler(fh)
    if foreground:
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        root.addHandler(sh)
    for noisy in ("urllib3", "requests", "requests_oauthlib", "oauthlib", "websockets"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def _build_live_market_data_client():
    from alpha_tech_tracker.op_momentum_strategy.config import (
        _TRADESTATION_SESSION_TOKENS,
        TRADESTATION_ENVIRONMENT,
        _load_config,
    )
    from alpha_tech_tracker.trade_api.tradestation.client import TradeStationAPIClient
    from alpha_tech_tracker.trade_api.tradestation.market_data_client import (
        TradeStationMarketDataClient,
    )
    _load_config()
    if not _TRADESTATION_SESSION_TOKENS.get("access_token"):
        raise RuntimeError(
            "TradeStation session not found — run tradestation_auth.py first"
        )
    ts_client = TradeStationAPIClient(environment=TRADESTATION_ENVIRONMENT)
    ts_client.restore_session(_TRADESTATION_SESSION_TOKENS)
    if not ts_client.verify_session():
        raise RuntimeError(
            "TradeStation session invalid — run tradestation_auth.py first"
        )
    return TradeStationMarketDataClient(ts_client)


def _build_arg_parser():
    parser = argparse.ArgumentParser(description="MA Open Range Momentum Screener")
    parser.add_argument(
        "action",
        nargs="?",
        default="backtest",
        choices=["run", "start", "stop", "status", "restart", "logs", "backtest", "analyze", "winrate-backtest"],
        help=(
            "run: live foreground | start: live daemon | stop | status | restart | "
            "logs: tail the log file | backtest: single-date backtest (default) | "
            "analyze: date-range analysis | winrate-backtest: fast multi-day win-rate selector backtest"
        ),
    )
    parser.add_argument(
        "--date", default=None,
        help="Target date YYYY-MM-DD for backtest (default: today)"
    )
    parser.add_argument("--live", action="store_true", help=argparse.SUPPRESS)  # legacy alias for 'run'
    parser.add_argument(
        "--or-bars", type=int, default=_DEFAULT_OR_BARS,
        help=f"5-min bars in the opening range (default {_DEFAULT_OR_BARS})"
    )
    parser.add_argument(
        "--or-start", default=_DEFAULT_OR_START,
        help=f"OR start time ET, e.g. 09:30 (default {_DEFAULT_OR_START})"
    )
    parser.add_argument(
        "--collection-bars", type=int, default=3,
        help="Bars to scan for signals starting at OR close (default 3)"
    )
    parser.add_argument(
        "--tickers", nargs="+", default=None,
        help="Override ticker pool (default: DEFAULT_TICKERS)"
    )
    parser.add_argument(
        "--source", default="alpaca", choices=["alpaca", "tradestation"],
        help="Data source for backtest (default: alpaca)"
    )
    parser.add_argument(
        "--feed", default="sip", choices=["sip", "iex"],
        help="Alpaca feed for backtest (default: sip)"
    )
    parser.add_argument(
        "--poll-interval", type=int, default=30,
        help="Seconds between live polls (default: 30)"
    )
    parser.add_argument("--dry-run", action="store_true", help="Suppress SMS in live mode")
    parser.add_argument(
        "--enable-regime-engine", action="store_true",
        help="Enable MASTER_REGIME_SUMMARY pattern-based regime engine (direction filter + hold window)"
    )
    parser.add_argument("--print-all", action="store_true",
                        help="Print non-signal tickers in backtest output")
    parser.add_argument(
        "--start", default=None,
        help="Start date YYYY-MM-DD for range analysis"
    )
    parser.add_argument(
        "--end", default=None,
        help="End date YYYY-MM-DD for range analysis"
    )
    parser.add_argument(
        "--min-vol-ratio", type=float, default=2.0,
        help="Minimum vol/20dAvg ratio to qualify for range analysis (default: 2.0)"
    )
    parser.add_argument(
        "--window", nargs=2, metavar=("HH:MM", "BARS"), action="append", dest="windows",
        help="OR window for range analysis: start time and bar count (repeatable)."
    )
    parser.add_argument(
        "--pid-file", default=_PID_FILE,
        help=f"PID file path for daemon mode (default: {_PID_FILE})"
    )
    parser.add_argument(
        "--log-file", default=None,
        help="Log file path (default: logs/ma_or_screener_YYYY-MM-DD.log)"
    )
    parser.add_argument(
        "--log-level", default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Log level (default: INFO)"
    )
    # ── winrate-backtest args ──────────────────────────────────────────────────
    parser.add_argument(
        "--top", type=int, default=8,
        help="Top-N tickers to select per day in winrate-backtest (default: 8)"
    )
    parser.add_argument(
        "--capital", type=float, default=80_000.0,
        help="Daily capital in winrate-backtest (default: 80000)"
    )
    parser.add_argument(
        "--lookback-days", type=int, default=60, dest="lookback_days",
        help="EOD win-rate ranking lookback in trading days (default: 60)"
    )
    parser.add_argument(
        "--no-regime", action="store_true", dest="no_regime",
        help="Disable RegimeEngine direction filter in winrate-backtest"
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Print per-day trade table in winrate-backtest output"
    )
    return parser


def _run_live(args, tickers):
    market_data_client = _build_live_market_data_client()
    run_live(
        tickers=tickers,
        or_bars=args.or_bars,
        or_start=args.or_start,
        collection_bars=args.collection_bars,
        market_data_client=market_data_client,
        poll_interval_sec=args.poll_interval,
        dry_run=args.dry_run,
        enable_regime_engine=args.enable_regime_engine,
    )


def main():
    parser = _build_arg_parser()
    args = parser.parse_args()

    # Backwards-compat: bare --live flag maps to "run" action
    if getattr(args, "live", False) and args.action == "backtest":
        args.action = "run"

    tickers = args.tickers if args.tickers else list(DEFAULT_TICKERS)
    feed = DataFeed.SIP if args.feed == "sip" else DataFeed.IEX
    log_file = args.log_file or _screener_log_file()
    os.makedirs(os.path.dirname(os.path.abspath(log_file)), exist_ok=True)

    # ── logs ──────────────────────────────────────────────────────────────────
    if args.action == "logs":
        if not os.path.exists(log_file):
            print(f"No log file found: {log_file}")
            sys.exit(1)
        print(f"==> {log_file} <==")
        try:
            os.execvp("tail", ["tail", "-f", log_file])
        except Exception as exc:
            print(f"tail failed: {exc}")
            sys.exit(1)

    # ── status ────────────────────────────────────────────────────────────────
    if args.action == "status":
        pid = _read_pid(args.pid_file)
        if pid and _is_running(pid):
            print(f"Screener daemon running (PID {pid}) — log: {log_file}")
        else:
            print("Screener daemon is not running.")
        sys.exit(0)

    # ── stop ──────────────────────────────────────────────────────────────────
    if args.action == "stop":
        _daemon_stop(args.pid_file, log_file)
        sys.exit(0)

    # ── restart ───────────────────────────────────────────────────────────────
    if args.action == "restart":
        _daemon_stop(args.pid_file, log_file)

    # ── run (foreground live) ─────────────────────────────────────────────────
    if args.action == "run":
        _setup_logging(log_file, level=args.log_level, foreground=True)
        logger.info("Starting screener in foreground — log: %s", log_file)
        _run_live(args, tickers)
        sys.exit(0)

    # ── start / restart (daemon) ──────────────────────────────────────────────
    if args.action in ("start", "restart"):
        existing_pid = _read_pid(args.pid_file)
        if existing_pid and _is_running(existing_pid):
            print(f"Screener daemon already running (PID {existing_pid}). Use 'restart' or 'stop' first.")
            sys.exit(1)
        print(f"Starting screener daemon — log: {log_file}")
        _daemonize(log_file)
        # daemon process only beyond this point
        _write_pid(args.pid_file)
        _setup_logging(log_file, level=args.log_level, foreground=False)
        logger.info("Screener daemon started (PID %d)", os.getpid())
        try:
            _run_live(args, tickers)
        except Exception:
            logger.exception("Screener daemon crashed")
        finally:
            _remove_pid(args.pid_file)
        sys.exit(0)

    # ── winrate-backtest ──────────────────────────────────────────────────────
    if args.action == "winrate-backtest":
        if not args.start or not args.end:
            print("winrate-backtest requires --start and --end")
            sys.exit(1)
        run_winrate_selector_backtest(
            tickers=tickers,
            start_date=date.fromisoformat(args.start),
            end_date=date.fromisoformat(args.end),
            or_start=args.or_start,
            or_bars=args.or_bars,
            collection_bars=args.collection_bars,
            top_n=args.top,
            capital=args.capital,
            feed=args.feed,
            lookback_days=args.lookback_days,
            use_regime_engine=not args.no_regime,
            verbose=args.verbose,
        )
        return

    # ── analyze (date-range) ──────────────────────────────────────────────────
    if args.action == "analyze" or (args.start and args.end):
        windows = (
            [(w[0], int(w[1])) for w in args.windows]
            if args.windows else None
        )
        run_range_analysis(
            start_date=date.fromisoformat(args.start),
            end_date=date.fromisoformat(args.end),
            tickers=tickers,
            windows=windows,
            or_bars=args.or_bars,
            or_start=args.or_start,
            collection_bars=args.collection_bars,
            min_vol_ratio=args.min_vol_ratio,
            source=args.source,
            feed=feed,
        )
        return

    # ── backtest (default) ────────────────────────────────────────────────────
    target_date = date.fromisoformat(args.date) if args.date else date.today()
    run_backtest(
        target_date=target_date,
        tickers=tickers,
        or_bars=args.or_bars,
        or_start=args.or_start,
        collection_bars=args.collection_bars,
        source=args.source,
        feed=feed,
        print_all=args.print_all,
        enable_regime_engine=args.enable_regime_engine,
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    main()

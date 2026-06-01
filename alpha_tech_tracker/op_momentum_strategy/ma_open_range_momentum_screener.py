import argparse
import logging
import os
import time
from datetime import date, datetime, timedelta
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
_5MIN_WARMUP_DAYS = 14    # guarantees 200+ 5-min bars across holiday gaps
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
) -> Optional[float]:
    """
    Compute the average volume across the collection window time slots over the
    past `lookback_days` trading days.

    The collection window starts at the OR close bar open time
    (or_start + (or_bars-1)*5 min) and covers `collection_bars` bars.
    Each prior trading day contributes the mean volume of bars in those same
    time slots, then the overall mean is returned.
    """
    or_start_dt = datetime.combine(date.today(), or_start_time)
    collection_start = (or_start_dt + timedelta(minutes=(or_bars - 1) * 5)).time()
    collection_end = (
        or_start_dt + timedelta(minutes=(or_bars - 1 + collection_bars - 1) * 5)
    ).time()

    prior_dates = sorted(
        {d for d in df.index.date if d < target_date}, reverse=True
    )[:lookback_days]

    if not prior_dates:
        return None

    daily_avgs = []
    for d in prior_dates:
        day = df[df.index.date == d]
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

    # Collection window volume today (mean across the scan bars)
    scan_slice = from_or.iloc[or_bars - 1 : or_bars - 1 + collection_bars]
    collection_vol = float(scan_slice["Volume"].mean()) if not scan_slice.empty else None
    if collection_vol is None:
        return None

    scan_start = or_bars - 1
    scan_end = scan_start + collection_bars
    for idx, bar in from_or.iloc[scan_start:scan_end].iterrows():
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

    _print_backtest_table(
        signals, list(tickers), ticker_bars_5m, or_start, or_bars, target_date, print_all,
        collection_bars=collection_bars,
    )

    return {
        "signals": signals,
        "bars_5m": ticker_bars_5m,
        "bars_1m": bars_1m,
        "daily_bars": daily_bars,
    }


# ─── Live polling entry point ──────────────────────────────────────────────────


def run_live(
    tickers,
    or_bars=_DEFAULT_OR_BARS,
    or_start=_DEFAULT_OR_START,
    collection_bars=3,
    market_data_client=None,
    poll_interval_sec=30,
    dry_run=False,
):
    """
    Poll live 5-min bars from TradeStation and fire SMS on OR/MA overlap signals.

    Signals are re-evaluated after each new bar (per-bar, not just at OR close).
    Each ticker fires at most once per session. A summary SMS is sent at EOD.
    """
    if dry_run:
        disable_notifications()

    or_start_time = datetime.strptime(or_start, "%H:%M").time()
    or_close_time = (
        datetime.combine(date.today(), or_start_time) + timedelta(minutes=or_bars * 5)
    ).time()
    eod_time = datetime.strptime(_EOD_TIME, "%H:%M").time()

    all_tickers = list(tickers) + (["QQQ"] if "QQQ" not in tickers else [])

    # Pre-warm from Alpaca historical data (prior days only — safe to cache)
    yesterday = (_now_et() - timedelta(days=1)).date()
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

    already_notified = set()
    summary_sent = False
    session_signals = []
    current_day = None

    print(
        f"Live polling started. OR: {or_start}/{or_bars} bars "
        f"(closes {or_close_time.strftime('%H:%M')}). "
        f"Poll: {poll_interval_sec}s. Dry-run: {dry_run}."
    )

    while True:
        now_et = _now_et()
        today = now_et.date()
        now_time = now_et.time()

        if current_day != today:
            current_day = today
            already_notified = set()
            summary_sent = False
            session_signals = []
            print(f"\n--- {today} ---")

        if now_time < or_close_time:
            time.sleep(poll_interval_sec)
            continue

        if now_time >= eod_time:
            if not summary_sent:
                _send_session_summary(session_signals, today)
                summary_sent = True
            time.sleep(60)
            continue

        # Fetch today's live bars from TradeStation
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

        qqq_bars_5m = merged_bars.get("QQQ", pd.DataFrame())
        ticker_bars_5m = {t: df for t, df in merged_bars.items() if t != "QQQ"}

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
                already_notified.add(sig["ticker"])
                session_signals.append(sig)
                sms = format_sms(sig)
                print(f"SIGNAL: {sms}")
                _notify(sms)

        time.sleep(poll_interval_sec)


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


def _window_label(or_start, or_bars):
    """Short label used in table and summary, e.g. '09:30/3b'."""
    return f"{or_start}/{or_bars}b"


def _print_summary_block(results_subset, label):
    """Print one summary block (one window or aggregate) for the given result rows."""
    n = len(results_subset)
    print(f"\n{label}  ({n} signal(s))")
    print(f"  {'Hold':<8} {'Count':>6} {'Win Rate':>10} {'Avg Gain':>10} {'Avg Win':>10} {'Avg Loss':>10} {'Exp Value':>10} {'Total P&L':>10}")
    print("  " + "-" * 84)
    for mins in _HOLD_WINDOWS_MIN:
        key = f"pct_{_hold_label(mins)}"
        pcts = [r[key] for r in results_subset if r.get(key) is not None]
        if not pcts:
            continue
        wins = [p for p in pcts if p > 0]
        losses = [p for p in pcts if p <= 0]
        win_rate = len(wins) / len(pcts) * 100
        avg_gain = sum(pcts) / len(pcts)
        avg_win = sum(wins) / len(wins) if wins else 0.0
        avg_loss = sum(losses) / len(losses) if losses else 0.0
        exp_val = (win_rate / 100) * avg_win + (1 - win_rate / 100) * avg_loss
        total_pnl = sum(pcts)
        print(
            f"  {_hold_label(mins):<8} {len(pcts):>6} {win_rate:>9.1f}% "
            f"{avg_gain:>+10.2f}% {avg_win:>+10.2f}% {avg_loss:>+10.2f}% "
            f"{exp_val:>+10.2f}% {total_pnl:>+10.2f}%"
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

    warmup_start = start_date - timedelta(days=30)
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

    win_labels_str = ", ".join(_window_label(s, b) for s, b in effective_windows)
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


def _build_live_market_data_client():
    from alpha_tech_tracker.trade_api.tradestation.market_data_client import (
        TradeStationMarketDataClient,
    )
    return TradeStationMarketDataClient()


def main():
    parser = argparse.ArgumentParser(
        description="MA Open Range Momentum Screener"
    )
    parser.add_argument(
        "--date", default=None,
        help="Target date YYYY-MM-DD for backtest (default: today)"
    )
    parser.add_argument("--live", action="store_true", help="Run in live polling mode")
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
        help="Bars to scan for signals starting at OR close (default 3 = 15 min window)"
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
        help="OR window for range analysis: start time and bar count (repeatable). "
             "Overrides --or-start/--or-bars when used with --start/--end."
    )
    args = parser.parse_args()

    tickers = args.tickers if args.tickers else list(DEFAULT_TICKERS)
    feed = DataFeed.SIP if args.feed == "sip" else DataFeed.IEX

    if args.live:
        market_data_client = _build_live_market_data_client()
        run_live(
            tickers=tickers,
            or_bars=args.or_bars,
            or_start=args.or_start,
            collection_bars=args.collection_bars,
            market_data_client=market_data_client,
            poll_interval_sec=args.poll_interval,
            dry_run=args.dry_run,
        )
    elif args.start and args.end:
        windows = (
            [(w[0], int(w[1])) for w in args.windows]
            if args.windows
            else None
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
    else:
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
        )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    main()

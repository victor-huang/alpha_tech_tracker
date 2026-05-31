import argparse
import os
import re
import threading
import pandas as pd
import pytz
import yfinance as yf
from datetime import date, datetime, time as _time, timedelta
from pathlib import Path

from alpaca.data.enums import DataFeed
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit


TICKERS = ["NVDA", "CRWD", "COIN", "JNJ", "XOM", "CAT"]
SUCCESS_BARS = 3  # "long enough" = held correct side for >= 3 bars (15 min)

# No new positions (primary or any re-entry) may be opened after this time.
NO_MORE_NEW_POSITION_AFTER = _time(15, 48)

# OR vol ratio acceleration boost: if every successive OR bar's volume grows by more than
# this threshold, or_vol_ratio is multiplied by (1 + boost). Validated via 2026 sweep.
_OR_VOL_ACC_THRESHOLD = 0.08
_OR_VOL_ACC_BOOST = 0.20

_CACHE_DIR = Path(__file__).parent.parent.parent / "market_data" / "cache"

# Extra calendar days before start_date retained for MA warmup (MA200 needs ~3 trading days).
_CACHE_WARMUP_DAYS = 7

# Alpaca data feed used for all bar fetches. Changing this automatically updates cache keys
# so IEX and SIP data live in separate cache files (e.g. alpaca_iex_5min_... vs alpaca_sip_5min_...).
_ALPACA_FEED = DataFeed.SIP


def _trim_bars_to_range(df: pd.DataFrame, start_date: date, end_date: date) -> pd.DataFrame:
    """Trim a 5-min bar DataFrame to [start_date - warmup, end_date] to prevent cache bloat."""
    warmup_start = start_date - timedelta(days=_CACHE_WARMUP_DAYS)
    return df[(df.index.date >= warmup_start) & (df.index.date <= end_date)]


def _cache_source(source: str, feed: DataFeed = None) -> str:
    """Return the cache-key source string, encoding the Alpaca feed name for alpaca sources."""
    if source == "alpaca":
        effective_feed = feed if feed is not None else _ALPACA_FEED
        return f"alpaca_{effective_feed.value}"
    return source


def _cache_path(
    ticker: str, start: date, end: date, source: str, timeframe: str
) -> Path:
    return _CACHE_DIR / f"{source}_{timeframe}_{ticker}_{start}_{end}.json"


def _save_cache(df: pd.DataFrame, path: Path, timeframe: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{os.getpid()}_{threading.get_ident()}.tmp")
    df.to_json(tmp, orient="split", date_format="iso")
    tmp.replace(path)  # atomic on POSIX — readers see old or new file, never a partial write


def _load_cache(path: Path, timeframe: str) -> pd.DataFrame:
    df = pd.read_json(path, orient="split")
    if timeframe == "5min":
        df.index = pd.to_datetime(df.index, utc=True).tz_convert("America/New_York")
    else:
        df.index = pd.to_datetime(df.index).date
    return df


def _to_date(d) -> date:
    return d.date() if isinstance(d, datetime) else d


def _evict_contained_cache_pieces(
    ticker: str, new_start: date, new_end: date, source: str, timeframe: str
) -> None:
    """Delete per-period cache files whose span is fully contained within [new_start, new_end].

    Called after saving a consolidated cache file so that smaller overlapping
    pieces don't accumulate and confuse the stitcher.
    """
    pattern = re.compile(
        rf"^{re.escape(source)}_{re.escape(timeframe)}_{re.escape(ticker)}"
        rf"_(\d{{4}}-\d{{2}}-\d{{2}})_(\d{{4}}-\d{{2}}-\d{{2}})\.json$"
    )
    for f in list(_CACHE_DIR.iterdir()):
        m = pattern.match(f.name)
        if not m:
            continue
        c_start = date.fromisoformat(m.group(1))
        c_end = date.fromisoformat(m.group(2))
        # Skip the file we just saved
        if c_start == new_start and c_end == new_end:
            continue
        if c_start >= new_start and c_end <= new_end:
            try:
                f.unlink()
            except FileNotFoundError:
                pass  # another process evicted it first


def _is_cacheable(end_date: date) -> bool:
    """True when end_date's data is fully settled and safe to cache."""
    et = pytz.timezone("America/New_York")
    now_et = datetime.now(et)
    today = now_et.date()
    if end_date < today:
        return True
    if end_date == today:
        # Weekend or after market close (4 PM ET) — data is final
        market_closed = now_et.weekday() >= 5 or now_et.hour >= 16
        return market_closed
    return False


YFINANCE_MAX_DAYS = 60  # yfinance hard limit for 5-minute data


def fetch_yfinance_bars(tickers: list, start_date: date, end_date: date) -> dict:
    # yfinance only supports 5-min data for the last 60 days — historical ranges will fail
    result = {}
    for ticker in tickers:
        df = yf.download(
            ticker,
            start=start_date - timedelta(days=30),  # buffer for MA warmup
            end=end_date,
            interval="5m",
            auto_adjust=True,
            progress=False,
        )
        df.columns = df.columns.droplevel(1)
        df.index = df.index.tz_convert("America/New_York")
        result[ticker] = df
    return result


def fetch_alpaca_bars(
    tickers: list, start_date: date, end_date, allow_intraday: bool = False,
    feed: DataFeed = None,
) -> dict:
    key_id = os.environ.get("ALPACA_API_KEY")
    secret_key = os.environ.get("ALPACA_SECRET_KEY")
    client = StockHistoricalDataClient(key_id, secret_key)

    et = pytz.timezone("America/New_York")
    now_et = datetime.now(tz=et)
    today_et = now_et.date()
    end_date_only = end_date.date() if isinstance(end_date, datetime) else end_date
    if not allow_intraday and end_date_only >= today_et:
        market_open_et = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
        market_close_et = now_et.replace(hour=16, minute=0, second=0, microsecond=0)
        if market_open_et <= now_et < market_close_et:
            raise ValueError(
                f"end_date {end_date} includes today but market hasn't closed yet "
                f"(current ET time: {now_et.strftime('%H:%M')}). "
                f"Re-run after 16:00 ET."
            )

    # MA200 on 5-min bars = 200 bars × 5 min = ~2.6 trading days; 5 calendar days is enough.
    fetch_start = datetime.combine(start_date - timedelta(days=5), datetime.min.time())
    if isinstance(end_date, datetime):
        fetch_end = end_date
    else:
        fetch_end = datetime.combine(end_date + timedelta(days=1), datetime.min.time())

    effective_feed = feed if feed is not None else _ALPACA_FEED
    request = StockBarsRequest(
        symbol_or_symbols=tickers,
        timeframe=TimeFrame(amount=5, unit=TimeFrameUnit.Minute),
        start=fetch_start,
        end=fetch_end,
        feed=effective_feed,
    )
    bars = client.get_stock_bars(request)

    result = {}
    for ticker in tickers:
        if ticker in bars.df.index.get_level_values(0):
            df = bars.df.xs(ticker, level=0).copy()
            df.index = df.index.tz_convert("America/New_York")
            df.columns = [c.capitalize() for c in df.columns]
            # Keep only regular market hours (9:30 AM – 4:00 PM ET)
            df = df.between_time("09:30", "15:55")
            result[ticker] = df
        else:
            result[ticker] = pd.DataFrame()
    return result


def parse_args():
    parser = argparse.ArgumentParser(description="op_momentum_guide backtest")
    parser.add_argument(
        "--days",
        type=int,
        default=14,
        help="Number of calendar days to backtest (default: 14)",
    )
    parser.add_argument(
        "--opening-bars",
        type=int,
        default=3,
        help="Number of 5-min bars in the opening period (default: 3 = 15 min, 4 = 20 min)",
    )
    parser.add_argument(
        "--bearish-ma200",
        action="store_true",
        default=False,
        help="Require price < MA200 for bearish signal (use in bearish market regime, default: off)",
    )
    parser.add_argument(
        "--source",
        choices=["alpaca", "yfinance"],
        default="alpaca",
        help="Market data source (default: alpaca). yfinance is limited to 60 days.",
    )
    parser.add_argument(
        "--tickers",
        nargs="+",
        default=None,
        help="Override TICKERS list, e.g. --tickers NVDA CRWD COIN",
    )
    parser.add_argument(
        "--start",
        type=str,
        default=None,
        help="Start date for backtest window, YYYY-MM-DD (overrides --days)",
    )
    parser.add_argument(
        "--end",
        type=str,
        default=None,
        help="End date for backtest window, YYYY-MM-DD (default: today, requires --start)",
    )
    parser.add_argument(
        "--stop-pct",
        type=float,
        default=0.15,
        help="Hard stop as a fraction of OR range from the favorable end (default: 0.15). "
        "Bull: exit if price drops below OR_high - stop_pct * OR_range. "
        "Bear: exit if price rises above OR_low + stop_pct * OR_range.",
    )
    parser.add_argument(
        "--trailing-ma",
        choices=["ma20", "ma50", "both"],
        default="ma20",
        help="Trailing MA stop to use once MA is above hard stop (default: ma20). "
        "ma20: use MA20 only. ma50: use MA50 only. both: use MA20 then MA50.",
    )
    parser.add_argument(
        "--trailing-ma-switch",
        choices=["none", "after-arm", "after-target"],
        default="none",
        dest="trailing_ma_switch",
        help="Upgrade trailing stop to a faster MA once a profit threshold is reached. "
        "after-arm: upgrade when price moves 1x OR range past entry. "
        "after-target: upgrade at factor x OR range (see --trailing-ma-switch-factor). "
        "Default: none.",
    )
    parser.add_argument(
        "--trailing-ma-switch-period",
        type=int,
        default=8,
        dest="trailing_ma_switch_period",
        help="Period of the fast MA used after the switch threshold is hit (default: 8). "
        "Common choices: 5, 8, 10. Only applies when --trailing-ma-switch is not none.",
    )
    parser.add_argument(
        "--trailing-ma-switch-factor",
        type=float,
        default=1.0,
        dest="trailing_ma_switch_factor",
        help="OR-range multiplier for --trailing-ma-switch after-target (default: 1.0).",
    )
    parser.add_argument(
        "--max-loss-pct",
        type=float,
        default=None,
        help="Per-trade max loss as a fraction of entry price (e.g. 0.02 = 2%%). "
        "Exit immediately if loss exceeds this threshold. Default: disabled.",
    )
    parser.add_argument(
        "--armed-ma20-exit",
        action="store_true",
        default=False,
        help="Once hard stop is armed, use MA20 as the trailing exit instead of hard_stop_price. "
        "Lets winners run further but increases loss size on reversals. Default: off.",
    )
    parser.add_argument(
        "--regime-filter",
        action="store_true",
        default=False,
        help="Skip BULLISH signals on days when QQQ close is below its N-day MA. Default: off.",
    )
    parser.add_argument(
        "--regime-ma",
        type=int,
        default=5,
        help="N-day MA period for QQQ regime filter (default: 5).",
    )
    parser.add_argument(
        "--min-first-bar-range",
        type=float,
        default=None,
        dest="min_first_bar_range_pct",
        help="Rule 1: skip entry if the first 5-min bar of the opening window has a "
        "high-low range smaller than this fraction of the bar midpoint "
        "(e.g. 0.015 = 1.5%%). Default: disabled.",
    )
    parser.add_argument(
        "--min-first-bar-volume",
        type=float,
        default=None,
        dest="min_first_bar_volume_mult",
        help="Rule 4: skip M1 entry if the 09:30 bar volume is below MULT × (20d avg daily vol / 78). "
        "Filters weak-open days with no institutional participation "
        "(e.g. 1.5 requires 1.5× the average per-bar rate). Default: disabled.",
    )
    parser.add_argument(
        "--min-or-vol-ratio",
        type=float,
        default=None,
        dest="min_or_vol_ratio",
        help="Skip entry if OR-window mean volume / 20d historical OR-window mean volume < threshold. "
        "Apples-to-apples vs Rule 4: compares OR bars to historical OR bars, not full-session avg. "
        "Default: disabled.",
    )
    parser.add_argument(
        "--no-exit-at-bar-close",
        dest="exit_at_bar_close",
        action="store_false",
        default=True,
        help="Exit at the intrabar stop/fallback price instead of bar close. "
        "Default: exit at bar close (matches live engine behaviour).",
    )
    return parser.parse_args()


def compute_signals_with_backtest(
    df: pd.DataFrame,
    opening_bars: int,
    bearish_ma200: bool = False,
    stop_pct: float = 0.40,
    opening_start_time: str = "09:30",
    trailing_ma: str = "ma20",
    max_loss_pct: float = None,
    armed_ma20_exit: bool = False,
    bearish_regime_dates: set = None,
    enable_reversal: bool = False,
    reversal_max_bars_held: int = 3,
    enable_bearish_reversal: bool = False,
    bearish_reversal_max_bars_held: int = 3,
    or_bar_lookback: int = 0,
    enable_bearish_reentry: bool = False,
    bearish_reentry_max_bars: int = 3,
    enable_bullish_reentry: bool = False,
    bullish_reentry_max_bars: int = 5,
    close_top_pct: float = None,
    bear_ctp_dates: set = None,
    bear_ctp: float = None,
    filter_flat_or: bool = True,
    qqq_align_skip_bull: set = None,
    qqq_align_skip_bear: set = None,
    trailing_ma_switch: str = "none",
    trailing_ma_switch_factor: float = 1.0,
    trailing_ma_switch_period: int = 8,
    min_first_bar_range_pct: float = None,
    min_first_bar_volume_mult: float = None,
    min_or_vol_ratio: float = None,
    min_hold_bars: int = 0,
    stale_cut_mins: int = 0,
    stale_cut_threshold: float = 0.0,
    exit_at_bar_close: bool = True,
    ma_momentum_gate: bool = False,
    compute_or_vol_ratio: bool = True,
) -> pd.DataFrame:
    opening_start_t = datetime.strptime(opening_start_time, "%H:%M").time()

    # Suppress signals when the OR close (entry time) falls after 15:48 ET —
    # too close to the 15:55 EOD cap to be worth trading.
    _or_close_dt = datetime.combine(datetime.min, opening_start_t) + timedelta(minutes=opening_bars * 5)
    if _or_close_dt.time() > NO_MORE_NEW_POSITION_AFTER:
        return pd.DataFrame()

    df = df.copy()
    fast_ma_col = f"MA{trailing_ma_switch_period}"
    _use_ma_switch = trailing_ma_switch != "none"
    if _use_ma_switch and fast_ma_col not in df.columns:
        df[fast_ma_col] = df["Close"].rolling(trailing_ma_switch_period).mean()
    if "MA20" not in df.columns:
        df["MA20"] = df["Close"].rolling(20).mean()
    if "MA50" not in df.columns:
        df["MA50"] = df["Close"].rolling(50).mean()
    if "MA200" not in df.columns:
        df["MA200"] = df["Close"].rolling(200).mean()

    # Rule 4: pre-compute 20-day rolling average daily volume for the M1 volume gate.
    # Uses prior-day data only (shift 1) — no lookahead. Only computed when needed.
    _avg_daily_vol: dict = {}
    if min_first_bar_volume_mult is not None and opening_start_time == "09:30":
        daily_vol = df.groupby(df.index.date)["Volume"].sum()
        rolling_avg = daily_vol.rolling(20, min_periods=5).mean().shift(1)
        _avg_daily_vol = rolling_avg.to_dict()

    # OR vol ratio: 20-day rolling avg of mean OR-window volume for the same time slot.
    # Apples-to-apples: compares today's OR bars to historical OR bars (not full-session avg).
    # Shift 1 ensures no lookahead bias.
    _hist_or_vol: dict = {}
    if compute_or_vol_ratio:
        _or_slice = df[df.index.time >= opening_start_t]
        or_vol_by_date = (
            _or_slice
            .groupby(_or_slice.index.date)
            .apply(lambda g: g.head(opening_bars)["Volume"].mean())
        )
        _hist_or_vol = or_vol_by_date.rolling(20, min_periods=5).mean().shift(1).to_dict()

    rows = []
    for date_, day_df in df.groupby(df.index.date):
        # Bars from opening_start onward define the opening range and post-open window.
        # All day bars (from 09:30) remain in df for accurate MA calculations.
        day_from_start = day_df[day_df.index.time >= opening_start_t]
        opening = day_from_start.head(opening_bars)
        if len(opening) < opening_bars:
            continue

        or_high = opening["High"].max()
        or_low = opening["Low"].min()
        or_range = or_high - or_low
        if filter_flat_or and or_range == 0:
            continue

        # Rule 1: first-bar range gate — M1 only (09:30 window).
        # Skip if the 09:30–09:35 bar range is too narrow, indicating no directional
        # conviction at open. Afternoon windows are excluded; their first bar is not
        # the market open and the noise signature does not apply.
        if min_first_bar_range_pct is not None and opening_start_time == "09:30":
            first_bar = opening.iloc[0]
            first_bar_mid = (first_bar["High"] + first_bar["Low"]) / 2
            if first_bar_mid > 0:
                first_bar_range_pct = (first_bar["High"] - first_bar["Low"]) / first_bar_mid
                if first_bar_range_pct < min_first_bar_range_pct:
                    continue

        # Rule 4: first-bar volume gate — M1 only (09:30 window).
        # Skip if the 09:30–09:35 bar volume is below mult × (20d avg daily vol / 78 bars).
        # 78 = number of 5-min bars in a full trading session (6.5h × 12 bars/h).
        # Low opening volume means no institutional participation — move is unlikely to sustain.
        if min_first_bar_volume_mult is not None and opening_start_time == "09:30":
            avg_daily_vol = _avg_daily_vol.get(date_)
            if avg_daily_vol is not None and not pd.isna(avg_daily_vol) and avg_daily_vol > 0:
                if opening.iloc[0]["Volume"] < min_first_bar_volume_mult * avg_daily_vol / 78:
                    continue

        # OR vol ratio gate: compare mean OR-window volume to the 20d historical OR-window avg.
        # Acceleration boost: if every successive OR bar grows by > _OR_VOL_ACC_THRESHOLD,
        # or_vol_ratio is multiplied by (1 + _OR_VOL_ACC_BOOST). Constants are module-level.
        or_vol_ratio = None
        hist_or_vol = _hist_or_vol.get(date_)
        if hist_or_vol is not None and not pd.isna(hist_or_vol) and hist_or_vol > 0:
            or_vol_ratio = opening["Volume"].mean() / hist_or_vol
            or_vols = opening["Volume"].tolist()
            if len(or_vols) > 1 and all(
                or_vols[i] > or_vols[i - 1] * (1 + _OR_VOL_ACC_THRESHOLD)
                for i in range(1, len(or_vols))
            ):
                or_vol_ratio *= 1 + _OR_VOL_ACC_BOOST
        if min_or_vol_ratio is not None and (or_vol_ratio is None or or_vol_ratio < min_or_vol_ratio):
            continue

        midpoint = (or_high + or_low) / 2
        bottom_30_threshold = or_low + 0.20 * or_range

        effective_or_range = or_range
        if or_bar_lookback > 0:
            pre_opening = day_df[day_df.index.time < opening_start_t].tail(or_bar_lookback)
            if len(pre_opening) > 0:
                avg_recent_bar_range = (pre_opening["High"] - pre_opening["Low"]).mean()
                if or_range < avg_recent_bar_range / 4:
                    effective_or_range = avg_recent_bar_range

        last_bar = opening.iloc[-1]
        close = last_bar["Close"]
        ma20 = last_bar["MA20"]
        ma200 = last_bar["MA200"]

        if pd.isna(ma20) or pd.isna(ma200):
            continue

        bearish_ma_ok = close < ma20 and (close < ma200 if bearish_ma200 else True)

        _bear_ctp_active = (
            bear_ctp_dates is not None
            and bear_ctp is not None
            and date_ in bear_ctp_dates
        )
        if close_top_pct is not None:
            bull_ok = close >= or_high - close_top_pct * or_range
            _eff_bear_pct = bear_ctp if _bear_ctp_active else close_top_pct
            bear_ok = close <= or_low + _eff_bear_pct * or_range
        elif _bear_ctp_active:
            bull_ok = close > midpoint
            bear_ok = close <= or_low + bear_ctp * or_range
        else:
            bull_ok = close > midpoint
            bear_ok = close <= bottom_30_threshold

        if bull_ok and close > ma20 and close > ma200:
            signal = "BULLISH"
        elif bear_ok and bearish_ma_ok:
            signal = "BEARISH"
        else:
            continue

        if ma_momentum_gate:
            ma50_gate = last_bar["MA50"]
            if pd.isna(ma50_gate):
                continue
            if signal == "BULLISH":
                # OR range must overlap or sit above both MA20 and MA50
                # close > ma20 is already guaranteed; also require close > ma50 or the range reaches it
                if not (or_high >= ma20 and or_high >= ma50_gate):
                    continue
                if not (close > ma20 or close > ma50_gate):
                    continue
            else:  # BEARISH
                # OR range must overlap or sit below both MA20 and MA50
                if not (or_low <= ma20 and or_low <= ma50_gate):
                    continue
                if not (close < ma20):
                    continue

        if (
            bearish_regime_dates
            and date_ in bearish_regime_dates
            and signal == "BULLISH"
        ):
            continue

        if qqq_align_skip_bull and date_ in qqq_align_skip_bull and signal == "BULLISH":
            continue
        if qqq_align_skip_bear and date_ in qqq_align_skip_bear and signal == "BEARISH":
            continue

        # Hard stop: bull exits if price drops back below the stop level after first crossing above it.
        # Bear exits if price rises back above the stop level after first crossing below it.
        # If price never crosses the stop level (no breakout confirmation), fall back to 20% from favorable end of OR range.
        # Bull fallback: OR_high - 20% × OR_range (80th percentile). Bear fallback: OR_low + 20% × OR_range (20th percentile).
        bull_hard_stop = or_high - stop_pct * effective_or_range
        bear_hard_stop = or_low + stop_pct * effective_or_range
        hard_stop_price = bull_hard_stop if signal == "BULLISH" else bear_hard_stop
        bull_fallback = or_high - 0.20 * effective_or_range
        bear_fallback = or_low + 0.20 * effective_or_range
        fallback_price = bull_fallback if signal == "BULLISH" else bear_fallback

        if close_top_pct is not None:
            # Stop is the opposite end of the bar; pre-arm so fallback path is bypassed.
            hard_stop_price = or_low if signal == "BULLISH" else or_high
            fallback_price = hard_stop_price

        # All bars from entry through EOD — cap at 15:55 (5 min before close).
        # Trades exit naturally (hard stop, trailing MA, or EOD at 15:55).
        post_open = day_from_start.iloc[opening_bars:]
        post_open = post_open[post_open.index.time < _time(15, 55)]
        bars_held = 0
        max_favorable_move = 0.0
        hard_stop_armed = close_top_pct is not None
        exit_price = fallback_price
        exit_reason = "fallback_20pct" if close_top_pct is None else "hard_stop"
        exit_bar_idx = -1  # index into post_open where the primary trade exited

        _switch_threshold = None
        if trailing_ma_switch == "after-arm":
            _switch_threshold = effective_or_range
        elif trailing_ma_switch == "after-target":
            _switch_threshold = trailing_ma_switch_factor * effective_or_range
        use_ma_fast = False

        for bar_idx, (_, bar) in enumerate(post_open.iterrows()):
            exit_bar_idx = bar_idx  # always tracks the last bar reached
            bar_ma_fast = bar[fast_ma_col] if _use_ma_switch else float("nan")
            bar_ma20 = bar["MA20"]
            bar_ma50 = bar["MA50"]
            bar_close = bar["Close"]

            if signal == "BULLISH":
                if not hard_stop_armed and bar_close > hard_stop_price:
                    hard_stop_armed = True
                move = bar_close - midpoint
            else:
                if not hard_stop_armed and bar_close < hard_stop_price:
                    hard_stop_armed = True
                move = midpoint - bar_close

            if not use_ma_fast and _switch_threshold is not None:
                if max(max_favorable_move, move) >= _switch_threshold:
                    use_ma_fast = True
            _eff_trail = bar_ma_fast if (use_ma_fast and not pd.isna(bar_ma_fast)) else bar_ma20
            _eff_trail_reason = f"trailing_stop_{fast_ma_col.lower()}" if (use_ma_fast and not pd.isna(bar_ma_fast)) else "trailing_stop_ma20"
            _trail_active = (
                (use_ma_fast and not pd.isna(bar_ma_fast))
                or (trailing_ma in ("ma20", "both") and not pd.isna(bar_ma20))
            )

            # Max loss guard — highest priority exit
            if max_loss_pct is not None:
                loss_pct = (
                    (close - bar_close) / close
                    if signal == "BULLISH"
                    else (bar_close - close) / close
                )
                if loss_pct >= max_loss_pct:
                    exit_price = bar_close
                    exit_reason = "max_loss"
                    break

            # Min-hold window: suppress fallback and hard-stop exits so the trade can develop.
            if bar_idx < min_hold_bars:
                bars_held += 1
                max_favorable_move = max(max_favorable_move, move)
                if signal == "BULLISH":
                    exit_price = max(bar_close, midpoint)
                else:
                    exit_price = min(bar_close, midpoint)
                exit_reason = "end_of_day"
                continue

            if signal == "BULLISH":
                fallback_hit = not hard_stop_armed and bar_close <= fallback_price
                if hard_stop_armed and armed_ma20_exit:
                    # Armed MA20 mode: MA20 (or fast MA if upgraded) replaces hard_stop as the trailing exit
                    if _trail_active:
                        ma20_trailing_stop_hit = bar_close < _eff_trail
                        ma20_exit_price, ma20_exit_reason = bar_close, _eff_trail_reason
                    else:
                        ma20_trailing_stop_hit = bar_close <= hard_stop_price
                        _bull_stop_fill = bar_close if exit_at_bar_close else (
                            hard_stop_price if bar["High"] >= hard_stop_price else bar["Open"]
                        )
                        ma20_exit_price, ma20_exit_reason = _bull_stop_fill, "hard_stop"
                else:
                    hard_stop_hit = hard_stop_armed and bar_close <= hard_stop_price
                    ma20_trailing_stop_hit = (
                        not hard_stop_hit
                        and _trail_active
                        and _eff_trail > hard_stop_price
                        and bar_close < _eff_trail
                    )
                    _bull_stop_fill = bar_close if exit_at_bar_close else (
                        hard_stop_price if bar["High"] >= hard_stop_price else bar["Open"]
                    )
                    ma20_exit_price, ma20_exit_reason = (
                        (_bull_stop_fill, "hard_stop")
                        if hard_stop_hit
                        else (bar_close, _eff_trail_reason)
                    )
                    ma20_trailing_stop_hit = ma20_trailing_stop_hit or hard_stop_hit
                trailing_stop_hit = (
                    trailing_ma in ("ma50", "both")
                    and not pd.isna(bar_ma50)
                    and bar_ma50 > hard_stop_price
                    and bar_close < bar_ma50
                )
            else:
                fallback_hit = not hard_stop_armed and bar_close >= fallback_price
                if hard_stop_armed and armed_ma20_exit:
                    if _trail_active:
                        ma20_trailing_stop_hit = bar_close > _eff_trail
                        ma20_exit_price, ma20_exit_reason = bar_close, _eff_trail_reason
                    else:
                        ma20_trailing_stop_hit = bar_close >= hard_stop_price
                        _bear_stop_fill = bar_close if exit_at_bar_close else (
                            hard_stop_price if bar["Low"] <= hard_stop_price else bar["Open"]
                        )
                        ma20_exit_price, ma20_exit_reason = _bear_stop_fill, "hard_stop"
                else:
                    hard_stop_hit = hard_stop_armed and bar_close >= hard_stop_price
                    ma20_trailing_stop_hit = (
                        not hard_stop_hit
                        and _trail_active
                        and _eff_trail < or_low
                        and bar_close > _eff_trail
                    )
                    _bear_stop_fill = bar_close if exit_at_bar_close else (
                        hard_stop_price if bar["Low"] <= hard_stop_price else bar["Open"]
                    )
                    ma20_exit_price, ma20_exit_reason = (
                        (_bear_stop_fill, "hard_stop")
                        if hard_stop_hit
                        else (bar_close, _eff_trail_reason)
                    )
                    ma20_trailing_stop_hit = ma20_trailing_stop_hit or hard_stop_hit
                trailing_stop_hit = (
                    trailing_ma in ("ma50", "both")
                    and not pd.isna(bar_ma50)
                    and bar_ma50 < or_low
                    and bar_close > bar_ma50
                )

            if fallback_hit:
                if exit_at_bar_close:
                    exit_price = bar_close
                elif signal == "BULLISH":
                    exit_price = fallback_price if bar["High"] >= fallback_price else bar_close
                else:
                    exit_price = fallback_price if bar["Low"] <= fallback_price else bar["Open"]
                exit_reason = "fallback_20pct"
                break
            elif ma20_trailing_stop_hit:
                exit_price = ma20_exit_price
                exit_reason = ma20_exit_reason
                break
            elif trailing_stop_hit:
                exit_price = bar_close
                exit_reason = "trailing_stop_ma50"
                break
            else:
                bars_held += 1
                max_favorable_move = max(max_favorable_move, move)
                if signal == "BULLISH":
                    exit_price = max(bar_close, midpoint)
                else:
                    exit_price = min(bar_close, midpoint)
                exit_reason = "end_of_day"

                # Stale-cut: exit if trade is flat after stale_cut_mins minutes.
                if stale_cut_mins > 0 and stale_cut_threshold > 0.0 and bars_held * 5 == stale_cut_mins:
                    current_pnl_pct = abs((bar_close - close) / close * 100)
                    if current_pnl_pct < stale_cut_threshold:
                        exit_price = bar_close
                        exit_reason = "stale_cut"
                        break

        if signal == "BULLISH":
            pnl = exit_price - close
        else:
            pnl = close - exit_price

        rows.append(
            {
                "date": date_,
                "signal": signal,
                "or_high": round(or_high, 2),
                "or_low": round(or_low, 2),
                "midpoint": round(midpoint, 2),
                "entry_price": round(close, 2),
                "exit_price": round(exit_price, 2),
                "pnl": round(pnl, 2),
                "exit_reason": exit_reason,
                "ma20": round(ma20, 2),
                "ma50": round(float(last_bar["MA50"]), 2),
                "ma200": round(ma200, 2),
                "bars_held": bars_held,
                "mins_held": bars_held * 5,
                "max_favorable_move": round(max_favorable_move, 2),
                "held_to_close": exit_reason == "end_of_day",
                "total_post_bars": len(post_open),
                "success": pnl > 0,
                "is_reversal": False,
                "is_bearish_reentry": False,
                "is_bullish_reentry": False,
                "or_vol_ratio": round(or_vol_ratio, 4) if or_vol_ratio is not None else None,
            }
        )
        primary_row = rows[-1]

        # Reversal / Bearish re-entry — first chronological trigger wins.
        #
        # Both entry scans run before either simulation so we can compare bar
        # indices.  Reversal wins same-bar ties (BRE scan stops before the bar
        # where reversal fires).  Whichever loses has its entry price set to None
        # and its simulation block is skipped.
        #
        # Reversal: BEARISH primary stopped out within N bars AND price later
        # crosses above OR high — flip to BULLISH.
        # BRE: BEARISH primary stopped out within N bars AND price later closes
        # below OR low — re-enter short.

        rev_entry_price = None
        rev_entry_idx = None
        reversal_hard_stop = None
        reversal_scan = None

        reversal_eligible = enable_reversal and (
            signal == "BEARISH"
            and bars_held <= reversal_max_bars_held
            and exit_reason in ("hard_stop", "fallback_20pct")
            and exit_bar_idx >= 0
        )
        if reversal_eligible:
            reversal_hard_stop = midpoint
            reversal_scan = post_open.iloc[exit_bar_idx + 1:]

            for scan_idx, (scan_ts, scan_bar) in enumerate(reversal_scan.iterrows()):
                if scan_ts.time() > NO_MORE_NEW_POSITION_AFTER:
                    break
                if scan_bar["Close"] > or_high:
                    rev_entry_price = scan_bar["Close"]
                    rev_entry_idx = scan_idx
                    break

        # BRE entry scan — runs before reversal simulation.
        # Stops at the bar where reversal fires (if it fires) so that reversal
        # wins same-bar ties and BRE never "beats" reversal on an equal bar.
        bearish_reentry_eligible = (
            enable_bearish_reentry
            and signal == "BEARISH"
            and bars_held <= bearish_reentry_max_bars
            and exit_reason in ("hard_stop", "fallback_20pct")
            and exit_bar_idx >= 0
        )
        br_entry_price = None
        br_entry_idx = None
        if bearish_reentry_eligible:
            br_hard_stop = midpoint
            br_scan = post_open.iloc[exit_bar_idx + 1:]

            for scan_idx, (scan_ts, scan_bar) in enumerate(br_scan.iterrows()):
                if scan_ts.time() > NO_MORE_NEW_POSITION_AFTER:
                    break
                if rev_entry_idx is not None and scan_idx >= rev_entry_idx:
                    break  # reversal fires here or earlier — stop before this bar
                bar_ma20 = scan_bar.get("MA20") if hasattr(scan_bar, "get") else scan_bar["MA20"]
                if (
                    scan_bar["Close"] < or_low
                    and not pd.isna(bar_ma20)
                    and scan_bar["Close"] < bar_ma20
                ):
                    br_entry_price = scan_bar["Close"]
                    br_entry_idx = scan_idx
                    break

            # BRE fired on an earlier bar than reversal — cancel reversal.
            if br_entry_price is not None:
                rev_entry_price = None
                rev_entry_idx = None

        # Reversal simulation (only if reversal won).
        if rev_entry_price is not None:
            rev_bars_held = 0
            rev_max_favorable_move = 0.0
            rev_exit_price = rev_entry_price
            rev_exit_reason = "end_of_day"
            # Entry is already above OR high > reversal_hard_stop, so armed at start.
            remaining_rev_bars = reversal_scan.iloc[rev_entry_idx + 1:]

            rev_trailing_armed = False
            rev_use_ma_fast = False
            for _, rev_bar in remaining_rev_bars.iterrows():
                rev_bar_ma_fast = rev_bar[fast_ma_col] if _use_ma_switch else float("nan")
                rev_bar_ma20 = rev_bar["MA20"]
                rev_bar_ma50 = rev_bar["MA50"]
                rev_bar_close = rev_bar["Close"]
                rev_move = rev_bar_close - rev_entry_price

                if rev_bar_close >= rev_entry_price + or_range:
                    rev_trailing_armed = True

                if not rev_use_ma_fast and trailing_ma_switch != "none":
                    if trailing_ma_switch == "after-arm" and rev_trailing_armed:
                        rev_use_ma_fast = True
                    elif trailing_ma_switch == "after-target" and rev_move >= trailing_ma_switch_factor * or_range:
                        rev_use_ma_fast = True
                _rev_eff_trail = rev_bar_ma_fast if (rev_use_ma_fast and not pd.isna(rev_bar_ma_fast)) else rev_bar_ma20
                _rev_eff_reason = f"trailing_stop_{fast_ma_col.lower()}" if (rev_use_ma_fast and not pd.isna(rev_bar_ma_fast)) else "trailing_stop_ma20"
                _rev_trail_active = (
                    (rev_use_ma_fast and not pd.isna(rev_bar_ma_fast))
                    or (trailing_ma in ("ma20", "both") and not pd.isna(rev_bar_ma20))
                )

                rev_hard_stop_hit = rev_bar_close <= reversal_hard_stop
                rev_ma20_trailing = (
                    rev_trailing_armed
                    and not rev_hard_stop_hit
                    and _rev_trail_active
                    and _rev_eff_trail > reversal_hard_stop
                    and rev_bar_close < _rev_eff_trail
                )
                rev_ma50_trailing = (
                    rev_trailing_armed
                    and trailing_ma in ("ma50", "both")
                    and not pd.isna(rev_bar_ma50)
                    and rev_bar_ma50 > reversal_hard_stop
                    and rev_bar_close < rev_bar_ma50
                )
                rev_ma20_exit_price = (
                    reversal_hard_stop if rev_hard_stop_hit else rev_bar_close
                )
                rev_ma20_exit_reason = (
                    "hard_stop" if rev_hard_stop_hit else _rev_eff_reason
                )
                rev_stop_hit = rev_hard_stop_hit or rev_ma20_trailing

                if rev_stop_hit:
                    rev_exit_price = rev_ma20_exit_price
                    rev_exit_reason = rev_ma20_exit_reason
                    break
                elif rev_ma50_trailing:
                    rev_exit_price = rev_bar_close
                    rev_exit_reason = "trailing_stop_ma50"
                    break
                else:
                    rev_bars_held += 1
                    rev_max_favorable_move = max(rev_max_favorable_move, rev_move)
                    rev_exit_price = rev_bar_close
                    rev_exit_reason = "end_of_day"

            rev_pnl = rev_exit_price - rev_entry_price
            primary_row["rev_entry_price"] = rev_entry_price
            primary_row["rev_entry_idx"] = rev_entry_idx
            primary_row["rev_bars_held"] = rev_bars_held
            rows.append(
                {
                    "date": date_,
                    "signal": "BULLISH",
                    "or_high": round(or_high, 2),
                    "or_low": round(or_low, 2),
                    "midpoint": round(midpoint, 2),
                    "entry_price": round(rev_entry_price, 2),
                    "exit_price": round(rev_exit_price, 2),
                    "pnl": round(rev_pnl, 2),
                    "exit_reason": rev_exit_reason,
                    "ma20": round(ma20, 2),
                    "ma200": round(ma200, 2),
                    "bars_held": rev_bars_held,
                    "mins_held": rev_bars_held * 5,
                    "entry_idx": rev_entry_idx,
                    "max_favorable_move": round(rev_max_favorable_move, 2),
                    "held_to_close": rev_exit_reason == "end_of_day",
                    "total_post_bars": len(post_open),
                    "success": rev_pnl > 0,
                    "is_reversal": True,
                    "is_bearish_reentry": False,
                    "is_bullish_reentry": False,
                    "or_vol_ratio": round(or_vol_ratio, 4) if or_vol_ratio is not None else None,
                }
            )

        # BRE simulation (only if BRE won).
        # br_scan is the full post-exit bar range; br_entry_idx is within it.
        if br_entry_price is not None:
            br_bars_held = 0
            br_max_favorable_move = 0.0
            br_exit_price = br_entry_price
            br_exit_reason = "end_of_day"
            br_trailing_armed = False
            br_use_ma_fast = False
            remaining_br_bars = br_scan.iloc[br_entry_idx + 1:]

            for _, br_bar in remaining_br_bars.iterrows():
                br_bar_ma_fast = br_bar[fast_ma_col] if _use_ma_switch else float("nan")
                br_bar_ma20 = br_bar["MA20"]
                br_bar_close = br_bar["Close"]
                br_move = br_entry_price - br_bar_close

                if not br_trailing_armed and not pd.isna(br_bar_ma20) and br_bar_ma20 < midpoint:
                    br_trailing_armed = True

                if not br_use_ma_fast and trailing_ma_switch != "none":
                    if trailing_ma_switch == "after-arm" and br_trailing_armed:
                        br_use_ma_fast = True
                    elif trailing_ma_switch == "after-target" and br_move >= trailing_ma_switch_factor * effective_or_range:
                        br_use_ma_fast = True
                _br_eff_trail = br_bar_ma_fast if (br_use_ma_fast and not pd.isna(br_bar_ma_fast)) else br_bar_ma20
                _br_eff_reason = f"trailing_stop_{fast_ma_col.lower()}" if (br_use_ma_fast and not pd.isna(br_bar_ma_fast)) else "trailing_stop_ma20"
                _br_trail_active = (
                    (br_use_ma_fast and not pd.isna(br_bar_ma_fast))
                    or (trailing_ma in ("ma20", "both") and not pd.isna(br_bar_ma20))
                )

                br_hard_stop_hit = br_bar_close >= br_hard_stop
                br_ma20_trailing = (
                    br_trailing_armed
                    and not br_hard_stop_hit
                    and _br_trail_active
                    and _br_eff_trail < midpoint
                    and br_bar_close > _br_eff_trail
                )
                br_exit_price_candidate = br_hard_stop if br_hard_stop_hit else br_bar_close
                br_exit_reason_candidate = "hard_stop" if br_hard_stop_hit else _br_eff_reason
                br_stop_hit = br_hard_stop_hit or br_ma20_trailing

                if br_stop_hit:
                    br_exit_price = br_exit_price_candidate
                    br_exit_reason = br_exit_reason_candidate
                    break
                else:
                    br_bars_held += 1
                    br_max_favorable_move = max(br_max_favorable_move, br_move)
                    br_exit_price = br_bar_close
                    br_exit_reason = "end_of_day"

            br_pnl = br_entry_price - br_exit_price
            primary_row["br_entry_price"] = br_entry_price
            primary_row["br_entry_idx"] = br_entry_idx
            primary_row["br_bars_held"] = br_bars_held
            rows.append(
                {
                    "date": date_,
                    "signal": "BEARISH",
                    "or_high": round(or_high, 2),
                    "or_low": round(or_low, 2),
                    "midpoint": round(midpoint, 2),
                    "entry_price": round(br_entry_price, 2),
                    "exit_price": round(br_exit_price, 2),
                    "pnl": round(br_pnl, 2),
                    "exit_reason": br_exit_reason,
                    "ma20": round(ma20, 2),
                    "ma200": round(ma200, 2),
                    "bars_held": br_bars_held,
                    "mins_held": br_bars_held * 5,
                    "entry_idx": br_entry_idx,
                    "max_favorable_move": round(br_max_favorable_move, 2),
                    "held_to_close": br_exit_reason == "end_of_day",
                    "total_post_bars": len(post_open),
                    "success": br_pnl > 0,
                    "is_reversal": False,
                    "is_bearish_reentry": True,
                    "is_bullish_reentry": False,
                    "or_vol_ratio": round(or_vol_ratio, 4) if or_vol_ratio is not None else None,
                }
            )

        # Bearish reversal: BULLISH primary stopped out within N bars AND price later
        # crosses below OR low — flip to BEARISH.
        # Competes with BRU; bearish reversal wins same-bar ties (BRU scan stops
        # before the bar where bearish reversal fires).
        brev_entry_price = None
        brev_entry_idx = None
        brev_hard_stop = None
        brev_scan = None

        brev_eligible = enable_bearish_reversal and (
            signal == "BULLISH"
            and bars_held <= bearish_reversal_max_bars_held
            and exit_reason in ("hard_stop", "fallback_20pct")
            and exit_bar_idx >= 0
        )
        if brev_eligible:
            brev_hard_stop = midpoint
            brev_scan = post_open.iloc[exit_bar_idx + 1:]

            for scan_idx, (scan_ts, scan_bar) in enumerate(brev_scan.iterrows()):
                if scan_ts.time() > NO_MORE_NEW_POSITION_AFTER:
                    break
                if scan_bar["Close"] < or_low:
                    brev_entry_price = scan_bar["Close"]
                    brev_entry_idx = scan_idx
                    break

        # Bullish re-entry: BULLISH primary stopped out within N bars AND price later
        # closes above OR_high — re-enter BULLISH.
        # Hard stop: midpoint (falling back to midpoint = bullish thesis dead).
        # Trailing arm: price rises effective_or_range above entry;
        # exit when MA20 > midpoint AND close < MA20.
        bullish_reentry_eligible = (
            enable_bullish_reentry
            and signal == "BULLISH"
            and bars_held <= bullish_reentry_max_bars
            and exit_reason in ("hard_stop", "fallback_20pct")
            and exit_bar_idx >= 0
        )
        if bullish_reentry_eligible:
            bru_hard_stop = midpoint
            bru_scan = post_open.iloc[exit_bar_idx + 1:]
            bru_entry_price = None
            bru_entry_idx = None

            for scan_idx, (scan_ts, scan_bar) in enumerate(bru_scan.iterrows()):
                if scan_ts.time() > NO_MORE_NEW_POSITION_AFTER:
                    break
                if brev_entry_idx is not None and scan_idx >= brev_entry_idx:
                    break  # bearish reversal fires here or earlier — stop before this bar
                bar_ma50 = scan_bar.get("MA50") if hasattr(scan_bar, "get") else scan_bar["MA50"]
                if (
                    scan_bar["Close"] > or_high
                    and not pd.isna(bar_ma50)
                    and scan_bar["Close"] > bar_ma50
                ):
                    bru_entry_price = scan_bar["Close"]
                    bru_entry_idx = scan_idx
                    break

            # BRU fired on an earlier bar than bearish reversal — cancel bearish reversal.
            if bru_entry_price is not None:
                brev_entry_price = None
                brev_entry_idx = None

            if bru_entry_price is not None:
                bru_bars_held = 0
                bru_max_favorable_move = 0.0
                bru_exit_price = bru_entry_price
                bru_exit_reason = "end_of_day"
                bru_trailing_armed = False
                bru_use_ma_fast = False
                remaining_bru_bars = bru_scan.iloc[bru_entry_idx + 1:]

                for _, bru_bar in remaining_bru_bars.iterrows():
                    bru_bar_ma_fast = bru_bar[fast_ma_col] if _use_ma_switch else float("nan")
                    bru_bar_ma20 = bru_bar["MA20"]
                    bru_bar_close = bru_bar["Close"]
                    bru_move = bru_bar_close - bru_entry_price

                    if not bru_trailing_armed and bru_bar_close >= bru_entry_price + effective_or_range * 0.1:
                        _bru_arm_ma = bru_bar_ma_fast if (bru_use_ma_fast and not pd.isna(bru_bar_ma_fast)) else bru_bar_ma20
                        bru_trailing_armed = (
                            not pd.isna(_bru_arm_ma) and bru_bar_close > _bru_arm_ma
                        )

                    if not bru_use_ma_fast and trailing_ma_switch != "none":
                        if trailing_ma_switch == "after-arm" and bru_trailing_armed:
                            bru_use_ma_fast = True
                        elif trailing_ma_switch == "after-target" and bru_move >= trailing_ma_switch_factor * effective_or_range:
                            bru_use_ma_fast = True
                    _bru_eff_trail = bru_bar_ma_fast if (bru_use_ma_fast and not pd.isna(bru_bar_ma_fast)) else bru_bar_ma20
                    _bru_eff_reason = f"trailing_stop_{fast_ma_col.lower()}" if (bru_use_ma_fast and not pd.isna(bru_bar_ma_fast)) else "trailing_stop_ma20"
                    _bru_trail_active = (
                        (bru_use_ma_fast and not pd.isna(bru_bar_ma_fast))
                        or (trailing_ma in ("ma20", "both") and not pd.isna(bru_bar_ma20))
                    )

                    bru_hard_stop_hit = bru_bar_close <= bru_hard_stop
                    bru_ma20_trailing = (
                        bru_trailing_armed
                        and not bru_hard_stop_hit
                        and _bru_trail_active
                        and _bru_eff_trail > bru_hard_stop
                        and bru_bar_close < _bru_eff_trail
                    )
                    bru_exit_price_candidate = bru_hard_stop if bru_hard_stop_hit else bru_bar_close
                    bru_exit_reason_candidate = "hard_stop" if bru_hard_stop_hit else _bru_eff_reason
                    bru_stop_hit = bru_hard_stop_hit or bru_ma20_trailing

                    if bru_stop_hit:
                        bru_exit_price = bru_exit_price_candidate
                        bru_exit_reason = bru_exit_reason_candidate
                        break
                    else:
                        bru_bars_held += 1
                        bru_max_favorable_move = max(bru_max_favorable_move, bru_move)
                        bru_exit_price = bru_bar_close
                        bru_exit_reason = "end_of_day"

                bru_pnl = bru_exit_price - bru_entry_price
                primary_row["bru_entry_price"] = bru_entry_price
                primary_row["bru_entry_idx"] = bru_entry_idx
                primary_row["bru_bars_held"] = bru_bars_held
                rows.append(
                    {
                        "date": date_,
                        "signal": "BULLISH",
                        "or_high": round(or_high, 2),
                        "or_low": round(or_low, 2),
                        "midpoint": round(midpoint, 2),
                        "entry_price": round(bru_entry_price, 2),
                        "exit_price": round(bru_exit_price, 2),
                        "pnl": round(bru_pnl, 2),
                        "exit_reason": bru_exit_reason,
                        "ma20": round(ma20, 2),
                        "ma200": round(ma200, 2),
                        "bars_held": bru_bars_held,
                        "mins_held": bru_bars_held * 5,
                        "entry_idx": bru_entry_idx,
                        "max_favorable_move": round(bru_max_favorable_move, 2),
                        "held_to_close": bru_exit_reason == "end_of_day",
                        "total_post_bars": len(post_open),
                        "success": bru_pnl > 0,
                        "is_reversal": False,
                        "is_bearish_reentry": False,
                        "is_bullish_reentry": True,
                        "or_vol_ratio": round(or_vol_ratio, 4) if or_vol_ratio is not None else None,
                    }
                )

        # Bearish reversal simulation (only if bearish reversal won over BRU).
        if brev_entry_price is not None:
            brev_bars_held = 0
            brev_max_favorable_move = 0.0
            brev_exit_price = brev_entry_price
            brev_exit_reason = "end_of_day"
            brev_trailing_armed = False
            brev_use_ma_fast = False
            remaining_brev_bars = brev_scan.iloc[brev_entry_idx + 1:]

            for _, brev_bar in remaining_brev_bars.iterrows():
                brev_bar_ma_fast = brev_bar[fast_ma_col] if _use_ma_switch else float("nan")
                brev_bar_ma20 = brev_bar["MA20"]
                brev_bar_close = brev_bar["Close"]
                brev_move = brev_entry_price - brev_bar_close

                if not brev_trailing_armed and not pd.isna(brev_bar_ma20) and brev_bar_ma20 < midpoint:
                    brev_trailing_armed = True

                if not brev_use_ma_fast and trailing_ma_switch != "none":
                    if trailing_ma_switch == "after-arm" and brev_trailing_armed:
                        brev_use_ma_fast = True
                    elif trailing_ma_switch == "after-target" and brev_move >= trailing_ma_switch_factor * effective_or_range:
                        brev_use_ma_fast = True
                _brev_eff_trail = brev_bar_ma_fast if (brev_use_ma_fast and not pd.isna(brev_bar_ma_fast)) else brev_bar_ma20
                _brev_eff_reason = f"trailing_stop_{fast_ma_col.lower()}" if (brev_use_ma_fast and not pd.isna(brev_bar_ma_fast)) else "trailing_stop_ma20"
                _brev_trail_active = (
                    (brev_use_ma_fast and not pd.isna(brev_bar_ma_fast))
                    or (trailing_ma in ("ma20", "both") and not pd.isna(brev_bar_ma20))
                )

                brev_hard_stop_hit = brev_bar_close >= brev_hard_stop
                brev_ma20_trailing = (
                    brev_trailing_armed
                    and not brev_hard_stop_hit
                    and _brev_trail_active
                    and _brev_eff_trail < midpoint
                    and brev_bar_close > _brev_eff_trail
                )
                brev_exit_price_candidate = brev_hard_stop if brev_hard_stop_hit else brev_bar_close
                brev_exit_reason_candidate = "hard_stop" if brev_hard_stop_hit else _brev_eff_reason
                brev_stop_hit = brev_hard_stop_hit or brev_ma20_trailing

                if brev_stop_hit:
                    brev_exit_price = brev_exit_price_candidate
                    brev_exit_reason = brev_exit_reason_candidate
                    break
                else:
                    brev_bars_held += 1
                    brev_max_favorable_move = max(brev_max_favorable_move, brev_move)
                    brev_exit_price = brev_bar_close
                    brev_exit_reason = "end_of_day"

            brev_pnl = brev_entry_price - brev_exit_price
            primary_row["brev_entry_price"] = brev_entry_price
            primary_row["brev_entry_idx"] = brev_entry_idx
            primary_row["brev_bars_held"] = brev_bars_held
            rows.append(
                {
                    "date": date_,
                    "signal": "BEARISH",
                    "or_high": round(or_high, 2),
                    "or_low": round(or_low, 2),
                    "midpoint": round(midpoint, 2),
                    "entry_price": round(brev_entry_price, 2),
                    "exit_price": round(brev_exit_price, 2),
                    "pnl": round(brev_pnl, 2),
                    "exit_reason": brev_exit_reason,
                    "ma20": round(ma20, 2),
                    "ma200": round(ma200, 2),
                    "bars_held": brev_bars_held,
                    "mins_held": brev_bars_held * 5,
                    "entry_idx": brev_entry_idx,
                    "max_favorable_move": round(brev_max_favorable_move, 2),
                    "held_to_close": brev_exit_reason == "end_of_day",
                    "total_post_bars": len(post_open),
                    "success": brev_pnl > 0,
                    "is_reversal": True,
                    "is_bearish_reentry": False,
                    "is_bullish_reentry": False,
                    "or_vol_ratio": round(or_vol_ratio, 4) if or_vol_ratio is not None else None,
                }
            )

    return pd.DataFrame(rows)


def print_successful_days(ticker: str, results: pd.DataFrame, backtest_days: int):
    wins = results[results["success"]].reset_index(drop=True)

    print(f"\n{'=' * 96}")
    print(
        f"  {ticker}  |  Successful signal days  |  Last {backtest_days} calendar days"
    )
    print(f"{'=' * 96}")
    print(
        f"  {'Date':<12} {'Signal':<9} {'Mid':>7} {'Entry':>7} {'Exit':>7} "
        f"{'P&L':>8} {'MinsHeld':>9} {'MaxMove':>9}  Exit Reason"
    )
    print(f"  {'-' * 94}")

    if wins.empty:
        print("  No successful signals in this period.")
        return

    for _, r in wins.iterrows():
        pnl_str = (
            f"+${abs(r['pnl']):.2f}" if r["pnl"] >= 0 else f"-${abs(r['pnl']):.2f}"
        )
        signal_display = r["signal"] + (" [R]" if r.get("is_reversal") else "")
        print(
            f"  {str(r['date']):<12} {signal_display:<13} "
            f"{r['midpoint']:>7.2f} {r['entry_price']:>7.2f} {r['exit_price']:>7.2f} "
            f"{pnl_str:>8} {r['mins_held']:>9} "
            f"${r['max_favorable_move']:>8.2f}  {r['exit_reason']}"
        )


def print_stats(ticker: str, results: pd.DataFrame):
    if results.empty:
        print(f"\n  {ticker} — No signals fired in this period.")
        return

    total = len(results)
    successes = int(results["success"].sum())
    failures = total - successes
    rate = successes / total * 100

    bull = results[results["signal"] == "BULLISH"]
    bear = results[results["signal"] == "BEARISH"]

    avg_mins_success = (
        results[results["success"]]["bars_held"].mean() * 5 if successes else 0
    )
    avg_move = (
        results[results["success"]]["max_favorable_move"].mean() if successes else 0
    )
    held_all_day = int(results["held_to_close"].sum())
    total_pnl = results["pnl"].sum()
    win_pnl = results[results["success"]]["pnl"].sum()
    loss_pnl = results[~results["success"]]["pnl"].sum()

    print(f"\n  {ticker} — Stats")
    print(f"  {'─' * 52}")
    print(f"  Signals fired      : {total}  (bull={len(bull)}, bear={len(bear)})")
    print(
        f"  Success / Fail     : {successes} / {failures}  →  {rate:.0f}% success rate"
    )
    print(f"  Held all day       : {held_all_day} / {total}")
    print(f"  Avg mins held (W)  : {avg_mins_success:.0f} min")
    print(f"  Avg max move (W)   : ${avg_move:.2f} from midpoint")
    print(f"  Win P&L            : +${win_pnl:.2f}")
    print(f"  Loss P&L           : -${abs(loss_pnl):.2f}")
    print(f"  Net P&L            : {'+' if total_pnl >= 0 else ''}${total_pnl:.2f}")
    if not bull.empty:
        print(
            f"  Bullish success    : {int(bull['success'].sum())}/{len(bull)} = {bull['success'].mean() * 100:.0f}%"
        )
    if not bear.empty:
        print(
            f"  Bearish success    : {int(bear['success'].sum())}/{len(bear)} = {bear['success'].mean() * 100:.0f}%"
        )


def print_daily_pnl(all_results: dict, backtest_days: int):
    # Combine all tickers, pivot by date
    frames = []
    for ticker, df in all_results.items():
        if df.empty:
            continue
        tmp = df[
            ["date", "signal", "entry_price", "exit_price", "pnl", "success"]
        ].copy()
        tmp["ticker"] = ticker
        frames.append(tmp)

    if not frames:
        return

    combined = pd.concat(frames, ignore_index=True)
    all_dates = sorted(combined["date"].unique())

    print(f"\n{'=' * 82}")
    print(
        f"  DAILY P&L REPORT  |  Last {backtest_days} calendar days  |  1 share per signal"
    )
    print(f"{'=' * 82}")

    grand_total = 0.0
    for d in all_dates:
        day = combined[combined["date"] == d]
        wins = day[day["success"]]
        losses = day[~day["success"]]
        win_count = len(wins)
        loss_count = len(losses)
        day_pnl = day["pnl"].sum()
        grand_total += day_pnl

        pnl_str = f"+${day_pnl:.2f}" if day_pnl >= 0 else f"-${abs(day_pnl):.2f}"
        print(
            f"\n  {d}  |  signals={len(day)}  wins={win_count}  losses={loss_count}  "
            f"day P&L: {pnl_str}"
        )
        print(f"  {'─' * 78}")
        print(
            f"  {'Ticker':<7} {'Signal':<9} {'Entry':>8} {'Exit':>8} {'P&L':>9}  Result"
        )
        print(f"  {'─' * 78}")

        for _, r in day.iterrows():
            result = "WIN " if r["success"] else "LOSS"
            pnl_str_row = (
                f"+${abs(r['pnl']):.2f}" if r["pnl"] >= 0 else f"-${abs(r['pnl']):.2f}"
            )
            print(
                f"  {r['ticker']:<7} {r['signal']:<9} "
                f"{r['entry_price']:>8.2f} {r['exit_price']:>8.2f} "
                f"{pnl_str_row:>9}  {result}"
            )

    grand_str = (
        f"+${grand_total:.2f}" if grand_total >= 0 else f"-${abs(grand_total):.2f}"
    )
    print(f"\n{'=' * 82}")
    print(f"  TOTAL P&L ({backtest_days}-day window, 1 share per signal): {grand_str}")
    print(f"{'=' * 82}")


def print_pnl_distribution(all_results: dict, backtest_days: int, trading_dates: list):
    tickers = [t for t, df in all_results.items() if not df.empty]
    if not tickers:
        return

    frames = []
    for ticker, df in all_results.items():
        if df.empty:
            continue
        tmp = df[["date", "pnl", "signal", "success"]].copy()
        tmp["ticker"] = ticker
        frames.append(tmp)

    combined = pd.concat(frames, ignore_index=True)
    all_dates = sorted(trading_dates)

    col_w = 14
    ticker_col_w = 10

    header = f"  {'Date':<12}"
    for t in tickers:
        header += f"  {t:>{col_w}}"
    header += f"  {'DayTotal':>{col_w}}  Tickers W/L"
    divider = "  " + "─" * (12 + (col_w + 2) * (len(tickers) + 1) + 16)

    print(f"\n{'=' * len(divider)}")
    print(
        f"  P&L DISTRIBUTION — Last {backtest_days} calendar days  |  MA20/MA50 trailing stop"
    )
    print(f"{'=' * len(divider)}")
    print(header)
    print(divider)

    ticker_totals = {t: 0.0 for t in tickers}
    ticker_wins = {t: 0 for t in tickers}
    ticker_trades = {t: 0 for t in tickers}
    grand_total = 0.0

    for d in all_dates:
        day = combined[combined["date"] == d]
        row = f"  {str(d):<12}"
        day_total = 0.0
        win_count = 0
        loss_count = 0

        for t in tickers:
            trade = day[day["ticker"] == t]
            if trade.empty:
                row += f"  {'—':>{col_w}}"
            else:
                pnl = trade["pnl"].values[0]
                success = trade["success"].values[0]
                day_total += pnl
                ticker_totals[t] += pnl
                ticker_trades[t] += 1
                if success:
                    ticker_wins[t] += 1
                    win_count += 1
                    tag = f"W +${pnl:.2f}" if pnl >= 0 else f"W -${abs(pnl):.2f}"
                else:
                    loss_count += 1
                    tag = f"L -${abs(pnl):.2f}" if pnl < 0 else f"L +${pnl:.2f}"
                row += f"  {tag:>{col_w}}"

        grand_total += day_total
        if win_count == 0 and loss_count == 0:
            row += f"  {'no signal':>{col_w}}  —"
        else:
            day_str = (
                f"+${day_total:.2f}" if day_total >= 0 else f"-${abs(day_total):.2f}"
            )
            row += f"  {day_str:>{col_w}}  {win_count}W / {loss_count}L"
        print(row)

    print(divider)

    # totals row
    total_row = f"  {'TOTAL':<12}"
    for t in tickers:
        v = ticker_totals[t]
        tag = f"+${v:.2f}" if v >= 0 else f"-${abs(v):.2f}"
        total_row += f"  {tag:>{col_w}}"
    grand_str = (
        f"+${grand_total:.2f}" if grand_total >= 0 else f"-${abs(grand_total):.2f}"
    )
    total_row += f"  {grand_str:>{col_w}}"
    print(total_row)

    # win rate row
    rate_row = f"  {'WIN RATE':<12}"
    for t in tickers:
        n = ticker_trades[t]
        w = ticker_wins[t]
        rate_row += f"  {f'{w}/{n} = {w / n * 100:.0f}%' if n else '—':>{col_w}}"
    rate_row += f"  {'':>{col_w}}"
    print(rate_row)

    print(f"{'=' * len(divider)}\n")


def print_monthly_breakdown(all_results: dict, opening_bars: int):
    frames = []
    for ticker, df in all_results.items():
        if df.empty:
            continue
        tmp = df[["date", "pnl", "success", "bars_held"]].copy()
        tmp["ticker"] = ticker
        tmp["month"] = pd.to_datetime(tmp["date"]).dt.to_period("M")
        frames.append(tmp)

    if not frames:
        return

    combined = pd.concat(frames, ignore_index=True)
    tickers = list(all_results.keys())
    months = sorted(combined["month"].unique())

    print(f"\n{'=' * 70}")
    print(f"  MONTHLY BREAKDOWN — op_momentum_guide  |  {opening_bars * 5}-min opening")
    print(f"{'=' * 70}")
    print(
        f"  {'Month':<10} {'Ticker':<8} {'Signals':>8} {'Wins':>6} {'Fails':>6} {'Rate':>7} {'NetP&L':>9}"
    )
    print(f"  {'─' * 68}")

    for month in months:
        month_data = combined[combined["month"] == month]
        month_net = 0.0
        first = True
        for ticker in tickers:
            rows = month_data[month_data["ticker"] == ticker]
            if rows.empty:
                continue
            total = len(rows)
            wins = int(rows["success"].sum())
            fails = total - wins
            rate = wins / total * 100
            net = rows["pnl"].sum()
            month_net += net
            net_str = f"+${net:.2f}" if net >= 0 else f"-${abs(net):.2f}"
            month_label = str(month) if first else ""
            print(
                f"  {month_label:<10} {ticker:<8} {total:>8} {wins:>6} {fails:>6} {rate:>6.0f}%  {net_str:>9}"
            )
            first = False

        net_str = f"+${month_net:.2f}" if month_net >= 0 else f"-${abs(month_net):.2f}"
        print(f"  {'':10} {'─' * 58}")
        print(
            f"  {'':10} {'Month total':<8} {'':>8} {'':>6} {'':>6} {'':>7}  {net_str:>9}"
        )
        print()

    grand = combined["pnl"].sum()
    grand_str = f"+${grand:.2f}" if grand >= 0 else f"-${abs(grand):.2f}"
    print(f"  {'─' * 68}")
    print(
        f"  {'TOTAL':<10} {'all':<8} {len(combined):>8} {int(combined['success'].sum()):>6} "
        f"{len(combined) - int(combined['success'].sum()):>6} "
        f"{combined['success'].mean() * 100:>6.0f}%  {grand_str:>9}"
    )
    print(f"{'=' * 70}")


def print_summary(all_results: dict, backtest_days: int, opening_bars: int):
    print(f"\n{'=' * 96}")
    print(
        f"  SUMMARY — op_momentum_guide  |  Last {backtest_days} days  |  {opening_bars * 5}-min opening"
    )
    print(f"{'=' * 96}")
    print(
        f"  {'Ticker':<8} {'Signals':>8} {'Wins':>6} {'Fails':>6} {'Rate':>7} "
        f"{'AvgMins(W)':>11} {'AvgWin%':>8} {'AvgLoss%':>9} {'EV/Trade':>9} {'WinP&L':>9} {'LossP&L':>9} {'NetP&L':>9}"
    )
    print(f"  {'─' * 94}")

    total_net = 0.0
    all_win_pcts = []
    all_loss_pcts = []
    for ticker, results in all_results.items():
        if results.empty:
            print(f"  {ticker:<8} {'no signals':>8}")
            continue
        total = len(results)
        wins = int(results["success"].sum())
        fails = total - wins
        win_rate = wins / total
        loss_rate = fails / total
        avg_mins = results[results["success"]]["bars_held"].mean() * 5 if wins else 0

        win_rows = results[results["success"]]
        loss_rows = results[~results["success"]]

        win_pct_series = win_rows["pnl"] / win_rows["entry_price"] * 100
        avg_win_pct = win_pct_series.mean() if wins else 0
        all_win_pcts.extend(win_pct_series.tolist())

        loss_pct_series = loss_rows["pnl"].abs() / loss_rows["entry_price"] * 100
        avg_loss_pct = loss_pct_series.mean() if fails else 0
        all_loss_pcts.extend(loss_pct_series.tolist())

        ev = win_rate * avg_win_pct - loss_rate * avg_loss_pct

        win_pnl = win_rows["pnl"].sum()
        loss_pnl = loss_rows["pnl"].sum()
        net_pnl = results["pnl"].sum()
        total_net += net_pnl

        ev_str = f"+{ev:.3f}%" if ev >= 0 else f"{ev:.3f}%"
        net_str = f"+${net_pnl:.2f}" if net_pnl >= 0 else f"-${abs(net_pnl):.2f}"
        win_str = f"+${win_pnl:.2f}" if win_pnl >= 0 else f"-${abs(win_pnl):.2f}"
        loss_str = f"-${abs(loss_pnl):.2f}"
        print(
            f"  {ticker:<8} {total:>8} {wins:>6} {fails:>6} {win_rate * 100:>6.0f}%"
            f" {avg_mins:>10.0f}m  {avg_win_pct:>7.2f}%  {avg_loss_pct:>8.2f}%  {ev_str:>9}"
            f"  {win_str:>9}  {loss_str:>9}  {net_str:>9}"
        )

    print(f"  {'─' * 94}")
    total_str = f"+${total_net:.2f}" if total_net >= 0 else f"-${abs(total_net):.2f}"
    overall_avg_win_pct = sum(all_win_pcts) / len(all_win_pcts) if all_win_pcts else 0
    overall_avg_loss_pct = (
        sum(all_loss_pcts) / len(all_loss_pcts) if all_loss_pcts else 0
    )
    total_wins = sum(len(r[r["success"]]) for r in all_results.values() if not r.empty)
    total_sigs = sum(len(r) for r in all_results.values() if not r.empty)
    overall_win_rate = total_wins / total_sigs if total_sigs else 0
    overall_ev = (
        overall_win_rate * overall_avg_win_pct
        - (1 - overall_win_rate) * overall_avg_loss_pct
    )
    overall_ev_str = f"+{overall_ev:.3f}%" if overall_ev >= 0 else f"{overall_ev:.3f}%"
    print(
        f"  {'TOTAL':<8} {'':>8} {'':>6} {'':>6} {'':>7} {'':>11}"
        f"  {overall_avg_win_pct:>7.2f}%  {overall_avg_loss_pct:>8.2f}%  {overall_ev_str:>9}"
        f"  {'':>9}  {'':>9} {total_str:>9}"
    )
    print(f"{'=' * 96}")


def _stitch_cache(
    ticker: str, start_date: date, end_date: date, source: str
) -> "pd.DataFrame | None":
    """Try to build a full-range DataFrame by stitching existing per-period cache files."""
    pattern = re.compile(
        rf"^{re.escape(source)}_5min_{re.escape(ticker)}_(\d{{4}}-\d{{2}}-\d{{2}})_(\d{{4}}-\d{{2}}-\d{{2}})\.json$"
    )
    pieces = []
    for f in _CACHE_DIR.iterdir():
        m = pattern.match(f.name)
        if not m:
            continue
        c_start = date.fromisoformat(m.group(1))
        c_end = date.fromisoformat(m.group(2))
        if c_start <= start_date and c_end >= end_date:
            return _load_cache(f, "5min")
        if c_end >= start_date and c_start <= end_date:
            pieces.append((c_start, c_end, f))

    if not pieces:
        return None

    pieces.sort(key=lambda x: x[0])
    covered_end = start_date - timedelta(days=1)
    dfs = []
    for c_start, c_end, f in pieces:
        if c_start > covered_end + timedelta(days=7):
            return None
        try:
            dfs.append(_load_cache(f, "5min"))
        except FileNotFoundError:
            return None  # another process evicted this piece; fall through to API fetch
        if c_end > covered_end:
            covered_end = c_end

    if covered_end < end_date:
        return None

    combined = pd.concat(dfs)
    combined = combined[~combined.index.duplicated(keep="last")]
    combined.sort_index(inplace=True)
    return combined


def _partial_stitch_cache(
    ticker: str, start_date: date, end_date: date, source: str
) -> "tuple[pd.DataFrame | None, date | None]":
    """Return the best contiguous partial cache coverage without requiring full coverage.

    Unlike _stitch_cache, does not bail when covered_end < end_date — returns
    (df, covered_end) so the caller can delta-fetch only the missing tail.
    Returns (None, None) when there is no usable partial cache at all.
    """
    pattern = re.compile(
        rf"^{re.escape(source)}_5min_{re.escape(ticker)}_(\d{{4}}-\d{{2}}-\d{{2}})_(\d{{4}}-\d{{2}}-\d{{2}})\.json$"
    )
    pieces = []
    for f in _CACHE_DIR.iterdir():
        m = pattern.match(f.name)
        if not m:
            continue
        c_start = date.fromisoformat(m.group(1))
        c_end = date.fromisoformat(m.group(2))
        if c_end >= start_date and c_start <= end_date:
            pieces.append((c_start, c_end, f))

    if not pieces:
        return None, None

    pieces.sort(key=lambda x: x[0])
    covered_end = start_date - timedelta(days=1)
    dfs = []
    for c_start, c_end, f in pieces:
        if c_start > covered_end + timedelta(days=7):
            break  # Gap too large — stop with contiguous coverage we have
        try:
            dfs.append(_load_cache(f, "5min"))
        except FileNotFoundError:
            break  # another process evicted this piece; return coverage up to here
        if c_end > covered_end:
            covered_end = c_end

    if not dfs:
        return None, None

    combined = pd.concat(dfs)
    combined = combined[~combined.index.duplicated(keep="last")]
    combined.sort_index(inplace=True)
    return combined, covered_end


def _fetch_ts_bars(market_data_client, tickers: list, start_date: date, end_date: date) -> dict:
    """Fetch 5-min bars from a TradeStation market data client for the given date range."""
    _ET = pytz.timezone("America/New_York")
    start_dt = _ET.localize(datetime.combine(start_date, _time(9, 30)))
    end_dt = _ET.localize(datetime.combine(end_date, _time(16, 0)))
    return market_data_client.fetch_bars(tickers, start_dt, end_dt)


def fetch_bars(
    tickers: list,
    start_date: date,
    end_date,
    source: str = "alpaca",
    allow_intraday: bool = False,
    feed: DataFeed = None,
    market_data_client=None,
) -> dict:
    end_date_only = _to_date(end_date)
    cacheable = _is_cacheable(end_date_only)

    csource = _cache_source(source, feed)
    result = {}
    to_fetch = []
    to_fetch_delta = []  # (ticker, partial_df, partial_end)
    for ticker in tickers:
        if cacheable:
            cp = _cache_path(ticker, start_date, end_date_only, csource, "5min")
            if cp.exists():
                loaded = _load_cache(cp, "5min")
                if loaded.empty:
                    try:
                        cp.unlink()  # delete corrupt empty cache file, re-fetch below
                    except FileNotFoundError:
                        pass
                else:
                    trimmed = _trim_bars_to_range(loaded, start_date, end_date_only)
                    if not trimmed.empty:
                        if len(trimmed) < len(loaded):
                            _save_cache(trimmed, cp, "5min")
                        result[ticker] = trimmed
                        continue
                    try:
                        cp.unlink()  # cached data doesn't cover range, re-fetch below
                    except FileNotFoundError:
                        pass
            stitched = _stitch_cache(ticker, start_date, end_date_only, csource)
            if stitched is not None:
                stitched = _trim_bars_to_range(stitched, start_date, end_date_only)
                if not stitched.empty:
                    result[ticker] = stitched
                    _save_cache(stitched, cp, "5min")
                    _evict_contained_cache_pieces(
                        ticker, start_date, end_date_only, csource, "5min"
                    )
                    continue
                # Stitch returned data that doesn't cover requested range — fall through to API
            partial_df, partial_end = _partial_stitch_cache(
                ticker, start_date, end_date_only, csource
            )
            if partial_df is not None:
                partial_df = _trim_bars_to_range(partial_df, start_date, partial_end)
                to_fetch_delta.append((ticker, partial_df, partial_end))
                continue
        to_fetch.append(ticker)

    if to_fetch_delta:
        delta_start = min(pe for _, _, pe in to_fetch_delta) + timedelta(days=1)
        delta_tickers = [t for t, _, _ in to_fetch_delta]
        if delta_start <= end_date_only:
            print(
                f"  [cache] delta-fetching {len(delta_tickers)} tickers from {source} "
                f"({delta_start} → {end_date_only})"
            )
            if source == "yfinance":
                delta_fetched = fetch_yfinance_bars(delta_tickers, delta_start, end_date)
            elif source == "tradestation" and market_data_client is not None:
                delta_fetched = _fetch_ts_bars(market_data_client, delta_tickers, delta_start, end_date_only)
            else:
                delta_fetched = fetch_alpaca_bars(
                    delta_tickers, delta_start, end_date, allow_intraday=allow_intraday,
                    feed=feed,
                )
        else:
            delta_fetched = {}  # partial cache already covers full range
        for ticker, partial_df, _ in to_fetch_delta:
            tail_df = delta_fetched.get(ticker, pd.DataFrame())
            if tail_df.empty:
                merged = partial_df
            else:
                merged = pd.concat([partial_df, tail_df])
                merged = merged[~merged.index.duplicated(keep="last")]
                merged.sort_index(inplace=True)
            merged = _trim_bars_to_range(merged, start_date, end_date_only)
            result[ticker] = merged
            if not merged.empty:
                _save_cache(
                    merged,
                    _cache_path(ticker, start_date, end_date_only, csource, "5min"),
                    "5min",
                )
                _evict_contained_cache_pieces(
                    ticker, start_date, end_date_only, csource, "5min"
                )

    if to_fetch:
        if cacheable:
            print(
                f"  [cache] fetching {len(to_fetch)} tickers from {source} (cache miss)"
            )
        if source == "yfinance":
            fetched = fetch_yfinance_bars(to_fetch, start_date, end_date)
        elif source == "tradestation" and market_data_client is not None:
            fetched = _fetch_ts_bars(market_data_client, to_fetch, start_date, end_date_only)
        else:
            fetched = fetch_alpaca_bars(
                to_fetch, start_date, end_date, allow_intraday=allow_intraday, feed=feed,
            )
        for ticker, df in fetched.items():
            result[ticker] = df
            if cacheable and not df.empty:
                _save_cache(
                    df,
                    _cache_path(ticker, start_date, end_date_only, csource, "5min"),
                    "5min",
                )

    cached_count = len(tickers) - len(to_fetch) - len(to_fetch_delta)
    if cached_count:
        print(f"  [cache] loaded {cached_count} tickers from cache")

    for ticker in list(result.keys()):
        if not result[ticker].empty:
            result[ticker] = result[ticker].between_time("09:30", "15:55")

    return result


def fetch_daily_bars(
    tickers: list, start_date: date, end_date: date, source: str = "alpaca",
    feed: DataFeed = None,
) -> dict:
    """Fetch 1-day bars for the given tickers. Returns {ticker: DataFrame} with date index."""
    cacheable = _is_cacheable(end_date)

    csource = _cache_source(source, feed)
    result = {}
    to_fetch = []
    for ticker in tickers:
        if cacheable:
            cp = _cache_path(ticker, start_date, end_date, csource, "1day")
            if cp.exists():
                result[ticker] = _load_cache(cp, "1day")
                continue
        to_fetch.append(ticker)

    if not to_fetch:
        return result

    fetched = {}
    if source == "yfinance":
        for ticker in to_fetch:
            df = yf.download(
                ticker,
                start=start_date,
                end=end_date + timedelta(days=1),
                interval="1d",
                auto_adjust=True,
                progress=False,
            )
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.droplevel(1)
            df.index = pd.to_datetime(df.index).date
            fetched[ticker] = df
    else:
        key_id = os.environ.get("ALPACA_API_KEY")
        secret_key = os.environ.get("ALPACA_SECRET_KEY")
        client = StockHistoricalDataClient(key_id, secret_key)
        effective_feed = feed if feed is not None else _ALPACA_FEED
        request = StockBarsRequest(
            symbol_or_symbols=to_fetch,
            timeframe=TimeFrame(amount=1, unit=TimeFrameUnit.Day),
            start=datetime.combine(start_date, datetime.min.time()),
            end=datetime.combine(end_date + timedelta(days=1), datetime.min.time()),
            feed=effective_feed,
        )
        bars = client.get_stock_bars(request)
        for ticker in to_fetch:
            if ticker in bars.df.index.get_level_values(0):
                df = bars.df.xs(ticker, level=0).copy()
                df.index = [pd.Timestamp(t).date() for t in df.index]
                df.columns = [c.capitalize() for c in df.columns]
                fetched[ticker] = df
            else:
                fetched[ticker] = pd.DataFrame()

    for ticker, df in fetched.items():
        result[ticker] = df
        if cacheable and not df.empty:
            _save_cache(
                df, _cache_path(ticker, start_date, end_date, csource, "1day"), "1day"
            )

    return result


def build_bearish_regime_dates(
    start_date: date, end_date: date, source: str = "alpaca", regime_ma: int = 5,
    feed: DataFeed = None,
) -> set:
    """Return the set of dates on which BULLISH signals should be suppressed.

    A date D is included when QQQ's settled close on the *prior* business day
    was below its regime_ma-day MA.  Using the prior day's close means the set
    contains only information that is available at signal time (~9:45 AM ET),
    eliminating the 1-day lookahead that arises from using today's close.
    """
    fetch_start = start_date - timedelta(days=regime_ma * 3 + 10)
    qqq_df = fetch_daily_bars(["QQQ"], fetch_start, end_date, source=source, feed=feed).get(
        "QQQ", pd.DataFrame()
    )
    if qqq_df.empty:
        return set()
    qqq_df = qqq_df.copy()
    qqq_df["regime_ma"] = qqq_df["Close"].rolling(regime_ma).mean()
    bearish = qqq_df[qqq_df["Close"] < qqq_df["regime_ma"]]
    next_bday = pd.tseries.offsets.BDay(1)
    return {(pd.Timestamp(d) + next_bday).date() for d in bearish.index}


def build_qqq_or_alignment(
    start_date: date,
    end_date: date,
    opening_bars: int,
    opening_start_time: str,
    source: str = "alpaca",
    feed: DataFeed = None,
    threshold: float = 0.50,
) -> tuple:
    """Return (skip_bull_dates, skip_bear_dates) for the QQQ intraday alignment filter.

    For each trading day, computes QQQ's OR close position:
        OR_cpos = (OR_close - OR_low) / (OR_high - OR_low)

    skip_bull_dates: days where QQQ OR_cpos <= threshold (QQQ macro bearish — skip BULLISH entry)
    skip_bear_dates: days where QQQ OR_cpos >  threshold (QQQ macro bullish — skip BEARISH entry)

    Uses the same OR window (opening_bars, opening_start_time) as the individual stock signal.
    Only uses data settled at signal time (~9:45 AM ET) — no lookahead bias.
    """
    qqq_bars = fetch_bars(["QQQ"], start_date, end_date, source=source, feed=feed).get(
        "QQQ", pd.DataFrame()
    )
    if qqq_bars.empty:
        return set(), set()

    opening_start_t = datetime.strptime(opening_start_time, "%H:%M").time()
    skip_bull = set()
    skip_bear = set()

    for date_, day_df in qqq_bars.groupby(qqq_bars.index.date):
        day_from_start = day_df[day_df.index.time >= opening_start_t]
        opening = day_from_start.head(opening_bars)
        if len(opening) < opening_bars:
            continue
        or_high = float(opening["High"].max())
        or_low = float(opening["Low"].min())
        or_range = or_high - or_low
        if or_range == 0:
            continue
        or_close = float(opening.iloc[-1]["Close"])
        or_cpos = (or_close - or_low) / or_range

        if or_cpos <= threshold:
            skip_bull.add(date_)
        else:
            skip_bear.add(date_)

    return skip_bull, skip_bear


def build_qqq_extended_dates(
    start_date: date,
    end_date: date,
    extend_days: int,
    extend_pct: float,
    max_dd: float = 0.0,
    source: str = "alpaca",
    feed: DataFeed = None,
) -> set:
    """Return dates where QQQ has risen too much too fast without consolidation.

    A signal date D is included when all of the following hold using prior-day closes:
    - N-day cumulative return = close[D-1] / close[D-1-N] - 1 > extend_pct
    - (if max_dd > 0) no single trading day in that N-day window closed down more than max_dd

    Uses prior-day closes only — fully settled before 9:45 AM signal time, no lookahead.
    Used to gate --qqq-align-filter so it only fires during runaway rallies.
    """
    fetch_start = start_date - timedelta(days=extend_days * 3 + 10)
    qqq_daily = fetch_daily_bars(
        ["QQQ"], fetch_start, end_date, source=source, feed=feed
    ).get("QQQ", pd.DataFrame())
    if qqq_daily.empty:
        return set()

    closes = qqq_daily["Close"]
    trading_dates = closes.index.tolist()

    extended = set()
    for i, signal_date in enumerate(trading_dates):
        if signal_date < start_date:
            continue
        window_end_idx = i - 1
        window_start_idx = i - 1 - extend_days
        if window_start_idx < 0:
            continue
        window_end_close = closes.iloc[window_end_idx]
        window_start_close = closes.iloc[window_start_idx]
        if window_start_close <= 0:
            continue
        cumulative_return = (window_end_close / window_start_close) - 1.0
        if cumulative_return <= extend_pct:
            continue
        if max_dd > 0:
            window_closes = closes.iloc[window_start_idx: window_end_idx + 1]
            daily_returns = window_closes.pct_change().dropna()
            if (daily_returns < -max_dd).any():
                continue
        extended.add(signal_date)

    return extended


def run_backtest(
    tickers: list,
    start_date: date,
    end_date: date,
    opening_bars: int = 3,
    bearish_ma200: bool = False,
    stop_pct: float = 0.15,
    source: str = "alpaca",
    ticker_dfs: dict = None,
    opening_start_time: str = "09:30",
    trailing_ma: str = "ma20",
    max_loss_pct: float = None,
    armed_ma20_exit: bool = False,
    regime_filter: bool = False,
    regime_ma: int = 5,
    or_bar_lookback: int = 0,
    enable_bearish_reentry: bool = False,
    bearish_reentry_max_bars: int = 3,
    enable_bullish_reentry: bool = False,
    bullish_reentry_max_bars: int = 5,
    close_top_pct: float = None,
    bear_ctp_dates: set = None,
    bear_ctp: float = None,
    trailing_ma_switch: str = "none",
    trailing_ma_switch_factor: float = 1.0,
    trailing_ma_switch_period: int = 8,
    min_first_bar_range_pct: float = None,
    min_first_bar_volume_mult: float = None,
    min_or_vol_ratio: float = None,
    min_hold_bars: int = 0,
    stale_cut_mins: int = 0,
    stale_cut_threshold: float = 0.0,
    exit_at_bar_close: bool = True,
    ma_momentum_gate: bool = False,
) -> dict:
    if ticker_dfs is None:
        ticker_dfs = fetch_bars(tickers, start_date, end_date, source=source)
    bearish_regime_dates = (
        build_bearish_regime_dates(start_date, end_date, source, regime_ma)
        if regime_filter
        else None
    )
    all_results = {}
    for ticker in tickers:
        df = ticker_dfs.get(ticker, pd.DataFrame())
        if df.empty:
            all_results[ticker] = pd.DataFrame()
            continue
        results = compute_signals_with_backtest(
            df,
            opening_bars,
            bearish_ma200,
            stop_pct,
            opening_start_time,
            trailing_ma,
            max_loss_pct=max_loss_pct,
            armed_ma20_exit=armed_ma20_exit,
            bearish_regime_dates=bearish_regime_dates,
            or_bar_lookback=or_bar_lookback,
            enable_bearish_reentry=enable_bearish_reentry,
            bearish_reentry_max_bars=bearish_reentry_max_bars,
            enable_bullish_reentry=enable_bullish_reentry,
            bullish_reentry_max_bars=bullish_reentry_max_bars,
            close_top_pct=close_top_pct,
            bear_ctp_dates=bear_ctp_dates,
            bear_ctp=bear_ctp,
            trailing_ma_switch=trailing_ma_switch,
            trailing_ma_switch_factor=trailing_ma_switch_factor,
            trailing_ma_switch_period=trailing_ma_switch_period,
            min_first_bar_range_pct=min_first_bar_range_pct,
            min_first_bar_volume_mult=min_first_bar_volume_mult,
            min_or_vol_ratio=min_or_vol_ratio,
            min_hold_bars=min_hold_bars,
            stale_cut_mins=stale_cut_mins,
            stale_cut_threshold=stale_cut_threshold,
            exit_at_bar_close=exit_at_bar_close,
            ma_momentum_gate=ma_momentum_gate,
        )
        if not results.empty:
            results = results[results["date"] >= start_date].reset_index(drop=True)
        all_results[ticker] = results
    return all_results


if __name__ == "__main__":
    args = parse_args()
    source = args.source
    opening_bars = args.opening_bars
    bearish_ma200 = args.bearish_ma200
    stop_pct = args.stop_pct
    tickers = args.tickers if args.tickers else TICKERS

    if args.start:
        cutoff = date.fromisoformat(args.start)
        end_date = date.fromisoformat(args.end) if args.end else date.today()
    else:
        end_date = date.today()
        if source == "yfinance" and args.days > YFINANCE_MAX_DAYS:
            print(
                f"Warning: yfinance only supports up to {YFINANCE_MAX_DAYS} days for 5-min data. Capping at {YFINANCE_MAX_DAYS}."
            )
            args.days = YFINANCE_MAX_DAYS
        cutoff = end_date - timedelta(days=args.days)

    backtest_days = (end_date - cutoff).days
    period_label = f"{cutoff} → {end_date}  ({backtest_days} calendar days)"

    trailing_ma = args.trailing_ma
    max_loss_pct = args.max_loss_pct
    armed_ma20_exit = args.armed_ma20_exit
    regime_filter = args.regime_filter
    regime_ma = args.regime_ma
    bearish_filter = "MA20 + MA200" if bearish_ma200 else "MA20 only"
    trailing_ma_label = {
        "ma20": "MA20 only",
        "ma50": "MA50 only",
        "both": "MA20 then MA50",
    }[trailing_ma]
    print(f"\nop_momentum_guide backtest — {period_label} ({source})")
    print(f"Tickers           : {', '.join(tickers)}")
    print(
        f"Opening period    : first {opening_bars * 5} min ({opening_bars} x 5-min bars)"
    )
    print(
        f"Exit rule         : trailing stop ({trailing_ma_label}, when MA > hard stop)  |  hard stop at {stop_pct * 100:.0f}% from favorable end of OR"
    )
    print(
        f"  → Bull hard stop: OR_high - {stop_pct * 100:.0f}% × OR_range  |  Bear hard stop: OR_low + {stop_pct * 100:.0f}% × OR_range"
    )
    print(
        f"Bearish filter    : {bearish_filter}  (use --bearish-ma200 to add MA200 requirement)"
    )

    print(f"\nFetching {len(tickers)} tickers from {source} ({cutoff} → {end_date})...")

    if source == "alpaca":
        ticker_dfs = fetch_alpaca_bars(tickers, cutoff, end_date)
    else:
        ticker_dfs = fetch_yfinance_bars(tickers, cutoff, end_date)

    bearish_regime_dates = (
        build_bearish_regime_dates(cutoff, end_date, source, regime_ma)
        if regime_filter
        else None
    )

    all_results = {}
    trading_dates = set()

    for ticker in tickers:
        df = ticker_dfs.get(ticker, pd.DataFrame())
        if df.empty:
            print(f"\n  {ticker}: no data returned from {source}")
            all_results[ticker] = pd.DataFrame()
            continue

        # collect all trading days within the backtest window
        for d in df.index.date:
            if d >= cutoff:
                trading_dates.add(d)

        results = compute_signals_with_backtest(
            df,
            opening_bars,
            bearish_ma200,
            stop_pct,
            trailing_ma=trailing_ma,
            max_loss_pct=max_loss_pct,
            armed_ma20_exit=armed_ma20_exit,
            bearish_regime_dates=bearish_regime_dates,
            trailing_ma_switch=args.trailing_ma_switch,
            trailing_ma_switch_factor=args.trailing_ma_switch_factor,
            trailing_ma_switch_period=args.trailing_ma_switch_period,
            min_first_bar_range_pct=args.min_first_bar_range_pct,
            min_first_bar_volume_mult=args.min_first_bar_volume_mult,
            min_or_vol_ratio=args.min_or_vol_ratio,
            exit_at_bar_close=args.exit_at_bar_close,
        )
        if not results.empty:
            results = results[results["date"] >= cutoff].reset_index(drop=True)

        all_results[ticker] = results
        print_successful_days(ticker, results, backtest_days)
        print_stats(ticker, results)

    print_daily_pnl(all_results, backtest_days)
    print_pnl_distribution(all_results, backtest_days, trading_dates)
    print_monthly_breakdown(all_results, opening_bars)
    print_summary(all_results, backtest_days, opening_bars)

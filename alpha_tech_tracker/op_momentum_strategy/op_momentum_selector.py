import argparse
import numpy as np
import pandas as pd
import pytz
from datetime import date, datetime, timedelta

from alpaca.data.enums import DataFeed

from alpha_tech_tracker.op_momentum_strategy.op_momentum_backtest import (
    build_bearish_regime_dates,
    fetch_bars,
    run_backtest,
    compute_signals_with_backtest,
)


_ET = pytz.timezone("America/New_York")


def _safe_bars_end(target_date: date):
    """
    Returns the safe end boundary for intraday bar fetches to avoid Alpaca's
    'recent SIP data' restriction.

    - Historical date (before today): return date + 1 (safe, already in the past).
    - Today, pre-market (before 9:30 AM ET): return target_date so the request
      ends at yesterday's close.
    - Today, market open or later: return the current datetime in ET so the
      request ends right now rather than at midnight UTC tonight (which is still
      in the future and triggers the 403).
    """
    now_et = datetime.now(_ET)
    if target_date < now_et.date():
        return target_date + timedelta(days=1)
    market_open = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
    if now_et >= market_open:
        return now_et
    return target_date


# DEFAULT_TICKERS = ["SNDK", "APP", "SHOP", "CVNA", "AMD", "META", "EXPE", "FANG"]
# v2 pool: added PLTR, COIN, NVDA — 5yr backtest 2021-2025: +330% vs +319% original
# GS and REGN: $2.50/signal over 90 days from 3/26/2026, during down trend
# removed UI 2026-03-31: Alpaca returns only sparse extended-hours bars, no reliable morning session data
# removed ISSC, added RH 2026-04-01: swap gains +19pp over 5 years; RH has cleaner OR breakouts
# removed FANG (structurally weak, +1-2% in Q1/Q2 2025 and Q1 2026), NVDA (fading trend, +0.6% Q4 2024),
# TSLA (peaked Q2/Q3 2025, declining to +6.5% Q1 2026) — replaced with CLS, MSTR, CRWV, MRVL (2026-04-12)
DEFAULT_TICKERS = [
    #"SNDK", # price is too high
    'CHTR',  # bring in diversification
    "APP",
    "SHOP",
    "CVNA",
    "AMD",
    "META",
    "EXPE",
    "JPM",
    "TSLA",
    "MU",
    "CRDO", # replaced ANAB 2026-04-10: sparse live data; CRDO has min 72 bars/day, 3.65% OR
    "PLTR",
    "COIN",
    "CLS",  # replaced FANG 2026-04-12: CLS +12-39% per quarter vs FANG structurally weak
    "MSTR", # replaced NVDA 2026-04-12: MSTR consistent +8-56%, NVDA fading (+0.6% Q4 2024)
    "CRWV", # replaced TSLA 2026-04-12: CRWV accelerating (+24% Q4 2025, +37% Q1 2026); TSLA peaked
    "MRVL", # added 2026-04-12: high-variance but strong peaks (+40% Q2 2025, +28% Q1 2026)
]

# AT pool (2026-04-12): removed ANAB, RH, FN, EXPE, FANG (sparse bars / low trade count
# from March 2026 data); added RKLB, ASTS, HOOD (Russell 2000 active), MSTR, NFLX (large-cap).
# CRWD → MSTR swap: MSTR wins 5/7 years vs CRWD (+4.5pp over 7 years); BTC-correlated beta driver.
ACTIVELY_TRADE_TICKERS = [
    "SNDK",
    "APP",
    "SHOP",
    "CVNA",
    "AMD",
    "META",
    "MU",
    "PLTR",
    "COIN",
    "NVDA",
    "TSLA",
    "RKLB",
    "ASTS",
    "HOOD",
    "MSTR",
    "NFLX",
]
ROLLING_LOOKBACK_DAYS = 60
OPENING_BARS = 3
OPENING_START_TIME = "09:30"
STOP_PCT = 0.15


def _compute_ev(success: np.ndarray, pnl: np.ndarray, entry_price: np.ndarray) -> float:
    total = len(success)
    if total == 0:
        return 0.0
    win_mask = success
    loss_mask = ~success
    win_count = int(win_mask.sum())
    loss_count = int(loss_mask.sum())
    win_rate = win_count / total
    loss_rate = loss_count / total
    avg_win_pct = (pnl[win_mask] / entry_price[win_mask] * 100).mean() if win_count else 0.0
    avg_loss_pct = (
        np.abs(pnl[loss_mask]) / entry_price[loss_mask] * 100
    ).mean() if loss_count else 0.0
    return win_rate * avg_win_pct - loss_rate * avg_loss_pct


def compute_ticker_stats(results_df: pd.DataFrame, recent_days: int = 15, recent_bear_trades: int = 7) -> dict:
    if results_df.empty:
        return {
            "signals": 0,
            "win_rate": 0.0,
            "avg_win_pct": 0.0,
            "avg_loss_pct": 0.0,
            "ev_trade": 0.0,
            "avg_entry_vs_mid_pct": 0.0,
            "ev_trade_bullish": 0.0,
            "ev_trade_bearish": 0.0,
            "ev_trend": 0.0,
            "recent_bear_ev": 0.0,
        }

    # Extract to numpy once — eliminates per-operation pandas overhead across all EV calls.
    success = results_df["success"].to_numpy(dtype=bool)
    pnl = results_df["pnl"].to_numpy(dtype=float)
    entry_price = results_df["entry_price"].to_numpy(dtype=float)
    midpoint = results_df["midpoint"].to_numpy(dtype=float)
    signal = results_df["signal"].to_numpy()
    dates = results_df["date"].to_numpy()

    total = len(success)
    win_mask = success
    loss_mask = ~success
    win_count = int(win_mask.sum())
    loss_count = int(loss_mask.sum())
    win_rate = win_count / total
    loss_rate = loss_count / total

    avg_win_pct = (pnl[win_mask] / entry_price[win_mask] * 100).mean() if win_count else 0.0
    avg_loss_pct = (
        np.abs(pnl[loss_mask]) / entry_price[loss_mask] * 100
    ).mean() if loss_count else 0.0
    ev_trade = win_rate * avg_win_pct - loss_rate * avg_loss_pct

    avg_entry_vs_mid_pct = (
        np.abs(entry_price[win_mask] - midpoint[win_mask]) / midpoint[win_mask] * 100
    ).mean() if win_count else 0.0

    bull_mask = signal == "BULLISH"
    bear_mask = signal == "BEARISH"
    ev_trade_bullish = _compute_ev(success[bull_mask], pnl[bull_mask], entry_price[bull_mask])
    ev_trade_bearish = _compute_ev(success[bear_mask], pnl[bear_mask], entry_price[bear_mask])

    recent_cutoff = dates.max() - timedelta(days=recent_days)
    recent_mask = dates >= recent_cutoff
    ev_trend = _compute_ev(success[recent_mask], pnl[recent_mask], entry_price[recent_mask]) - ev_trade

    bear_indices = np.where(bear_mask)[0]
    tail_indices = bear_indices[-recent_bear_trades:] if len(bear_indices) > 0 else bear_indices
    recent_bear_ev = _compute_ev(success[tail_indices], pnl[tail_indices], entry_price[tail_indices])

    return {
        "signals": total,
        "win_rate": win_rate,
        "avg_win_pct": avg_win_pct,
        "avg_loss_pct": avg_loss_pct,
        "ev_trade": ev_trade,
        "avg_entry_vs_mid_pct": avg_entry_vs_mid_pct,
        "ev_trade_bullish": ev_trade_bullish,
        "ev_trade_bearish": ev_trade_bearish,
        "ev_trend": ev_trend,
        "recent_bear_ev": recent_bear_ev,
    }


def compute_today_signals(
    ticker_dfs: dict,
    opening_bars: int,
    bearish_ma200: bool,
    stop_pct: float,
    target_date: date = None,
    opening_start_time: str = OPENING_START_TIME,
    or_bar_lookback: int = 3,
    bearish_regime_dates: set = None,
) -> dict:
    if target_date is None:
        target_date = datetime.now(_ET).date()

    opening_start_t = datetime.strptime(opening_start_time, "%H:%M").time()

    signals = {}
    for ticker, df in ticker_dfs.items():
        if df.empty:
            continue

        results = compute_signals_with_backtest(
            df, opening_bars, bearish_ma200, stop_pct,
            opening_start_time=opening_start_time,
            bearish_regime_dates=bearish_regime_dates,
        )
        if results.empty:
            continue

        today_rows = results[results["date"] == target_date]
        if today_rows.empty:
            continue

        _false = pd.Series(False, index=today_rows.index)
        primary_rows = today_rows[
            (today_rows.get("is_reversal", _false) != True)  # noqa: E712
            & (today_rows.get("is_bearish_reentry", _false) != True)  # noqa: E712
            & (today_rows.get("is_bullish_reentry", _false) != True)  # noqa: E712
        ]
        if primary_rows.empty:
            continue
        row = primary_rows.iloc[0]
        entry = row["entry_price"]
        mid = row["midpoint"]
        or_high = row["or_high"]
        or_low = row["or_low"]
        or_range = or_high - or_low
        entry_vs_mid_pct = abs(entry - mid) / mid * 100 if mid != 0 else 0.0

        if or_bar_lookback > 0:
            day_df_full = df[df.index.date == target_date]
            pre_opening = day_df_full[day_df_full.index.time < opening_start_t].tail(or_bar_lookback)
            if len(pre_opening) > 0:
                avg_recent_bar_range = (pre_opening["High"] - pre_opening["Low"]).mean()
                if or_range < avg_recent_bar_range / 4:
                    or_range = avg_recent_bar_range

        or_range_pct = or_range / entry * 100 if entry != 0 else 0.0

        # Pull MA50 from the bar data at the opening period close on target_date
        day_df = df[df.index.date == target_date]
        ma50 = float("nan")
        if not day_df.empty and "MA50" in day_df.columns:
            opening_close = (
                day_df.iloc[opening_bars - 1]
                if len(day_df) >= opening_bars
                else day_df.iloc[-1]
            )
            ma50 = opening_close["MA50"]
        else:
            # Compute MA50 if not present
            df_copy = df.copy()
            df_copy["MA50"] = df_copy["Close"].rolling(50).mean()
            day_df_copy = df_copy[df_copy.index.date == target_date]
            if not day_df_copy.empty:
                opening_close = (
                    day_df_copy.iloc[opening_bars - 1]
                    if len(day_df_copy) >= opening_bars
                    else day_df_copy.iloc[-1]
                )
                ma50 = opening_close["MA50"]

        raw_ratio = row.get("or_vol_ratio", None)
        or_vol_ratio = float(raw_ratio) if raw_ratio is not None and not pd.isna(raw_ratio) else 1.0
        signals[ticker] = {
            "signal": row["signal"],
            "or_high": float(or_high),
            "or_low": float(or_low),
            "or_range": float(or_range),
            "midpoint": float(mid),
            "entry_price": float(entry),
            "entry_vs_mid_pct": float(entry_vs_mid_pct),
            "or_range_pct": float(or_range_pct),
            "or_vol_ratio": or_vol_ratio,
            "ma20": float(row["ma20"]),
            "ma50": float(ma50) if not pd.isna(ma50) else float("nan"),
            "ma200": float(row["ma200"]),
        }

    return signals


def score_ticker(
    signal_dict: dict,
    ticker_stats: dict,
    score_entry_weight: float = 0.50,
    score_vol_ratio_weight: float = 0.00,
    score_avg_win_weight: float = 0.30,
    score_ev_trend_weight: float = 0.00,
    score_dist_52w_low_weight: float = 0.00,
    score_streak_weight: float = 0.00,
    score_prev_day_vol_weight: float = 0.00,
    score_ma200_dist_weight: float = 0.00,
    score_ma50_dist_weight: float = 0.00,
    score_win_rate_weight: float = 0.00,
    score_trend_align_weight: float = 0.00,
    score_dist_52w_high_weight: float = 0.00,
    score_frog_weight: float = 0.00,
    score_rel_strength_weight: float = 0.00,
    score_dir_ev_weight: float = 0.00,
    score_recent_bear_ev_weight: float = 0.00,
    score_or_bar_quality_weight: float = 0.00,
    score_gap_weight: float = 0.00,
    daily_context: dict = None,
    ma_momentum_gate_in_scoring: bool = False,
) -> float:
    if ticker_stats["ev_trade"] <= 0:
        return 0.0
    _ma_gate_penalty = False
    if ma_momentum_gate_in_scoring:
        or_high = signal_dict.get("or_high", float("nan"))
        or_low = signal_dict.get("or_low", float("nan"))
        sig_ma20 = signal_dict.get("ma20", float("nan"))
        sig_ma50 = signal_dict.get("ma50", float("nan"))
        if not (np.isnan(or_high) or np.isnan(or_low) or np.isnan(sig_ma20) or np.isnan(sig_ma50)):
            direction = signal_dict.get("signal", "")
            if direction == "BULLISH":
                if not (or_high >= sig_ma20 and or_high >= sig_ma50):
                    _ma_gate_penalty = True
            elif direction == "BEARISH":
                if not (or_low <= sig_ma20 and or_low <= sig_ma50):
                    _ma_gate_penalty = True
    or_range_weight = (
        1.0
        - score_entry_weight
        - score_vol_ratio_weight
        - score_avg_win_weight
        - score_ev_trend_weight
        - score_dist_52w_low_weight
        - score_streak_weight
        - score_prev_day_vol_weight
        - score_ma200_dist_weight
        - score_ma50_dist_weight
        - score_win_rate_weight
        - score_trend_align_weight
        - score_dist_52w_high_weight
        - score_frog_weight
        - score_rel_strength_weight
        - score_dir_ev_weight
        - score_recent_bear_ev_weight
        - score_or_bar_quality_weight
        - score_gap_weight
    )
    if or_range_weight < -1e-9:
        raise ValueError(
            f"Score weights sum exceeds 1.0: entry={score_entry_weight}, "
            f"vol_ratio={score_vol_ratio_weight}, avg_win={score_avg_win_weight}, "
            f"ev_trend={score_ev_trend_weight}, dist_52w_low={score_dist_52w_low_weight}, "
            f"dist_52w_high={score_dist_52w_high_weight}, streak={score_streak_weight}, "
            f"prev_day_vol={score_prev_day_vol_weight}, ma200_dist={score_ma200_dist_weight}, "
            f"ma50_dist={score_ma50_dist_weight}, win_rate={score_win_rate_weight}, "
            f"trend_align={score_trend_align_weight}, frog={score_frog_weight}, "
            f"rel_strength={score_rel_strength_weight}, dir_ev={score_dir_ev_weight}, "
            f"recent_bear_ev={score_recent_bear_ev_weight}, "
            f"or_bar_quality={score_or_bar_quality_weight}, gap={score_gap_weight} — "
            f"or_range_weight would be {or_range_weight:.3f}"
        )
    or_range_weight = max(or_range_weight, 0.0)
    if _ma_gate_penalty:
        or_range_weight *= 0.5

    ctx = daily_context or {}
    direction_sign = 1.0 if signal_dict.get("signal") == "BULLISH" else -1.0

    gap_pct = ctx.get("overnight_gap_pct", np.nan)
    # Contrarian: gap_term = direction_sign * (-gap_pct)
    # Gap up into a BEARISH signal (stock gapped up but signals weakness) is rewarded.
    # Gap down into a BULLISH signal (stock gapped down but signals recovery) is rewarded.
    gap_term = direction_sign * (-gap_pct) if not np.isnan(gap_pct) else 0.0

    dist_52w_low = ctx.get("dist_52w_low_pct", np.nan)
    dist_52w_low_term = (-dist_52w_low / 100.0) if not np.isnan(dist_52w_low) else 0.0

    dist_52w_high = ctx.get("dist_52w_high_pct", np.nan)
    # George & Hwang (2004): stocks near their 52w high have stronger continuation.
    # Term maps to [0, 1]: 1.0 at 52w high, decreasing as stock moves further below.
    # Applied symmetrically: BULLISH (breakout near high) and BEARISH (failing at resistance).
    dist_52w_high_term = (1.0 + dist_52w_high / 100.0) if not np.isnan(dist_52w_high) else 0.0

    streak = ctx.get("consec_streak", np.nan)
    streak_term = (-abs(streak)) if not np.isnan(streak) else 0.0
    # Direction-aware: reward signal aligned with prior price momentum, penalize counter-trend.
    # consec_streak > 0 = consecutive up days, < 0 = consecutive down days.
    # Normalized to [-1, +1] range using 5 as typical max streak.
    trend_align_term = (direction_sign * streak / 5.0) if not np.isnan(streak) else 0.0

    prev_vol = ctx.get("prev_day_vol_ratio", np.nan)
    prev_day_vol_term = (prev_vol - 1.0) if not np.isnan(prev_vol) else 0.0

    ma200_dist = ctx.get("daily_ma200_dist_pct", np.nan)
    ma200_dist_term = (-ma200_dist / 10.0) if not np.isnan(ma200_dist) else 0.0

    # Direction-aware: reward above-MA50 for BULLISH, below-MA50 for BEARISH
    ma50_dist = ctx.get("daily_ma50_dist_pct", np.nan)
    ma50_dist_term = (direction_sign * ma50_dist / 10.0) if not np.isnan(ma50_dist) else 0.0

    frog_score = ctx.get("frog_score", 0.0) or 0.0
    # Direction-aware: consistent up-days reward BULLISH, consistent down-days reward BEARISH.
    frog_term = direction_sign * frog_score

    # Cross-sectional relative MA50 strength: ticker's MA50 dist minus pool mean for the day.
    # Positive = outperforming pool (less beaten down in bear, or more extended in bull).
    # Direction-aware: rewards BULLISH for outperforming, BEARISH for underperforming pool.
    rel_ma50_dist = ctx.get("rel_ma50_dist_pct", np.nan)
    rel_strength_term = (direction_sign * rel_ma50_dist / 10.0) if not np.isnan(rel_ma50_dist) else 0.0

    # Direction-specific historical EV: uses ev_trade_bullish for BULLISH signals,
    # ev_trade_bearish for BEARISH signals. This separates tickers that perform well
    # in a given direction from those that are just generally active.
    if signal_dict.get("signal") == "BULLISH":
        dir_ev = ticker_stats.get("ev_trade_bullish", 0.0) or 0.0
    else:
        dir_ev = ticker_stats.get("ev_trade_bearish", 0.0) or 0.0
    dir_ev_term = dir_ev

    return (
        signal_dict["entry_vs_mid_pct"] * score_entry_weight
        + ticker_stats["avg_win_pct"] * score_avg_win_weight
        + signal_dict["or_range_pct"] * or_range_weight
        + signal_dict.get("or_vol_ratio", 1.0) * score_vol_ratio_weight
        + ticker_stats.get("ev_trend", 0.0) * score_ev_trend_weight
        + dist_52w_low_term * score_dist_52w_low_weight
        + streak_term * score_streak_weight
        + prev_day_vol_term * score_prev_day_vol_weight
        + ma200_dist_term * score_ma200_dist_weight
        + ma50_dist_term * score_ma50_dist_weight
        + ticker_stats["win_rate"] * score_win_rate_weight
        + trend_align_term * score_trend_align_weight
        + dist_52w_high_term * score_dist_52w_high_weight
        + frog_term * score_frog_weight
        + rel_strength_term * score_rel_strength_weight
        + dir_ev_term * score_dir_ev_weight
        + ticker_stats.get("recent_bear_ev", 0.0) * score_recent_bear_ev_weight
        + signal_dict.get("or_bar_quality", 0.5) * score_or_bar_quality_weight
        + gap_term * score_gap_weight
    )


def select_top_n(
    n: int,
    tickers: list,
    lookback_days: int,
    opening_bars: int,
    bearish_ma200: bool,
    stop_pct: float,
    source: str,
    target_date: date = None,
    ticker_dfs: dict = None,
    opening_start_time: str = OPENING_START_TIME,
    or_bar_lookback: int = 3,
    regime_filter: bool = False,
    regime_ma: int = 8,
    close_top_pct: float = None,
    trailing_ma: str = "ma20",
    max_loss_pct: float = None,
    armed_ma20_exit: bool = False,
    feed: DataFeed = None,
    score_entry_weight: float = 0.50,
    score_avg_win_weight: float = 0.30,
    score_win_rate_weight: float = 0.0,
    score_rel_strength_weight: float = 0.0,
    normalize_or_by_adr: bool = False,
    adr_days: int = 20,
    min_pool_vote_to_trade: int = 0,
) -> list:
    if target_date is None:
        target_date = datetime.now(_ET).date()

    lookback_start = target_date - timedelta(days=lookback_days)

    if ticker_dfs is None:
        # Single fetch covering both the rolling lookback and MA warmup windows.
        # MA warmup needs 30 days; use min() so a longer lookback_days still works.
        ma_warmup_start = target_date - timedelta(days=30)
        fetch_start = min(lookback_start, ma_warmup_start)
        ticker_dfs = fetch_bars(
            tickers,
            fetch_start,
            _safe_bars_end(target_date),
            source=source,
        )

    all_results = run_backtest(
        tickers=tickers,
        start_date=lookback_start,
        end_date=target_date,
        opening_bars=opening_bars,
        bearish_ma200=bearish_ma200,
        stop_pct=stop_pct,
        source=source,
        ticker_dfs=ticker_dfs,
        opening_start_time=opening_start_time,
        or_bar_lookback=or_bar_lookback,
        regime_filter=regime_filter,
        regime_ma=regime_ma,
        close_top_pct=close_top_pct,
        trailing_ma=trailing_ma,
        max_loss_pct=max_loss_pct,
        armed_ma20_exit=armed_ma20_exit,
    )

    rolling_stats = {
        ticker: compute_ticker_stats(
            df[df["date"] < target_date] if not df.empty else df
        )
        for ticker, df in all_results.items()
    }

    _bearish_regime_dates = (
        build_bearish_regime_dates(lookback_start, target_date, source, regime_ma, feed=feed)
        if regime_filter
        else None
    )
    today_signals = compute_today_signals(
        ticker_dfs, opening_bars, bearish_ma200, stop_pct, target_date,
        opening_start_time=opening_start_time,
        or_bar_lookback=or_bar_lookback,
        bearish_regime_dates=_bearish_regime_dates,
    )

    if min_pool_vote_to_trade > 0:
        pool_vote = sum(1 for s in rolling_stats.values() if s["ev_trade"] > 0)
        if pool_vote < min_pool_vote_to_trade:
            return {
                "picks": [],
                "no_signal": list(tickers),
                "negative_ev": [],
                "rolling_stats": rolling_stats,
            }

    # Pre-compute 20-day rolling ADR per ticker (prior-day, no lookahead).
    adr_by_ticker = {}
    if normalize_or_by_adr and ticker_dfs:
        for t, df in ticker_dfs.items():
            if df.empty:
                continue
            mh = df.between_time("09:30", "16:00")
            daily = mh.resample("D").agg(
                High=("High", "max"),
                Low=("Low", "min"),
                Close=("Close", "last"),
            ).dropna(subset=["Close"])
            daily.index = daily.index.normalize().tz_localize(None)
            daily["adr_pct"] = (daily["High"] - daily["Low"]) / daily["Close"] * 100
            rolling_adr = daily["adr_pct"].rolling(adr_days, min_periods=5).mean().shift(1)
            adr_by_ticker[t] = {
                ts.date(): float(v)
                for ts, v in rolling_adr.items()
                if not pd.isna(v)
            }

    # Cross-sectional relative MA50 strength: ticker's prior-day MA50-distance minus
    # the pool mean on target_date - 1 (shift(1) matches backtest daily_context logic).
    rel_strength_by_ticker = {}
    if score_rel_strength_weight and ticker_dfs:
        ma50_dist_vals = {}
        prev_date = target_date - timedelta(days=1)
        for t, df in ticker_dfs.items():
            if df.empty:
                continue
            mh = df.between_time("09:30", "16:00")
            daily = mh.resample("D").agg(
                Open=("Open", "first"),
                Close=("Close", "last"),
            ).dropna(subset=["Close"])
            daily.index = daily.index.normalize().tz_localize(None)
            ma50 = daily["Close"].rolling(50, min_periods=20).mean()
            # shift(1): today's dist uses yesterday's close for MA50 computation,
            # but we use yesterday's Open as proxy for the OR open (no-lookahead).
            # Match backtest: daily_ma50_dist_pct = (Open - MA50) / MA50 * 100, shift(1).
            dist = (daily["Open"] - ma50) / ma50 * 100
            prev_ts = pd.Timestamp(prev_date)
            if prev_ts in dist.index:
                ma50_dist_vals[t] = float(dist[prev_ts])
        valid_vals = [v for v in ma50_dist_vals.values() if not np.isnan(v)]
        pool_mean = sum(valid_vals) / len(valid_vals) if valid_vals else 0.0
        for t, v in ma50_dist_vals.items():
            rel_strength_by_ticker[t] = (v - pool_mean) if not np.isnan(v) else float("nan")

    scored = []
    no_signal = []
    negative_ev = []

    for ticker in tickers:
        if ticker not in today_signals:
            no_signal.append(ticker)
            continue

        sig = dict(today_signals[ticker])  # copy — normalize_or_by_adr mutates or_range_pct
        stats = rolling_stats.get(ticker, compute_ticker_stats(pd.DataFrame()))

        if stats["ev_trade"] <= 0:
            negative_ev.append(ticker)
            continue

        if normalize_or_by_adr:
            _adr = adr_by_ticker.get(ticker, {}).get(target_date)
            if _adr and _adr > 0:
                sig["or_range_pct"] = sig["or_range_pct"] / _adr

        daily_ctx = None
        if score_rel_strength_weight:
            daily_ctx = {"rel_ma50_dist_pct": rel_strength_by_ticker.get(ticker, float("nan"))}

        s = score_ticker(
            sig, stats,
            score_entry_weight=score_entry_weight,
            score_avg_win_weight=score_avg_win_weight,
            score_win_rate_weight=score_win_rate_weight,
            score_rel_strength_weight=score_rel_strength_weight,
            daily_context=daily_ctx,
        )
        scored.append(
            {
                "ticker": ticker,
                "signal": sig["signal"],
                "score": round(s, 3),
                "entry_vs_mid_pct": round(sig["entry_vs_mid_pct"], 3),
                "or_range_pct": round(sig["or_range_pct"], 3),
                "ev_trade": round(stats["ev_trade"], 3),
                "win_rate": round(stats["win_rate"], 3),
                "avg_win_pct": round(stats["avg_win_pct"], 3),
            }
        )

    scored.sort(key=lambda x: x["score"], reverse=True)
    top = scored[:n]

    return {
        "picks": top,
        "no_signal": no_signal,
        "negative_ev": negative_ev,
        "rolling_stats": rolling_stats,
    }


def _parse_args():
    parser = argparse.ArgumentParser(
        description="op_momentum live top-N stock selector"
    )
    parser.add_argument(
        "--top",
        type=int,
        default=3,
        help="Number of top tickers to select (default: 3)",
    )
    parser.add_argument(
        "--tickers", nargs="+", default=None, help="Override default ticker list"
    )
    parser.add_argument(
        "--ticker-set",
        choices=["V3", "AT"],
        default=None,
        help="Named ticker set: V3 (default pool) or AT (ACTIVELY_TRADE_TICKERS)",
    )
    parser.add_argument(
        "--lookback",
        type=int,
        default=ROLLING_LOOKBACK_DAYS,
        help=f"Rolling lookback in calendar days (default: {ROLLING_LOOKBACK_DAYS})",
    )
    parser.add_argument(
        "--stop-pct",
        type=float,
        default=STOP_PCT,
        help=f"Hard stop as fraction of OR range (default: {STOP_PCT})",
    )
    parser.add_argument(
        "--date", type=str, default=None, help="Target date YYYY-MM-DD (default: today)"
    )
    parser.add_argument(
        "--source",
        choices=["alpaca", "yfinance"],
        default="alpaca",
        help="Market data source (default: alpaca)",
    )
    parser.add_argument(
        "--bearish-ma200",
        action="store_true",
        default=False,
        help="Require price < MA200 for bearish signal",
    )
    parser.add_argument(
        "--opening-bars",
        type=int,
        default=OPENING_BARS,
        help=f"Number of 5-min bars in opening period (default: {OPENING_BARS})",
    )
    parser.add_argument(
        "--opening-start",
        type=str,
        default=OPENING_START_TIME,
        help=f"Opening window start time HH:MM ET (default: {OPENING_START_TIME})",
    )
    parser.add_argument(
        "--or-bar-lookback",
        type=int,
        default=3,
        dest="or_bar_lookback",
        help="If OR range < 1/4 of avg High-Low of last N bars before the window, use that avg as the effective OR range for scoring. Default: 3.",
    )
    return parser.parse_args()


def _print_table(
    picks: list,
    target_date: date,
    opening_bars: int,
    lookback_days: int,
    stop_pct: float,
):
    sep = "\u2501" * 78
    opening_mins = opening_bars * 5
    print(
        f"\nTop {len(picks)} picks for {target_date}  "
        f"({opening_mins}-min opening, stop-pct {stop_pct}, {lookback_days}-day rolling stats)"
    )
    print(sep)
    print(
        f"{'Rank':>4}  {'Ticker':<7} {'Signal':<9} {'Score':>6}  "
        f"{'Entry%vMid':>10}  {'OR Range%':>9}  {'EV/Trade':>9}  {'WinRate':>8}  {'AvgWin%':>8}"
    )
    print(sep)

    if not picks:
        print("  No tickers with a signal and positive EV today.")
    else:
        for i, p in enumerate(picks, 1):
            ev_str = (
                f"+{p['ev_trade']:.3f}%"
                if p["ev_trade"] >= 0
                else f"{p['ev_trade']:.3f}%"
            )
            print(
                f"{i:>4}   {p['ticker']:<7} {p['signal']:<9} {p['score']:>6.3f}  "
                f"{p['entry_vs_mid_pct']:>9.2f}%  {p['or_range_pct']:>8.2f}%  "
                f"{ev_str:>9}  {p['win_rate'] * 100:>7.0f}%  {p['avg_win_pct']:>7.2f}%"
            )

    print(sep)


if __name__ == "__main__":
    args = _parse_args()
    _TICKER_SETS = {"V3": DEFAULT_TICKERS, "AT": ACTIVELY_TRADE_TICKERS}
    tickers = args.tickers or _TICKER_SETS.get(args.ticker_set, DEFAULT_TICKERS)
    target_date = date.fromisoformat(args.date) if args.date else date.today()

    print(f"Fetching data and computing signals for {target_date}...")

    result = select_top_n(
        n=args.top,
        tickers=tickers,
        lookback_days=args.lookback,
        opening_bars=args.opening_bars,
        bearish_ma200=args.bearish_ma200,
        stop_pct=args.stop_pct,
        source=args.source,
        target_date=target_date,
        opening_start_time=args.opening_start,
        or_bar_lookback=args.or_bar_lookback,
    )

    picks = result["picks"]
    no_signal = result["no_signal"]
    negative_ev = result["negative_ev"]

    _print_table(picks, target_date, args.opening_bars, args.lookback, args.stop_pct)

    if no_signal:
        no_sig_str = ", ".join(f"{t} (no signal fired)" for t in no_signal)
        print(f"No signal today: {no_sig_str}")
    if negative_ev:
        print(f"Excluded (negative EV): {', '.join(negative_ev)}")
    if not no_signal and not negative_ev:
        print("No excluded tickers.")

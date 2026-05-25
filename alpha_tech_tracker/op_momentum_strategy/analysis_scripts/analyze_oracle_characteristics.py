"""
Oracle characteristics analysis.

For every trading day in the eval window, simulate all tickers with the M1 config,
rank them by actual P&L (oracle/hindsight), then compare feature distributions
between oracle top-2 picks and the rest to surface discriminating signals.

All daily features use only prior-day (or earlier) data — no same-day lookahead.
Today's open is known at 9:30 AM and is safe to use against prior-close-based bands/MAs.

Features — OR / 5-min bars at signal time:
  entry_vs_mid_pct    : |entry - OR midpoint| / midpoint * 100
  or_range_pct        : OR range / entry * 100
  or_vol_ratio        : mean OR-bar volume / 20d rolling avg of same window
  ma20_dist_pct       : (entry - 5min_ma20) / 5min_ma20 * 100
  ma200_dist_pct      : (entry - 5min_ma200) / 5min_ma200 * 100

Features — daily bars (resampled from 5-min, prior-day based, no lookahead):
  gap_pct             : (today open - prev close) / prev close * 100
  gap_vs_prev_high_pct: (today open - prev day high) / prev day high * 100  [breakout gate]
  prev_day_close_pos  : (prev close - prev low) / (prev high - prev low)  [0=bottom,1=top]
  ret_5d_pct          : (today open - 5d ago close) / 5d ago close * 100
  ret_20d_pct         : (today open - 20d ago close) / 20d ago close * 100
  daily_ma20_dist_pct : (today open - daily MA20) / daily MA20 * 100  [MA = prior closes]
  daily_ma50_dist_pct : (today open - daily MA50) / daily MA50 * 100
  daily_ma200_dist_pct: (today open - daily MA200) / daily MA200 * 100
  ma_stack            : count of MAs (20/50/200) that prior close is above  [0-3]
  rsi_14              : RSI(14) on prior close
  bb_position         : (today open - BB lower) / (BB upper - BB lower)  [prior-close bands]
  macd_hist           : MACD histogram value on prior close (positive=accelerating)
  atr_ratio           : OR range / 20d avg true range
  prev_day_vol_ratio  : prev day volume / 20d rolling avg volume  [no lookahead proxy]
  consec_streak       : consecutive up(+) or down(-) closes through prior day
  dist_52w_high_pct   : (today open - 52w high through prior day) / 52w high * 100

Usage:
  PYTHONPATH=. python alpha_tech_tracker/op_momentum_strategy/analyze_oracle_characteristics.py \
    --start 2026-01-01 --end 2026-05-23
"""

import argparse
from datetime import date, timedelta

import numpy as np
import pandas as pd
from alpaca.data.enums import DataFeed

from alpha_tech_tracker.op_momentum_strategy.op_momentum_backtest import (
    compute_signals_with_backtest,
    fetch_bars,
)
from alpha_tech_tracker.op_momentum_strategy.op_momentum_selector import (
    DEFAULT_TICKERS,
)

OPENING_BARS = 3
OPENING_START = "09:30"
STOP_PCT = 0.15
LOOKBACK_DAYS = 400  # needs ~1yr for 52-week high + MA200 warmup
SOURCE = "alpaca"
FEED = DataFeed.SIP


# ── helpers ──────────────────────────────────────────────────────────────────

def _safe(v):
    return float(v) if v is not None and not (isinstance(v, float) and np.isnan(v)) else np.nan


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / (avg_loss + 1e-9)
    return 100 - 100 / (1 + rs)


def _consec_streak(close: pd.Series) -> pd.Series:
    """Consecutive up (+N) or down (-N) closes."""
    result = np.zeros(len(close))
    vals = close.values
    streak = 0
    for i in range(1, len(vals)):
        if np.isnan(vals[i]) or np.isnan(vals[i - 1]):
            streak = 0
        elif vals[i] > vals[i - 1]:
            streak = streak + 1 if streak > 0 else 1
        elif vals[i] < vals[i - 1]:
            streak = streak - 1 if streak < 0 else -1
        else:
            streak = 0
        result[i] = streak
    return pd.Series(result, index=close.index)


def _resample_daily(bars_5min: pd.DataFrame) -> pd.DataFrame:
    mh = bars_5min.between_time("09:30", "16:00")
    daily = mh.resample("D").agg(
        Open=("Open", "first"),
        High=("High", "max"),
        Low=("Low", "min"),
        Close=("Close", "last"),
        Volume=("Volume", "sum"),
    ).dropna(subset=["Close"])
    daily.index = daily.index.normalize().tz_localize(None)
    return daily


def _build_daily_features(bars_5min: pd.DataFrame) -> pd.DataFrame:
    """
    Full daily feature table — all values use only prior-day or earlier data.
    Today's open is compared against prior-close-based indicators (no lookahead).
    """
    d = _resample_daily(bars_5min).copy()

    # ── momentum / gap ────────────────────────────────────────────────────────
    d["prev_close"] = d["Close"].shift(1)
    d["gap_pct"] = (d["Open"] - d["prev_close"]) / d["prev_close"] * 100
    d["gap_vs_prev_high_pct"] = (d["Open"] - d["High"].shift(1)) / d["High"].shift(1) * 100
    d["prev_day_close_pos"] = (
        (d["Close"].shift(1) - d["Low"].shift(1))
        / (d["High"].shift(1) - d["Low"].shift(1) + 1e-9)
    )
    d["ret_5d_pct"] = (d["Open"] - d["Close"].shift(5)) / d["Close"].shift(5) * 100
    d["ret_20d_pct"] = (d["Open"] - d["Close"].shift(20)) / d["Close"].shift(20) * 100

    # ── moving averages (built on prior closes) ───────────────────────────────
    d["daily_ma20"] = d["Close"].rolling(20, min_periods=10).mean()
    d["daily_ma50"] = d["Close"].rolling(50, min_periods=20).mean()
    d["daily_ma200"] = d["Close"].rolling(200, min_periods=100).mean()
    d["daily_ma20_dist_pct"] = (d["Open"] - d["daily_ma20"]) / d["daily_ma20"] * 100
    d["daily_ma50_dist_pct"] = (d["Open"] - d["daily_ma50"]) / d["daily_ma50"] * 100
    d["daily_ma200_dist_pct"] = (d["Open"] - d["daily_ma200"]) / d["daily_ma200"] * 100

    # ma_stack: how many MAs the prior close is above (0-3)
    above_ma20 = (d["Close"].shift(1) > d["daily_ma20"]).astype(int)
    above_ma50 = (d["Close"].shift(1) > d["daily_ma50"]).astype(int)
    above_ma200 = (d["Close"].shift(1) > d["daily_ma200"]).astype(int)
    d["ma_stack"] = above_ma20 + above_ma50 + above_ma200

    # ── RSI(14) on prior close ────────────────────────────────────────────────
    d["rsi_14"] = _rsi(d["Close"]).shift(1)

    # ── Bollinger Bands — prior-close bands, today open position ─────────────
    bb_mid = d["Close"].rolling(20, min_periods=10).mean()
    bb_std = d["Close"].rolling(20, min_periods=10).std()
    bb_upper = (bb_mid + 2 * bb_std).shift(1)
    bb_lower = (bb_mid - 2 * bb_std).shift(1)
    d["bb_position"] = (d["Open"] - bb_lower) / (bb_upper - bb_lower + 1e-9)
    # >1.0 = above upper band (overbought), <0 = below lower band (oversold), 0.5 = mid

    # ── MACD histogram on prior close ────────────────────────────────────────
    ema12 = d["Close"].ewm(span=12, min_periods=12).mean()
    ema26 = d["Close"].ewm(span=26, min_periods=26).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, min_periods=9).mean()
    d["macd_hist"] = (macd_line - signal_line).shift(1)

    # ── volatility / range ────────────────────────────────────────────────────
    true_range = pd.concat([
        d["High"] - d["Low"],
        (d["High"] - d["Close"].shift(1)).abs(),
        (d["Low"] - d["Close"].shift(1)).abs(),
    ], axis=1).max(axis=1)
    d["atr_20d"] = true_range.rolling(20, min_periods=5).mean().shift(1)

    # ── volume (prior-day — no lookahead) ─────────────────────────────────────
    vol_20d_avg = d["Volume"].rolling(20, min_periods=5).mean().shift(1)
    d["prev_day_vol_ratio"] = d["Volume"].shift(1) / vol_20d_avg

    # ── consecutive streak through prior close ────────────────────────────────
    d["consec_streak"] = _consec_streak(d["Close"]).shift(1)

    # ── 52-week high/low through prior day ────────────────────────────────────
    d["high_52w"] = d["High"].rolling(252, min_periods=60).max().shift(1)
    d["low_52w"] = d["Low"].rolling(252, min_periods=60).min().shift(1)
    d["dist_52w_high_pct"] = (d["Open"] - d["high_52w"]) / d["high_52w"] * 100
    d["dist_52w_low_pct"] = (d["Open"] - d["low_52w"]) / d["low_52w"] * 100

    return d


def _compute_or_features(row, daily_features: pd.DataFrame) -> dict:
    """Merge trade-row OR features with daily features for the signal date."""
    entry = float(row["entry_price"])
    or_high = float(row["or_high"])
    or_low = float(row["or_low"])
    or_range = or_high - or_low
    midpoint = (or_high + or_low) / 2

    entry_vs_mid_pct = abs(entry - midpoint) / midpoint * 100 if midpoint else 0.0
    or_range_pct = or_range / entry * 100 if entry else 0.0

    raw_ratio = row.get("or_vol_ratio")
    or_vol_ratio = (
        float(raw_ratio)
        if raw_ratio is not None and not (isinstance(raw_ratio, float) and np.isnan(raw_ratio))
        else 1.0
    )

    ma20 = float(row.get("ma20", np.nan))
    ma200 = float(row.get("ma200", np.nan))
    ma20_dist_pct = (entry - ma20) / ma20 * 100 if ma20 and not np.isnan(ma20) else np.nan
    ma200_dist_pct = (entry - ma200) / ma200 * 100 if ma200 and not np.isnan(ma200) else np.nan

    ts = pd.Timestamp(row["date"])
    nan_daily = {k: np.nan for k in [
        "gap_pct", "gap_vs_prev_high_pct", "prev_day_close_pos",
        "ret_5d_pct", "ret_20d_pct",
        "daily_ma20_dist_pct", "daily_ma50_dist_pct", "daily_ma200_dist_pct",
        "ma_stack", "rsi_14", "bb_position", "macd_hist",
        "atr_ratio", "prev_day_vol_ratio", "consec_streak",
        "dist_52w_high_pct", "dist_52w_low_pct",
    ]}

    if daily_features.empty or ts not in daily_features.index:
        feat = nan_daily
    else:
        r = daily_features.loc[ts]
        atr = _safe(r["atr_20d"])
        feat = {
            "gap_pct":              _safe(r["gap_pct"]),
            "gap_vs_prev_high_pct": _safe(r["gap_vs_prev_high_pct"]),
            "prev_day_close_pos":   _safe(r["prev_day_close_pos"]),
            "ret_5d_pct":           _safe(r["ret_5d_pct"]),
            "ret_20d_pct":          _safe(r["ret_20d_pct"]),
            "daily_ma20_dist_pct":  _safe(r["daily_ma20_dist_pct"]),
            "daily_ma50_dist_pct":  _safe(r["daily_ma50_dist_pct"]),
            "daily_ma200_dist_pct": _safe(r["daily_ma200_dist_pct"]),
            "ma_stack":             _safe(r["ma_stack"]),
            "rsi_14":               _safe(r["rsi_14"]),
            "bb_position":          _safe(r["bb_position"]),
            "macd_hist":            _safe(r["macd_hist"]),
            "atr_ratio":            or_range / atr if atr and atr > 0 and not np.isnan(atr) else np.nan,
            "prev_day_vol_ratio":   _safe(r["prev_day_vol_ratio"]),
            "consec_streak":        _safe(r["consec_streak"]),
            "dist_52w_high_pct":    _safe(r["dist_52w_high_pct"]),
            "dist_52w_low_pct":     _safe(r["dist_52w_low_pct"]),
        }

    def _r(v):
        return round(v, 3) if v is not None and not (isinstance(v, float) and np.isnan(v)) else np.nan

    return {
        "entry_vs_mid_pct": _r(entry_vs_mid_pct),
        "or_range_pct":     _r(or_range_pct),
        "or_vol_ratio":     round(or_vol_ratio, 4),
        "ma20_dist_pct":    _r(ma20_dist_pct),
        "ma200_dist_pct":   _r(ma200_dist_pct),
        **{k: _r(v) for k, v in feat.items()},
    }


def _build_signal_features(tickers, eval_start: date, eval_end: date, all_bars: dict) -> pd.DataFrame:
    daily_feats = {
        ticker: _build_daily_features(bars)
        for ticker, bars in all_bars.items()
        if bars is not None and not bars.empty
    }

    records = []
    for ticker in tickers:
        bars = all_bars.get(ticker)
        if bars is None or bars.empty:
            continue
        try:
            results = compute_signals_with_backtest(
                bars,
                opening_bars=OPENING_BARS,
                opening_start_time=OPENING_START,
                stop_pct=STOP_PCT,
            )
        except Exception as e:
            print(f"  Warning: backtest failed for {ticker}: {e}")
            continue
        if results.empty:
            continue

        primary = results[
            (~results["is_reversal"])
            & (~results["is_bearish_reentry"])
            & (~results["is_bullish_reentry"])
        ].copy()
        primary = primary[(primary["date"] >= eval_start) & (primary["date"] <= eval_end)]

        ticker_daily = daily_feats.get(ticker, pd.DataFrame())
        for _, row in primary.iterrows():
            pnl_pct = row["pnl"] / row["entry_price"] * 100 if row["entry_price"] else 0.0
            records.append({
                "date": row["date"],
                "ticker": ticker,
                "signal": row["signal"],
                "actual_pnl_pct": round(pnl_pct, 4),
                "success": bool(row["success"]),
                "exit_reason": row["exit_reason"],
                "bars_held": int(row["bars_held"]),
                **_compute_or_features(row, ticker_daily),
            })

    return pd.DataFrame(records)


def _label_oracle_ranks(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["oracle_rank"] = (
        df.groupby("date")["actual_pnl_pct"]
        .rank(method="first", ascending=False)
        .astype(int)
    )
    df["is_oracle_pick"] = df["oracle_rank"] <= 2
    return df


# ── feature registry ─────────────────────────────────────────────────────────

FEATURES = [
    # OR signals
    "entry_vs_mid_pct",
    "or_range_pct",
    "or_vol_ratio",
    "ma20_dist_pct",
    "ma200_dist_pct",
    # momentum / gap
    "gap_pct",
    "gap_vs_prev_high_pct",
    "prev_day_close_pos",
    "ret_5d_pct",
    "ret_20d_pct",
    # daily MA structure
    "daily_ma20_dist_pct",
    "daily_ma50_dist_pct",
    "daily_ma200_dist_pct",
    "ma_stack",
    # classic indicators
    "rsi_14",
    "bb_position",
    "macd_hist",
    # volatility / volume
    "atr_ratio",
    "prev_day_vol_ratio",
    # pattern
    "consec_streak",
    "dist_52w_high_pct",
    "dist_52w_low_pct",
]

FEATURE_LABELS = {
    "entry_vs_mid_pct":     "Entry vs OR midpoint (%)",
    "or_range_pct":         "OR range / entry price (%)",
    "or_vol_ratio":         "OR volume vs 20d avg (ratio)",
    "ma20_dist_pct":        "Entry vs 5min MA20 (%)",
    "ma200_dist_pct":       "Entry vs 5min MA200 (%)",
    "gap_pct":              "Gap from prior close (%)",
    "gap_vs_prev_high_pct": "Open vs prev day high (%)",
    "prev_day_close_pos":   "Prev day close position (0-1)",
    "ret_5d_pct":           "5-day return to open (%)",
    "ret_20d_pct":          "20-day return to open (%)",
    "daily_ma20_dist_pct":  "Open vs daily MA20 (%)",
    "daily_ma50_dist_pct":  "Open vs daily MA50 (%)",
    "daily_ma200_dist_pct": "Open vs daily MA200 (%)",
    "ma_stack":             "MAs prev close is above (0-3)",
    "rsi_14":               "RSI(14) prior close",
    "bb_position":          "Bollinger Band position (0-1)",
    "macd_hist":            "MACD histogram prior close",
    "atr_ratio":            "OR range / 20d ATR",
    "prev_day_vol_ratio":   "Prev day vol vs 20d avg",
    "consec_streak":        "Consecutive up(+)/down(-) days",
    "dist_52w_high_pct":    "Open vs 52w high (%)",
    "dist_52w_low_pct":     "Open vs 52w low (%)",
}


# ── output helpers ────────────────────────────────────────────────────────────

def _pct_positive(series):
    return f"{(series > 0).mean() * 100:.0f}%"


def _print_summary(df: pd.DataFrame):
    oracle = df[df["is_oracle_pick"]]
    rest = df[~df["is_oracle_pick"]]
    total_days = df["date"].nunique()
    print(f"\n{'━'*60}")
    print(f"  DATASET SUMMARY")
    print(f"{'━'*60}")
    print(f"  Trading days analyzed : {total_days}")
    print(f"  Total signal rows     : {len(df)}")
    print(f"  Oracle picks (top-2)  : {len(oracle)}  WR {oracle['success'].mean()*100:.0f}%  avg P&L {oracle['actual_pnl_pct'].mean():+.3f}%")
    print(f"  Rest of pool          : {len(rest)}  WR {rest['success'].mean()*100:.0f}%  avg P&L {rest['actual_pnl_pct'].mean():+.3f}%")
    print(f"  Avg tickers/day       : {len(df)/total_days:.1f}")
    print(f"  BULLISH signals       : {(df['signal']=='BULLISH').sum()}  ({(df['signal']=='BULLISH').mean()*100:.0f}%)")
    print(f"  BEARISH signals       : {(df['signal']=='BEARISH').sum()}  ({(df['signal']=='BEARISH').mean()*100:.0f}%)")
    print(f"{'━'*60}")


def _print_feature_table(df: pd.DataFrame):
    oracle = df[df["is_oracle_pick"]]
    rest = df[~df["is_oracle_pick"]]
    print(f"\n{'━'*95}")
    print(f"  FEATURE COMPARISON  Oracle top-2 vs rest-of-pool  (n={len(oracle)} oracle, n={len(rest)} rest)")
    print(f"{'━'*95}")
    print(f"  {'Feature':<38}  {'Oracle':>8}  {'Rest':>8}  {'Δ':>8}  {'Ora %+':>7}  {'Rst %+':>7}")
    print(f"  {'-'*38}  {'-'*8}  {'-'*8}  {'-'*8}  {'-'*7}  {'-'*7}")

    rows = []
    for feat in FEATURES:
        o_col = oracle[feat].dropna()
        r_col = rest[feat].dropna()
        if o_col.empty or r_col.empty:
            continue
        o_mean = o_col.mean()
        r_mean = r_col.mean()
        delta = o_mean - r_mean
        rows.append((feat, o_mean, r_mean, delta, _pct_positive(o_col), _pct_positive(r_col)))

    rows.sort(key=lambda x: abs(x[3]), reverse=True)
    for feat, o_mean, r_mean, delta, o_pos, r_pos in rows:
        label = FEATURE_LABELS.get(feat, feat)
        sign = "+" if delta >= 0 else ""
        print(f"  {label:<38}  {o_mean:>+8.3f}  {r_mean:>+8.3f}  {sign}{delta:>7.3f}  {o_pos:>7}  {r_pos:>7}")
    print(f"{'━'*95}")


def _print_distribution_breakdown(df: pd.DataFrame):
    oracle = df[df["is_oracle_pick"]]
    near = df[(df["oracle_rank"] >= 3) & (df["oracle_rank"] <= 5)]
    far = df[df["oracle_rank"] > 5]
    print(f"\n{'━'*72}")
    print(f"  THREE-WAY SPLIT  (oracle top-2 / rank 3-5 / rank 6+)")
    print(f"{'━'*72}")
    print(f"  {'Feature':<38}  {'Top-2':>7}  {'Rank3-5':>7}  {'Rank6+':>7}")
    print(f"  {'-'*38}  {'-'*7}  {'-'*7}  {'-'*7}")
    for feat in FEATURES:
        o_m = oracle[feat].dropna().mean()
        n_m = near[feat].dropna().mean()
        f_m = far[feat].dropna().mean()
        label = FEATURE_LABELS.get(feat, feat)
        print(f"  {label:<38}  {o_m:>+7.3f}  {n_m:>+7.3f}  {f_m:>+7.3f}")
    print(f"{'━'*72}")


def _print_bull_bear_split(df: pd.DataFrame):
    oracle = df[df["is_oracle_pick"]]
    bull = oracle[oracle["signal"] == "BULLISH"]
    bear = oracle[oracle["signal"] == "BEARISH"]
    rest_bull = df[(~df["is_oracle_pick"]) & (df["signal"] == "BULLISH")]
    rest_bear = df[(~df["is_oracle_pick"]) & (df["signal"] == "BEARISH")]
    print(f"\n{'━'*95}")
    print(f"  SIGNAL DIRECTION SPLIT  (oracle picks only)")
    print(f"{'━'*95}")
    print(f"  Oracle: BULLISH={len(bull)}  BEARISH={len(bear)}    Rest: BULLISH={len(rest_bull)}  BEARISH={len(rest_bear)}")
    print(f"\n  {'Feature':<38}  {'Ora BUL':>8}  {'Rst BUL':>8}  {'Ora BEA':>8}  {'Rst BEA':>8}")
    print(f"  {'-'*38}  {'-'*8}  {'-'*8}  {'-'*8}  {'-'*8}")
    key_feats = [
        "entry_vs_mid_pct", "or_range_pct", "or_vol_ratio",
        "gap_pct", "gap_vs_prev_high_pct", "prev_day_close_pos",
        "ret_5d_pct", "rsi_14", "bb_position", "macd_hist",
        "daily_ma50_dist_pct", "ma_stack", "prev_day_vol_ratio",
        "consec_streak", "dist_52w_high_pct",
    ]
    for feat in key_feats:
        label = FEATURE_LABELS.get(feat, feat)
        ob = bull[feat].dropna().mean()
        rb = rest_bull[feat].dropna().mean()
        oe = bear[feat].dropna().mean()
        re = rest_bear[feat].dropna().mean()
        print(f"  {label:<38}  {ob:>+8.3f}  {rb:>+8.3f}  {oe:>+8.3f}  {re:>+8.3f}")
    print(f"{'━'*95}")


def _print_top_oracle_days(df: pd.DataFrame, n: int = 25):
    picks = df[df["is_oracle_pick"]].copy().sort_values("actual_pnl_pct", ascending=False).head(n)
    print(f"\n{'━'*115}")
    print(f"  TOP {n} ORACLE PICKS BY ACTUAL P&L%")
    print(f"{'━'*115}")
    print(f"  {'Date':<12} {'Tkr':<5} {'Sig':<8} {'P&L%':>6}  {'EntMid':>6}  {'ORrng':>5}  "
          f"{'VRat':>5}  {'RSI':>5}  {'BB':>5}  {'MA_stk':>6}  {'Gap':>5}  "
          f"{'5dRet':>6}  {'52wHi':>6}  {'Streak':>6}  {'PdVol':>6}")
    print(f"  {'-'*115}")
    for _, r in picks.iterrows():
        def _f(v, fmt="+6.2f"):
            try:
                return format(float(v), fmt) if not np.isnan(float(v)) else "  nan"
            except Exception:
                return "  nan"
        print(
            f"  {str(r['date']):<12} {r['ticker']:<5} {r['signal']:<8} {_f(r['actual_pnl_pct'])}"
            f"  {_f(r['entry_vs_mid_pct'])}  {_f(r['or_range_pct'], '+5.2f')}"
            f"  {_f(r['or_vol_ratio'], '+5.2f')}  {_f(r['rsi_14'], '+5.1f')}"
            f"  {_f(r['bb_position'], '+5.2f')}  {_f(r['ma_stack'], '+6.0f')}"
            f"  {_f(r['gap_pct'], '+5.2f')}  {_f(r['ret_5d_pct'], '+6.2f')}"
            f"  {_f(r['dist_52w_high_pct'], '+6.2f')}  {_f(r['consec_streak'], '+6.0f')}"
            f"  {_f(r['prev_day_vol_ratio'], '+6.2f')}"
        )
    print(f"{'━'*115}")


def _print_bottom_oracle_days(df: pd.DataFrame, n: int = 15):
    losers = df[df["is_oracle_pick"] & (~df["success"])].copy().sort_values("actual_pnl_pct").head(n)
    if losers.empty:
        return
    print(f"\n{'━'*110}")
    print(f"  WORST ORACLE PICKS (oracle top-2 that still lost)")
    print(f"{'━'*110}")
    print(f"  {'Date':<12} {'Tkr':<5} {'Sig':<8} {'P&L%':>6}  {'RSI':>5}  {'BB':>5}  "
          f"{'MA_stk':>6}  {'Gap':>5}  {'5dRet':>6}  {'52wHi':>6}  {'Streak':>6}  {'Exit'}")
    print(f"  {'-'*110}")
    for _, r in losers.iterrows():
        def _f(v, fmt="+6.2f"):
            try:
                return format(float(v), fmt) if not np.isnan(float(v)) else "   nan"
            except Exception:
                return "   nan"
        print(
            f"  {str(r['date']):<12} {r['ticker']:<5} {r['signal']:<8} {_f(r['actual_pnl_pct'])}"
            f"  {_f(r['rsi_14'], '+5.1f')}  {_f(r['bb_position'], '+5.2f')}"
            f"  {_f(r['ma_stack'], '+6.0f')}  {_f(r['gap_pct'], '+5.2f')}"
            f"  {_f(r['ret_5d_pct'], '+6.2f')}  {_f(r['dist_52w_high_pct'], '+6.2f')}"
            f"  {_f(r['consec_streak'], '+6.0f')}  {r['exit_reason']}"
        )
    print(f"{'━'*110}")


def main():
    parser = argparse.ArgumentParser(description="Oracle picker feature analysis")
    parser.add_argument("--start", default="2026-01-01")
    parser.add_argument("--end", default="2026-05-23")
    parser.add_argument("--tickers", nargs="+", default=DEFAULT_TICKERS)
    parser.add_argument("--dump-csv", help="Write full feature CSV to this path")
    args = parser.parse_args()

    eval_start = date.fromisoformat(args.start)
    eval_end = date.fromisoformat(args.end)
    fetch_start = eval_start - timedelta(days=LOOKBACK_DAYS)

    print(f"Fetching bars for {len(args.tickers)} tickers ({fetch_start} → {eval_end})...")
    all_bars = fetch_bars(args.tickers, fetch_start, eval_end, source=SOURCE, feed=FEED)

    print("Building signal feature vectors...")
    df = _build_signal_features(args.tickers, eval_start, eval_end, all_bars)

    if df.empty:
        print("No signals found.")
        return

    df = _label_oracle_ranks(df)

    _print_summary(df)
    _print_feature_table(df)
    _print_distribution_breakdown(df)
    _print_bull_bear_split(df)
    _print_top_oracle_days(df, n=25)
    _print_bottom_oracle_days(df, n=15)

    if args.dump_csv:
        df.to_csv(args.dump_csv, index=False)
        print(f"\nFull feature table written to {args.dump_csv}")


if __name__ == "__main__":
    main()

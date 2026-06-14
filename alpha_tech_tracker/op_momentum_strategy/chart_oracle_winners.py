"""
Generate candlestick charts for oracle winning trades (>= min_pnl_pct).

For each trade:
  - Top panel : daily chart (60 days context), MA20/MA50/MA200, entry/exit day marked
  - Bottom panel : 5-min chart (full trading day), MA20/MA200 (5-min rolling),
                   entry bar and exit bar labelled

Usage:
  PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker \
    python alpha_tech_tracker/op_momentum_strategy/chart_oracle_winners.py \
    --csv /tmp/may2026_oracle.csv \
    --min-pnl 0.5 \
    --out-dir /tmp/oracle_charts_may2026
"""

import argparse
import os
import sys
from datetime import date, timedelta

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import mplfinance as mpf
import numpy as np
import pandas as pd
from alpaca.data.enums import DataFeed

sys.path.insert(0, '/Users/victorhuang/work/alpha_tech_tracker')
from alpha_tech_tracker.op_momentum_strategy.op_momentum_backtest import fetch_bars

OPENING_BARS = 3
OPENING_START_HOUR = 9
OPENING_START_MIN = 30

# bars 0,1,2 = 9:30,9:35,9:40  →  entry is bar index 3 = 9:45
ENTRY_BAR_OFFSET = OPENING_BARS


def _entry_time(trade_date: date):
    """9:45 AM ET on the trade date."""
    return pd.Timestamp(trade_date).tz_localize("America/New_York").replace(
        hour=9, minute=45
    )


def _daily_bars(bars_5min: pd.DataFrame) -> pd.DataFrame:
    mh = bars_5min.between_time("09:30", "16:00")
    daily = mh.resample("D").agg(
        Open=("Open", "first"),
        High=("High", "max"),
        Low=("Low", "min"),
        Close=("Close", "last"),
        Volume=("Volume", "sum"),
    ).dropna(subset=["Close"])
    daily.index = daily.index.tz_localize(None)
    return daily


def _compute_daily_mas(daily: pd.DataFrame) -> pd.DataFrame:
    daily = daily.copy()
    daily["MA20"] = daily["Close"].rolling(20, min_periods=5).mean()
    daily["MA50"] = daily["Close"].rolling(50, min_periods=20).mean()
    daily["MA200"] = daily["Close"].rolling(200, min_periods=80).mean()
    return daily


def _compute_5min_mas(bars: pd.DataFrame) -> pd.DataFrame:
    bars = bars.copy()
    bars["MA20"] = bars["Close"].rolling(20, min_periods=5).mean()
    bars["MA200"] = bars["Close"].rolling(200, min_periods=50).mean()
    return bars


def _chart_trade(trade: pd.Series, bars_5min: pd.DataFrame, out_dir: str):
    ticker = trade["ticker"]
    signal = trade["signal"]
    trade_date = pd.Timestamp(trade["date"]).date()
    pnl_pct = trade["actual_pnl_pct"]
    bars_held = int(trade["bars_held"])
    exit_reason = trade["exit_reason"]

    # ── 5-min slice for the trade day ────────────────────────────────────────
    day_start = pd.Timestamp(trade_date).tz_localize("America/New_York").replace(hour=9, minute=30)
    day_end = pd.Timestamp(trade_date).tz_localize("America/New_York").replace(hour=16, minute=0)
    intraday = bars_5min[(bars_5min.index >= day_start) & (bars_5min.index <= day_end)].copy()

    if intraday.empty:
        print(f"  [skip] no intraday bars for {ticker} {trade_date}")
        return

    intraday_with_ma = _compute_5min_mas(bars_5min[bars_5min.index <= day_end]).copy()
    intraday_with_ma = intraday_with_ma[(intraday_with_ma.index >= day_start) & (intraday_with_ma.index <= day_end)]

    # locate entry and exit bar indices in intraday slice
    entry_ts = _entry_time(trade_date)
    intraday_reset = intraday_with_ma.reset_index()
    entry_iloc = None
    for i, ts in enumerate(intraday_with_ma.index):
        if ts >= entry_ts:
            entry_iloc = i
            break
    if entry_iloc is None:
        print(f"  [skip] entry bar not found for {ticker} {trade_date}")
        return
    exit_iloc = min(entry_iloc + bars_held - 1, len(intraday_with_ma) - 1)

    entry_price = float(intraday_with_ma.iloc[entry_iloc]["Open"])
    exit_price = float(intraday_with_ma.iloc[exit_iloc]["Close"])

    # ── daily slice: 60-day context ending on trade date ─────────────────────
    all_daily = _compute_daily_mas(_daily_bars(bars_5min))
    trade_date_ts = pd.Timestamp(trade_date)
    daily_end_mask = all_daily.index <= trade_date_ts
    daily_context = all_daily[daily_end_mask].tail(60).copy()

    if daily_context.empty:
        print(f"  [skip] no daily bars for {ticker} {trade_date}")
        return

    # ── figure layout: 2 rows ─────────────────────────────────────────────────
    direction_color = "#1a7a1a" if signal == "BULLISH" else "#aa0000"
    title = (
        f"{ticker}  {trade_date}  {signal}  P&L {pnl_pct:+.2f}%  "
        f"({bars_held} bars,  exit: {exit_reason})"
    )
    fig = plt.figure(figsize=(18, 12))
    fig.suptitle(title, fontsize=13, fontweight="bold", color=direction_color)

    gs = fig.add_gridspec(2, 1, hspace=0.35, height_ratios=[1, 1])
    ax_daily = fig.add_subplot(gs[0])
    ax_5min = fig.add_subplot(gs[1])

    # ── daily chart ──────────────────────────────────────────────────────────
    _plot_candlestick(ax_daily, daily_context, title="Daily (60-day context)")

    # MA overlays on daily
    for col, color, lw in [("MA20", "#1f77b4", 1.2), ("MA50", "#ff7f0e", 1.2), ("MA200", "#9467bd", 1.2)]:
        valid = daily_context[col].dropna()
        if not valid.empty:
            ax_daily.plot(range(len(daily_context)), daily_context[col].values,
                          color=color, linewidth=lw, label=col, zorder=3)

    # mark the trade day on daily chart
    trade_iloc_daily = daily_context.index.get_loc(trade_date_ts) if trade_date_ts in daily_context.index else None
    if trade_iloc_daily is not None:
        ylo = daily_context.iloc[trade_iloc_daily]["Low"] * 0.995
        yhi = daily_context.iloc[trade_iloc_daily]["High"] * 1.005
        ax_daily.axvline(trade_iloc_daily, color=direction_color, linewidth=1.5, linestyle="--", alpha=0.7, zorder=4)
        ax_daily.annotate("trade day", xy=(trade_iloc_daily, yhi),
                          xytext=(trade_iloc_daily + 0.5, yhi * 1.003),
                          fontsize=7, color=direction_color)

    ax_daily.legend(loc="upper left", fontsize=8, framealpha=0.7)
    _set_xticks_dates(ax_daily, daily_context.index)

    # ── 5-min chart ──────────────────────────────────────────────────────────
    _plot_candlestick(ax_5min, intraday_with_ma, title=f"5-min intraday  {trade_date}")

    # MA overlays on 5-min
    ax_5min.plot(range(len(intraday_with_ma)), intraday_with_ma["MA20"].values,
                 color="#1f77b4", linewidth=1.0, label="MA20 (5m)", zorder=3)
    ax_5min.plot(range(len(intraday_with_ma)), intraday_with_ma["MA200"].values,
                 color="#9467bd", linewidth=1.0, label="MA200 (5m)", zorder=3)

    # OR box (first 3 bars)
    if len(intraday_with_ma) >= OPENING_BARS:
        or_hi = intraday_with_ma.iloc[:OPENING_BARS]["High"].max()
        or_lo = intraday_with_ma.iloc[:OPENING_BARS]["Low"].min()
        ax_5min.axhspan(or_lo, or_hi, xmin=0, xmax=OPENING_BARS / len(intraday_with_ma),
                        color="#aaaaaa", alpha=0.15, zorder=1)
        ax_5min.axhline(y=(or_hi + or_lo) / 2, color="#888888", linewidth=0.8,
                        linestyle=":", alpha=0.6, zorder=2)

    # entry marker
    entry_y = intraday_with_ma.iloc[entry_iloc]["Open"]
    ax_5min.annotate(
        f"ENTRY\n{entry_price:.2f}",
        xy=(entry_iloc, entry_y),
        xytext=(entry_iloc + 1, entry_y * (1.005 if signal == "BULLISH" else 0.995)),
        fontsize=7, color="#006600" if signal == "BULLISH" else "#880000",
        fontweight="bold",
        arrowprops=dict(arrowstyle="->", color="#006600" if signal == "BULLISH" else "#880000", lw=1.2),
    )

    # exit marker
    exit_y = intraday_with_ma.iloc[exit_iloc]["Close"]
    ax_5min.annotate(
        f"EXIT\n{exit_price:.2f}\n{pnl_pct:+.2f}%",
        xy=(exit_iloc, exit_y),
        xytext=(max(exit_iloc - 4, 0), exit_y * (1.008 if signal == "BULLISH" else 0.992)),
        fontsize=7, color="#aa0000" if signal == "BULLISH" else "#004488",
        fontweight="bold",
        arrowprops=dict(arrowstyle="->", color="#aa0000" if signal == "BULLISH" else "#004488", lw=1.2),
    )

    ax_5min.legend(loc="upper left", fontsize=8, framealpha=0.7)
    _set_xticks_times(ax_5min, intraday_with_ma.index)

    fname = f"{ticker}_{trade_date}_{signal}_{pnl_pct:+.2f}pct.png".replace("+", "p").replace("-", "n")
    out_path = os.path.join(out_dir, fname)
    fig.savefig(out_path, dpi=120, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  saved: {out_path}")


def _plot_candlestick(ax, df: pd.DataFrame, title: str = ""):
    """Draw OHLCV candlesticks on ax using integer x-axis."""
    ax.set_title(title, fontsize=9, loc="left", pad=4)
    ax.set_facecolor("#fafafa")
    n = len(df)
    width = 0.6
    for i, (_, row) in enumerate(df.iterrows()):
        o, h, l, c = float(row["Open"]), float(row["High"]), float(row["Low"]), float(row["Close"])
        color = "#2ca02c" if c >= o else "#d62728"
        ax.plot([i, i], [l, h], color=color, linewidth=0.8, zorder=2)
        ax.add_patch(plt.Rectangle(
            (i - width / 2, min(o, c)), width, abs(c - o),
            facecolor=color, edgecolor=color, linewidth=0.3, zorder=2,
        ))
    ax.set_xlim(-0.5, n - 0.5)
    ax.grid(axis="y", color="#e0e0e0", linewidth=0.5, zorder=0)
    ax.tick_params(axis="both", labelsize=7)


def _set_xticks_dates(ax, index, max_ticks=10):
    n = len(index)
    step = max(1, n // max_ticks)
    ticks = list(range(0, n, step))
    labels = [str(index[i].date()) for i in ticks]
    ax.set_xticks(ticks)
    ax.set_xticklabels(labels, rotation=30, ha="right", fontsize=7)


def _set_xticks_times(ax, index, max_ticks=12):
    n = len(index)
    step = max(1, n // max_ticks)
    ticks = list(range(0, n, step))
    labels = [index[i].strftime("%H:%M") for i in ticks]
    ax.set_xticks(ticks)
    ax.set_xticklabels(labels, rotation=0, ha="center", fontsize=7)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", default="/tmp/may2026_oracle.csv")
    parser.add_argument("--min-pnl", type=float, default=0.5)
    parser.add_argument("--out-dir", default="/tmp/oracle_charts_may2026")
    args = parser.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)

    df = pd.read_csv(args.csv)
    winners = df[df["is_oracle_pick"] & (df["actual_pnl_pct"] >= args.min_pnl)].copy()
    winners = winners.sort_values("actual_pnl_pct", ascending=False)
    print(f"Charting {len(winners)} oracle trades >= {args.min_pnl:+.1f}%\n")

    tickers = winners["ticker"].unique().tolist()
    min_trade_date = pd.to_datetime(winners["date"]).dt.date.min()
    max_trade_date = pd.to_datetime(winners["date"]).dt.date.max()
    fetch_start = min_trade_date - timedelta(days=400)  # MA200 + 52w warmup
    fetch_end = max_trade_date

    print(f"Loading bar data for: {tickers}")
    all_bars = fetch_bars(tickers, fetch_start, fetch_end, source="alpaca", feed=DataFeed.SIP)

    for _, trade in winners.iterrows():
        ticker = trade["ticker"]
        bars = all_bars.get(ticker)
        if bars is None or bars.empty:
            print(f"  [skip] no bars for {ticker}")
            continue
        print(f"  {ticker} {trade['date']} {trade['signal']} {trade['actual_pnl_pct']:+.2f}%")
        _chart_trade(trade, bars, args.out_dir)

    print(f"\nDone. Charts saved to: {args.out_dir}")


if __name__ == "__main__":
    main()

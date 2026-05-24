"""
Generate candlestick charts for selector backtest trades.

For each trade:
  - Top panel : daily chart (60 days context), MA20/MA50/MA200, entry/exit day marked
  - Bottom panel : 5-min chart (full trading day), MA20/MA200 (5-min rolling),
                   OR box, entry bar and exit bar labelled
  - Reversal sub-trade annotated when present (rev_bars_held > 0)

Usage:
  PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker \
    python alpha_tech_tracker/op_momentum_strategy/chart_selector_trades.py \
    --csv /tmp/jan2025_ma_gate_trades.csv \
    --out-dir /tmp/selector_charts_jan2025

  # Combine into PDF:
    python alpha_tech_tracker/op_momentum_strategy/chart_selector_trades.py \
    --csv /tmp/jan2025_ma_gate_trades.csv \
    --out-dir /tmp/selector_charts_jan2025 \
    --pdf /tmp/selector_charts_jan2025/trades.pdf
"""

import argparse
import os
import sys
from datetime import date, timedelta

import matplotlib.pyplot as plt
import pandas as pd
from alpaca.data.enums import DataFeed

sys.path.insert(0, '/Users/victorhuang/work/alpha_tech_tracker')
from alpha_tech_tracker.op_momentum_strategy.op_momentum_backtest import fetch_bars

OPENING_BARS = 3


def _entry_time(trade_date: date):
    return pd.Timestamp(trade_date).tz_localize("America/New_York").replace(hour=9, minute=45)


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


def _plot_candlestick(ax, df: pd.DataFrame, title: str = ""):
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


def _chart_trade(trade: pd.Series, bars_5min: pd.DataFrame, out_dir: str) -> str:
    ticker = trade["ticker"]
    signal = trade["signal"]
    trade_date = pd.Timestamp(trade["date"]).date()
    pnl_pct = float(trade["pnl_pct"])
    bars_held = int(trade["bars_held"])
    exit_reason = trade["exit_reason"]
    rank = int(trade["rank"])
    score = float(trade.get("score", 0.0))
    window = str(trade.get("window", "M1"))

    # ── 5-min slice for trade day ────────────────────────────────────────────
    day_start = pd.Timestamp(trade_date).tz_localize("America/New_York").replace(hour=9, minute=30)
    day_end = pd.Timestamp(trade_date).tz_localize("America/New_York").replace(hour=16, minute=0)
    intraday = bars_5min[(bars_5min.index >= day_start) & (bars_5min.index <= day_end)].copy()

    if intraday.empty:
        print(f"  [skip] no intraday bars for {ticker} {trade_date}")
        return None

    intraday_with_ma = _compute_5min_mas(bars_5min[bars_5min.index <= day_end]).copy()
    intraday_with_ma = intraday_with_ma[
        (intraday_with_ma.index >= day_start) & (intraday_with_ma.index <= day_end)
    ]

    entry_ts = _entry_time(trade_date)
    entry_iloc = None
    for i, ts in enumerate(intraday_with_ma.index):
        if ts >= entry_ts:
            entry_iloc = i
            break
    if entry_iloc is None:
        print(f"  [skip] entry bar not found for {ticker} {trade_date}")
        return None
    exit_iloc = min(entry_iloc + bars_held - 1, len(intraday_with_ma) - 1)

    entry_price = float(intraday_with_ma.iloc[entry_iloc]["Open"])
    exit_price = float(intraday_with_ma.iloc[exit_iloc]["Close"])

    # reversal sub-trade
    rev_bars_held = int(trade.get("rev_bars_held", 0))
    rev_entry_idx = int(trade.get("rev_entry_idx", 0))
    rev_pnl = float(trade.get("rev_pnl", 0.0))
    has_reversal = rev_bars_held > 0

    # ── daily slice: 60-day context ending on trade date ─────────────────────
    all_daily = _compute_daily_mas(_daily_bars(bars_5min))
    trade_date_ts = pd.Timestamp(trade_date)
    daily_context = all_daily[all_daily.index <= trade_date_ts].tail(60).copy()

    if daily_context.empty:
        print(f"  [skip] no daily bars for {ticker} {trade_date}")
        return None

    # ── figure ───────────────────────────────────────────────────────────────
    direction_color = "#1a7a1a" if signal == "BULLISH" else "#aa0000"
    rev_signal = "BEARISH" if signal == "BULLISH" else "BULLISH"
    rev_note = f"  +REV {rev_signal} {rev_pnl/entry_price*100:+.2f}%" if has_reversal else ""
    title = (
        f"{ticker}  {trade_date}  {signal}  P&L {pnl_pct:+.2f}%{rev_note}  "
        f"({bars_held} bars,  exit: {exit_reason})  "
        f"[{window} rank#{rank} score={score:.3f}]"
    )

    fig = plt.figure(figsize=(18, 12))
    fig.suptitle(title, fontsize=11, fontweight="bold", color=direction_color)

    gs = fig.add_gridspec(2, 1, hspace=0.35, height_ratios=[1, 1])
    ax_daily = fig.add_subplot(gs[0])
    ax_5min = fig.add_subplot(gs[1])

    # ── daily panel ──────────────────────────────────────────────────────────
    _plot_candlestick(ax_daily, daily_context, title="Daily (60-day context)")
    for col, color, lw in [("MA20", "#1f77b4", 1.2), ("MA50", "#ff7f0e", 1.2), ("MA200", "#9467bd", 1.2)]:
        if not daily_context[col].dropna().empty:
            ax_daily.plot(range(len(daily_context)), daily_context[col].values,
                          color=color, linewidth=lw, label=col, zorder=3)

    trade_iloc_daily = daily_context.index.get_loc(trade_date_ts) if trade_date_ts in daily_context.index else None
    if trade_iloc_daily is not None:
        yhi = daily_context.iloc[trade_iloc_daily]["High"] * 1.005
        ax_daily.axvline(trade_iloc_daily, color=direction_color, linewidth=1.5,
                         linestyle="--", alpha=0.7, zorder=4)
        ax_daily.annotate("trade day", xy=(trade_iloc_daily, yhi),
                          xytext=(trade_iloc_daily + 0.5, yhi * 1.003),
                          fontsize=7, color=direction_color)

    ax_daily.legend(loc="upper left", fontsize=8, framealpha=0.7)
    _set_xticks_dates(ax_daily, daily_context.index)

    # ── 5-min panel ──────────────────────────────────────────────────────────
    _plot_candlestick(ax_5min, intraday_with_ma, title=f"5-min intraday  {trade_date}")
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

    # primary entry marker
    e_col = "#006600" if signal == "BULLISH" else "#880000"
    ax_5min.annotate(
        f"ENTRY\n{entry_price:.2f}",
        xy=(entry_iloc, entry_price),
        xytext=(entry_iloc + 1, entry_price * (1.005 if signal == "BULLISH" else 0.995)),
        fontsize=7, color=e_col, fontweight="bold",
        arrowprops=dict(arrowstyle="->", color=e_col, lw=1.2),
    )

    # primary exit marker
    x_col = "#aa0000" if signal == "BULLISH" else "#004488"
    ax_5min.annotate(
        f"EXIT\n{exit_price:.2f}\n{pnl_pct:+.2f}%",
        xy=(exit_iloc, exit_price),
        xytext=(max(exit_iloc - 4, 0), exit_price * (1.008 if signal == "BULLISH" else 0.992)),
        fontsize=7, color=x_col, fontweight="bold",
        arrowprops=dict(arrowstyle="->", color=x_col, lw=1.2),
    )

    # reversal entry/exit markers
    if has_reversal:
        rev_entry_iloc_abs = entry_iloc + rev_entry_idx
        rev_exit_iloc_abs = min(rev_entry_iloc_abs + rev_bars_held - 1, len(intraday_with_ma) - 1)
        if rev_entry_iloc_abs < len(intraday_with_ma):
            rev_e_price = float(intraday_with_ma.iloc[rev_entry_iloc_abs]["Open"])
            rev_x_price = float(intraday_with_ma.iloc[rev_exit_iloc_abs]["Close"])
            rev_e_col = "#006600" if rev_signal == "BULLISH" else "#880000"
            ax_5min.annotate(
                f"REV\n{rev_e_price:.2f}",
                xy=(rev_entry_iloc_abs, rev_e_price),
                xytext=(rev_entry_iloc_abs + 1, rev_e_price * (1.005 if rev_signal == "BULLISH" else 0.995)),
                fontsize=6, color=rev_e_col, fontstyle="italic",
                arrowprops=dict(arrowstyle="->", color=rev_e_col, lw=0.9),
            )
            ax_5min.annotate(
                f"REV EXIT\n{rev_x_price:.2f}",
                xy=(rev_exit_iloc_abs, rev_x_price),
                xytext=(max(rev_exit_iloc_abs - 4, 0), rev_x_price * (1.008 if rev_signal == "BULLISH" else 0.992)),
                fontsize=6, color="#555555", fontstyle="italic",
                arrowprops=dict(arrowstyle="->", color="#555555", lw=0.9),
            )

    ax_5min.legend(loc="upper left", fontsize=8, framealpha=0.7)
    _set_xticks_times(ax_5min, intraday_with_ma.index)

    pnl_sign = "p" if pnl_pct >= 0 else "n"
    fname = f"{trade['date']}_{ticker}_{signal}_rank{rank}_{abs(pnl_pct):.2f}{pnl_sign}pct.png"
    out_path = os.path.join(out_dir, fname)
    fig.savefig(out_path, dpi=120, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  saved: {out_path}")
    return out_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", required=True, help="Path to selector backtest CSV (--csv-out output)")
    parser.add_argument("--out-dir", default="/tmp/selector_charts", help="Directory for chart PNGs")
    parser.add_argument("--pdf", default=None, help="If set, combine all charts into this PDF path")
    parser.add_argument("--feed", default="sip", choices=["sip", "iex"])
    args = parser.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)

    df = pd.read_csv(args.csv)
    trades = df[~df.get("skipped", pd.Series([False] * len(df)))].copy()
    trades = trades.sort_values("date").reset_index(drop=True)
    print(f"Charting {len(trades)} trades\n")

    tickers = trades["ticker"].unique().tolist()
    min_date = pd.to_datetime(trades["date"]).dt.date.min()
    max_date = pd.to_datetime(trades["date"]).dt.date.max()
    fetch_start = min_date - timedelta(days=400)
    fetch_end = max_date

    feed = DataFeed.SIP if args.feed == "sip" else DataFeed.IEX
    print(f"Loading bar data for: {tickers}")
    all_bars = fetch_bars(tickers, fetch_start, fetch_end, source="alpaca", feed=feed)

    chart_paths = []
    for _, trade in trades.iterrows():
        ticker = trade["ticker"]
        bars = all_bars.get(ticker)
        if bars is None or bars.empty:
            print(f"  [skip] no bars for {ticker}")
            continue
        print(f"  {ticker} {trade['date']} {trade['signal']} {trade['pnl_pct']:+.2f}%  rank#{int(trade['rank'])}")
        path = _chart_trade(trade, bars, args.out_dir)
        if path:
            chart_paths.append(path)

    if args.pdf and chart_paths:
        from matplotlib.backends.backend_pdf import PdfPages
        import matplotlib.image as mpimg
        with PdfPages(args.pdf) as pdf:
            for p in chart_paths:
                img = mpimg.imread(p)
                fig, ax = plt.subplots(figsize=(18, 12))
                ax.imshow(img)
                ax.axis("off")
                pdf.savefig(fig, bbox_inches="tight")
                plt.close(fig)
        print(f"\nPDF saved to: {args.pdf}")

    print(f"\nDone. Charts in: {args.out_dir}")


if __name__ == "__main__":
    main()

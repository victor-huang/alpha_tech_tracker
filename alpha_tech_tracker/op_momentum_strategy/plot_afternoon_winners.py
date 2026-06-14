"""
Plot intraday 5-min candlestick charts for A1/A2 trades with bars_held >= 3.
Includes MA20/MA50/MA200, OR bar highlight, entry/exit markers.

Usage:
    PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker \
      python alpha_tech_tracker/op_momentum_strategy/plot_afternoon_winners.py \
        --start 2025-01-01 --end 2025-12-31 \
        --out charts/afternoon_winners_2025.pdf

    PYTHONPATH=... python ... --start 2026-01-01 --end 2026-04-08 \
        --out charts/afternoon_winners_2026.pdf
"""
import argparse
import math
from datetime import date, timedelta
from datetime import datetime as dt
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import mplfinance as mpf
import pandas as pd
import pytz

from alpha_tech_tracker.op_momentum_strategy.op_momentum_backtest import (
    compute_signals_with_backtest,
    fetch_bars,
    build_bearish_regime_dates,
)
from alpha_tech_tracker.op_momentum_strategy.op_momentum_selector import DEFAULT_TICKERS

ET = pytz.timezone("America/New_York")

REGIME_MA = 8
STOP_PCT = 0.15
OR_BAR_LOOKBACK = 3
MIN_BARS_HELD = 3

WINDOWS = [
    {"label": "A1", "opening_start": "13:15", "opening_bars": 1},
    {"label": "A2", "opening_start": "15:00", "opening_bars": 1},
]

CHARTS_PER_PAGE = 3  # candlestick charts are tall — 3 per PDF page


def _collect_trades(tickers, start: date, end: date):
    fetch_start = start - timedelta(days=90)
    print(f"Fetching bars for {len(tickers)} tickers ({start} → {end})...")
    all_bars = fetch_bars(tickers, fetch_start, end, source="alpaca")

    bearish_regime_dates = build_bearish_regime_dates(
        start - timedelta(days=60), end, regime_ma=REGIME_MA
    )

    trades = []
    for win in WINDOWS:
        label = win["label"]
        print(f"Computing signals [{label}] {win['opening_start']} / {win['opening_bars']} bar(s)...")
        for ticker in tickers:
            df = all_bars.get(ticker, pd.DataFrame())
            if df.empty:
                continue
            results = compute_signals_with_backtest(
                df,
                win["opening_bars"],
                stop_pct=STOP_PCT,
                opening_start_time=win["opening_start"],
                trailing_ma="ma20",
                bearish_regime_dates=bearish_regime_dates,
                enable_reversal=True,
                reversal_max_bars_held=3,
                or_bar_lookback=OR_BAR_LOOKBACK,
                enable_bearish_reentry=True,
                enable_bullish_reentry=True,
            )
            if results.empty:
                continue
            mask = (
                (results["date"] >= start)
                & (results["date"] <= end)
                & (results["bars_held"] >= MIN_BARS_HELD)
            )
            for _, row in results[mask].iterrows():
                trades.append(
                    {
                        "window": label,
                        "opening_start": win["opening_start"],
                        "ticker": ticker,
                        "date": row["date"],
                        "signal": row["signal"],
                        "entry_price": row["entry_price"],
                        "exit_price": row["exit_price"],
                        "or_high": row["or_high"],
                        "or_low": row["or_low"],
                        "bars_held": int(row["bars_held"]),
                        "pnl": row["pnl"],
                        "pnl_pct": row["pnl"] / row["entry_price"] * 100,
                        "exit_reason": row["exit_reason"],
                        "success": row["success"],
                        "df": all_bars[ticker],
                    }
                )
    trades.sort(key=lambda t: (t["date"], t["window"], t["ticker"]))
    print(f"Found {len(trades)} trades with bars_held >= {MIN_BARS_HELD}")
    return trades


def _get_day_df(trade: dict) -> pd.DataFrame:
    """Return ET-indexed intraday 5-min bars for the trade date, 9:30–16:00."""
    df = trade["df"]
    trade_date = trade["date"]
    day_df = df[df.index.date == trade_date].copy()
    if day_df.index.tzinfo is None:
        day_df.index = day_df.index.tz_localize("UTC").tz_convert(ET)
    else:
        day_df.index = day_df.index.tz_convert(ET)
    day_df = day_df.between_time("09:30", "16:00")
    return day_df


def _build_chart(trade: dict, ax_candle, ax_vol):
    """Draw candlestick + MA lines + markers onto pre-created axes."""
    day_df = _get_day_df(trade)
    if day_df.empty:
        ax_candle.set_visible(False)
        ax_vol.set_visible(False)
        return

    # ── MA lines (computed over whole history, sliced to today) ──────────────
    full_df = trade["df"].copy()
    if full_df.index.tzinfo is None:
        full_df.index = full_df.index.tz_localize("UTC").tz_convert(ET)
    else:
        full_df.index = full_df.index.tz_convert(ET)
    full_df["MA20"] = full_df["Close"].rolling(20).mean()
    full_df["MA50"] = full_df["Close"].rolling(50).mean()
    full_df["MA200"] = full_df["Close"].rolling(200).mean()

    trade_date = trade["date"]
    today_full = full_df[full_df.index.date == trade_date].between_time("09:30", "16:00")

    ma20 = today_full["MA20"].reindex(day_df.index)
    ma50 = today_full["MA50"].reindex(day_df.index)
    ma200 = today_full["MA200"].reindex(day_df.index)

    # ── OR bar position ───────────────────────────────────────────────────────
    opening_start = trade["opening_start"]
    or_bars = day_df.between_time(opening_start, opening_start)

    # ── candlesticks (manual draw so we can reuse axes) ──────────────────────
    bar_width = pd.Timedelta(minutes=3.5)
    wick_width = pd.Timedelta(seconds=30)

    for ts, row in day_df.iterrows():
        is_up = row["Close"] >= row["Open"]
        color = "#26a69a" if is_up else "#ef5350"  # teal up, red down
        body_bot = min(row["Open"], row["Close"])
        body_top = max(row["Open"], row["Close"])
        body_h = max(body_top - body_bot, 1e-6)

        # body
        ax_candle.bar(ts, body_h, bottom=body_bot, width=bar_width,
                      color=color, edgecolor=color, linewidth=0.3, zorder=3)
        # wick
        ax_candle.bar(ts, row["High"] - row["Low"], bottom=row["Low"],
                      width=wick_width, color=color, zorder=3)

    # ── volume bars ──────────────────────────────────────────────────────────
    for ts, row in day_df.iterrows():
        is_up = row["Close"] >= row["Open"]
        color = "#26a69a" if is_up else "#ef5350"
        ax_vol.bar(ts, row["Volume"], width=bar_width, color=color,
                   alpha=0.6, zorder=2)

    xs = day_df.index.to_pydatetime()

    # ── MA overlays ──────────────────────────────────────────────────────────
    if ma20.notna().any():
        ax_candle.plot(xs, ma20.values, color="#f6c90e", linewidth=0.9,
                       label="MA20", zorder=4)
    if ma50.notna().any():
        ax_candle.plot(xs, ma50.values, color="#3f88c5", linewidth=0.9,
                       label="MA50", zorder=4)
    if ma200.notna().any():
        ax_candle.plot(xs, ma200.values, color="#e040fb", linewidth=0.9,
                       label="MA200", zorder=4)

    # ── OR bar highlight ─────────────────────────────────────────────────────
    if not or_bars.empty:
        or_left = or_bars.index[0].to_pydatetime()
        or_right = (or_bars.index[-1] + pd.Timedelta(minutes=5)).to_pydatetime()
        ax_candle.axvspan(or_left, or_right, alpha=0.18, color="#f39c12",
                          zorder=1, label="OR bar")
        ax_vol.axvspan(or_left, or_right, alpha=0.18, color="#f39c12", zorder=1)

    # ── OR high / low dashed lines ───────────────────────────────────────────
    ax_candle.axhline(trade["or_high"], color="#aaaaaa", linewidth=0.7,
                      linestyle="--", zorder=2)
    ax_candle.axhline(trade["or_low"], color="#aaaaaa", linewidth=0.7,
                      linestyle="--", zorder=2)

    # ── entry / exit horizontal lines ────────────────────────────────────────
    sig_color = "#e74c3c" if trade["signal"] == "BEARISH" else "#27ae60"
    ax_candle.axhline(trade["entry_price"], color=sig_color, linewidth=1.1,
                      linestyle="-", zorder=5)
    ax_candle.axhline(trade["exit_price"], color="#2980b9", linewidth=1.1,
                      linestyle="-", zorder=5)

    # ── entry / exit scatter markers ─────────────────────────────────────────
    post_or = day_df[day_df.index > (or_bars.index[-1] if not or_bars.empty
                                     else day_df.index[0])]
    if not post_or.empty:
        entry_ts = post_or.index[0].to_pydatetime()
        marker = "^" if trade["signal"] == "BULLISH" else "v"
        ax_candle.scatter([entry_ts], [trade["entry_price"]], color=sig_color,
                          s=80, marker=marker, zorder=6)

    exit_idx = trade["bars_held"]
    if not post_or.empty:
        exit_row = post_or.iloc[min(exit_idx, len(post_or) - 1)]
        ax_candle.scatter([exit_row.name.to_pydatetime()], [trade["exit_price"]],
                          color="#2980b9", s=80, marker="X", zorder=6)

    # ── axis formatting ───────────────────────────────────────────────────────
    import matplotlib.dates as mdates
    fmt = mdates.DateFormatter("%H:%M", tz=ET)
    ax_candle.xaxis.set_major_formatter(fmt)
    ax_candle.xaxis.set_major_locator(mdates.HourLocator(interval=1, tz=ET))
    ax_vol.xaxis.set_major_formatter(fmt)
    ax_vol.xaxis.set_major_locator(mdates.HourLocator(interval=1, tz=ET))

    ax_candle.tick_params(axis="both", labelsize=7)
    ax_vol.tick_params(axis="both", labelsize=6)
    ax_vol.yaxis.set_ticklabels([])
    ax_candle.grid(axis="y", linewidth=0.35, alpha=0.4)
    ax_vol.grid(axis="y", linewidth=0.35, alpha=0.3)

    # ── legend ────────────────────────────────────────────────────────────────
    handles = ax_candle.get_legend_handles_labels()
    ax_candle.legend(*handles, fontsize=6, loc="upper left",
                     framealpha=0.65, ncol=3)

    # ── title ─────────────────────────────────────────────────────────────────
    pnl_pct = trade["pnl_pct"]
    pnl_str = f"+{pnl_pct:.2f}%" if pnl_pct >= 0 else f"{pnl_pct:.2f}%"
    win_str = "WIN" if trade["success"] else "LOSS"
    title = (
        f"{trade['ticker']}  {trade['date']}  [{trade['window']} {opening_start}]  "
        f"{trade['signal']}  {pnl_str} ({win_str})  "
        f"{trade['bars_held']} bars  {trade['exit_reason']}"
    )
    ax_candle.set_title(title, fontsize=8, pad=4, fontweight="bold",
                        color="#27ae60" if trade["success"] else "#c0392b")


def plot_trades(trades, out_path: Path):
    from matplotlib.backends.backend_pdf import PdfPages

    out_path.parent.mkdir(parents=True, exist_ok=True)
    n_pages = math.ceil(len(trades) / CHARTS_PER_PAGE)

    # Each chart = 2 subplots (candle + volume), height ratio 4:1
    PANEL_HEIGHTS = [4, 1]
    N_PANELS = len(PANEL_HEIGHTS)

    with PdfPages(out_path) as pdf:
        for page in range(n_pages):
            chunk = trades[page * CHARTS_PER_PAGE: (page + 1) * CHARTS_PER_PAGE]
            n = len(chunk)

            # Build gridspec: CHARTS_PER_PAGE groups × 2 rows each
            fig = plt.figure(figsize=(14, 4.5 * n))
            import matplotlib.gridspec as gridspec
            gs = gridspec.GridSpec(
                n * N_PANELS, 1,
                height_ratios=PANEL_HEIGHTS * n,
                hspace=0.08,
                left=0.06, right=0.97, top=0.97, bottom=0.04,
            )

            for i, trade in enumerate(chunk):
                ax_candle = fig.add_subplot(gs[i * N_PANELS])
                ax_vol = fig.add_subplot(gs[i * N_PANELS + 1], sharex=ax_candle)
                if i < n - 1:
                    plt.setp(ax_candle.get_xticklabels(), visible=False)
                _build_chart(trade, ax_candle, ax_vol)

                # separator line between charts
                if i < n - 1:
                    ax_vol.spines["bottom"].set_linewidth(1.5)

            fig.suptitle(
                f"A1/A2 Winners (bars_held ≥ {MIN_BARS_HELD})  —  page {page + 1}/{n_pages}",
                fontsize=9, y=0.995,
            )
            pdf.savefig(fig, bbox_inches="tight")
            plt.close(fig)
            if (page + 1) % 10 == 0 or page == n_pages - 1:
                print(f"  Page {page + 1}/{n_pages} saved")

    print(f"\nSaved {len(trades)} charts → {out_path}")


def _parse_args():
    parser = argparse.ArgumentParser(description="Plot A1/A2 afternoon winner candlestick charts")
    parser.add_argument("--start", required=True, help="Start date YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="End date YYYY-MM-DD")
    parser.add_argument("--out", default="charts/afternoon_winners.pdf", help="Output PDF path")
    parser.add_argument("--tickers", nargs="+", default=None)
    parser.add_argument(
        "--min-bars", type=int, default=MIN_BARS_HELD,
        help=f"Minimum bars_held to include (default: {MIN_BARS_HELD})"
    )
    parser.add_argument(
        "--top-pct", type=float, default=None,
        help="Keep only the top N%% of trades by P&L (e.g. 20 for top 20%%). Default: all."
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    tickers = args.tickers or DEFAULT_TICKERS
    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)

    trades = _collect_trades(tickers, start, end)
    if not trades:
        print("No qualifying trades found.")
    else:
        if args.top_pct is not None:
            pnl_pcts = sorted(t["pnl_pct"] for t in trades)
            threshold = pnl_pcts[int(len(pnl_pcts) * (1 - args.top_pct / 100))]
            trades = [t for t in trades if t["pnl_pct"] >= threshold]
            trades.sort(key=lambda t: t["pnl_pct"], reverse=True)
            print(f"Top {args.top_pct:.0f}%: {len(trades)} trades (P&L% >= {threshold:.2f}%)")
        plot_trades(trades, Path(args.out))

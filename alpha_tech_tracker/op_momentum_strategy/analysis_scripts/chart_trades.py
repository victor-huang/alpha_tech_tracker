"""
Standard chart template — selector trade charts PDF.

Reads a trade CSV (format: output of op_momentum_selector_backtest.py --csv-out)
and produces a single PDF with one page per trade showing:
  - 5-min candlestick bars for the full session
  - Opening Range (OR) high / low / midpoint lines + OR window shading
  - Entry marker (▲ green = BULLISH, ▼ red = BEARISH) and Exit marker (✕)
  - SMA 20 (blue), SMA 50 (orange), SMA 200 (purple)
  - Volume bars overlaid in the bottom 25% of the chart (twin y-axis)

Usage — edit the two constants at the top of main() to point at your CSV and
date range, then run from the project root:

  PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker \\
    python alpha_tech_tracker/op_momentum_strategy/analysis_scripts/chart_trades.py

Output: charts/<output_name>.pdf
"""
import os
import sys
from datetime import datetime, timedelta

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pytz
from matplotlib.backends.backend_pdf import PdfPages

sys.path.insert(0, "/Users/victorhuang/work/alpha_tech_tracker")

import pandas as pd
from alpaca.data.enums import DataFeed

from alpha_tech_tracker.op_momentum_strategy.op_momentum_backtest import fetch_bars

ET = pytz.timezone("America/New_York")


def load_trades():
    df = pd.read_csv("logs/oracle_compare/may2026_top5_daily.csv")
    df = df[df["skipped"] == False]
    df = df[df["date"] <= "2026-05-08"]
    return df.sort_values(["date", "rank"]).reset_index(drop=True)


def get_bars(ticker, date_str):
    start = datetime.strptime(date_str, "%Y-%m-%d").date()
    result = fetch_bars([ticker], start_date=start, end_date=start,
                        source="alpaca", feed=DataFeed.SIP)
    bars = result.get(ticker)
    if bars is None or bars.empty:
        return None
    df = bars.copy()
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    df.index = df.index.tz_convert(ET)
    open_dt  = ET.localize(datetime.strptime(f"{date_str} 09:30", "%Y-%m-%d %H:%M"))
    close_dt = ET.localize(datetime.strptime(f"{date_str} 16:00", "%Y-%m-%d %H:%M"))
    df = df[(df.index >= open_dt) & (df.index < close_dt)]
    df = df.rename(columns={"open": "Open", "high": "High",
                             "low": "Low", "close": "Close", "volume": "Volume"})
    df["SMA20"]  = df["Close"].rolling(20).mean()
    df["SMA50"]  = df["Close"].rolling(50).mean()
    df["SMA200"] = df["Close"].rolling(200).mean()
    return df


def nearest_bar(bars_index, dt):
    diffs = [(abs((b - dt).total_seconds()), b) for b in bars_index.to_pydatetime()]
    return min(diffs)[1]


def draw_chart(fig, trade, bars):
    ax_price = fig.add_subplot(1, 1, 1)
    ax_vol   = ax_price.twinx()  # volume shares x-axis, separate y-axis on the right

    # ── Volume bars (draw first so candles sit on top) ───────────────────────
    vol_colors = ["#26a69a" if c >= o else "#ef5350"
                  for c, o in zip(bars["Close"], bars["Open"])]
    ax_vol.bar(bars.index, bars["Volume"], color=vol_colors,
               width=timedelta(minutes=4), align="center", alpha=0.25, zorder=1)
    # Scale volume to occupy bottom 25% of chart so it doesn't obscure candles
    ax_vol.set_ylim(0, bars["Volume"].max() * 4)
    ax_vol.set_ylabel("Volume", fontsize=7, color="#888888")
    ax_vol.tick_params(axis="y", labelsize=6, labelcolor="#888888")

    # ── Candlesticks ────────────────────────────────────────────────────────
    for dt, row in bars.iterrows():
        color = "#26a69a" if row["Close"] >= row["Open"] else "#ef5350"
        ax_price.plot([dt, dt], [row["Low"], row["High"]], color=color, linewidth=0.7, zorder=3)
        ax_price.plot([dt, dt], [row["Open"], row["Close"]], color=color, linewidth=3.5, zorder=3)

    # ── SMAs ────────────────────────────────────────────────────────────────
    ax_price.plot(bars.index, bars["SMA20"],  color="#1565C0", lw=1.1, label="SMA20",  zorder=4)
    ax_price.plot(bars.index, bars["SMA50"],  color="#E65100", lw=1.1, label="SMA50",  zorder=4)
    ax_price.plot(bars.index, bars["SMA200"], color="#6A1B9A", lw=1.1, label="SMA200", zorder=4)

    # ── OR range ────────────────────────────────────────────────────────────
    or_high = trade["or_high"]
    or_low  = trade["or_low"]
    mid     = trade["midpoint"]
    or_end_dt = ET.localize(datetime.strptime(f"{trade['date']} 09:45", "%Y-%m-%d %H:%M"))
    ax_price.axvspan(bars.index[0], or_end_dt, alpha=0.08, color="#FF9800", zorder=1, label="OR window")
    ax_price.axhline(or_high, color="#FF9800", lw=0.9, ls="--", alpha=0.85, label=f"OR H {or_high:.2f}")
    ax_price.axhline(or_low,  color="#FF9800", lw=0.9, ls="--", alpha=0.85, label=f"OR L {or_low:.2f}")
    ax_price.axhline(mid,     color="#FF9800", lw=0.6, ls=":",  alpha=0.6,  label=f"OR Mid {mid:.2f}")

    # ── Entry / exit ─────────────────────────────────────────────────────────
    entry_dt = ET.localize(datetime.strptime(f"{trade['date']} 09:45", "%Y-%m-%d %H:%M"))
    exit_dt  = entry_dt + timedelta(minutes=int(trade["mins_held"]))
    entry_bar = nearest_bar(bars.index, entry_dt)
    exit_bar  = nearest_bar(bars.index, exit_dt)
    ep = trade["entry_price"]
    xp = trade["exit_price"]
    signal = trade["signal"]

    bull = signal == "BULLISH"
    entry_color  = "#00C853" if bull else "#D32F2F"
    entry_marker = "^"      if bull else "v"

    ax_price.scatter(entry_bar, ep, marker=entry_marker, color=entry_color,
                     s=180, zorder=7, label=f"Entry @ {ep:.2f}")
    ax_price.scatter(exit_bar,  xp, marker="X", color="#212121",
                     s=140, zorder=7, label=f"Exit @ {xp:.2f}")
    ax_price.annotate(f" {ep:.2f}", xy=(entry_bar, ep), fontsize=7.5,
                      color=entry_color, va="center", fontweight="bold")
    ax_price.annotate(f" {xp:.2f}", xy=(exit_bar,  xp), fontsize=7.5,
                      color="#212121", va="center")

    # ── Formatting ───────────────────────────────────────────────────────────
    pnl = trade["pnl_pct"]
    pnl_color = "#00695C" if pnl >= 0 else "#B71C1C"
    result_str = "WIN" if pnl >= 0 else "LOSS"
    exit_lbl = (trade["exit_reason"]
                .replace("trailing_stop_ma20", "Trail MA20")
                .replace("fallback_20pct", "Fallback 20%")
                .replace("hard_stop", "Hard Stop"))

    fig.suptitle(
        f"Rank {int(trade['rank'])}  ·  {trade['ticker']}  ·  {trade['date']}  ·  {signal}\n"
        f"P&L: {pnl:+.2f}%  [{result_str}]  ·  Exit: {exit_lbl}  ·  Held: {int(trade['mins_held'])} min  ·  Score: {trade['score']:.3f}",
        fontsize=10, fontweight="bold", color=pnl_color, y=1.02
    )

    fmt = mdates.DateFormatter("%H:%M", tz=ET)
    ax_price.xaxis.set_major_formatter(fmt)
    ax_price.xaxis.set_major_locator(mdates.MinuteLocator(byminute=[0, 30], interval=1))
    plt.setp(ax_price.get_xticklabels(), rotation=45, fontsize=7)

    ax_price.set_ylabel("Price ($)", fontsize=8)
    ax_price.tick_params(axis="y", labelsize=7)
    ax_price.legend(fontsize=6.5, loc="upper left", ncol=4, framealpha=0.7)
    ax_price.grid(True, alpha=0.2, zorder=0)

    fig.tight_layout()


def main():
    trades = load_trades()
    out_path = "charts/week1_may2026_top5.pdf"
    os.makedirs("charts", exist_ok=True)

    with PdfPages(out_path) as pdf:
        # Cover page
        fig = plt.figure(figsize=(11, 4))
        fig.text(0.5, 0.65, "May 2026 — Week 1 Selector Picks", ha="center",
                 fontsize=18, fontweight="bold")
        fig.text(0.5, 0.50, "Top-5 per day  ·  M1 window (09:30 / 3 bars)  ·  SIP feed",
                 ha="center", fontsize=12, color="#555555")
        fig.text(0.5, 0.40,
                 "Config: no-CHTR  ·  stop=0.45  ·  lookback=60d  ·  entry=0.60  ·  rel_strength=0.15",
                 ha="center", fontsize=10, color="#777777")
        days = sorted(trades["date"].unique())
        summary_lines = []
        for day in days:
            day_df = trades[trades["date"] == day]
            wins   = (day_df["pnl_pct"] > 0).sum()
            losses = (day_df["pnl_pct"] <= 0).sum()
            picks  = len(day_df)
            total  = day_df["pnl_pct"].sum()
            summary_lines.append(f"{day}  —  {picks} picks  {wins}W/{losses}L  total P&L: {total:+.2f}%")
        fig.text(0.5, 0.08, "\n".join(summary_lines), ha="center", fontsize=9,
                 color="#333333", family="monospace")
        pdf.savefig(fig, bbox_inches="tight")
        plt.close()

        total_trades = len(trades)
        for idx, (_, trade) in enumerate(trades.iterrows()):
            ticker = trade["ticker"]
            date   = trade["date"]
            print(f"  [{idx+1}/{total_trades}] {date} rank={int(trade['rank'])} {ticker} ...")
            bars = get_bars(ticker, date)
            if bars is None or bars.empty:
                print(f"    !! no bar data for {ticker} {date}")
                continue
            fig = plt.figure(figsize=(14, 8))
            draw_chart(fig, trade, bars)
            pdf.savefig(fig, bbox_inches="tight")
            plt.close()

        d = pdf.infodict()
        d["Title"]   = "May 2026 Week 1 — Selector Top-5 Charts"
        d["Author"]  = "alpha_tech_tracker"
        d["Subject"] = "5-min candlestick charts with OR range, entry/exit, SMA20/50/200"

    print(f"\nPDF saved: {out_path}")


if __name__ == "__main__":
    main()

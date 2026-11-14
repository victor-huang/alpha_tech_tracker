"""PDF of daily candlestick charts (8/20/50/200-day averages) for every top-5 trade, holding period highlighted."""
import os
import pickle
import sys
from datetime import date, datetime

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from alpaca.data.enums import Adjustment, DataFeed  # noqa: E402
from alpaca.data.requests import StockBarsRequest  # noqa: E402
from alpaca.data.timeframe import TimeFrame  # noqa: E402
from matplotlib.backends.backend_pdf import PdfPages  # noqa: E402

from alpha_tech_tracker.research.top_performers import AlpacaData, sip_request_end  # noqa: E402

PKL, OHLC, PDF = sys.argv[1], sys.argv[2], sys.argv[3]
TIERS = ("Large", "Mid", "Small")
MAS = {8: "#e377c2", 20: "#1f77b4", 50: "#ff7f0e", 200: "#7f7f7f"}
BEFORE, AFTER = 60, 20
ROWS, COLS = 3, 2


def fetch_ohlc(symbols, year):
    if os.path.exists(OHLC):
        return pd.read_pickle(OHLC)
    client = AlpacaData().data
    frames = []
    for i in range(0, len(symbols), 50):
        req = StockBarsRequest(symbol_or_symbols=symbols[i:i + 50], timeframe=TimeFrame.Day,
                               start=datetime(year - 1, 1, 2), end=sip_request_end(date.today(), datetime.utcnow()),
                               adjustment=Adjustment.ALL, feed=DataFeed.SIP)
        frames.append(client.get_stock_bars(req).df[["open", "high", "low", "close"]].reset_index())
    bars = pd.concat(frames, ignore_index=True)
    bars["day"] = pd.to_datetime(pd.to_datetime(bars["timestamp"]).dt.tz_convert("America/New_York").dt.date)
    bars = bars.drop(columns="timestamp")
    bars.to_pickle(OHLC)
    return bars


def draw(ax, bars, trade, number):
    b = bars.sort_values("day").set_index("day")
    for n in MAS:
        b[f"ma{n}"] = b["close"].rolling(n).mean()
    days = b.index
    i0 = days.searchsorted(trade["entry"])
    i1 = days.searchsorted(trade["exit"])
    w = b.iloc[max(i0 - BEFORE, 0):min(i1 + AFTER, len(b) - 1) + 1]
    x = np.arange(len(w))
    up = w["close"] >= w["open"]
    color = np.where(up, "#26a69a", "#ef5350")
    ax.vlines(x, w["low"], w["high"], color=color, linewidth=0.6)
    ax.bar(x, (w["close"] - w["open"]).abs().clip(lower=w["close"] * 1e-3), bottom=np.minimum(w["open"], w["close"]),
           color=color, width=0.7, linewidth=0)
    for n, c in MAS.items():
        ax.plot(x, w[f"ma{n}"], color=c, linewidth=0.9, label=f"{n}d")
    a = w.index.searchsorted(trade["entry"])
    z = w.index.searchsorted(trade["exit"])
    gain = trade["ret"] >= 0
    ax.axvspan(a - 0.5, z + 0.5, color="#2e7d32" if gain else "#c62828", alpha=0.12)
    ax.plot([a, z], [w["close"].iloc[a], w["close"].iloc[min(z, len(w) - 1)]], "o", color="black", markersize=3)
    status = "held to end" if trade["reason"] == "open" else trade["reason"]
    ax.set_title(f"{number}. {trade['symbol']}  checkpoint {trade['checkpoint']:%m-%d}  "
                 f"{trade['entry']:%m-%d} → {trade['exit']:%m-%d}  {trade['ret']:+.1%}  ({status})",
                 fontsize=8, color="#1b5e20" if gain else "#b71c1c", loc="left")
    ticks = x[::max(len(x) // 6, 1)]
    ax.set_xticks(ticks)
    ax.set_xticklabels([w.index[t].strftime("%m-%d") for t in ticks], fontsize=6)
    ax.tick_params(axis="y", labelsize=6)
    ax.ticklabel_format(axis="y", style="plain", useOffset=False)
    ax.set_xlim(-1, len(w))
    ax.grid(alpha=0.2)
    ax.legend(fontsize=5, loc="upper left", ncol=4, frameon=False)


def summary_page(pdf, data):
    n = data.get("n", 5)
    fig = plt.figure(figsize=(11, 8.5))
    fig.suptitle(f"{data.get('year', 2026)} top-{n} books: recommended Large / Mid / Small rules (through "
                 f"{data['Large'][0].index[-1]:%Y-%m-%d})", fontsize=13)
    ax = fig.add_axes([0.06, 0.52, 0.9, 0.36])
    for t, c in zip(TIERS + ("QQQ",), ("#1f77b4", "#ff7f0e", "#2ca02c", "#7f7f7f")):
        s = data[t] if t == "QQQ" else data[t][0]
        ax.plot(s.index, (s - 1) * 100, label=t, color=c, linewidth=1.4 if t != "QQQ" else 1)
    ax.axhline(0, color="black", linewidth=0.5)
    ax.set_ylabel("cumulative %")
    ax.legend(frameon=False)
    ax.grid(alpha=0.3)
    table = (data["monthly"] * 100).round(1)
    tax = fig.add_axes([0.08, 0.04, 0.42, 0.42])
    tax.axis("off")
    cells = [[f"{v:+.1f}%" for v in row] for row in table.values]
    tb = tax.table(cellText=cells, rowLabels=list(table.index), colLabels=list(table.columns), loc="center")
    tb.auto_set_font_size(False)
    tb.set_fontsize(8)
    for (r, c), cell in tb.get_celld().items():
        if r > 0 and c >= 0:
            v = table.values[r - 1, c]
            cell.set_facecolor("#e8f5e9" if v > 0 else "#ffebee" if v < 0 else "white")
    notes = [f"Top {n}, equal weight, checked every 10 trading days, 0.1% cost per trade.",
             "Large: 180-day / vol^0.5 with breakout slots, 25% trailing stop.",
             "Mid: reclaim + growth list, never-held first, 15% trailing stop.",
             "Small: composite + no dilution + gross profit, 15% trailing stop.", ""]
    for t in TIERS:
        tr = data[t][1]
        notes.append(f"{t}: {len(tr)} trades, {(tr['ret'] > 0).mean():.0%} winners, "
                     f"avg {tr['ret'].mean():+.1%}, best {tr.loc[tr['ret'].idxmax(), 'symbol']} "
                     f"{tr['ret'].max():+.0%}, worst {tr.loc[tr['ret'].idxmin(), 'symbol']} {tr['ret'].min():+.0%}")
    notes += ["", "Charts: daily candles, 8/20/50/200-day averages, holding period shaded",
              "(green = gain, red = loss), ordered by checkpoint."]
    fig.text(0.53, 0.44, "\n".join(notes), fontsize=7.5, va="top")
    pdf.savefig(fig)
    plt.close(fig)


def main():
    with open(PKL, "rb") as f:
        data = pickle.load(f)
    trades = pd.concat([data[t][1] for t in TIERS], ignore_index=True)
    bars = fetch_ohlc(sorted(trades["symbol"].unique()), data.get("year", 2026))
    by_symbol = {s: g for s, g in bars.groupby("symbol")}
    per_page = ROWS * COLS
    n = data.get("n", 5)
    with PdfPages(PDF) as pdf:
        summary_page(pdf, data)
        for t in TIERS:
            tr = data[t][1].sort_values(["checkpoint", "entry"]).reset_index(drop=True)
            for p in range(0, len(tr), per_page):
                fig, axes = plt.subplots(ROWS, COLS, figsize=(11, 8.5))
                chunk = tr.iloc[p:p + per_page]
                fig.suptitle(f"{t} top {n} — trades {p + 1}–{p + len(chunk)} of {len(tr)}", fontsize=11)
                for ax, (k, trade) in zip(axes.flat, chunk.iterrows()):
                    if trade["symbol"] in by_symbol:
                        draw(ax, by_symbol[trade["symbol"]], trade, k + 1)
                    else:
                        ax.set_title(f"{k + 1}. {trade['symbol']}: no OHLC bars", fontsize=8)
                for ax in list(axes.flat)[len(chunk):]:
                    ax.axis("off")
                fig.tight_layout(rect=(0, 0, 1, 0.96))
                pdf.savefig(fig)
                plt.close(fig)
    print(f"wrote {PDF}")


if __name__ == "__main__":
    main()

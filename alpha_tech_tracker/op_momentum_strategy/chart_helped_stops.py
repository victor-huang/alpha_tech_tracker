"""Generate 5-min candlestick charts for 10 representative 'HELPED' losing
afternoon trades, showing where the stop fired and how price continued after.

Usage:
    source ~/.pyenv/versions/alpha_tech_tracker/bin/activate
    PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker \
        python alpha_tech_tracker/op_momentum_strategy/chart_helped_stops.py
"""

import math
import pytz
from datetime import datetime, date, timedelta

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.dates as mdates
import pandas as pd

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

ET = pytz.timezone("America/New_York")

ALPACA_KEY    = "AK2PHJV4ZFO65JYT2IU7EDDIDH"
ALPACA_SECRET = "7NmxWaaBDRtXq8TJ2HLusiHqXqjT3QQQYWX1KZhj8iTb"

# ── 10 representative HELPED trades ──────────────────────────────────────────
# Fields: ticker, date, direction (CALL/PUT), window, open_et, close_et,
#         opt_pct (option P&L%), post_stock_pct (stock move after stop)
HELPED_TRADES = [
    # A2 window picks
    dict(ticker="MU",   dt="2026-04-27", direction="CALL", window="A2",
         open_et="13:46", close_et="13:48", opt_pct=-1.33, post_pct=-0.28),
    dict(ticker="COIN", dt="2026-04-28", direction="PUT",  window="A2",
         open_et="13:22", close_et="13:26", opt_pct=-1.53, post_pct=+0.39),
    dict(ticker="COIN", dt="2026-04-30", direction="PUT",  window="A2",
         open_et="13:22", close_et="13:26", opt_pct=-1.02, post_pct=+0.93),
    dict(ticker="CVNA", dt="2026-04-30", direction="PUT",  window="A2",
         open_et="13:43", close_et="14:51", opt_pct=-36.97, post_pct=+1.29),
    dict(ticker="MU",   dt="2026-05-04", direction="CALL", window="A2",
         open_et="13:22", close_et="13:31", opt_pct=-1.45, post_pct=-0.74),
    # A3 window picks
    dict(ticker="MSTR", dt="2026-04-28", direction="PUT",  window="A3",
         open_et="15:07", close_et="15:11", opt_pct=-1.33, post_pct=+0.54),
    dict(ticker="CVNA", dt="2026-04-29", direction="PUT",  window="A3",
         open_et="15:07", close_et="15:31", opt_pct=-2.61, post_pct=+0.55),
    dict(ticker="CVNA", dt="2026-04-30", direction="CALL", window="A3",
         open_et="15:07", close_et="15:11", opt_pct=-3.94, post_pct=-0.76),
    dict(ticker="MU",   dt="2026-05-05", direction="CALL", window="A3",
         open_et="15:01", close_et="15:21", opt_pct=-13.81, post_pct=-1.40),
    dict(ticker="CRDO", dt="2026-05-07", direction="PUT",  window="A3",
         open_et="15:21", close_et="15:38", opt_pct=-10.64, post_pct=+0.98),
]


def _to_et_dt(date_str: str, time_str: str) -> datetime:
    return ET.localize(datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M"))


def _fetch_bars(client, ticker: str, dt_str: str) -> pd.DataFrame:
    dt = date.fromisoformat(dt_str)
    start = ET.localize(datetime.combine(dt, datetime.min.time()).replace(hour=12, minute=30))
    end   = ET.localize(datetime.combine(dt, datetime.min.time()).replace(hour=16, minute=5))
    req = StockBarsRequest(
        symbol_or_symbols=[ticker],
        timeframe=TimeFrame(5, TimeFrameUnit.Minute),
        start=start,
        end=end,
        feed="sip",
    )
    raw = client.get_stock_bars(req)
    bars = raw.data.get(ticker, [])
    if not bars:
        return pd.DataFrame()
    rows = [{
        "timestamp": b.timestamp.astimezone(ET).replace(tzinfo=None),
        "open":  b.open,
        "high":  b.high,
        "low":   b.low,
        "close": b.close,
        "volume": b.volume,
    } for b in bars]
    df = pd.DataFrame(rows).set_index("timestamp")
    df.index = pd.DatetimeIndex(df.index)
    return df


def _draw_candle_chart(ax, df: pd.DataFrame, trade: dict):
    if df.empty:
        ax.text(0.5, 0.5, "No data", ha="center", va="center", transform=ax.transAxes)
        return

    open_dt  = _to_et_dt(trade["dt"], trade["open_et"]).replace(tzinfo=None)
    close_dt = _to_et_dt(trade["dt"], trade["close_et"]).replace(tzinfo=None)
    bullish  = trade["direction"] == "CALL"

    # Draw candlesticks manually
    bar_width_days = 4.5 / (24 * 60)  # ~4.5 min in day fractions
    for ts, row in df.iterrows():
        x = mdates.date2num(ts.to_pydatetime())
        color = "#26a69a" if row["close"] >= row["open"] else "#ef5350"
        # Body
        body_bot = min(row["open"], row["close"])
        body_top = max(row["open"], row["close"])
        rect = mpatches.FancyBboxPatch(
            (x - bar_width_days / 2, body_bot),
            bar_width_days,
            max(body_top - body_bot, 0.001),
            linewidth=0,
            facecolor=color,
            boxstyle="square,pad=0",
        )
        ax.add_patch(rect)
        # Wicks
        ax.plot([x, x], [row["low"], body_bot], color=color, linewidth=0.7)
        ax.plot([x, x], [body_top, row["high"]], color=color, linewidth=0.7)

    # Shade trade period (entry → exit)
    ax.axvspan(mdates.date2num(open_dt), mdates.date2num(close_dt),
               alpha=0.15, color="gray", zorder=0)

    # Entry line
    ax.axvline(mdates.date2num(open_dt), color="#1565c0", linewidth=1.5,
               linestyle="--", label="Entry")
    # Exit line
    ax.axvline(mdates.date2num(close_dt), color="#b71c1c", linewidth=1.5,
               linestyle="--", label="Stop-out")

    # Arrow showing trade direction at entry
    y_range = df["high"].max() - df["low"].min()
    entry_row = df[df.index <= pd.Timestamp(open_dt)]
    entry_y = entry_row["close"].iloc[-1] if not entry_row.empty else df["close"].mean()
    arrow_dy = y_range * 0.08 * (1 if bullish else -1)
    ax.annotate(
        "▲ CALL" if bullish else "▼ PUT",
        xy=(mdates.date2num(open_dt), entry_y),
        xytext=(mdates.date2num(open_dt), entry_y + arrow_dy * 2),
        fontsize=7, color="#1565c0", ha="center",
        arrowprops=dict(arrowstyle="->", color="#1565c0", lw=1.2),
    )

    # Format x axis
    ax.xaxis_date()
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    ax.xaxis.set_major_locator(mdates.MinuteLocator(byminute=[0, 30]))
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=0, fontsize=7)
    ax.yaxis.set_tick_params(labelsize=7)
    ax.set_xlim(df.index[0].to_pydatetime(), df.index[-1].to_pydatetime())
    ax.set_ylim(df["low"].min() * 0.999, df["high"].max() * 1.001)
    ax.grid(axis="y", linewidth=0.4, alpha=0.5)

    # Title
    post_arrow = "↓" if trade["post_pct"] < 0 else "↑"
    ax.set_title(
        f"{trade['ticker']} {trade['dt'][5:]}  [{trade['window']}]  "
        f"{trade['direction']}  {trade['open_et']}→{trade['close_et']}\n"
        f"Opt: {trade['opt_pct']:+.1f}%   Stock after: {post_arrow}{abs(trade['post_pct']):.2f}%",
        fontsize=8, pad=4,
    )


def main():
    client = StockHistoricalDataClient(api_key=ALPACA_KEY, secret_key=ALPACA_SECRET)

    print("Fetching bars for 10 trades...")
    nrows, ncols = 2, 5
    fig, axes = plt.subplots(nrows, ncols, figsize=(22, 9))
    fig.suptitle(
        "Afternoon Stop Quality — HELPED trades (stop avoided further loss)\n"
        "Blue dashed = entry  |  Red dashed = stop-out  |  Gray shading = trade held",
        fontsize=11, y=1.01,
    )
    axes_flat = axes.flatten()

    for i, trade in enumerate(HELPED_TRADES):
        print(f"  {i+1}/10  {trade['ticker']} {trade['dt']} {trade['window']}")
        df = _fetch_bars(client, trade["ticker"], trade["dt"])
        _draw_candle_chart(axes_flat[i], df, trade)

    plt.tight_layout(rect=[0, 0, 1, 0.97])
    out_path = "charts/afternoon_helped_stops.pdf"
    import pathlib
    pathlib.Path("charts").mkdir(exist_ok=True)
    plt.savefig(out_path, bbox_inches="tight", dpi=150)
    print(f"\nSaved → {out_path}")


if __name__ == "__main__":
    main()

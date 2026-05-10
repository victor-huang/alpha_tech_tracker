import json
import os
import glob
from datetime import date, datetime, timedelta

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.dates as mdates
import matplotlib.gridspec as gridspec
import numpy as np
import pandas as pd

CACHE_DIR = "/Users/victorhuang/work/alpha_tech_tracker/market_data/cache"
OUT_DIR = "/Users/victorhuang/work/alpha_tech_tracker/charts"

TRADE_ANNOTATIONS = {
    ("CRDO", "2026-02-03"): [
        {"time": "09:45", "action": "short", "price": 117.03, "shares": 86},
        {"time": "14:00", "action": "cover", "price": 106.92, "shares": 86, "pnl": +869.58},
    ],
    ("PLTR", "2026-02-03"): [
        {"time": "10:00", "action": "buy", "price": 155.75, "shares": 10},
        {"time": "14:30", "action": "sell", "price": 157.62, "shares": 10, "pnl": +18.70},
    ],
    ("PLTR", "2026-02-04"): [
        {"time": "09:40", "action": "short", "price": 148.67, "shares": 40},
        {"time": "15:00", "action": "cover", "price": 137.54, "shares": 40, "pnl": +445.20},
    ],
    ("MU", "2026-02-04"): [
        {"time": "09:45", "action": "short", "price": 400.42, "shares": 5},
        {"time": "14:00", "action": "cover", "price": 368.95, "shares": 5, "pnl": +157.35},
    ],
    ("TSLA", "2026-02-04"): [
        {"time": "09:35", "action": "short", "price": 370.00, "shares": 8},
        {"time": "13:00", "action": "cover", "price": 355.00, "shares": 8, "pnl": +120.00},
    ],
    ("SNDK", "2026-02-04"): [
        {"time": "09:40", "action": "short", "price": 58.00, "shares": 50},
        {"time": "13:30", "action": "cover", "price": 54.00, "shares": 50, "pnl": +200.00},
    ],
    ("SHOP", "2026-02-11"): [
        {"time": "09:35", "action": "short", "price": 123.55, "shares": 30},
        {"time": "14:30", "action": "cover", "price": 111.00, "shares": 30, "pnl": +376.50},
    ],
    ("CRDO", "2026-02-11"): [
        {"time": "09:40", "action": "short", "price": 127.40, "shares": 50},
        {"time": "13:00", "action": "cover", "price": 123.63, "shares": 50, "pnl": +188.50},
    ],
    ("MU", "2026-02-11"): [
        {"time": "10:00", "action": "buy", "price": 380.00, "shares": 5},
        {"time": "15:00", "action": "sell", "price": 392.00, "shares": 5, "pnl": +60.00},
    ],
    ("CVNA", "2026-04-30"): [
        {"time": "09:35", "action": "short", "price": 383.50, "shares": 5},
        {"time": "10:30", "action": "cover", "price": 385.73, "shares": 5, "pnl": -11.15},
        {"time": "11:00", "action": "short", "price": 372.92, "shares": 5},
        {"time": "14:00", "action": "cover", "price": 389.89, "shares": 5, "pnl": -84.85},
    ],
    ("CRDO", "2026-04-30"): [
        {"time": "09:40", "action": "buy", "price": 175.00, "shares": 20},
        {"time": "11:00", "action": "sell", "price": 174.57, "shares": 20, "pnl": -8.60},
    ],
    ("CVNA", "2026-05-07"): [
        {"time": "09:35", "action": "short", "price": 370.00, "shares": 5},
        {"time": "11:00", "action": "cover", "price": 373.00, "shares": 5, "pnl": -15.00},
    ],
    ("CRDO", "2026-05-07"): [
        {"time": "10:00", "action": "buy", "price": 165.00, "shares": 20},
        {"time": "12:00", "action": "sell", "price": 163.00, "shares": 20, "pnl": -40.00},
    ],
}

DAY_CONFIGS = [
    {
        "label": "best_feb03",
        "title": "BEST DAY — Feb 3, 2026  (+$811 day)",
        "date": "2026-02-03",
        "tickers": ["CRDO", "PLTR"],
    },
    {
        "label": "best_feb04",
        "title": "BEST DAY — Feb 4, 2026  (+$644 day)",
        "date": "2026-02-04",
        "tickers": ["PLTR", "MU", "TSLA", "SNDK"],
    },
    {
        "label": "best_feb11",
        "title": "BEST DAY — Feb 11, 2026  (+$713 day)",
        "date": "2026-02-11",
        "tickers": ["SHOP", "CRDO", "MU"],
    },
    {
        "label": "worst_apr30",
        "title": "WORST DAY — Apr 30, 2026  (-$381 day)",
        "date": "2026-04-30",
        "tickers": ["CVNA", "CRDO"],
    },
    {
        "label": "worst_may07",
        "title": "WORST DAY — May 7, 2026  (small losses)",
        "date": "2026-05-07",
        "tickers": ["CVNA", "CRDO"],
    },
]


def find_cache_file(ticker, target_date_str):
    target_date = datetime.strptime(target_date_str, "%Y-%m-%d").date()
    pattern = os.path.join(CACHE_DIR, f"alpaca_iex_5min_{ticker}_*_*.json")
    candidates = glob.glob(pattern)
    best = None
    best_start = None
    for path in candidates:
        fname = os.path.basename(path)
        parts = fname.replace(".json", "").split("_")
        try:
            start_str = parts[-2]
            end_str = parts[-1]
            start = datetime.strptime(start_str, "%Y-%m-%d").date()
            end = datetime.strptime(end_str, "%Y-%m-%d").date()
        except ValueError:
            continue
        if start <= target_date <= end:
            if best is None or start > best_start:
                best = path
                best_start = start
    return best


def load_5min_bars(ticker, target_date_str):
    path = find_cache_file(ticker, target_date_str)
    if path is None:
        print(f"  [WARN] No cache file found for {ticker} on {target_date_str}")
        return None
    with open(path) as f:
        raw = json.load(f)
    df = pd.DataFrame(raw["data"], index=raw["index"], columns=raw["columns"])
    df.index = pd.to_datetime(df.index, utc=True).tz_convert("America/New_York")
    df.rename(columns={"Open": "open", "High": "high", "Low": "low",
                        "Close": "close", "Volume": "volume"}, inplace=True)
    return df


def get_intraday_bars(df, date_str):
    target = pd.Timestamp(date_str).date()
    mask = df.index.date == target
    day_df = df[mask].copy()
    market_open = pd.Timestamp(f"{date_str} 09:30:00", tz="America/New_York")
    market_close = pd.Timestamp(f"{date_str} 16:00:00", tz="America/New_York")
    return day_df[(day_df.index >= market_open) & (day_df.index <= market_close)]


def get_daily_bars_from_5min(df, date_str, lookback_days=35):
    target = pd.Timestamp(date_str).date()
    cutoff = target - timedelta(days=lookback_days * 2)
    mask = df.index.date <= target
    subset = df[mask]
    grouped = subset.groupby(subset.index.date).agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
    )
    grouped.index = pd.to_datetime(grouped.index)
    recent = grouped[grouped.index.date >= cutoff]
    return recent.tail(35)


def ema(series, span):
    return series.ewm(span=span, adjust=False).mean()


def sma(series, window):
    return series.rolling(window=window, min_periods=1).mean()


def draw_candlestick(ax, df, color_up="#2ecc71", color_down="#e74c3c", width=0.6):
    for i, (ts, row) in enumerate(df.iterrows()):
        is_up = row["close"] >= row["open"]
        color = color_up if is_up else color_down
        body_bottom = min(row["open"], row["close"])
        body_height = abs(row["close"] - row["open"])
        rect = mpatches.FancyBboxPatch(
            (i - width / 2, body_bottom), width, max(body_height, row["close"] * 0.0002),
            boxstyle="square,pad=0", linewidth=0, color=color, zorder=3,
        )
        ax.add_patch(rect)
        ax.plot([i, i], [row["low"], body_bottom], color=color, linewidth=0.8, zorder=2)
        ax.plot([i, i], [body_bottom + max(body_height, 0), row["high"]], color=color, linewidth=0.8, zorder=2)
    ax.set_xlim(-1, len(df))
    all_prices = pd.concat([df["high"], df["low"]])
    pad = (all_prices.max() - all_prices.min()) * 0.05
    ax.set_ylim(all_prices.min() - pad, all_prices.max() + pad)


def price_to_idx(df, time_str, date_str):
    ts = pd.Timestamp(f"{date_str} {time_str}:00", tz="America/New_York")
    diffs = abs(df.index - ts)
    return int(diffs.argmin())


def annotate_trades(ax, intraday_df, trades, date_str):
    if not trades:
        return
    for trade in trades:
        idx = price_to_idx(intraday_df, trade["time"], date_str)
        if idx >= len(intraday_df):
            continue
        price = trade["price"]
        action = trade["action"]

        if action in ("buy",):
            ax.annotate(
                f"BUY\n${price:.2f}",
                xy=(idx, price),
                xytext=(idx, price * 0.975),
                fontsize=6.5,
                color="#27ae60",
                fontweight="bold",
                ha="center",
                arrowprops=dict(arrowstyle="->", color="#27ae60", lw=1.5),
            )
        elif action in ("short",):
            ax.annotate(
                f"SHORT\n${price:.2f}",
                xy=(idx, price),
                xytext=(idx, price * 1.025),
                fontsize=6.5,
                color="#e74c3c",
                fontweight="bold",
                ha="center",
                arrowprops=dict(arrowstyle="->", color="#e74c3c", lw=1.5),
            )
        elif action in ("sell", "cover"):
            pnl = trade.get("pnl", 0)
            pnl_str = f"+${pnl:.0f}" if pnl >= 0 else f"-${abs(pnl):.0f}"
            color = "#27ae60" if pnl >= 0 else "#e74c3c"
            label = "SELL" if action == "sell" else "COVER"
            ax.annotate(
                f"{label}\n${price:.2f}\n{pnl_str}",
                xy=(idx, price),
                xytext=(idx, price * (0.965 if pnl >= 0 else 1.035)),
                fontsize=6.5,
                color=color,
                fontweight="bold",
                ha="center",
                arrowprops=dict(arrowstyle="->", color=color, lw=1.5),
            )


def plot_intraday_panel(ax, ax_vol, ticker, date_str, all_df):
    intraday = get_intraday_bars(all_df, date_str)
    if intraday.empty:
        ax.text(0.5, 0.5, f"No data for {ticker} {date_str}", transform=ax.transAxes,
                ha="center", va="center", fontsize=9, color="gray")
        return intraday

    draw_candlestick(ax, intraday)

    xs = np.arange(len(intraday))
    ema9 = ema(intraday["close"], 9)
    ema20 = ema(intraday["close"], 20)
    ax.plot(xs, ema9.values, color="#3498db", linewidth=1.0, label="EMA9", zorder=4)
    ax.plot(xs, ema20.values, color="#f39c12", linewidth=1.0, label="EMA20", zorder=4)
    ax.legend(loc="upper left", fontsize=6, framealpha=0.7)

    trades = TRADE_ANNOTATIONS.get((ticker, date_str), [])
    annotate_trades(ax, intraday, trades, date_str)

    tick_step = max(1, len(intraday) // 6)
    tick_positions = xs[::tick_step]
    tick_labels = [intraday.index[i].strftime("%H:%M") for i in tick_positions]
    ax.set_xticks(tick_positions)
    ax.set_xticklabels(tick_labels, fontsize=6)
    ax.tick_params(axis="y", labelsize=6)
    ax.set_ylabel("Price", fontsize=7)
    ax.set_title(f"{ticker} — Intraday 5-min  ({date_str})", fontsize=8, fontweight="bold")
    ax.grid(True, alpha=0.3, linewidth=0.5)

    colors = ["#2ecc71" if intraday["close"].iloc[i] >= intraday["open"].iloc[i] else "#e74c3c"
              for i in range(len(intraday))]
    ax_vol.bar(xs, intraday["volume"].values, color=colors, alpha=0.6, width=0.8)
    ax_vol.set_xlim(-1, len(intraday))
    ax_vol.set_xticks([])
    ax_vol.set_ylabel("Vol", fontsize=6)
    ax_vol.tick_params(axis="y", labelsize=5)
    ax_vol.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"{x/1000:.0f}K"))
    ax_vol.grid(True, alpha=0.2, linewidth=0.4)

    return intraday


def plot_daily_panel(ax, ax_vol, ticker, date_str, all_df):
    daily = get_daily_bars_from_5min(all_df, date_str, lookback_days=40)
    if daily.empty:
        ax.text(0.5, 0.5, f"No daily data for {ticker}", transform=ax.transAxes,
                ha="center", va="center", fontsize=9, color="gray")
        return

    draw_candlestick(ax, daily, width=0.5)

    xs = np.arange(len(daily))
    ma20 = sma(daily["close"], 20)
    ma50 = sma(daily["close"], 50)
    ax.plot(xs, ma20.values, color="#3498db", linewidth=1.2, label="MA20")
    ax.plot(xs, ma50.values, color="#e67e22", linewidth=1.2, label="MA50")
    ax.legend(loc="upper left", fontsize=6, framealpha=0.7)

    target_dt = pd.Timestamp(date_str)
    if target_dt in daily.index:
        key_idx = daily.index.get_loc(target_dt)
        ax.axvspan(key_idx - 0.5, key_idx + 0.5, color="#f1c40f", alpha=0.35, zorder=1, label="Key date")

    tick_step = max(1, len(daily) // 7)
    tick_positions = xs[::tick_step]
    tick_labels = [daily.index[i].strftime("%m/%d") for i in tick_positions]
    ax.set_xticks(tick_positions)
    ax.set_xticklabels(tick_labels, fontsize=6, rotation=30)
    ax.tick_params(axis="y", labelsize=6)
    ax.set_ylabel("Price", fontsize=7)
    ax.set_title(f"{ticker} — Daily (~30-day context)", fontsize=8, fontweight="bold")
    ax.grid(True, alpha=0.3, linewidth=0.5)

    colors = ["#2ecc71" if daily["close"].iloc[i] >= daily["open"].iloc[i] else "#e74c3c"
              for i in range(len(daily))]
    ax_vol.bar(xs, daily["volume"].values, color=colors, alpha=0.6, width=0.8)
    ax_vol.set_xlim(-1, len(daily))
    ax_vol.set_xticks([])
    ax_vol.set_ylabel("Vol", fontsize=6)
    ax_vol.tick_params(axis="y", labelsize=5)
    ax_vol.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"{x/1e6:.1f}M"))
    ax_vol.grid(True, alpha=0.2, linewidth=0.4)


def create_day_pdf(config):
    label = config["label"]
    title = config["title"]
    date_str = config["date"]
    tickers = config["tickers"]

    print(f"\nCreating {label}.pdf  ({title})")

    loaded = {}
    valid_tickers = []
    for ticker in tickers:
        df = load_5min_bars(ticker, date_str)
        if df is not None and not df.empty:
            loaded[ticker] = df
            valid_tickers.append(ticker)
        else:
            print(f"  Skipping {ticker} — no data")

    if not valid_tickers:
        print(f"  [ERROR] No data found for any ticker on {date_str}")
        return

    n = len(valid_tickers)
    fig = plt.figure(figsize=(16, 5.5 * n))
    fig.suptitle(title, fontsize=14, fontweight="bold", y=0.995)

    outer = gridspec.GridSpec(n, 1, figure=fig, hspace=0.55)

    for row_idx, ticker in enumerate(valid_tickers):
        all_df = loaded[ticker]
        inner = gridspec.GridSpecFromSubplotSpec(
            2, 2,
            subplot_spec=outer[row_idx],
            hspace=0.0,
            wspace=0.35,
            height_ratios=[3, 1],
        )
        ax_intra = fig.add_subplot(inner[0, 0])
        ax_intra_vol = fig.add_subplot(inner[1, 0])
        ax_daily = fig.add_subplot(inner[0, 1])
        ax_daily_vol = fig.add_subplot(inner[1, 1])

        plot_intraday_panel(ax_intra, ax_intra_vol, ticker, date_str, all_df)
        plot_daily_panel(ax_daily, ax_daily_vol, ticker, date_str, all_df)

    out_path = os.path.join(OUT_DIR, f"{label}.pdf")
    fig.savefig(out_path, bbox_inches="tight", dpi=150)
    plt.close(fig)
    print(f"  Saved: {out_path}")


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    for config in DAY_CONFIGS:
        create_day_pdf(config)
    print("\nAll charts saved.")


if __name__ == "__main__":
    main()

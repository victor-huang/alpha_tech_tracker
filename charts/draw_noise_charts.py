import json
import os
import re
from datetime import datetime, timezone, timedelta

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.gridspec as gridspec
import matplotlib.dates as mdates
import numpy as np
import pandas as pd
from matplotlib.backends.backend_pdf import PdfPages

CACHE_DIR = "/Users/victorhuang/work/alpha_tech_tracker/market_data/cache"
LOG_DIR = "/Users/victorhuang/work/alpha_tech_tracker/logs/replay_2026_stock_5win"
OUT_DIR = "/Users/victorhuang/work/alpha_tech_tracker/charts"

TRADE_RE = re.compile(
    r"^\s{2}(\S+)\s+\[([^\]]+)\]\s+\S+ \[stock\]\s+(\d+)sh\s+"
    r"(\d+:\d+)\s+(\d+:\d+)\s+\$(\S+)\s+\$(\S+)\s+"
    r"([+-]?\$[\d,.]+)\s+([+-]?[\d.]+)%\s+(\S+)"
)

NOISE_DAYS = [
    "2026-04-06", "2026-04-30", "2026-03-10", "2026-02-03",
    "2026-02-04", "2026-02-05", "2026-02-09", "2026-02-10", "2026-02-11",
]

GOOD_DAYS = [
    "2026-02-03", "2026-02-04", "2026-02-11", "2026-02-09",
    "2026-02-12", "2026-02-13", "2026-02-02", "2026-02-06", "2026-01-28",
]

NOISE_DAYS_SET = {
    "2026-04-06", "2026-04-30", "2026-03-10",
    "2026-02-05", "2026-02-10",
    "2026-01-12", "2026-01-15", "2026-01-27", "2026-02-19",
}


def load_5min_bars(ticker, target_date_str):
    """Load 5-min bars for ticker on target_date_str from rolling cache files.

    Prefers the file that has the most data *before* the target date (largest
    target_dt - start) so daily charts get the full 30-day lookback window.
    """
    target_dt = datetime.strptime(target_date_str, "%Y-%m-%d")
    best_file = None
    best_coverage = timedelta(days=-1)
    for fname in os.listdir(CACHE_DIR):
        if not fname.startswith("alpaca_sip_5min_" + ticker + "_"):
            continue
        m = re.match(
            r"alpaca_sip_5min_" + ticker + r"_(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})\.json",
            fname
        )
        if not m:
            continue
        start = datetime.strptime(m.group(1), "%Y-%m-%d")
        end = datetime.strptime(m.group(2), "%Y-%m-%d")
        if start <= target_dt <= end:
            prior_days = target_dt - start
            if prior_days > best_coverage:
                best_coverage = prior_days
                best_file = os.path.join(CACHE_DIR, fname)
    if best_file is None:
        best_coverage = timedelta(days=-1)
        for fname in os.listdir(CACHE_DIR):
            if not fname.startswith("alpaca_5min_" + ticker + "_"):
                continue
            m = re.match(
                r"alpaca_5min_" + ticker + r"_(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})\.json",
                fname
            )
            if not m:
                continue
            start = datetime.strptime(m.group(1), "%Y-%m-%d")
            end = datetime.strptime(m.group(2), "%Y-%m-%d")
            if start <= target_dt <= end:
                prior_days = target_dt - start
                if prior_days > best_coverage:
                    best_coverage = prior_days
                    best_file = os.path.join(CACHE_DIR, fname)
    if best_file is None:
        return None
    with open(best_file) as f:
        raw = json.load(f)
    df = pd.DataFrame(raw["data"], index=raw["index"], columns=raw["columns"])
    df.index = pd.to_datetime(df.index, utc=True).tz_convert("US/Eastern")
    return df


def get_intraday_bars(ticker, date_str):
    """Return 5-min bars for a single trading day (09:30-16:00 ET)."""
    df = load_5min_bars(ticker, date_str)
    if df is None:
        return None
    mask = df.index.date == datetime.strptime(date_str, "%Y-%m-%d").date()
    day_df = df[mask].copy()
    day_df = day_df.between_time("09:30", "15:55")
    return day_df


def get_daily_bars(ticker, up_to_date_str, n_days=30):
    """Return up to n_days of daily bars ending on up_to_date_str from 5-min data."""
    df = load_5min_bars(ticker, up_to_date_str)
    if df is None:
        return None
    target = datetime.strptime(up_to_date_str, "%Y-%m-%d").date()
    df_reg = df.between_time("09:30", "15:55")
    daily = df_reg.groupby(df_reg.index.date).agg(
        Open=("Open", "first"),
        High=("High", "max"),
        Low=("Low", "min"),
        Close=("Close", "last"),
        Volume=("Volume", "sum"),
    )
    daily = daily[daily.index <= target].tail(n_days)
    daily.index = pd.to_datetime(daily.index)
    return daily


def parse_trades_from_log(date_str):
    """Parse trade rows from a replay log file."""
    log_path = os.path.join(LOG_DIR, date_str + ".log")
    if not os.path.exists(log_path):
        return []
    trades = []
    with open(log_path) as f:
        for line in f:
            m = TRADE_RE.match(line)
            if m:
                ticker = m.group(1)
                direction = m.group(2)
                shares = int(m.group(3))
                entry_time = m.group(4)
                exit_time = m.group(5)
                entry_price = float(m.group(6).replace(",", ""))
                exit_price = float(m.group(7).replace(",", ""))
                pnl_str = m.group(8).replace("$", "").replace(",", "")
                pnl = float(pnl_str)
                pct = float(m.group(9))
                exit_reason = m.group(10)
                is_short = "bearish" in direction.lower()
                trades.append({
                    "ticker": ticker,
                    "direction": direction,
                    "shares": shares,
                    "entry_time": entry_time,
                    "exit_time": exit_time,
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "pnl": pnl,
                    "pct": pct,
                    "exit_reason": exit_reason,
                    "is_short": is_short,
                    "win": pnl > 0,
                })
    return trades


def time_str_to_dt(date_str, time_str):
    """Convert date + 'HH:MM' to tz-aware ET datetime."""
    dt = datetime.strptime(date_str + " " + time_str, "%Y-%m-%d %H:%M")
    import pytz
    et = pytz.timezone("US/Eastern")
    return et.localize(dt)


def draw_candlesticks(ax, df):
    """Draw candlestick chart on ax from OHLC DataFrame."""
    width_mins = 4
    width = width_mins / (24 * 60)
    for idx, row in df.iterrows():
        o, h, l, c = row["Open"], row["High"], row["Low"], row["Close"]
        color = "#2ecc71" if c >= o else "#e74c3c"
        body_low = min(o, c)
        body_high = max(o, c)
        body_height = max(body_high - body_low, 0.01)
        rect = mpatches.Rectangle(
            (mdates.date2num(idx) - width / 2, body_low),
            width, body_height,
            facecolor=color, edgecolor=color, linewidth=0.5, zorder=3
        )
        ax.add_patch(rect)
        ax.plot(
            [mdates.date2num(idx), mdates.date2num(idx)],
            [l, h], color=color, linewidth=0.8, zorder=2
        )


def add_ema_lines(ax, df, spans=None):
    if spans is None:
        spans = [9, 20]
    colors = ["#e67e22", "#2980b9"]
    labels = ["EMA-9", "EMA-20"]
    for span, color, label in zip(spans, colors, labels):
        ema = df["Close"].ewm(span=span, adjust=False).mean()
        ax.plot(df.index, ema, color=color, linewidth=1.2, label=label, zorder=4)


def add_ma_lines(ax, df, spans=None):
    if spans is None:
        spans = [20, 50]
    colors = ["#2980b9", "#e67e22"]
    labels = ["MA-20", "MA-50"]
    for span, color, label in zip(spans, colors, labels):
        ma = df["Close"].rolling(span, min_periods=1).mean()
        ax.plot(df.index, ma, color=color, linestyle="--",
                linewidth=1.1, label=label, zorder=4)


def annotate_trades(ax, ax_vol, trades, date_str, ticker, df_bars):
    """Annotate intraday chart with trade markers, shading, and dashed levels."""
    tick_trades = [t for t in trades if t["ticker"] == ticker]
    annotation_y_offsets = {}
    for i, trade in enumerate(tick_trades):
        try:
            entry_dt = time_str_to_dt(date_str, trade["entry_time"])
            exit_dt = time_str_to_dt(date_str, trade["exit_time"])
        except Exception:
            continue
        ep = trade["entry_price"]
        xp = trade["exit_price"]
        is_short = trade["is_short"]
        entry_num = mdates.date2num(entry_dt)
        exit_num = mdates.date2num(exit_dt)
        entry_h = entry_num
        exit_h = exit_num
        if is_short:
            face_color = (1.0, 0.8, 0.8, 0.25)
            arrow_color = "#c0392b"
            marker_text = "▼ SHORT"
        else:
            face_color = (0.8, 0.9, 1.0, 0.25)
            arrow_color = "#27ae60"
            marker_text = "▲ BUY"
        ax.axhspan(min(ep, xp), max(ep, xp), xmin=0, xmax=1,
                   facecolor=face_color, zorder=1, alpha=0.3)
        ax.axvspan(entry_num, exit_num, facecolor=face_color, zorder=1, alpha=0.25)
        ax.axhline(ep, color=arrow_color, linestyle="--", linewidth=0.7,
                   alpha=0.7, zorder=2)
        ax.axhline(xp, color="#7f8c8d", linestyle="--", linewidth=0.7,
                   alpha=0.6, zorder=2)
        hold_mins = int((exit_dt - entry_dt).total_seconds() / 60)
        pnl_sign = "+" if trade["pnl"] >= 0 else ""
        label = "{} {}min\n{}${:.0f}".format(
            marker_text, hold_mins, pnl_sign, trade["pnl"]
        )
        ax.annotate(
            label,
            xy=(entry_num, ep),
            xytext=(entry_num, ep + (0.005 if not is_short else -0.005) * ep),
            fontsize=5.5,
            color=arrow_color,
            ha="left",
            va="bottom" if not is_short else "top",
            bbox=dict(boxstyle="round,pad=0.15", fc="white", alpha=0.7, lw=0),
            zorder=6,
        )


def add_volume_panel(ax, df, key_date=None):
    """Draw volume bars on a separate axis."""
    for idx, row in df.iterrows():
        o, c = row["Open"], row["Close"]
        color = "#2ecc71" if c >= o else "#e74c3c"
        width_mins = 4
        width = width_mins / (24 * 60)
        rect = mpatches.Rectangle(
            (mdates.date2num(idx) - width / 2, 0),
            width, row["Volume"],
            facecolor=color, edgecolor=color, linewidth=0.3, alpha=0.7
        )
        ax.add_patch(rect)
    ax.set_ylim(bottom=0)
    ax.yaxis.set_major_formatter(
        plt.FuncFormatter(lambda x, _: "{:.0f}K".format(x / 1000) if x >= 1000 else "{:.0f}".format(x))
    )
    ax.tick_params(labelsize=5)
    if key_date is not None:
        import pytz
        et = pytz.timezone("US/Eastern")
        kd = datetime.strptime(key_date, "%Y-%m-%d")
        kd_et = et.localize(kd)
        ax.axvspan(
            mdates.date2num(kd_et),
            mdates.date2num(kd_et + timedelta(days=1)),
            facecolor="yellow", alpha=0.25, zorder=1
        )


def format_xaxis_intraday(ax):
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M", tz="US/Eastern"))
    ax.xaxis.set_major_locator(mdates.HourLocator(interval=1, tz="US/Eastern"))
    ax.xaxis.set_minor_locator(mdates.MinuteLocator(byminute=[30], tz="US/Eastern"))
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, fontsize=6)


def format_xaxis_daily(ax):
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))
    ax.xaxis.set_major_locator(mdates.WeekdayLocator(byweekday=0))
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, fontsize=6)


def draw_intraday_panel(ax, ax_vol, ticker, date_str, trades, title_prefix=""):
    """Draw intraday chart for a ticker on a date."""
    df = get_intraday_bars(ticker, date_str)
    if df is None or df.empty:
        ax.text(0.5, 0.5, "No data: {} {}".format(ticker, date_str),
                ha="center", va="center", transform=ax.transAxes, fontsize=9)
        return
    ax.xaxis_date()
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M", tz="US/Eastern"))
    draw_candlesticks(ax, df)
    add_ema_lines(ax, df)
    tick_trades = [t for t in trades if t["ticker"] == ticker]
    n_trades = len(tick_trades)
    n_wins = sum(1 for t in tick_trades if t["win"])
    net_pnl = sum(t["pnl"] for t in tick_trades)
    net_pct = sum(t["pct"] for t in tick_trades)
    if n_trades > 0:
        avg_entry = np.mean([t["entry_price"] for t in tick_trades])
        net_pct_display = net_pnl / (avg_entry * tick_trades[0]["shares"] * n_trades) * 100 if avg_entry else 0
    else:
        net_pct_display = 0
    sign = "+" if net_pnl >= 0 else ""
    title = "{}{} {} — {}${:.0f} | {} trades | {} wins".format(
        title_prefix, ticker, date_str, sign, net_pnl, n_trades, n_wins
    )
    ax.set_title(title, fontsize=7.5, fontweight="bold", pad=2)
    annotate_trades(ax, ax_vol, trades, date_str, ticker, df)
    ax.legend(fontsize=5.5, loc="upper right", framealpha=0.7)
    ax.tick_params(labelsize=6)
    ax.grid(axis="y", linestyle="--", alpha=0.4)
    format_xaxis_intraday(ax)
    all_prices = list(df["High"]) + list(df["Low"])
    if all_prices:
        margin = (max(all_prices) - min(all_prices)) * 0.1
        ax.set_ylim(min(all_prices) - margin, max(all_prices) + margin)
    add_volume_panel(ax_vol, df)
    ax_vol.set_xlim(ax.get_xlim())
    ax_vol.xaxis_date()
    format_xaxis_intraday(ax_vol)


def draw_daily_panel(ax, ax_vol, ticker, key_date_str):
    """Draw 30-day daily chart."""
    df = get_daily_bars(ticker, key_date_str, n_days=30)
    if df is None or df.empty:
        ax.text(0.5, 0.5, "No data: {} {}".format(ticker, key_date_str),
                ha="center", va="center", transform=ax.transAxes, fontsize=9)
        return
    ax.xaxis_date()
    draw_candlesticks(ax, df)
    add_ma_lines(ax, df)
    import pytz
    et = pytz.timezone("US/Eastern")
    kd = datetime.strptime(key_date_str, "%Y-%m-%d")
    ax.axvspan(
        mdates.date2num(et.localize(kd)),
        mdates.date2num(et.localize(kd + timedelta(days=1))),
        facecolor="yellow", alpha=0.35, zorder=1, label="Key date"
    )
    if key_date_str in df.index.strftime("%Y-%m-%d"):
        kd_idx = df.index[df.index.strftime("%Y-%m-%d") == key_date_str]
        if len(kd_idx):
            row = df.loc[kd_idx[0]]
            ma20 = df["Close"].rolling(20, min_periods=1).mean()
            ma50 = df["Close"].rolling(50, min_periods=1).mean()
            kd_pos = df.index.get_loc(kd_idx[0])
            ma20_val = ma20.iloc[kd_pos]
            ma50_val = ma50.iloc[kd_pos]
            close_val = row["Close"]
            vs_ma20 = "above" if close_val > ma20_val else "below"
            vs_ma50 = "above" if close_val > ma50_val else "below"
            ax.text(
                0.02, 0.03,
                "MA20: {} | MA50: {}".format(vs_ma20, vs_ma50),
                transform=ax.transAxes, fontsize=6,
                bbox=dict(boxstyle="round,pad=0.2", fc="lightyellow", alpha=0.8),
                va="bottom"
            )
    ax.set_title("{} — 30-day daily (ends {})".format(ticker, key_date_str),
                 fontsize=7.5, pad=2)
    ax.legend(fontsize=5.5, loc="upper left", framealpha=0.7)
    ax.tick_params(labelsize=6)
    ax.grid(axis="y", linestyle="--", alpha=0.4)
    format_xaxis_daily(ax)
    all_prices = list(df["High"]) + list(df["Low"])
    if all_prices:
        margin = (max(all_prices) - min(all_prices)) * 0.1
        ax.set_ylim(min(all_prices) - margin, max(all_prices) + margin)
    ax_vol.xaxis_date()
    add_volume_panel(ax_vol, df, key_date=key_date_str)
    ax_vol.set_xlim(ax.get_xlim())
    format_xaxis_daily(ax_vol)


def build_pdf1():
    """PDF 1: 4 rows × 2 columns noise day patterns."""
    rows_spec = [
        ("SNDK", "2026-04-06", "Noise: "),
        ("CVNA", "2026-04-30", "Noise: "),
        ("COIN", "2026-03-10", "Noise: "),
        ("CRDO", "2026-02-03", "Best day: "),
    ]
    out_path = os.path.join(OUT_DIR, "noise_day_patterns.pdf")
    with PdfPages(out_path) as pdf:
        fig = plt.figure(figsize=(18, 26))
        fig.suptitle("Noise Day Patterns vs Best Day", fontsize=14,
                     fontweight="bold", y=0.99)
        outer_gs = gridspec.GridSpec(
            4, 2,
            figure=fig,
            hspace=0.55,
            wspace=0.3,
            top=0.975,
            bottom=0.03,
        )
        for row_i, (ticker, date_str, prefix) in enumerate(rows_spec):
            trades = parse_trades_from_log(date_str)
            for col_i in range(2):
                inner_gs = gridspec.GridSpecFromSubplotSpec(
                    2, 1,
                    subplot_spec=outer_gs[row_i, col_i],
                    height_ratios=[4, 1],
                    hspace=0.08,
                )
                ax_main = fig.add_subplot(inner_gs[0])
                ax_vol = fig.add_subplot(inner_gs[1], sharex=ax_main)
                if col_i == 0:
                    draw_intraday_panel(ax_main, ax_vol, ticker, date_str,
                                        trades, title_prefix=prefix)
                    plt.setp(ax_main.xaxis.get_majorticklabels(), visible=False)
                else:
                    draw_daily_panel(ax_main, ax_vol, ticker, date_str)
                    plt.setp(ax_main.xaxis.get_majorticklabels(), visible=False)
        pdf.savefig(fig, bbox_inches="tight")
        plt.close(fig)
    file_size = os.path.getsize(out_path)
    print("PDF 1: {} ({:.1f} KB)".format(out_path, file_size / 1024))
    return out_path


def compute_first_bar_ranges(dates, tickers_of_interest=None):
    """Compute first 5-min bar range as % of price for each date."""
    ranges = []
    for date_str in dates:
        trades = parse_trades_from_log(date_str)
        if tickers_of_interest is None:
            active_tickers = list(set(t["ticker"] for t in trades))
        else:
            active_tickers = tickers_of_interest
        for ticker in active_tickers:
            df = get_intraday_bars(ticker, date_str)
            if df is None or df.empty:
                continue
            first = df.iloc[0]
            bar_range_pct = (first["High"] - first["Low"]) / first["Open"] * 100
            ranges.append(bar_range_pct)
    return ranges


def compute_direction_flips(dates):
    """Count direction flips (same ticker both bullish & bearish) per date."""
    flips_per_date = []
    for date_str in dates:
        trades = parse_trades_from_log(date_str)
        by_ticker = {}
        for t in trades:
            tk = t["ticker"]
            if tk not in by_ticker:
                by_ticker[tk] = set()
            by_ticker[tk].add("short" if t["is_short"] else "long")
        flips = sum(1 for dirs in by_ticker.values() if len(dirs) > 1)
        flips_per_date.append(flips)
    return flips_per_date


def compute_exit_time_distribution(dates):
    """Return exit times (as hours from market open) for each date group."""
    times = []
    for date_str in dates:
        trades = parse_trades_from_log(date_str)
        for t in trades:
            h, m = map(int, t["exit_time"].split(":"))
            mins_from_open = (h * 60 + m) - (9 * 60 + 30)
            times.append(mins_from_open)
    return times


def compute_noise_scores(all_dates):
    """Score tickers by noise = appearances × (1 - win_rate)."""
    ticker_noise = set(NOISE_DAYS_SET)
    ticker_data = {}
    for date_str in all_dates:
        if date_str not in NOISE_DAYS_SET:
            continue
        trades = parse_trades_from_log(date_str)
        for t in trades:
            tk = t["ticker"]
            if tk not in ticker_data:
                ticker_data[tk] = {"count": 0, "wins": 0}
            ticker_data[tk]["count"] += 1
            if t["win"]:
                ticker_data[tk]["wins"] += 1
    scores = {}
    for tk, d in ticker_data.items():
        if d["count"] == 0:
            continue
        win_rate = d["wins"] / d["count"]
        scores[tk] = d["count"] * (1 - win_rate)
    return scores


def build_pdf2():
    """PDF 2: noise avoidance guide summary."""
    out_path = os.path.join(OUT_DIR, "noise_avoidance_guide.pdf")
    all_log_dates = [
        f.replace(".log", "")
        for f in os.listdir(LOG_DIR)
        if f.endswith(".log")
    ]
    all_log_dates.sort()
    actual_noise_days = [d for d in all_log_dates if d in NOISE_DAYS_SET]
    actual_good_days = [d for d in all_log_dates if d in set(GOOD_DAYS) and d not in NOISE_DAYS_SET]
    actual_good_days = actual_good_days[:9]
    noise_ranges = compute_first_bar_ranges(actual_noise_days)
    good_ranges = compute_first_bar_ranges(actual_good_days)
    noise_flips = compute_direction_flips(actual_noise_days)
    good_flips = compute_direction_flips(actual_good_days)
    noise_exits = compute_exit_time_distribution(actual_noise_days)
    good_exits = compute_exit_time_distribution(actual_good_days)
    noise_scores = compute_noise_scores(all_log_dates)
    top_tickers = sorted(noise_scores, key=lambda x: noise_scores[x], reverse=True)[:10]
    with PdfPages(out_path) as pdf:
        fig = plt.figure(figsize=(16, 20))
        fig.suptitle("Noise Avoidance Guide — Signal Patterns", fontsize=14,
                     fontweight="bold", y=0.99)
        gs = gridspec.GridSpec(2, 2, figure=fig, hspace=0.45, wspace=0.35,
                               top=0.96, bottom=0.05)
        ax1 = fig.add_subplot(gs[0, 0])
        bins = np.linspace(0, max((noise_ranges or [3]) + (good_ranges or [3])) * 1.1, 20)
        if noise_ranges:
            ax1.hist(noise_ranges, bins=bins, alpha=0.65, color="#e74c3c",
                     label="Noise days (n={})".format(len(noise_ranges)), density=True)
        if good_ranges:
            ax1.hist(good_ranges, bins=bins, alpha=0.65, color="#2ecc71",
                     label="Good days (n={})".format(len(good_ranges)), density=True)
        if noise_ranges:
            ax1.axvline(np.mean(noise_ranges), color="#c0392b", linestyle="--",
                        linewidth=1.5, label="Noise mean {:.2f}%".format(np.mean(noise_ranges)))
        if good_ranges:
            ax1.axvline(np.mean(good_ranges), color="#27ae60", linestyle="--",
                        linewidth=1.5, label="Good mean {:.2f}%".format(np.mean(good_ranges)))
        ax1.set_title("1. First-Bar Range (% of Price)", fontsize=10, fontweight="bold")
        ax1.set_xlabel("Range %", fontsize=8)
        ax1.set_ylabel("Density", fontsize=8)
        ax1.legend(fontsize=7)
        ax1.tick_params(labelsize=7)
        ax1.grid(axis="y", alpha=0.4)
        ax2 = fig.add_subplot(gs[0, 1])
        groups = ["Noise days", "Good days"]
        means = [
            np.mean(noise_flips) if noise_flips else 0,
            np.mean(good_flips) if good_flips else 0,
        ]
        bars = ax2.bar(groups, means, color=["#e74c3c", "#2ecc71"], alpha=0.8,
                       edgecolor="black", linewidth=0.5)
        for bar, val in zip(bars, means):
            ax2.text(bar.get_x() + bar.get_width() / 2,
                     bar.get_height() + 0.03,
                     "{:.1f}".format(val), ha="center", va="bottom", fontsize=9)
        ax2.set_title("2. Avg Direction Flips per Day", fontsize=10, fontweight="bold")
        ax2.set_ylabel("Avg # flips (same ticker both directions)", fontsize=8)
        ax2.tick_params(labelsize=8)
        ax2.grid(axis="y", alpha=0.4)
        ax2.set_ylim(0, max(means + [0.5]) * 1.4)
        ax3 = fig.add_subplot(gs[1, 0])
        max_mins = 390
        bins3 = np.arange(0, max_mins + 15, 15)
        if noise_exits:
            ax3.hist(noise_exits, bins=bins3, alpha=0.65, color="#e74c3c",
                     label="Noise days", density=True)
        if good_exits:
            ax3.hist(good_exits, bins=bins3, alpha=0.65, color="#2ecc71",
                     label="Good days", density=True)
        ax3.set_xticks(range(0, max_mins + 1, 60))
        tick_labels = ["09:30", "10:30", "11:30", "12:30", "13:30",
                       "14:30", "15:30", "16:30"]
        ax3.set_xticklabels(tick_labels[:len(range(0, max_mins + 1, 60))],
                            rotation=45, fontsize=6.5)
        ax3.set_title("3. Exit Time Distribution", fontsize=10, fontweight="bold")
        ax3.set_xlabel("Exit time (ET)", fontsize=8)
        ax3.set_ylabel("Density", fontsize=8)
        ax3.legend(fontsize=7)
        ax3.tick_params(labelsize=7)
        ax3.grid(axis="y", alpha=0.4)
        ax4 = fig.add_subplot(gs[1, 1])
        if top_tickers:
            scores = [noise_scores[t] for t in top_tickers]
            colors4 = ["#c0392b" if s > np.mean(scores) else "#e67e22"
                       for s in scores]
            bars4 = ax4.barh(top_tickers[::-1], scores[::-1],
                             color=colors4[::-1], alpha=0.8,
                             edgecolor="black", linewidth=0.5)
            for bar, val in zip(bars4, scores[::-1]):
                ax4.text(bar.get_width() + 0.05, bar.get_y() + bar.get_height() / 2,
                         "{:.1f}".format(val), va="center", fontsize=8)
        ax4.set_title("4. Ticker Noise Score\n(appearances × (1 − win_rate))",
                      fontsize=10, fontweight="bold")
        ax4.set_xlabel("Noise score", fontsize=8)
        ax4.tick_params(labelsize=7.5)
        ax4.grid(axis="x", alpha=0.4)
        if top_tickers:
            ax4.set_xlim(0, max(scores) * 1.25)
        fig.text(
            0.5, 0.005,
            "Noise days: {} | Good days: {}".format(
                ", ".join(sorted(actual_noise_days)),
                ", ".join(sorted(actual_good_days))
            ),
            ha="center", fontsize=6, style="italic", color="#555555"
        )
        pdf.savefig(fig, bbox_inches="tight")
        plt.close(fig)
    file_size = os.path.getsize(out_path)
    print("PDF 2: {} ({:.1f} KB)".format(out_path, file_size / 1024))
    return out_path


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    print("Building PDF 1: noise_day_patterns.pdf ...")
    pdf1 = build_pdf1()
    print("Building PDF 2: noise_avoidance_guide.pdf ...")
    pdf2 = build_pdf2()
    print("\nDone.")
    print("  PDF 1:", pdf1)
    print("  PDF 2:", pdf2)


if __name__ == "__main__":
    main()

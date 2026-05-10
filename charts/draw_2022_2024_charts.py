"""
Full-year best/worst week charts for 2022 and 2024, plus noise day pattern charts.
Outputs:
  charts/best_worst_2022.pdf  — 4 rows: 2 best-week days, 2 worst-week days
  charts/best_worst_2024.pdf  — 4 rows: 2 best-week days, 2 worst-week days
  charts/noise_2022.pdf       — 3 noise day intraday + daily, avoidance guide
  charts/noise_2024.pdf       — 3 noise day intraday + daily, avoidance guide
"""

import glob
import json
import os
from datetime import datetime, timedelta

import matplotlib
matplotlib.use("Agg")
import matplotlib.ticker as mticker
import matplotlib.patches as mpatches
import matplotlib.gridspec as gridspec
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

CACHE_DIR = "/Users/victorhuang/work/alpha_tech_tracker/market_data/cache"
LOG_BASE = "/Users/victorhuang/work/alpha_tech_tracker/logs"
OUT_DIR = "/Users/victorhuang/work/alpha_tech_tracker/charts"

# ---------------------------------------------------------------------------
# Actual trade annotations — prices extracted from replay logs
# ---------------------------------------------------------------------------
TRADE_ANNOTATIONS = {
    # 2022 Best week (Aug 1): CVNA Aug 5 +15.52%, COIN Aug 3 +13.10%
    ("CVNA", "2022-08-05"): dict(direction="long",  entry_time="09:45", exit_time="11:15",
                                  entry_price=38.53, exit_price=44.51, pnl_pct=15.52),
    ("COIN", "2022-08-03"): dict(direction="long",  entry_time="09:45", exit_time="13:40",
                                  entry_price=69.77, exit_price=78.91, pnl_pct=13.10),
    # 2022 Worst week (Sep 12): CVNA Sep 12 -4.58%, CVNA Sep 15 -4.40%
    ("CVNA", "2022-09-12"): dict(direction="long",  entry_time="09:50", exit_time="11:25",
                                  entry_price=41.88, exit_price=39.96, pnl_pct=-4.58),
    ("CVNA", "2022-09-15"): dict(direction="long",  entry_time="10:10", exit_time="10:55",
                                  entry_price=38.21, exit_price=36.53, pnl_pct=-4.40),

    # 2024 Best week (Nov 4): COIN Nov 6 +9.95%, CLS May 24 +4.53%
    ("COIN", "2024-11-06"): dict(direction="long",  entry_time="10:15", exit_time="15:05",
                                  entry_price=228.65, exit_price=251.39, pnl_pct=9.95),
    ("CLS",  "2024-05-24"): dict(direction="long",  entry_time="09:45", exit_time="13:00",
                                  entry_price=56.02, exit_price=58.56, pnl_pct=4.53),
    # 2024 Worst week (Feb 26): CVNA Feb 26 -2.87% (DD), Dec 26 APP -1.23% fallback
    ("CVNA", "2024-02-26"): dict(direction="long",  entry_time="09:45", exit_time="10:40",
                                  entry_price=73.03, exit_price=72.22, pnl_pct=-1.11),
    ("APP",  "2024-12-26"): dict(direction="long",  entry_time="09:45", exit_time="09:50",
                                  entry_price=347.18, exit_price=342.91, pnl_pct=-1.23),
}

# Representative noise days for each year
NOISE_DAYS_2022 = [
    ("CVNA", "2022-09-02"),   # -$393; CVNA shorts into a bounce
    ("COIN", "2022-07-12"),   # -$119; COIN/AMD two-sided chop
    ("MSTR", "2022-10-17"),   # -$119; MSTR direction flip
]
NOISE_DAYS_2024 = [
    ("MSTR", "2024-12-12"),   # -$148; MSTR/COIN holiday-week noise
    ("APP",  "2024-05-09"),   # -$203; APP fast fallbacks
    ("CRDO", "2024-04-29"),   # -$97;  CRDO fast fallbacks
]


# ---------------------------------------------------------------------------
# Data helpers (shared with existing chart scripts)
# ---------------------------------------------------------------------------

def find_cache_file(ticker, target_date_str):
    target_date = datetime.strptime(target_date_str, "%Y-%m-%d").date()
    for pattern in [
        os.path.join(CACHE_DIR, f"alpaca_sip_5min_{ticker}_*_*.json"),
        os.path.join(CACHE_DIR, f"alpaca_5min_{ticker}_*_*.json"),
        os.path.join(CACHE_DIR, f"alpaca_iex_5min_{ticker}_*_*.json"),
    ]:
        candidates = glob.glob(pattern)
        best, best_start = None, None
        for path in candidates:
            fname = os.path.basename(path)
            parts = fname.replace(".json", "").split("_")
            try:
                start = datetime.strptime(parts[-2], "%Y-%m-%d").date()
                end   = datetime.strptime(parts[-1],  "%Y-%m-%d").date()
            except ValueError:
                continue
            if start <= target_date <= end:
                if best is None or start > best_start:
                    best, best_start = path, start
        if best:
            return best
    return None


def load_5min_bars(ticker, target_date_str):
    path = find_cache_file(ticker, target_date_str)
    if path is None:
        print(f"  [WARN] No cache for {ticker} {target_date_str}")
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
    day_df = df[df.index.date == target].copy()
    lo = pd.Timestamp(f"{date_str} 09:30:00", tz="America/New_York")
    hi = pd.Timestamp(f"{date_str} 16:00:00", tz="America/New_York")
    return day_df[(day_df.index >= lo) & (day_df.index <= hi)]


def get_daily_bars(df, date_str, lookback=30):
    target = pd.Timestamp(date_str).date()
    subset = df[df.index.date <= target]
    grouped = subset.groupby(subset.index.date).agg(
        open=("open", "first"), high=("high", "max"),
        low=("low", "min"), close=("close", "last"), volume=("volume", "sum"),
    )
    grouped.index = pd.to_datetime(grouped.index)
    return grouped.tail(lookback)


def ema(series, span):
    return series.ewm(span=span, adjust=False).mean()


def sma(series, window):
    return series.rolling(window=window, min_periods=1).mean()


def draw_candles(ax, df, width=0.6):
    UP, DOWN = "#2ecc71", "#e74c3c"
    for i, (_, row) in enumerate(df.iterrows()):
        c = UP if row["close"] >= row["open"] else DOWN
        lo_body = min(row["open"], row["close"])
        hi_body = max(row["open"], row["close"])
        min_h = row["close"] * 0.0002
        rect = mpatches.FancyBboxPatch(
            (i - width / 2, lo_body), width, max(hi_body - lo_body, min_h),
            boxstyle="square,pad=0", linewidth=0, color=c, zorder=3,
        )
        ax.add_patch(rect)
        ax.plot([i, i], [row["low"], lo_body],  color=c, lw=0.8, zorder=2)
        ax.plot([i, i], [hi_body, row["high"]], color=c, lw=0.8, zorder=2)
    ax.set_xlim(-1, len(df))
    all_p = pd.concat([df["high"], df["low"]])
    pad = (all_p.max() - all_p.min()) * 0.05
    ax.set_ylim(all_p.min() - pad, all_p.max() + pad)


def time_to_idx(df, time_str, date_str):
    ts = pd.Timestamp(f"{date_str} {time_str}:00", tz="America/New_York")
    for i, t in enumerate(df.index):
        if t >= ts:
            return i
    return len(df) - 1


def plot_intraday(ax, ax_vol, ticker, date_str, ann=None):
    full_df = load_5min_bars(ticker, date_str)
    if full_df is None:
        ax.text(0.5, 0.5, f"No data\n{ticker} {date_str}",
                ha="center", va="center", transform=ax.transAxes, fontsize=11)
        ax_vol.set_visible(False)
        return

    df = get_intraday_bars(full_df, date_str)
    if df.empty:
        ax.text(0.5, 0.5, "No intraday data", ha="center", va="center",
                transform=ax.transAxes, fontsize=11)
        ax_vol.set_visible(False)
        return

    draw_candles(ax, df)
    xs = range(len(df))
    ax.plot(list(xs), ema(df["close"], 9).values,  color="orange",  lw=1.2, label="EMA-9",  zorder=4)
    ax.plot(list(xs), ema(df["close"], 20).values, color="#3498db", lw=1.2, label="EMA-20", zorder=4)

    if ann:
        shade = "mistyrose" if ann["direction"] == "short" else "lightblue"
        ei = time_to_idx(df, ann["entry_time"], date_str)
        xi = time_to_idx(df, ann["exit_time"],  date_str)
        ax.axvspan(ei - 0.5, xi + 0.5, color=shade, alpha=0.45, zorder=1)
        ep, xp = ann["entry_price"], ann["exit_price"]
        pct = ann["pnl_pct"]
        sign = "+" if pct >= 0 else ""
        ax.annotate(f"Entry ${ep:.2f}", xy=(ei, ep), xytext=(ei + 1.5, ep),
                    fontsize=7, color="navy",
                    arrowprops=dict(arrowstyle="->", color="navy", lw=0.8))
        ax.annotate(f"Exit ${xp:.2f}\n{sign}{pct:.2f}%",
                    xy=(xi, xp), xytext=(max(xi - 7, 0), xp),
                    fontsize=7, color="darkred" if pct < 0 else "darkgreen",
                    arrowprops=dict(arrowstyle="->", color="gray", lw=0.8))

    # hourly x-ticks
    seen, tpos, tlab = set(), [], []
    for i, ts in enumerate(df.index):
        if (ts.minute == 30 and ts.hour == 9) or (ts.minute == 0 and ts.hour > 9):
            lab = ts.strftime("%H:%M")
            if lab not in seen:
                seen.add(lab); tpos.append(i); tlab.append(lab)
    ax.set_xticks(tpos); ax.set_xticklabels(tlab, fontsize=7)
    ax.legend(fontsize=7, loc="upper right")
    ax.tick_params(axis="y", labelsize=7)
    ax.grid(axis="y", ls="--", lw=0.4, alpha=0.6)

    vol_colors = ["#2ecc71" if r["close"] >= r["open"] else "#e74c3c" for _, r in df.iterrows()]
    ax_vol.bar(range(len(df)), df["volume"].values, color=vol_colors, alpha=0.7, width=0.8)
    ax_vol.set_xlim(-1, len(df)); ax_vol.set_xticks([])
    ax_vol.tick_params(axis="y", labelsize=6)
    ax_vol.yaxis.set_major_formatter(
        mticker.FuncFormatter(lambda x, _: f"{int(x/1000)}k" if x >= 1000 else str(int(x)))
    )
    ax_vol.grid(axis="y", ls="--", lw=0.3, alpha=0.5)


def plot_daily(ax, ticker, date_str, lookback=30):
    full_df = load_5min_bars(ticker, date_str)
    if full_df is None:
        ax.text(0.5, 0.5, "No data", ha="center", va="center",
                transform=ax.transAxes, fontsize=11)
        return
    daily = get_daily_bars(full_df, date_str, lookback)
    if daily.empty:
        ax.text(0.5, 0.5, "No daily data", ha="center", va="center",
                transform=ax.transAxes, fontsize=11)
        return

    draw_candles(ax, daily)
    xs = list(range(len(daily)))
    ma20 = sma(daily["close"], 20)
    ma50 = sma(daily["close"], 50)
    ax.plot(xs, ma20.values, color="#3498db", lw=1.2, ls="--", label="MA-20", zorder=4)
    ax.plot(xs, ma50.values, color="orange",  lw=1.2, ls="--", label="MA-50", zorder=4)

    key_dt = pd.Timestamp(date_str).normalize()
    matches = [i for i, d in enumerate(daily.index.normalize()) if d == key_dt]
    if matches:
        ki = matches[0]
        ax.axvspan(ki - 0.5, ki + 0.5, color="yellow", alpha=0.5, zorder=1)
        close_v = daily["close"].iloc[ki]
        above20 = "Above MA-20" if close_v >= ma20.iloc[ki] else "Below MA-20"
        above50 = "Above MA-50" if close_v >= ma50.iloc[ki] else "Below MA-50"
        yr = daily["high"].max() - daily["low"].min()
        ax.text(ki, daily["high"].max() - yr * 0.05,
                f"{above20}\n{above50}", ha="center", va="top", fontsize=6.5,
                color="navy",
                bbox=dict(boxstyle="round,pad=0.2", facecolor="lightyellow",
                          alpha=0.8, edgecolor="gray"))

    # month x-ticks
    tpos, tlab, last_m = [], [], None
    for i, dt in enumerate(daily.index):
        if dt.month != last_m:
            tpos.append(i); tlab.append(dt.strftime("%b %d")); last_m = dt.month
    ax.set_xticks(tpos); ax.set_xticklabels(tlab, fontsize=7, rotation=30, ha="right")
    ax.legend(fontsize=7, loc="upper left")
    ax.tick_params(axis="y", labelsize=7)
    ax.grid(axis="y", ls="--", lw=0.4, alpha=0.6)


def make_row(fig, outer_gs, row_idx, ticker_intra, date_intra, ticker_daily, date_daily):
    cell_l = outer_gs[row_idx, 0]
    cell_r = outer_gs[row_idx, 1]
    inner = gridspec.GridSpecFromSubplotSpec(2, 1, subplot_spec=cell_l,
                                             height_ratios=[4, 1], hspace=0.05)
    ax_price = fig.add_subplot(inner[0])
    ax_vol   = fig.add_subplot(inner[1])
    ax_daily = fig.add_subplot(cell_r)

    ann = TRADE_ANNOTATIONS.get((ticker_intra, date_intra))
    plot_intraday(ax_price, ax_vol, ticker_intra, date_intra, ann)

    direction = ann["direction"].capitalize() if ann else ""
    pct = f"  {ann['pnl_pct']:+.2f}%" if ann else ""
    ax_price.set_title(f"{ticker_intra}  {date_intra} | {direction}{pct}", fontsize=8, pad=4)

    plot_daily(ax_daily, ticker_daily, date_daily)
    ax_daily.set_title(f"{ticker_daily} Daily (30-bar) ending {date_daily}", fontsize=8, pad=4)


# ---------------------------------------------------------------------------
# Best / worst week PDFs
# ---------------------------------------------------------------------------

def make_best_worst_pdf(year, rows, suptitle, outname):
    fig = plt.figure(figsize=(16, 6 * len(rows)))
    fig.suptitle(suptitle, fontsize=13, fontweight="bold", y=0.995)
    outer_gs = gridspec.GridSpec(len(rows), 2, figure=fig, hspace=0.55, wspace=0.28)
    for i, (ti, di, td, dd) in enumerate(rows):
        make_row(fig, outer_gs, i, ti, di, td, dd)
    out = os.path.join(OUT_DIR, outname)
    fig.savefig(out, bbox_inches="tight", dpi=150)
    plt.close(fig)
    print(f"Saved: {out}  ({os.path.getsize(out)/1024:.1f} KB)")


def make_pdf_2022():
    rows = [
        # Best week Aug 1: two biggest days
        ("CVNA", "2022-08-05", "CVNA", "2022-08-05"),  # +15.5%, long, trailing stop
        ("COIN", "2022-08-03", "COIN", "2022-08-03"),  # +13.1%, long, trailing stop
        # Worst week Sep 12: CVNA Bullish Cont losses
        ("CVNA", "2022-09-12", "CVNA", "2022-09-12"),  # -4.6% Cont into CPI reversal
        ("CVNA", "2022-09-15", "CVNA", "2022-09-15"),  # -4.4% second attempt same direction
    ]
    make_best_worst_pdf(
        2022, rows,
        "2022 Full-Year Best Week (Aug 1, +$2,605) & Worst Week (Sep 12, -$498)\n"
        "Best: CVNA/COIN bullish run — clean MA alignment, trailing-stop exits\n"
        "Worst: CVNA Bullish Cont into CPI reversal — counter-trend into MA resistance",
        "best_worst_2022.pdf",
    )


def make_pdf_2024():
    rows = [
        # Best week Nov 4: COIN election surge
        ("COIN", "2024-11-06", "COIN", "2024-11-06"),  # +9.95%, long, trailing stop
        # Best week May 20: CLS breakout
        ("CLS",  "2024-05-24", "CLS",  "2024-05-24"),  # +4.53%, long, trailing stop
        # Worst week Feb 26: CVNA Doubledown into reversal
        ("CVNA", "2024-02-26", "CVNA", "2024-02-26"),  # -1.11% primary + -2.87% DD
        # Worst week Dec 23: APP holiday fallback
        ("APP",  "2024-12-26", "APP",  "2024-12-26"),  # -1.23% fallback_20pct
    ]
    make_best_worst_pdf(
        2024, rows,
        "2024 Full-Year Best Weeks (Nov 4 +$1,612 & May 20 +$1,225) & "
        "Worst Weeks (Feb 26 -$292 & Dec 23 -$279)\n"
        "Best: COIN election surge (DD amplified), CLS AI-infra breakout — trending daily, trailing stops\n"
        "Worst: CVNA DD into failing long; APP/CRDO holiday-week fallback cluster",
        "best_worst_2024.pdf",
    )


# ---------------------------------------------------------------------------
# Noise day pattern PDFs — 3 noise examples + avoidance guide
# ---------------------------------------------------------------------------

def make_noise_pdf(year, noise_days, outname):
    n = len(noise_days)
    fig = plt.figure(figsize=(16, 6 * n + 5))
    fig.suptitle(
        f"{year} Noise Day Patterns — max single-trade gain < 0.5%\n"
        "All noise days share: tight first bar, fast fallback exits, direction flips, counter-trend signals",
        fontsize=12, fontweight="bold", y=0.995,
    )
    outer_gs = gridspec.GridSpec(n + 1, 2, figure=fig, hspace=0.6, wspace=0.28,
                                  height_ratios=[4] * n + [3])

    for i, (ticker, date_str) in enumerate(noise_days):
        cell_l = outer_gs[i, 0]
        cell_r = outer_gs[i, 1]
        inner = gridspec.GridSpecFromSubplotSpec(2, 1, subplot_spec=cell_l,
                                                  height_ratios=[4, 1], hspace=0.05)
        ax_price = fig.add_subplot(inner[0])
        ax_vol   = fig.add_subplot(inner[1])
        ax_daily = fig.add_subplot(cell_r)

        plot_intraday(ax_price, ax_vol, ticker, date_str, ann=None)
        ax_price.set_title(f"{ticker}  {date_str} — NOISE DAY (intraday 5-min)", fontsize=8, pad=4)
        plot_daily(ax_daily, ticker, date_str)
        ax_daily.set_title(f"{ticker} Daily (30-bar) ending {date_str}", fontsize=8, pad=4)

    # Bottom row: text avoidance guide spanning both columns
    ax_text = fig.add_subplot(outer_gs[n, :])
    ax_text.axis("off")

    guide = (
        f"{year} Noise Day Avoidance Rules — Validated Across All 4 Replay Years\n\n"
        "Rule 1 — M1 First-Bar Range Gate\n"
        "  Skip M1 entry if first 5-min bar (09:30–09:35) range < 1.5% of bar midpoint.\n"
        "  Noise days averaged 2.37% first-bar range vs 3.22% on good days.\n\n"
        "Rule 2 — Direction Flip Block\n"
        "  Once a ticker exits both long AND short on the same day, block further same-ticker entries.\n"
        "  Direction flips cost -$37 to -$272 per additional trade on noise days.\n\n"
        "Rule 3 — High-Noise-Ticker Fallback Guard\n"
        "  If a ticker from the list (CVNA, MSTR, COIN, CRDO, APP, AMD, CLS, MRVL) exits via\n"
        "  fallback_20pct within 5 min, block all same-ticker entries for the rest of the window.\n"
        "  These tickers appear on noise days in all 4 replay years.\n\n"
        "Rule 4 — M1 Volume Gate\n"
        "  Require first 5-min bar volume ≥ 1.5× (20-day ADV / 78 bars) before any M1 entry.\n"
        "  81% of fallback_20pct exits cluster at 09:50 — weak open = no institutional participation.\n\n"
        "Rule 5 — Daily Loss Circuit Breaker\n"
        "  Block new entries once daily realized P&L reaches -$150. Existing positions unaffected.\n"
        f"  Caps worst noise days: {year} noise days ranged -$17 to -$449 cap P&L.\n\n"
        f"Full-year {year} noise metrics: {year} had "
        + ("39/251 (15.5%)" if year == 2022 else "33/252 (13.1%)")
        + " noise days | Win rate 20-24% vs 41-44% on good days\n"
        "Fast exits ≤5 min: 31-35% | Of fast exits, losses: 80-83% | M1 fallback rate: 45-49%"
    )
    ax_text.text(0.02, 0.98, guide, transform=ax_text.transAxes,
                 fontsize=8.5, va="top", ha="left", family="monospace",
                 bbox=dict(boxstyle="round,pad=0.6", facecolor="#f8f8f8",
                           edgecolor="#cccccc", alpha=0.9))

    out = os.path.join(OUT_DIR, outname)
    fig.savefig(out, bbox_inches="tight", dpi=150)
    plt.close(fig)
    print(f"Saved: {out}  ({os.path.getsize(out)/1024:.1f} KB)")


if __name__ == "__main__":
    make_pdf_2022()
    make_pdf_2024()
    make_noise_pdf(2022, NOISE_DAYS_2022, "noise_2022.pdf")
    make_noise_pdf(2024, NOISE_DAYS_2024, "noise_2024.pdf")

#!/usr/bin/env python3
"""Generate QQQ weekly candlestick + VIX + strategy weekly P&L chart.

Layout:
  Panel 1 (top): QQQ weekly candlesticks with P&L bars overlaid on secondary y-axis
  Panel 2 (bottom): VIX weekly
"""

import os
import re
from datetime import date, timedelta

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.lines as mlines
import pandas as pd
import yfinance as yf
import numpy as np

LOG_DIRS = [
    "/Users/victorhuang/work/alpha_tech_tracker/logs/replay_2025_stock_4win",
    "/Users/victorhuang/work/alpha_tech_tracker/logs/replay_2026_stock_4win",
]
OUT = "/Users/victorhuang/work/alpha_tech_tracker/charts/pnl_qqq_vix_weekly_2025_2026.png"

GREEN = "#26a69a"
RED = "#ef5350"
PNL_GREEN = "#00e676"
PNL_RED = "#ff1744"
VIX_COLOR = "#ff9800"
BG = "#0d0d0d"
GRID = "#252525"
CANDLE_WIDTH = 0.55   # fraction of 1-unit slot
PNL_BAR_WIDTH = 0.55  # same slot width for overlay


def load_daily_pnl(log_dirs):
    results = {}
    for log_dir in log_dirs:
        if not os.path.isdir(log_dir):
            continue
        for fname in sorted(os.listdir(log_dir)):
            if not re.match(r"\d{4}-\d{2}-\d{2}\.log$", fname):
                continue
            d_str = fname.replace(".log", "")
            with open(os.path.join(log_dir, fname)) as f:
                for line in f:
                    m = re.search(r"cap:\s*([+-]?\$[\d,.]+)", line)
                    if m:
                        val = float(m.group(1).replace("$", "").replace(",", ""))
                        results[d_str] = val
    return results


def daily_to_weekly(daily):
    weeks = {}
    for d_str, pnl in sorted(daily.items()):
        d = date.fromisoformat(d_str)
        week_mon = d - timedelta(days=d.weekday())
        weeks[week_mon] = weeks.get(week_mon, 0.0) + pnl
    return weeks


def style_ax(ax):
    ax.set_facecolor(BG)
    ax.tick_params(colors="#888888", labelsize=8)
    for spine in ax.spines.values():
        spine.set_color(GRID)
    ax.grid(True, color=GRID, linewidth=0.4, linestyle="-", zorder=0)
    ax.yaxis.label.set_color("#888888")


def draw_candles(ax, x_vals, qqq_df):
    """Draw candlestick bodies and wicks onto ax using integer x positions."""
    hw = CANDLE_WIDTH / 2
    for xi, (_, row) in zip(x_vals, qqq_df.iterrows()):
        try:
            o = float(row["Open"])
            h = float(row["High"])
            l = float(row["Low"])
            c = float(row["Close"])
        except Exception:
            continue
        color = GREEN if c >= o else RED
        # wick
        ax.plot([xi, xi], [l, h], color=color, linewidth=0.9, zorder=3)
        # body
        body_lo = min(o, c)
        body_hi = max(o, c)
        body_h = max(body_hi - body_lo, (h - l) * 0.01)  # at least 1% of range
        rect = plt.Rectangle(
            (xi - hw, body_lo), CANDLE_WIDTH, body_h,
            linewidth=0, facecolor=color, zorder=4
        )
        ax.add_patch(rect)


def main():
    print("Fetching QQQ and VIX weekly data...")
    qqq_raw = yf.download("QQQ", start="2025-01-01", end="2026-05-10",
                          interval="1wk", auto_adjust=True, progress=False)
    vix_raw = yf.download("^VIX", start="2025-01-01", end="2026-05-10",
                          interval="1wk", auto_adjust=True, progress=False)

    # Flatten multi-index columns (yfinance >=0.2 returns MultiIndex)
    for df in [qqq_raw, vix_raw]:
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

    qqq = qqq_raw.dropna(subset=["Open", "High", "Low", "Close"])
    vix = vix_raw.dropna(subset=["Close"])
    print(f"QQQ rows: {len(qqq)}, VIX rows: {len(vix)}")

    print("Loading daily P&L from logs...")
    daily = load_daily_pnl(LOG_DIRS)
    weekly_pnl = daily_to_weekly(daily)
    print(f"Strategy weeks: {len(weekly_pnl)}, total P&L: ${sum(weekly_pnl.values()):,.0f}")

    # Numeric x-axis indexed to QQQ weekly dates
    qqq_dates = list(qqq.index)
    n = len(qqq_dates)
    x_vals = list(range(n))
    date_to_x = {d: i for i, d in enumerate(qqq_dates)}

    def snap_to_qqq(target_date):
        """Return x index for the QQQ week closest to target_date (within 5 days)."""
        ts = pd.Timestamp(target_date)
        closest = min(qqq_dates, key=lambda d: abs((d - ts).days))
        if abs((closest - ts).days) <= 6:
            return date_to_x[closest]
        return None

    # P&L bars aligned to QQQ x positions
    pnl_x, pnl_y = [], []
    for week_date, pnl in sorted(weekly_pnl.items()):
        xi = snap_to_qqq(week_date)
        if xi is not None:
            pnl_x.append(xi)
            pnl_y.append(pnl)

    # VIX aligned to QQQ x positions
    vix_x, vix_y = [], []
    for vd in vix.index:
        xi = snap_to_qqq(vd)
        if xi is not None:
            try:
                vix_x.append(xi)
                vix_y.append(float(vix.loc[vd, "Close"]))
            except Exception:
                pass

    # ── Figure ──────────────────────────────────────────────────────────────
    fig = plt.figure(figsize=(20, 11), facecolor=BG)
    fig.suptitle(
        "QQQ Weekly  |  VIX  |  Strategy Weekly P&L (Stock, $10k)  —  2025 to May 2026",
        color="white", fontsize=13, y=0.99
    )

    gs = fig.add_gridspec(2, 1, height_ratios=[3, 1], hspace=0.06)
    ax_qqq = fig.add_subplot(gs[0])
    ax_vix = fig.add_subplot(gs[1], sharex=ax_qqq)

    style_ax(ax_qqq)
    style_ax(ax_vix)

    ax_qqq.set_xlim(-1, n + 1)

    # ── Panel 1a: QQQ candlesticks (left y-axis) ────────────────────────────
    draw_candles(ax_qqq, x_vals, qqq)
    ax_qqq.set_ylabel("QQQ ($)", color="#888888", fontsize=9)
    ax_qqq.yaxis.tick_left()
    ax_qqq.tick_params(axis="y", colors="#888888")

    # ── Panel 1b: P&L bars on secondary y-axis (right) ──────────────────────
    ax_pnl = ax_qqq.twinx()
    ax_pnl.set_facecolor("none")  # transparent so QQQ shows through
    bar_colors = [PNL_GREEN if v >= 0 else PNL_RED for v in pnl_y]
    ax_pnl.bar(pnl_x, pnl_y, width=PNL_BAR_WIDTH, color=bar_colors, alpha=0.55, zorder=2)
    ax_pnl.axhline(0, color="#555555", linewidth=0.7, zorder=1)
    ax_pnl.set_ylabel("Weekly P&L ($)", color="#aaaaaa", fontsize=9)
    ax_pnl.tick_params(axis="y", colors="#aaaaaa", labelsize=8)
    ax_pnl.spines["top"].set_visible(False)
    ax_pnl.spines["right"].set_color(GRID)
    ax_pnl.spines["left"].set_color(GRID)
    ax_pnl.spines["bottom"].set_color(GRID)

    # Scale P&L axis so bars sit in the lower ~30% of the panel
    pnl_max = max(abs(v) for v in pnl_y)
    ax_pnl.set_ylim(-pnl_max * 1.2, pnl_max * 5)

    # ── Legend ───────────────────────────────────────────────────────────────
    leg_items = [
        mpatches.Patch(color=GREEN, label="QQQ Up week"),
        mpatches.Patch(color=RED, label="QQQ Down week"),
        mpatches.Patch(color=PNL_GREEN, alpha=0.7, label="P&L positive week"),
        mpatches.Patch(color=PNL_RED, alpha=0.7, label="P&L negative week"),
    ]
    ax_qqq.legend(handles=leg_items, loc="upper left", framealpha=0.2,
                  facecolor=BG, labelcolor="white", fontsize=8)

    # ── Panel 2: VIX ────────────────────────────────────────────────────────
    ax_vix.fill_between(vix_x, vix_y, alpha=0.35, color=VIX_COLOR)
    ax_vix.plot(vix_x, vix_y, color=VIX_COLOR, linewidth=1.3, zorder=3)
    for lvl in [20, 30, 40]:
        ax_vix.axhline(lvl, color=VIX_COLOR, linestyle="--", linewidth=0.5, alpha=0.45)
        ax_vix.text(n + 0.5, lvl, str(lvl), color=VIX_COLOR, fontsize=7, va="center")
    ax_vix.set_ylabel("VIX", color="#888888", fontsize=9)
    ax_vix.yaxis.tick_left()
    ax_vix.tick_params(axis="y", colors="#888888")

    # ── X-axis tick labels (one per month, bottom panel only) ───────────────
    tick_pos, tick_lbl = [], []
    prev_mo = None
    for i, d in enumerate(qqq_dates):
        mo = d.to_pydatetime().month
        mo_str = d.to_pydatetime().strftime("%b")
        yr_str = d.to_pydatetime().strftime("%Y")
        if mo != prev_mo:
            tick_pos.append(i)
            tick_lbl.append(mo_str if mo != 1 else f"Jan\n{yr_str}")
            prev_mo = mo

    ax_vix.set_xticks(tick_pos)
    ax_vix.set_xticklabels(tick_lbl, color="#888888", fontsize=8)
    plt.setp(ax_qqq.get_xticklabels(), visible=False)

    print(f"Saving {OUT} ...")
    plt.savefig(OUT, dpi=150, bbox_inches="tight", facecolor=BG)
    plt.close()
    print(f"Saved.")

    print(f"\nWeekly P&L  min=${min(pnl_y):,.0f}  max=${max(pnl_y):,.0f}")
    neg = [v for v in pnl_y if v < 0]
    print(f"Negative weeks: {len(neg)} / {len(pnl_y)}")


if __name__ == "__main__":
    main()

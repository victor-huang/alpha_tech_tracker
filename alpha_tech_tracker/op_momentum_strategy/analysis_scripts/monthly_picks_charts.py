"""Monthly process picks on daily candles: one PDF page per monthly checkpoint (Finding 46).

For one year of the monthly process walk-forward (fixed setups + the gated drive short, capped at --max-positions,
5 bps), each checkpoint's picks are drawn as daily candles with MA 8 / 20 / 50 / 200, 90 sessions before the month
and 10 after, the held month shaded. Each title gives the stock's move over the month (first open to last close)
and the strategy's $ on that ticker; the sixth panel lists the month. Prints the per-pick table, the monthly P&L
and the capital in use (each trading day's most money open at once, averaged).

  python -m alpha_tech_tracker.op_momentum_strategy.analysis_scripts.monthly_picks_charts --year 2024 \\
    --out alpha_tech_tracker/op_momentum_strategy/charts/top5_picks_2024.pdf
"""

import argparse
from datetime import timedelta

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.backends.backend_pdf import PdfPages  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

from alpha_tech_tracker.op_momentum_strategy.analysis_scripts import monthly_process_walk_forward as mp  # noqa: E402
from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.ticker_screen import fetch_daily  # noqa: E402

BEFORE, AFTER = 90, 10
MAS = ((8, "#e377c2"), (20, "#ff7f0e"), (50, "#1f77b4"), (200, "#7f7f7f"))
DAILY_HISTORY_DAYS = 420


def month_move(bars, start, end):
    """(first row, last row, % from the first session's open to the last session's close) of start..end."""
    i0 = bars.index.searchsorted(pd.Timestamp(start))
    i1 = bars.index.searchsorted(pd.Timestamp(end), side="right") - 1
    return i0, i1, 100 * (bars.Close.iloc[i1] / bars.Open.iloc[i0] - 1)


def draw(ax, bars, start, end, ticker, label, strategy_dollars):
    i0, i1, move = month_move(bars, start, end)
    lo, hi = max(0, i0 - BEFORE), min(len(bars), i1 + 1 + AFTER)
    view = bars.iloc[lo:hi]
    for x, b in enumerate(view.itertuples()):
        color = "#2ca02c" if b.Close >= b.Open else "#d62728"
        ax.vlines(x, b.Low, b.High, color=color, linewidth=0.6)
        ax.add_patch(Rectangle((x - 0.35, min(b.Open, b.Close)), 0.7, max(abs(b.Close - b.Open), 1e-6),
                               facecolor=color, edgecolor=color, linewidth=0.4))
    for n, color in MAS:
        ax.plot(range(len(view)), bars.Close.rolling(n).mean().iloc[lo:hi].values, color=color, linewidth=0.9,
                label=f"MA{n}")
    ax.axvspan(i0 - lo - 0.5, i1 - lo + 0.5, color="#ffd700", alpha=0.18)
    ax.set_title(f"{ticker}  {label}   stock {move:+.1f}%   strategy ${strategy_dollars:+,.0f}", fontsize=9,
                 color="#1a7f37" if strategy_dollars >= 0 else "#b42318")
    ticks = list(range(0, len(view), max(1, len(view) // 6)))
    ax.set_xticks(ticks)
    ax.set_xticklabels([view.index[t].strftime("%m-%d") for t in ticks], fontsize=7)
    ax.tick_params(axis="y", labelsize=7)
    ax.set_xlim(-1, len(view))
    ax.grid(alpha=0.2)
    return move


def page(pdf, start, days, names, daily, by, args):
    end, key = max(days), start.strftime("%Y-%m")
    label = f"{start:%b %d} – {end:%b %d %Y}"
    fig, axes = plt.subplots(3, 2, figsize=(11, 14))
    axes = axes.ravel()
    rows, lines = [], []
    for ax, ticker in zip(axes, names):
        dollars = by.get((key, ticker), 0.0)
        if ticker not in daily:
            ax.set_title(f"{ticker}: no daily bars")
            continue
        move = draw(ax, daily[ticker], start, end, ticker, label, dollars)
        rows.append({"month": key, "ticker": ticker, "stock %": round(move, 1), "strategy $": round(dollars)})
        lines.append(f"{ticker:6s} stock {move:+6.1f}%   strategy ${dollars:+8,.0f}")
    for ax in axes[len(names):5]:
        ax.axis("off")
    total = sum(r["strategy $"] for r in rows)
    if names:
        axes[0].legend(fontsize=7, loc="upper left")
    axes[5].axis("off")
    axes[5].text(0.02, 0.95, f"Checkpoint {start:%Y-%m-%d}\nheld {label}\n\n" + "\n".join(lines)
                 + f"\n\nmonth total ${total:+,.0f}\n\nPlan: fixed setups + gated drive short,\n"
                 f"${args.capital / args.picks:,.0f} a trade, max {args.max_positions} open, 5 bps.\n"
                 "Yellow band = held period; stock % = first open\nto last close of the period.",
                 va="top", family="monospace", fontsize=9)
    fig.suptitle(f"Top-{args.picks} picks, checkpoint {start:%Y-%m-%d}  (month ${total:+,.0f})", fontsize=13)
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    pdf.savefig(fig)
    plt.close(fig)
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--out", required=True, help="PDF path")
    known, rest = parser.parse_known_args(argv)
    args = mp.parse_args(["--year", str(known.year), "--rank-shorts", "switched", *rest])
    picks, data = mp.load_data(known.year, args)
    trades, _ = mp.run_plan("fixed", True, False, picks, data, args)
    three = mp.variants(trades, args)
    by = three["capped + costs"].groupby(["month", "ticker"]).dollars.sum()
    months = data["months"]
    tickers = sorted({t for names in picks.values() for t in names})
    daily = fetch_daily(tickers, min(months) - timedelta(days=DAILY_HISTORY_DAYS), data["end"])
    daily = {t: f.set_axis(pd.to_datetime([pd.Timestamp(d).date() for d in f.index]), axis=0) for t, f in daily.items()}
    rows = []
    with PdfPages(known.out) as pdf:
        for start in sorted(months):
            rows += page(pdf, start, months[start], picks[start], daily, by, args)
    table = pd.DataFrame(rows)
    print(table.to_string(index=False))
    monthly = three["capped + costs"].groupby("month").dollars.sum().round(0)
    print(monthly.to_frame("strategy $").assign(cum=monthly.cumsum()).to_string())
    pnl = three["capped + costs"].dollars.sum()
    average, peak = mp.capital_in_use(three["capped"], args.capital / args.picks)
    account = args.max_positions * args.capital / args.picks
    print(f"{known.year}: P&L ${pnl:+,.0f}; capital in use ${average:,.0f} average, ${peak:,.0f} peak; "
          f"{100 * pnl / average:.1f}% on capital in use, {100 * pnl / account:.1f}% on ${account:,.0f}")


if __name__ == "__main__":
    main()

"""Per-trade chart PDF for the large_top3 yearly book, reusing top_n_charts.py with its own summary page.
Usage: top3_charts.py <top3_year.pkl> <ohlc cache.pkl> <out.pdf>"""
import importlib.util

import matplotlib.pyplot as plt

SCRIPTS = "alpha_tech_tracker/research/top_performers_output/uptrend_formation/top_n_by_year/scripts"

spec = importlib.util.spec_from_file_location("top_n_charts", f"{SCRIPTS}/top_n_charts.py")
charts = importlib.util.module_from_spec(spec)
spec.loader.exec_module(charts)
charts.TIERS = ("Large",)


def summary_page(pdf, data):
    fig = plt.figure(figsize=(11, 8.5))
    fig.suptitle(f"{data['year']} large_top3: top 3 Large by 180-day / vol^0.5, no breakout slots (through "
                 f"{data['plain'].index[-1]:%Y-%m-%d})", fontsize=13)
    ax = fig.add_axes([0.06, 0.52, 0.9, 0.36])
    for label, s, c in (("top 3", data["plain"], "#1f77b4"), ("top 3 + short hedge", data["hedged"], "#d62728"),
                        ("QQQ", data["QQQ"], "#7f7f7f")):
        ax.plot(s.index, (s - 1) * 100, label=label, color=c, linewidth=1.4 if label != "QQQ" else 1)
    ax.axhline(0, color="black", linewidth=0.5)
    ax.set_ylabel("cumulative %")
    ax.legend(frameon=False)
    ax.grid(alpha=0.3)
    table = (data["monthly"] * 100).round(1)
    tax = fig.add_axes([0.08, 0.04, 0.36, 0.42])
    tax.axis("off")
    tb = tax.table(cellText=[[f"{v:+.1f}%" for v in row] for row in table.values], rowLabels=list(table.index),
                   colLabels=list(table.columns), loc="center")
    tb.auto_set_font_size(False)
    tb.set_fontsize(8)
    for (r, c), cell in tb.get_celld().items():
        if r > 0 and c >= 0:
            v = table.values[r - 1, c]
            cell.set_facecolor("#e8f5e9" if v > 0 else "#ffebee" if v < 0 else "white")
    tr = data["trades"]
    on = [cp.strftime("%m-%d") for cp, v in data["on"].items() if v]
    notes = ["Top 3, equal weight, checked every 10 trading days, 0.1% cost per trade.",
             "Large: 180-day return / vol_60d^0.5, trend filter, no breakout slots,",
             "25% trailing stop (stopped names wait in cash for the next checkpoint).",
             "Hedge: short the 15 weakest liquid Large names at 50% of the book while QQQ",
             "is below its 50- and 200-day and not above a falling 20-day.",
             f"Hedge on at: {', '.join(on) if on else 'none'}", "",
             f"{len(tr)} trades, {(tr['ret'] > 0).mean():.0%} winners, avg {tr['ret'].mean():+.1%}, "
             f"best {tr.loc[tr['ret'].idxmax(), 'symbol']} {tr['ret'].max():+.0%}, "
             f"worst {tr.loc[tr['ret'].idxmin(), 'symbol']} {tr['ret'].min():+.0%}", "",
             "Charts: daily candles, 8/20/50/200-day averages, holding period shaded",
             "(green = gain, red = loss), ordered by checkpoint. Charts show the unhedged trades."]
    fig.text(0.50, 0.44, "\n".join(notes), fontsize=7.5, va="top")
    pdf.savefig(fig)
    plt.close(fig)


charts.summary_page = summary_page

if __name__ == "__main__":
    charts.main()

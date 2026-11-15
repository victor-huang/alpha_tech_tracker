"""large_top3 (Large, 180-day / vol^0.5 score alone, no breakout slots, 25% trailing stop, 3 names) one year at a
time, plain and with the short hedge (20-day rebound hold-off). Usage: top3_book.py <dir> <year>"""
import importlib.util
import pickle
import sys

import pandas as pd

from alpha_tech_tracker.research.concentration import LARGE_SCORE_ONLY
from alpha_tech_tracker.research.recommended_rules import prepare_recommended_panel
from alpha_tech_tracker.research.selection_filters import parse_args, prepare_inputs, rank_variant
from alpha_tech_tracker.research.short_hedge import downtrend, weakest
from alpha_tech_tracker.research.uptrend_formation import REGIME_INDEX
from alpha_tech_tracker.research.walk_forward_tuning import variant_for

S, YEAR = sys.argv[1], int(sys.argv[2])
N = 3
SCRIPTS = "alpha_tech_tracker/research/top_performers_output/uptrend_formation/top_n_by_year/scripts"


def load(name, argv):
    saved = sys.argv
    sys.argv = argv
    spec = importlib.util.spec_from_file_location(name, f"{SCRIPTS}/{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    sys.argv = saved
    return mod


books = load("top_n_books", ["x", "unused", str(N), str(YEAR)])
overlay = load("hedge_overlay", ["x", S, str(YEAR)])


def main():
    inputs = prepare_inputs(parse_args(["--years", str(YEAR)]))
    close = inputs.close.loc[:f"{YEAR}-12-31"]
    panel = prepare_recommended_panel(inputs.panel, inputs.close)
    cps = list(inputs.checkpoints)
    ranked = rank_variant(panel, variant_for(LARGE_SCORE_ONLY), 15)
    ranked = ranked[ranked["tier"] == "Large"]
    eq, trades = books.simulate(books.ranked_picker(ranked), close[sorted(set(ranked["symbol"]))], cps, 0.25)
    on = downtrend(close[REGIME_INDEX], cps, rebound_hold_off=True)
    dates = close.index[close.index >= cps[0]]
    hedged = overlay.hedged_equity(eq, overlay.hedge_periods(close.loc[dates], cps, weakest(panel), on, dates), dates)
    qqq = close[REGIME_INDEX].loc[dates] / close[REGIME_INDEX].loc[dates].iloc[0]
    table = pd.DataFrame({"top3": overlay.monthly(eq), "top3+h": overlay.monthly(hedged), "QQQ": overlay.monthly(qqq)})
    table.index = table.index.strftime("%Y-%m")
    dd = lambda e: (e / e.cummax() - 1).min()  # noqa: E731
    table.loc["total"] = [eq.iloc[-1] - 1, hedged.iloc[-1] - 1, qqq.iloc[-1] - 1]
    table.loc["max_dd"] = [dd(eq), dd(hedged), dd(qqq)]
    print(f"== {YEAR} large_top3: {len(trades)} trades, win rate {(trades['ret'] > 0).mean():.0%}, "
          f"hedge on {int(on.sum())} checkpoints, data through {eq.index[-1].date()}")
    print((table * 100).round(1).to_string())
    top = trades.sort_values("ret", ascending=False)
    print("best:", ", ".join(f"{r.symbol} {r.ret:+.0%}" for r in top.head(3).itertuples()),
          "| worst:", ", ".join(f"{r.symbol} {r.ret:+.0%}" for r in top.tail(2).itertuples()))
    with open(f"{S}/top3_{YEAR}.pkl", "wb") as f:
        pickle.dump({"plain": eq, "hedged": hedged, "QQQ": qqq, "trades": trades, "monthly": table, "on": on,
                     "checkpoints": cps, "n": N, "year": YEAR, "Large": (eq, trades.assign(tier="Large"))}, f)


if __name__ == "__main__":
    main()

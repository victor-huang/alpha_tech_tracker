"""Add the short hedge (15 weakest liquid Large names at 50% of each book, while QQQ is below its 50- and 200-day
and not bouncing above a falling 20-day) to the saved top-N yearly books, day by day."""
import pickle
import sys

import pandas as pd

from alpha_tech_tracker.research.recommended_rules import prepare_recommended_panel
from alpha_tech_tracker.research.selection_filters import parse_args, prepare_inputs
from alpha_tech_tracker.research.short_hedge import BORROW_RATE, HEDGE_FRACTION, basket_turnover, downtrend, weakest
from alpha_tech_tracker.research.uptrend_formation import REGIME_INDEX

S, YEAR = sys.argv[1], int(sys.argv[2])
COST = 1e-3
TIERS = ("Large", "Mid", "Small")


def hedge_periods(close, cps, basket, on, dates):
    """Per checkpoint period: start and end day positions, the short basket's value relative to the start (None when
    off), and the hedge's cost at the start as a share of equity."""
    c = close.ffill()
    turnover = basket_turnover(basket, on)
    names = {cp: list(g["symbol"]) for cp, g in basket.groupby("checkpoint")}
    starts = list(dates.get_indexer(cps))
    ends = starts[1:] + [len(dates) - 1]
    periods = []
    for cp, a, b in zip(cps, starts, ends):
        cols = [s for s in names.get(cp, []) if s in c.columns]
        if on.get(cp, False) and cols:
            rel = (c[cols].iloc[a:b + 1] / c[cols].iloc[a]).mean(axis=1).values
            days = (dates[b] - dates[a]).days or 14
            cost = HEDGE_FRACTION * (COST * turnover.get(cp, 0.0) + BORROW_RATE * days / 365)
        else:
            rel, cost = None, 0.0
        periods.append((a, b, rel, cost))
    return periods


def hedged_equity(long_eq, periods, dates):
    long_eq = long_eq.reindex(dates).ffill()
    out = pd.Series(index=dates, dtype=float)
    h = long_eq.iloc[periods[0][0]]
    for a, b, rel, cost in periods:
        h *= 1 - cost
        base = long_eq.iloc[a]
        for k in range(a, b + 1):
            short = -HEDGE_FRACTION * (rel[k - a] - 1) if rel is not None else 0.0
            out.iloc[k] = h * (long_eq.iloc[k] / base + short)
        h = out.iloc[b]
    return out.dropna()


def monthly(eq):
    m = eq.resample("M").last()
    return m.pct_change().fillna(m.iloc[0] - 1)


def main():
    inputs = prepare_inputs(parse_args(["--years", str(YEAR)]))
    end = f"{YEAR}-12-31"
    close = inputs.close.loc[:end]
    panel = prepare_recommended_panel(inputs.panel, inputs.close)
    cps = list(inputs.checkpoints)
    on = downtrend(close[REGIME_INDEX], cps, rebound_hold_off=True)
    basket = weakest(panel)
    dates = close.index[close.index >= cps[0]]
    periods = hedge_periods(close.loc[dates], cps, basket, on, dates)
    out = {"on": on}
    for n in (5, 10):
        d = pickle.load(open(f"{S}/top{n}_{YEAR}.pkl", "rb"))
        res = {}
        for t in TIERS:
            h = hedged_equity(d[t][0], periods, dates)
            res[t] = {"plain": d[t][0], "hedged": h}
        res["QQQ"] = d["QQQ"]
        out[n] = res
        table = pd.DataFrame({f"{t}{n}": monthly(res[t]["plain"]) for t in TIERS})
        for t in TIERS:
            table[f"{t}{n}+h"] = monthly(res[t]["hedged"])
        table["QQQ"] = monthly(d["QQQ"])
        table.index = table.index.strftime("%Y-%m")
        table.loc["total"] = [((1 + table[c]).prod() - 1) for c in table.columns]
        table.loc["max_dd"] = [(lambda e: (e / e.cummax() - 1).min())(
            res[c.rstrip("+h").rstrip("0123456789")]["hedged" if c.endswith("+h") else "plain"]) if c != "QQQ"
            else (d["QQQ"] / d["QQQ"].cummax() - 1).min() for c in table.columns]
        out[f"monthly{n}"] = table
    on_cps = [cp.date().isoformat() for cp, v in on.items() if v]
    print(f"== {YEAR}: hedge on at {len(on_cps)} checkpoints {on_cps}")
    with pd.option_context("display.width", 250):
        for n in (5, 10):
            print((out[f"monthly{n}"] * 100).round(1).to_string())
    pickle.dump(out, open(f"{S}/hedged_{YEAR}.pkl", "wb"))


if __name__ == "__main__":
    main()

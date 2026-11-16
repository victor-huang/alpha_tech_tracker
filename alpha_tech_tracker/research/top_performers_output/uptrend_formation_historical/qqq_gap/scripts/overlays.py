"""Overlays on the Large top-10 book's daily equity, 2005-2026: QQQ core + book satellite, a right-tail regime
switch, and a rebound rule. Every signal uses only data known on the day before it is acted on."""
import os
import pickle
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import OUT, books, panel  # noqa: E402

YEARS = list(range(2005, 2027))
UP_PRE = [2006, 2007, 2010, 2011, 2012, 2013, 2014, 2015, 2016, 2017]
SWITCH_COST = 1e-3


def daily(year):
    path = f"{OUT}/base_book_{year}.pkl"
    if os.path.exists(path):
        with open(path, "rb") as f:
            b = pickle.load(f)
        eq, qqq = b["equity"], b["qqq"]
    else:
        b = books(year)[10]
        eq, qqq = b["Large"][0], b["QQQ"]
    qqq = qqq.reindex(eq.index).ffill()
    book_r = eq.pct_change().fillna(eq.iloc[0] - 1)
    return pd.DataFrame({"book": book_r, "qqq": qqq.pct_change().fillna(0.0), "qqq_px": qqq})


def doublers(year):
    """Large-tier names up 100%+ over the trailing 250 days, at each checkpoint."""
    p = panel(year)
    p = p[p["tier"] == "Large"]
    return p.groupby("checkpoint")["ret_250d"].apply(lambda r: int((r > 1.0).sum()))


def run_weights(d: pd.DataFrame, w_book: pd.Series) -> pd.Series:
    """Daily returns for a mix that holds w_book in the book, the rest in QQQ, with w_book decided the day before."""
    w = w_book.shift(1).fillna(w_book.iloc[0])
    cost = w.diff().abs().fillna(0.0) * SWITCH_COST
    return w * d["book"] + (1 - w) * d["qqq"] - cost


def strategies(year, d, dbl):
    out = {"QQQ": d["qqq"], "book": d["book"]}
    for core in (0.3, 0.5, 0.7):
        out[f"core{int(core * 100)}_qqq"] = run_weights(d, pd.Series(1 - core, index=d.index))

    sig = dbl.reindex(d.index, method="ffill").bfill()
    for k in (5, 10):
        out[f"switch_doublers>={k}"] = run_weights(d, (sig >= k).astype(float))
        out[f"tilt_doublers>={k}"] = run_weights(d, np.where(sig >= k, 0.8, 0.3) * pd.Series(1.0, index=d.index))

    px = d["qqq_px"]
    drawdown = px / px.rolling(60, min_periods=1).max() - 1
    for depth, hold in ((0.08, 40), (0.10, 40), (0.10, 60)):
        in_rebound = pd.Series(0.0, index=d.index)
        armed, left = False, 0
        ma20 = px.rolling(20, min_periods=1).mean()
        for i, day in enumerate(d.index):
            if drawdown.iloc[i] <= -depth:
                armed = True
            if armed and px.iloc[i] > ma20.iloc[i]:
                armed, left = False, hold
            if left > 0:
                in_rebound.iloc[i] = 1.0
                left -= 1
        out[f"rebound_{int(depth * 100)}pct_{hold}d"] = run_weights(d, 1 - in_rebound)
    return out


def main():
    rows = []
    for year in YEARS:
        d = daily(year)
        for name, r in strategies(year, d, doublers(year)).items():
            eq = (1 + r).cumprod()
            rows.append(dict(year=year, strategy=name, ret=eq.iloc[-1] - 1, max_dd=(eq / eq.cummax() - 1).min()))
        print(year, flush=True)
    res = pd.DataFrame(rows)
    res.to_csv(f"{OUT}/overlays_by_year.csv", index=False)

    wide = res.pivot(index="strategy", columns="year", values="ret")
    gap = wide.sub(wide.loc["QQQ"], axis=1)

    def cagr(cols):
        return ((1 + wide[cols]).prod(axis=1) ** (1 / len(cols)) - 1) * 100

    summary = pd.DataFrame({
        "pre_up_vs_qqq_avg": gap[UP_PRE].mean(axis=1) * 100,
        "pre_up_years_beat_qqq": (gap[UP_PRE] > 0).sum(axis=1),
        "cagr_2005_2017": cagr(list(range(2005, 2018))),
        "cagr_2018_2026": cagr(list(range(2018, 2027))),
        "cagr_2005_2026": cagr(YEARS),
        "worst_year": wide.min(axis=1) * 100,
        "worst_dd": res.groupby("strategy")["max_dd"].min() * 100,
    }).round(1).sort_values("cagr_2005_2026", ascending=False)
    summary.to_csv(f"{OUT}/overlays_summary.csv")
    (wide * 100).round(1).to_csv(f"{OUT}/overlays_wide.csv")
    print(summary.to_string())
    print((wide * 100).round(1).to_string())


main()

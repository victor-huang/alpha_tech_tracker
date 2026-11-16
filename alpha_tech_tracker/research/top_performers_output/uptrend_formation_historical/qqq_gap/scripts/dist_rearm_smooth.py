"""Fewer round trips for "distribution exit below the 200-day, re-exit below the 50-day": buffers, confirmation days,
minimum stays, weekly / checkpoint checks and a falling-50-day condition on the 50-day re-exit and re-entry."""
import os
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(HERE, "dist_reentry.py")).read().split("above_50 = close > ma50")[0]
ns = {"__file__": os.path.join(HERE, "dist_reentry.py")}
exec(compile(src, "dist_reentry", "exec"), ns)
OUT, d, bases, stats, run_off, DOWN_YEARS = (ns[k] for k in ("OUT", "d", "bases", "stats", "run_off", "DOWN_YEARS"))
close, ma50, ma200, below_both, is_dist = (ns[k] for k in ("close", "ma50", "ma200", "below_both", "is_dist"))
uptrend = ((close > ma50) & (close > ma200) & (ma50 > ma200)).values
C, M50, M200 = close.values, ma50.values, ma200.values
ma50_falling = (ma50 < ma50.shift(5)).values
dates = close.index
fridays = pd.Series(dates.dayofweek, index=dates)
week_end = (pd.Series(dates.isocalendar().week.values, index=dates) != pd.Series(dates.isocalendar().week.values, index=dates).shift(-1)).values
checkpoint_days = set(d.index[d["year"].ne(d["year"].shift())])  # first day of each book year
cp = np.zeros(len(dates), dtype=bool)
for y, g in d.groupby("year"):
    cp[np.searchsorted(dates.values, g.index[::10].values)] = True


def machine(band=0.0, confirm=1, min_stay=0, check=None, falling=False):
    off, n_switch = np.zeros(len(C), dtype=bool), 0
    in_cash, armed, last_entry, last_switch = False, False, 0, -10 ** 6
    below_run = above_run = 0
    for i in range(len(C)):
        below_run = below_run + 1 if C[i] < M50[i] * (1 - band) else 0
        above_run = above_run + 1 if C[i] > M50[i] * (1 + band) else 0
        can_act = (i - last_switch >= min_stay) and (check is None or check[i])
        n = is_dist[max(i - 24, last_entry):i + 1].sum()
        trigger = n >= 6 and C[i] < M50[i] and C[i] < M200[i]
        if not in_cash:
            if armed and uptrend[i]:
                armed = False
            re_exit = armed and below_run >= confirm and can_act and (not falling or ma50_falling[i])
            if trigger or re_exit:
                in_cash, armed, last_switch, n_switch = True, True, i, n_switch + 1
        elif above_run >= confirm and can_act:
            in_cash, last_entry, last_switch, n_switch = False, i + 1, i, n_switch + 1
        off[i] = in_cash
    return pd.Series(off, index=dates), n_switch


VARIANTS = {
    "base (previous best)": dict(),
    "band 1%": dict(band=0.01), "band 2%": dict(band=0.02), "band 3%": dict(band=0.03),
    "confirm 2 closes": dict(confirm=2), "confirm 3 closes": dict(confirm=3),
    "min stay 5d": dict(min_stay=5), "min stay 10d": dict(min_stay=10),
    "weekly close check": dict(check=week_end), "checkpoint check (10d)": dict(check=cp),
    "re-exit only if 50d falling": dict(falling=True),
    "band 1% + confirm 2": dict(band=0.01, confirm=2),
    "band 2% + 50d falling": dict(band=0.02, falling=True),
    "confirm 2 + 50d falling": dict(confirm=2, falling=True),
    "weekly + band 1%": dict(check=week_end, band=0.01),
}
rows, per_year = [], []
for name, kw in VARIANTS.items():
    off, n_sw = machine(**kw)
    for b, r0 in bases.items():
        by, dd = stats(run_off(r0, off), d["year"])
        rows.append(dict(base=b, rule=name, cagr=(1 + by).prod() ** (1 / len(by)) - 1, worst_dd=dd,
                         **{f"y{y}": by[y] for y in DOWN_YEARS}, days_cash=off.reindex(r0.index).mean(),
                         switches_per_yr=n_sw / (len(dates) / 252)))
        per_year.append(by.rename(f"{b}|{name}"))
n_ref = int(below_both.astype(int).diff().abs().sum())
for b, r0 in bases.items():
    for name, off, n_sw in (("[ref] none", pd.Series(False, index=dates), 0), ("[ref] 50/200 rule", below_both, n_ref)):
        by, dd = stats(run_off(r0, off), d["year"])
        rows.append(dict(base=b, rule=name, cagr=(1 + by).prod() ** (1 / len(by)) - 1, worst_dd=dd,
                         **{f"y{y}": by[y] for y in DOWN_YEARS}, days_cash=off.reindex(r0.index).mean(),
                         switches_per_yr=n_sw / (len(dates) / 252)))
        per_year.append(by.rename(f"{b}|{name}"))
res = pd.DataFrame(rows)
res.to_csv(f"{OUT}/dist_rearm_smooth_summary.csv", index=False)
pd.concat(per_year, axis=1).T.to_csv(f"{OUT}/dist_rearm_smooth_by_year.csv")
for c in ["cagr", "worst_dd", "y2008", "y2018", "y2022", "days_cash"]:
    res[c] = (res[c] * 100).round(1)
res["switches_per_yr"] = res["switches_per_yr"].round(1)
pd.set_option("display.width", 250)
for b, g in res.groupby("base", sort=False):
    print(f"== {b}"); print(g.drop(columns="base").sort_values("cagr", ascending=False).to_string(index=False))

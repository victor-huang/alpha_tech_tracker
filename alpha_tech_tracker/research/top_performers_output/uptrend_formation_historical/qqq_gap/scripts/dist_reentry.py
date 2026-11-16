"""Distribution-day exit (flat/down day on volume above the 20-day average and the day before; 6+ in 25 days; QQQ
below its 50-day) combined with the 50/200-day rule's re-entry, 2005-2026."""
import os
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(HERE, "dist_days.py")).read().split("VARIANTS = {")[0]
ns = {"__file__": os.path.join(HERE, "dist_days.py")}
exec(compile(src, "dist_days", "exec"), ns)
OUT, d, bases, stats, run_off, YEARS, DOWN_YEARS = (ns[k] for k in ("OUT", "d", "bases", "stats", "run_off", "YEARS", "DOWN_YEARS"))
close, vol, ret, avg_vol, ma50 = (ns[k] for k in ("close", "vol", "ret", "avg_vol", "ma50"))
ma200 = close.rolling(200).mean()
below_both = (close < ma50) & (close < ma200)
is_dist = ((ret <= 0.002) & (vol > avg_vol) & (vol > vol.shift(1))).fillna(False).astype(int).values


def machine(need, reenter, also_below_200=False, union=False):
    """In cash after `need`+ distribution days in 25 (counted since the last re-entry) with QQQ below its 50-day
    (and below its 200-day if also_below_200); out of cash when `reenter` is true. union: also in cash whenever the
    50/200-day rule says so."""
    off, events, in_cash, last_entry = pd.Series(False, index=close.index), [], False, 0
    for i, day in enumerate(close.index):
        n = is_dist[max(i - 24, last_entry):i + 1].sum()
        trigger = n >= need and close.iloc[i] < ma50.iloc[i] and (not also_below_200 or close.iloc[i] < ma200.iloc[i])
        if not in_cash and trigger:
            in_cash = True
            events.append(dict(day=day.date(), event="exit", close=round(close.iloc[i], 2), dist_days=int(n)))
        elif in_cash and reenter.iloc[i]:
            in_cash, last_entry = False, i + 1
            events.append(dict(day=day.date(), event="re-enter", close=round(close.iloc[i], 2)))
        off.iloc[i] = in_cash or (union and bool(below_both.iloc[i]))
    return off, pd.DataFrame(events)


above_50 = close > ma50
not_below_both = ~below_both
above_both = (close > ma50) & (close > ma200)
RULES = {
    "dist exit, re-enter above 50d (= 50/200 re-entry)": dict(need=6, reenter=above_50),
    "dist exit, re-enter above 50d and 200d": dict(need=6, reenter=above_both),
    "dist exit only below 200d too, 50/200 re-entry": dict(need=6, reenter=not_below_both, also_below_200=True),
    "50/200 rule OR dist exit (re-enter above 50d)": dict(need=6, reenter=above_50, union=True),
    "50/200 rule OR dist exit, 8 days": dict(need=8, reenter=above_50, union=True),
}
rows, per_year, logs = [], [], {}
for name, kw in RULES.items():
    off, ev = machine(**kw)
    logs[name] = ev
    for b, r0 in bases.items():
        by, dd = stats(run_off(r0, off), d["year"])
        rows.append(dict(base=b, rule=name, cagr=(1 + by).prod() ** (1 / len(by)) - 1, worst_dd=dd,
                         **{f"y{y}": by[y] for y in DOWN_YEARS}, days_cash=off.reindex(r0.index).mean(),
                         exits=int((ev["event"] == "exit").sum())))
        per_year.append(by.rename(f"{b}|{name}"))
for b, r0 in bases.items():
    for name, off in (("[ref] none", pd.Series(False, index=close.index)), ("[ref] 50/200 rule", below_both)):
        by, dd = stats(run_off(r0, off), d["year"])
        rows.append(dict(base=b, rule=name, cagr=(1 + by).prod() ** (1 / len(by)) - 1, worst_dd=dd,
                         **{f"y{y}": by[y] for y in DOWN_YEARS}, days_cash=off.reindex(r0.index).mean()))
        per_year.append(by.rename(f"{b}|{name}"))
res = pd.DataFrame(rows)
res.to_csv(f"{OUT}/dist_reentry_summary.csv", index=False)
pd.concat(per_year, axis=1).T.to_csv(f"{OUT}/dist_reentry_by_year.csv")
pd.concat([e.assign(rule=k) for k, e in logs.items()]).to_csv(f"{OUT}/dist_reentry_events.csv", index=False)
for c in ["cagr", "worst_dd", "y2008", "y2018", "y2022", "days_cash"]:
    res[c] = (res[c] * 100).round(1)
for b, g in res.groupby("base", sort=False):
    print(f"== {b}"); print(g.drop(columns="base").sort_values("cagr", ascending=False).to_string(index=False))
ev = logs["dist exit, re-enter above 50d (= 50/200 re-entry)"]
print("\nfirst exits around the down years:")
print(ev[ev["day"].astype(str).str[:4].isin(["2007", "2008", "2018", "2021", "2022"])].to_string(index=False))
by = pd.concat(per_year, axis=1).T
print((by.loc[["switch_QQQ|[ref] 50/200 rule", "switch_QQQ|dist exit, re-enter above 50d (= 50/200 re-entry)",
               "switch_QQQ|50/200 rule OR dist exit (re-enter above 50d)"]].T * 100).round(1).to_string())

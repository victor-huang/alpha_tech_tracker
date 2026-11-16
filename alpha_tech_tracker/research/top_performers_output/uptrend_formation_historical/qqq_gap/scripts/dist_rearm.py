"""Distribution-day exit + 50-day re-entry, with a re-exit: once a distribution exit has fired, any later close below
the 50-day sends the book back to cash (no new distribution days needed) until the rule is disarmed."""
import os
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(HERE, "dist_reentry.py")).read().split("above_50 = close > ma50")[0]
ns = {"__file__": os.path.join(HERE, "dist_reentry.py")}
exec(compile(src, "dist_reentry", "exec"), ns)
OUT, d, bases, stats, run_off, DOWN_YEARS = (ns[k] for k in ("OUT", "d", "bases", "stats", "run_off", "DOWN_YEARS"))
close, ma50, ma200, below_both, is_dist = (ns[k] for k in ("close", "ma50", "ma200", "below_both", "is_dist"))

above_50 = close > ma50
new_high = close >= close.rolling(252, min_periods=1).max()
above_50_streak = above_50.groupby((~above_50).cumsum()).cumsum()
uptrend = (close > ma50) & (close > ma200) & (ma50 > ma200)
DISARM = {
    "never (no re-exit)": pd.Series(True, index=close.index),
    "new 52-week high": new_high,
    "20 days above 50d": above_50_streak >= 20,
    "above 50d & 200d, 50d > 200d": uptrend,
    "above 50d & 200d, 50d > 200d, 10 days": uptrend.groupby((~uptrend).cumsum()).cumsum() >= 10,
}


def machine(disarm, need=6, also_below_200=False):
    off, events = pd.Series(False, index=close.index), []
    in_cash, armed, last_entry = False, False, 0
    for i, day in enumerate(close.index):
        n = is_dist[max(i - 24, last_entry):i + 1].sum()
        below50 = close.iloc[i] < ma50.iloc[i]
        trigger = n >= need and below50 and (not also_below_200 or close.iloc[i] < ma200.iloc[i])
        if not in_cash:
            if armed and disarm.iloc[i]:
                armed = False
            if trigger or (armed and below50):
                kind = "exit" if trigger else "re-exit"
                in_cash, armed = True, True
                events.append(dict(day=day.date(), event=kind, close=round(close.iloc[i], 2)))
        elif not below50:
            in_cash, last_entry = False, i + 1
            events.append(dict(day=day.date(), event="re-enter", close=round(close.iloc[i], 2)))
        off.iloc[i] = in_cash
    return off, pd.DataFrame(events)


rows, per_year, logs = [], [], {}
for also in (False, True):
    for dname, dis in DISARM.items():
        name = ("[dist & below 200d] " if also else "") + "disarm: " + dname
        off, ev = machine(dis, also_below_200=also)
        logs[name] = ev
        for b, r0 in bases.items():
            by, dd = stats(run_off(r0, off), d["year"])
            rows.append(dict(base=b, rule=name, cagr=(1 + by).prod() ** (1 / len(by)) - 1, worst_dd=dd,
                             **{f"y{y}": by[y] for y in DOWN_YEARS}, days_cash=off.reindex(r0.index).mean(),
                             exits=int(ev["event"].isin(["exit", "re-exit"]).sum())))
            per_year.append(by.rename(f"{b}|{name}"))
for b, r0 in bases.items():
    for name, off in (("[ref] none", pd.Series(False, index=close.index)), ("[ref] 50/200 rule", below_both)):
        by, dd = stats(run_off(r0, off), d["year"])
        rows.append(dict(base=b, rule=name, cagr=(1 + by).prod() ** (1 / len(by)) - 1, worst_dd=dd,
                         **{f"y{y}": by[y] for y in DOWN_YEARS}, days_cash=off.reindex(r0.index).mean()))
        per_year.append(by.rename(f"{b}|{name}"))
res = pd.DataFrame(rows)
res.to_csv(f"{OUT}/dist_rearm_summary.csv", index=False)
byy = pd.concat(per_year, axis=1).T
byy.to_csv(f"{OUT}/dist_rearm_by_year.csv")
pd.concat([e.assign(rule=k) for k, e in logs.items()]).to_csv(f"{OUT}/dist_rearm_events.csv", index=False)
for c in ["cagr", "worst_dd", "y2008", "y2018", "y2022", "days_cash"]:
    res[c] = (res[c] * 100).round(1)
for b, g in res.groupby("base", sort=False):
    print(f"== {b}"); print(g.drop(columns="base").sort_values("cagr", ascending=False).to_string(index=False))
best = res[res.base == "switch_QQQ"].sort_values("cagr", ascending=False)["rule"].iloc[0]
print("\nby year, switch_QQQ:", best)
print((byy.loc[["switch_QQQ|[ref] none", "switch_QQQ|[ref] 50/200 rule", f"switch_QQQ|{best}"]].T * 100).round(1).to_string())

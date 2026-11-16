"""O'Neil follow-through-day re-entry, 2005-2026.

In cash, track the rally attempt: the correction low is the lowest close since the exit; day 1 is the first up close
after it; a close below the low resets the attempt, and an attempt with no follow-through by day FTD_TO is dropped,
so the next up close starts a new one (O'Neil keeps the attempt alive until the low is undercut). A follow-through day is day FTD_FROM..FTD_TO of the
attempt with a gain of at least GAIN on volume above the day before; re-enter at that close (act next day). With
`fail_exit`, a close below the rally attempt's low before the uptrend is confirmed (QQQ above both averages, 50-day above
200-day) sends the book back to cash. Distribution days are counted only since the last re-entry.
"""
import os
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(HERE, "dist_reentry.py")).read().split("above_50 = close > ma50")[0]
ns = {"__file__": os.path.join(HERE, "dist_reentry.py")}
exec(compile(src, "dist_reentry", "exec"), ns)
OUT, d, bases, stats, run_off, DOWN_YEARS = (ns[k] for k in ("OUT", "d", "bases", "stats", "run_off", "DOWN_YEARS"))
close, vol, ret, ma50, ma200, below_both, is_dist = (ns[k] for k in ("close", "vol", "ret", "ma50", "ma200", "below_both", "is_dist"))
uptrend = (close > ma50) & (close > ma200) & (ma50 > ma200)
C, V, R = close.values, vol.values, ret.values


def machine(exit_kind, ftd_to, gain, fail_exit, ftd_from=4):
    off, events = pd.Series(False, index=close.index), []
    in_cash, last_entry = False, 0
    low = day1 = None
    armed_low = None
    for i, day in enumerate(close.index):
        if not in_cash:
            n = is_dist[max(i - 24, last_entry):i + 1].sum()
            b50, b200 = C[i] < ma50.iloc[i], C[i] < ma200.iloc[i]
            if exit_kind == "dist":
                trig = n >= 6 and b50
            elif exit_kind == "dist_below_200":
                trig = n >= 6 and b50 and b200
            else:
                trig = bool(below_both.iloc[i])
            if armed_low is not None and uptrend.iloc[i]:
                armed_low = None
            failed = fail_exit and armed_low is not None and C[i] < armed_low
            if trig or failed:
                in_cash, low, day1 = True, C[i], None
                events.append(dict(day=day.date(), event="exit" if trig else "failed FTD", close=round(C[i], 2)))
        else:
            if C[i] < low:
                low, day1 = C[i], None
            elif day1 is None and R[i] > 0:
                day1 = i
            elif day1 is not None:
                k = i - day1 + 1
                if ftd_from <= k <= ftd_to and R[i] >= gain and V[i] > V[i - 1]:
                    in_cash, last_entry, armed_low = False, i + 1, low
                    events.append(dict(day=day.date(), event=f"FTD day {k}", close=round(C[i], 2)))
                elif k > ftd_to:
                    day1 = None  # stale attempt: the next up close starts a new day 1
        off.iloc[i] = in_cash
    return off, pd.DataFrame(events)


EXITS = {"dist": "dist 6/25 & <50d", "dist_below_200": "dist 6/25 & <50d & <200d", "ma": "50/200 rule exit"}
rows, per_year, logs = [], [], {}
for ek, elabel in EXITS.items():
    for ftd_to in (7, 10):
        for gain in (0.0125, 0.017):
            for fail in (False, True):
                name = f"{elabel} | FTD d4-{ftd_to} +{gain:.2%}{' +fail exit' if fail else ''}"
                off, ev = machine(ek, ftd_to, gain, fail)
                logs[name] = ev
                for b, r0 in bases.items():
                    by, dd = stats(run_off(r0, off), d["year"])
                    rows.append(dict(base=b, rule=name, cagr=(1 + by).prod() ** (1 / len(by)) - 1, worst_dd=dd,
                                     **{f"y{y}": by[y] for y in DOWN_YEARS}, days_cash=off.reindex(r0.index).mean(),
                                     exits=int((~ev["event"].str.startswith("FTD")).sum()) if len(ev) else 0))
                    per_year.append(by.rename(f"{b}|{name}"))
for b, r0 in bases.items():
    for name, off in (("[ref] none", pd.Series(False, index=close.index)), ("[ref] 50/200 rule", below_both)):
        by, dd = stats(run_off(r0, off), d["year"])
        rows.append(dict(base=b, rule=name, cagr=(1 + by).prod() ** (1 / len(by)) - 1, worst_dd=dd,
                         **{f"y{y}": by[y] for y in DOWN_YEARS}, days_cash=off.reindex(r0.index).mean()))
        per_year.append(by.rename(f"{b}|{name}"))
# best candidate from the re-exit test, for comparison
res = pd.DataFrame(rows)
res.to_csv(f"{OUT}/ftd_summary.csv", index=False)
byy = pd.concat(per_year, axis=1).T
byy.to_csv(f"{OUT}/ftd_by_year.csv")
pd.concat([e.assign(rule=k) for k, e in logs.items()]).to_csv(f"{OUT}/ftd_events.csv", index=False)
for c in ["cagr", "worst_dd", "y2008", "y2018", "y2022", "days_cash"]:
    res[c] = (res[c] * 100).round(1)
pd.set_option("display.width", 250)
for b, g in res.groupby("base", sort=False):
    print(f"== {b}"); print(g.drop(columns="base").sort_values("cagr", ascending=False).to_string(index=False))

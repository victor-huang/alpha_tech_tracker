"""Distribution-day exit, capitulation + follow-through re-entry, tested on QQQ and the doubler switch, 2005-2026.

Exit to cash when, within the last 25 trading days, QQQ had at least 6 distribution days and closes below its 50-day
average. A distribution day: QQQ near flat (|return| <= FLAT), volume above its 20-day average and above the day
before. Re-enter after a capitulation day (a loss among the worst LOSS_PCT of the last 252 days on volume >= VOL_X
times the 20-day average), followed within 10 days by a +2% day and then, within 10 more days, a +1% day on
above-average volume. Signals are taken at the close and acted on the next day; cash earns the T-bill.
"""
import os

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(HERE, "downside.py")).read().split("# 1. Timeline")[0]
ns = {"__file__": os.path.join(HERE, "downside.py")}
exec(compile(src, "downside", "exec"), ns)
OUT, d, tbill, bases, stats, sig = ns["OUT"], ns["d"], ns["tbill"], ns["bases"], ns["stats"], ns["sig"]
YEARS, DOWN_YEARS = ns["YEARS"], ns["DOWN_YEARS"]

px = pd.read_pickle(f"{OUT}/qqq_ohlcv.pkl")
close, vol = px["Close"], px["Volume"]
ret = close.pct_change()
avg_vol = vol.rolling(20).mean().shift(1)
ma50 = close.rolling(50).mean()


def states(flat=0.002, need=6, window=25, loss_pct=0.02, vol_x=1.5, follow=10, fallback=None, dist="flat"):
    """Daily risk-off flag (True = in cash) and the list of exit / re-entry events."""
    if dist == "flat":
        is_dist = (ret.abs() <= flat) & (vol > avg_vol) & (vol > vol.shift(1))
    elif dist == "flat_or_down":  # corrected spec: near flat (up at most FLAT) or any down day, on higher volume
        is_dist = (ret <= flat) & (vol > avg_vol) & (vol > vol.shift(1))
    elif dist == "down":  # O'Neil-style: down 0.2%+ on volume above the 20-day average and the day before
        is_dist = (ret <= -0.002) & (vol > avg_vol) & (vol > vol.shift(1))
    is_dist = is_dist.fillna(False).astype(int).values
    worst = ret.rolling(252, min_periods=120).quantile(loss_pct)
    capitulation = (ret <= worst) & (vol >= vol_x * avg_vol)

    off, events = pd.Series(False, index=close.index), []
    in_cash, cap_day, up2_day = False, None, None
    dates = close.index
    last_entry = 0
    count = pd.Series(0, index=dates)
    for i, day in enumerate(dates):
        # distribution days in the window, counted only since the last re-entry
        count.iloc[i] = is_dist[max(i - window + 1, last_entry):i + 1].sum()
        if not in_cash:
            if count.iloc[i] >= need and close.iloc[i] < ma50.iloc[i]:
                in_cash, cap_day, up2_day = True, None, None
                events.append(dict(day=day.date(), event="exit", close=close.iloc[i], dist_days=int(count.iloc[i])))
        else:
            if capitulation.iloc[i]:
                cap_day, up2_day = i, None
            elif cap_day is not None and up2_day is None and ret.iloc[i] >= 0.02 and i - cap_day <= follow:
                up2_day = i
            elif up2_day is not None and ret.iloc[i] >= 0.01 and vol.iloc[i] > avg_vol.iloc[i] and i - up2_day <= follow:
                in_cash, last_entry = False, i + 1
                events.append(dict(day=day.date(), event="re-enter", close=close.iloc[i],
                                   capitulation=dates[cap_day].date()))
            if cap_day is not None and up2_day is None and i - cap_day > follow:
                cap_day = None
            if up2_day is not None and i - up2_day > follow:
                cap_day, up2_day = None, None
            if in_cash and fallback == "above_50d" and close.iloc[i] > ma50.iloc[i] and \
                    (events[-1]["event"] == "exit") and (day - pd.Timestamp(events[-1]["day"])).days > 5:
                in_cash, last_entry = False, i + 1
                events.append(dict(day=day.date(), event="re-enter (fallback)", close=close.iloc[i]))
        off.iloc[i] = in_cash
    return off, pd.DataFrame(events)


def run_off(base_r, off):
    o = off.reindex(base_r.index).ffill().fillna(False).shift(1).fillna(False).astype(bool)
    return base_r.where(~o, tbill) - o.astype(int).diff().abs().fillna(0) * 1e-3


VARIANTS = {
    "flat/down, 6 in 25d (as specified)": dict(dist="flat_or_down"),
    "flat/down, 7 in 25d": dict(dist="flat_or_down", need=7),
    "flat/down, 8 in 25d": dict(dist="flat_or_down", need=8),
    "flat/down, 6 in 25d, capit. worst 5%": dict(dist="flat_or_down", loss_pct=0.05),
    "flat/down, 6 in 25d, capit. worst 5%, vol 1.2x": dict(dist="flat_or_down", loss_pct=0.05, vol_x=1.2),
    "flat/down, 6 in 25d +fallback above 50d": dict(dist="flat_or_down", fallback="above_50d"),
    "flat/down, 8 in 25d +fallback above 50d": dict(dist="flat_or_down", need=8, fallback="above_50d"),
}

rows, logs, per_year = [], {}, []
for name, kw in VARIANTS.items():
    off, ev = states(**kw)
    logs[name] = ev
    for base_name, base_r in bases.items():
        r = run_off(base_r, off)
        by, dd = stats(r, d["year"])
        b0, _ = stats(base_r, d["year"])
        up = [y for y in YEARS if y not in DOWN_YEARS]
        rows.append(dict(base=base_name, rule=name, cagr=(1 + by).prod() ** (1 / len(by)) - 1, worst_dd=dd,
                         **{f"y{y}": by[y] for y in DOWN_YEARS}, up_years_cost=(by[up] - b0[up]).mean(),
                         days_cash=off.reindex(base_r.index).fillna(False).mean(),
                         exits=int((ev["event"] == "exit").sum()) if len(ev) else 0))
        per_year.append(by.rename(f"{base_name}|{name}"))
for base_name, base_r in bases.items():
    for ref, flag in (("none", pd.Series(False, index=base_r.index)), ("below_50_and_200d", sig["below_50_and_200d"])):
        r = ns["run"](base_r, flag, "cash", tbill)
        by, dd = stats(r, d["year"])
        rows.append(dict(base=base_name, rule=f"[ref] {ref}", cagr=(1 + by).prod() ** (1 / len(by)) - 1, worst_dd=dd,
                         **{f"y{y}": by[y] for y in DOWN_YEARS}, days_cash=flag.mean()))
        per_year.append(by.rename(f"{base_name}|[ref] {ref}"))

res = pd.DataFrame(rows)
res.to_csv(f"{OUT}/dist_days_v2_summary.csv", index=False)
pd.concat(per_year, axis=1).T.to_csv(f"{OUT}/dist_days_v2_by_year.csv")
pd.concat([e.assign(rule=k) for k, e in logs.items()]).to_csv(f"{OUT}/dist_days_v2_events.csv", index=False)
for c in ["cagr", "worst_dd", "y2008", "y2018", "y2022", "up_years_cost", "days_cash"]:
    res[c] = (res[c] * 100).round(1)
for b, g in res.groupby("base", sort=False):
    print(f"== {b}")
    print(g.drop(columns="base").sort_values("cagr", ascending=False).to_string(index=False))
for k in ("flat/down, 6 in 25d (as specified)", "flat/down, 6 in 25d, capit. worst 5%"):
    print("== events: " + k); print(logs[k].round(2).to_string(index=False))

"""Down years (2008, 2018, 2022): which warning signals fired before the big drop, and does moving to cash or shorting
QQQ when they fire pay across all of 2005-2026?

Signals are computed on a day's close and acted on the next day. Cash earns the 13-week T-bill (^IRX). A short QQQ
position earns -QQQ plus the T-bill on the cash, minus a 0.5% a year borrow/financing charge.
"""
import os

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(HERE, "mag7.py")).read().replace("\nmain()\n", "\n")
m = {"__file__": os.path.join(HERE, "mag7.py")}
exec(compile(src, "mag7", "exec"), m)
OUT, YEARS = m["OUT"], m["YEARS"]
ov = m["ov"]
SHORT_COST = 0.005 / 252
DOWN_YEARS = (2008, 2018, 2022)


def macro():
    d = pd.read_pickle(f"{OUT}/macro_daily.pkl")
    q = d["QQQ"]
    ma50, ma200 = q.rolling(50).mean(), q.rolling(200).mean()
    credit = d["HYG"] / d["LQD"]
    s = pd.DataFrame(index=d.index)
    s["below_200d"] = q < ma200
    s["below_50_and_200d"] = (q < ma50) & (q < ma200)
    s["death_cross"] = ma50 < ma200
    ma20 = q.rolling(20).mean()
    s["below_20_and_200d"] = (q < ma20) & (q < ma200)
    s["ma20_below_50_falling"] = (ma20 < ma50) & (ma20 < ma20.shift(5))
    s["ma20_below_50_falling_and_below_200d"] = s["ma20_below_50_falling"] & (q < ma200)
    s["below_20_50_and_200d"] = (q < ma20) & (q < ma50) & (q < ma200)
    s["vix_over_25"] = d["^VIX"] > 25
    s["vix_20d_over_25"] = d["^VIX"].rolling(20).mean() > 25
    s["curve_inverted"] = d["^TNX"] < d["^IRX"]
    s["credit_below_100d"] = (credit < credit.rolling(100).mean()).where(credit.notna(), False)
    s["drawdown_10pct"] = q / q.rolling(252, min_periods=1).max() - 1 <= -0.10
    s["below_200d_and_vix_20"] = s["below_200d"] & (d["^VIX"] > 20)
    s["below_200d_and_credit"] = s["below_200d"] & s["credit_below_100d"]
    return s, d


def breadth():
    """Share of the Large tier closing above its 200-day average, at each checkpoint."""
    parts = []
    for year in YEARS:
        p = m["panel"](year)
        p = p[p["tier"] == "Large"]
        parts.append(p.groupby("checkpoint").apply(lambda g: (g["close"] > g["ma200"]).mean()))
    return pd.concat(parts).sort_index()


def daily_all():
    """Book, QQQ, top 7 and switch-weight daily series for 2005-2026, one row per book day."""
    frames = []
    for year in YEARS:
        d = ov["daily"](year)
        p = m["panel"](year)
        p = p[p["tier"] == "Large"]
        share = p.groupby("checkpoint")["ret_250d"].apply(lambda r: (r > 1.0).mean())
        d["w_book"] = (share.reindex(d.index, method="ffill").bfill() >= 0.015).astype(float)
        d["top7"], _ = m["basket_returns"](year, m["top7_pit"](year), d.index)
        d["year"] = year
        frames.append(d)
    return pd.concat(frames)


def run(base_r, risk_off, mode, tbill):
    """Replace `base_r` with cash or a QQQ short while risk_off (decided the day before) is on."""
    off = risk_off.shift(1).fillna(False).astype(bool)
    alt = tbill if mode == "cash" else (-qqq_r + tbill - SHORT_COST)
    flips = off.astype(int).diff().abs().fillna(0) * 1e-3
    return base_r.where(~off, alt) - flips


def stats(r, years):
    by_year = (1 + r).groupby(years).prod() - 1
    eq = (1 + r).cumprod()
    return by_year, (eq / eq.cummax() - 1).min()


s, mac = macro()
br = breadth()
d = daily_all()
idx = d.index
qqq_r = d["qqq"]
tbill = (mac["^IRX"].reindex(idx).ffill() / 100 / 252).fillna(0.0)
sig = s.reindex(idx).ffill().fillna(False)
sig["breadth_under_40"] = (br.reindex(idx, method="ffill") < 0.40).fillna(False)
sig["breadth_under_40_and_below_200d"] = sig["breadth_under_40"] & sig["below_200d"]

w = d["w_book"].shift(1).fillna(d["w_book"].iloc[0])
bases = {
    "QQQ": qqq_r,
    "switch_QQQ": w * d["book"] + (1 - w) * qqq_r - w.diff().abs().fillna(0) * 1e-3,
    "switch_top7": w * d["book"] + (1 - w) * d["top7"] - w.diff().abs().fillna(0) * 1e-3,
}

# 1. Timeline: when each signal first fired in the run-up to each down year's big drop
rows = []
q = mac["QQQ"]
for year, (peak_from, peak_to) in {2008: ("2007-06-01", "2008-06-30"), 2018: ("2018-06-01", "2018-12-31"),
                                   2022: ("2021-09-01", "2022-06-30")}.items():
    peak_day = q[peak_from:peak_to].idxmax()
    trough_day = q[peak_day:f"{year}-12-31"].idxmin()
    for name in sig.columns:
        col = s[name] if name in s else sig[name]
        window = col[peak_day - pd.Timedelta(days=120):trough_day]
        fired = window[window.astype(bool)]
        first = fired.index[0] if len(fired) else None
        rows.append(dict(year=year, signal=name, peak=peak_day.date(), trough=trough_day.date(),
                         peak_to_trough=q[trough_day] / q[peak_day] - 1,
                         first_fired=first.date() if first is not None else None,
                         days_after_peak=(first - peak_day).days if first is not None else None,
                         qqq_off_peak_then=(q[first] / q[peak_day] - 1) if first is not None else None,
                         further_drop_after=(q[trough_day] / q[first] - 1) if first is not None else None))
timeline = pd.DataFrame(rows)
timeline.to_csv(f"{OUT}/downside_timeline.csv", index=False)

# 2. Backtest every signal x action on QQQ and on the two switch strategies
res, per_year = [], []
for base_name, base_r in bases.items():
    by_year, dd = stats(base_r, d["year"])
    res.append(dict(base=base_name, signal="none", action="-", cagr=((1 + by_year).prod() ** (1 / len(by_year)) - 1),
                    worst_dd=dd, **{f"y{y}": by_year[y] for y in DOWN_YEARS}, up_years_cost=0.0, days_off=0.0))
    per_year.append(by_year.rename(f"{base_name}|none|-"))
    for name in sig.columns:
        for mode in ("cash", "short"):
            r = run(base_r, sig[name], mode, tbill)
            by, dd2 = stats(r, d["year"])
            up = [y for y in YEARS if y not in DOWN_YEARS]
            res.append(dict(base=base_name, signal=name, action=mode,
                            cagr=((1 + by).prod() ** (1 / len(by)) - 1), worst_dd=dd2,
                            **{f"y{y}": by[y] for y in DOWN_YEARS},
                            up_years_cost=(by[up] - by_year[up]).mean(), days_off=sig[name].mean()))
            per_year.append(by.rename(f"{base_name}|{name}|{mode}"))
summary = pd.DataFrame(res)
summary.to_csv(f"{OUT}/downside_summary.csv", index=False)
pd.concat(per_year, axis=1).T.to_csv(f"{OUT}/downside_by_year.csv")

pct = lambda x: (x * 100).round(1)
print(timeline.assign(peak_to_trough=pct(timeline["peak_to_trough"]), qqq_off_peak_then=pct(timeline["qqq_off_peak_then"]),
                      further_drop_after=pct(timeline["further_drop_after"])).to_string(index=False))
for base_name in bases:
    t = summary[summary["base"] == base_name].copy()
    for c in ["cagr", "worst_dd", "y2008", "y2018", "y2022", "up_years_cost", "days_off"]:
        t[c] = pct(t[c])
    print(f"\n== {base_name}")
    print(t.drop(columns="base").sort_values("cagr", ascending=False).to_string(index=False))

"""Robustness of the right-tail switch: thresholds as counts and as tier shares, and how often it flips."""
import sys, os
import pandas as pd
sys.argv = ["x"]
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "overlays.py")).read().replace("\nmain()\n", "\n")
ns = {"__file__": os.path.join(os.path.dirname(os.path.abspath(__file__)), "overlays.py")}
exec(compile(src, "overlays", "exec"), ns)
from common import OUT, panel

def share(year):
    p = panel(year); p = p[p["tier"] == "Large"]
    return p.groupby("checkpoint")["ret_250d"].apply(lambda r: (r > 1.0).mean())

rows, flips, sig_rows = [], [], []
for year in ns["YEARS"]:
    d = ns["daily"](year); dbl = ns["doublers"](year); sh = share(year)
    for cp, v in dbl.items():
        sig_rows.append(dict(year=year, checkpoint=cp, doublers=v, share=sh[cp]))
    def add(name, w):
        r = ns["run_weights"](d, w); eq = (1 + r).cumprod()
        rows.append(dict(year=year, strategy=name, ret=eq.iloc[-1] - 1, dd=(eq / eq.cummax() - 1).min()))
        flips.append(dict(year=year, strategy=name, flips=int((w.diff().abs() > 0).sum()), in_book=w.mean()))
    s = dbl.reindex(d.index, method="ffill").bfill(); s2 = sh.reindex(d.index, method="ffill").bfill()
    for k in (2, 3, 4, 5, 6, 8, 10, 15):
        add(f"count>={k}", (s >= k).astype(float))
    for q in (0.005, 0.01, 0.015, 0.02, 0.03):
        add(f"share>={q:.1%}", (s2 >= q).astype(float))
    rows.append(dict(year=year, strategy="QQQ", ret=(1 + d["qqq"]).prod() - 1))
    rows.append(dict(year=year, strategy="book", ret=(1 + d["book"]).prod() - 1))
res = pd.DataFrame(rows); wide = res.pivot(index="strategy", columns="year", values="ret")
f = pd.DataFrame(flips).groupby("strategy")[["flips", "in_book"]].mean()
UP_PRE = ns["UP_PRE"]
def cagr(cols): return ((1 + wide[cols]).prod(axis=1) ** (1 / len(cols)) - 1) * 100
gap = wide.sub(wide.loc["QQQ"], axis=1)
summ = pd.DataFrame({"pre_up_vs_qqq": gap[UP_PRE].mean(axis=1) * 100,
    "cagr_05_17": cagr(list(range(2005, 2018))), "cagr_18_26": cagr(list(range(2018, 2027))),
    "cagr_05_26": cagr(ns["YEARS"]), "years_beat_qqq": (gap > 0).sum(axis=1),
    "worst_dd": res.groupby("strategy")["dd"].min() * 100}).join(f).round(2)
print(summ.sort_values("cagr_05_26", ascending=False).to_string())
sig = pd.DataFrame(sig_rows); sig.to_csv(f"{OUT}/doubler_signal.csv", index=False)
summ.to_csv(f"{OUT}/switch_sweep.csv"); (wide * 100).round(1).to_csv(f"{OUT}/switch_sweep_wide.csv")
print(sig.groupby("year").agg(dbl_min=("doublers", "min"), dbl_mean=("doublers", "mean"), dbl_max=("doublers", "max"), share_mean=("share", "mean")).round(3).to_string())
print((wide.loc[["QQQ", "book", "count>=3", "count>=5", "count>=8", "share>=1.0%", "share>=1.5%"]] * 100).round(1).to_string())

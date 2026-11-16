import os
import pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(HERE, "dist_rearm_smooth.py")).read().split("VARIANTS = {")[0]
ns = {"__file__": os.path.join(HERE, "dist_rearm_smooth.py")}
exec(compile(src, "smooth", "exec"), ns)
rows = []
for k in (0, 3, 5, 7, 8, 10, 12, 15, 20, 25):
    off, n = ns["machine"](min_stay=k)
    for b in ("switch_QQQ", "switch_top7"):
        r0 = ns["bases"][b]
        for cost in (1e-3, 3e-3):
            o = off.reindex(r0.index).ffill().fillna(False).shift(1).fillna(False).astype(bool)
            r = ns["run_off"](r0, off) - o.astype(int).diff().abs().fillna(0) * (cost - 1e-3)
            by, dd = ns["stats"](r, ns["d"]["year"])
            rows.append(dict(min_stay=k, base=b, cost=f"{cost:.1%}", cagr=round(((1 + by).prod() ** (1 / len(by)) - 1) * 100, 1),
                             worst_dd=round(dd * 100, 1), y2008=round(by[2008] * 100, 1), y2022=round(by[2022] * 100, 1),
                             switches_per_yr=round(n / 22.8, 1)))
t = pd.DataFrame(rows)
t.to_csv(f"{ns['OUT']}/min_stay_sweep.csv", index=False)
print(t.pivot_table(index="min_stay", columns=["base", "cost"], values="cagr").to_string())
print(t[t.cost == "0.1%"].pivot_table(index="min_stay", columns="base", values=["worst_dd", "y2008", "y2022", "switches_per_yr"]).to_string())

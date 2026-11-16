"""Does momentum ranking work each year? Per tier and checkpoint, the Large rule's score (180-day return over 60-day
vol ** 0.5) against the return to the next checkpoint (10 trading days), 2005-2026."""
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, "/Users/victorhuang/work/alpha_tech_tracker_hist")
from common import ALPACA_YEARS, HIST_YEARS, OUT, close, panel  # noqa: E402

STEP = 10
TOP = 10


def spearman(a, b):
    return a.rank().corr(b.rank())


def trend_ok(p):
    return (p["close"] > p["ma50"]) & (p["ma50"] > p["ma200"]) & p["ma200_rising"].astype(bool)


rows = []
for year in HIST_YEARS + ALPACA_YEARS:
    p = panel(year)
    c = close(year).ffill(limit=5)
    cps = sorted(p["checkpoint"].unique())
    idx = c.index
    pos = idx.get_indexer(cps)
    ret180 = c / c.shift(180) - 1
    fwd = c.shift(-STEP) / c - 1
    qqq_sum = 0.0
    acc = {}
    for cp, i in zip(cps, pos):
        if i < 0 or i + STEP >= len(idx):
            continue
        day = idx[i]
        q = fwd.loc[day, "QQQ"] if "QQQ" in fwd else np.nan
        qqq_sum += q
        snap = p[p["checkpoint"] == cp].set_index("symbol")
        snap = snap[~snap.index.duplicated()]
        snap = snap.assign(score=ret180.loc[day].reindex(snap.index) / snap["vol_60d"] ** 0.5,
                           f=fwd.loc[day].reindex(snap.index)).dropna(subset=["score", "f"])
        for tier, g in snap.groupby("tier"):
            a = acc.setdefault(tier, dict(ic=[], ic_trend=[], top_edge=0.0, ls=0.0, tier_ret=0.0, top_ret=0.0,
                                          breadth=[], disp=[], n=0))
            ok = g[trend_ok(g)]
            a["ic"].append(spearman(g["score"], g["f"]))
            if len(ok) >= 20:
                a["ic_trend"].append(spearman(ok["score"], ok["f"]))
            top = ok.nlargest(TOP, "score")
            a["top_ret"] += top["f"].mean() if len(top) else 0.0
            a["tier_ret"] += g["f"].mean()
            a["top_edge"] += (top["f"].mean() - g["f"].mean()) if len(top) else 0.0
            dec = max(len(g) // 10, 1)
            r250 = g["ret_250d"].dropna()
            hi, lo = r250.nlargest(dec).index, r250.nsmallest(dec).index
            a["ls"] += g.loc[hi, "f"].mean() - g.loc[lo, "f"].mean()
            a["breadth"].append(len(ok) / len(g))
            a["disp"].append(g["f"].std())
            a["n"] += 1
    for tier, a in acc.items():
        rows.append(dict(year=year, tier=tier, checkpoints=a["n"], ic=np.nanmean(a["ic"]),
                         ic_trend=np.nanmean(a["ic_trend"]) if a["ic_trend"] else np.nan,
                         top10_sum=a["top_ret"], tier_sum=a["tier_ret"], qqq_sum=qqq_sum,
                         top10_vs_tier=a["top_edge"], top10_vs_qqq=a["top_ret"] - qqq_sum,
                         tier_vs_qqq=a["tier_ret"] - qqq_sum, mom12m_long_short=a["ls"],
                         trend_breadth=np.mean(a["breadth"]), dispersion_10d=np.mean(a["disp"])))
    print(year, flush=True)

f = pd.DataFrame(rows).round(4)
f.to_csv(f"{OUT}/factor.csv", index=False)
for tier in ("Large", "Mid", "Small"):
    print(f"== {tier}")
    t = f[f["tier"] == tier].set_index("year")
    print((t[["ic", "ic_trend", "top10_vs_tier", "tier_vs_qqq", "top10_vs_qqq", "mom12m_long_short"]] * 100)
          .round(1).join(t[["trend_breadth"]].round(2)).to_string())

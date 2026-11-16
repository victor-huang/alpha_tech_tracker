"""Inside the Large top-10 book, 2005-2019: idle cash, what stopped / dropped names did next, sector mix vs the QQQ
stand-in, and whether the book held the names that drove QQQ."""
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, "/Users/victorhuang/work/alpha_tech_tracker_hist")
from common import HIST_YEARS, OUT, books, close, sector_of  # noqa: E402

N = 10
AFTER = (10, 40)
proxy = pd.read_pickle(f"{OUT}/proxy_members.pkl")
contributors = pd.read_csv(f"{OUT}/qqq_top_contributors.csv")

rows, sector_rows, held_rows = [], [], []
for year in HIST_YEARS:
    b = books(year)[10]
    eq, trades = b["Large"]
    c = close(year).ffill(limit=5)
    days = eq.index
    trades = trades.copy()
    trades["exit"] = pd.to_datetime(trades["exit"])
    trades["entry"] = pd.to_datetime(trades["entry"])

    open_count = pd.Series(0, index=days)
    for t in trades.itertuples():
        open_count[(days >= t.entry) & (days < t.exit)] += 1
    invested = (open_count.clip(upper=N) / N).mean()

    after = {}
    for reason in ("stop", "dropped"):
        sel = trades[trades["reason"].str.startswith(reason)]
        for h in AFTER:
            vals = []
            for t in sel.itertuples():
                i = c.index.get_indexer([t.exit])[0]
                if i < 0 or i + h >= len(c.index) or t.symbol not in c:
                    continue
                vals.append(c[t.symbol].iloc[i + h] / c[t.symbol].iloc[i] - 1 - (c["QQQ"].iloc[i + h] / c["QQQ"].iloc[i] - 1))
            after[f"{reason}_next{h}d_vs_qqq"] = np.mean(vals) if vals else np.nan
        after[f"{reason}_count"] = len(sel)
    hold_days = (trades["exit"] - trades["entry"]).dt.days.mean()
    rows.append(dict(year=year, ret=eq.iloc[-1] - 1, trades=len(trades), names=trades["symbol"].nunique(),
                     avg_hold_days=hold_days, invested=invested, **after))

    pos_days = {}
    for t in trades.itertuples():
        d = int(((days >= t.entry) & (days < t.exit)).sum())
        pos_days[sector_of(t.symbol)] = pos_days.get(sector_of(t.symbol), 0) + d
    total = sum(pos_days.values()) or 1
    w = proxy[proxy["year"] == year].assign(sector=lambda x: x["sector"]).groupby("sector")["weight"].sum()
    for sector in sorted(set(pos_days) | set(w.index)):
        sector_rows.append(dict(year=year, sector=sector, book_share=pos_days.get(sector, 0) / total,
                                qqq_weight=w.get(sector, 0.0)))

    for r in contributors[contributors["year"] == year].itertuples():
        t = trades[trades["symbol"] == r.symbol]
        d = int(sum(((days >= x.entry) & (days < x.exit)).sum() for x in t.itertuples()))
        held_rows.append(dict(year=year, symbol=r.symbol, qqq_contribution=r.contribution, stock_ret=r.ret,
                              days_held=d, share_of_year=d / len(days), book_pnl=(t["ret"].sum() / N) if len(t) else 0))
    print(year, flush=True)

m = pd.DataFrame(rows).round(4); m.to_csv(f"{OUT}/mechanics.csv", index=False)
s = pd.DataFrame(sector_rows).round(4); s.to_csv(f"{OUT}/book_sectors.csv", index=False)
h = pd.DataFrame(held_rows).round(4); h.to_csv(f"{OUT}/megacap_held.csv", index=False)
print(m.set_index("year").round(3).to_string())
print(s[s["sector"] == "Technology"].set_index("year")[["book_share", "qqq_weight"]].round(2).T.to_string())
print(h.groupby("year").apply(lambda g: pd.Series(dict(
    top10_contrib=g["qqq_contribution"].sum(), avg_share_held=g["share_of_year"].mean(),
    held_any=(g["days_held"] > 0).mean(), book_pnl_pts=g["book_pnl"].sum()))).round(3).to_string())

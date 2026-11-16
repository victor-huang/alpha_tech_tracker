"""How many universe names have an implausible market cap (cap / median daily dollar volume), by year and tier."""
import sys
import pandas as pd
sys.path.insert(0, "/Users/victorhuang/work/alpha_tech_tracker_hist")
from common import HIST_YEARS, OUT, books, close, market_caps, panel, _hist_year  # noqa: E402

rows, flagged = [], []
for year in HIST_YEARS:
    p = panel(year); tiers = p.drop_duplicates("symbol").set_index("symbol")["tier"]
    d = pd.concat([_hist_year(y) for y in (year - 1,) if y >= 2003])
    d = d[d["day"] >= pd.Timestamp(year - 1, 9, 1)]
    dv = (d["close"] * d["volume"]).groupby(d["symbol"]).median()
    caps = market_caps(tiers.index, year)
    ratio = (caps / dv.reindex(caps.index)).dropna()
    bad = ratio[ratio > 5000]
    traded = set()
    for key, b in books(year).items():
        if key == "large_top3":
            traded |= set(b["trades"]["symbol"])
        else:
            traded |= set(b["Large"][1]["symbol"]) if len(b["Large"][1]) else set()
    for s in bad.index:
        flagged.append(dict(year=year, symbol=s, tier=tiers[s], cap_bn=caps[s] / 1e9, dv_m=dv.get(s, 0) / 1e6,
                            ratio=bad[s], in_large_book=s in traded))
    t = tiers[bad.index].value_counts()
    rows.append(dict(year=year, universe=len(tiers), flagged=len(bad), flagged_large=t.get("Large", 0),
                     large=int((tiers == "Large").sum()),
                     traded_in_large_books=sum(1 for s in bad.index if s in traded and tiers[s] == "Large")))
pd.DataFrame(rows).to_csv(f"{OUT}/cap_check.csv", index=False)
f = pd.DataFrame(flagged); f.round(1).to_csv(f"{OUT}/cap_flagged.csv", index=False)
print(pd.DataFrame(rows).to_string(index=False))
print(f[f.in_large_book].round(1).to_string(index=False))

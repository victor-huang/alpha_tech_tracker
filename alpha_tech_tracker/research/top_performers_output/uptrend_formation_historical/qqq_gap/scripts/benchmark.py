"""What drove QQQ each year: a NASDAQ-100 stand-in from our own data, its biggest contributors and sectors, and the
Large tier cap-weighted vs equal-weighted."""
import sys

import pandas as pd

sys.path.insert(0, "/Users/victorhuang/work/alpha_tech_tracker_hist")
from common import HIST_YEARS, OUT, close, exchanges_on, market_caps, panel, sector_of, year_return  # noqa: E402

PROXY_SIZE = 100
MAX_CAP_TO_DOLLAR_VOLUME = 5000  # above this the share count or raw price is junk (FTR, ETFC, COL ...)
# listings only carry today's exchange: large companies that moved from the NYSE to NASDAQ after 2005 (Kraft became
# Mondelez on NASDAQ in Oct 2012), and those that left NASDAQ for the NYSE (Oracle in Jul 2013)
NASDAQ_FROM = {"TXN": 2012, "ADP": 2013, "MDLZ": 2013, "PEP": 2018, "CSX": 2018, "EXC": 2019, "KDP": 2020,
               "XEL": 2021, "WMT": 2022, "HON": 2022, "AEP": 2022, "LIN": 2023, "ROP": 2023, "AZN": 2024}
NASDAQ_UNTIL = {"ORCL": 2013}

flagged = pd.read_csv(f"{OUT}/cap_flagged.csv")
junk = {y: set(g["symbol"]) for y, g in flagged[flagged["ratio"] > MAX_CAP_TO_DOLLAR_VOLUME].groupby("year")}
rows, contributors, sector_rows, members = [], [], [], []
for year in HIST_YEARS:
    p = panel(year)
    tiers = p.drop_duplicates("symbol").set_index("symbol")["tier"]
    c = close(year)
    r = year_return(c[sorted({s for s in tiers.index if s in c.columns} | {"QQQ"})], year)
    caps = market_caps(tiers.index, year)
    ex = exchanges_on(pd.Timestamp(year, 1, 1))
    info = pd.DataFrame({"tier": tiers, "cap": caps, "ret": r.reindex(tiers.index)})
    info["exchange"] = [ex.get(s.split("~")[0]) for s in info.index]
    info["sector"] = [sector_of(s) for s in info.index]
    info = info.dropna(subset=["cap", "ret"])
    info["nasdaq"] = [(e == "NASDAQ" and NASDAQ_FROM.get(s.split("~")[0], 0) <= year)
                      or year <= NASDAQ_UNTIL.get(s.split("~")[0], 0)
                      for s, e in zip(info.index, info["exchange"])]
    info["plausible"] = info.index.map(lambda s: s not in junk.get(year, set()))

    proxy = info[info["nasdaq"] & info["plausible"] & (info["sector"] != "Finance")].nlargest(PROXY_SIZE, "cap")
    w = proxy["cap"] / proxy["cap"].sum()
    contrib = (w * proxy["ret"]).sort_values(ascending=False)
    proxy_ret = contrib.sum()
    large = info[(info["tier"] == "Large") & info["plausible"]]
    lw = large["cap"] / large["cap"].sum()
    rows.append(dict(
        year=year, qqq=r["QQQ"], proxy_cw=proxy_ret, proxy_ew=proxy["ret"].mean(),
        top5_share=contrib.head(5).sum() / proxy_ret if proxy_ret else None,
        top10_share=contrib.head(10).sum() / proxy_ret if proxy_ret else None,
        top10_weight=w.sort_values(ascending=False).head(10).sum(),
        large_cw=(lw * large["ret"]).sum(), large_ew=large["ret"].mean(), large_median=large["ret"].median(),
        mid_ew=info.loc[info["tier"] == "Mid", "ret"].mean(), small_ew=info.loc[info["tier"] == "Small", "ret"].mean(),
        large_beat_qqq=(large["ret"] > r["QQQ"]).mean(), all_beat_qqq=(info["ret"] > r["QQQ"]).mean(),
    ))
    for s, v in contrib.head(10).items():
        contributors.append(dict(year=year, symbol=s, sector=proxy.loc[s, "sector"], weight=w[s],
                                 ret=proxy.loc[s, "ret"], contribution=v))
    members.append(proxy.assign(year=year, weight=w).reset_index().rename(columns={"index": "symbol"}))
    for (tier, sector), g in info.groupby(["tier", "sector"]):
        sector_rows.append(dict(year=year, tier=tier, sector=sector, n=len(g), ew_ret=g["ret"].mean()))
    for sector, g in proxy.groupby("sector"):
        sector_rows.append(dict(year=year, tier="QQQ proxy", sector=sector, n=len(g), ew_ret=g["ret"].mean(),
                                weight=w[g.index].sum(), contribution=(w[g.index] * g["ret"]).sum()))
    print(year, f"QQQ {r['QQQ']:.1%} proxy {proxy_ret:.1%}", flush=True)

pd.DataFrame(rows).round(4).to_csv(f"{OUT}/benchmark.csv", index=False)
pd.DataFrame(contributors).round(4).to_csv(f"{OUT}/qqq_top_contributors.csv", index=False)
pd.DataFrame(sector_rows).round(4).to_csv(f"{OUT}/sectors.csv", index=False)
pd.concat(members).to_pickle(f"{OUT}/proxy_members.pkl")
print(pd.DataFrame(rows).set_index("year").mul(100).round(1).to_string())

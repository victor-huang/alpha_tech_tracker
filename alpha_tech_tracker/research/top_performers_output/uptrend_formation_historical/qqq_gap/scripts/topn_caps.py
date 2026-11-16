"""Point-in-time top-N NASDAQ caps (N = 3, 5, 7, 10) in place of QQQ: alone and as the doubler switch's off-side."""
import os
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(HERE, "mag7.py")).read().replace("\nmain()\n", "\n")
m = {"__file__": os.path.join(HERE, "mag7.py")}
exec(compile(src, "mag7", "exec"), m)
OUT, YEARS, UP_PRE = m["OUT"], m["YEARS"], m["UP_PRE"]
SIZES = (3, 5, 7, 10)


def top_n(year, n):
    if year >= 2020:
        caps = pd.read_csv(f"{OUT}/nasdaq_caps_2020_2026.csv")
        return caps[caps["year"] == year].nlargest(n, "cap_b")["symbol"].tolist()
    p = pd.read_pickle(f"{OUT}/proxy_members.pkl")
    p = p[(p["year"] == year) & p["nasdaq"] & ~p["symbol"].isin(m["NOT_US_TOP"])].set_index("symbol")["cap"]
    if year >= 2013:
        p = pd.concat([p, m["market_caps"](["FB"], year)])
    if year == 2005:
        p["EBAY"] = m["EBAY_2005_CAP"]
    return p.nlargest(n).index.tolist()


rows, members = [], []
for year in YEARS:
    d = m["ov"]["daily"](year)
    p = m["panel"](year)
    p = p[p["tier"] == "Large"]
    share = p.groupby("checkpoint")["ret_250d"].apply(lambda r: (r > 1.0).mean())
    on = (share.reindex(d.index, method="ffill").bfill() >= 0.015).astype(float)
    strat = {"QQQ": d["qqq"], "book": d["book"], "switch book/QQQ": m["mix"](d, d["qqq"], on)}
    for n in SIZES:
        alt, held = m["basket_returns"](year, top_n(year, 10)[:n], d.index)
        members.append(dict(year=year, n=n, members=" ".join(held)))
        strat[f"top{n}"] = alt
        strat[f"switch book/top{n}"] = m["mix"](d, alt, on)
    for name, r in strat.items():
        eq = (1 + r).cumprod()
        rows.append(dict(year=year, strategy=name, ret=eq.iloc[-1] - 1, max_dd=(eq / eq.cummax() - 1).min()))
    print(year, flush=True)

res = pd.DataFrame(rows)
wide = res.pivot(index="strategy", columns="year", values="ret")
gap = wide.sub(wide.loc["QQQ"], axis=1)


def cagr(cols):
    return ((1 + wide[cols]).prod(axis=1) ** (1 / len(cols)) - 1) * 100


summary = pd.DataFrame({
    "pre_up_vs_qqq": gap[UP_PRE].mean(axis=1) * 100,
    "cagr_05_17": cagr(list(range(2005, 2018))), "cagr_18_26": cagr(list(range(2018, 2027))),
    "cagr_05_26": cagr(YEARS), "years_beat_qqq": (gap > 0).sum(axis=1),
    "worst_year": wide.min(axis=1) * 100, "worst_dd": res.groupby("strategy")["max_dd"].min() * 100,
}).round(1)
order = ["QQQ", "book", "switch book/QQQ"] + [f"top{n}" for n in SIZES] + [f"switch book/top{n}" for n in SIZES]
summary = summary.loc[order]
summary.to_csv(f"{OUT}/topn_caps_summary.csv"); (wide * 100).round(1).to_csv(f"{OUT}/topn_caps_wide.csv")
pd.DataFrame(members).to_csv(f"{OUT}/topn_caps_members.csv", index=False)
print(summary.to_string())
print((wide.loc[["QQQ"] + [f"top{n}" for n in SIZES]] * 100).round(1).to_string())
print(pd.DataFrame(members)[lambda x: x.n == 5].to_string(index=False))

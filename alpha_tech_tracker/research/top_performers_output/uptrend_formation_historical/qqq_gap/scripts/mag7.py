"""Magnificent 7 in place of QQQ, 2005-2026: alone, as the 50% core, and as the off-side of the doubler switch.

Two baskets, each equal weight bought on the first trading day of the year and held to year end:
  mag7_hindsight - AAPL MSFT GOOGL AMZN NVDA META TSLA, picked in 2023 (look-ahead before then)
  top7_pit       - the 7 largest US NASDAQ companies on the last close before the year (no look-ahead)
"""
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import OUT, close, market_caps, panel  # noqa: E402

src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "overlays.py")).read().replace("\nmain()\n", "\n")
ov = {"__file__": os.path.join(os.path.dirname(os.path.abspath(__file__)), "overlays.py")}
exec(compile(src, "overlays", "exec"), ov)

YEARS, UP_PRE, SWITCH_COST = ov["YEARS"], ov["UP_PRE"], ov["SWITCH_COST"]
HINDSIGHT = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA"]
# ADRs, a bad cap (ETFC, BIDU) and one listed on NYSE at the time (SNY); the proxy keeps them, a US top-7 should not
NOT_US_TOP = {"ERIC", "SNY", "VOD", "BIDU", "ETFC", "GOOG", "VEON"}
EBAY_2005_CAP = 76e9  # the proxy's 150B multiplies pre-split price by post-split shares


def top7_pit(year):
    if year >= 2020:
        caps = pd.read_csv(f"{OUT}/nasdaq_caps_2020_2026.csv")
        return caps[caps["year"] == year].nlargest(7, "cap_b")["symbol"].tolist()
    p = pd.read_pickle(f"{OUT}/proxy_members.pkl")
    p = p[(p["year"] == year) & p["nasdaq"] & ~p["symbol"].isin(NOT_US_TOP)].set_index("symbol")["cap"]
    if year >= 2013:
        p = pd.concat([p, market_caps(["FB"], year)])
    if year == 2005:
        p["EBAY"] = EBAY_2005_CAP
    return p.nlargest(7).index.tolist()


def basket_returns(year, members, days):
    c = close(year)
    alias = {"META": "FB"} if year <= 2019 else {}
    cols = [alias.get(s, s) for s in members]
    c = c[[s for s in cols if s in c]].reindex(days).ffill()
    c = c.loc[:, c.iloc[0].notna()]
    value = (c / c.iloc[0]).mean(axis=1)
    return value.pct_change().fillna(0.0), list(c.columns)


def mix(d, alt, w_book):
    w = w_book.shift(1).fillna(w_book.iloc[0])
    return w * d["book"] + (1 - w) * alt - w.diff().abs().fillna(0.0) * SWITCH_COST


def main():
    rows, members = [], []
    for year in YEARS:
        d = ov["daily"](year)
        p = panel(year)
        p = p[p["tier"] == "Large"]
        share = p.groupby("checkpoint")["ret_250d"].apply(lambda r: (r > 1.0).mean())
        count = p.groupby("checkpoint")["ret_250d"].apply(lambda r: int((r > 1.0).sum()))
        on_share = (share.reindex(d.index, method="ffill").bfill() >= 0.015).astype(float)
        on_count = (count.reindex(d.index, method="ffill").bfill() >= 5).astype(float)
        alts = {"QQQ": d["qqq"]}
        for name, m in (("mag7", HINDSIGHT), ("top7", top7_pit(year))):
            alts[name], held = basket_returns(year, m, d.index)
            members.append(dict(year=year, basket=name, members=" ".join(held)))
        strat = {"book": d["book"]}
        for name, alt in alts.items():
            strat[name] = alt
            strat[f"50/50 book+{name}"] = mix(d, alt, pd.Series(0.5, index=d.index))
            strat[f"switch1.5% book/{name}"] = mix(d, alt, on_share)
            strat[f"switch>=5 book/{name}"] = mix(d, alt, on_count)
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
        "cagr_05_17": cagr(list(range(2005, 2018))),
        "cagr_18_26": cagr(list(range(2018, 2027))),
        "cagr_05_26": cagr(YEARS),
        "years_beat_qqq": (gap > 0).sum(axis=1),
        "worst_year": wide.min(axis=1) * 100,
        "worst_dd": res.groupby("strategy")["max_dd"].min() * 100,
    }).round(1).sort_values("cagr_05_26", ascending=False)
    summary.to_csv(f"{OUT}/mag7_summary.csv")
    (wide * 100).round(1).to_csv(f"{OUT}/mag7_wide.csv")
    pd.DataFrame(members).to_csv(f"{OUT}/mag7_members.csv", index=False)
    print(summary.to_string())
    print((wide.loc[["QQQ", "mag7", "top7", "book", "switch1.5% book/QQQ", "switch1.5% book/mag7",
                     "switch1.5% book/top7"]] * 100).round(1).to_string())
    print(pd.DataFrame(members)[lambda m: m["basket"] == "top7"].to_string(index=False))


main()

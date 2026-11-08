"""Test price-derived factors for spotting future top performers on the biweekly checkpoint panels.

Factors (computed from cached daily closes and dollar volume only; bars have no open, so a "jump" is a
close-to-close move on heavy volume - usually an earnings or news reaction):

  * jump_held_60d    up-jump in the last 60 trading days, still holding at least half of it
  * jump_faded_60d   up-jump in the last 60 trading days that gave back more than half
  * drop_60d         down-jump (same thresholds) in the last 60 trading days
  * jumps_250d_2plus two or more up-jumps in the last 250 trading days
  * turnaround       1-year low at least 50% under the prior high, and back above the 200-day average after
                     being below it within the last 60 days
  * listed_lt_1y / listed_1_3y   trading-day age since the first cached bar (censored ages are excluded)
  * industry-group strength (see industry_groups.py): group in the top / bottom 20% of industries by median
    120- or 60-day return, group breadth >= 60% in an uptrend, and a stock in an uptrend leading a top group

For each factor and tier: hit rate of the next-60-day top 5%, lift, volatility-matched lift, mean excess vs
same-volatility peers (overall, by year, by QQQ regime), the incremental effect inside the early-momentum list
and the ranked top-30 lists, and how common the factor was among the yearly top-10 winners.

Usage:
    PYTHONPATH=. python -m alpha_tech_tracker.research.winner_factors --years 2020 2021 2022 2023 2024 2025 2026
"""
import argparse
import os
from datetime import date
from typing import Dict

import numpy as np
import pandas as pd

from alpha_tech_tracker.research import selection_filters as sf
from alpha_tech_tracker.research.industry_groups import GROUP_FACTORS, IndustryCache, add_group_strength
from alpha_tech_tracker.research.price_factors import attach_factors, factor_frames
from alpha_tech_tracker.research.top_performers import DEFAULT_CACHE_DIR, AlpacaData, DailyBarCache
from alpha_tech_tracker.research.uptrend_formation import (
    DEFAULT_WINNERS_CSV,
    REGIME_INDEX,
    _vol_matched_lift,
    market_regime,
)

FACTORS = ["jump_held_60d", "jump_faded_60d", "drop_60d", "jumps_250d_2plus", "turnaround", "listed_lt_1y",
           "listed_1_3y"] + GROUP_FACTORS
RANKED_LISTS = {"Large": "trend+riskadj120", "Mid": "trend+riskadj120", "Small": "trend+composite"}
RANKED_POOL = 30


def factor_tests(panel: pd.DataFrame, regime: pd.Series) -> pd.DataFrame:
    """Per factor and tier: next-60-day top-5% hit rate, lifts and mean excess vs same-volatility peers."""
    p = panel[panel["fwd_win"].notna()].copy()
    p["up_market"] = p["checkpoint"].map(regime).astype(bool)
    rows = []
    for factor in FACTORS:
        for tier in ("Large", "Mid", "Small"):
            tier_all = p[(p["tier"] == tier) & p[factor].notna()]
            flagged = tier_all[tier_all[factor] == 1]
            if flagged.empty:
                continue
            excess = flagged["excess"].dropna()
            by_cp = flagged.groupby("checkpoint")["excess"].mean()
            by_year = by_cp.groupby(by_cp.index.year).mean()
            rows.append({
                "factor": factor, "tier": tier,
                "per_checkpoint": round(len(flagged) / tier_all["checkpoint"].nunique(), 1),
                "hit_rate": flagged["fwd_win"].mean(),
                "lift": flagged["fwd_win"].mean() / tier_all["fwd_win"].mean(),
                "vol_matched_lift": _vol_matched_lift(flagged, tier_all),
                "loss_lift": flagged["fwd_lose"].mean() / tier_all["fwd_lose"].mean(),
                "excess_pct": excess.mean() * 100,
                "excess_up_market_pct": flagged.loc[flagged["up_market"], "excess"].mean() * 100,
                "excess_down_market_pct": flagged.loc[~flagged["up_market"], "excess"].mean() * 100,
                "years_positive": f"{int((by_year > 0).sum())}/{len(by_year)}",
                **{f"y{y}": round(v * 100, 2) for y, v in by_year.items()},
            })
    return pd.DataFrame(rows)


def incremental_tests(panel: pd.DataFrame, ranked_pools: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Inside a candidate list: mean excess of names with the factor minus names without it."""
    p = panel[panel["excess"].notna()]
    lists = {"early_momentum": p[p["early_momentum"].astype(bool)]}
    for tier, pool in ranked_pools.items():
        lists[f"top{RANKED_POOL}:{RANKED_LISTS[tier]}:{tier}"] = p.merge(pool[["checkpoint", "symbol"]],
                                                                        on=["checkpoint", "symbol"])
    rows = []
    for list_name, members in lists.items():
        for factor in FACTORS:
            for tier in ("Large", "Mid", "Small"):
                m = members[(members["tier"] == tier) & members[factor].notna()]
                with_f, without = m[m[factor] == 1], m[m[factor] == 0]
                if len(with_f) < 20:
                    continue
                diff_by_year = (with_f.groupby(with_f["checkpoint"].dt.year)["excess"].mean()
                                - without.groupby(without["checkpoint"].dt.year)["excess"].mean()).dropna()
                rows.append({
                    "list": list_name, "factor": factor, "tier": tier, "n_with": len(with_f),
                    "share_with": len(with_f) / len(m),
                    "excess_with_pct": with_f["excess"].mean() * 100,
                    "excess_without_pct": without["excess"].mean() * 100,
                    "difference_pct": (with_f["excess"].mean() - without["excess"].mean()) * 100,
                    "hit_with": with_f["fwd_win"].mean(), "hit_without": without["fwd_win"].mean(),
                    "years_better": f"{int((diff_by_year > 0).sum())}/{len(diff_by_year)}",
                })
    return pd.DataFrame(rows)


def winner_prevalence(panel: pd.DataFrame, winners: pd.DataFrame) -> pd.DataFrame:
    """Share of yearly top-10 winners showing each factor at some checkpoint in the year's first half, against
    the same share for every other stock in their tier."""
    p = panel[panel["checkpoint"].dt.month <= 6].copy()
    p["year"] = p["checkpoint"].dt.year
    any_by_stock = p.groupby(["year", "tier", "symbol"])[FACTORS].max().reset_index()
    marked = any_by_stock.merge(winners[["year", "symbol"]].assign(winner=True), on=["year", "symbol"], how="left")
    marked["winner"] = marked["winner"].fillna(False).astype(bool)
    rows = []
    for factor in FACTORS:
        for tier in ("Large", "Mid", "Small", "All"):
            m = marked if tier == "All" else marked[marked["tier"] == tier]
            w, o = m[m["winner"]], m[~m["winner"]]
            w, o = w[w[factor].notna()], o[o[factor].notna()]
            rows.append({"factor": factor, "tier": tier, "winners": len(w), "winner_share": w[factor].mean(),
                         "others_share": o[factor].mean(),
                         "ratio": w[factor].mean() / o[factor].mean() if o[factor].mean() > 0 else np.nan})
    return pd.DataFrame(rows)


def run(args: argparse.Namespace) -> None:
    alpaca = AlpacaData()
    panel = sf.drop_funds(sf.load_panels(args.panel_dir, args.years), alpaca.listed_stocks()["name"])
    checkpoints = sorted(panel["checkpoint"].unique())
    symbols = sorted(panel["symbol"].unique())
    bar_cache = DailyBarCache(args.cache_dir, alpaca.daily_bars)
    close, dollar_volume = bar_cache.load(symbols + [REGIME_INDEX], date(min(args.years) - 2, 10, 1), args.today,
                                          args.today)
    regime = market_regime(close[REGIME_INDEX]).reindex(checkpoints).fillna(False)
    panel = sf.add_selection_features(panel, dollar_volume[symbols].rolling(20, min_periods=15).median()
                                      .reindex(checkpoints))
    panel = attach_factors(panel, factor_frames(close[symbols], dollar_volume[symbols]))
    industries = IndustryCache(os.path.join(args.cache_dir, "industries.csv")).load(args.today)
    panel = add_group_strength(panel, industries)
    print(f"industry known for {panel['industry'].notna().mean():.1%} of panel rows, "
          f"{panel['industry'].nunique()} industries", flush=True)

    pools = {}
    for tier, variant in RANKED_LISTS.items():
        ranked = sf.rank_variant(panel, sf.VARIANTS[variant], RANKED_POOL)
        pools[tier] = ranked[(ranked["tier"] == tier) & (ranked["rank"] <= RANKED_POOL)]
    winners = pd.read_csv(args.winners_csv)
    winners = winners[winners["year"].isin(args.years)]

    out_dir = os.path.join(args.out_dir, "winner_factors")
    os.makedirs(out_dir, exist_ok=True)
    factor_tests(panel, regime).round(3).to_csv(os.path.join(out_dir, "factor_tests.csv"), index=False)
    incremental_tests(panel, pools).round(3).to_csv(os.path.join(out_dir, "incremental_tests.csv"), index=False)
    winner_prevalence(panel, winners).round(3).to_csv(os.path.join(out_dir, "winner_prevalence.csv"), index=False)
    print(f"wrote {out_dir}")


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--years", type=int, nargs="+", required=True)
    p.add_argument("--winners-csv", default=DEFAULT_WINNERS_CSV)
    p.add_argument("--panel-dir", default=sf.PANEL_DIR)
    p.add_argument("--cache-dir", default=DEFAULT_CACHE_DIR)
    p.add_argument("--out-dir", default=sf.PANEL_DIR)
    p.add_argument("--today", type=date.fromisoformat, default=date.today())
    return p.parse_args(argv)


def main(argv=None) -> None:
    run(parse_args(argv))


if __name__ == "__main__":
    main()

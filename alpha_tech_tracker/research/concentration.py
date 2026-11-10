"""How does the book change when only the top N names of each recommended list are held?

One continuous book over the given years per list and N, held day by day with the list's trailing stop:
  * Large (recommended rule, breakout slots in the first 5 places), every 2 weeks
  * Large ranked by the 180-day score alone (no slots), every 2 weeks
  * Small (recommended rule), every 2 weeks while QQQ is above both its 50- and 200-day averages, otherwise monthly

Also lists, for the smallest N, which stocks the gains came from (no stops, summed per-period contributions), and
runs a walk-forward over the 60 walk_forward_tuning settings for Large top 3, 5 and 15: each test year uses the setting
with the best compounded return over the earlier years only, to measure how much hindsight is in the chosen settings.

Usage:
    PYTHONPATH=. python -m alpha_tech_tracker.research.concentration --years 2020 2021 2022 2023 2024 2025 2026
"""
import os
from typing import Dict, List, NamedTuple

import numpy as np
import pandas as pd

from alpha_tech_tracker.research.ranking_exits import EXIT_RULES, daily_data, run_daily_book
from alpha_tech_tracker.research.rebalance_interval import (
    DYNAMIC,
    book_summary,
    dynamic_schedule,
    returns_by_year,
    trend_state,
)
from alpha_tech_tracker.research.recommended_rules import RECOMMENDED, prepare_recommended_panel
from alpha_tech_tracker.research.selection_filters import (
    Variant,
    parse_args,
    period_returns,
    prepare_inputs,
    rank_variant,
    run_portfolio,
)
from alpha_tech_tracker.research.uptrend_formation import REGIME_INDEX
from alpha_tech_tracker.research.walk_forward_tuning import Setting, add_lookback_returns, settings, variant_for

TOP_NS = (3, 5, 10, 15)
RANK_DEPTH = 15
LARGE_SCORE_ONLY = Setting(lookback=180, vol_power=0.5, clean=False, slots=False)
SMALL_SCHEDULE = "uptrend 2w, else 1m"
WF_TOP_NS = (3, 5, 15)
WF_FIRST_TEST_YEAR = 2021
WF_SUMMARY_FROM = 2022


class ListSpec(NamedTuple):
    tier: str
    variant: Variant
    exit_rule: str
    trend_schedule: str = ""


LISTS: Dict[str, ListSpec] = {
    "large_slots": ListSpec("Large", RECOMMENDED["Large"][1], RECOMMENDED["Large"][2]),
    "large_score_only": ListSpec("Large", variant_for(LARGE_SCORE_ONLY), RECOMMENDED["Large"][2]),
    "small": ListSpec("Small", RECOMMENDED["Small"][1], RECOMMENDED["Small"][2], SMALL_SCHEDULE),
}


def contributions(book: pd.DataFrame, returns: pd.DataFrame) -> pd.DataFrame:
    """Per symbol: periods held and the sum of its weighted period returns, largest first."""
    rows = [(cp, s, returns.loc[cp, s] / len(held)) for cp, held in book["held"].items() for s in held]
    c = pd.DataFrame(rows, columns=["checkpoint", "symbol", "contribution"])
    out = c.groupby("symbol").agg(periods=("checkpoint", "size"), contribution=("contribution", "sum"))
    return out.sort_values("contribution", ascending=False)


def top_share(contrib: pd.DataFrame, k: int = 5) -> float:
    """Share of the summed contributions that came from the k largest contributors."""
    return float(contrib["contribution"].head(k).sum() / contrib["contribution"].sum())


def geometric_mean(returns) -> float:
    """Average yearly return compounded: the CAGR of the given yearly returns."""
    return float(np.exp(np.log1p(pd.Series(returns, dtype=float)).mean()) - 1)


def setting_grid(panel: pd.DataFrame, data, checkpoints: List[pd.Timestamp], tier: str, exit_rule: str,
                 cost: float, top_ns=WF_TOP_NS) -> pd.DataFrame:
    """Yearly return of a continuous book for every walk_forward_tuning setting and top N."""
    rows = []
    for s in settings():
        ranked = rank_variant(panel, variant_for(s), RANK_DEPTH)
        ranked = ranked[ranked["tier"] == tier]
        for n in top_ns:
            book = run_daily_book(ranked, data, checkpoints, n, n, EXIT_RULES[exit_rule], cost)
            rows += [{"setting": s.name, "top": n, "year": int(y), "ret": r} for y, r in returns_by_year(book).items()]
    return pd.DataFrame(rows)


def walk_forward_picks(grid: pd.DataFrame, first_test_year: int = WF_FIRST_TEST_YEAR) -> pd.DataFrame:
    """Per top N and test year: the setting with the best compounded return over earlier years, its test-year
    return, its rank among all settings that year, and the median and best setting that year."""
    rows = []
    for n, g in grid.groupby("top"):
        table = g.pivot(index="setting", columns="year", values="ret")
        for year in [y for y in table.columns if y >= first_test_year]:
            train = table[[y for y in table.columns if y < year]].apply(geometric_mean, axis=1)
            chosen = train.idxmax()
            test = table.loc[chosen, year]
            rows.append({"top": n, "year": year, "chosen": chosen, "train_cagr": train.max(), "test_ret": test,
                         "rank": int((table[year] > test).sum()) + 1, "settings": len(table),
                         "median_setting": table[year].median(), "best_setting": table[year].max()})
    return pd.DataFrame(rows)


def walk_forward_summary(grid: pd.DataFrame, picks: pd.DataFrame, fixed: str,
                         from_year: int = WF_SUMMARY_FROM) -> pd.DataFrame:
    """CAGR from `from_year` on per top N: walk-forward picks, the fixed in-sample setting, the setting best over
    the whole period in hindsight, and the median setting each year."""
    rows = []
    for n, g in grid[grid["year"] >= from_year].groupby("top"):
        table = g.pivot(index="setting", columns="year", values="ret")
        test = picks[(picks["top"] == n) & (picks["year"] >= from_year)]
        rows.append({"top": n, "walk_forward": geometric_mean(test["test_ret"]),
                     "fixed": geometric_mean(table.loc[fixed]),
                     "hindsight_best": table.apply(geometric_mean, axis=1).max(),
                     "median_setting": geometric_mean(table.median())})
    return pd.DataFrame(rows).assign(fixed_setting=fixed, years=f"{from_year}-{grid['year'].max()}")


def run_walk_forward(panel: pd.DataFrame, data, checkpoints: List[pd.Timestamp], cost: float, out_dir: str) -> None:
    spec = LISTS["large_score_only"]
    grid = setting_grid(panel, data, checkpoints, spec.tier, spec.exit_rule, cost)
    picks = walk_forward_picks(grid)
    summary = walk_forward_summary(grid, picks, LARGE_SCORE_ONLY.name)
    grid.round(4).to_csv(os.path.join(out_dir, "walk_forward_grid.csv"), index=False)
    picks.round(4).to_csv(os.path.join(out_dir, "walk_forward.csv"), index=False)
    summary.round(4).to_csv(os.path.join(out_dir, "walk_forward_summary.csv"), index=False)
    with pd.option_context("display.width", 200):
        print(picks.round(3).to_string(index=False))
        print(summary.round(3).to_string(index=False))


def run(args) -> None:
    inputs = prepare_inputs(args)
    panel = add_lookback_returns(prepare_recommended_panel(inputs.panel, inputs.close), inputs.close)
    checkpoints: List[pd.Timestamp] = list(inputs.checkpoints)
    in_years = inputs.close.index <= pd.Timestamp(max(args.years), 12, 31)
    data = daily_data(inputs.close.loc[in_years, inputs.symbols], inputs.dollar_volume.loc[in_years, inputs.symbols])
    end = data.dates[-1]
    returns = period_returns(inputs.close.loc[in_years], checkpoints)
    states = trend_state(inputs.close[REGIME_INDEX], checkpoints)
    cost = args.cost_bps / 1e4
    out_dir = os.path.join(args.out_dir, "concentration", "_".join(str(y) for y in args.years))
    os.makedirs(out_dir, exist_ok=True)

    rows, yearly_rows, contrib_rows = [], [], []
    for name, spec in LISTS.items():
        ranked = rank_variant(panel, spec.variant, RANK_DEPTH)
        ranked = ranked[ranked["tier"] == spec.tier]
        schedule = dynamic_schedule(states, DYNAMIC[spec.trend_schedule]) if spec.trend_schedule else checkpoints
        for n in TOP_NS:
            book = run_daily_book(ranked, data, schedule, n, n, EXIT_RULES[spec.exit_rule], cost)
            r = book["ret"]
            per_year = len(book) / ((end - book.index[0]).days / 365.25)
            rows.append({"list": name, "top": n, **book_summary(book, end),
                         "sharpe": r.mean() / r.std() * per_year ** 0.5, "worst_period": r.min()})
            yearly_rows.append({"list": name, "top": n, **returns_by_year(book).to_dict()})
        smallest = run_portfolio(ranked, returns, inputs.regime, min(TOP_NS), min(TOP_NS), False, cost)
        contrib = contributions(smallest, returns)
        contrib_rows.append(contrib.head(10).reset_index().assign(list=name, top=min(TOP_NS),
                                                                  top5_share=top_share(contrib)))
        print(f"done {name}", flush=True)

    summary = pd.DataFrame(rows)
    summary.round(4).to_csv(os.path.join(out_dir, "summary.csv"), index=False)
    pd.DataFrame(yearly_rows).round(4).to_csv(os.path.join(out_dir, "by_year.csv"), index=False)
    pd.concat(contrib_rows, ignore_index=True).round(4).to_csv(os.path.join(out_dir, "top_contributors.csv"),
                                                               index=False)
    with pd.option_context("display.width", 200):
        print(summary.round(3).to_string(index=False))
    run_walk_forward(panel, data, checkpoints, cost, out_dir)
    print(f"wrote {out_dir}")


def main(argv=None) -> None:
    run(parse_args(argv))


if __name__ == "__main__":
    main()

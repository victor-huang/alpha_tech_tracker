"""How the recommended top-15 lists catch the yearly top-10 winners, and how book size changes the outcome.

  * capture     for each yearly top-10 winner (top10_by_year_2020_2026.csv): whether the list held it during
                that year, how far into the year it was first held, the share of the year's log gain still ahead
                then, and the share of the year's log gain the book actually earned while holding it
  * book size   the same rules holding the top 5 / 8 / 10 / 15 names
  * random subsets  hold k names drawn at random from the top 15 (kept while still in the top 15) - the spread of
                    outcomes when you buy only part of the list

Usage:
    PYTHONPATH=. python -m alpha_tech_tracker.research.winner_capture --years 2020 2021 2022 2023 2024 2025 2026
"""
import os
from typing import Dict, List

import numpy as np
import pandas as pd

from alpha_tech_tracker.research.selection_filters import (
    BENCHMARKS,
    TIERS,
    VARIANTS,
    parse_args,
    performance,
    period_returns,
    prepare_inputs,
    rank_variant,
    run_portfolio,
    yearly,
)
from alpha_tech_tracker.research.uptrend_formation import DEFAULT_WINNERS_CSV

LISTS = {"Large": "trend+riskadj120+clean", "Mid": "trend+composite",
         "Small": "trend+composite+no_dilution+prefer_gross_profit"}
BOOK_SIZES = (5, 8, 10, 15)
RANDOM_SIZES = (3, 5, 8)
RANDOM_DRAWS = 200
FULL_LIST = 15
SEED = 7


def year_bounds(close: pd.Series, year: int):
    """Last close before the year and last close in it (NaN when missing)."""
    before = close[close.index.year < year].dropna()
    inside = close[close.index.year == year].dropna()
    return (before.iloc[-1] if len(before) else np.nan), (inside.iloc[-1] if len(inside) else np.nan)


def winner_capture(book: pd.DataFrame, winners: pd.DataFrame, close: pd.DataFrame,
                   returns: pd.DataFrame) -> pd.DataFrame:
    """One row per winner: held or not, first checkpoint held in its year, share of the year's log gain ahead at
    that point, share of it earned while held, and checkpoints held."""
    rows = []
    for w in winners.itertuples():
        in_year = book[book.index.year == w.year]
        held_cps = [cp for cp, names in in_year["held"].items() if w.symbol in names]
        start, end = year_bounds(close[w.symbol], w.year) if w.symbol in close else (np.nan, np.nan)
        year_log = np.log(end / start) if start > 0 and end > 0 else np.nan
        row = {"year": w.year, "tier": w.tier, "symbol": w.symbol, "return_pct": w.return_pct,
               "held": bool(held_cps), "checkpoints_held": len(held_cps), "first_held": pd.NaT,
               "share_ahead": np.nan, "share_captured": np.nan}
        if held_cps and year_log and year_log > 0:
            first = held_cps[0]
            row["first_held"] = first
            row["share_ahead"] = np.log(end / close.loc[first, w.symbol]) / year_log
            earned = np.log1p(returns.loc[held_cps, w.symbol].fillna(0)).sum()
            row["share_captured"] = earned / year_log
        rows.append(row)
    return pd.DataFrame(rows)


def names_per_year(book: pd.DataFrame) -> pd.Series:
    """Distinct symbols held at some checkpoint of each year."""
    return book["held"].groupby(book.index.year).apply(lambda s: len(set().union(*map(set, s))))


def shuffled_top(ranked: pd.DataFrame, rng: np.random.Generator, size: int = FULL_LIST) -> pd.DataFrame:
    """The top `size` per checkpoint with their ranks randomly permuted (fills come in random order)."""
    top = ranked[ranked["rank"] <= size].copy()
    top["rank"] = top.groupby("checkpoint")["rank"].transform(lambda r: rng.permutation(len(r)) + 1.0)
    return top


def random_subsets(ranked: pd.DataFrame, returns: pd.DataFrame, regime: pd.Series, k: int, cost: float,
                   draws: int, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    for draw in range(draws):
        book = run_portfolio(shuffled_top(ranked, rng), returns, regime, k, FULL_LIST, False, cost)
        rows.append({"draw": draw, **performance(book["ret"])})
    return pd.DataFrame(rows)


def run(args) -> None:
    inputs = prepare_inputs(args)
    panel, close, regime, checkpoints = inputs.panel, inputs.close, inputs.regime, inputs.checkpoints
    returns = period_returns(close, checkpoints)
    cost = args.cost_bps / 1e4
    winners = pd.read_csv(DEFAULT_WINNERS_CSV)
    winners = winners[winners["year"].isin(args.years)]
    out_dir = os.path.join(args.out_dir, "winner_capture")
    os.makedirs(out_dir, exist_ok=True)

    capture_rows: List[pd.DataFrame] = []
    yearly_names: Dict[str, pd.Series] = {}
    size_rows, size_yearly, random_rows = [], [], []
    for b in BENCHMARKS:
        size_rows.append({"tier": "Benchmark", "list": b, "book": np.nan, **performance(returns[b])})
    for tier in TIERS:
        universe = panel[panel["tier"] == tier].pivot(index="checkpoint", columns="symbol", values="close").notna()
        tier_ret = returns.where(universe.reindex(columns=returns.columns, fill_value=False)).mean(axis=1)
        size_rows.append({"tier": tier, "list": "universe_equal_weight", "book": np.nan, **performance(tier_ret)})
        name, variant = LISTS[tier], VARIANTS[LISTS[tier]]
        tier_winners = winners[winners["tier"] == tier]
        in_universe = set(zip(panel.loc[panel["tier"] == tier, "checkpoint"].dt.year, panel.loc[
            panel["tier"] == tier, "symbol"]))
        for buffer in (args.top, args.buffer):
            ranked = rank_variant(panel, variant, args.top)
            book = run_portfolio(ranked[ranked["tier"] == tier], returns, regime, args.top, buffer, False, cost)
            cap = winner_capture(book, tier_winners, close, returns).assign(list=name, buffer=buffer)
            cap["in_universe"] = [(y, s) in in_universe for y, s in zip(cap["year"], cap["symbol"])]
            capture_rows.append(cap)
            yearly_names[f"{tier}|buffer={buffer}"] = names_per_year(book)
        for n in BOOK_SIZES:
            ranked = rank_variant(panel, variant, n)
            book = run_portfolio(ranked[ranked["tier"] == tier], returns, regime, n, n, False, cost)
            size_rows.append({"tier": tier, "list": name, "book": n, **performance(book["ret"])})
            size_yearly.append(yearly(book["ret"]).rename((tier, n)))
        ranked = rank_variant(panel, variant, FULL_LIST)
        tier_ranked = ranked[ranked["tier"] == tier]
        for k in RANDOM_SIZES:
            draws = random_subsets(tier_ranked, returns, regime, k, cost, RANDOM_DRAWS, SEED + k)
            random_rows.append(draws.assign(tier=tier, list=name, k=k))
        print(f"done {tier}", flush=True)

    capture = pd.concat(capture_rows, ignore_index=True)
    capture.to_csv(os.path.join(out_dir, "winner_capture.csv"), index=False)
    pd.DataFrame(yearly_names).to_csv(os.path.join(out_dir, "names_held_per_year.csv"))
    pd.DataFrame(size_rows).round(4).to_csv(os.path.join(out_dir, "book_size.csv"), index=False)
    pd.DataFrame(size_yearly).round(4).to_csv(os.path.join(out_dir, "book_size_by_year.csv"))
    draws = pd.concat(random_rows, ignore_index=True)
    draws.round(4).to_csv(os.path.join(out_dir, "random_subsets.csv"), index=False)
    print(f"wrote {out_dir}")


def main(argv=None) -> None:
    run(parse_args(argv))


if __name__ == "__main__":
    main()

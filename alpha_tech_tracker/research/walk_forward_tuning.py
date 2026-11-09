"""Walk-forward tuning of the momentum ranking: does choosing settings on past years catch next year's winners
earlier, or only fit the past?

Grid (each with the trend filter, top 15 per tier, no buffer, no gate):
  * lookback        60 / 90 / 120 / 180 / 250-day return
  * vol adjustment  return / vol_60d ** a with a = 0, 0.5, 1
  * clean           exclude faded jumps and heavy-volume drops, or not
  * slots           3 big-jump + 2 fresh 52-week-high breakout slots, or not

For every setting, tier and year: the book's return and how it handled that year's top-10 winners (held at all,
share of the year's gain still ahead when first held, share of the gain earned). Walk-forward: for each test year
from 2022, pick the setting with the best record on all earlier years (by book return, or by winner capture) and
score it on the test year only.

Usage:
    PYTHONPATH=. python -m alpha_tech_tracker.research.walk_forward_tuning --years 2020 2021 2022 2023 2024 2025 2026
"""
import itertools
import os
from typing import Dict, List, NamedTuple

import numpy as np
import pandas as pd

from alpha_tech_tracker.research.selection_filters import (
    FADED_OR_DROPPED,
    SPLIT_FRESH,
    TIERS,
    VARIANTS,
    Variant,
    _trend_ok,
    parse_args,
    period_returns,
    prepare_inputs,
    rank_variant,
    run_portfolio,
    yearly,
)
from alpha_tech_tracker.research.uptrend_formation import DEFAULT_WINNERS_CSV
from alpha_tech_tracker.research.winner_capture import LISTS, winner_capture

LOOKBACKS = (60, 90, 120, 180, 250)
VOL_POWERS = (0.0, 0.5, 1.0)
FIRST_TEST_YEAR = 2022
TOP = 15


class Setting(NamedTuple):
    lookback: int
    vol_power: float
    clean: bool
    slots: bool

    @property
    def name(self) -> str:
        return (f"ret{self.lookback}/vol^{self.vol_power:g}" + ("+clean" if self.clean else "")
                + ("+slots" if self.slots else ""))


def settings() -> List[Setting]:
    return [Setting(*s) for s in itertools.product(LOOKBACKS, VOL_POWERS, (False, True), (False, True))]


def variant_for(setting: Setting) -> Variant:
    column = f"ret_{setting.lookback}d"

    def score(p: pd.DataFrame) -> pd.Series:
        return p[column] / p["vol_60d"] ** setting.vol_power

    exclude = FADED_OR_DROPPED if setting.clean else ()
    if not setting.slots:
        return Variant(_trend_ok, score, exclude=exclude)
    return Variant(_trend_ok, score, exclude=exclude, also_eligible=("gap_10d", "high_breakout_10d"),
                   boost_groups=SPLIT_FRESH)


def add_lookback_returns(panel: pd.DataFrame, close: pd.DataFrame, lookbacks=LOOKBACKS) -> pd.DataFrame:
    """ret_{L}d at each checkpoint for lookbacks the panel does not already carry."""
    p = panel.copy()
    c = close.ffill(limit=5)
    checkpoints = sorted(p["checkpoint"].unique())
    for days in lookbacks:
        column = f"ret_{days}d"
        if column in p:
            continue
        at = (c / c.shift(days) - 1).reindex(checkpoints).stack().rename(column)
        at.index.names = ["checkpoint", "symbol"]
        p = p.merge(at.reset_index(), on=["checkpoint", "symbol"], how="left")
    return p


def year_metrics(book: pd.DataFrame, winners: pd.DataFrame, close: pd.DataFrame,
                 returns: pd.DataFrame) -> pd.DataFrame:
    """Per year: book return, winners held, median share of the gain ahead at first hold, mean share captured
    (0 for winners never held)."""
    cap = winner_capture(book, winners, close, returns)
    by_year = cap.groupby("year").agg(winners=("symbol", "size"), held=("held", "sum"),
                                      ahead=("share_ahead", "median"),
                                      captured=("share_captured", lambda s: s.fillna(0).mean()))
    by_year["ret"] = yearly(book["ret"])
    return by_year


def walk_forward(grid: pd.DataFrame, objective: str, first_test_year: int = FIRST_TEST_YEAR) -> pd.DataFrame:
    """For each tier and test year, the setting with the best mean `objective` over earlier years (book return
    compounds as a geometric mean), and that setting's test-year row."""
    rows = []
    for tier, g in grid.groupby("tier"):
        for year in sorted(y for y in g["year"].unique() if y >= first_test_year):
            past = g[g["year"] < year]
            if objective == "ret":
                score = past.groupby("setting")["ret"].apply(lambda r: np.exp(np.log1p(r).mean()) - 1)
            else:
                score = past.groupby("setting")[objective].mean()
            chosen = score.idxmax()
            test = g[(g["setting"] == chosen) & (g["year"] == year)].iloc[0]
            rows.append({"tier": tier, "objective": objective, "year": year, "chosen": chosen,
                         "train_score": score.max(), **test.drop(["tier", "setting", "year"]).to_dict()})
    return pd.DataFrame(rows)


def run(args) -> None:
    inputs = prepare_inputs(args)
    close, regime, checkpoints = inputs.close, inputs.regime, inputs.checkpoints
    panel = add_lookback_returns(inputs.panel, close)
    returns = period_returns(close, checkpoints)
    cost = args.cost_bps / 1e4
    winners = pd.read_csv(DEFAULT_WINNERS_CSV)
    winners = winners[winners["year"].isin(args.years)]
    out_dir = os.path.join(args.out_dir, "walk_forward_tuning")
    os.makedirs(out_dir, exist_ok=True)

    candidates: Dict[str, Variant] = {s.name: variant_for(s) for s in settings()}
    references = {f"reference:{tier}:{name}": (tier, VARIANTS[name]) for tier, name in LISTS.items()}
    rows = []
    for name, variant in candidates.items():
        ranked = rank_variant(panel, variant, TOP)
        for tier in TIERS:
            book = run_portfolio(ranked[ranked["tier"] == tier], returns, regime, TOP, TOP, False, cost)
            m = year_metrics(book, winners[winners["tier"] == tier], close, returns)
            rows.append(m.assign(tier=tier, setting=name).reset_index())
        print(f"done {name}", flush=True)
    for name, (tier, variant) in references.items():
        ranked = rank_variant(panel, variant, TOP)
        book = run_portfolio(ranked[ranked["tier"] == tier], returns, regime, TOP, TOP, False, cost)
        m = year_metrics(book, winners[winners["tier"] == tier], close, returns)
        rows.append(m.assign(tier=tier, setting=name).reset_index())

    grid = pd.concat(rows, ignore_index=True)
    grid.round(4).to_csv(os.path.join(out_dir, "grid_by_year.csv"), index=False)
    tuned = grid[~grid["setting"].str.startswith("reference:")]
    wf = pd.concat([walk_forward(tuned, "ret"), walk_forward(tuned, "captured")], ignore_index=True)
    wf.round(4).to_csv(os.path.join(out_dir, "walk_forward.csv"), index=False)
    print(f"wrote {out_dir}")


def main(argv=None) -> None:
    run(parse_args(argv))


if __name__ == "__main__":
    main()

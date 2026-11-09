"""Does rebalancing the recommended lists less often, or on a schedule set by the market trend, change the result?

The lists are rebuilt at the biweekly checkpoints (every 10 trading days), so the schedules rebalance on a subset of
them, holding day by day in between with each tier's trailing stop (a stopped name sits in cash until the next
rebalance):

  * fixed: every 1 (2 weeks), 2 (about a month) or 6 (about 3 months) checkpoints, run from every starting offset
    so the result is not one lucky calendar phase
  * dynamic: at each checkpoint, the wanted interval depends on QQQ against its 50- and 200-day averages; rebalance
    once that many checkpoints have passed since the last rebalance

Run one year at a time (each starts in cash on the year's first checkpoint, and daily data is cut at the year's end);
every run also refreshes summary_by_year.csv, chaining all single-year results found so far. Several years in one run
give one continuous book (positions and schedules carry across year ends), with by_year.csv per calendar year.

Usage:
    PYTHONPATH=. python -m alpha_tech_tracker.research.rebalance_interval --years 2026
"""
import os
from typing import Dict, List, NamedTuple

import numpy as np
import pandas as pd

from alpha_tech_tracker.research.ranking_exits import EXIT_RULES, daily_data, run_daily_book
from alpha_tech_tracker.research.recommended_rules import RECOMMENDED, TOP, prepare_recommended_panel
from alpha_tech_tracker.research.selection_filters import parse_args, prepare_inputs, rank_variant
from alpha_tech_tracker.research.uptrend_formation import REGIME_INDEX

FIXED_INTERVALS = {"2 weeks": 1, "1 month": 2, "3 months": 6}


class TrendIntervals(NamedTuple):
    """Checkpoints between rebalances when QQQ is above both averages, above the 200-day only, or below it."""
    above_both: int
    above_200_only: int
    below_200: int


DYNAMIC: Dict[str, TrendIntervals] = {
    "uptrend 1m, else 2w": TrendIntervals(2, 1, 1),
    "uptrend 3m, else 2w": TrendIntervals(6, 1, 1),
    "uptrend 3m, above 200 1m, below 2w": TrendIntervals(6, 2, 1),
    "uptrend 2w, else 1m": TrendIntervals(1, 2, 2),
    "uptrend 2w, else 3m": TrendIntervals(1, 6, 6),
}


def trend_state(index_close: pd.Series, checkpoints: List[pd.Timestamp]) -> pd.Series:
    """Per checkpoint: "above_both", "above_200_only" or "below_200" for the index against its 50/200-day averages."""
    c = index_close.ffill()
    ma50 = c.rolling(50, min_periods=40).mean().reindex(checkpoints)
    ma200 = c.rolling(200, min_periods=160).mean().reindex(checkpoints)
    at = c.reindex(checkpoints)
    state = np.where(at <= ma200, "below_200", np.where(at > ma50, "above_both", "above_200_only"))
    return pd.Series(state, index=checkpoints)


def fixed_schedule(checkpoints: List[pd.Timestamp], every: int, offset: int) -> List[pd.Timestamp]:
    """Every `every`-th checkpoint from `offset`; the first checkpoint is always a rebalance (the book starts there)."""
    picked = checkpoints[offset::every]
    return checkpoints[:1] + [cp for cp in picked if cp != checkpoints[0]]


def dynamic_schedule(states: pd.Series, intervals: TrendIntervals) -> List[pd.Timestamp]:
    """Rebalance at a checkpoint once the interval wanted by that checkpoint's trend state has passed."""
    schedule = [states.index[0]]
    since = 0
    for cp, state in states.iloc[1:].items():
        since += 1
        if since >= getattr(intervals, state):
            schedule.append(cp)
            since = 0
    return schedule


def book_summary(book: pd.DataFrame, end: pd.Timestamp) -> Dict[str, float]:
    """Total and yearly-compounded return, worst drop measured at rebalance dates, rebalances, turnover and stops."""
    equity = pd.concat([pd.Series([1.0]), (1 + book["ret"]).cumprod().reset_index(drop=True)])
    years = (end - book.index[0]).days / 365.25
    return {"total_return": float(equity.iloc[-1] - 1), "cagr": float(equity.iloc[-1] ** (1 / years) - 1),
            "max_dd_at_rebalances": float((equity / equity.cummax() - 1).min()), "rebalances": len(book),
            "turnover": float(book["turnover"].sum()), "stops": int(book["exits"].sum())}


def returns_by_year(book: pd.DataFrame) -> pd.Series:
    """Compounded return per calendar year, each holding period credited to the year it starts in."""
    return (1 + book["ret"]).groupby(book.index.year).prod() - 1


def combine_years(root: str, exit_kind: str = "recommended") -> pd.DataFrame:
    """Single-year summaries found under `root` (each year a fresh Jan start) chained into one table per tier and
    schedule: each year's return, the compounded total and the years beating the 2-week schedule by 0.5 points."""
    frames = [pd.read_csv(os.path.join(root, d, "summary.csv")).assign(year=int(d))
              for d in sorted(os.listdir(root)) if d.isdigit() and os.path.exists(os.path.join(root, d, "summary.csv"))]
    s = pd.concat(frames, ignore_index=True)
    s = s[s["exit"] != "none"] if exit_kind == "recommended" else s[s["exit"] == "none"]
    table = s.pivot_table(index=["tier", "schedule"], columns="year", values="total_return", sort=False)
    years = list(table.columns)
    table["total"] = (1 + table[years]).prod(axis=1) - 1
    two_weeks = table.xs("2 weeks", level="schedule")[years]
    table["years_beat_2_weeks"] = [int((table.loc[i, years] > two_weeks.loc[i[0]] + 0.005).sum()) for i in table.index]
    table["turnover_per_year"] = s.groupby(["tier", "schedule"], sort=False)["turnover"].mean().reindex(table.index)
    return table


def run(args) -> None:
    inputs = prepare_inputs(args)
    panel = prepare_recommended_panel(inputs.panel, inputs.close)
    checkpoints = list(inputs.checkpoints)
    states = trend_state(inputs.close[REGIME_INDEX], checkpoints)
    in_years = inputs.close.index <= pd.Timestamp(max(args.years), 12, 31)
    data = daily_data(inputs.close.loc[in_years, inputs.symbols], inputs.dollar_volume.loc[in_years, inputs.symbols])
    cost = args.cost_bps / 1e4
    out_dir = os.path.join(args.out_dir, "rebalance_interval", "_".join(str(y) for y in args.years))
    os.makedirs(out_dir, exist_ok=True)

    schedules: Dict[str, List[List[pd.Timestamp]]] = {
        name: [fixed_schedule(checkpoints, every, offset) for offset in range(every)]
        for name, every in FIXED_INTERVALS.items()}
    schedules.update({name: [dynamic_schedule(states, intervals)] for name, intervals in DYNAMIC.items()})

    end = data.dates[-1]
    rows, yearly_rows = [], []
    for tier, (rule, variant, exit_name) in RECOMMENDED.items():
        ranked = rank_variant(panel, variant, TOP)
        ranked = ranked[ranked["tier"] == tier]
        for exit_label in (exit_name, "none"):
            for name, runs in schedules.items():
                for i, schedule in enumerate(runs):
                    book = run_daily_book(ranked, data, schedule, TOP, TOP, EXIT_RULES[exit_label], cost)
                    key = {"tier": tier, "exit": exit_label, "schedule": name, "offset": i}
                    rows.append({**key, **book_summary(book, end)})
                    yearly_rows.append({**key, **returns_by_year(book).to_dict()})
        print(f"done {tier}", flush=True)

    detail = pd.DataFrame(rows)
    detail.round(4).to_csv(os.path.join(out_dir, "by_offset.csv"), index=False)
    summary = detail.groupby(["tier", "exit", "schedule"], sort=False).agg(
        total_return=("total_return", "mean"), worst_offset=("total_return", "min"),
        best_offset=("total_return", "max"), cagr=("cagr", "mean"), max_dd_at_rebalances=("max_dd_at_rebalances", "mean"),
        rebalances=("rebalances", "mean"), turnover=("turnover", "mean"), stops=("stops", "mean")).reset_index()
    summary.round(4).to_csv(os.path.join(out_dir, "summary.csv"), index=False)
    if len(args.years) > 1:
        by_year = pd.DataFrame(yearly_rows).groupby(["tier", "exit", "schedule"], sort=False).mean().drop(
            columns="offset")
        by_year.round(4).to_csv(os.path.join(out_dir, "by_year.csv"))
    states.rename("qqq_trend").to_csv(os.path.join(out_dir, "qqq_trend.csv"))
    with pd.option_context("display.width", 200, "display.max_rows", 100):
        print(summary.round(3).to_string(index=False))
    root = os.path.dirname(out_dir)
    combine_years(root).round(4).to_csv(os.path.join(root, "summary_by_year.csv"))
    print(f"wrote {out_dir} and {root}/summary_by_year.csv")


def main(argv=None) -> None:
    run(parse_args(argv))


if __name__ == "__main__":
    main()

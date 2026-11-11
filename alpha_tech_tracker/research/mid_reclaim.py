"""Mid "reclaim + growth" list: Mid names that closed back above a flat or rising 200-day average in the last
40 trading days, sit above their 20- and 50-day averages, and grow sales at least 25% year over year.

Book: up to 15 names, checked every 2 weeks, equal weight re-split at each check, 15% trailing stop held day by day.
A name is sold when it leaves the list (reclaim older than the window, a broken average, a falling 200-day or slower
sales) or hits its stop; it is not watched or re-admitted afterwards. Open slots are filled from the list:
  * volume_surge (recommended): highest 10-day / prior 60-day dollar volume first
  * fresh_first: names the book has never held go first, volume surge within each group

A walk-forward over the reclaim window, sales-growth threshold, 200-day slope floor and the two rankings picks each
test year's setting from earlier years only.

Usage:
    PYTHONPATH=. python -m alpha_tech_tracker.research.mid_reclaim --years 2020 2021 2022 2023 2024 2025 2026
"""
import itertools
import os
from typing import Dict, List, NamedTuple

import numpy as np
import pandas as pd

from alpha_tech_tracker.research.concentration import walk_forward_picks, walk_forward_summary
from alpha_tech_tracker.research.rebalance_interval import book_summary, returns_by_year
from alpha_tech_tracker.research.selection_filters import parse_args, prepare_inputs

TIER = "Mid"
SLOTS = 15
STOP = 0.15
SLOPE_DAYS = 20
SURGE_DAYS = 10
SURGE_BASE_DAYS = 60
VOLUME_SURGE = "volume_surge"
FRESH_FIRST = "fresh_first"
RANKINGS = (VOLUME_SURGE, FRESH_FIRST)
WINDOWS = (20, 40, 60)
GROWTHS = (0.15, 0.25, 0.40)
SLOPES = (-0.01, 0.0, 0.01)
FIRST_TEST_YEAR = 2022
SUMMARY_FROM = 2022


class MidSetting(NamedTuple):
    reclaim_days: int = 40
    sales_growth: float = 0.25
    min_slope: float = 0.0
    ranking: str = VOLUME_SURGE

    @property
    def name(self) -> str:
        return f"reclaim{self.reclaim_days}_growth{self.sales_growth:.0%}_slope{self.min_slope:+.0%}_{self.ranking}"


RECOMMENDED = MidSetting()


def reclaim_features(close: pd.DataFrame, dollar_volume: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    """Daily frames: trading days since the last close below the 200-day, above the 20/50/200-day averages,
    the 200-day's change over SLOPE_DAYS, and 10-day over prior 60-day dollar volume."""
    ma200 = close.rolling(200, min_periods=180).mean()
    below = close < ma200
    day = np.arange(len(close))
    last_below = pd.DataFrame(np.where(below.values, day[:, None], np.nan), index=close.index,
                              columns=close.columns).ffill()
    return {
        "days_since_reclaim": last_below.rsub(pd.Series(day, index=close.index), axis=0),
        "above_averages": (close > close.rolling(20).mean()) & (close > close.rolling(50).mean()) & (close > ma200),
        "ma200_slope": ma200 / ma200.shift(SLOPE_DAYS) - 1,
        "volume_surge": dollar_volume.rolling(SURGE_DAYS).mean()
        / dollar_volume.rolling(SURGE_BASE_DAYS).mean().shift(SURGE_DAYS),
    }


def attach_features(panel: pd.DataFrame, features: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    """The tier's panel rows with the daily features read at each checkpoint."""
    p = panel[panel["tier"] == TIER].copy()
    keys = pd.MultiIndex.from_frame(p[["checkpoint", "symbol"]])
    for name, frame in features.items():
        p[name] = frame.stack(dropna=False).reindex(keys).values
    return p


def reclaim_list(panel: pd.DataFrame, setting: MidSetting) -> Dict[pd.Timestamp, List[str]]:
    """Per checkpoint, the names passing the setting's filter, highest volume surge first."""
    ok = (panel["above_averages"].fillna(False).astype(bool)
          & (panel["days_since_reclaim"] <= setting.reclaim_days)
          & (panel["ma200_slope"] >= setting.min_slope)
          & (panel["rev_yoy"] >= setting.sales_growth))
    p = panel[ok].sort_values(["checkpoint", "volume_surge"], ascending=[True, False])
    return {cp: list(g["symbol"]) for cp, g in p.groupby("checkpoint")}


def order_candidates(candidates: List[str], held_before: set, ranking: str) -> List[str]:
    """Candidates in buying order: as listed, or never-held names first with the listed order kept in each group."""
    if ranking == FRESH_FIRST:
        return [s for s in candidates if s not in held_before] + [s for s in candidates if s in held_before]
    return list(candidates)


def run_reclaim_book(lists: Dict[pd.Timestamp, List[str]], close: pd.DataFrame, checkpoints: List[pd.Timestamp],
                     ranking: str = VOLUME_SURGE, n: int = SLOTS, stop: float = STOP,
                     cost: float = 1e-3) -> pd.DataFrame:
    """Hold up to n names from the list day by day. At each checkpoint sell names off the list, fill open slots
    from the list in `ranking` order and re-split equally; between checkpoints a trailing stop sells to cash.

    Returns per checkpoint: return to the next checkpoint, names held, one-way turnover and stop exits."""
    c = close.ffill()
    price = c.values
    daily = c.pct_change(fill_method=None).fillna(0.0).values
    col = {s: i for i, s in enumerate(c.columns)}
    starts = list(c.index.get_indexer(checkpoints))
    ends = starts[1:] + [len(c.index) - 1]
    positions: Dict[str, float] = {}
    peaks: Dict[str, float] = {}
    held_before: set = set()
    cash = 1.0
    rows = []
    for cp, start, end in zip(checkpoints, starts, ends):
        listed = [s for s in lists.get(cp, []) if s in col]
        start_value = cash + sum(positions.values())
        keep = [s for s in positions if s in listed]
        buys = [s for s in order_candidates(listed, held_before, ranking) if s not in keep][:max(n - len(keep), 0)]
        held = keep + buys
        target = {s: 1.0 / len(held) for s in held} if held else {}
        current = {s: v / start_value for s, v in positions.items()}
        turnover = sum(abs(target.get(s, 0.0) - current.get(s, 0.0)) for s in set(target) | set(current))
        value = start_value * (1 - cost * turnover)
        positions = {s: value * w for s, w in target.items()}
        cash = value - sum(positions.values())
        peaks = {s: peaks[s] if s in keep else price[start, col[s]] for s in held}
        held_before.update(buys)
        exits = 0
        for day in range(start + 1, end + 1):
            for s in list(positions):
                j = col[s]
                positions[s] *= 1 + daily[day, j]
                peaks[s] = max(peaks[s], price[day, j])
                if price[day, j] <= peaks[s] * (1 - stop):
                    cash += positions.pop(s) * (1 - cost)
                    peaks.pop(s)
                    exits += 1
        rows.append({"checkpoint": cp, "ret": (cash + sum(positions.values())) / start_value - 1,
                     "names": len(held), "turnover": turnover / 2, "exits": exits})
    return pd.DataFrame(rows).set_index("checkpoint")


def settings() -> List[MidSetting]:
    return [MidSetting(*combo) for combo in itertools.product(WINDOWS, GROWTHS, SLOPES, RANKINGS)]


def setting_grid(panel: pd.DataFrame, close: pd.DataFrame, checkpoints: List[pd.Timestamp],
                 cost: float) -> pd.DataFrame:
    """Yearly return of the book for every setting, in the shape concentration.walk_forward_picks reads."""
    rows = []
    for s in settings():
        book = run_reclaim_book(reclaim_list(panel, s), close, checkpoints, s.ranking, cost=cost)
        rows += [{"setting": s.name, "top": SLOTS, "year": int(y), "ret": r} for y, r in returns_by_year(book).items()]
    return pd.DataFrame(rows)


def run(args) -> None:
    inputs = prepare_inputs(args)
    in_years = inputs.close.index <= pd.Timestamp(max(args.years), 12, 31)
    symbols = sorted(set(inputs.panel.loc[inputs.panel["tier"] == TIER, "symbol"]) & set(inputs.close.columns))
    close = inputs.close.loc[in_years, symbols]
    features = reclaim_features(close, inputs.dollar_volume.loc[in_years, symbols])
    panel = attach_features(inputs.panel, features)
    checkpoints = list(inputs.checkpoints)
    cost = args.cost_bps / 1e4
    end = close.index[-1]
    out_dir = os.path.join(args.out_dir, "mid_reclaim", "_".join(str(y) for y in args.years))
    os.makedirs(out_dir, exist_ok=True)

    rows, yearly = [], []
    for s in (RECOMMENDED, RECOMMENDED._replace(ranking=FRESH_FIRST)):
        book = run_reclaim_book(reclaim_list(panel, s), close, checkpoints, s.ranking, cost=cost)
        rows.append({"setting": s.name, **book_summary(book, end), "avg_names": float(book["names"].mean())})
        yearly.append({"setting": s.name, **{str(k): v for k, v in returns_by_year(book).items()}})
    current = reclaim_list(panel, RECOMMENDED).get(checkpoints[-1], [])

    grid = setting_grid(panel, close, checkpoints, cost)
    picks = walk_forward_picks(grid, FIRST_TEST_YEAR)
    summary = walk_forward_summary(grid, picks, RECOMMENDED.name, SUMMARY_FROM)

    pd.DataFrame(rows).round(4).to_csv(os.path.join(out_dir, "summary.csv"), index=False)
    pd.DataFrame(yearly).round(4).to_csv(os.path.join(out_dir, "by_year.csv"), index=False)
    grid.round(4).to_csv(os.path.join(out_dir, "walk_forward_grid.csv"), index=False)
    picks.round(4).to_csv(os.path.join(out_dir, "walk_forward.csv"), index=False)
    summary.round(4).to_csv(os.path.join(out_dir, "walk_forward_summary.csv"), index=False)
    with pd.option_context("display.width", 250):
        print(pd.DataFrame(rows).round(3).to_string(index=False))
        print(pd.DataFrame(yearly).round(3).to_string(index=False))
        print(picks.round(3).to_string(index=False))
        print(summary.round(3).to_string(index=False))
    print(f"list at {checkpoints[-1].date()}: {', '.join(current) or 'none'}")
    print(f"wrote {out_dir}")


def main(argv=None) -> None:
    run(parse_args(argv))


if __name__ == "__main__":
    main()

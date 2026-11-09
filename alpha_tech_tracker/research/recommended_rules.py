"""The recommended top-15 rules in one place, and the backtest behind the choices still open on them:

  * Small safeguards: the $20M dollar-volume floor and the 8-checkpoint streak cap, alone and together
  * exits for both tiers: selling a held name between checkpoints (below the 50-day average, trailing stops, down-jumps)

Every book is top 15, equal weight, rebalanced every 10 trading days, no buffer and no market gate.

Usage:
    PYTHONPATH=. python -m alpha_tech_tracker.research.recommended_rules --years 2020 2021 2022 2023 2024 2025 2026
"""
import os
from typing import Dict, Tuple

import pandas as pd

from alpha_tech_tracker.research.ranking_exits import EXIT_RULES, daily_data, run_daily_book
from alpha_tech_tracker.research.selection_filters import (
    SMALL_STREAK_CAP,
    VARIANTS,
    Variant,
    parse_args,
    performance,
    period_returns,
    prepare_inputs,
    rank_variant,
    run_portfolio,
    yearly,
)
from alpha_tech_tracker.research.walk_forward_tuning import Setting, add_lookback_returns, variant_for

TOP = 15
LARGE_SETTING = Setting(lookback=180, vol_power=0.5, clean=False, slots=True)
SMALL_BASE = "trend+composite+no_dilution+prefer_gross_profit"
EXITS = ("none", "ma50", "trail15", "trail25", "ma50+down_jump")

SMALL_VARIANTS: Dict[str, Variant] = {
    SMALL_BASE: VARIANTS[SMALL_BASE],
    f"{SMALL_BASE}+liquid": VARIANTS[SMALL_BASE]._replace(liquid=True),
    f"{SMALL_BASE}+streak_cap": VARIANTS[SMALL_BASE]._replace(max_streak=SMALL_STREAK_CAP),
    f"{SMALL_BASE}+liquid+streak_cap": VARIANTS[SMALL_BASE]._replace(liquid=True, max_streak=SMALL_STREAK_CAP),
}

# tier -> (rule name, variant, exit rule name). Exits from this module's backtest: a 25% trailing stop is neutral
# on Large return and trims drawdown; a 15% one halves the Small drawdown (mostly the 2020 crash).
RECOMMENDED: Dict[str, Tuple[str, Variant, str]] = {
    "Large": (LARGE_SETTING.name, variant_for(LARGE_SETTING), "trail25"),
    "Small": (SMALL_BASE, SMALL_VARIANTS[SMALL_BASE], "trail15"),
}


def prepare_recommended_panel(panel: pd.DataFrame, close: pd.DataFrame) -> pd.DataFrame:
    """The checkpoint panel plus the 180-day return the Large rule ranks on."""
    return add_lookback_returns(panel, close, (LARGE_SETTING.lookback,))


def run(args) -> None:
    inputs = prepare_inputs(args)
    panel = prepare_recommended_panel(inputs.panel, inputs.close)
    returns = period_returns(inputs.close, inputs.checkpoints)
    cost = args.cost_bps / 1e4
    out_dir = os.path.join(args.out_dir, "recommended_rules")
    os.makedirs(out_dir, exist_ok=True)
    perf_rows, yearly_rows = [], []

    def record(tier: str, label: str, book: pd.DataFrame) -> None:
        extra = {"exits_per_year": book["exits"].sum() / (len(book) / 25.2)} if "exits" in book else {}
        perf_rows.append({"tier": tier, "rule": label, "turnover_per_rebalance": book["turnover"].mean(),
                          "avg_names": book["names"].mean(), **extra, **performance(book["ret"])})
        yearly_rows.append(yearly(book["ret"]).rename((tier, label)))

    for name, variant in SMALL_VARIANTS.items():
        ranked = rank_variant(panel, variant, TOP)
        record("Small", name, run_portfolio(ranked[ranked["tier"] == "Small"], returns, inputs.regime, TOP, TOP,
                                            False, cost))
        print(f"done {name}", flush=True)

    symbols = inputs.symbols
    data = daily_data(inputs.close[symbols], inputs.dollar_volume[symbols])
    for tier, (name, variant, _) in RECOMMENDED.items():
        ranked = rank_variant(panel, variant, TOP)
        ranked = ranked[ranked["tier"] == tier]
        for exit_name in EXITS:
            book = run_daily_book(ranked, data, inputs.checkpoints, TOP, TOP, EXIT_RULES[exit_name], cost)
            record(tier, f"{name}|exit={exit_name}", book)
            print(f"done {tier} exit {exit_name}", flush=True)

    pd.DataFrame(perf_rows).round(4).to_csv(os.path.join(out_dir, "performance.csv"), index=False)
    pd.DataFrame(yearly_rows).round(4).to_csv(os.path.join(out_dir, "by_year.csv"))
    print(f"wrote {out_dir}")


def main(argv=None) -> None:
    run(parse_args(argv))


if __name__ == "__main__":
    main()

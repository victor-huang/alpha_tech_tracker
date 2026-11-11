"""A conditional short hedge on top of the Large book: while QQQ closes below both its 50- and 200-day averages at a
checkpoint, short the weakest liquid Large names (lowest 180-day return / vol^0.5 among the most traded) at a fixed
fraction of the book until the next checkpoint. The basket is rebuilt every checkpoint and carries no stop.

Costs: 10 bps per unit traded on the short side (entries, exits and basket changes) plus a borrow rate while on.

Usage:
    PYTHONPATH=. python -m alpha_tech_tracker.research.short_hedge --years 2020 2021 2022 2023 2024 2025 2026
"""
import os
from typing import List

import pandas as pd

from alpha_tech_tracker.research.concentration import LISTS
from alpha_tech_tracker.research.ranking_exits import EXIT_RULES, daily_data, run_daily_book
from alpha_tech_tracker.research.rebalance_interval import returns_by_year
from alpha_tech_tracker.research.recommended_rules import prepare_recommended_panel
from alpha_tech_tracker.research.selection_filters import parse_args, period_returns, prepare_inputs, rank_variant
from alpha_tech_tracker.research.uptrend_formation import REGIME_INDEX

SHORT_NAMES = 15
LIQUID_RANK = 300
HEDGE_FRACTION = 0.5
BORROW_RATE = 0.01
FRACTIONS = (0.25, 0.5)
SMALL_WEIGHTS = (0.0, 0.3)


def downtrend(index_close: pd.Series, checkpoints: List[pd.Timestamp]) -> pd.Series:
    """True at checkpoints where the index closes below both its 50- and 200-day averages."""
    c = index_close.ffill()
    at = c.reindex(checkpoints)
    below = (at < c.rolling(50).mean().reindex(checkpoints)) & (at < c.rolling(200).mean().reindex(checkpoints))
    return below.fillna(False)


def weakest(panel: pd.DataFrame, tier: str = "Large", n: int = SHORT_NAMES,
            liquid_rank: int = LIQUID_RANK) -> pd.DataFrame:
    """Per checkpoint, the n lowest 180-day scores among the tier's `liquid_rank` most traded names, rank 1 = weakest."""
    p = panel[panel["tier"] == tier].copy()
    p["dv_rank"] = p.groupby("checkpoint")["dollar_volume_20d"].rank(ascending=False)
    p["score"] = p["ret_180d"] / p["vol_60d"] ** 0.5
    p = p[(p["dv_rank"] <= liquid_rank) & p["score"].notna()]
    p["rank"] = p.groupby("checkpoint")["score"].rank(method="first")
    return p.loc[p["rank"] <= n, ["checkpoint", "symbol", "score", "rank"]].sort_values(["checkpoint", "rank"])


def basket_returns(basket: pd.DataFrame, returns: pd.DataFrame) -> pd.Series:
    """Equal-weight period return of the basket at each checkpoint."""
    return pd.Series({cp: returns.loc[cp, g["symbol"]].mean() for cp, g in basket.groupby("checkpoint")})


def basket_turnover(basket: pd.DataFrame, on: pd.Series) -> pd.Series:
    """One-way short turnover per checkpoint as a share of the hedge: a full basket when the hedge switches on or
    off, otherwise the share of names replaced."""
    names = {cp: set(g["symbol"]) for cp, g in basket.groupby("checkpoint")}
    out, previous, was_on = {}, set(), False
    for cp in on.index:
        current = names.get(cp, set()) if on[cp] else set()
        replaced = len(current - previous) / len(current) if current else 0.0
        out[cp] = 1.0 if was_on != bool(on[cp]) else replaced
        previous, was_on = current, bool(on[cp])
    return pd.Series(out)


def hedged_returns(book: pd.Series, basket_ret: pd.Series, on: pd.Series, fraction: float, cost: float,
                   borrow_rate: float = BORROW_RATE, turnover: pd.Series = None) -> pd.Series:
    """Book period returns minus `fraction` of the basket's return while `on`, less trading and borrow costs."""
    on = on.reindex(book.index).fillna(False).astype(bool)
    short = basket_ret.reindex(book.index).fillna(0.0).where(on, 0.0)
    days = pd.Series(book.index, index=book.index).diff().shift(-1).dt.days.fillna(14)
    borrow = (borrow_rate * days / 365).where(on, 0.0)
    traded = turnover.reindex(book.index).fillna(0.0) if turnover is not None else on.astype(float)
    return book - fraction * (short + borrow + cost * traded)


def summarize(name: str, r: pd.Series, end: pd.Timestamp) -> dict:
    equity = (1 + r).cumprod()
    years = (end - r.index[0]).days / 365.25
    per_year = len(r) / years
    return {"book": name, "cagr": float(equity.iloc[-1] ** (1 / years) - 1),
            "max_dd_at_rebalances": float((equity / equity.cummax() - 1).min()),
            "sharpe": float(r.mean() / r.std() * per_year ** 0.5), "worst_period": float(r.min())}


def run(args) -> None:
    inputs = prepare_inputs(args)
    panel = prepare_recommended_panel(inputs.panel, inputs.close)
    checkpoints = list(inputs.checkpoints)
    in_years = inputs.close.index <= pd.Timestamp(max(args.years), 12, 31)
    data = daily_data(inputs.close.loc[in_years, inputs.symbols], inputs.dollar_volume.loc[in_years, inputs.symbols])
    end = data.dates[-1]
    returns = period_returns(inputs.close.loc[in_years], checkpoints)
    cost = args.cost_bps / 1e4
    out_dir = os.path.join(args.out_dir, "short_hedge", "_".join(str(y) for y in args.years))
    os.makedirs(out_dir, exist_ok=True)

    on = downtrend(inputs.close[REGIME_INDEX], checkpoints)
    basket = weakest(panel)
    basket_ret = basket_returns(basket, returns)
    turnover = basket_turnover(basket, on)
    books = {}
    for name, key, exit_rule in (("Large", "large_slots", "trail25"), ("Small", "small", "trail15")):
        spec = LISTS[key]
        ranked = rank_variant(panel, spec.variant, 15)
        ranked = ranked[ranked["tier"] == spec.tier]
        books[name] = run_daily_book(ranked, data, checkpoints, 15, 15, EXIT_RULES[exit_rule], cost)["ret"]

    rows, yearly = [], []
    for small_weight in SMALL_WEIGHTS:
        long_book = (1 - small_weight) * books["Large"] + small_weight * books["Small"]
        base_name = "Large" if small_weight == 0 else f"Large {1 - small_weight:.0%} / Small {small_weight:.0%}"
        for fraction in (0.0,) + FRACTIONS:
            r = hedged_returns(long_book, basket_ret, on, fraction, cost, turnover=turnover)
            name = base_name if fraction == 0 else f"{base_name} + short {fraction:.0%} weakest in downtrend"
            rows.append(summarize(name, r, end))
            yearly.append({"book": name, **{str(k): v for k, v in returns_by_year(pd.DataFrame({"ret": r})).items()}})
    summary = pd.DataFrame(rows)
    summary.round(4).to_csv(os.path.join(out_dir, "summary.csv"), index=False)
    pd.DataFrame(yearly).round(4).to_csv(os.path.join(out_dir, "by_year.csv"), index=False)
    basket.merge(basket_ret.rename("basket_ret"), left_on="checkpoint", right_index=True) \
        .merge(on.rename("hedge_on"), left_on="checkpoint", right_index=True) \
        .round(4).to_csv(os.path.join(out_dir, "basket.csv"), index=False)
    with pd.option_context("display.width", 200):
        print(f"hedge on at {int(on.sum())} of {len(on)} checkpoints")
        print(summary.round(3).to_string(index=False))
        print(pd.DataFrame(yearly).round(3).to_string(index=False))
    print(f"wrote {out_dir}")


def main(argv=None) -> None:
    run(parse_args(argv))


if __name__ == "__main__":
    main()

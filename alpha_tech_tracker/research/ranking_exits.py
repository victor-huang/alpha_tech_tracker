"""Alternative momentum scores and exit / sizing rules for the top-15 selection books.

Scores (each eligible only in a confirmed uptrend, like the selection_filters.py rules):

  * resid120        sum of the last 120 days' log returns left after removing the stock's SPY beta (estimated
                    over 250 days), divided by their volatility - momentum the market move does not explain
  * industry_rel120 120-day return minus the median of its Nasdaq industry (5+ members), per unit of volatility
  * high52          closeness to the 52-week high
  * skip20          120-day return excluding the last 20 days, per unit of volatility
  * blend           average percentile of risk_adj_120, resid120 and high52

Exits and sizing are tested with a daily book: after each biweekly pick a holding is sold at the close the rule
fires (close under its 50-day average, a fall from its peak since entry, or a heavy-volume down-jump) and the
money waits in cash until the next checkpoint. Inverse-volatility weighting replaces equal weights.

Usage:
    PYTHONPATH=. python -m alpha_tech_tracker.research.ranking_exits --years 2020 2021 2022 2023 2024 2025 2026
"""
import os
from typing import Dict, List, NamedTuple, Optional

import numpy as np
import pandas as pd

from alpha_tech_tracker.research.price_factors import jump_days
from alpha_tech_tracker.research.selection_filters import (
    BENCHMARKS,
    FADED_OR_DROPPED,
    TIERS,
    Variant,
    _composite,
    _trend_ok,
    parse_args,
    period_returns,
    performance,
    pick_top,
    prepare_inputs,
    rank_variant,
    run_portfolio,
    signal_test,
    yearly,
)

MARKET = "SPY"
BETA_WINDOW = 250
BETA_MIN_OBS = 200
RESID_WINDOW = 120
RESID_MIN_OBS = 100
MIN_INDUSTRY_MEMBERS = 5


class ExitRule(NamedTuple):
    below_ma50: bool = False
    trail: Optional[float] = None
    down_jump: bool = False
    inverse_vol: bool = False


EXIT_RULES: Dict[str, ExitRule] = {
    "none": ExitRule(),
    "ma50": ExitRule(below_ma50=True),
    "trail15": ExitRule(trail=0.15),
    "trail25": ExitRule(trail=0.25),
    "down_jump": ExitRule(down_jump=True),
    "ma50+down_jump": ExitRule(below_ma50=True, down_jump=True),
    "inverse_vol": ExitRule(inverse_vol=True),
    "inverse_vol+ma50": ExitRule(below_ma50=True, inverse_vol=True),
}


def residual_momentum(close: pd.DataFrame, market: pd.Series, checkpoints: List[pd.Timestamp]) -> pd.DataFrame:
    """(checkpoint x symbol) t-stat-like residual momentum: sum of the last RESID_WINDOW daily log residuals
    r - beta * r_market over their volatility * sqrt(days); beta from the trailing BETA_WINDOW days."""
    log_ret = np.log(close.ffill(limit=5)).diff()
    m = np.log(market.reindex(close.index).ffill()).diff().fillna(0.0).values
    rows = {}
    for cp in checkpoints:
        i = close.index.get_loc(cp)
        if i < BETA_WINDOW:
            continue
        window = log_ret.values[i - BETA_WINDOW + 1:i + 1]
        mask = ~np.isnan(window)
        r = np.where(mask, window, 0.0)
        mk = np.where(mask, m[i - BETA_WINDOW + 1:i + 1, None], 0.0)
        obs = mask.sum(axis=0)
        with np.errstate(invalid="ignore", divide="ignore"):
            mean_r, mean_m = r.sum(axis=0) / obs, mk.sum(axis=0) / obs
            beta = ((r * mk).sum(axis=0) / obs - mean_r * mean_m) / ((mk ** 2).sum(axis=0) / obs - mean_m ** 2)
            resid = np.where(mask, r - beta * mk, 0.0)[-RESID_WINDOW:]
            recent = mask[-RESID_WINDOW:].sum(axis=0)
            total = resid.sum(axis=0)
            sd = np.sqrt((resid ** 2).sum(axis=0) / recent - (total / recent) ** 2)
            score = total / (sd * np.sqrt(recent))
        score[(obs < BETA_MIN_OBS) | (recent < RESID_MIN_OBS)] = np.nan
        rows[cp] = score
    return pd.DataFrame.from_dict(rows, orient="index", columns=close.columns)


def industry_relative(panel: pd.DataFrame) -> pd.Series:
    """120-day return minus its industry's median (NaN for groups under MIN_INDUSTRY_MEMBERS), over vol_60d."""
    by = panel.groupby(["checkpoint", "industry"])["ret_120d"]
    median = by.transform("median").where(by.transform("size") >= MIN_INDUSTRY_MEMBERS)
    return (panel["ret_120d"] - median) / panel["vol_60d"]


def add_ranking_scores(panel: pd.DataFrame, resid: pd.DataFrame) -> pd.DataFrame:
    p = panel.copy()
    at = resid.stack().rename("resid120")
    at.index.names = ["checkpoint", "symbol"]
    p = p.merge(at.reset_index(), on=["checkpoint", "symbol"], how="left")
    p["industry_rel120"] = industry_relative(p)
    p["skip20"] = ((1 + p["ret_120d"]) / (1 + p["ret_20d"]) - 1) / p["vol_60d"]
    by = p.groupby(["checkpoint", "tier"])
    p["blend"] = (by["risk_adj_120"].rank(pct=True) + by["resid120"].rank(pct=True)
                  + by["off_52w_high"].rank(pct=True)) / 3
    p["composite_resid"] = _composite(p.assign(risk_adj_120=p["resid120"]))
    return p


def _column(name: str):
    return lambda p: p[name]


SCORES = {"riskadj120": "risk_adj_120", "composite": "composite", "resid120": "resid120",
          "industry_rel120": "industry_rel120", "high52": "off_52w_high", "skip20": "skip20", "blend": "blend",
          "composite_resid": "composite_resid"}
SCORE_VARIANTS: Dict[str, Variant] = {}
for _name, _col in SCORES.items():
    SCORE_VARIANTS[f"trend+{_name}"] = Variant(_trend_ok, _column(_col))
    SCORE_VARIANTS[f"trend+{_name}+clean"] = Variant(_trend_ok, _column(_col), exclude=FADED_OR_DROPPED)
for _name in ("composite", "composite_resid", "blend"):
    SCORE_VARIANTS[f"trend+{_name}+prefer_turnaround"] = Variant(_trend_ok, _column(SCORES[_name]),
                                                                 prefer=("turnaround",))
EXIT_BASES = ("trend+riskadj120+clean", "trend+composite", "trend+composite+prefer_turnaround")


class DailyData(NamedTuple):
    returns: np.ndarray
    close: np.ndarray
    ma50: np.ndarray
    down_jump: np.ndarray
    columns: Dict[str, int]
    dates: pd.DatetimeIndex


def daily_data(close: pd.DataFrame, dollar_volume: pd.DataFrame) -> DailyData:
    c = close.ffill()
    ma50 = close.ffill(limit=5).rolling(50, min_periods=40).mean()
    down = jump_days(close.ffill(limit=5), dollar_volume)["down"]
    return DailyData(c.pct_change(fill_method=None).fillna(0.0).values, c.values, ma50.values,
                     down.reindex(columns=close.columns, fill_value=False).values,
                     {s: i for i, s in enumerate(close.columns)}, close.index)


def _target_weights(held: List[str], vol: Dict[str, float], inverse_vol: bool) -> Dict[str, float]:
    if not held:
        return {}
    if not inverse_vol:
        return {s: 1.0 / len(held) for s in held}
    known = [v for v in (vol.get(s) for s in held) if v and np.isfinite(v)]
    fallback = float(np.median(known)) if known else 1.0
    raw = {s: 1.0 / (vol.get(s) if vol.get(s) and np.isfinite(vol.get(s)) else fallback) for s in held}
    total = sum(raw.values())
    return {s: w / total for s, w in raw.items()}


def run_daily_book(ranked: pd.DataFrame, data: DailyData, checkpoints: List[pd.Timestamp], n: int, buffer: int,
                   rule: ExitRule, cost: float, vol: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    """Biweekly picks as in run_portfolio, held day by day so `rule` can sell a name between checkpoints.

    Returns per checkpoint: net return to the next checkpoint, names bought, one-way turnover and exits.
    """
    by_cp = {cp: g.sort_values("rank") for cp, g in ranked.groupby("checkpoint")}
    starts = list(data.dates.get_indexer(checkpoints))
    ends = starts[1:] + [len(data.dates) - 1]
    positions: Dict[str, float] = {}
    peaks: Dict[str, float] = {}
    cash = 1.0
    rows = []
    for cp, start, end in zip(checkpoints, starts, ends):
        start_value = cash + sum(positions.values())
        g = by_cp.get(cp)
        held = list(positions)
        if g is not None:
            rank_of = dict(zip(g["symbol"], g["rank"]))
            held = sorted([s for s in held if rank_of.get(s, np.inf) <= buffer], key=rank_of.get)[:n]
            for s in g["symbol"]:
                if len(held) >= n:
                    break
                if s not in held:
                    held.append(s)
        else:
            held = []
        vol_at = vol.loc[cp].to_dict() if vol is not None and cp in vol.index else {}
        target = _target_weights(held, vol_at, rule.inverse_vol)
        current = {s: v / start_value for s, v in positions.items()}
        turnover = sum(abs(target.get(s, 0.0) - current.get(s, 0.0)) for s in set(target) | set(current))
        positions = {s: start_value * w for s, w in target.items()}
        cash = start_value - sum(positions.values())
        peaks = {s: peaks.get(s, data.close[start, data.columns[s]]) if s in current else
                 data.close[start, data.columns[s]] for s in positions}
        exits = 0
        for day in range(start + 1, end + 1):
            for s in list(positions):
                j = data.columns[s]
                positions[s] *= 1 + data.returns[day, j]
                price = data.close[day, j]
                peaks[s] = max(peaks[s], price)
                if _exit_fires(rule, price, data.ma50[day, j], peaks[s], data.down_jump[day, j]):
                    cash += positions.pop(s) * (1 - cost)
                    peaks.pop(s)
                    exits += 1
        gross = (cash + sum(positions.values())) / start_value - 1
        net = gross - cost * turnover
        scale = (1 + net) / (1 + gross)
        positions = {s: v * scale for s, v in positions.items()}
        cash *= scale
        rows.append({"checkpoint": cp, "ret": net, "names": len(target),
                     "turnover": turnover / 2, "exits": exits})
    return pd.DataFrame(rows).set_index("checkpoint")


def _exit_fires(rule: ExitRule, price: float, ma50: float, peak: float, down_jump: bool) -> bool:
    if rule.below_ma50 and price < ma50:
        return True
    if rule.trail is not None and price / peak - 1 <= -rule.trail:
        return True
    return bool(rule.down_jump and down_jump)


def run(args) -> None:
    inputs = prepare_inputs(args)
    panel, close, regime, checkpoints, symbols = (inputs.panel, inputs.close, inputs.regime, inputs.checkpoints,
                                                  inputs.symbols)
    panel = add_ranking_scores(panel, residual_momentum(close[symbols], close[MARKET], checkpoints))
    returns = period_returns(close, checkpoints)
    data = daily_data(close[symbols], inputs.dollar_volume[symbols])
    vol = panel.pivot(index="checkpoint", columns="symbol", values="vol_60d")
    cost = args.cost_bps / 1e4

    out_dir = os.path.join(args.out_dir, "ranking_exits")
    os.makedirs(out_dir, exist_ok=True)
    signal_rows, perf_rows, yearly_rows = [], [], []
    for b in BENCHMARKS:
        perf_rows.append({"study": "benchmark", "tier": "Benchmark", "variant": b, **performance(returns[b])})
        yearly_rows.append(yearly(returns[b]).rename(("Benchmark", b)))
    for tier in TIERS:
        universe = panel[panel["tier"] == tier].pivot(index="checkpoint", columns="symbol", values="close").notna()
        tier_ret = returns.where(universe.reindex(columns=returns.columns, fill_value=False)).mean(axis=1)
        perf_rows.append({"study": "benchmark", "tier": tier, "variant": "universe_equal_weight",
                          **performance(tier_ret)})
        yearly_rows.append(yearly(tier_ret).rename((tier, "universe_equal_weight")))

    ranked_by_variant = {}
    for name, variant in SCORE_VARIANTS.items():
        ranked = rank_variant(panel, variant, args.top)
        ranked_by_variant[name] = ranked
        signal_rows.append(signal_test(panel, pick_top(ranked, args.top), regime).assign(variant=name))
        for tier in TIERS:
            for buffer in (args.top, args.buffer):
                book = run_portfolio(ranked[ranked["tier"] == tier], returns, regime, args.top, buffer, False, cost)
                perf_rows.append({"study": "score", "tier": tier, "variant": name, "buffer": buffer,
                                  "turnover_per_rebalance": book["turnover"].mean(), **performance(book["ret"])})
                yearly_rows.append(yearly(book["ret"]).rename((tier, f"{name}|buffer={buffer}")))

    for base in EXIT_BASES:
        ranked = ranked_by_variant[base]
        for tier in TIERS:
            tier_ranked = ranked[ranked["tier"] == tier]
            for rule_name, rule in EXIT_RULES.items():
                for buffer in (args.top, args.buffer):
                    book = run_daily_book(tier_ranked, data, checkpoints, args.top, buffer, rule, cost, vol)
                    label = f"{base}|exit={rule_name}"
                    perf_rows.append({"study": "exit", "tier": tier, "variant": label, "buffer": buffer,
                                      "turnover_per_rebalance": book["turnover"].mean(),
                                      "exits_per_year": book["exits"].sum() / (len(book) / 25.2),
                                      **performance(book["ret"])})
                    yearly_rows.append(yearly(book["ret"]).rename((tier, f"{label}|buffer={buffer}")))
            print(f"exits done: {base} {tier}")

    signal = pd.concat(signal_rows, ignore_index=True)
    signal.groupby(["variant", "tier", "index_above_ma200"]).agg(
        excess_pct=("excess", lambda s: s.mean() * 100), share_positive=("excess", lambda s: (s > 0).mean()),
        checkpoints=("excess", "size")).round(3).to_csv(os.path.join(out_dir, "signal_by_regime.csv"))
    signal["year"] = pd.to_datetime(signal["checkpoint"]).dt.year
    (signal.groupby(["variant", "tier", "year"])["excess"].mean().unstack("year") * 100).round(2).to_csv(
        os.path.join(out_dir, "signal_by_year.csv"))
    pd.DataFrame(perf_rows).round(4).to_csv(os.path.join(out_dir, "portfolio_performance.csv"), index=False)
    pd.DataFrame(yearly_rows).round(4).to_csv(os.path.join(out_dir, "portfolio_by_year.csv"))
    print(f"wrote {out_dir}")


def main(argv=None) -> None:
    run(parse_args(argv))


if __name__ == "__main__":
    main()

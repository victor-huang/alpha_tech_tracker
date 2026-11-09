"""Narrow the biweekly momentum screen to a short, tradable list and test whether the cut keeps the edge.

Reads the per-year checkpoint panels written by uptrend_formation.py plus the cached daily bars, then for
each selection variant (eligibility filter + ranking score + optional persistence / liquidity / streak rules and
price or industry-group factors from price_factors.py / industry_groups.py):

  * signal test   - mean 60-day forward log return of the picks minus same checkpoint/tier/volatility-quintile
                    peers, split by the QQQ 200-day regime
  * portfolio     - equal-weight top-N per tier, rebalanced every checkpoint (10 trading days), optional holding
                    buffer and regime gate (cash when QQQ < MA200), costs on turnover; compared with the
                    equal-weight tier universe and SPY / QQQ / IWM

Usage:
    PYTHONPATH=. python -m alpha_tech_tracker.research.selection_filters --years 2020 2021 2022 2023 2024 2025 2026
"""
import argparse
import os
import re
from datetime import date
from typing import Callable, Dict, List, NamedTuple, Optional, Tuple

import numpy as np
import pandas as pd

from alpha_tech_tracker.research.industry_groups import IndustryCache, add_group_strength
from alpha_tech_tracker.research.price_factors import attach_factors, factor_frames
from alpha_tech_tracker.research.sec_fundamentals import FundamentalsCache, add_fundamental_factors
from alpha_tech_tracker.research.top_performers import DEFAULT_CACHE_DIR, AlpacaData, DailyBarCache
from alpha_tech_tracker.research.uptrend_formation import DEFAULT_OUT_DIR as PANEL_DIR
from alpha_tech_tracker.research.uptrend_formation import REGIME_INDEX, market_regime

BENCHMARKS = ["SPY", "QQQ", "IWM"]
TIERS = ("Large", "Mid", "Small")
LIQUID_DOLLAR_VOLUME = 20e6
PERSIST_RANK_MULTIPLE = 2
PREFER_POOL_MULTIPLE = 2
SMALL_STREAK_CAP = 8
CHECKPOINTS_PER_YEAR = 25.2
FUND_SPONSORS = (r"BlackRock|Gabelli|GAMCO|Invesco|Calamos|Royce|abrdn|Nuveen|XAI|Eaton Vance|Cohen & Steers|Adams|"
                 r"Tekla|Liberty All|PIMCO|Western Asset|Virtus|DoubleLine|Guggenheim|Kayne|Tortoise|ClearBridge|"
                 r"Allspring|John Hancock")
FUND_NAME = re.compile(rf"^(?:The )?(?:{FUND_SPONSORS})\b.*\b(?:Trust|TR|Investors|Fund|Total Return|Income)\b"
                       r"|\bFund\b|Central Securities|Tri-Continental", re.I)
# Tiered from another issuer's share history after a ticker change (a ~$100B bank labelled Small).
EXCLUDED_SYMBOLS = {"BNY"}


class Variant(NamedTuple):
    eligible: Callable[[pd.DataFrame], pd.Series]
    score: Callable[[pd.DataFrame], pd.Series]
    persist: bool = False
    liquid: bool = False
    max_streak: Optional[int] = None
    hold_on_list: bool = False
    exclude: Tuple[str, ...] = ()
    require: Tuple[str, ...] = ()
    prefer: Tuple[str, ...] = ()
    take_all: bool = False
    also_eligible: Tuple[str, ...] = ()
    boost: Tuple[str, ...] = ()
    keep_while: Tuple[str, ...] = ()
    boost_slots: int = 0
    boost_score: Optional[str] = None
    boost_groups: Tuple[Tuple[str, str, int], ...] = ()


def _all(p: pd.DataFrame) -> pd.Series:
    return pd.Series(True, index=p.index)


def _trend_ok(p: pd.DataFrame) -> pd.Series:
    return (p["close"] > p["ma50"]) & (p["ma50"] > p["ma200"]) & p["ma200_rising"].astype(bool)


def _risk_adj_120(p: pd.DataFrame) -> pd.Series:
    return p["ret_120d"] / p["vol_60d"]


def _composite(p: pd.DataFrame) -> pd.Series:
    """Risk-adjusted momentum, closeness to the 52-week high and trend smoothness (no single-day jump)."""
    by = p.groupby(["checkpoint", "tier"])
    parts = [
        by["risk_adj_120"].rank(pct=True),
        by["off_52w_high"].rank(pct=True),
        by["up_day_share_20d"].rank(pct=True),
        by["max_1d_gain_20d"].rank(pct=True, ascending=False),
    ]
    return 0.4 * parts[0] + 0.2 * parts[1] + 0.2 * parts[2] + 0.2 * parts[3]


VARIANTS: Dict[str, Variant] = {
    "early_momentum_all": Variant(lambda p: p["early_momentum"].astype(bool), lambda p: p["ret_60d"], take_all=True),
    "mom120": Variant(_all, lambda p: p["ret_120d"]),
    "riskadj120": Variant(_all, lambda p: p["risk_adj_120"]),
    "trend+riskadj120": Variant(_trend_ok, lambda p: p["risk_adj_120"]),
    "trend+riskadj120+persist": Variant(_trend_ok, lambda p: p["risk_adj_120"], persist=True),
    "trend+riskadj120+persist+liquid": Variant(_trend_ok, lambda p: p["risk_adj_120"], persist=True, liquid=True),
    "trend+composite": Variant(_trend_ok, lambda p: p["composite"]),
    "trend+lowvol_control": Variant(_trend_ok, lambda p: -p["vol_60d"]),
    "trend+composite+persist+liquid": Variant(_trend_ok, lambda p: p["composite"], persist=True, liquid=True),
    "trend+riskadj120+streak_first": Variant(_trend_ok, lambda p: p["risk_adj_120"], prefer=("streak",)),
    "trend+riskadj120+hold_on_list": Variant(_trend_ok, lambda p: p["risk_adj_120"], hold_on_list=True),
    "trend+riskadj120+streak_cap": Variant(_trend_ok, lambda p: p["risk_adj_120"], max_streak=SMALL_STREAK_CAP),
    "trend+composite+streak_cap": Variant(_trend_ok, lambda p: p["composite"], max_streak=SMALL_STREAK_CAP),
    "mom120+streak_cap": Variant(_all, lambda p: p["ret_120d"], max_streak=SMALL_STREAK_CAP),
}
FADED_OR_DROPPED = ("jump_faded_60d", "drop_60d")
WEAK_GROUP = ("group_bottom20_120d",)
for _base, _score in (("trend+riskadj120", lambda p: p["risk_adj_120"]), ("trend+composite", lambda p: p["composite"])):
    VARIANTS.update({
        f"{_base}+clean": Variant(_trend_ok, _score, exclude=FADED_OR_DROPPED),
        f"{_base}+no_weak_group": Variant(_trend_ok, _score, exclude=WEAK_GROUP),
        f"{_base}+top_group": Variant(_trend_ok, _score, require=("group_top20_120d",)),
        f"{_base}+prefer_leader": Variant(_trend_ok, _score, prefer=("leader_in_top_group",)),
        f"{_base}+prefer_turnaround": Variant(_trend_ok, _score, prefer=("turnaround",)),
        f"{_base}+combo": Variant(_trend_ok, _score, exclude=FADED_OR_DROPPED + WEAK_GROUP,
                                  prefer=("leader_in_top_group", "turnaround")),
    })
VARIANTS.update({
    "trend+riskadj120+clean+prefer_growth": Variant(_trend_ok, lambda p: p["risk_adj_120"], exclude=FADED_OR_DROPPED,
                                                    prefer=("sales_growth_25", "growth_accel_combo")),
    "trend+riskadj120+clean+require_growth": Variant(_trend_ok, lambda p: p["risk_adj_120"],
                                                     exclude=FADED_OR_DROPPED, require=("sales_growth_25",)),
    "trend+riskadj120+clean+prefer_margin": Variant(_trend_ok, lambda p: p["risk_adj_120"], exclude=FADED_OR_DROPPED,
                                                    prefer=("margin_expansion", "earnings_growth_25")),
    "trend+composite+prefer_turnaround+no_decel": Variant(_trend_ok, lambda p: p["composite"],
                                                          exclude=("sales_decel",), prefer=("turnaround",)),
    "trend+composite+prefer_turnaround+accel": Variant(_trend_ok, lambda p: p["composite"],
                                                       prefer=("turnaround", "sales_accel_2q")),
    "trend+composite+prefer_combo": Variant(_trend_ok, lambda p: p["composite"], prefer=("growth_accel_combo",)),
})
_QUALITY_BASES = {"trend+riskadj120+clean": (lambda p: p["risk_adj_120"], FADED_OR_DROPPED, ()),
                  "trend+composite": (lambda p: p["composite"], (), ()),
                  "trend+composite+prefer_turnaround": (lambda p: p["composite"], (), ("turnaround",))}
for _base, (_score, _exclude, _prefer) in _QUALITY_BASES.items():
    VARIANTS.update({
        f"{_base}+no_dilution": Variant(_trend_ok, _score, exclude=_exclude + ("dilution_10",), prefer=_prefer),
        f"{_base}+no_low_runway": Variant(_trend_ok, _score, exclude=_exclude + ("low_runway",), prefer=_prefer),
        f"{_base}+no_cash_burn": Variant(_trend_ok, _score, exclude=_exclude + ("cash_burn",), prefer=_prefer),
        f"{_base}+no_dilution_or_low_runway": Variant(_trend_ok, _score,
                                                      exclude=_exclude + ("dilution_10", "low_runway"),
                                                      prefer=_prefer),
        f"{_base}+prefer_gross_profit": Variant(_trend_ok, _score, exclude=_exclude,
                                                prefer=_prefer + ("gp_top30",)),
        f"{_base}+no_dilution+prefer_gross_profit": Variant(_trend_ok, _score, exclude=_exclude + ("dilution_10",),
                                                            prefer=_prefer + ("gp_top30",)),
    })
VARIANTS["trend+mom120+clean"] = Variant(_trend_ok, lambda p: p["ret_120d"], exclude=FADED_OR_DROPPED)
BREAKOUT_SIGNALS = {"gap": ("gap_10d",), "high": ("high_breakout_10d",), "breakout": ("breakout_10d",),
                    "breakout_hold": ("breakout_hold_60d",)}
for _base, _score in (("trend+riskadj120+clean", lambda p: p["risk_adj_120"]),
                      ("trend+mom120+clean", lambda p: p["ret_120d"])):
    for _name, _flags in BREAKOUT_SIGNALS.items():
        VARIANTS[f"{_base}+{_name}"] = Variant(_trend_ok, _score, exclude=FADED_OR_DROPPED, also_eligible=_flags,
                                               boost=_flags)
MA_RISING = ("ma_rising_8_20_50",)
MA_RISING_200 = ("ma_rising_8_20_50_200",)
for _base in ("trend+riskadj120+clean", "trend+mom120+clean", "trend+composite+no_dilution+prefer_gross_profit",
              "trend+riskadj120+clean+breakout"):
    _v = VARIANTS.get(_base)
    if _v is None:
        continue
    VARIANTS[f"{_base}+hold_ma_rising"] = _v._replace(keep_while=MA_RISING)
    VARIANTS[f"{_base}+hold_ma_rising_200"] = _v._replace(keep_while=MA_RISING_200)
    VARIANTS[f"{_base}+require_ma_rising"] = _v._replace(require=_v.require + MA_RISING)
    VARIANTS[f"{_base}+require_ma_rising_200"] = _v._replace(require=_v.require + MA_RISING_200)
    VARIANTS[f"{_base}+prefer_ma_rising"] = _v._replace(prefer=_v.prefer + MA_RISING)
    VARIANTS[f"{_base}+prefer_ma_rising_200"] = _v._replace(prefer=_v.prefer + MA_RISING_200)
BREAKOUT_SLOTS = 5
for _base in ("trend+riskadj120+clean", "trend+mom120+clean", "trend+composite+no_dilution+prefer_gross_profit"):
    _v = VARIANTS[_base]
    VARIANTS[f"{_base}+breakout5"] = _v._replace(
        also_eligible=("breakout_10d",), boost=("breakout_10d",), boost_slots=BREAKOUT_SLOTS,
        boost_score="breakout_strength_10d")
    VARIANTS[f"{_base}+breakout5_hold"] = _v._replace(
        also_eligible=("breakout_hold_60d",), boost=("breakout_hold_60d",), boost_slots=BREAKOUT_SLOTS,
        boost_score="breakout_strength_60d")
SPLIT_FRESH = (("gap_10d", "gap_strength_10d", 3), ("high_breakout_10d", "high_base_10d", 2))
SPLIT_HOLD = (("gap_hold_60d", "gap_strength_60d", 3), ("high_hold_60d", "high_base_60d", 2))
for _base in ("trend+riskadj120+clean", "trend+mom120+clean"):
    _v = VARIANTS[_base]
    VARIANTS[f"{_base}+gap3_high2"] = _v._replace(also_eligible=("gap_10d", "high_breakout_10d"),
                                                  boost_groups=SPLIT_FRESH)
    VARIANTS[f"{_base}+gap3_high2_hold"] = _v._replace(also_eligible=("gap_hold_60d", "high_hold_60d"),
                                                       boost_groups=SPLIT_HOLD)
BASE = ("base_building",)
for _base in ("trend+riskadj120+clean", "trend+mom120+clean", "trend+composite+no_dilution+prefer_gross_profit"):
    _v = VARIANTS[_base]
    VARIANTS[f"{_base}+base_ok"] = _v._replace(also_eligible=BASE)
    VARIANTS[f"{_base}+base_ok+prefer_ma_rising"] = _v._replace(also_eligible=BASE, prefer=_v.prefer + MA_RISING)
    VARIANTS[f"{_base}+base_ok+breakout"] = _v._replace(also_eligible=BASE + ("breakout_10d",),
                                                         boost=("breakout_10d",))
VARIANTS["trend+composite+no_dilution+prefer_gross_profit+breakout"] = Variant(
    _trend_ok, lambda p: p["composite"], exclude=("dilution_10",), prefer=("gp_top30",),
    also_eligible=("breakout_10d",), boost=("breakout_10d",))
VARIANTS["early_momentum_all+top_group+clean"] = Variant(
    lambda p: p["early_momentum"].astype(bool), lambda p: p["ret_60d"], take_all=True,
    exclude=FADED_OR_DROPPED, require=("group_top20_120d",))


def load_panels(panel_dir: str, years: List[int]) -> pd.DataFrame:
    panels = [pd.read_pickle(os.path.join(panel_dir, str(y), "panel.pkl")) for y in years]
    return pd.concat(panels, ignore_index=True).sort_values(["checkpoint", "tier", "symbol"], ignore_index=True)


def drop_funds(panel: pd.DataFrame, names: pd.Series) -> pd.DataFrame:
    """Closed-end funds and the like slip past the ETF filter and dominate any low-volatility ranking."""
    is_fund = panel["symbol"].map(names).fillna("").str.contains(FUND_NAME)
    return panel[~is_fund & ~panel["symbol"].isin(EXCLUDED_SYMBOLS)].reset_index(drop=True)


def list_streak(panel: pd.DataFrame, flag: str) -> pd.Series:
    """Consecutive checkpoints (including this one) the symbol has had `flag` set; 0 when not set."""
    order = {cp: i for i, cp in enumerate(sorted(panel["checkpoint"].unique()))}
    flagged = panel[panel[flag].astype(bool)]
    f = pd.DataFrame({"symbol": flagged["symbol"], "i": flagged["checkpoint"].map(order)}).sort_values(["symbol", "i"])
    run_id = (f.groupby("symbol")["i"].diff() != 1).cumsum()
    f["streak"] = f.groupby(run_id).cumcount() + 1
    return f["streak"].reindex(panel.index, fill_value=0)


def add_selection_features(panel: pd.DataFrame, dollar_volume_20d: pd.DataFrame) -> pd.DataFrame:
    """risk_adj_120, composite score, early-momentum streak, 20-day median dollar volume and 60-day excess vs
    volatility peers."""
    p = panel.copy()
    p["streak"] = list_streak(p, "early_momentum")
    p["risk_adj_120"] = _risk_adj_120(p)
    p["composite"] = _composite(p)
    dv = dollar_volume_20d.stack().rename("dollar_volume_20d")
    dv.index.names = ["checkpoint", "symbol"]
    p = p.merge(dv.reset_index(), on=["checkpoint", "symbol"], how="left")
    fwd_log = np.log1p(p["fwd_ret"].clip(lower=-0.99))
    peers = fwd_log.groupby([p["checkpoint"], p["tier"], p["vol_bucket"]]).transform("mean")
    p["excess"] = (fwd_log - peers).where(p["vol_bucket"].notna())
    return p


def rank_variant(panel: pd.DataFrame, variant: Variant, n: int) -> pd.DataFrame:
    """Eligible rows with their score rank within (checkpoint, tier), after the variant's liquidity, streak,
    exclude (factor == 1 drops the row) and require (factor must be 1) rules; `prefer` moves names with those
    factors to the front of the top PREFER_POOL_MULTIPLE * n. `also_eligible` factors (== 1) admit a row that
    fails the eligibility filter, and `boost` factors move rows ahead of every unboosted row (by score among
    themselves; with `boost_slots`, only that many, strongest `boost_score` first)."""
    eligible = variant.eligible(panel).fillna(False).astype(bool)
    for factor in variant.also_eligible:
        eligible |= panel[factor] == 1
    for factor in variant.exclude:
        eligible &= panel[factor] != 1
    for factor in variant.require:
        eligible &= panel[factor] == 1
    if variant.liquid:
        eligible &= panel["dollar_volume_20d"] >= LIQUID_DOLLAR_VOLUME
    if variant.max_streak is not None:
        eligible &= panel["streak"] <= variant.max_streak
    p = panel.loc[eligible, ["checkpoint", "tier", "symbol", "streak"]].copy()
    p["score"] = variant.score(panel)[eligible]
    p = p[p["score"].notna()]
    p["rank"] = p.groupby(["checkpoint", "tier"])["score"].rank(ascending=False, method="first")
    if variant.boost:
        p["order"] = p["rank"]
        boosted = (panel.loc[p.index, list(variant.boost)] == 1).any(axis=1)
        if variant.boost_slots:
            strength = panel.loc[p.index, variant.boost_score].where(boosted)
            p["order"] = strength.groupby([p["checkpoint"], p["tier"]]).rank(ascending=False, method="first")
            boosted = p["order"] <= variant.boost_slots
            p["order"] = p["order"].where(boosted, p["rank"])
        p["boosted"] = boosted
        p = p.sort_values(["checkpoint", "tier", "boosted", "order"], ascending=[True, True, False, True])
        p["rank"] = p.groupby(["checkpoint", "tier"]).cumcount() + 1.0
        p = p.drop(columns=["boosted", "order"])
    if variant.boost_groups:
        p = _apply_boost_groups(p, panel, variant.boost_groups)
    if variant.persist:
        checkpoints = sorted(panel["checkpoint"].unique())
        next_checkpoint = dict(zip(checkpoints[:-1], checkpoints[1:]))
        ranked_before = p.loc[p["rank"] <= PERSIST_RANK_MULTIPLE * n, ["checkpoint", "symbol"]]
        ranked_before["checkpoint"] = ranked_before["checkpoint"].map(next_checkpoint)
        p = p.reset_index().merge(ranked_before.dropna(), on=["checkpoint", "symbol"]).set_index("index")
        p.index.name = None
        p["rank"] = p.groupby(["checkpoint", "tier"])["score"].rank(ascending=False, method="first")
    if variant.prefer:
        p["in_pool"] = p["rank"] <= PREFER_POOL_MULTIPLE * n
        p["preference"] = panel.loc[p.index, list(variant.prefer)].fillna(0).sum(axis=1)
        p = p.sort_values(["checkpoint", "tier", "in_pool", "preference", "rank"],
                          ascending=[True, True, False, False, True])
        p["rank"] = p.groupby(["checkpoint", "tier"]).cumcount() + 1.0
        p = p.drop(columns=["in_pool", "preference"])
    p["keep"] = (p["streak"] > 0) if variant.hold_on_list else False
    for factor in variant.keep_while:
        p["keep"] = p["keep"] | (panel.loc[p.index, factor] == 1)
    return p


def _apply_boost_groups(p: pd.DataFrame, panel: pd.DataFrame,
                        groups: Tuple[Tuple[str, str, int], ...]) -> pd.DataFrame:
    """Fill each (flag, score, slots) group in order with its strongest flagged rows, ahead of everything else."""
    p = p.copy()
    p["slot"] = np.nan
    offset = 0
    for flag, score, slots in groups:
        open_rows = p["slot"].isna() & (panel.loc[p.index, flag] == 1)
        strength = panel.loc[p.index, score].where(open_rows)
        order = strength.groupby([p["checkpoint"], p["tier"]]).rank(ascending=False, method="first")
        chosen = order <= slots
        p.loc[chosen, "slot"] = offset + order[chosen]
        offset += slots
    p["order"] = p["slot"].fillna(offset + p["rank"])
    p = p.sort_values(["checkpoint", "tier", "order"])
    p["rank"] = p.groupby(["checkpoint", "tier"]).cumcount() + 1.0
    return p.drop(columns=["slot", "order"])


def pick_top(ranked: pd.DataFrame, n: int, take_all: bool = False) -> pd.DataFrame:
    return ranked if take_all else ranked[ranked["rank"] <= n]


def signal_test(panel: pd.DataFrame, picks: pd.DataFrame, regime: pd.Series) -> pd.DataFrame:
    """Per (checkpoint, tier): mean excess vs volatility peers of the picks, and the pick count."""
    rows = picks.merge(panel[["checkpoint", "symbol", "excess"]], on=["checkpoint", "symbol"])
    rows = rows[rows["excess"].notna()]
    out = rows.groupby(["checkpoint", "tier"])["excess"].agg(["mean", "size"]).reset_index()
    out.columns = ["checkpoint", "tier", "excess", "picks"]
    out["index_above_ma200"] = out["checkpoint"].map(regime).astype(bool)
    return out


def period_returns(close: pd.DataFrame, checkpoints: List[pd.Timestamp]) -> pd.DataFrame:
    """Return from each checkpoint close to the next one (the last runs to the latest close)."""
    c = close.ffill()
    ends = checkpoints[1:] + [c.index[-1]]
    at_start = c.reindex(checkpoints)
    at_end = c.reindex(ends)
    at_end.index = checkpoints
    return at_end / at_start - 1


def run_portfolio(ranked: pd.DataFrame, returns: pd.DataFrame, regime: pd.Series, n: int, buffer: int,
                  gate: bool, cost: float, take_all: bool = False) -> pd.DataFrame:
    """Equal-weight book per checkpoint: keep holdings still ranked <= buffer (or flagged `keep`), fill up to n
    from the top.

    Returns one row per checkpoint: net return over the following period, names held, one-way turnover and the
    held symbols.
    """
    by_cp = {cp: g.sort_values("rank") for cp, g in ranked.groupby("checkpoint")}
    held: List[str] = []
    weights_prev = pd.Series(dtype=float)
    rows = []
    for cp in returns.index:
        g = by_cp.get(cp)
        if (gate and not regime.get(cp, False)) or g is None:
            held = []
        elif take_all:
            held = g["symbol"].tolist()
        else:
            rank_of = dict(zip(g["symbol"], g["rank"]))
            keep_of = dict(zip(g["symbol"], g["keep"])) if "keep" in g else {}
            held = [s for s in held if rank_of.get(s, np.inf) <= buffer or keep_of.get(s, False)]
            held = sorted(held, key=rank_of.get)[:n]
            for s in g["symbol"]:
                if len(held) >= n:
                    break
                if s not in held:
                    held.append(s)
        weights = pd.Series(1.0 / len(held), index=held) if held else pd.Series(dtype=float)
        turnover = weights.subtract(weights_prev, fill_value=0).abs().sum()
        gross = returns.loc[cp, held].fillna(0).mean() if held else 0.0
        rows.append({"checkpoint": cp, "ret": gross - cost * turnover, "names": len(held), "turnover": turnover / 2,
                     "held": list(held)})
        if held:
            drifted = weights * (1 + returns.loc[cp, held].fillna(0))
            weights_prev = drifted / drifted.sum()
        else:
            weights_prev = pd.Series(dtype=float)
    return pd.DataFrame(rows).set_index("checkpoint")


def performance(ret: pd.Series) -> Dict[str, float]:
    equity = (1 + ret).cumprod()
    years = len(ret) / CHECKPOINTS_PER_YEAR
    vol = ret.std() * np.sqrt(CHECKPOINTS_PER_YEAR)
    return {
        "cagr": equity.iloc[-1] ** (1 / years) - 1,
        "vol": vol,
        "sharpe": ret.mean() * CHECKPOINTS_PER_YEAR / vol if vol > 0 else np.nan,
        "max_dd": (equity / equity.cummax() - 1).min(),
    }


def yearly(ret: pd.Series) -> pd.Series:
    return (1 + ret).groupby(ret.index.year).prod() - 1


class Inputs(NamedTuple):
    panel: pd.DataFrame
    close: pd.DataFrame
    dollar_volume: pd.DataFrame
    regime: pd.Series
    checkpoints: List[pd.Timestamp]
    symbols: List[str]


def prepare_inputs(args: argparse.Namespace) -> Inputs:
    """Checkpoint panel with selection, price, industry-group and SEC factors, plus the daily bars behind it."""
    years = args.years
    alpaca = AlpacaData()
    panel = drop_funds(load_panels(args.panel_dir, years), alpaca.listed_stocks()["name"])
    checkpoints = sorted(panel["checkpoint"].unique())
    symbols = sorted(panel["symbol"].unique())
    bar_cache = DailyBarCache(args.cache_dir, alpaca.daily_bars)
    close, dollar_volume = bar_cache.load(symbols + BENCHMARKS, date(min(years) - 2, 10, 1), args.today, args.today)
    regime = market_regime(close[REGIME_INDEX]).reindex(checkpoints).fillna(False)
    dv20 = dollar_volume[symbols].rolling(20, min_periods=15).median().reindex(checkpoints)
    panel = add_selection_features(panel, dv20)
    panel = attach_factors(panel, factor_frames(close[symbols], dollar_volume[symbols]))
    panel = add_group_strength(panel, IndustryCache(os.path.join(args.cache_dir, "industries.csv")).load(args.today))
    panel = add_fundamental_factors(panel, FundamentalsCache(os.path.join(args.cache_dir, "sec")).load(symbols,
                                                                                                     args.today))
    return Inputs(panel, close, dollar_volume, regime, checkpoints, symbols)


def run(args: argparse.Namespace) -> None:
    panel, close, _, regime, checkpoints, _ = prepare_inputs(args)
    returns = period_returns(close, checkpoints)

    out_dir = os.path.join(args.out_dir, "selection_filters")
    os.makedirs(out_dir, exist_ok=True)
    signal_rows, perf_rows, yearly_rows = [], [], []
    for tier in TIERS:
        universe = panel[panel["tier"] == tier].pivot(index="checkpoint", columns="symbol", values="close").notna()
        tier_ret = returns.where(universe.reindex(columns=returns.columns, fill_value=False)).mean(axis=1)
        for name, r in (("universe_equal_weight", tier_ret), ("universe_equal_weight_gated", tier_ret.where(regime, 0.0))):
            perf_rows.append({"tier": tier, "variant": name, "gate": "gated" in name, **performance(r)})
            yearly_rows.append(yearly(r).rename((tier, name)))
    for b in BENCHMARKS:
        r = returns[b]
        perf_rows.append({"tier": "Benchmark", "variant": b, "gate": False, **performance(r)})
        yearly_rows.append(yearly(r).rename(("Benchmark", b)))

    for name, variant in VARIANTS.items():
        take_all = variant.take_all
        ranked = rank_variant(panel, variant, args.top)
        picks = pick_top(ranked, args.top, take_all)
        sig = signal_test(panel, picks, regime).assign(variant=name)
        signal_rows.append(sig)
        for tier in TIERS:
            tier_ranked = ranked[ranked["tier"] == tier]
            for gate in (False, True):
                for buffer in ((args.top,) if take_all else (args.top, args.buffer)):
                    book = run_portfolio(tier_ranked, returns, regime, args.top, buffer, gate, args.cost_bps / 1e4,
                                         take_all)
                    label = f"{name}|gate={'on' if gate else 'off'}|buffer={buffer}"
                    perf_rows.append({"tier": tier, "variant": name, "gate": gate, "buffer": buffer,
                                      "avg_names": book["names"][book["names"] > 0].mean(),
                                      "turnover_per_rebalance": book["turnover"].mean(),
                                      **performance(book["ret"])})
                    yearly_rows.append(yearly(book["ret"]).rename((tier, label)))

    signal = pd.concat(signal_rows, ignore_index=True)
    signal.to_csv(os.path.join(out_dir, "signal_by_checkpoint.csv"), index=False)
    by_regime = signal.groupby(["variant", "tier", "index_above_ma200"]).agg(
        excess_pct=("excess", lambda s: s.mean() * 100), share_positive=("excess", lambda s: (s > 0).mean()),
        picks=("picks", "mean"), checkpoints=("excess", "size"))
    by_regime.round(3).to_csv(os.path.join(out_dir, "signal_by_regime.csv"))
    signal["year"] = pd.to_datetime(signal["checkpoint"]).dt.year
    (signal.groupby(["variant", "tier", "year"])["excess"].mean().unstack("year") * 100).round(2).to_csv(
        os.path.join(out_dir, "signal_by_year.csv"))
    pd.DataFrame(perf_rows).round(4).to_csv(os.path.join(out_dir, "portfolio_performance.csv"), index=False)
    pd.DataFrame(yearly_rows).round(4).to_csv(os.path.join(out_dir, "portfolio_by_year.csv"))
    print(f"wrote {out_dir}")


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--years", type=int, nargs="+", required=True)
    p.add_argument("--top", type=int, default=15, help="names held per tier")
    p.add_argument("--buffer", type=int, default=40, help="keep a holding while its rank stays within this")
    p.add_argument("--cost-bps", type=float, default=10.0, help="cost per unit of traded weight, each side")
    p.add_argument("--panel-dir", default=PANEL_DIR)
    p.add_argument("--cache-dir", default=DEFAULT_CACHE_DIR)
    p.add_argument("--out-dir", default=PANEL_DIR)
    p.add_argument("--today", type=date.fromisoformat, default=date.today())
    return p.parse_args(argv)


def main(argv=None) -> None:
    run(parse_args(argv))


if __name__ == "__main__":
    main()

"""Narrow the biweekly momentum screen to a short, tradable list and test whether the cut keeps the edge.

Reads the per-year checkpoint panels written by uptrend_formation.py plus the cached daily bars, then for
each selection variant (eligibility filter + ranking score + optional persistence / liquidity rule):

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
from typing import Callable, Dict, List, NamedTuple, Optional

import numpy as np
import pandas as pd

from alpha_tech_tracker.research.top_performers import DEFAULT_CACHE_DIR, AlpacaData, DailyBarCache
from alpha_tech_tracker.research.uptrend_formation import DEFAULT_OUT_DIR as PANEL_DIR
from alpha_tech_tracker.research.uptrend_formation import REGIME_INDEX, market_regime

BENCHMARKS = ["SPY", "QQQ", "IWM"]
TIERS = ("Large", "Mid", "Small")
LIQUID_DOLLAR_VOLUME = 20e6
PERSIST_RANK_MULTIPLE = 2
STREAK_POOL_MULTIPLE = 2
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
    streak_first: bool = False
    hold_on_list: bool = False


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
    "early_momentum_all": Variant(lambda p: p["early_momentum"].astype(bool), lambda p: p["ret_60d"]),
    "mom120": Variant(_all, lambda p: p["ret_120d"]),
    "riskadj120": Variant(_all, lambda p: p["risk_adj_120"]),
    "trend+riskadj120": Variant(_trend_ok, lambda p: p["risk_adj_120"]),
    "trend+riskadj120+persist": Variant(_trend_ok, lambda p: p["risk_adj_120"], persist=True),
    "trend+riskadj120+persist+liquid": Variant(_trend_ok, lambda p: p["risk_adj_120"], persist=True, liquid=True),
    "trend+composite": Variant(_trend_ok, lambda p: p["composite"]),
    "trend+lowvol_control": Variant(_trend_ok, lambda p: -p["vol_60d"]),
    "trend+composite+persist+liquid": Variant(_trend_ok, lambda p: p["composite"], persist=True, liquid=True),
    "trend+riskadj120+streak_first": Variant(_trend_ok, lambda p: p["risk_adj_120"], streak_first=True),
    "trend+riskadj120+hold_on_list": Variant(_trend_ok, lambda p: p["risk_adj_120"], hold_on_list=True),
    "trend+riskadj120+streak_cap": Variant(_trend_ok, lambda p: p["risk_adj_120"], max_streak=SMALL_STREAK_CAP),
    "trend+composite+streak_cap": Variant(_trend_ok, lambda p: p["composite"], max_streak=SMALL_STREAK_CAP),
    "mom120+streak_cap": Variant(_all, lambda p: p["ret_120d"], max_streak=SMALL_STREAK_CAP),
}


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
    """Eligible rows with their score rank within (checkpoint, tier); persistence and liquidity applied."""
    eligible = variant.eligible(panel).fillna(False).astype(bool)
    if variant.liquid:
        eligible &= panel["dollar_volume_20d"] >= LIQUID_DOLLAR_VOLUME
    if variant.max_streak is not None:
        eligible &= panel["streak"] <= variant.max_streak
    p = panel.loc[eligible, ["checkpoint", "tier", "symbol", "streak"]].copy()
    p["score"] = variant.score(panel)[eligible]
    p = p[p["score"].notna()]
    p["rank"] = p.groupby(["checkpoint", "tier"])["score"].rank(ascending=False, method="first")
    if variant.persist:
        checkpoints = sorted(panel["checkpoint"].unique())
        next_checkpoint = dict(zip(checkpoints[:-1], checkpoints[1:]))
        ranked_before = p.loc[p["rank"] <= PERSIST_RANK_MULTIPLE * n, ["checkpoint", "symbol"]]
        ranked_before["checkpoint"] = ranked_before["checkpoint"].map(next_checkpoint)
        p = p.merge(ranked_before.dropna(), on=["checkpoint", "symbol"])
        p["rank"] = p.groupby(["checkpoint", "tier"])["score"].rank(ascending=False, method="first")
    if variant.streak_first:
        p["in_pool"] = p["rank"] <= STREAK_POOL_MULTIPLE * n
        p = p.sort_values(["checkpoint", "tier", "in_pool", "streak", "rank"], ascending=[True, True, False, False, True])
        p["rank"] = p.groupby(["checkpoint", "tier"]).cumcount() + 1.0
        p = p.drop(columns="in_pool")
    p["keep"] = (p["streak"] > 0) if variant.hold_on_list else False
    return p


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

    Returns one row per checkpoint: net return over the following period, names held and one-way turnover.
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
        rows.append({"checkpoint": cp, "ret": gross - cost * turnover, "names": len(held), "turnover": turnover / 2})
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


def run(args: argparse.Namespace) -> None:
    years = args.years
    alpaca = AlpacaData()
    panel = drop_funds(load_panels(args.panel_dir, years), alpaca.listed_stocks()["name"])
    checkpoints = sorted(panel["checkpoint"].unique())
    symbols = sorted(panel["symbol"].unique())
    bar_cache = DailyBarCache(args.cache_dir, alpaca.daily_bars)
    close, dollar_volume = bar_cache.load(symbols + BENCHMARKS, date(min(years) - 1, 11, 1), args.today, args.today)
    regime = market_regime(close[REGIME_INDEX]).reindex(checkpoints).fillna(False)
    dv20 = dollar_volume[symbols].rolling(20, min_periods=15).median().reindex(checkpoints)
    panel = add_selection_features(panel, dv20)
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
        take_all = name == "early_momentum_all"
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

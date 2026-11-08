"""Experiment: can a biweekly scan spot a year's top performers while their uptrend is forming?

Usage (repo root, Alpaca keys set; reuses the top_performers bar and share caches):

    PYTHONPATH=. python -m alpha_tech_tracker.research.uptrend_formation --year 2026
    PYTHONPATH=. python -m alpha_tech_tracker.research.uptrend_formation --year 2020 2021 2022  # + cross-year summary

Three parts, all evaluated at checkpoints every `--step` trading days using only data up to that close:
  1. winner timeline   - when each of the year's top-10 (per tier) first passed each screen, and how much
                         of its gain was still ahead at that point
  2. feature profile   - the winners' within-tier percentile for each feature, checkpoint by checkpoint
  3. forward test      - for every stock at every checkpoint: does passing a screen (or ranking high on a
                         feature) raise the odds of a top-5% return over the next `--horizon` trading days?
  4. excess vs peers   - flagged stocks' forward return minus same-volatility peers', split by whether QQQ
                         is above its 200-day average (with several years, summarized across years)
"""
import argparse
import os
from datetime import date, timedelta
from typing import Dict, List

import numpy as np
import pandas as pd

from alpha_tech_tracker.research.top_performers import (
    DEFAULT_CACHE_DIR,
    AlpacaData,
    DailyBarCache,
    SharesCache,
    market_cap_at,
    tier_for,
)

RESEARCH_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_WINNERS_CSV = os.path.join(RESEARCH_DIR, "docs", "top10_by_year_2020_2026.csv")
DEFAULT_OUT_DIR = os.path.join(RESEARCH_DIR, "top_performers_output", "uptrend_formation")
BENCHMARKS = ["SPY", "QQQ"]
REGIME_INDEX = "QQQ"
LOOKBACK_MONTHS = 14
MIN_START_PRICE = 2.0
MIN_START_DOLLAR_VOLUME = 2e6
FORWARD_WIN_QUANTILE = 0.95

# continuous features ranked within tier at each checkpoint; True = higher is "more trend-like"
RANKED_FEATURES = {
    "ret_20d": True,
    "ret_60d": True,
    "ret_120d": True,
    "ret_250d": True,
    "off_52w_high": True,
    "above_52w_low": True,
    "ma50_slope": True,
    "volume_surge": True,
    "vol_contraction": False,
    "max_1d_gain_20d": True,
    "up_day_share_20d": True,
}


def checkpoint_days(trading_days: pd.DatetimeIndex, year: int, step: int) -> List[pd.Timestamp]:
    in_year = trading_days[trading_days.year == year]
    return list(in_year[::step])


def compute_feature_frames(close: pd.DataFrame, dollar_volume: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    """Wide (day x symbol) feature frames; each value uses only data up to that day."""
    c = close.ffill(limit=5)
    daily = c.pct_change(fill_method=None)
    share_volume = dollar_volume / close
    ma50 = c.rolling(50, min_periods=40).mean()
    ma200 = c.rolling(200, min_periods=160).mean()
    high_250 = c.rolling(250, min_periods=200).max()
    low_250 = c.rolling(250, min_periods=200).min()
    return {
        "close": c,
        "ret_10d": c / c.shift(10) - 1,
        "ret_20d": c / c.shift(20) - 1,
        "ret_60d": c / c.shift(60) - 1,
        "ret_120d": c / c.shift(120) - 1,
        "ret_250d": c / c.shift(250) - 1,
        "ma50": ma50,
        "ma200": ma200,
        "ma50_slope": ma50 / ma50.shift(10) - 1,
        "ma200_rising": ma200 > ma200.shift(20),
        "off_52w_high": c / high_250 - 1,
        "above_52w_low": c / low_250 - 1,
        "new_high_10d": c.rolling(10).max() >= high_250 * 0.999,
        "volume_surge": share_volume.rolling(10, min_periods=8).mean()
        / share_volume.rolling(60, min_periods=45).mean(),
        "vol_contraction": daily.rolling(20, min_periods=15).std() / daily.rolling(120, min_periods=90).std(),
        "max_1d_gain_20d": daily.rolling(20, min_periods=15).max(),
        "vol_60d": daily.rolling(60, min_periods=45).std() * np.sqrt(252),
        "up_day_share_20d": (daily > 0).astype(float).where(daily.notna()).rolling(20, min_periods=15).mean(),
    }


def checkpoint_panel(frames: Dict[str, pd.DataFrame], days: List[pd.Timestamp], universe: pd.Series,
                     horizon: int) -> pd.DataFrame:
    """Long panel: one row per (checkpoint, symbol) in `universe` (symbol -> tier), plus forward returns."""
    close = frames["close"]
    all_days = close.index
    symbols = [s for s in universe.index if s in close.columns]
    rows = []
    for day in days:
        pos = all_days.get_loc(day)
        part = pd.DataFrame({name: f.loc[day, symbols] for name, f in frames.items()})
        part["checkpoint"] = day
        part["tier"] = universe.reindex(symbols).values
        fwd_pos = pos + horizon
        part["fwd_ret"] = (close.iloc[fwd_pos][symbols] / close.loc[day, symbols] - 1) if fwd_pos < len(all_days) \
            else np.nan
        part["ret_to_end"] = close.loc[:days[-1].replace(month=12, day=31), symbols].ffill().iloc[-1] \
            / close.loc[day, symbols] - 1
        rows.append(part.rename_axis("symbol").reset_index())
    panel = pd.concat(rows, ignore_index=True)
    panel = panel[panel["close"].notna()]
    return add_ranks_and_screens(panel)


def add_ranks_and_screens(panel: pd.DataFrame) -> pd.DataFrame:
    panel = panel.copy()
    by_tier = panel.groupby(["checkpoint", "tier"])
    for name, higher_is_better in RANKED_FEATURES.items():
        panel[f"{name}_pct"] = by_tier[name].rank(pct=True, ascending=higher_is_better)
    panel["rs_rank"] = panel.groupby("checkpoint")["ret_120d"].rank(pct=True)
    panel["trend_template"] = (
        (panel["close"] > panel["ma50"])
        & (panel["ma50"] > panel["ma200"])
        & panel["ma200_rising"].astype(bool)
        & (panel["off_52w_high"] >= -0.15)
        & (panel["above_52w_low"] >= 0.30)
        & (panel["rs_rank"] >= 0.80)
    )
    panel["breakout"] = panel["new_high_10d"].astype(bool) & (panel["volume_surge"] >= 1.5)
    panel["early_momentum"] = (
        (panel["close"] > panel["ma50"])
        & (panel["ma50_slope"] > 0)
        & (panel["ret_60d_pct"] >= 0.90)
    )
    has_fwd = panel["fwd_ret"].notna()
    cut = panel[has_fwd].groupby(["checkpoint", "tier"])["fwd_ret"].transform(
        lambda s: s.quantile(FORWARD_WIN_QUANTILE))
    low_cut = panel[has_fwd].groupby(["checkpoint", "tier"])["fwd_ret"].transform(
        lambda s: s.quantile(1 - FORWARD_WIN_QUANTILE))
    panel["fwd_win"] = np.nan
    panel["fwd_lose"] = np.nan
    panel.loc[has_fwd, "fwd_win"] = (panel.loc[has_fwd, "fwd_ret"] >= cut).astype(float)
    panel.loc[has_fwd, "fwd_lose"] = (panel.loc[has_fwd, "fwd_ret"] <= low_cut).astype(float)
    panel["vol_bucket"] = panel.groupby(["checkpoint", "tier"])["vol_60d"].transform(
        lambda s: pd.qcut(s.rank(method="first"), 5, labels=False) if s.notna().sum() >= 5 else np.nan)
    return panel


SCREENS = ("trend_template", "breakout", "early_momentum")


def winner_timeline(panel: pd.DataFrame, winners: pd.DataFrame, daily_close: pd.DataFrame,
                    year_start_close: pd.Series) -> pd.DataFrame:
    """Per winner: when each screen first fired, the YTD gain by then, and the share of the log gain still ahead."""
    out = []
    final = daily_close.ffill().iloc[-1]
    for w in winners.itertuples():
        rows = panel[panel["symbol"] == w.symbol].sort_values("checkpoint")
        base, end = year_start_close.get(w.symbol), final.get(w.symbol)
        if rows.empty or pd.isna(base) or pd.isna(end):
            continue
        total_log = np.log(end / base)
        daily = daily_close[w.symbol][daily_close.index.year == rows["checkpoint"].iloc[0].year].pct_change().dropna()
        rec = {
            "tier": w.tier, "rank": w.rank, "symbol": w.symbol, "ytd_pct": round((end / base - 1) * 100, 1),
            "biggest_day_pct": round(daily.max() * 100, 1) if len(daily) else np.nan,
            "biggest_day_share_of_gain": round(np.log1p(daily.max()) / total_log, 2) if total_log > 0 else np.nan,
        }
        for screen in SCREENS:
            hit = rows[rows[screen]]
            if hit.empty:
                rec[f"{screen}_first"] = None
                rec[f"{screen}_ytd_at_first_pct"] = np.nan
                rec[f"{screen}_gain_ahead_share"] = 0.0
                continue
            first = hit.iloc[0]
            at = first["close"]
            rec[f"{screen}_first"] = first["checkpoint"].date()
            rec[f"{screen}_ytd_at_first_pct"] = round((at / base - 1) * 100, 1)
            rec[f"{screen}_gain_ahead_share"] = round(max(np.log(end / at), 0) / total_log, 2) if total_log > 0 else 0
        out.append(rec)
    return pd.DataFrame(out)


def feature_profile(panel: pd.DataFrame, winner_symbols: List[str]) -> pd.DataFrame:
    """Median within-tier percentile of each feature for the winners, per checkpoint (0.5 = typical stock)."""
    cols = [f"{n}_pct" for n in RANKED_FEATURES]
    w = panel[panel["symbol"].isin(winner_symbols)]
    prof = w.groupby("checkpoint")[cols].median()
    prof.columns = [c[:-4] for c in cols]
    for screen in SCREENS:
        prof[f"{screen}_share"] = w.groupby("checkpoint")[screen].mean()
        prof[f"{screen}_share_all"] = panel.groupby("checkpoint")[screen].mean()
    return prof.round(2)


def forward_test(panel: pd.DataFrame) -> pd.DataFrame:
    """Pooled over checkpoints with a full forward window: hit rate of each rule vs the 5% base rate."""
    p = panel[panel["fwd_win"].notna()]
    rules = {screen: p[screen] for screen in SCREENS}
    for name in RANKED_FEATURES:
        rules[f"top_decile_{name}"] = p[f"{name}_pct"] >= 0.9
    base_rate = p["fwd_win"].mean()
    rows = []
    for name, mask in rules.items():
        flagged = p[mask.astype(bool)]
        for tier, group in [("All", flagged)] + [(t, flagged[flagged["tier"] == t]) for t in ("Large", "Mid", "Small")]:
            tier_all = p if tier == "All" else p[p["tier"] == tier]
            if group.empty:
                continue
            rows.append({
                "rule": name,
                "tier": tier,
                "flagged_per_checkpoint": round(len(group) / p["checkpoint"].nunique(), 1),
                "hit_rate": round(group["fwd_win"].mean(), 3),
                "lift": round(group["fwd_win"].mean() / tier_all["fwd_win"].mean(), 2),
                "loss_rate": round(group["fwd_lose"].mean(), 3),
                "vol_matched_lift": _vol_matched_lift(group, tier_all),
                "median_fwd_ret_pct": round(group["fwd_ret"].median() * 100, 1),
                "median_fwd_ret_all_pct": round(tier_all["fwd_ret"].median() * 100, 1),
                "recall": round(group["fwd_win"].sum() / tier_all["fwd_win"].sum(), 3),
            })
    out = pd.DataFrame(rows)
    out.attrs["base_rate"] = base_rate
    return out


def _vol_matched_lift(flagged: pd.DataFrame, population: pd.DataFrame) -> float:
    """Hit rate of flagged stocks over the hit rate expected from their volatility mix alone (1.0 = no edge
    beyond being volatile)."""
    by_bucket = population.groupby(["checkpoint", "tier", "vol_bucket"])["fwd_win"].mean().rename("bucket_rate")
    expected = flagged.join(by_bucket, on=["checkpoint", "tier", "vol_bucket"])["bucket_rate"].mean()
    return round(flagged["fwd_win"].mean() / expected, 2) if expected and expected > 0 else np.nan


def start_of_year_universe(close: pd.DataFrame, dollar_volume: pd.DataFrame, year: int,
                           shares_for, raw_closes_for) -> pd.Series:
    """symbol -> tier, using only what was known on the last trading day before the year."""
    before = close.index[close.index < pd.Timestamp(year, 1, 1)]
    base_day = before[-1]
    base = close.loc[:base_day].ffill().iloc[-1]
    liquidity = dollar_volume.loc[:base_day].iloc[-60:].median()
    eligible = [s for s in close.columns
                if base.get(s, 0) >= MIN_START_PRICE and liquidity.get(s, 0) >= MIN_START_DOLLAR_VOLUME]
    raws = raw_closes_for(eligible, base_day.date())
    tiers = {}
    for s in eligible:
        tier = tier_for(market_cap_at(shares_for(s), base_day.date(), raws.get(s)))
        if tier:
            tiers[s] = tier
    return pd.Series(tiers, name="tier")


EXCESS_RULES = {
    "mom120_top10": lambda p: p["ret_120d_pct"] >= 0.9,
    "mom60_top10": lambda p: p["ret_60d_pct"] >= 0.9,
    "early_momentum": lambda p: p["early_momentum"].astype(bool),
    "trend_template": lambda p: p["trend_template"].astype(bool),
    "near_52w_high": lambda p: p["off_52w_high_pct"] >= 0.9,
}


def market_regime(index_close: pd.Series) -> pd.Series:
    """True where the regime index closes above its 200-day moving average."""
    return (index_close > index_close.rolling(200, min_periods=160).mean()).rename("index_above_ma200")


def excess_vs_vol_peers(panel: pd.DataFrame, regime: pd.Series) -> pd.DataFrame:
    """Per (rule, checkpoint, tier): mean forward log return of flagged stocks minus the mean of all stocks in
    the same checkpoint, tier and volatility quintile. Positive = edge beyond just being volatile."""
    p = panel[panel["fwd_ret"].notna() & panel["vol_bucket"].notna()].copy()
    p["fwd_log"] = np.log1p(p["fwd_ret"].clip(lower=-0.99))
    p["excess"] = p["fwd_log"] - p.groupby(["checkpoint", "tier", "vol_bucket"])["fwd_log"].transform("mean")
    out = []
    for name, rule in EXCESS_RULES.items():
        g = p[rule(p)].groupby(["checkpoint", "tier"])["excess"].agg(["mean", "size"]).reset_index()
        g.columns = ["checkpoint", "tier", "excess", "flagged"]
        g["rule"] = name
        out.append(g)
    result = pd.concat(out, ignore_index=True)
    result["index_above_ma200"] = result["checkpoint"].map(regime).astype(bool)
    return result


def summarize_years(out_dir: str, years: List[int]) -> pd.DataFrame:
    """Key forward-test numbers and winner-capture stats side by side for each year already run."""
    rows = []
    for year in years:
        folder = os.path.join(out_dir, str(year))
        fwd = pd.read_csv(os.path.join(folder, "forward_test.csv"))
        timeline = pd.read_csv(os.path.join(folder, "winner_timeline.csv"))
        for r in fwd.itertuples():
            rows.append({"year": year, "rule": r.rule, "tier": r.tier, "flagged_per_checkpoint": r.flagged_per_checkpoint,
                         "hit_rate": r.hit_rate, "loss_rate": r.loss_rate, "lift": r.lift,
                         "vol_matched_lift": r.vol_matched_lift})
        for screen in SCREENS:
            rows.append({"year": year, "rule": f"capture:{screen}", "tier": "Winners",
                         "caught": int(timeline[f"{screen}_first"].notna().sum()), "of": len(timeline),
                         "median_gain_ahead": timeline[f"{screen}_gain_ahead_share"].median()})
    summary = pd.DataFrame(rows)
    summary.to_csv(os.path.join(out_dir, f"summary_{min(years)}_{max(years)}.csv"), index=False)
    excess = pd.concat([pd.read_csv(os.path.join(out_dir, str(y), "excess_vs_vol_peers.csv")).assign(year=y)
                        for y in years], ignore_index=True)
    by_year = excess.groupby(["rule", "tier", "year"])["excess"].mean().unstack("year") * 100
    by_year.round(2).to_csv(os.path.join(out_dir, f"excess_by_year_{min(years)}_{max(years)}.csv"))
    by_regime = excess.groupby(["rule", "tier", "index_above_ma200"])["excess"].agg(
        mean_excess_pct=lambda s: s.mean() * 100, checkpoints="size", share_positive=lambda s: (s > 0).mean())
    by_regime.round(3).to_csv(os.path.join(out_dir, f"excess_by_regime_{min(years)}_{max(years)}.csv"))
    return summary


def run(args: argparse.Namespace) -> None:
    today = args.today or date.today()
    alpaca = AlpacaData()
    stocks = alpaca.listed_stocks()
    bar_cache = DailyBarCache(args.cache_dir, alpaca.daily_bars)
    start = date(args.year - 1, 1, 1) - timedelta(days=31 * (LOOKBACK_MONTHS - 12))
    year_end = pd.Timestamp(args.year, 12, 31)
    end = min(date(args.year + 1, 4, 30), today)
    close, dollar_volume = bar_cache.load(stocks.index.tolist() + BENCHMARKS, start, end, today)
    print(f"bars {close.shape}, {close.index.min().date()} -> {close.index.max().date()}", flush=True)

    shares_cache = SharesCache(os.path.join(args.cache_dir, "shares.json"))
    try:
        universe = start_of_year_universe(close, dollar_volume, args.year,
                                          lambda s: shares_cache.get(s, today), alpaca.raw_closes)
    finally:
        shares_cache.save()
    print(f"universe {len(universe)}: {universe.value_counts().to_dict()}", flush=True)

    winners = pd.read_csv(args.winners_csv)
    winners = winners[winners["year"] == args.year]
    frames = compute_feature_frames(close, dollar_volume)
    days = checkpoint_days(close.index, args.year, args.step)
    panel = checkpoint_panel(frames, days, universe, args.horizon)
    year_start_close = close[close.index < pd.Timestamp(args.year, 1, 1)].ffill().iloc[-1]

    in_year = (close.index >= pd.Timestamp(args.year - 1, 12, 1)) & (close.index <= year_end)
    timeline = winner_timeline(panel, winners, close[in_year], year_start_close)
    profile = feature_profile(panel, winners["symbol"].tolist())
    fwd = forward_test(panel)
    excess = excess_vs_vol_peers(panel, market_regime(close[REGIME_INDEX]))

    out = os.path.join(args.out_dir, str(args.year))
    os.makedirs(out, exist_ok=True)
    panel.to_pickle(os.path.join(out, "panel.pkl"))
    timeline.to_csv(os.path.join(out, "winner_timeline.csv"), index=False)
    profile.to_csv(os.path.join(out, "winner_feature_profile.csv"))
    fwd.to_csv(os.path.join(out, "forward_test.csv"), index=False)
    excess.to_csv(os.path.join(out, "excess_vs_vol_peers.csv"), index=False)
    print(f"checkpoints {len(days)}, panel rows {len(panel)}, forward base rate {fwd.attrs['base_rate']:.3f}")
    print(f"wrote {out}")


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--year", type=int, nargs="+", required=True, help="one or more years, run in order")
    p.add_argument("--step", type=int, default=10, help="trading days between checkpoints (10 = two weeks)")
    p.add_argument("--horizon", type=int, default=60, help="forward window in trading days for the forward test")
    p.add_argument("--winners-csv", default=DEFAULT_WINNERS_CSV)
    p.add_argument("--cache-dir", default=DEFAULT_CACHE_DIR)
    p.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    p.add_argument("--today", type=date.fromisoformat, help=argparse.SUPPRESS)
    return p.parse_args(argv)


def main(argv=None) -> None:
    args = parse_args(argv)
    years = args.year
    for year in years:
        print(f"=== {year} ===", flush=True)
        run(argparse.Namespace(**{**vars(args), "year": year}))
    if len(years) > 1:
        summarize_years(args.out_dir, years)
        print(f"wrote summary for {years}")


if __name__ == "__main__":
    main()

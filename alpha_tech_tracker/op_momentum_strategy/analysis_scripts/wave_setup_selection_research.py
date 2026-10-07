"""Setup selection research: which measures pick wave setups that keep working, and which don't.

Everything is decided from data before each weekly decision day, and judged on a calibration
period first, then checked on a later test period (Finding 18 in the ticker-tuning doc).

Dataset: every `--step` sessions (decision day d), for each ticker x setup (fixed exits from setup
reports' trades.csv), the setup's track record before d (3-month / 1-month / 2-week totals, win rate,
risk-adjusted score, consistency, profit factor, recency-weighted total), the ticker's and QQQ's
conditions before d (20/60/120-session return, distance to MA50, volatility trend, overnight vs
in-session moves), and the setup's result over the next 5 / 10 sessions.

Report sections:
  A. Ranking measures: rank by each, trade each ticker's top 3 for 5 sessions -> $ per period.
  B. Conditions: next-5-session result per setup type when a condition holds or not.
  C. Rules: R0 rank by 3-month total; R1 = R0 with long + overnight setups only; R2 = R1 with long
     setups only above MA50; R3 = R1, pausing a setup type after a losing month across tickers.
  D. Ticker momentum on top of R1: keep the top 3 / 5 tickers by 20/60/120-session return.
     The variant is chosen on calibration by return on capital used, then reported on test.

$10k per traded ticker in three $3,333 setup sleeves, fixed size, costs as in the setup reports.

  PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker \\
    python -m alpha_tech_tracker.op_momentum_strategy.analysis_scripts.wave_setup_selection_research \\
    --reports alpha_tech_tracker/op_momentum_strategy/backtest_result/wave_setups/2025-06-02_2026-10-06 \\
    --exclude SNDK --clip 10
"""

import argparse
import math
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
from alpaca.data.enums import DataFeed

from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.wave_risk_reward_scan import _load_bars
from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.wave_risk_reward_setup_report import (
    DEFAULT_OUT_ROOT,
    REPORT_EXITS,
    SETUP_TYPES,
)
from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.wave_setup_walk_forward import family_of, load_trades

LOOKBACK = 63
PER_TICKER = 10000.0
SLEEVE = PER_TICKER / 3
MEASURES = ["tot63", "tot21", "tot10", "win63", "tstat63", "consistency63", "pf63", "ewm15", "both_horizons"]
RULES = ("R0", "R1", "R2", "R3")
MOMENTUM = ("ret20", "ret60", "ret120")


# ---------------------------------------------------------------------------
# Dataset
# ---------------------------------------------------------------------------

def daily_frame(ticker, first, last, feed=DataFeed.SIP):
    bars = _load_bars(ticker, first, last, feed)
    day = bars.groupby(bars.index.date).agg(open=("open", "first"), high=("high", "max"), low=("low", "min"),
                                            close=("close", "last"))
    day.index = pd.Index(day.index)
    return day


def ticker_features(day, d):
    """Trend, volatility and overnight/in-session measures from daily bars before `d`."""
    past = day[day.index < d]
    if len(past) < 61:
        return {}
    close = past["close"]
    ranges = (past["high"] - past["low"]) / past["close"]
    return {"ret20": close.iloc[-1] / close.iloc[-21] - 1, "ret60": close.iloc[-1] / close.iloc[-61] - 1,
            "ret120": close.iloc[-1] / close.iloc[-121] - 1 if len(past) >= 121 else np.nan,
            "ma50gap": close.iloc[-1] / close.iloc[-50:].mean() - 1,
            "adr_ratio": ranges.iloc[-10:].mean() / ranges.iloc[-60:].mean(),
            "on20": np.log(past["open"] / close.shift(1)).iloc[-20:].sum(),
            "ins20": np.log(past["close"] / past["open"]).iloc[-20:].sum()}


def setup_features(returns, days, sessions, i):
    """Track-record measures of one setup before sessions[i]; returns/days are its trades in day order."""
    before = days < sessions[i]
    window_mask = before & (days >= sessions[max(0, i - LOOKBACK)])
    window, w_days = returns[window_mask], days[window_mask]
    out = {"n63": len(window), "tot63": float(window.sum())}
    for n in (21, 10):
        out[f"tot{n}"] = float(returns[before & (days >= sessions[max(0, i - n)])].sum())
    out["win63"] = float((window > 0).mean()) if len(window) else np.nan
    sd = window.std(ddof=1) if len(window) >= 3 else np.nan
    out["tstat63"] = float(window.mean() / sd * math.sqrt(len(window))) if sd and sd > 0 else np.nan
    edges = [sessions[max(0, i - 60 + 10 * k)] for k in range(7)]
    slices = [window[(w_days >= edges[k]) & (w_days < edges[k + 1])].sum() for k in range(6)]
    out["consistency63"] = float(np.mean([s > 0 for s in slices]) + window.sum() / 1000)
    gains, losses = window[window > 0].sum(), -window[window < 0].sum()
    out["pf63"] = float(min(gains / losses, 10.0)) if losses > 0 else (10.0 if gains > 0 else np.nan)
    ages = np.array([i - np.searchsorted(sessions, d) for d in w_days])
    out["ewm15"] = float((np.asarray(window) * 0.5 ** (ages / 15)).sum()) if len(window) else 0.0
    out["both_horizons"] = out["tot63"] if out["tot63"] > 0 and out["tot21"] > 0 else -np.inf
    return out


def build_dataset(trades, calibration, step=5, daily_loader=daily_frame):
    sessions = np.array(sorted(set(trades["day"])), dtype=object)
    qqq = daily_loader("QQQ", sessions[0], sessions[-1])
    rows = []
    for ticker in sorted(set(trades["ticker"])):
        mine = trades[trades["ticker"] == ticker].sort_values("day")
        day = daily_loader(ticker, sessions[0], sessions[-1])
        per_setup = {s: (np.asarray(g["net_pct"], dtype=float), np.array(g["day"])) for s, g in mine.groupby("setup")}
        for i in range(LOOKBACK, len(sessions), step):
            d = sessions[i]
            tf, qf = ticker_features(day, d), ticker_features(qqq, d)
            if not tf or not qf:
                continue
            for setup in REPORT_EXITS:
                if setup not in per_setup:
                    continue
                returns, days = per_setup[setup]
                row = {"ticker": ticker, "setup": setup, "type": SETUP_TYPES[setup], "d": d, **tf,
                       "qqq_ret20": qf["ret20"], "qqq_ma50gap": qf["ma50gap"],
                       **setup_features(returns, days, sessions, i)}
                for n in (5, 10):
                    if i + n <= len(sessions):
                        row[f"fwd{n}"] = float(returns[(days >= d) & (days <= sessions[i + n - 1])].sum())
                    else:
                        row[f"fwd{n}"] = np.nan
                rows.append(row)
    frame = pd.DataFrame(rows)
    frame = frame[frame["d"] >= calibration[0]]
    frame["period"] = np.where(frame["d"] <= calibration[1], "calibration", "test")
    return frame


# ---------------------------------------------------------------------------
# Picking
# ---------------------------------------------------------------------------

def pick_setups(group, measure="tot63", rule="R0", type_health=None, top=3, min_trades=3):
    """Top setups of one ticker on one decision day: eligible by the rule, best `measure` first,
    one per family. All rules need >= `min_trades` trades and a positive 3-month total."""
    pool = group[(group["n63"] >= min_trades) & (group["tot63"] > 0)]
    pool = pool[pool[measure].notna() & np.isfinite(pool[measure].astype(float))]
    if rule in ("R1", "R2", "R3"):
        pool = pool[pool["type"].isin(["long", "overnight"])]
    if rule == "R2":
        pool = pool[(pool["type"] != "long") | (pool["ma50gap"] > 0)]
    if rule == "R3":
        pool = pool[pool["type"].isin([t for t, v in (type_health or {}).items() if v > 0])]
    chosen, families = [], []
    for _, row in pool.sort_values(measure, ascending=False).iterrows():
        family = family_of(row["setup"])
        if family not in families:
            chosen.append(row)
            families.append(family)
        if len(chosen) == top:
            break
    return chosen


def momentum_keep(day_rows, momentum, top_k, positive_only):
    """Tickers kept on a decision day: the top `top_k` by trailing return (positive ones only, optionally)."""
    ranks = day_rows.groupby("ticker")[momentum].first().dropna().sort_values(ascending=False)
    if positive_only:
        ranks = ranks[ranks > 0]
    return list(ranks.index[:top_k])


def simulate(frame, period, measure="tot63", rule="R0", momentum=None, top_k=None, positive_only=False):
    """Weekly portfolio: $ per week, month and ticker, and the average capital used."""
    sub = frame[(frame["period"] == period) & frame["fwd5"].notna()]
    health = frame.groupby(["d", "type"])["tot21"].sum() if rule == "R3" else None
    weeks, months, per_ticker, slots = {}, {}, {}, 0
    for d, day_rows in sub.groupby("d"):
        keep = momentum_keep(day_rows, momentum, top_k, positive_only) if momentum else sorted(day_rows["ticker"].unique())
        slots += len(keep)
        type_health = health.loc[d].to_dict() if health is not None else None
        week = 0.0
        for ticker in keep:
            picks = pick_setups(day_rows[day_rows["ticker"] == ticker], measure, rule, type_health)
            pnl = sum(r["fwd5"] for r in picks) / 100 * SLEEVE
            per_ticker[ticker] = per_ticker.get(ticker, 0.0) + pnl
            week += pnl
        weeks[d] = week
        months[f"{d:%Y-%m}"] = months.get(f"{d:%Y-%m}", 0.0) + week
    w = pd.Series(weeks, dtype=float)
    capital = slots / len(w) * PER_TICKER if len(w) else 0.0
    return {"total": w.sum(), "capital": capital, "return_pct": w.sum() / capital * 100 if capital else 0.0,
            "weeks_up": f"{(w > 0).sum()}/{len(w)}", "worst_week": w.min() if len(w) else 0.0,
            "months": pd.Series(months, dtype=float), "per_ticker": per_ticker}


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def _money(v):
    return f"{'-' if v < 0 else '+'}${abs(v):,.0f}"


def section_measures(frame):
    lines = ["## A. Ranking measures (top 3 per ticker, 5 sessions, all setup types)", "",
             "| Measure | Calibration | Weeks up | Worst week | Test | Weeks up | Worst week |", "|---|---|---|---|---|---|---|"]
    rows = []
    for measure in MEASURES:
        cal, test = simulate(frame, "calibration", measure), simulate(frame, "test", measure)
        rows.append((cal["total"], f"| {measure} | {_money(cal['total'])} | {cal['weeks_up']} | {_money(cal['worst_week'])} | "
                                   f"{_money(test['total'])} | {test['weeks_up']} | {_money(test['worst_week'])} |"))
    return lines + [line for _, line in sorted(rows, reverse=True)]


def section_conditions(frame):
    conditions = {
        "ticker up 20 sessions": frame["ret20"] > 0, "ticker above MA50": frame["ma50gap"] > 0,
        "moves came overnight (20)": frame["on20"] > 0, "moves came in-session (20)": frame["ins20"] > 0,
        "volatility rising (ADR10/60 > 1.1)": frame["adr_ratio"] > 1.1, "QQQ up 20 sessions": frame["qqq_ret20"] > 0,
        "setup up last 2 weeks": frame["tot10"] > 0, "setup up 3 months": frame["tot63"] > 0,
    }
    lines = ["## B. Conditions (average next-5-session result, % per setup-week: yes / no)", "",
             "| Condition | Type | Calibration yes / no | Test yes / no | Same direction |", "|---|---|---|---|---|"]
    for name, mask in conditions.items():
        for setup_type in ("long", "short", "box", "overnight"):
            cells, diffs = [], []
            for period in ("calibration", "test"):
                sub = frame[(frame["period"] == period) & (frame["type"] == setup_type) & frame["fwd5"].notna()]
                cond = mask.reindex(sub.index)
                yes, no = sub[cond]["fwd5"].mean(), sub[~cond]["fwd5"].mean()
                cells.append(f"{yes:+.2f} / {no:+.2f}")
                diffs.append(yes - no)
            same = "yes" if np.sign(diffs[0]) == np.sign(diffs[1]) else "no"
            lines.append(f"| {name} | {setup_type} | {cells[0]} | {cells[1]} | {same} |")
    return lines


def section_rules(frame):
    n = frame["ticker"].nunique()
    lines = [f"## C. Rules (rank by 3-month total, weekly, $10k x {n} tickers)", "",
             "| Rule | Calibration | Weeks up | Worst week | Tickers up | Test | Weeks up | Worst week | Tickers up |",
             "|---|---|---|---|---|---|---|---|---|"]
    for rule in RULES:
        cal, test = simulate(frame, "calibration", rule=rule), simulate(frame, "test", rule=rule)
        up = lambda r: f"{sum(v > 0 for v in r['per_ticker'].values())}/{len(r['per_ticker'])}"
        lines.append(f"| {rule} | {_money(cal['total'])} | {cal['weeks_up']} | {_money(cal['worst_week'])} | {up(cal)} | "
                     f"{_money(test['total'])} | {test['weeks_up']} | {_money(test['worst_week'])} | {up(test)} |")
    return lines


def section_momentum(frame):
    variants = [("all tickers", None, None, False)] + [
        (f"top {k} by {m}{' (positive)' if pos else ''}", m, k, pos)
        for m in MOMENTUM for k in (3, 5) for pos in (False, True)]
    lines = ["## D. Ticker momentum on top of R1 ($10k per kept ticker; return on capital used)", "",
             "| Variant | Calibration $ | Capital | Return | Test $ | Capital | Return | Weeks up |",
             "|---|---|---|---|---|---|---|---|"]
    results = {}
    for name, momentum, k, pos in variants:
        cal = simulate(frame, "calibration", rule="R1", momentum=momentum, top_k=k, positive_only=pos)
        test = simulate(frame, "test", rule="R1", momentum=momentum, top_k=k, positive_only=pos)
        results[name] = (cal, test)
        lines.append(f"| {name} | {_money(cal['total'])} | ${cal['capital']:,.0f} | {cal['return_pct']:+.1f}% | "
                     f"{_money(test['total'])} | ${test['capital']:,.0f} | {test['return_pct']:+.1f}% | {test['weeks_up']} |")
    chosen = max((n for n in results if n != "all tickers"), key=lambda n: results[n][0]["return_pct"])
    cal, test = results[chosen]
    lines += ["", f"Chosen on calibration (return on capital used): **{chosen}** — calibration {cal['return_pct']:+.1f}%, "
                  f"test {test['return_pct']:+.1f}% (all tickers: {results['all tickers'][1]['return_pct']:+.1f}% in test)."]
    return lines


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--reports", nargs="+", required=True, help="Setup report folders (trades.csv), same window")
    parser.add_argument("--exclude", nargs="*", default=[], help="Tickers to leave out")
    parser.add_argument("--clip", type=float, default=0.0, help="Cap each trade at +/- this %% (0 = off)")
    parser.add_argument("--calibration", nargs=2, type=date.fromisoformat, default=[date(2025, 9, 2), date(2026, 7, 2)])
    parser.add_argument("--test-end", type=date.fromisoformat, help="Last decision day of the test (default: data end)")
    parser.add_argument("--step", type=int, default=5, help="Sessions between decision days (default: 5)")
    parser.add_argument("--out-dir", help="Default: backtest_result/wave_setups/selection_research_<calibration start>_<data end>")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    trades = pd.concat([load_trades(Path(p) / "trades.csv") for p in args.reports], ignore_index=True)
    trades = trades[~trades["ticker"].isin(args.exclude)]
    if args.test_end:
        trades = trades[trades["day"] <= args.test_end]
    if args.clip:
        trades["net_pct"] = trades["net_pct"].clip(-args.clip, args.clip)
    frame = build_dataset(trades, tuple(args.calibration), args.step)
    end = max(trades["day"])
    out_dir = Path(args.out_dir) if args.out_dir else DEFAULT_OUT_ROOT / (
        f"selection_research_{args.calibration[0]}_{end}" + (f"_clip{args.clip:g}" if args.clip else ""))
    out_dir.mkdir(parents=True, exist_ok=True)
    frame.to_csv(out_dir / "dataset.csv", index=False)
    header = [f"# Setup selection research {args.calibration[0]} .. {end}", "",
              f"{frame['ticker'].nunique()} tickers ({', '.join(sorted(frame['ticker'].unique()))}); calibration "
              f"{args.calibration[0]}..{args.calibration[1]}, test after. Decisions every {args.step} sessions from data "
              f"before each decision day."
              + (f" Trades capped at +/-{args.clip:g}%." if args.clip else "")
              + (f" Excluded: {', '.join(args.exclude)}." if args.exclude else ""), ""]
    text = "\n".join(header + section_measures(frame) + [""] + section_conditions(frame) + [""]
                     + section_rules(frame) + [""] + section_momentum(frame)) + "\n"
    (out_dir / "report.md").write_text(text)
    print(text)
    print(f"report.md and dataset.csv written to {out_dir}")


if __name__ == "__main__":
    main()

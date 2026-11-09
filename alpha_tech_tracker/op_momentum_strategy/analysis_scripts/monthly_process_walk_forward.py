"""Monthly process walk-forward: re-pick the tickers and their setups every month, trade with the monitor's rules.

At each month's first session, with no data from after it (ticker-tuning doc, Finding 43):

  1. tickers  ticker_screen's top --picks (ticker_screen_walk_forward: top 150 by dollar volume, 4%+ range, ranked by
              the last 63 sessions of drive long + filtered overnight long)
  2. setups   the monitor's config refresh (top_setups_by_ticker): each pick's top --top-setups long / overnight
              setups over the last --refresh-lookback sessions, with --min-trades trades and a positive total
  3. trade    for the month, the setups at their fixed exits; overnight longs only on nights the overnight trend
              filter allows (and not when the overnight short is on); the monitor's drive short + re-entry behind
              --short-gate and overnight short behind --overnight-short-gate on the picks plus QQQ

Four plans are compared: refreshed vs fixed setups (--fixed-setups), with and without the shorts. $10k split
--picks ways a trade, 5 bps, not compounded. The setup report and the per-ticker short trades are cached under
--cache-dir/<year>/, the ticker picks under ticker_screen_walk_forward's cache.

  python -m alpha_tech_tracker.op_momentum_strategy.analysis_scripts.monthly_process_walk_forward --year 2026 \\
    --end 2026-11-06
  ... --overnight-short-gate off      # the monitor without the overnight short
"""

import argparse
import json
from concurrent.futures import ProcessPoolExecutor
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
from alpaca.data.enums import DataFeed

from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.setup_portfolio_check import daily_frames, gated_sessions
from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.ticker_screen import fetch_assets, legs_job, stock_universe
from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.ticker_screen_walk_forward import (
    parse_args as walk_forward_args,
    run_year,
)
from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.ticker_stats_report import clamp_end_for_sip
from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.wave_risk_reward_setup_report import (
    REPORT_EXITS,
    SETUP_TYPES,
    main as setup_report_main,
    top_setups_by_ticker,
)
from alpha_tech_tracker.op_momentum_strategy.trend_filters import MARKET_TICKER, market_trend, session_flags

DEFAULT_CACHE = Path(__file__).resolve().parents[1] / "backtest_result" / "monthly_process"
REFRESH_TYPES = ("long", "overnight")
REFRESH_SETUPS = ["drive long", "pullback long", "pullback long C1", "bounce long", "overnight always", "overnight ma200"]
SHORT_LEGS = ("drive short + re-entry", "overnight short")
GATE_CHOICES = ("qqq-ma50-down10", "qqq-ma50", "qqq-ma200", "always", "off")
PLANS = (("screen + setup refresh + shorts", "refresh", True), ("screen + fixed setups + shorts", "fixed", True),
         ("screen + setup refresh, no shorts", "refresh", False), ("screen + fixed setups, no shorts", "fixed", False))
REPORT_MARGIN_SESSIONS = 5


def month_days(starts, sessions, end):
    """{month start: the sessions of that month up to end}."""
    bounds = list(starts[1:]) + [end + timedelta(days=1)]
    return {start: [d for d in sessions if start <= d < stop and d <= end] for start, stop in zip(starts, bounds)}


def refresh_setups(trades, tickers, past_days, top_n, min_trades):
    """{ticker: setups} as the monitor's config refresh picks them from the trades over past_days."""
    rows = trades[trades.ticker.isin(tickers) & trades.day.isin(set(past_days))]
    ranked = top_setups_by_ticker(rows.to_dict("records"), top_n, REFRESH_TYPES, min_trades)
    return {t: [s for s, _ in ranked.get(t, [])] for t in tickers}


def month_trades(fixed_exit, short_legs, setups, days, gates, with_shorts):
    """The month's trades: setups at their fixed exits (overnight longs filtered) and, with_shorts, the gated shorts."""
    days = set(days)
    drive_gate, night_gate, night_ok = gates
    rows = []
    for r in fixed_exit[fixed_exit.ticker.isin(list(setups)) & fixed_exit.day.isin(days)].itertuples():
        if r.setup not in setups[r.ticker]:
            continue
        if SETUP_TYPES[r.setup] == "overnight" and (not night_ok.get(r.day, False) or (with_shorts and r.day in night_gate)):
            continue
        rows.append((r.ticker, r.day, r.setup, r.net_pct))
    if with_shorts:
        traded = short_legs[short_legs.ticker.isin(list(setups) + [MARKET_TICKER]) & short_legs.day.isin(days)]
        for r in traded.itertuples():
            if (r.leg == SHORT_LEGS[0] and r.day in drive_gate) or (r.leg == SHORT_LEGS[1] and r.day in night_gate):
                rows.append((r.ticker, r.day, r.leg, r.pct))
    return pd.DataFrame(rows, columns=["ticker", "day", "setup", "pct"])


def run_plan(kind, with_shorts, picks, data, args):
    """(trades with month / dollars columns, {month start: {ticker: setups}}) for one plan."""
    parts, chosen = [], {}
    for start, days in data["months"].items():
        names = picks[start]
        if kind == "refresh":
            past = [d for d in data["sessions"] if d < start][-args.refresh_lookback:]
            setups = refresh_setups(data["trades"], names, past, args.top_setups, args.min_trades)
        else:
            setups = {t: list(args.fixed_setups) for t in names}
        chosen[start] = setups
        month = month_trades(data["fixed_exit"], data["short_legs"], setups, days, data["gates"], with_shorts)
        parts.append(month.assign(month=start.strftime("%Y-%m"), dollars=month.pct / 100 * args.capital / args.picks))
    return pd.concat(parts, ignore_index=True), chosen


def summary(trades):
    if trades.empty:
        return {"trades": 0, "won %": 0.0, "per trade %": 0.0, "P&L $": 0, "max DD $": 0, "months +": "0/0"}
    equity = trades.groupby("day").dollars.sum().sort_index().cumsum()
    months = trades.groupby("month").dollars.sum()
    return {"trades": len(trades), "won %": round(100 * (trades.pct > 0).mean(), 1),
            "per trade %": round(trades.pct.mean(), 3), "P&L $": round(trades.dollars.sum()),
            "max DD $": round((equity - equity.cummax()).min()), "months +": f"{(months > 0).sum()}/{len(months)}"}


def gate_days(gate, start, end):
    return set() if gate == "off" else gated_sessions(start, end, gate)


def cached_short_legs(tickers, start, end, folder, workers):
    """The monitor short legs per ticker over start..end, cached one CSV per ticker."""
    folder.mkdir(parents=True, exist_ok=True)
    missing = [t for t in tickers if not (folder / f"{t}.csv").exists()]
    if missing:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            for ticker, legs in zip(missing, pool.map(legs_job, [(t, start, end) for t in missing])):
                legs[legs.leg.isin(SHORT_LEGS)].to_csv(folder / f"{ticker}.csv", index=False)
    legs = pd.concat([pd.read_csv(folder / f"{t}.csv") for t in tickers], ignore_index=True)
    legs["day"] = [date.fromisoformat(str(d)[:10]) for d in legs.day]
    return legs


def cached_setup_report(tickers, start, end, folder, workers):
    """The setup report's trades for the refresh setups, rerun when a ticker is missing from the cached one."""
    path = folder / "trades.csv"
    if path.exists() and set(tickers) <= set(pd.read_csv(path, usecols=["ticker"]).ticker):
        trades = pd.read_csv(path)
    else:
        setup_report_main(["--tickers", *tickers, "--start", start.isoformat(), "--end", end.isoformat(),
                           "--workers", str(workers), "--setups", *REFRESH_SETUPS, "--out-dir", str(folder)])
        trades = pd.read_csv(path)
    trades["day"] = [date.fromisoformat(t[:10]) for t in trades.entry_time]
    return trades


def load_data(year, args):
    end = clamp_end_for_sip(min(date(year, 12, 31), args.end or date.today()), DataFeed.SIP)
    screen_args = walk_forward_args(["--years", str(year), "--end", end.isoformat(), "--picks", str(args.picks),
                                     "--workers", str(args.workers)])
    _, picks = run_year(year, stock_universe(fetch_assets()), screen_args)
    qqq = daily_frames([MARKET_TICKER], date(year - 2, 1, 1), end)[MARKET_TICKER]
    sessions = sorted(d for d in qqq.index if d <= end)
    starts = sorted(picks)
    report_start = [d for d in sessions if d < starts[0]][-(args.refresh_lookback + REPORT_MARGIN_SESSIONS)]
    tickers = sorted({t for names in picks.values() for t in names})
    folder = Path(args.cache_dir) / str(year)
    trades = cached_setup_report(tickers, report_start, end, folder / "setup_report", args.workers)
    short_legs = cached_short_legs(tickers + [MARKET_TICKER], starts[0], end, folder / "short_legs", args.workers)
    gates = (gate_days(args.short_gate, starts[0], end), gate_days(args.overnight_short_gate, starts[0], end),
             session_flags(market_trend(qqq), sessions, "overnight_ok"))
    fixed_exit = trades[[REPORT_EXITS.get(s) == x for s, x in zip(trades.setup, trades.exit)]]
    return picks, {"trades": trades, "fixed_exit": fixed_exit, "short_legs": short_legs, "sessions": sessions,
                   "months": month_days(starts, sessions, end), "gates": gates, "end": end}


def report(year, picks, data, args):
    results = {name: run_plan(kind, shorts, picks, data, args) for name, kind, shorts in PLANS}
    pd.set_option("display.width", 300, "display.max_colwidth", 200)
    per_trade = args.capital / args.picks
    print(f"\n=== {year} to {data['end']}: top {args.picks} monthly, ${per_trade:,.0f} a trade, 5 bps; short gate "
          f"{args.short_gate}, overnight short gate {args.overnight_short_gate}")
    print(pd.DataFrame({name: summary(t) for name, (t, _) in results.items()}).T.to_string())
    months = pd.DataFrame({name: t.groupby("month").dollars.sum() for name, (t, _) in results.items()}).fillna(0)
    months.loc["total"] = months.sum()
    print("\n=== by month ($)")
    print(months.round(0).to_string())
    trades, chosen = results[PLANS[0][0]]
    print(f"\n=== {PLANS[0][0]}: picks, refreshed setups and P&L")
    for start, setups in chosen.items():
        month = trades[trades.month == start.strftime("%Y-%m")]
        by = month.groupby("ticker").dollars.sum()
        cells = [f"{t} [{', '.join(setups[t]) or 'no setup'}] {by.get(t, 0):+,.0f}" for t in setups]
        print(f"{start:%b}: ${month.dollars.sum():+,.0f} | " + "; ".join(cells) + f"; {MARKET_TICKER} {by.get(MARKET_TICKER, 0):+,.0f}")
    print(f"\n=== {PLANS[0][0]}: by setup")
    print(trades.groupby("setup").agg(trades=("pct", "size"), won_pct=("pct", lambda x: 100 * (x > 0).mean()),
                                      per_trade_pct=("pct", "mean"), dollars=("dollars", "sum"))
          .sort_values("dollars").round(2).to_string())
    return results


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--year", type=int, nargs="+", required=True)
    parser.add_argument("--end", type=date.fromisoformat, help="Last session (default: today)")
    parser.add_argument("--picks", type=int, default=5)
    parser.add_argument("--top-setups", type=int, default=3, help="Setups per ticker from the refresh")
    parser.add_argument("--refresh-lookback", type=int, default=63, help="Sessions the refresh ranks setups on")
    parser.add_argument("--min-trades", type=int, default=3)
    parser.add_argument("--fixed-setups", nargs="+", default=["drive long", "pullback long", "overnight always"])
    parser.add_argument("--short-gate", choices=GATE_CHOICES, default="qqq-ma50-down10",
                        help="Gate for the monitor's drive short + re-entry")
    parser.add_argument("--overnight-short-gate", choices=GATE_CHOICES, default="qqq-ma200")
    parser.add_argument("--capital", type=float, default=10000.0)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--cache-dir", default=str(DEFAULT_CACHE))
    parser.add_argument("--json", help="Also write each plan's summary and monthly P&L to this JSON file")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    out = {}
    for year in args.year:
        picks, data = load_data(year, args)
        results = report(year, picks, data, args)
        out[year] = {name: {"summary": summary(t), "months": t.groupby("month").dollars.sum().round(0).to_dict()}
                     for name, (t, _) in results.items()}
    if args.json:
        Path(args.json).write_text(json.dumps(out, indent=1, default=str))


if __name__ == "__main__":
    main()

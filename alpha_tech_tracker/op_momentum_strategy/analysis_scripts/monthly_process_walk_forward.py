"""Monthly process walk-forward: re-pick the tickers and their setups every month, trade with the monitor's rules.

At each month's first session, with no data from after it (ticker-tuning doc, Finding 43):

  1. tickers  ticker_screen's top --picks (ticker_screen_walk_forward: top 150 by dollar volume, 4%+ range, ranked by
              the last 63 sessions of drive long + filtered overnight long)
  2. setups   the monitor's config refresh (top_setups_by_ticker): each pick's top --top-setups long / overnight
              setups over the last --refresh-lookback sessions, with --min-trades trades and a positive total
  3. trade    for the month, the setups at their fixed exits; overnight longs only on nights the overnight trend
              filter allows (and not when the overnight short is on); the monitor's drive short + re-entry behind
              --short-gate and overnight short behind --overnight-short-gate on the picks plus QQQ

The setup report's 5-min bars are not split-adjusted, so its trades held across a stock split (overnight holds on the
split night, a fake -90% on a 10-for-1) are dropped; split days come from raw vs split-adjusted daily closes.

Six plans are compared: refreshed vs fixed setups (--fixed-setups), each with both shorts, the drive short only, and
no shorts. $10k / --picks a trade ($2,000), 5 bps, not compounded. Each plan is reported three ways: as traded
(every signal taken), capped (at most --max-positions open at a time, by entry time; default 2 x --picks, $20k), and
capped with --extra-cost-bps on every trade and --borrow-bps a day on shorts (both off by default). Returns are also
given on the capital actually used: each trading day's most money open at once (overnight holds included),
averaged over the days traded. Years the rules were tuned on (TUNED_ON) are marked in-sample.

Against hindsight: the universe includes delisted stocks (--listed-only to drop them), the screen's price floor uses
the raw close of the time, and neither the ranking nor the setup refresh sees an overnight hold that exits after the
month starts. The setup report and the per-ticker short trades are cached under --cache-dir/<year>/, the ticker
picks under ticker_screen_walk_forward's cache.

  python -m alpha_tech_tracker.op_momentum_strategy.analysis_scripts.monthly_process_walk_forward --year 2026 \\
    --end 2026-11-06 --extra-cost-bps 5 --borrow-bps 2
"""

import argparse
import json
from concurrent.futures import ProcessPoolExecutor
from datetime import date, datetime, time, timedelta
from pathlib import Path

import pandas as pd
from alpaca.data.enums import Adjustment, DataFeed

from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.setup_portfolio_check import daily_frames, gated_sessions
from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.ticker_screen import (
    fetch_daily,
    legs_job,
)
from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.ticker_screen_walk_forward import (
    parse_args as walk_forward_args,
    run_year,
    screen_universe,
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
PLANS = (("fixed setups + both shorts", "fixed", True, True), ("fixed setups + drive short", "fixed", True, False),
         ("fixed setups, no shorts", "fixed", False, False), ("setup refresh + both shorts", "refresh", True, True),
         ("setup refresh + drive short", "refresh", True, False), ("setup refresh, no shorts", "refresh", False, False))
TUNED_ON = {2020: "gates", 2022: "gates", 2023: "screen", 2025: "screen, gates", 2026: "screen, gates, fixed setups"}
OPEN_BAR, CLOSE_BAR = time(9, 30), time(15, 55)
REPORT_MARGIN_SESSIONS = 5
SPLIT_JUMP = 0.1


def month_days(starts, sessions, end):
    """{month start: the sessions of that month up to end}."""
    bounds = list(starts[1:]) + [end + timedelta(days=1)]
    return {start: [d for d in sessions if start <= d < stop and d <= end] for start, stop in zip(starts, bounds)}


def refresh_setups(trades, tickers, past_days, top_n, min_trades):
    """{ticker: setups} as the monitor's config refresh picks them from the trades over past_days (less overnight holds
    entered on the last of them: they exit after the refresh)."""
    rows = trades[trades.ticker.isin(tickers) & trades.day.isin(set(past_days))]
    if past_days:
        rows = rows[~((rows.setup.map(SETUP_TYPES) == "overnight") & (rows.day == past_days[-1]))]
    ranked = top_setups_by_ticker(rows.to_dict("records"), top_n, REFRESH_TYPES, min_trades)
    return {t: [s for s, _ in ranked.get(t, [])] for t in tickers}


def _stamp(text):
    return datetime.strptime(str(text)[:16], "%Y-%m-%d %H:%M")


def short_times(leg, day):
    """(entry, exit) of a monitor short: the drive short from the first bar to the close, the overnight short from
    the close to the next open (next calendar day, enough to order it before the next session's entries)."""
    if leg == SHORT_LEGS[0]:
        return datetime.combine(day, OPEN_BAR), datetime.combine(day, CLOSE_BAR)
    return datetime.combine(day, CLOSE_BAR), datetime.combine(day + timedelta(days=1), OPEN_BAR)


def month_trades(fixed_exit, short_legs, setups, days, gates, drive_short, overnight_short):
    """The month's trades with entry / exit times: setups at their fixed exits (overnight longs filtered, and skipped
    when the overnight short is on) and the gated shorts that are switched on."""
    days = set(days)
    drive_gate, night_gate, night_ok = gates
    rows = []
    for r in fixed_exit[fixed_exit.ticker.isin(list(setups)) & fixed_exit.day.isin(days)].itertuples():
        if r.setup not in setups[r.ticker]:
            continue
        if SETUP_TYPES[r.setup] == "overnight" and (not night_ok.get(r.day, False) or (overnight_short and r.day in night_gate)):
            continue
        rows.append((r.ticker, r.day, r.setup, r.net_pct, _stamp(r.entry_time), _stamp(r.exit_time)))
    if drive_short or overnight_short:
        traded = short_legs[short_legs.ticker.isin(list(setups) + [MARKET_TICKER]) & short_legs.day.isin(days)]
        for r in traded.itertuples():
            if (drive_short and r.leg == SHORT_LEGS[0] and r.day in drive_gate) or \
                    (overnight_short and r.leg == SHORT_LEGS[1] and r.day in night_gate):
                rows.append((r.ticker, r.day, r.leg, r.pct, *short_times(r.leg, r.day)))
    return pd.DataFrame(rows, columns=["ticker", "day", "setup", "pct", "entry", "exit"])


def peak_positions(trades):
    """The most trades open at once (an exit at a time frees its slot before an entry at the same time)."""
    events = sorted([(t, 1) for t in trades.entry] + [(t, -1) for t in trades.exit], key=lambda e: (e[0], e[1]))
    open_now = peak = 0
    for _, step in events:
        open_now += step
        peak = max(peak, open_now)
    return peak


def cap_positions(trades, slots):
    """trades taken in entry-time order while fewer than `slots` are open (an exit frees its slot for an entry at the
    same time); the rest are skipped, as with $10k split into `slots` pieces."""
    if not slots or trades.empty:
        return trades
    ordered = trades.sort_values(["entry", "ticker", "setup"], kind="mergesort")
    open_exits, keep = [], []
    for index, entry, exit_ in zip(ordered.index, ordered.entry, ordered.exit):
        open_exits = [x for x in open_exits if x > entry]
        if len(open_exits) < slots:
            open_exits.append(exit_)
            keep.append(index)
    return trades[trades.index.isin(keep)]


def capital_in_use(trades, per_trade):
    """(average, peak) of each trading day's most money open at once; overnight holds count on the day they are bought
    and the morning they are sold."""
    if trades.empty:
        return 0.0, 0.0
    events = sorted([(t, 1) for t in trades.entry] + [(t, -1) for t in trades.exit], key=lambda e: (e[0], e[1]))
    open_now, by_day = 0, {}
    for stamp, step in events:
        before = open_now
        open_now += step
        day = stamp.date()
        by_day[day] = max(by_day.get(day, 0), open_now, before if step < 0 else 0)
    days = [n for d, n in by_day.items() if d.weekday() < 5 and n > 0]
    return (sum(days) / len(days) * per_trade, max(days) * per_trade) if days else (0.0, 0.0)


def with_costs(trades, extra_cost_bps, borrow_bps):
    """trades with extra_cost_bps off every trade and borrow_bps off every short."""
    shorts = trades.setup.isin(SHORT_LEGS)
    return trades.assign(pct=trades.pct - extra_cost_bps / 100 - shorts * borrow_bps / 100)


def run_plan(kind, drive_short, overnight_short, picks, data, args):
    """(trades with month / dollars columns, {month start: {ticker: setups}}) for one plan, every signal taken."""
    parts, chosen = [], {}
    for start, days in data["months"].items():
        names = picks[start]
        if kind == "refresh":
            past = [d for d in data["sessions"] if d < start][-args.refresh_lookback:]
            setups = refresh_setups(data["trades"], names, past, args.top_setups, args.min_trades)
        else:
            setups = {t: list(args.fixed_setups) for t in names}
        chosen[start] = setups
        month = month_trades(data["fixed_exit"], data["short_legs"], setups, days, data["gates"], drive_short,
                             overnight_short)
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


def split_days(raw, adjusted):
    """{ticker: sessions a split took effect}: where the raw / split-adjusted close ratio jumps by more than
    SPLIT_JUMP (the two feeds also differ by rounding from day to day)."""
    out = {}
    for ticker in set(raw) & set(adjusted):
        ratio = raw[ticker]["Close"].astype(float) / adjusted[ticker]["Close"].astype(float)
        jump = (ratio / ratio.shift() - 1).abs() > SPLIT_JUMP
        out[ticker] = {pd.Timestamp(d).date() for d in ratio.index[jump]}
    return out


def drop_split_trades(trades, splits):
    """trades without those held across a split day (entry before it, exit on or after it)."""
    exits = [date.fromisoformat(t[:10]) for t in trades.exit_time]
    across = [any(day < s <= out for s in splits.get(ticker, ())) for ticker, day, out in zip(trades.ticker, trades.day, exits)]
    return trades[[not a for a in across]]


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
    """The setup report's trades for the refresh setups; tickers missing from the cached report are run on their own
    and appended (a ticker the report cannot run is recorded as tried, with no trades)."""
    path, tried_path = folder / "trades.csv", folder / "tickers_tried.txt"
    cached = pd.read_csv(path) if path.exists() else pd.DataFrame()
    tried = set(tried_path.read_text().split()) if tried_path.exists() else set(cached.get("ticker", []))
    missing = [t for t in tickers if t not in tried]
    if missing:
        extra = folder / "added"
        setup_report_main(["--tickers", *missing, "--start", start.isoformat(), "--end", end.isoformat(),
                           "--workers", str(workers), "--setups", *REFRESH_SETUPS, "--out-dir", str(extra)])
        cached = pd.concat([cached, pd.read_csv(extra / "trades.csv")], ignore_index=True)
        folder.mkdir(parents=True, exist_ok=True)
        cached.to_csv(path, index=False)
        tried_path.write_text("\n".join(sorted(tried | set(missing))))
    trades = cached
    trades["day"] = [date.fromisoformat(t[:10]) for t in trades.entry_time]
    return trades


def load_data(year, args):
    end = clamp_end_for_sip(min(date(year, 12, 31), args.end or date.today()), DataFeed.SIP)
    screen_args = walk_forward_args(["--years", str(year), "--end", end.isoformat(), "--picks", str(args.picks),
                                     "--workers", str(args.workers)])
    _, picks = run_year(year, screen_universe(not args.listed_only), screen_args)
    qqq = daily_frames([MARKET_TICKER], date(year - 2, 1, 1), end)[MARKET_TICKER]
    sessions = sorted(d for d in qqq.index if d <= end)
    starts = sorted(picks)
    report_start = [d for d in sessions if d < starts[0]][-(args.refresh_lookback + REPORT_MARGIN_SESSIONS)]
    tickers = sorted({t for names in picks.values() for t in names})
    folder = Path(args.cache_dir) / str(year)
    trades = cached_setup_report(tickers, report_start, end, folder / "setup_report", args.workers)
    splits = split_days(fetch_daily(tickers, report_start, end, Adjustment.RAW), fetch_daily(tickers, report_start, end))
    kept = drop_split_trades(trades, splits)
    if len(kept) < len(trades):
        found = {t: sorted(str(d) for d in days) for t, days in splits.items() if days}
        print(f"dropped {len(trades) - len(kept)} setup report trades held across a split ({found})")
    trades = kept
    short_legs = cached_short_legs(tickers + [MARKET_TICKER], starts[0], end, folder / "short_legs", args.workers)
    gates = (gate_days(args.short_gate, starts[0], end), gate_days(args.overnight_short_gate, starts[0], end),
             session_flags(market_trend(qqq), sessions, "overnight_ok"))
    fixed_exit = trades[[REPORT_EXITS.get(s) == x for s, x in zip(trades.setup, trades.exit)]]
    return picks, {"trades": trades, "fixed_exit": fixed_exit, "short_legs": short_legs, "sessions": sessions,
                   "months": month_days(starts, sessions, end), "gates": gates, "end": end}


def variants(trades, args):
    """{as traded, capped, capped + costs}: the plan's trades three ways (dollars recomputed after costs)."""
    capped = cap_positions(trades, args.max_positions)
    costly = with_costs(capped, args.extra_cost_bps, args.borrow_bps)
    costly = costly.assign(dollars=costly.pct / 100 * args.capital / args.picks)
    return {"as traded": trades, "capped": capped, "capped + costs": costly}


def report(year, picks, data, args):
    results = {name: run_plan(kind, drive, night, picks, data, args) for name, kind, drive, night in PLANS}
    pd.set_option("display.width", 300, "display.max_colwidth", 200)
    per_trade = args.capital / args.picks
    tuned = TUNED_ON.get(year)
    print(f"\n=== {year} to {data['end']}: top {args.picks} monthly, ${per_trade:,.0f} a trade, 5 bps; short gate "
          f"{args.short_gate}, overnight short gate {args.overnight_short_gate}; cap {args.max_positions} open, extra "
          f"{args.extra_cost_bps:g} bps, borrow {args.borrow_bps:g} bps/day; "
          + (f"IN-SAMPLE (tuned on: {tuned})" if tuned else "out of sample"))
    rows = {}
    for name, (trades, _) in results.items():
        three = variants(trades, args)
        row = {f"{k} $": summary(v)["P&L $"] for k, v in three.items()}
        average, peak = capital_in_use(three["capped"], per_trade)
        row.update({"avg capital $": round(average), "peak capital $": round(peak),
                    "capped % of avg capital": round(100 * row["capped $"] / average, 1) if average else 0.0})
        row.update({"trades": len(trades), "taken capped": len(three["capped"]),
                    "max DD $ (capped + costs)": summary(three["capped + costs"])["max DD $"],
                    "months + (capped + costs)": summary(three["capped + costs"])["months +"],
                    "peak open (as traded)": peak_positions(trades) if len(trades) else 0})
        rows[name] = row
    print(pd.DataFrame(rows).T.to_string())
    months = pd.DataFrame({name: variants(t, args)["capped + costs"].groupby("month").dollars.sum()
                           for name, (t, _) in results.items()}).fillna(0)
    months.loc["total"] = months.sum()
    print("\n=== by month, capped + costs ($)")
    print(months.round(0).to_string())
    trades, chosen = results[PLANS[3][0]]
    print(f"\n=== {PLANS[3][0]}: picks, refreshed setups and P&L (as traded)")
    for start, setups in chosen.items():
        month = trades[trades.month == start.strftime("%Y-%m")]
        by = month.groupby("ticker").dollars.sum()
        cells = [f"{t} [{', '.join(setups[t]) or 'no setup'}] {by.get(t, 0):+,.0f}" for t in setups]
        print(f"{start:%b}: ${month.dollars.sum():+,.0f} | " + "; ".join(cells) + f"; {MARKET_TICKER} {by.get(MARKET_TICKER, 0):+,.0f}")
    trades = variants(results[PLANS[0][0]][0], args)["capped + costs"]
    print(f"\n=== {PLANS[0][0]}: by setup, capped + costs")
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
    parser.add_argument("--max-positions", type=int, help="Most trades open at once (default: 2 x --picks, $20k at the "
                                                          "default size; 0 = no cap)")
    parser.add_argument("--extra-cost-bps", type=float, default=0.0, help="Slippage on every trade, beyond the 5 bps")
    parser.add_argument("--borrow-bps", type=float, default=0.0, help="Borrow cost a day on every short")
    parser.add_argument("--listed-only", action="store_true", help="Universe of today's listed stocks only")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--cache-dir", default=str(DEFAULT_CACHE))
    parser.add_argument("--json", help="Also write each plan's summary and monthly P&L to this JSON file")
    args = parser.parse_args(argv)
    if args.max_positions is None:
        args.max_positions = 2 * args.picks
    return args


def main(argv=None):
    args = parse_args(argv)
    out = {}
    for year in args.year:
        picks, data = load_data(year, args)
        results = report(year, picks, data, args)
        out[year] = {"in_sample": TUNED_ON.get(year)}
        for name, (t, _) in results.items():
            three = variants(t, args)
            out[year][name] = {k: {"summary": summary(v), "months": v.groupby("month").dollars.sum().round(0).to_dict()}
                               for k, v in three.items()}
            out[year][name]["peak open"] = peak_positions(t) if len(t) else 0
            average, peak = capital_in_use(three["capped"], args.capital / args.picks)
            out[year][name]["capital"] = {"average": round(average), "peak": round(peak)}
    if args.json:
        Path(args.json).write_text(json.dumps(out, indent=1, default=str))


if __name__ == "__main__":
    main()

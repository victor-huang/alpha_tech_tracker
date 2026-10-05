"""Find the setups that work for a ticker: run every setup, validate on a second half, combine.

For each ticker, every setup in `wave_risk_reward.py` is backtested on its own over
`--start`..`--end`, which is split into two halves by session count:

First half  = choose each intraday setup's exit (target, target-trail, giveback or eod).
Second half = check that choice on data it was not chosen on.

A setup is recommended when it made money in both halves with at least `--min-trades` trades in
each. From overlapping families (pullback long vs pullback long on coarse waves; the two overnight
filters) only the one with the better first half is kept. The recommended setups trade
independently, so the combination's result is the sum of theirs.

The report also shows the ticker's overnight vs in-session return per half: tickers whose gains
come overnight tend to suit the overnight hold, tickers whose gains come in-session the intraday
long setups.

  PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker \\
    python -m alpha_tech_tracker.op_momentum_strategy.analysis_scripts.wave_risk_reward_scan \\
    --tickers AMAT --start 2025-10-01 --end 2026-10-02
"""

import argparse
import math
from collections import OrderedDict
from concurrent.futures import ProcessPoolExecutor
from datetime import date, timedelta

from alpaca.data.enums import DataFeed

from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.ticker_stats_report import (
    clamp_end_for_sip,
)
from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.wave_risk_reward import (
    OVERNIGHT_WARMUP_SESSIONS,
    add_moving_averages,
    regular_hours,
)
from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.wave_risk_reward_backtest import (
    parse_args as parse_backtest_args,
    run_backtest,
)
from alpha_tech_tracker.op_momentum_strategy.op_momentum_backtest import fetch_bars

INTRADAY_EXITS = ("target", "target-trail", "giveback", "eod")
SETUP_RUNS = OrderedDict([
    ("box signals", []),
    ("drive long", ["--no-box-signals", "--opening-drive", "long"]),
    ("drive short", ["--no-box-signals", "--opening-drive", "short"]),
    ("pullback long", ["--no-box-signals", "--wave-pullback", "long"]),
    ("pullback short", ["--no-box-signals", "--wave-pullback", "short"]),
    ("pullback long C1", ["--no-box-signals", "--wave-pullback", "long", "--min-wave-bar-ranges", "3"]),
    ("bounce long", ["--no-box-signals", "--deep-bounce", "long"]),
    ("bounce short", ["--no-box-signals", "--deep-bounce", "short"]),
    ("overnight always", ["--no-box-signals", "--overnight-hold", "always"]),
    ("overnight ma200", ["--no-box-signals", "--overnight-hold", "ma200"]),
])
BOX_GROUPS = {"narrow-box break": "box break", "wide-box break": "box break", "fade": "box fade", "gap": "box gap"}
FAMILIES = ({"pullback long", "pullback long C1"}, {"overnight always", "overnight ma200"})
DEFAULT_MIN_TRADES = 5


def split_halves(sessions):
    """(first-half start, first-half end, second-half start, second-half end) by session count."""
    middle = len(sessions) // 2
    return sessions[0], sessions[middle - 1], sessions[middle], sessions[-1]


def half_stats(trades, start, end):
    pnl = [t["net_pct"] for t in trades if start <= t["entry_time"].date() <= end]
    return {"trades": len(pnl), "total": sum(pnl), "win": sum(p > 0 for p in pnl) / len(pnl) if pnl else 0.0}


def evaluate_setup(trades_by_exit, halves, overnight):
    """Best exit chosen on the first half, with its stats on both halves."""
    a_start, a_end, b_start, b_end = halves
    exits = ("target",) if overnight else INTRADAY_EXITS
    scored = {mode: (half_stats(trades_by_exit[mode], a_start, a_end), half_stats(trades_by_exit[mode], b_start, b_end))
              for mode in exits}
    exit_mode = max(scored, key=lambda mode: scored[mode][0]["total"])
    first, second = scored[exit_mode]
    return {"exit": "next open" if overnight else exit_mode, "first": first, "second": second}


def recommend(rows, min_trades):
    """Setups positive in both halves with enough trades, one per overlapping family (better first half)."""
    holds = [name for name, row in rows.items()
             if row["first"]["total"] > 0 and row["second"]["total"] > 0
             and row["first"]["trades"] >= min_trades and row["second"]["trades"] >= min_trades]
    chosen = []
    for name in holds:
        family = next((f for f in FAMILIES if name in f), {name})
        rivals = [other for other in holds if other in family]
        if max(rivals, key=lambda other: rows[other]["first"]["total"]) == name:
            chosen.append(name)
    return chosen


def session_split(bars, start, end):
    """(overnight %, in-session %) for sessions between start and end."""
    daily = bars.groupby(bars.index.date).agg(open=("open", "first"), close=("close", "last"))
    previous_close = daily["close"].shift(1)
    window = daily[(daily.index >= start) & (daily.index <= end)]
    overnight = sum(math.log(o / p) for o, p in zip(window["open"], previous_close.loc[window.index]) if p == p)
    session = sum(math.log(c / o) for c, o in zip(window["close"], window["open"]))
    return math.exp(overnight) * 100 - 100, math.exp(session) * 100 - 100


def _load_bars(ticker, start, end, feed):
    fetch_start = start - timedelta(days=int(OVERNIGHT_WARMUP_SESSIONS * 1.5))
    fetch_end = clamp_end_for_sip(end + timedelta(days=7), feed)
    raw = fetch_bars([ticker], fetch_start, fetch_end, allow_intraday=True, feed=feed)[ticker]
    return add_moving_averages(regular_hours(raw))


def _run_setup(job):
    ticker, name, start, end, cost_bps, feed_name, earnings = job
    feed = DataFeed.SIP if feed_name == "sip" else DataFeed.IEX
    bars = _load_bars(ticker, start, end, feed)
    args = parse_backtest_args(["--tickers", ticker, "--start", start.isoformat(), "--compare-exits",
                                "--cost-bps", str(cost_bps), "--earnings", earnings] + SETUP_RUNS[name])
    args.end = end
    trades_by_exit = run_backtest(OrderedDict([(ticker, bars)]), args)[0]
    return job, trades_by_exit


def scan_ticker(ticker, start, end, cost_bps, feed_name, workers, earnings="off"):
    feed = DataFeed.SIP if feed_name == "sip" else DataFeed.IEX
    bars = _load_bars(ticker, start, end, feed)
    sessions = sorted(d for d in set(bars.index.date) if start <= d <= end)
    halves = split_halves(sessions)
    jobs = [(ticker, name, start, end, cost_bps, feed_name, earnings) for name in SETUP_RUNS]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        outputs = dict(pool.map(_run_setup, jobs))

    rows = OrderedDict()
    for (_, name, *_), trades_by_exit in outputs.items():
        if name == "box signals":
            for label in sorted(set(BOX_GROUPS.values())):
                groups = [g for g, lab in BOX_GROUPS.items() if lab == label]
                subset = {mode: [t for t in trades if t["group"] in groups] for mode, trades in trades_by_exit.items()}
                rows[label] = evaluate_setup(subset, halves, overnight=False)
        else:
            rows[name] = evaluate_setup(trades_by_exit, halves, overnight=name.startswith("overnight"))
    return {"halves": halves, "rows": rows, "splits": (session_split(bars, *halves[:2]), session_split(bars, *halves[2:]))}


def print_report(ticker, report, min_trades):
    a_start, a_end, b_start, b_end = report["halves"]
    rows = report["rows"]
    (a_on, a_in), (b_on, b_in) = report["splits"]
    print("\n" + "=" * 104)
    print(f"{ticker}   first half {a_start}..{a_end} (exit chosen)   second half {b_start}..{b_end} (check)")
    print(f"  overnight / in-session return: first half {a_on:+.0f}% / {a_in:+.0f}%   second half {b_on:+.0f}% / {b_in:+.0f}%")
    print("=" * 104)
    print(f"  {'setup':18} {'exit':13} | {'first half':>24} | {'second half':>24} | {'both':>5}")
    for name, row in rows.items():
        cells = []
        for half in ("first", "second"):
            s = row[half]
            cells.append(f"{s['trades']:>4} {s['win']:>4.0%} {s['total']:>+9.2f}%")
        holds = (row["first"]["total"] > 0 and row["second"]["total"] > 0
                 and row["first"]["trades"] >= min_trades and row["second"]["trades"] >= min_trades)
        print(f"  {name:18} {row['exit']:13} | {cells[0]:>24} | {cells[1]:>24} | {'yes' if holds else '':>5}")
    chosen = recommend(rows, min_trades)
    if not chosen:
        print("  recommended: none - no setup made money in both halves")
        return chosen
    first = sum(rows[n]["first"]["total"] for n in chosen)
    second = sum(rows[n]["second"]["total"] for n in chosen)
    labels = ", ".join(f"{name} ({rows[name]['exit']})" for name in chosen)
    print(f"  recommended: {labels}")
    print(f"  combined: first half {first:+.2f}%   second half {second:+.2f}%   (setups trade independently; results add up)")
    return chosen


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tickers", nargs="+", required=True)
    parser.add_argument("--start", type=date.fromisoformat, help="First session (default: one year before --end)")
    parser.add_argument("--end", type=date.fromisoformat, help="Last session (default: today)")
    parser.add_argument("--feed", default="sip", choices=["sip", "iex"])
    parser.add_argument("--cost-bps", type=float, default=5.0, help="Round-trip cost in basis points (default: 5)")
    parser.add_argument("--min-trades", type=int, default=DEFAULT_MIN_TRADES,
                        help=f"Trades a setup needs in each half to be recommended (default: {DEFAULT_MIN_TRADES})")
    parser.add_argument("--earnings", default="off", choices=("off", "skip", "only"),
                        help="skip: drop trades that carry an earnings reaction; only: keep just them (default: off)")
    parser.add_argument("--workers", type=int, default=8)
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    feed = DataFeed.SIP if args.feed == "sip" else DataFeed.IEX
    end = clamp_end_for_sip(args.end or date.today(), feed)
    start = args.start or end - timedelta(days=365)
    print(f"Setup scan {start}..{end}, {args.cost_bps:g} bps round trip; each setup backtested on its own")
    for ticker in args.tickers:
        print_report(ticker, scan_ticker(ticker, start, end, args.cost_bps, args.feed, args.workers, args.earnings),
                     args.min_trades)


if __name__ == "__main__":
    main()

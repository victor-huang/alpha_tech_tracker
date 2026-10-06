"""Setup report: every wave_risk_reward setup on every ticker, with weekly and monthly breakdowns.

Runs each setup on its own (box breaks, fades, gaps, opening drive long/short, pullback long/short,
pullback long C1, deep bounce long/short, overnight always/ma200) for every ticker over
`--start`..`--end`, with all exits. Weekly and monthly tables use one exit per setup fixed in
advance (REPORT_EXITS) so they are not picked with hindsight; every trade for every exit is in
the trades CSV.

Every trade is flagged when it carries an earnings reaction (earnings_calendar.py): the
report lists each ticker's earnings sessions and splits the fixed-exit totals into earnings
vs other trades. `--earnings skip` drops those trades from every setup, `--earnings only`
keeps just them (the output folder gets an `_earnings-<mode>` suffix).

Writes to `--out-dir` (default backtest_result/wave_setups/<start>_<end>/):
  report.md   - per-ticker overview, setup x exit totals, monthly and weekly tables
  trades.csv  - every trade: ticker, setup, exit, entry/exit time, prices, net %
  summary.csv - ticker x setup x exit: trades, win rate, total %

  PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker \\
    python -m alpha_tech_tracker.op_momentum_strategy.analysis_scripts.wave_risk_reward_setup_report \\
    --tickers AMD META --start 2026-07-02 --end 2026-10-02
"""

import argparse
import csv
import math
from collections import OrderedDict
from concurrent.futures import ProcessPoolExecutor
from datetime import date, timedelta
from pathlib import Path

from alpaca.data.enums import DataFeed

from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.earnings_calendar import ticker_earnings_windows
from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.ticker_stats_report import clamp_end_for_sip
from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.wave_risk_reward_backtest import (
    parse_args as parse_backtest_args,
    run_backtest,
)
from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.wave_risk_reward_scan import (
    BOX_GROUPS,
    INTRADAY_EXITS,
    SETUP_RUNS,
    _load_bars,
)

REPORT_EXITS = OrderedDict([
    ("box break", "target"),
    ("box fade", "target"),
    ("box gap", "target"),
    ("drive long", "eod"),
    ("drive short", "eod"),
    ("pullback long", "target-trail"),
    ("pullback short", "target-trail"),
    ("pullback long C1", "target-trail"),
    ("bounce long", "target"),
    ("bounce short", "target"),
    ("overnight always", "next open"),
    ("overnight ma200", "next open"),
])
DEFAULT_OUT_ROOT = Path(__file__).resolve().parent.parent / "backtest_result" / "wave_setups"
TRADE_FIELDS = ["ticker", "setup", "exit", "entry_time", "exit_time", "side", "entry", "exit_price",
                "outcome", "net_pct", "earnings"]


def week_start(day):
    return day - timedelta(days=day.weekday())


def period_totals(trades, key):
    """Sum of net % per period, with periods in date order."""
    totals = OrderedDict()
    for t in sorted(trades, key=lambda t: t["entry_time"]):
        period = key(t["entry_time"].date())
        totals[period] = totals.get(period, 0.0) + t["net_pct"]
    return totals


def stats(trades):
    pnl = [t["net_pct"] for t in trades]
    return {"trades": len(pnl), "win": sum(p > 0 for p in pnl) / len(pnl) if pnl else 0.0, "total": sum(pnl)}


def _run(job):
    ticker, name, start, end, cost_bps, feed_name, earnings, windows = job
    feed = DataFeed.SIP if feed_name == "sip" else DataFeed.IEX
    bars = _load_bars(ticker, start, end, feed)
    args = parse_backtest_args(["--tickers", ticker, "--start", start.isoformat(), "--compare-exits",
                                "--cost-bps", str(cost_bps), "--earnings", earnings] + SETUP_RUNS[name])
    args.end = end
    trades_by_exit = run_backtest(OrderedDict([(ticker, bars)]), args, {ticker: windows})[0]
    out = OrderedDict()
    if name == "box signals":
        for label in sorted(set(BOX_GROUPS.values())):
            groups = [g for g, lab in BOX_GROUPS.items() if lab == label]
            out[label] = {mode: [t for t in trades if t["group"] in groups] for mode, trades in trades_by_exit.items()}
    elif name.startswith("overnight"):
        out[name] = {"next open": trades_by_exit["target"]}
    else:
        out[name] = {mode: trades_by_exit[mode] for mode in INTRADAY_EXITS}
    return ticker, out


def ticker_overview(ticker, start, end, feed, windows):
    bars = _load_bars(ticker, start, end, feed)
    daily = bars.groupby(bars.index.date).agg(open=("open", "first"), close=("close", "last"))
    previous_close = daily["close"].shift(1)
    window = daily[(daily.index >= start) & (daily.index <= end)]
    overnight = sum(math.log(o / p) for o, p in zip(window["open"], previous_close.loc[window.index]) if p == p)
    session = sum(math.log(c / o) for c, o in zip(window["close"], window["open"]))
    reaction = sorted(d for d in windows["reaction"] if start <= d <= end)
    return {"sessions": len(window), "buy_hold": (window["close"].iloc[-1] / window["open"].iloc[0] - 1) * 100,
            "overnight": math.exp(overnight) * 100 - 100, "in_session": math.exp(session) * 100 - 100,
            "earnings": OrderedDict((d, (daily.loc[d, "close"] / previous_close.loc[d] - 1) * 100) for d in reaction)}


def _pct(value):
    return f"{value:+.2f}%"


def build_report(results, overviews, start, end, cost_bps, earnings="off"):
    earnings_note = {"off": "", "skip": " Trades carrying an earnings reaction are skipped.",
                     "only": " Only trades carrying an earnings reaction are kept."}[earnings]
    lines = [f"# Wave setup report {start} .. {end}", "",
             f"Every setup backtested on its own, {cost_bps:g} bps round trip. Weekly and monthly tables use a fixed "
             "exit per setup: " + ", ".join(f"{s} = {e}" for s, e in REPORT_EXITS.items()) + ". "
             "Totals are sums of per-trade returns (not compounded); setups trade independently." + earnings_note, ""]

    lines += ["## Summary (fixed exits)", "",
              "| Setup | " + " | ".join(results) + " |", "|---|" + "---|" * len(results)]
    for setup, exit_mode in REPORT_EXITS.items():
        cells = [_pct(stats(results[t][setup][exit_mode])["total"]) for t in results]
        lines.append(f"| {setup} ({exit_mode}) | " + " | ".join(cells) + " |")
    lines += ["", "| Ticker | Buy & hold | Overnight | In-session | Best setup (fixed exit) |", "|---|---|---|---|---|"]
    for t, ov in overviews.items():
        best = max(REPORT_EXITS, key=lambda s: stats(results[t][s][REPORT_EXITS[s]])["total"])
        best_total = stats(results[t][best][REPORT_EXITS[best]])["total"]
        lines.append(f"| {t} | {_pct(ov['buy_hold'])} | {_pct(ov['overnight'])} | {_pct(ov['in_session'])} | "
                     f"{best} {_pct(best_total)} |")

    for t, setups in results.items():
        ov = overviews[t]
        lines += ["", f"## {t}", "",
                  f"{ov['sessions']} sessions: buy & hold {_pct(ov['buy_hold'])}, overnight {_pct(ov['overnight'])}, "
                  f"in-session {_pct(ov['in_session'])}.", "",
                  "Earnings reaction sessions (close vs previous close): "
                  + (", ".join(f"{d} {_pct(move)}" for d, move in ov.get("earnings", {}).items())
                     or "none in the window") + ".", "",
                  "### All exits (trades / win / total)", "",
                  "| Setup | target | target-trail | giveback | eod | next open |", "|---|---|---|---|---|---|"]
        for setup in REPORT_EXITS:
            cells = []
            for mode in list(INTRADAY_EXITS) + ["next open"]:
                trades = setups[setup].get(mode)
                if trades is None:
                    cells.append("")
                    continue
                s = stats(trades)
                cells.append(f"{s['trades']} / {s['win']:.0%} / {_pct(s['total'])}")
            lines.append(f"| {setup} | " + " | ".join(cells) + " |")

        if any("earnings" in t for by_exit in setups.values() for trades in by_exit.values() for t in trades):
            lines += ["", "### Earnings vs other trades (fixed exits, trades / total)", "",
                      "| Setup | earnings | other |", "|---|---|---|"]
            for setup, exit_mode in REPORT_EXITS.items():
                cells = []
                for flag in (True, False):
                    s = stats([t for t in setups[setup][exit_mode] if t.get("earnings") == flag])
                    cells.append(f"{s['trades']} / {_pct(s['total'])}")
                lines.append(f"| {setup} | " + " | ".join(cells) + " |")

        for title, key, label in (("Monthly", lambda d: (d.year, d.month), lambda p: f"{p[0]}-{p[1]:02d}"),
                                  ("Weekly (week starting)", week_start, lambda p: f"{p:%m-%d}")):
            periods = sorted({key(d) for d in _session_days(setups)})
            lines += ["", f"### {title} (fixed exits)", "",
                      "| Setup | " + " | ".join(label(p) for p in periods) + " | Total |",
                      "|---|" + "---|" * (len(periods) + 1)]
            for setup, exit_mode in REPORT_EXITS.items():
                totals = period_totals(setups[setup][exit_mode], key)
                cells = [_pct(totals[p]) if p in totals else "" for p in periods]
                lines.append(f"| {setup} | " + " | ".join(cells) + f" | {_pct(sum(totals.values()))} |")
    return "\n".join(lines) + "\n"


def _session_days(setups):
    return {t["entry_time"].date() for by_exit in setups.values() for trades in by_exit.values() for t in trades}


def write_outputs(results, overviews, start, end, cost_bps, out_dir, earnings="off"):
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "trades.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=TRADE_FIELDS)
        writer.writeheader()
        for ticker, setups in results.items():
            for setup, by_exit in setups.items():
                for mode, trades in by_exit.items():
                    for t in trades:
                        writer.writerow({"ticker": ticker, "setup": setup, "exit": mode,
                                         "entry_time": t["entry_time"], "exit_time": t["exit_time"],
                                         "side": t["side"], "entry": round(t["entry"], 4),
                                         "exit_price": round(t["exit"], 4), "outcome": t["outcome"],
                                         "net_pct": round(t["net_pct"], 4), "earnings": t.get("earnings", "")})
    with (out_dir / "summary.csv").open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["ticker", "setup", "exit", "trades", "win_rate", "total_pct", "report_exit"])
        for ticker, setups in results.items():
            for setup, by_exit in setups.items():
                for mode, trades in by_exit.items():
                    s = stats(trades)
                    writer.writerow([ticker, setup, mode, s["trades"], round(s["win"], 4), round(s["total"], 4),
                                     mode == REPORT_EXITS[setup]])
    (out_dir / "report.md").write_text(build_report(results, overviews, start, end, cost_bps, earnings))
    return out_dir


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tickers", nargs="+", required=True)
    parser.add_argument("--start", type=date.fromisoformat, help="First session (default: 3 months before --end)")
    parser.add_argument("--end", type=date.fromisoformat, help="Last session (default: today)")
    parser.add_argument("--feed", default="sip", choices=["sip", "iex"])
    parser.add_argument("--cost-bps", type=float, default=5.0)
    parser.add_argument("--earnings", default="off", choices=("off", "skip", "only"),
                        help="skip: drop trades that carry an earnings reaction; only: keep just them (default: off)")
    parser.add_argument("--out-dir", help="Output folder (default: backtest_result/wave_setups/<start>_<end>)")
    parser.add_argument("--workers", type=int, default=8)
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    feed = DataFeed.SIP if args.feed == "sip" else DataFeed.IEX
    end = clamp_end_for_sip(args.end or date.today(), feed)
    start = args.start or end - timedelta(days=91)
    # loaded once per ticker here, not in every worker, so parallel jobs never race on the calendar cache
    windows = OrderedDict((t, ticker_earnings_windows(t, _load_bars(t, start, end, feed))) for t in args.tickers)
    jobs = [(t, name, start, end, args.cost_bps, args.feed, args.earnings, windows[t])
            for t in args.tickers for name in SETUP_RUNS]
    results = OrderedDict((t, OrderedDict()) for t in args.tickers)
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for ticker, out in pool.map(_run, jobs):
            results[ticker].update(out)
    for ticker in results:
        results[ticker] = OrderedDict((s, results[ticker][s]) for s in REPORT_EXITS)
    overviews = OrderedDict((t, ticker_overview(t, start, end, feed, windows[t])) for t in args.tickers)
    folder = f"{start}_{end}" + (f"_earnings-{args.earnings}" if args.earnings != "off" else "")
    out_dir = write_outputs(results, overviews, start, end, args.cost_bps,
                            Path(args.out_dir) if args.out_dir else DEFAULT_OUT_ROOT / folder, args.earnings)
    report = (out_dir / "report.md").read_text()
    print(report.split("\n## ", 2)[0] + "\n## " + report.split("\n## ", 2)[1].split("\n## ")[0])
    print(f"\nreport, trades.csv and summary.csv written to {out_dir}")


if __name__ == "__main__":
    main()

"""Backtest wave_risk_reward.py signals: one trade per signal, reported by type, ticker and month.

Signals come from `wave_risk_reward.analyze_bars` with exactly the same options as the charting
script, so any configuration there can be backtested here. Every signal between `--start` and
`--end` becomes one trade:

Entry      = the signal bar's close, in the signal's direction (breakout, fade long and drive
             long buy; the rest short). Signals on a session's last bar are skipped.
Exit       = `--exit target`: the signal's stop or target, whichever comes first.
             `--exit target-trail`: the stop until the target is reached, then the
             give-back trail below instead of taking profit at the target.
             `--exit giveback`: the stop, or once the trade is up `--giveback-arm-r` x risk,
             the first close that gives back `--giveback` of the best close-to-close profit.
             `--exit eod`: the stop, else the session's last close.
             Every mode exits at the session close at the latest. A bar touching both stop
             and target counts as the stop; a gap through the stop fills at the bar's open.
             Overnight-hold signals always exit at the next session's first bar open,
             whatever `--exit` says.
Costs      = `--cost-bps` round trip, taken off every trade's return.
Earnings   = `--earnings skip` drops the trades that carry an earnings reaction (the overnight
             hold into a release, intraday signals on the reacting session); `--earnings only`
             keeps them alone. Either way each trade gets an `earnings` flag and the report a
             breakdown by it. Release times come from earnings_calendar.py (Yahoo, cached).

`--legs` adds a hindsight leg report: legs are pivot-to-pivot moves on 5-min closes within a
session that end when price reverses `--leg-reversal-adr` x ADR (prior 20 sessions' high-low).
This measure is independent of the Wave module, so it grades the signals against the moves a
chart reader would mark. A leg is caught when a signal in its direction fires before half the
leg is done.

  PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker \\
    python -m alpha_tech_tracker.op_momentum_strategy.analysis_scripts.wave_risk_reward_backtest \\
    --tickers QQQ SNDK --start 2026-06-01 --end 2026-10-02 --compare-exits
"""

import argparse
import csv
import statistics
from collections import OrderedDict
from datetime import date, timedelta
from pathlib import Path

import numpy as np
from alpaca.data.enums import DataFeed

from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.earnings_calendar import (
    in_earnings_window,
    ticker_earnings_windows,
)
from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.intraday_leg_timing import (
    prior_session_adr,
    regular_sessions,
)
from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.ticker_stats_report import (
    clamp_end_for_sip,
)
from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.wave_risk_reward import (
    LONG_SIGNALS,
    OVERNIGHT_WARMUP_SESSIONS,
    add_moving_averages,
    add_strategy_arguments,
    analyze_bars,
    overnight_needs_history,
    params_from_args,
    regular_hours,
)
from alpha_tech_tracker.op_momentum_strategy.op_momentum_backtest import fetch_bars

DEFAULT_TICKERS = ["QQQ", "SNDK"]
EXIT_MODES = ("target", "target-trail", "giveback", "eod")
DEFAULT_GIVEBACK = 0.32
DEFAULT_GIVEBACK_ARM_R = 0.25
WARMUP_CALENDAR_DAYS = 45  # MA200 and the wave lookback; also 20 prior sessions for leg ADR
DEFAULT_LEG_REVERSAL_ADR = 0.25
DEFAULT_LARGE_LEG_ADR = 0.75
DEFAULT_MEDIUM_LEG_ADR = 0.40
EARLY_LEG_FRACTION = 0.5
SIGNAL_GROUPS = (
    "narrow-box break", "fade", "wide-box break", "stop-and-reverse", "opening drive", "wave pullback",
    "deep bounce", "overnight hold", "gap",
)
CSV_FIELDS = [
    "ticker", "signal", "group", "regime", "entry_time", "exit_time", "side", "entry", "exit",
    "stop", "target", "outcome", "risk", "gross_pct", "net_pct", "net_r", "earnings",
]


def signal_group(signal):
    if signal["signal"].startswith("drive"):
        return "opening drive"
    if signal["signal"].startswith("pullback"):
        return "wave pullback"
    if signal["signal"].startswith("bounce"):
        return "deep bounce"
    if signal["signal"].startswith("overnight"):
        return "overnight hold"
    if signal["gap"]:
        return "gap"
    if signal["signal"].startswith("fade"):
        return "fade"
    if signal["reverses"]:
        return "stop-and-reverse"
    if signal["box_mode"] == "reversion":
        return "wide-box break"
    return "narrow-box break"


class TradeSimulator:
    """Replays one ticker's bars after each signal; built once per ticker."""

    def __init__(self, bars):
        self.index = bars.index
        self.position = {stamp: i for i, stamp in enumerate(bars.index)}
        self.open, self.high, self.low, self.close = (
            bars[column].values for column in ("open", "high", "low", "close")
        )
        dates = bars.index.date
        self.session_end = np.empty(len(bars), dtype=int)
        last = len(bars) - 1
        for i in range(len(bars) - 1, -1, -1):
            if i < len(bars) - 1 and dates[i] != dates[i + 1]:
                last = i
            self.session_end[i] = last

    def run(self, signal, exit_mode, giveback=DEFAULT_GIVEBACK, arm_r=DEFAULT_GIVEBACK_ARM_R):
        """One trade for `signal`, or None when it has no stop/target or fires on the last bar."""
        rr = signal["risk_reward"]
        i = self.position[signal["time"]]
        end = self.session_end[i]
        if signal["signal"] == "overnight_long":
            return self._overnight_trade(signal, i, end)
        if not rr or end == i:
            return None

        side = 1 if signal["signal"] in LONG_SIGNALS else -1
        entry, stop, target = self.close[i], rr["stop"], rr["target"]
        exit_index, exit_price, outcome = end, self.close[end], "eod"
        peak = entry
        target_reached = False
        for j in range(i + 1, end + 1):
            if (self.low[j] <= stop) if side == 1 else (self.high[j] >= stop):
                fill = min(self.open[j], stop) if side == 1 else max(self.open[j], stop)
                exit_index, exit_price, outcome = j, fill, "stop"
                break
            hit_target = (self.high[j] >= target) if side == 1 else (self.low[j] <= target)
            if exit_mode == "target" and hit_target:
                exit_index, exit_price, outcome = j, target, "target"
                break
            target_reached = target_reached or hit_target
            peak = max(peak, self.close[j]) if side == 1 else min(peak, self.close[j])
            if exit_mode == "giveback" or (exit_mode == "target-trail" and target_reached):
                move = (peak - entry) * side
                if move >= arm_r * rr["risk"] and (peak - self.close[j]) * side >= giveback * move:
                    exit_index, exit_price, outcome = j, self.close[j], "giveback"
                    break

        return {
            "signal": signal["signal"],
            "group": signal_group(signal),
            "regime": signal["regime"],
            "entry_time": signal["time"],
            "exit_time": self.index[exit_index],
            "side": side,
            "entry": float(entry),
            "exit": float(exit_price),
            "stop": stop,
            "target": target,
            "outcome": outcome,
            "risk": rr["risk"],
            "gross_pct": side * (exit_price - entry) / entry * 100,
        }

    def _overnight_trade(self, signal, i, end):
        """Buy the signal bar's close, sell the next session's first bar open."""
        next_open_index = end + 1
        if next_open_index >= len(self.close):
            return None
        entry, exit_price = self.close[i], self.open[next_open_index]
        return {
            "signal": signal["signal"],
            "group": signal_group(signal),
            "regime": signal["regime"],
            "entry_time": signal["time"],
            "exit_time": self.index[next_open_index],
            "side": 1,
            "entry": float(entry),
            "exit": float(exit_price),
            "stop": None,
            "target": None,
            "outcome": "next open",
            "risk": signal["risk_reward"]["risk"],
            "gross_pct": (exit_price - entry) / entry * 100,
        }


def apply_costs(trade, cost_bps):
    net_pct = trade["gross_pct"] - cost_bps / 100
    return dict(trade, net_pct=net_pct, net_r=net_pct / 100 * trade["entry"] / trade["risk"])


def summarize(trades):
    if not trades:
        return None
    returns = [trade["net_pct"] for trade in trades]
    return {
        "trades": len(trades),
        "win": sum(r > 0 for r in returns) / len(trades),
        "avg_pct": statistics.mean(returns),
        "avg_r": statistics.mean(trade["net_r"] for trade in trades),
        "total_pct": sum(returns),
        "outcomes": {o: sum(trade["outcome"] == o for trade in trades)
                     for o in ("target", "giveback", "stop", "eod", "next open")},
    }


def zigzag_legs(closes, reversal):
    """(start, end, direction) pivot-to-pivot legs on `closes`; a leg ends on a `reversal` move."""
    legs, start, extreme, direction = [], 0, 0, 0
    for i in range(1, len(closes)):
        extends = (direction >= 0 and closes[i] > closes[extreme]) or (direction <= 0 and closes[i] < closes[extreme])
        if extends:
            if direction == 0:
                direction = 1 if closes[i] > closes[start] else -1
            extreme = i
        elif direction != 0 and abs(closes[i] - closes[extreme]) >= reversal:
            legs.append((start, extreme, direction))
            start, extreme, direction = extreme, i, (1 if closes[i] > closes[extreme] else -1)
        elif direction == 0 and abs(closes[i] - closes[start]) >= reversal:
            direction, extreme = (1 if closes[i] > closes[start] else -1), i
    if direction != 0 and extreme > start:
        legs.append((start, extreme, direction))
    return legs


def find_legs(bars, start, end, reversal_adr, large_adr, medium_adr):
    """Large and medium hindsight legs per session between `start` and `end`."""
    sessions = regular_sessions(bars.rename(columns=str.capitalize))
    adr_pct = prior_session_adr(sessions)
    legs = []
    for session, frame in sessions:
        if not start <= session <= end or session not in adr_pct:
            continue
        adr_usd = adr_pct[session] / 100 * frame["Open"].iloc[0]
        closes = frame["Close"].values
        for a, b, direction in zigzag_legs(closes, reversal_adr * adr_usd):
            size = abs(closes[b] - closes[a])
            kind = "large" if size >= large_adr * adr_usd else "medium" if size >= medium_adr * adr_usd else None
            if kind:
                legs.append({
                    "start": frame.index[a], "end": frame.index[b], "direction": direction,
                    "start_price": closes[a], "end_price": closes[b], "size": size,
                    "adr_multiple": size / adr_usd, "kind": kind, "opening": a < 3,
                })
    return legs


def grade_legs(legs, signals, trades_by_signal_time):
    """Per leg: caught early, late only, signals against it, and the first early trade's capture."""
    graded = []
    for leg in legs:
        def with_leg(signal):
            return (signal["signal"] in LONG_SIGNALS) == (leg["direction"] == 1)

        def progress(signal):
            return (signal["price"] - leg["start_price"]) * leg["direction"] / leg["size"]

        during = [s for s in signals if leg["start"] <= s["time"] <= leg["end"]]
        aligned = sorted((s for s in during if with_leg(s)), key=lambda s: s["time"])
        early = [s for s in aligned if progress(s) <= EARLY_LEG_FRACTION]
        row = {"leg": leg, "caught": bool(early), "late": bool(aligned) and not early,
               "against": sum(1 for s in during if not with_leg(s)), "capture": None}
        if early:
            trade = trades_by_signal_time.get(early[0]["time"])
            if trade:
                row["capture"] = (trade["exit"] - trade["entry"]) * trade["side"] / leg["size"]
        graded.append(row)
    return graded


def _fmt_summary(summary):
    if not summary:
        return "trades    0"
    outcomes = " / ".join(f"{summary['outcomes'][o]}" for o in ("target", "giveback", "stop", "eod", "next open"))
    return (f"trades {summary['trades']:>4}  win {summary['win']:4.0%}  avg {summary['avg_pct']:+7.3f}%"
            f"  avg R {summary['avg_r']:+5.2f}  total {summary['total_pct']:+8.2f}%"
            f"  (target/giveback/stop/eod/next-open {outcomes})")


def _print_breakdown(title, groups):
    print(f"\n  by {title}")
    for label, trades in groups.items():
        if trades:
            print(f"    {label:18} {_fmt_summary(summarize(trades))}")


def print_report(trades, session_count, args, exit_mode):
    print("\n" + "=" * 110)
    print(f"Wave risk/reward backtest   {' '.join(args.tickers)}   {args.start} .. {args.end}"
          f"   exit={exit_mode}   cost={args.cost_bps:g} bps round trip")
    print("=" * 110)
    summary = summarize(trades)
    rate = len(trades) / session_count if session_count else 0
    print(f"  all                {_fmt_summary(summary)}   {rate:.2f} trades/session")
    _print_breakdown("signal type", OrderedDict((g, [t for t in trades if t["group"] == g]) for g in SIGNAL_GROUPS))
    _print_breakdown("ticker", OrderedDict((t, [x for x in trades if x["ticker"] == t]) for t in args.tickers))
    months = sorted({f"{t['entry_time']:%Y-%m}" for t in trades})
    _print_breakdown("month", OrderedDict((m, [t for t in trades if f"{t['entry_time']:%Y-%m}" == m]) for m in months))
    if any("earnings" in t for t in trades):
        _print_breakdown("earnings", OrderedDict((label, [t for t in trades if t.get("earnings") == flag])
                                                 for label, flag in (("earnings", True), ("other", False))))


def print_exit_comparison(trades_by_exit, args):
    print("\n" + "=" * 110)
    print(f"Exit comparison   {' '.join(args.tickers)}   {args.start} .. {args.end}   cost={args.cost_bps:g} bps")
    print("=" * 110)
    for exit_mode, trades in trades_by_exit.items():
        print(f"  {exit_mode:10} {_fmt_summary(summarize(trades))}")


def print_leg_report(graded, args):
    print("\n" + "=" * 110)
    print(f"Leg catch   reversal {args.leg_reversal_adr:g} x ADR, large >= {args.large_leg_adr:g} x ADR,"
          f" medium >= {args.medium_leg_adr:g} x ADR, caught = signal with the leg before half of it is done")
    print("=" * 110)
    for kind in ("large", "medium"):
        for scope, rows in (("all", [r for r in graded if r["leg"]["kind"] == kind]),
                            ("opening", [r for r in graded if r["leg"]["kind"] == kind and r["leg"]["opening"]])):
            if not rows:
                continue
            caught = [r for r in rows if r["caught"]]
            captures = [r["capture"] for r in caught if r["capture"] is not None]
            capture_text = f"   median capture {statistics.median(captures):+.0%} of the leg" if captures else ""
            print(f"  {kind:6} {scope:8} legs {len(rows):>4}   caught {len(caught):>4} ({len(caught) / len(rows):4.0%})"
                  f"   late only {sum(r['late'] for r in rows):>4}   signals against {sum(r['against'] for r in rows):>4}"
                  f"{capture_text}")


def write_csv(trades, out_path):
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for trade in trades:
            writer.writerow(trade)
    return out_path


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--tickers", nargs="+", default=DEFAULT_TICKERS)
    parser.add_argument("--start", required=True, type=date.fromisoformat, help="First session YYYY-MM-DD")
    parser.add_argument("--end", type=date.fromisoformat, help="Last session YYYY-MM-DD (default: today)")
    parser.add_argument("--feed", default="sip", choices=["sip", "iex"])
    parser.add_argument("--exit", default="target", choices=EXIT_MODES, help="Exit model (default: target)")
    parser.add_argument("--compare-exits", action="store_true", help="Also print every exit model side by side")
    parser.add_argument(
        "--giveback", type=float, default=DEFAULT_GIVEBACK,
        help=f"giveback exit: fraction of the best open profit to give back (default: {DEFAULT_GIVEBACK})",
    )
    parser.add_argument(
        "--giveback-arm-r", type=float, default=DEFAULT_GIVEBACK_ARM_R,
        help=f"giveback exit: arm once the trade is up this many x risk (default: {DEFAULT_GIVEBACK_ARM_R})",
    )
    parser.add_argument("--cost-bps", type=float, default=0.0, help="Round-trip cost in basis points (default: 0)")
    parser.add_argument("--legs", action="store_true", help="Add the hindsight leg-catch report")
    parser.add_argument("--leg-reversal-adr", type=float, default=DEFAULT_LEG_REVERSAL_ADR)
    parser.add_argument("--large-leg-adr", type=float, default=DEFAULT_LARGE_LEG_ADR)
    parser.add_argument("--medium-leg-adr", type=float, default=DEFAULT_MEDIUM_LEG_ADR)
    parser.add_argument("--csv-out", help="Write every trade (chosen exit) to this CSV path")
    add_strategy_arguments(parser)
    return parser.parse_args(argv)


def run_backtest(bars_by_ticker, args, earnings_windows_by_ticker=None):
    """Trades per exit mode, graded legs and the session count for the backtest window.

    Earnings windows come from `earnings_windows_by_ticker`, else from the calendar when
    `--earnings` is on; with windows every trade gets an `earnings` flag.
    """
    params = params_from_args(args)
    exit_modes = EXIT_MODES if args.compare_exits else (args.exit,)
    trades_by_exit = {mode: [] for mode in exit_modes}
    graded_legs, session_count = [], 0
    for ticker, bars in bars_by_ticker.items():
        windows = (earnings_windows_by_ticker or {}).get(ticker)
        if windows is None and params.earnings != "off":
            windows = ticker_earnings_windows(ticker, bars)
        signals = [s for s in analyze_bars(bars, params, windows)["signals"] if args.start <= s["time"].date() <= args.end]
        session_count += len({d for d in bars.index.date if args.start <= d <= args.end})
        simulator = TradeSimulator(bars)
        for mode in exit_modes:
            for signal in signals:
                trade = simulator.run(signal, mode, args.giveback, args.giveback_arm_r)
                if trade:
                    if windows is not None:
                        trade["earnings"] = in_earnings_window(signal, windows)
                    trades_by_exit[mode].append(dict(apply_costs(trade, args.cost_bps), ticker=ticker))
        if args.legs:
            legs = find_legs(bars, args.start, args.end, args.leg_reversal_adr, args.large_leg_adr, args.medium_leg_adr)
            chosen = {t["entry_time"]: t for t in trades_by_exit[args.exit] if t["ticker"] == ticker}
            graded_legs += grade_legs(legs, signals, chosen)
    return trades_by_exit, graded_legs, session_count


def main(argv=None):
    args = parse_args(argv)
    feed = DataFeed.SIP if args.feed == "sip" else DataFeed.IEX
    args.end = clamp_end_for_sip(args.end or date.today(), feed)
    warmup_days = int(OVERNIGHT_WARMUP_SESSIONS * 1.5) if overnight_needs_history(args.overnight_hold) else WARMUP_CALENDAR_DAYS
    # an overnight hold entered on the last session exits at the following open, so load a few days more
    fetch_end = clamp_end_for_sip(args.end + timedelta(days=7), feed) if args.overnight_hold != "off" else args.end
    raw = fetch_bars(args.tickers, args.start - timedelta(days=warmup_days), fetch_end,
                     allow_intraday=True, feed=feed)
    bars_by_ticker = OrderedDict()
    for ticker in args.tickers:
        if raw.get(ticker) is None or raw[ticker].empty:
            print(f"{ticker}: no bars, skipped")
            continue
        bars_by_ticker[ticker] = add_moving_averages(regular_hours(raw[ticker]))

    trades_by_exit, graded_legs, session_count = run_backtest(bars_by_ticker, args)
    print_report(trades_by_exit[args.exit], session_count, args, args.exit)
    if args.compare_exits:
        print_exit_comparison(trades_by_exit, args)
    if args.legs:
        print_leg_report(graded_legs, args)
    if args.csv_out:
        print(f"\ntrades written to {write_csv(trades_by_exit[args.exit], Path(args.csv_out))}")


if __name__ == "__main__":
    main()

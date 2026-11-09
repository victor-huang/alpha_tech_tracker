"""Build the replay simulater page: past sessions replayed bar by bar with the wave setup monitor's alerts.

For each chosen ticker-day the page gets the session's 5-min bars (with the previous session as context, VWAP and
the 9 / 20 / 50 / 200-bar moving averages of the 5-min closes) and the system's trades for that day: the setup
report's trades at each setup's fixed exit (REPORT_EXITS) for the setups given per ticker, plus the monitor's drive
short on the days the short gate is on. The player buys, shorts, closes and advances bar by bar; at the close the page
compares their P&L with the system's. See README.md in this folder.

  python -m alpha_tech_tracker.op_momentum_strategy.replay_simulater.build_replay_simulater \\
    --config logs/wave_setup_monitor_config.json --start 2026-09-08 --end 2026-11-06 --out replay_simulater.html
  python -m alpha_tech_tracker.op_momentum_strategy.replay_simulater.build_replay_simulater \\
    --tickers MRNA SNDK --setups "drive long" "pullback long" --start 2026-10-01 --end 2026-11-06 --sessions all
"""

import argparse
import json
import tempfile
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
from alpaca.data.enums import DataFeed

from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.setup_portfolio_check import gated_sessions
from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.wave_rider import load_rider_bars
from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.wave_risk_reward_setup_report import (
    REPORT_EXITS,
    main as setup_report_main,
)

TEMPLATE = Path(__file__).with_name("replay_simulater_template.html")
MA_LENGTHS = (20, 50, 200, 9)  # bar order in the page: m20, m50, m200, m9 (the page reads them by position)
CONTEXT_CALENDAR_DAYS = 7      # bars loaded before a session: enough for the 200-bar MA and the previous session
DRIVE_SHORT = "drive short"
EXIT_TEXT = {"eod": "hold to the close (stop only)", "target": "target", "target-trail": "target, then trail",
             "giveback": "give-back trail", "next open": "sell at the next open"}
SAMPLE = {"best": 7, "worst": 5, "last_week": 6, "spread": 6}


def config_setups(path):
    """{ticker: [setup names]} from a wave setup monitor config."""
    config = json.loads(Path(path).read_text())
    return {t: [s["setup"] if isinstance(s, dict) else s for s in specs] for t, specs in config["tickers"].items()}


def system_trades(trades, setups, gated_days):
    """The system trades: each ticker's setups at their fixed exits, plus drive shorts on gated days. Overnight
    setups are left out (the replay ends at the close)."""
    fixed = trades[[REPORT_EXITS.get(s) == x for s, x in zip(trades.setup, trades.exit)]].copy()
    fixed["day"] = [date.fromisoformat(t[:10]) for t in fixed.entry_time]
    keep = [(s in setups.get(t, []) and REPORT_EXITS[s] != "next open")
            or (s == DRIVE_SHORT and d in gated_days)
            for t, s, d in zip(fixed.ticker, fixed.setup, fixed.day)]
    return fixed[keep].drop_duplicates(["ticker", "setup", "entry_time"])


def pick_sessions(trades, mode, last_week_start=None):
    """[(ticker, day)] to include: every ticker-day with a trade ("all"), or a sample of the best and worst days, the
    last week and a spread of the rest."""
    per_day = trades.groupby(["ticker", "day"]).net_pct.sum().sort_values()
    if mode == "all":
        return sorted(per_day.index, key=lambda k: (k[1], k[0]))
    picks = list(per_day.index[-SAMPLE["best"]:]) + list(per_day.index[:SAMPLE["worst"]])
    if last_week_start:
        picks += [k for k in per_day.index if k[1] >= last_week_start and k not in picks][:SAMPLE["last_week"]]
    rest = [k for k in per_day.index if k not in picks]
    stride = max(1, len(rest) // SAMPLE["spread"])
    picks += rest[len(rest) // 4::stride][:SAMPLE["spread"]]
    return sorted(set(picks), key=lambda k: (k[1], k[0]))


def _r(value):
    return None if pd.isna(value) else round(float(value), 4)


def with_moving_averages(bars):
    bars = bars.copy()
    for n in MA_LENGTHS:
        bars[f"m{n}"] = bars.close.rolling(n, min_periods=n).mean()
    return bars


def session_signals(day_trades, bar_index, first_bar):
    """The page's signal rows for one ticker-day; trades whose entry or exit bar is not in the session are dropped."""
    signals = []
    for r in day_trades.itertuples():
        entry, exit_ = r.entry_time[11:16], r.exit_time[11:16]
        if entry not in bar_index or exit_ not in bar_index:
            continue
        stop = {"drive long": first_bar.low, DRIVE_SHORT: first_bar.high}.get(r.setup)
        signals.append({"setup": "short drive" if r.setup == DRIVE_SHORT else r.setup,
                        "side": "long" if r.side == 1 else "short", "entryBar": bar_index[entry], "entry": _r(r.entry),
                        "stop": _r(stop) if stop is not None else None, "exitText": EXIT_TEXT.get(r.exit, r.exit),
                        "exitBar": bar_index[exit_], "exitPrice": _r(r.exit_price), "outcome": r.outcome,
                        "pct": round(float(r.net_pct), 3)})
    return sorted(signals, key=lambda s: s["entryBar"])


def session_payload(ticker, day, bars, day_trades, gate_on):
    """One session for the page, or None when the bars or signals are missing."""
    bars = with_moving_averages(bars)
    days = sorted(set(bars.index.date))
    if day not in days or days.index(day) == 0:
        return None
    previous = days[days.index(day) - 1]
    today, prev = bars[bars.index.date == day], bars[bars.index.date == previous]
    index = {t.strftime("%H:%M"): i for i, t in enumerate(today.index)}
    signals = session_signals(day_trades, index, today.iloc[0])
    if not signals:
        return None
    return {"ticker": ticker, "date": day.isoformat(), "prevDate": previous.isoformat(), "gate": gate_on,
            "prev": [[_r(b.open), _r(b.high), _r(b.low), _r(b.close), _r(b.m20), _r(b.m50), _r(b.m200), _r(b.m9)]
                     for b in prev.itertuples()],
            "bars": [[t.strftime("%H:%M"), _r(b.open), _r(b.high), _r(b.low), _r(b.close), _r(b.vwap), _r(b.m20),
                      _r(b.m50), _r(b.m200), _r(b.m9)] for t, b in zip(today.index, today.itertuples())],
            "signals": signals}


def render(template, sessions):
    """The template with the sessions inserted (a '</' inside the JSON would end the script tag early)."""
    data = json.dumps(sessions, separators=(",", ":")).replace("</", "<\\/")
    return template.replace("__DATA__", data)


def run_setup_report(tickers, setups, start, end, out_dir, workers):
    names = sorted({s for t in tickers for s in setups.get(t, [])} | {DRIVE_SHORT})
    setup_report_main(["--tickers", *tickers, "--start", start.isoformat(), "--end", end.isoformat(),
                       "--workers", str(workers), "--setups", *names, "--out-dir", str(out_dir)])
    return pd.read_csv(Path(out_dir) / "trades.csv")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", help="Wave setup monitor config: its tickers and their setups")
    parser.add_argument("--tickers", nargs="+", help="Tickers (with --setups) when no --config is given")
    parser.add_argument("--setups", nargs="+", default=["drive long", "pullback long"],
                        help="Setups for every --tickers ticker (default: drive long, pullback long)")
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--short-gate", choices=["qqq-ma50-down10", "qqq-ma50", "qqq-ma200", "always", "off"],
                        default="qqq-ma50-down10", help="Include the monitor's drive short on the days this gate is on")
    parser.add_argument("--sessions", choices=["sample", "all"], default="sample",
                        help="sample: best, worst, last week and a spread (about 24); all: every ticker-day with a trade")
    parser.add_argument("--report-dir", help="Reuse an existing setup report folder (trades.csv) instead of running one")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--out", default="replay_simulater.html")
    args = parser.parse_args(argv)
    if not args.config and not args.tickers:
        parser.error("give --config or --tickers")
    return args


def main(argv=None):
    args = parse_args(argv)
    setups = config_setups(args.config) if args.config else {t: list(args.setups) for t in args.tickers}
    tickers = sorted(setups)
    if args.report_dir:
        trades = pd.read_csv(Path(args.report_dir) / "trades.csv")
    else:
        with tempfile.TemporaryDirectory() as folder:
            trades = run_setup_report(tickers, setups, args.start, args.end, folder, args.workers)
    trades = trades[trades.ticker.isin(tickers)]
    gated = set() if args.short_gate == "off" else gated_sessions(args.start, args.end, args.short_gate)
    trades = system_trades(trades, setups, gated)
    trades = trades[(trades.day >= args.start) & (trades.day <= args.end)]
    picks = pick_sessions(trades, args.sessions, args.end - timedelta(days=args.end.weekday()))
    sessions = []
    for ticker, day in picks:
        bars, _ = load_rider_bars(ticker, day - timedelta(days=CONTEXT_CALENDAR_DAYS), day, DataFeed.SIP, 20)
        payload = session_payload(ticker, day, bars, trades[(trades.ticker == ticker) & (trades.day == day)], day in gated)
        if payload:
            sessions.append(payload)
    Path(args.out).write_text(render(TEMPLATE.read_text(), sessions))
    print(f"{len(sessions)} sessions ({', '.join(tickers)}, {args.start}..{args.end}) written to {args.out}")


if __name__ == "__main__":
    main()

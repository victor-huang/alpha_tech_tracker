"""Recent drive long and overnight hold results, for the wave setup monitor's start-up alert.

Over the last `sessions` completed sessions, pooled over a ticker set, and day by day over the last `days`
sessions for the monitored tickers:

  drive long  the setup report's "drive long" (first green bar of the session, stop at its low, held to the close)
  overnight   the setup report's overnight hold (`overnight ma200` by default): buy the 15:55 bar's close when the
              daily moving-average filter passes, sell the next session's open; nights into an earnings release
              are skipped

Each trade is counted on its entry session; an overnight hold whose next open is not in yet is pending. No costs,
like the setup report's default. Early-close days have no 15:55 bar and so no overnight hold, like the backtest.
"""

from dataclasses import dataclass
from datetime import date
from typing import Optional

import pandas as pd

from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.earnings_calendar import in_earnings_window
from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.wave_risk_reward import (
    OVERNIGHT_ENTRY_TIME,
    analyze_bars,
    overnight_filter_ok,
    params_from_args,
)
from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.wave_risk_reward_backtest import (
    TradeSimulator,
    parse_args as parse_backtest_args,
)
from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.wave_risk_reward_scan import SETUP_RUNS
from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.wave_risk_reward_setup_report import REPORT_EXITS

# the 21 tickers of the setup tapes: the 7 EC2 monitor tickers, the 13-ticker set and LLY
DEFAULT_STATS_TICKERS = ("MRNA", "SNDK", "APP", "AMD", "MDB", "CRWV", "SNPS", "SPOT", "COIN", "MSFT", "SNOW", "CRWD",
                         "AMAT", "FN", "DDOG", "ARM", "CLS", "META", "SPCX", "CHTR", "LLY")
DEFAULT_STATS_SESSIONS = 10
DEFAULT_STATS_DAYS = 3
DEFAULT_STATS_OVERNIGHT = "ma200"
DRIVE_SETUP = "drive long"


@dataclass
class Result:
    ticker: str
    kind: str
    day: date
    pct: Optional[float]  # None: an overnight hold still waiting for the next open


def drive_long_results(ticker, bars, days):
    """Drive long trades entered on `days`, from the bars' analyze_bars signals (bars: lowercase OHLC)."""
    params = params_from_args(parse_backtest_args(["--start", "2000-01-01"] + SETUP_RUNS[DRIVE_SETUP]))
    simulator = TradeSimulator(bars)
    results = []
    for signal in analyze_bars(bars, params)["signals"]:
        if signal["signal"] != "drive_long" or signal["time"].date() not in days:
            continue
        trade = simulator.run(signal, REPORT_EXITS[DRIVE_SETUP])
        if trade:
            results.append(Result(ticker, "drive", signal["time"].date(), trade["gross_pct"]))
    return results


def overnight_results(ticker, bars, daily_closes, windows, days, mode=DEFAULT_STATS_OVERNIGHT):
    """Overnight holds entered on `days`, each sold at the next session's open in the bars (pending without one).

    `daily_closes` is a Series of daily closes indexed by date; the filter uses the closes before the entry session
    plus the 15:55 bar's close. `windows` are earnings windows (earnings_calendar.earnings_windows) or None.
    """
    sessions = sorted(set(bars.index.date))
    results = []
    for position, session in enumerate(sessions):
        if session not in days:
            continue
        day_bars = bars[bars.index.date == session]
        entry_bars = day_bars[day_bars.index.time == OVERNIGHT_ENTRY_TIME]
        if entry_bars.empty:
            continue
        entry_time, entry = entry_bars.index[0], float(entry_bars["close"].iloc[0])
        if windows is not None and in_earnings_window({"signal": "overnight_long", "time": entry_time}, windows):
            continue
        closes = [float(c) for d, c in daily_closes.items() if d < session] + [entry]
        if not overnight_filter_ok(mode, closes):
            continue
        if position + 1 == len(sessions):
            results.append(Result(ticker, "overnight", session, None))
            continue
        exit_price = float(bars[bars.index.date == sessions[position + 1]]["open"].iloc[0])
        results.append(Result(ticker, "overnight", session, (exit_price - entry) / entry * 100))
    return results


def _plural(count, word):
    return f"{count} {word}" + ("" if count == 1 else "s")


def _summary(results):
    done = [r for r in results if r.pct is not None]
    pending = len(results) - len(done)
    if not done:
        return f"{pending} pending (exit at the next open)" if pending else "no trades"
    wins = sum(r.pct > 0 for r in done)
    average = sum(r.pct for r in done) / len(done)
    text = f"{wins}/{len(done)} won ({wins / len(done):.0%}), avg {average:+.2f}%"
    return text + (f", {pending} pending" if pending else "")


def stats_message(results, stats_tickers, monitor_tickers, stats_days, recent_days, overnight_mode, missing=(),
                  notes=()):
    """The start-up alert text from drive long / overnight `results` (Result list)."""
    if not stats_days:
        return "signal stats: no completed sessions in the history"
    pooled = [r for r in results if r.ticker in stats_tickers and r.day in stats_days]
    lines = [f"signal stats, last {_plural(len(stats_days), 'session')} ({min(stats_days):%m-%d} to "
             f"{max(stats_days):%m-%d}), {_plural(len(set(stats_tickers) - set(missing)), 'ticker')}:",
             f"drive long: {_summary([r for r in pooled if r.kind == 'drive'])}",
             f"overnight {overnight_mode}: {_summary([r for r in pooled if r.kind == 'overnight'])}",
             f"monitored ({' '.join(monitor_tickers)}), by day:"]
    for day in recent_days:
        mine = [r for r in results if r.ticker in monitor_tickers and r.day == day]
        lines.append(f"{day:%m-%d} drive long {_summary([r for r in mine if r.kind == 'drive'])} | "
                     f"overnight {_summary([r for r in mine if r.kind == 'overnight'])}")
    if missing:
        lines.append(f"no data: {' '.join(missing)}")
    lines += list(notes)
    return "\n".join(lines)


def completed_sessions(bars_by_ticker, before):
    """Sessions before `before` that any ticker has bars for, oldest first."""
    days = set()
    for bars in bars_by_ticker.values():
        days.update(d for d in pd.DatetimeIndex(bars.index).date if d < before)
    return sorted(days)


def signal_stats(bars_by_ticker, daily_by_ticker, windows_by_ticker, stats_tickers, monitor_tickers, before,
                 sessions=DEFAULT_STATS_SESSIONS, days=DEFAULT_STATS_DAYS, overnight_mode=DEFAULT_STATS_OVERNIGHT,
                 notes=()):
    """The start-up alert text: drive long and overnight results entered in sessions before `before`.

    Bars from `before` on are used only for the next open that ends an overnight hold.
    """
    completed = completed_sessions(bars_by_ticker, before)
    stats_days, recent_days = set(completed[-sessions:]), completed[-days:]
    wanted = stats_days | set(recent_days)
    results, missing = [], []
    for ticker in dict.fromkeys(list(stats_tickers) + list(monitor_tickers)):
        bars = bars_by_ticker.get(ticker)
        if bars is None or bars.empty:
            missing.append(ticker)
            continue
        results += drive_long_results(ticker, bars[bars.index.date < before], wanted)
        results += overnight_results(ticker, bars, daily_by_ticker.get(ticker, pd.Series(dtype=float)),
                                     windows_by_ticker.get(ticker), wanted, overnight_mode)
    return stats_message(results, stats_tickers, monitor_tickers, stats_days, recent_days, overnight_mode,
                         [t for t in missing if t in stats_tickers], notes)

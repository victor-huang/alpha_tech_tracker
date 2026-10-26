"""Ticker setup check: where a ticker's move comes from (intraday vs overnight) and how the drive long and overnight
setups did on it, to help choose which to focus on.

For each ticker over `--start`..`--end` (5-min SIP bars, split-adjusted, `--cost-bps` per trade, $10k per trade):

  split     intraday (open -> close) vs overnight (previous close -> open) from split-adjusted daily bars: compounded
            gain, win rate (sessions closing above their open / gaps up), average move, the worst overnight gap and
            the share of gaps down; for the whole period and the last `--recent` sessions
  setups    drive long (green first bar, stop its low, hold to the close), drive-trail (stop raised to each new
            confirmed dip low, wave setting 7 bars / 38.2% / 1.5), re-entry once above the stop-out level, and the
            overnight hold (buy the 15:55 close, sell the next open; MA200 filter skipping earnings nights, and
            every night including earnings)
  drive     where the summed open -> close moves went: skipped days (first bar red), the first bar of traded days,
            after the stop-out, and what drive long kept

The split is descriptive: picking a ticker's setup family from its past 63/126-session split chose next month's
winner 52-53% of the time (ticker-tuning doc, Finding 36). Use it to see where a ticker has been earning and how much
overnight risk it carries (e.g. to skip overnight holds in a market down wave), not as a rule.

  python -m alpha_tech_tracker.op_momentum_strategy.analysis_scripts.ticker_setup_check MU LLY CRWD --start 2026-05-01
"""

import argparse
from datetime import date, timedelta

import numpy as np
import pandas as pd
from alpaca.data.enums import DataFeed

from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.earnings_calendar import earnings_windows, load_releases
from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.ticker_stats_report import clamp_end_for_sip
from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.wave_rider import load_rider_bars, ride, wave_events
from alpha_tech_tracker.op_momentum_strategy.op_momentum_backtest import fetch_daily_bars
from alpha_tech_tracker.op_momentum_strategy.signal_stats import overnight_results

TRAIL_SETTING = (7, 0.382, 1.5)
DRIVE_RIDERS = {"drive long": "drive", "drive-trail": "drive-trail", "re-entry": "reenter-stoplevel"}
DEFAULT_RECENT = (20, 60)
DAILY_HISTORY_DAYS = 420


def split_stats(daily, start):
    """Intraday vs overnight from daily bars (Open/Close columns, date index) for sessions from `start`."""
    prev = daily["Close"].shift(1)
    part = daily[daily.index >= start]
    intraday = np.log(part["Close"] / part["Open"])
    overnight = np.log(part["Open"] / prev[prev.index >= start])
    overnight.iloc[0] = 0.0
    gaps = overnight.iloc[1:]
    return {"sessions": len(part),
            "buy_hold": (part["Close"].iloc[-1] / part["Open"].iloc[0] - 1) * 100,
            "intraday": np.expm1(intraday.sum()) * 100, "intraday_win": (intraday > 0).mean() * 100,
            "intraday_avg": np.expm1(intraday).mean() * 100,
            "overnight": np.expm1(overnight.sum()) * 100, "overnight_win": (gaps > 0).mean() * 100 if len(gaps) else np.nan,
            "overnight_avg": np.expm1(gaps).mean() * 100 if len(gaps) else np.nan,
            "worst_gap": np.expm1(gaps.min()) * 100 if len(gaps) else np.nan,
            "worst_gap_day": gaps.idxmin() if len(gaps) else None}


def trade_stats(pcts_by_day):
    """trades, win rate, total %, max drawdown $ at $10k per trade from {day: [net % per trade]}."""
    pcts = [p for day in sorted(pcts_by_day) for p in pcts_by_day[day]]
    if not pcts:
        return {"trades": 0, "won": np.nan, "total": 0.0, "max_dd": 0.0}
    curve = pd.Series([sum(pcts_by_day[d]) * 100 for d in sorted(pcts_by_day)]).cumsum()
    return {"trades": len(pcts), "won": 100 * sum(p > 0 for p in pcts) / len(pcts), "total": sum(pcts),
            "max_dd": float((curve - curve.cummax().clip(lower=0)).min())}


def drive_breakdown(bars):
    """Summed open -> close moves split into what drive long skipped, the first bar, after the stop-out and kept."""
    out = {"open_close": 0.0, "skipped": 0.0, "skipped_days": 0, "first_bar": 0.0, "after_stop": 0.0, "stops": 0,
           "kept": 0.0}
    for _, g in bars.groupby(bars.index.date):
        o, c, first = g["open"].iloc[0], g["close"].iloc[-1], g.iloc[0]
        move = (c - o) / o * 100
        out["open_close"] += move
        if not first["close"] > first["open"]:
            out["skipped"] += move
            out["skipped_days"] += 1
            continue
        entry, stop = first["close"], first["low"]
        hit = g.iloc[1:][g["low"].iloc[1:] <= stop]
        exit_price = min(hit["open"].iloc[0], stop) if len(hit) else c
        out["first_bar"] += (entry - o) / o * 100
        if len(hit):
            out["after_stop"] += (c - exit_price) / o * 100
            out["stops"] += 1
        out["kept"] += (exit_price - entry) / o * 100
    return out


def check_ticker(ticker, start, end, cost_bps, recent):
    bars, _ = load_rider_bars(ticker, start, end, DataFeed.SIP, 20)
    daily = fetch_daily_bars([ticker], start - timedelta(days=DAILY_HISTORY_DAYS), end)[ticker]
    daily.index = [pd.Timestamp(x).date() for x in daily.index]
    daily = daily[daily.index <= end]
    sessions = sorted(set(bars.index.date))
    splits = {"period": split_stats(daily, sessions[0])}
    for n in recent:
        if len(sessions) > n:
            splits[f"last {n}"] = split_stats(daily, sessions[-n])

    setups = {}
    events = wave_events(bars, *TRAIL_SETTING)
    for label, rider in DRIVE_RIDERS.items():
        by_day = {}
        for day, evs in events.items():
            trades = ride(rider, evs)
            if trades:
                by_day[day] = [(x - e) / e * 100 - cost_bps / 100 for _, e, _, x, _ in trades]
        setups[label] = trade_stats(by_day)
    closes = daily["Close"].astype(float)
    windows = earnings_windows(load_releases(ticker), sessions)
    for label, mode, w in (("overnight ma200", "ma200", windows), ("overnight incl. earnings", "always", None)):
        held = [r for r in overnight_results(ticker, bars, closes, w, set(sessions), mode) if r.pct is not None]
        setups[label] = trade_stats({r.day: [r.pct - cost_bps / 100] for r in held})
    eves = sorted(d for d in windows["eve"] if d in set(sessions))
    return {"ticker": ticker, "splits": splits, "setups": setups, "drive": drive_breakdown(bars), "earnings_eves": eves,
            "first_session": sessions[0], "last_session": sessions[-1]}


def format_ticker(result):
    lines = [f"## {result['ticker']} ({result['first_session']} to {result['last_session']})", ""]
    split_rows = []
    for name, s in result["splits"].items():
        split_rows.append({"window": name, "sessions": s["sessions"], "buy & hold %": s["buy_hold"],
                           "intraday %": s["intraday"], "up sessions %": s["intraday_win"],
                           "avg day %": s["intraday_avg"], "overnight %": s["overnight"], "up gaps %": s["overnight_win"],
                           "avg gap %": s["overnight_avg"], "worst gap %": s["worst_gap"],
                           "worst gap on": f"{s['worst_gap_day']:%m-%d}" if s["worst_gap_day"] else ""})
    lines += [pd.DataFrame(split_rows).to_string(index=False, float_format=lambda x: f"{x:+.1f}"), ""]
    setup_rows = [{"setup": k, **v} for k, v in result["setups"].items()]
    lines += [pd.DataFrame(setup_rows).to_string(index=False, float_format=lambda x: f"{x:+.1f}"), ""]
    d = result["drive"]
    lines += [f"drive long breakdown of the summed open->close moves ({d['open_close']:+.1f}%): skipped {d['skipped']:+.1f}% "
              f"({d['skipped_days']} red-first-bar days) | first bar {d['first_bar']:+.1f}% | after the stop-out "
              f"{d['after_stop']:+.1f}% ({d['stops']} stops) | kept {d['kept']:+.1f}% before costs",
              "earnings nights skipped by the ma200 hold: " + (", ".join(f"{e:%m-%d}" for e in result["earnings_eves"]) or "none"),
              ""]
    return lines


def summary_table(results, recent):
    rows = []
    for r in results:
        s, last = r["splits"]["period"], r["splits"].get(f"last {recent}")
        rows.append({"ticker": r["ticker"], "intraday %": s["intraday"], "up sessions %": s["intraday_win"],
                     "overnight %": s["overnight"], "up gaps %": s["overnight_win"], "worst gap %": s["worst_gap"],
                     f"intraday % last {recent}": last["intraday"] if last else np.nan,
                     f"overnight % last {recent}": last["overnight"] if last else np.nan,
                     "drive long %": r["setups"]["drive long"]["total"],
                     "drive-trail %": r["setups"]["drive-trail"]["total"],
                     "overnight ma200 %": r["setups"]["overnight ma200"]["total"]})
    return pd.DataFrame(rows).to_string(index=False, float_format=lambda x: f"{x:+.1f}")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("tickers", nargs="+")
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, help="Default: the last completed session")
    parser.add_argument("--cost-bps", type=float, default=5.0)
    parser.add_argument("--recent", type=int, nargs="+", default=list(DEFAULT_RECENT),
                        help="Also show the split over the last N sessions (default: 20 60)")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    end = clamp_end_for_sip(args.end or date.today(), DataFeed.SIP)
    pd.set_option("display.width", 250)
    results = []
    for ticker in args.tickers:
        result = check_ticker(ticker, args.start, end, args.cost_bps, args.recent)
        results.append(result)
        print("\n".join(format_ticker(result)))
    if len(results) > 1:
        print(f"## Summary {results[0]['first_session']} to {max(r['last_session'] for r in results)}\n")
        print(summary_table(results, args.recent[0]))


if __name__ == "__main__":
    main()

"""Setup portfolio check: a capital amount split equally across tickers, traded with the wave setup monitor's long,
short and overnight setups, compared plan by plan.

Per ticker and session (5-min SIP bars, split-adjusted, `--cost-bps` per trade, capital / tickers per trade, one
position per ticker at a time, not compounded):

  drive long               green first bar, stop its low, hold to the close
  drive-trail              drive long, stop raised to each new confirmed dip low (wave setting 7 / 38.2% / 1.5)
  drive + re-entry         drive long, one re-entry on a close back above the first bar's low (before 15:00)
  drive-trail + re-entry   the monitor with --drive-trail --drive-reentry
  drive short + re-entry   red first bar shorted, stop its high, one re-entry back below it with no stop
  overnight long           buy the 15:55 close, sell the next open; MA200 filter, earnings nights skipped
  overnight short          short the 15:55 close, cover the next open; earnings nights skipped

The short legs and the overnight long follow the monitor's market gate (QQQ's previous close below its 50-day MA):
shorts only on gated sessions, the overnight long only on the others. Plans combine the legs; "monitor rules" is what
the monitor alerts with its defaults (plus the chosen drive long variant); with `--short-setups drive` the monitor keeps
the overnight long on gated sessions too.

  python -m alpha_tech_tracker.op_momentum_strategy.analysis_scripts.setup_portfolio_check SNDK APP SPOT MDB \\
    --start 2026-01-02 --end 2026-10-23
"""

import argparse
from concurrent.futures import ProcessPoolExecutor
from datetime import date, time, timedelta

import pandas as pd
from alpaca.data.enums import DataFeed

from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.earnings_calendar import (
    earnings_windows,
    in_earnings_window,
    load_releases,
)
from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.ticker_stats_report import clamp_end_for_sip
from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.wave_capture import daily_context
from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.wave_rider import (
    flip_bars,
    load_rider_bars,
    ride,
    short_pct,
    wave_events,
)
from alpha_tech_tracker.op_momentum_strategy.op_momentum_backtest import fetch_daily_bars
from alpha_tech_tracker.op_momentum_strategy.signal_stats import overnight_results

DRIVE_VARIANTS = ("drive long", "drive-trail", "drive + re-entry", "drive-trail + re-entry")
SHORT_LEGS = ("drive short + re-entry", "overnight short")
TRAIL_SETTING = (7, 0.382, 1.5)
REENTRY_LATEST = time(15, 0)
OVERNIGHT_ENTRY = time(15, 55)
GATE_TICKER, GATE_MA = "QQQ", 50
DAILY_HISTORY_DAYS = 420
WARMUP_DAYS = 32


def trail_reentry(bars):
    """The monitor with --drive-trail --drive-reentry on one session's event bars: drive long with the stop raised to
    each new dip low; after a stop-out one re-entry on a close back above the stop that was hit (before
    REENTRY_LATEST), stop the low since the stop-out, also trailed. Trades: (entry_time, entry, exit_time, exit, reason).
    """
    if not bars or not bars[0]["close"] > bars[0]["open"]:
        return []
    trades, reentered, level, low_since = [], False, None, None
    position = {"time": bars[0]["time"], "entry": bars[0]["close"], "stop": bars[0]["low"]}
    for i, bar in enumerate(bars[1:], start=1):
        last = i == len(bars) - 1
        if position:
            if bar["low"] <= position["stop"]:
                trades.append((position["time"], position["entry"], bar["time"], min(bar["open"], position["stop"]),
                               "stop"))
                level, low_since, position = position["stop"], bar["low"], None
                continue
            if bar["turn"] == "up":
                position["stop"] = max(position["stop"], bar["dip_low"])
            if last:
                trades.append((position["time"], position["entry"], bar["time"], bar["close"], "close"))
                position = None
            continue
        if level is None:
            continue
        low_since = min(low_since, bar["low"])
        if reentered or last or bar["time"].time() >= REENTRY_LATEST:
            continue
        if bar["close"] > level:
            reentered, position = True, {"time": bar["time"], "entry": bar["close"], "stop": low_since}
    return trades


def _event_bars(frame):
    return {d: [{"time": t, "open": r.open, "high": r.high, "low": r.low, "close": r.close, "turn": None,
                 "dip_low": None, "low_stop": None, "high_signal": False} for t, r in g.iterrows()]
            for d, g in frame.groupby(frame.index.date)}


def ticker_legs(job):
    """Every leg's trades for one ticker over start..end: DataFrame(ticker, day, leg, pct), and its buy-and-hold %."""
    ticker, start, end, cost_bps = job
    bars, _ = load_rider_bars(ticker, start - timedelta(days=WARMUP_DAYS), end, DataFeed.SIP, 20)
    daily = fetch_daily_bars([ticker], start - timedelta(days=DAILY_HISTORY_DAYS), end)[ticker]
    closes = pd.Series([float(c) for c in daily["Close"]], index=[pd.Timestamp(d).date() for d in daily.index])
    sessions = sorted(set(bars.index.date))
    windows = earnings_windows(load_releases(ticker), sessions)
    rows = []

    def add(day, leg, pct):
        if start <= day <= end:
            rows.append((ticker, day, leg, pct))

    for day, evs in _event_bars(bars).items():
        for _, e, _, x, _ in ride("drive", evs):
            add(day, "drive long", (x - e) / e * 100 - cost_bps / 100)
    for day, evs in wave_events(bars, *TRAIL_SETTING).items():
        for leg, rider in (("drive-trail", lambda b: ride("drive-trail", b)),
                           ("drive + re-entry", lambda b: ride("reenter-stoplevel", b)),
                           ("drive-trail + re-entry", trail_reentry)):
            for _, e, _, x, _ in rider(evs):
                add(day, leg, (x - e) / e * 100 - cost_bps / 100)
    flipped, k = flip_bars(bars)
    for day, evs in _event_bars(flipped).items():
        for _, e, _, x, _ in ride("reenter-stoplevel-nostop", evs):
            add(day, "drive short + re-entry", short_pct(k, e, x, cost_bps))
    for r in overnight_results(ticker, bars, closes, windows, {d for d in sessions if start <= d <= end}, "ma200"):
        if r.pct is not None:
            add(r.day, "overnight long", r.pct - cost_bps / 100)
    for today, nxt in zip(sessions, sessions[1:]):
        day_bars = bars[bars.index.date == today]
        last = day_bars[day_bars.index.time == OVERNIGHT_ENTRY]
        if last.empty or in_earnings_window({"signal": "overnight_long", "time": last.index[0]}, windows):
            continue
        entry, cover = float(last["close"].iloc[0]), float(bars[bars.index.date == nxt]["open"].iloc[0])
        add(today, "overnight short", (entry - cover) / entry * 100 - cost_bps / 100)
    held = bars[(bars.index.date >= start) & (bars.index.date <= end)]
    buy_hold = (held["close"].iloc[-1] / held["open"].iloc[0] - 1) * 100
    return pd.DataFrame(rows, columns=["ticker", "day", "leg", "pct"]), ticker, buy_hold


def gated_sessions(start, end):
    """Sessions whose previous QQQ close was below its GATE_MA-day MA (the monitor's short gate)."""
    daily = fetch_daily_bars([GATE_TICKER], start - timedelta(days=DAILY_HISTORY_DAYS), end)[GATE_TICKER]
    closes = pd.Series([float(c) for c in daily["Close"]], index=[pd.Timestamp(d).date() for d in daily.index])
    context = daily_context(closes).shift(1)
    return {d for d, r in context.iterrows() if pd.notna(r[f"ma{GATE_MA}"]) and r["close"] < r[f"ma{GATE_MA}"]}


def plans():
    """{plan name: function(trades frame with leg / gated columns) -> mask}."""
    def gated_short(x):
        return x["leg"].isin(SHORT_LEGS) & x["gated"]

    def overnight_long(x):
        return (x["leg"] == "overnight long") & ~x["gated"]

    out = {}
    for variant in DRIVE_VARIANTS:
        out[f"monitor rules with {variant}"] = (lambda v: lambda x: (x["leg"] == v) | gated_short(x) | overnight_long(x))(variant)
    for variant in DRIVE_VARIANTS:
        out[f"{variant} only"] = (lambda v: lambda x: x["leg"] == v)(variant)
        out[f"{variant} + gated drive short"] = (lambda v: lambda x: (x["leg"] == v) | (
            (x["leg"] == "drive short + re-entry") & x["gated"]))(variant)
    out["monitor with --short-setups drive (overnight long every allowed night)"] = lambda x: (
        (x["leg"] == "drive long") | ((x["leg"] == "drive short + re-entry") & x["gated"]) | (x["leg"] == "overnight long"))
    out["overnight long only (every allowed night)"] = lambda x: x["leg"] == "overnight long"
    out["drive long + overnight long (no shorts)"] = lambda x: x["leg"].isin(["drive long", "overnight long"])
    return out


def summarize(trades, capital):
    """trades (with a dollars column) -> trades, won %, P&L $, return %, max drawdown $ of the daily P&L."""
    if trades.empty:
        return {"trades": 0, "won %": float("nan"), "P&L $": 0.0, "return %": 0.0, "max DD $": 0.0}
    curve = trades.groupby("day")["dollars"].sum().sort_index().cumsum()
    return {"trades": len(trades), "won %": 100 * (trades["pct"] > 0).mean(), "P&L $": trades["dollars"].sum(),
            "return %": trades["dollars"].sum() / capital * 100,
            "max DD $": float((curve - curve.cummax().clip(lower=0)).min())}


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("tickers", nargs="+")
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, help="Default: the last completed session")
    parser.add_argument("--capital", type=float, default=10000.0, help="Split equally across the tickers")
    parser.add_argument("--cost-bps", type=float, default=5.0)
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    end = clamp_end_for_sip(args.end or date.today(), DataFeed.SIP)
    with ProcessPoolExecutor(max_workers=min(8, len(args.tickers))) as pool:
        results = list(pool.map(ticker_legs, [(t, args.start, end, args.cost_bps) for t in args.tickers]))
    trades = pd.concat([r[0] for r in results])
    buy_hold = {r[1]: r[2] for r in results}
    gated = gated_sessions(args.start, end)
    trades["gated"] = trades["day"].isin(gated)
    trades["dollars"] = trades["pct"] / 100 * args.capital / len(args.tickers)
    pd.set_option("display.width", 250)
    print(f"{len(args.tickers)} tickers, {args.start} to {end}, ${args.capital:,.0f} (${args.capital / len(args.tickers):,.0f} "
          f"per ticker per trade), {args.cost_bps:g} bps; gated sessions: {len({d for d in gated if args.start <= d <= end})}")
    table = pd.DataFrame({name: summarize(trades[mask(trades)], args.capital) for name, mask in plans().items()}).T
    print(table.to_string(float_format=lambda v: f"{v:+,.1f}"))
    average = sum(buy_hold.values()) / len(buy_hold)
    print(f"buy & hold, equal weight: {average:+.1f}% ({', '.join(f'{t} {v:+.1f}%' for t, v in buy_hold.items())})")
    monitor = trades[plans()["monitor rules with drive long"](trades)]
    print("\nmonitor rules, $ by ticker and leg:")
    print(monitor.pivot_table(index="ticker", columns="leg", values="dollars", aggfunc="sum", margins=True)
          .round(0).to_string())
    print("\nevery leg on every session it fired, $ by ticker:")
    print(trades.pivot_table(index="ticker", columns="leg", values="dollars", aggfunc="sum").round(0).to_string())


if __name__ == "__main__":
    main()

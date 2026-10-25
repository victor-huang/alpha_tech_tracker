"""Wave riders: long setups that try to ride several intraday up waves, scored by the share of the daily range caught.

The wave model (alpha_tech_tracker/wave.py) is replayed bar by bar per session (waves reset at the open) with
looser settings than analyze_bars' defaults: a turn needs the wave to be `min_length` bars long (default model: 7),
to have moved `min_ranges` x the trailing 78-bar average bar range % (default 2), and price to retrace `bounce` of it
(default 0.236). A turn up is confirmed on the bar whose close completes that retrace after a down wave; the dip's
low is the down wave's lowest wick. Riders (long only, entries at a bar's close, stops checked on bar lows and
filled at the stop or a lower open, flat at the session's last bar, `--cost-bps` per round trip):

  drive        baseline: first bar green -> buy its close, stop its low, hold to the close (setup report's drive long)
  turn         buy every confirmed turn up (stop the dip's low); sell the next confirmed turn down
  higher-low   as turn, but only when the dip's low is above the session's previous dip low
  drive-ride   drive, sold at the first confirmed turn down; then higher-low for the rest of the day
  trail        buy drive or any turn up; stop raised to each new dip low; no exit on a turn down; re-enter on turns up
  drive-trail  drive only, stop raised to each new dip low

Reversal riders take their entries from the wave setup monitor's reversal alerts (reversal_watch.ReversalWatch on
its default waves): a LOW? signal (piercing, push or a confirmed long tail near a down wave's low) buys the bar's
close with the stop at the wave's low so far (or the bar's low if lower); a HIGH? signal is the mirror at highs.

  reversal-close       buy LOW?, stop only, hold to the close
  reversal-trail       buy LOW?, stop raised to each new confirmed dip low
  reversal-high        buy LOW?, sell the first HIGH?
  reversal-trail-high  reversal-trail, also selling the first HIGH?
  drive-reversal-trail one position: drive, and when flat buy LOW?; stop raised to each new dip low
  drive + reversal-trail, drive-trail + reversal-trail
                       two independent legs (two positions at once at most), their trades added together

Day type at 10:30 (from the first DAYTYPE_BARS bars): net move = (10:25 bar close - open) / ADR, efficiency = |net
move| / the path travelled (sum of |close-to-close| moves). A trend-up day has net move >= N and efficiency >= E.

  daytype-cut E N      drive, sold at the 10:25 bar's close unless it is a trend-up day
  daytype-switch E N   daytype-cut, and on other days reversal-trail entries after 10:30
  daytype-trend E N    trend-up day: hold the drive, or buy the 10:25 close (stop the morning low) if not in;
                       other days: reversal-trail entries after 10:30

Limit entries at levels known one bar ahead (a buy limit at the previous bar's level, filled when the bar trades down
to it, at the level or a lower open; only if the previous close was above it; 10:00-15:00, at most
LIMIT_MAX_PER_DAY a day; the stop `buffer` x ADR below the level; a bar that reaches both counts as stopped; stop
raised to each new dip low; flat at the close):

  limit-vwap b         the session VWAP
  limit-ma20 b         the 5-min MA20, while it is above its level 3 bars earlier
  limit-dip b          the last confirmed dip low + LIMIT_DIP_OFFSET x ADR (a retest of the dip)

Re-entry after a drive long stop-out (re-entries until REENTER_LATEST, held to the close):

  reenter-stoplevel         re-buy the first close back above the stop-out level (the first bar's low); stop at
                            the low since the stop-out; once
  reenter-stoplevel-x       the same, as often as it stops out again
  reenter-stoplevel-nostop  re-buy above the stop-out level once, no stop
  reenter-entry             re-buy the first close back above the original entry (Finding 28's rule); stop at the
                            low since the stop-out; once

Score: dollars per share caught per session / the ADR known before the open (mean of the previous `--adr-sessions`
sessions' high - low), sessions without a trade counting 0. Settings are chosen on the calibration period and
reported on the test period.

  python -m alpha_tech_tracker.op_momentum_strategy.analysis_scripts.wave_rider --ticker SNDK \\
    --calibration 2025-02-14:2025-12-31 --test 2026-01-02:2026-10-23
"""

import argparse
import itertools
from concurrent.futures import ProcessPoolExecutor
from datetime import date
from pathlib import Path

import pandas as pd
from alpaca.data.enums import DataFeed

from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.wave_risk_reward import BAR_INTERVAL, BARS_PER_SESSION
from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.wave_risk_reward_scan import _load_bars
from alpha_tech_tracker.op_momentum_strategy.op_momentum_backtest import fetch_bars, fetch_daily_bars
from alpha_tech_tracker.op_momentum_strategy.reversal_watch import ReversalWatch
from alpha_tech_tracker.wave import Wave

DEFAULT_OUT_ROOT = Path(__file__).resolve().parents[1] / "backtest_result" / "wave_rider"
RIDER_RULES = {
    "drive": {"drive"},
    "turn": {"turn_entry", "sell_turn"},
    "higher-low": {"turn_entry", "higher_low", "sell_turn"},
    "drive-ride": {"drive", "turn_entry", "higher_low", "sell_turn"},
    "trail": {"drive", "turn_entry", "trail"},
    "drive-trail": {"drive", "trail"},
    "reversal-close": {"reversal_entry"},
    "reversal-trail": {"reversal_entry", "trail"},
    "reversal-high": {"reversal_entry", "sell_high"},
    "reversal-trail-high": {"reversal_entry", "trail", "sell_high"},
    "drive-reversal-trail": {"drive", "reversal_entry", "trail"},
}
COMBOS = {"drive + reversal-trail": ("drive", "reversal-trail"),
          "drive-trail + reversal-trail": ("drive-trail", "reversal-trail")}
DAYTYPE_BARS = 12
DAYTYPE_EFFICIENCY = (0.25, 0.4)
DAYTYPE_NET = (0.0, 0.2)
DAYTYPE_RIDERS = tuple(f"daytype-{mode} E{e:g} N{n:g}" for mode in ("cut", "switch", "trend")
                       for e in DAYTYPE_EFFICIENCY for n in DAYTYPE_NET)
LIMIT_BUFFERS = (0.05, 0.1, 0.2)
LIMIT_MAX_PER_DAY = 2
LIMIT_DIP_OFFSET = 0.05
LIMIT_WINDOW = ("10:00", "15:00")
LIMIT_RIDERS = tuple(f"limit-{kind} b{b:g}" for kind in ("vwap", "ma20", "dip") for b in LIMIT_BUFFERS)
REENTER_RIDERS = {"reenter-stoplevel": ("stop level", "low", 1), "reenter-stoplevel-x": ("stop level", "low", None),
                  "reenter-stoplevel-nostop": ("stop level", None, 1), "reenter-entry": ("entry", "low", 1)}
REENTER_LATEST = "15:00"
RIDERS = tuple(RIDER_RULES) + tuple(COMBOS) + DAYTYPE_RIDERS + LIMIT_RIDERS + tuple(REENTER_RIDERS)
MIN_LENGTHS = (3, 5, 7)
BOUNCES = (0.236, 0.382)
MIN_RANGES = (1.5, 2.0, 3.0)
DEFAULT_SETTING = (7, 0.236, 2.0)


def reversal_signals(bars):
    """{bar time: {"low_stop": stop for a LOW? signal or None, "high": HIGH? signal}} from ReversalWatch."""
    watch = ReversalWatch("rider")
    out = {}
    for stamp, row in bars.iterrows():
        bar = {k: float(row[k]) for k in ("open", "high", "low", "close")}
        signals = watch.update(stamp, bar)
        lows = [s.extreme for s in signals if s.side == "bottom"]
        out[stamp] = {"low_stop": min(min(lows), bar["low"]) if lows else None,
                      "high": any(s.side == "top" for s in signals)}
    return out


def wave_events(bars, min_length, bounce, min_ranges, reversals=None):
    """Per session, the bars with the wave turns confirmed on them: {"turn": "up"/"down"/None, "dip_low"}, plus the
    reversal signals (`reversals` from reversal_signals) as "low_stop" / "high_signal"."""
    range_pct = ((bars["high"] - bars["low"]) / bars["close"]).rolling(BARS_PER_SESSION, min_periods=1).mean()
    sessions = {}
    wave = None
    for stamp, row in bars.iterrows():
        bar = {"open": float(row["open"]), "high": float(row["high"]), "low": float(row["low"]),
               "close": float(row["close"])}
        min_change = min_ranges * float(range_pct[stamp])
        signal = (reversals or {}).get(stamp, {})
        event = {"time": stamp, **bar, "turn": None, "dip_low": None, "low_stop": signal.get("low_stop"),
                 "high_signal": signal.get("high", False)}
        for column in ("ma_20", "vwap", "adr"):
            if column in row:
                event[column] = float(row[column])
        if wave is None or stamp.date() != wave.df.index[-1].date():
            wave = _wave(stamp, bar, min_change, min_length, bounce)
        else:
            wave.minimum_wave_price_change = min_change
            before = wave.direction()
            new_wave = wave.count(stamp, bar, time_increment=BAR_INTERVAL)
            if new_wave:
                new_wave.minimum_wave_length, new_wave.bounce_threshold = min_length, bounce
                if before == "down":
                    event["turn"], event["dip_low"] = "up", float(wave.df["low"].min())
                elif before == "up":
                    event["turn"] = "down"
                wave = new_wave
        sessions.setdefault(stamp.date(), []).append(event)
    return sessions


def _wave(stamp, bar, min_change, min_length, bounce):
    wave = Wave(stamp, bar, minimum_wave_price_change=min_change)
    wave.minimum_wave_length, wave.bounce_threshold = min_length, bounce
    return wave


def ride(rider, bars):
    """Trades of one rider over one session's event bars: (entry_time, entry, exit_time, exit, reason)."""
    if rider.startswith("daytype-"):
        mode, efficiency, net = rider.split()
        return ride_daytype(mode[len("daytype-"):], float(efficiency[1:]), float(net[1:]), bars)
    if rider in REENTER_RIDERS:
        return ride_reenter(*REENTER_RIDERS[rider], bars)
    if rider.startswith("limit-"):
        kind, buffer = rider.split()
        return ride_limit(kind[len("limit-"):], float(buffer[1:]), bars)
    if rider in COMBOS:
        return [t for leg in COMBOS[rider] for t in ride(leg, bars)]
    rules = RIDER_RULES[rider]
    trades = []
    position = None
    previous_dip = last_dip = None
    for i, bar in enumerate(bars):
        last = i == len(bars) - 1
        exited = False
        if position and bar["low"] <= position["stop"]:
            trades.append((position["time"], position["entry"], bar["time"], min(bar["open"], position["stop"]), "stop"))
            position, exited = None, True
        if bar["turn"] == "up":
            previous_dip, last_dip = last_dip, bar["dip_low"]
        if position:
            if bar["turn"] == "up" and "trail" in rules:
                position["stop"] = max(position["stop"], bar["dip_low"])
            reason = ("close" if last else "turn down" if bar["turn"] == "down" and "sell_turn" in rules
                      else "high signal" if bar["high_signal"] and "sell_high" in rules else None)
            if reason:
                trades.append((position["time"], position["entry"], bar["time"], bar["close"], reason))
                position, exited = None, True
        if position or exited or last:
            continue
        if i == 0:
            if "drive" in rules and bar["close"] > bar["open"]:
                position = {"time": bar["time"], "entry": bar["close"], "stop": bar["low"]}
            continue
        if "reversal_entry" in rules and bar["low_stop"] is not None and bar["low_stop"] < bar["close"]:
            position = {"time": bar["time"], "entry": bar["close"], "stop": bar["low_stop"]}
            continue
        if "turn_entry" not in rules or bar["turn"] != "up" or bar["dip_low"] >= bar["close"]:
            continue
        if "higher_low" in rules and previous_dip is not None and bar["dip_low"] <= previous_dip:
            continue
        position = {"time": bar["time"], "entry": bar["close"], "stop": bar["dip_low"]}
    return trades


def day_type(bars):
    """(net move in ADR, efficiency) over the first DAYTYPE_BARS bars, or None for a short session."""
    if len(bars) <= DAYTYPE_BARS or not bars[0].get("adr"):
        return None
    morning = bars[:DAYTYPE_BARS]
    path = abs(morning[0]["close"] - morning[0]["open"]) + sum(
        abs(b["close"] - a["close"]) for a, b in zip(morning, morning[1:]))
    move = morning[-1]["close"] - morning[0]["open"]
    return move / bars[0]["adr"], abs(move) / path if path else 0.0


def ride_daytype(mode, efficiency_cut, net_cut, bars):
    """Drive until 10:30, then hold it on a trend-up day or (switch / trend) trade reversal-trail entries."""
    kind = day_type(bars)
    if kind is None:
        return ride("drive", bars)
    trend = kind[0] >= net_cut and kind[1] >= efficiency_cut
    decision = DAYTYPE_BARS - 1
    trades, position = [], None
    for i, bar in enumerate(bars):
        last = i == len(bars) - 1
        if position and bar["low"] <= position["stop"]:
            trades.append((position["time"], position["entry"], bar["time"], min(bar["open"], position["stop"]), "stop"))
            position = None
        elif position and (last or (i == decision and not trend)):
            trades.append((position["time"], position["entry"], bar["time"], bar["close"],
                           "close" if last else "chop at 10:30"))
            position = None
        if i == 0 and bar["close"] > bar["open"]:
            position = {"time": bar["time"], "entry": bar["close"], "stop": bar["low"]}
        if i == decision and trend and mode == "trend" and position is None and not last:
            position = {"time": bar["time"], "entry": bar["close"], "stop": min(b["low"] for b in bars[:DAYTYPE_BARS])}
        if i == decision:
            break
    if trend or mode == "cut":
        if position:
            for bar in bars[decision + 1:]:
                if bar["low"] <= position["stop"]:
                    trades.append((position["time"], position["entry"], bar["time"],
                                   min(bar["open"], position["stop"]), "stop"))
                    return trades
            trades.append((position["time"], position["entry"], bars[-1]["time"], bars[-1]["close"], "close"))
        return trades
    return trades + ride("reversal-trail", bars[decision + 1:])


def ride_reenter(trigger, stop_mode, max_reentries, bars):
    """Drive long; after a stop-out, re-buy a close back above the stop-out level (or the original entry)."""
    if not bars or not bars[0]["close"] > bars[0]["open"]:
        return []
    latest = pd.Timestamp(REENTER_LATEST).time()
    first = bars[0]
    level = first["low"] if trigger == "stop level" else first["close"]
    trades, reentries = [], 0
    position = {"time": first["time"], "entry": first["close"], "stop": first["low"]}
    low_since_stop = None
    for i, bar in enumerate(bars[1:], start=1):
        last = i == len(bars) - 1
        if position:
            if position["stop"] is not None and bar["low"] <= position["stop"]:
                exit_price = min(bar["open"], position["stop"])
                trades.append((position["time"], position["entry"], bar["time"], exit_price, "stop"))
                position, low_since_stop = None, bar["low"]
            elif last:
                trades.append((position["time"], position["entry"], bar["time"], bar["close"], "close"))
                position = None
            continue
        low_since_stop = min(low_since_stop, bar["low"])
        if last or bar["time"].time() >= latest or (max_reentries is not None and reentries >= max_reentries):
            continue
        if bar["close"] > level:
            reentries += 1
            stop = low_since_stop if stop_mode == "low" else None
            position = {"time": bar["time"], "entry": bar["close"], "stop": stop, "reentry": True}
    return trades


def ride_limit(kind, buffer, bars):
    """Buy limits at a level known one bar ahead, tight stop below it, stop raised to each new dip low."""
    trades, position, last_dip, entries = [], None, None, 0
    start, end = (pd.Timestamp(t).time() for t in LIMIT_WINDOW)
    for i, bar in enumerate(bars):
        last = i == len(bars) - 1
        exited = False
        if position and bar["low"] <= position["stop"]:
            trades.append((position["time"], position["entry"], bar["time"], min(bar["open"], position["stop"]), "stop"))
            position, exited = None, True
        if bar["turn"] == "up":
            last_dip = bar["dip_low"]
            if position:
                position["stop"] = max(position["stop"], bar["dip_low"])
        if position and last:
            trades.append((position["time"], position["entry"], bar["time"], bar["close"], "close"))
            position, exited = None, True
        if position or exited or last or i == 0 or entries >= LIMIT_MAX_PER_DAY:
            continue
        if not start <= bar["time"].time() < end:
            continue
        previous, adr = bars[i - 1], bar.get("adr")
        if not adr:
            continue
        if kind == "vwap":
            level = previous.get("vwap")
        elif kind == "ma20":
            level = previous.get("ma_20")
            if i < 4 or level is None or not level > bars[i - 4].get("ma_20", float("inf")):
                continue
        else:
            level = None if last_dip is None else last_dip + LIMIT_DIP_OFFSET * adr
        if level is None or level != level or not previous["close"] > level or bar["low"] > level:
            continue
        fill = min(bar["open"], level)
        stop = (last_dip if kind == "dip" else level) - buffer * adr
        if fill <= stop:
            continue
        entries += 1
        if bar["low"] <= stop:
            trades.append((bar["time"], fill, bar["time"], stop, "stop"))
            continue
        position = {"time": bar["time"], "entry": fill, "stop": stop}
    return trades


def day_type_study(events, adr, periods):
    """Do the 10:30 day-type measures predict the rest of the day? Quintile tables per period."""
    rows = []
    for session, bars in events.items():
        kind = day_type(bars)
        if kind is None or not adr.get(session):
            continue
        morning = bars[:DAYTYPE_BARS]
        high = max(b["high"] for b in morning)
        run_up = high - morning[0]["open"]
        after = ride("reversal-trail", bars[DAYTYPE_BARS:])
        rows.append({"session": session, "net_move": kind[0], "efficiency": kind[1],
                     "turns": sum(b["turn"] is not None for b in morning),
                     "pullback": (high - morning[-1]["close"]) / run_up if run_up > 0 else 1.0,
                     "morning_range": (high - min(b["low"] for b in morning)) / adr[session],
                     "hold_rest": (bars[-1]["close"] - morning[-1]["close"]) / adr[session],
                     "reversal_rest": sum(x - e for _, e, _, x, _ in after) / adr[session]})
    frame = pd.DataFrame(rows)
    lines = []
    for name, sessions in periods.items():
        part = frame[frame["session"].isin(sessions)]
        lines += [f"### {name}: {len(part)} sessions (rest of day in ADR: long from the 10:25 close, and the "
                  "reversal-trail leg after 10:30)", ""]
        for feature in ("net_move", "efficiency", "pullback", "turns", "morning_range"):
            buckets = pd.qcut(part[feature].rank(method="first"), 5, labels=["q1 low", "q2", "q3", "q4", "q5 high"])
            table = part.groupby(buckets).agg(cut=(feature, "max"), hold_rest=("hold_rest", "mean"),
                                              reversal_rest=("reversal_rest", "mean"), sessions=("hold_rest", "size"))
            ranks = part[[feature, "hold_rest", "reversal_rest"]].rank()
            lines += [f"{feature} (rank corr with hold_rest {ranks[feature].corr(ranks['hold_rest']):+.2f},"
                      f" with reversal_rest {ranks[feature].corr(ranks['reversal_rest']):+.2f})",
                      table.T.to_string(float_format=lambda x: f"{x:.3f}"), ""]
    return lines


def score(trades_by_session, adr, sessions, cost_bps):
    """Totals over `sessions`: trades, win rate, summed %, mean ADR capture per session."""
    pct, capture, wins, count = 0.0, [], 0, 0
    for session in sessions:
        caught = 0.0
        for _, entry, _, exit_price, _ in trades_by_session.get(session, []):
            net = (exit_price - entry) / entry * 100 - cost_bps / 100
            pct += net
            caught += net / 100 * entry
            wins += net > 0
            count += 1
        capture.append(caught / adr[session] if adr.get(session) else 0.0)
    return {"trades": count, "win": wins / count if count else 0.0, "total_pct": pct,
            "capture": sum(capture) / len(capture) if capture else 0.0, "per_session": len(sessions)}


def _run_setting(job):
    bars, setting, riders, reversals = job
    events = wave_events(bars, *setting, reversals=reversals)
    return setting, {r: {s: ride(r, bars_) for s, bars_ in events.items()} for r in riders}, events


def split_factors(bars, daily_closes):
    """{session: divisor} for sessions whose 5-min prices are not split-adjusted (off from the split-adjusted daily
    close by a whole split ratio, e.g. 4 before a 4-for-1 split, 1/10 before a 1-for-10 reverse split)."""
    last = bars.groupby(bars.index.date)["close"].last()
    factors = {}
    for session, close in last.items():
        daily = daily_closes.get(session)
        if not daily:
            continue
        ratio = close / daily
        whole = round(ratio) if ratio >= 1 else 1 / round(1 / ratio)
        if whole != 1 and abs(ratio / whole - 1) < 0.02:
            factors[session] = whole
    return factors


def load_rider_bars(ticker, start, end, feed, adr_sessions):
    """Regular-hours bars with the 5-min MA20, the session VWAP and the session's ADR, split-adjusted."""
    bars = _load_bars(ticker, start, end, feed)
    raw = fetch_bars([ticker], start - pd.Timedelta(days=10), end, allow_intraday=True, feed=feed)[ticker]
    raw = raw.reindex(bars.index)
    days = bars.index.date
    weighted = (raw["Vwap"] * raw["Volume"]).groupby(days).cumsum()
    bars["vwap"] = weighted / raw["Volume"].groupby(days).cumsum()
    daily = fetch_daily_bars([ticker], bars.index[0].date(), end)[ticker]
    column = "Close" if "Close" in daily.columns else "close"
    factors = split_factors(bars, {pd.Timestamp(d).date(): float(c) for d, c in daily[column].items()})
    if factors:
        divisor = pd.Series([factors.get(d, 1) for d in days], index=bars.index)
        for name in ("open", "high", "low", "close", "vwap"):
            bars[name] = bars[name] / divisor
        bars["ma_20"] = bars["close"].rolling(20, min_periods=20).mean()
    bars = bars[(bars.index.date >= start) & (bars.index.date <= end)]
    adr = session_adr(bars, adr_sessions)
    bars["adr"] = [adr.get(d) for d in bars.index.date]
    return bars[["open", "high", "low", "close", "ma_20", "vwap", "adr"]], adr


def session_adr(bars, adr_sessions):
    days = pd.Series(bars.index.date, index=bars.index)
    daily = bars.groupby(days.values).agg(high=("high", "max"), low=("low", "min"))
    return (daily["high"] - daily["low"]).rolling(adr_sessions, min_periods=adr_sessions).mean().shift(1).to_dict()


def _period(text):
    start, end = text.split(":")
    return date.fromisoformat(start), date.fromisoformat(end)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--calibration", type=_period, required=True, help="START:END the settings are chosen on")
    parser.add_argument("--test", type=_period, required=True, help="START:END reported")
    parser.add_argument("--cost-bps", type=float, default=5.0)
    parser.add_argument("--adr-sessions", type=int, default=20)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--feed", default="sip", choices=["sip", "iex"])
    parser.add_argument("--out-dir", help=f"Default: {DEFAULT_OUT_ROOT}/<ticker>")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    feed = DataFeed.SIP if args.feed == "sip" else DataFeed.IEX
    (cal_start, cal_end), (test_start, test_end) = args.calibration, args.test
    bars, adr = load_rider_bars(args.ticker, cal_start, test_end, feed, args.adr_sessions)
    days = sorted(set(bars.index.date))
    periods = {"calibration": [d for d in days if cal_start <= d <= cal_end and adr.get(d) == adr.get(d)],
               "test": [d for d in days if test_start <= d <= test_end]}
    settings = list(itertools.product(MIN_LENGTHS, BOUNCES, MIN_RANGES))
    reversals = reversal_signals(bars)
    rows = []
    study = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for setting, trades_by_rider, events in pool.map(_run_setting, [(bars, s, RIDERS, reversals) for s in settings]):
            if setting == DEFAULT_SETTING:
                study = day_type_study(events, adr, periods)
            for rider, by_session in trades_by_rider.items():
                row = {"rider": rider, "min_length": setting[0], "bounce": setting[1], "min_ranges": setting[2]}
                for name, sessions in periods.items():
                    for key, value in score(by_session, adr, sessions, args.cost_bps).items():
                        row[f"{name}_{key}"] = value
                rows.append(row)
    table = pd.DataFrame(rows)
    out_dir = Path(args.out_dir or DEFAULT_OUT_ROOT / args.ticker)
    out_dir.mkdir(parents=True, exist_ok=True)
    table.to_csv(out_dir / "grid.csv", index=False)

    columns = ["rider", "min_length", "bounce", "min_ranges", "calibration_trades", "calibration_win",
               "calibration_total_pct", "calibration_capture", "test_trades", "test_win", "test_total_pct",
               "test_capture"]
    fmt = {"calibration_win": "{:.0%}", "test_win": "{:.0%}"}

    def show(frame):
        frame = frame[columns].copy()
        for column, pattern in fmt.items():
            frame[column] = frame[column].map(pattern.format)
        return frame.to_string(index=False, float_format=lambda x: f"{x:.3f}")

    default = table[(table.min_length == DEFAULT_SETTING[0]) & (table.bounce == DEFAULT_SETTING[1])
                    & (table.min_ranges == DEFAULT_SETTING[2])]
    chosen = table.loc[table.groupby("rider")["calibration_capture"].idxmax()]
    lines = [f"# Wave riders: {args.ticker}, calibration {cal_start}..{cal_end} ({len(periods['calibration'])} "
             f"sessions), test {test_start}..{test_end} ({len(periods['test'])} sessions), {args.cost_bps:g} bps", "",
             "## Default wave settings (7 bars, 23.6%, 2 avg bars)", "", show(default), "",
             "## Each rider's best setting on the calibration period, with its test result", "",
             show(chosen.sort_values("calibration_capture", ascending=False)), "",
             "## Top 15 by calibration capture", "",
             show(table.sort_values("calibration_capture", ascending=False).head(15)), "",
             "## Day type at 10:30 vs the rest of the day (default wave settings)", ""] + study
    text = "\n".join(lines)
    (out_dir / "report.md").write_text(text)
    print(text)
    print(f"written to {out_dir}")


if __name__ == "__main__":
    main()

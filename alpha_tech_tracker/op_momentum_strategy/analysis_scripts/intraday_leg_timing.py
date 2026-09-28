"""Time-of-day profile of fast intraday legs on 5-min bars.

A leg starts at a bar's open and qualifies when price travels at least
`--min-move-adr` x the ticker's prior 20-session average intraday range within
`--impulse-bars` bars (default 3 = 15 min), without first giving back
`--retrace` of the distance. Once qualified the leg keeps running until price
retraces that fraction (default 20%) of its start-to-extreme distance.

Legs are grouped by the clock bucket they started in, and scored by what a
confirmation entry would have captured: buy/short the close of the bar that
qualified the leg, exit where the retracement triggers. `capture/session` folds
frequency and quality into one number, so it is the column that answers "when
is the best time to enter this ticker".

Bar-order caveat: 5-min OHLC hides whether a bar's high or low printed first.
With the default wick basis a leg ends on the first bar whose low (checked against
the prior extreme) or close (checked against the updated extreme) gives back the
retracement, so a spike that closes well off its high ends on its own bar.
`--retrace-basis close` measures on closes only, as a 5-min closing chart reads.
"""

import argparse
import csv
import statistics
from collections import OrderedDict
from datetime import date, time, timedelta
from pathlib import Path

from alpaca.data.enums import DataFeed

from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.ticker_stats_report import (
    MARKET_OPEN,
    clamp_end_for_sip,
)
from alpha_tech_tracker.op_momentum_strategy.op_momentum_backtest import fetch_bars

DEFAULT_TICKERS = ["SNDK", "APP", "NVDA", "LLY", "MRNA", "COIN", "HOOD"]
BAR_MINUTES = 5
ADR_SESSIONS = 20
DEFAULT_SESSIONS = 60
DEFAULT_BUCKET_MINUTES = 15
DEFAULT_IMPULSE_BARS = 3
DEFAULT_RETRACE = 0.20
DEFAULT_MIN_MOVE_ADR = 0.25
DEFAULT_MIN_LEGS = 5
ZONES = [
    ("open 30m", time(9, 30), time(10, 0)),
    ("morning", time(10, 0), time(11, 30)),
    ("midday", time(11, 30), time(13, 30)),
    ("afternoon", time(13, 30), time(15, 0)),
    ("power hour", time(15, 0), time(16, 0)),
]
CSV_FIELDS = [
    "ticker", "session", "direction", "bucket", "zone", "start_time", "confirm_time",
    "peak_time", "end_time", "start_price", "extreme_price", "move_usd", "move_pct",
    "adr_pct", "adr_multiple", "threshold_pct", "mins_to_confirm", "mins_to_peak",
    "mins_to_retrace", "retraced", "entry_price", "exit_price", "capture_pct",
]


def regular_sessions(bars):
    """(session date, regular-hours frame) for every session with at least two bars."""
    if bars.empty:
        return []
    sessions = []
    for session, frame in bars.groupby(bars.index.date):
        regular = frame[frame.index.time >= MARKET_OPEN]
        if len(regular) >= 2:
            sessions.append((session, regular))
    return sessions


def prior_session_adr(sessions, lookback=ADR_SESSIONS):
    """Map session -> mean (high-low)/open % of the `lookback` sessions before it.

    Uses the regular-hours range from the same 5-min bars the legs are measured on,
    and never the session's own range, so the threshold is known before the open.
    """
    ranges = []
    adr = {}
    for session, frame in sessions:
        if len(ranges) >= lookback:
            adr[session] = sum(ranges[-lookback:]) / lookback
        session_open = float(frame["Open"].iloc[0])
        if session_open:
            ranges.append(
                (float(frame["High"].max()) - float(frame["Low"].min())) / session_open * 100
            )
    return adr


def track_leg(opens, highs, lows, closes, start_idx, min_move_pct, impulse_bars, retrace_frac,
              close_basis=False):
    """Follow one up-leg from the open of `start_idx`.

    Down legs are passed in with prices negated (and highs/lows swapped) so one routine
    handles both sides. Returns None when the move does not reach `min_move_pct` within
    `impulse_bars` bars, or gives back `retrace_frac` before it does.

    `close_basis` measures the extreme, the threshold and the give-back on bar closes
    only, ignoring wicks.
    """
    start = opens[start_idx]
    scale = abs(start)
    if not scale:
        return None

    peaks = closes if close_basis else highs
    extreme, extreme_idx = start, start_idx
    confirm_idx = None
    end_idx, exit_price, retraced = len(opens) - 1, closes[-1], False
    for j in range(start_idx, len(opens)):
        give_back = extreme - retrace_frac * (extreme - start)
        # A bar's low may print before its high, so test it against the prior extreme.
        if not close_basis and j > start_idx and lows[j] <= give_back:
            end_idx, exit_price, retraced = j, min(opens[j], give_back), True
            break
        if peaks[j] > extreme:
            extreme, extreme_idx = peaks[j], j
        if confirm_idx is None:
            if (extreme - start) / scale * 100 >= min_move_pct:
                confirm_idx = j
            elif j - start_idx + 1 >= impulse_bars:
                return None
        give_back = extreme - retrace_frac * (extreme - start)
        if closes[j] <= give_back:
            end_idx, exit_price, retraced = j, closes[j], True
            break

    if confirm_idx is None:
        return None
    return {
        "start_idx": start_idx,
        "confirm_idx": confirm_idx,
        "extreme_idx": extreme_idx,
        "end_idx": end_idx,
        "start": start,
        "extreme": extreme,
        "entry": closes[confirm_idx],
        "exit": exit_price,
        "retraced": retraced,
    }


def bucket_start(stamp, bucket_minutes):
    """Clock time of the `bucket_minutes` bucket, anchored on the 09:30 open."""
    open_minutes = MARKET_OPEN.hour * 60 + MARKET_OPEN.minute
    elapsed = stamp.hour * 60 + stamp.minute - open_minutes
    floored = open_minutes + elapsed // bucket_minutes * bucket_minutes
    return time(floored // 60, floored % 60)


def zone_display(label):
    """'open 30m' -> 'open 30m 09:30-10:00'; unknown labels pass through."""
    for name, start, end in ZONES:
        if name == label:
            return f"{name} {start.strftime('%H:%M')}-{end.strftime('%H:%M')}"
    return str(label)


def zone_label(stamp):
    clock = time(stamp.hour, stamp.minute)
    for label, start, end in ZONES:
        if start <= clock < end:
            return label
    return None


def _describe_leg(leg, direction, stamps, bucket_minutes):
    sign = 1 if direction == "up" else -1
    bar = timedelta(minutes=BAR_MINUTES)
    start_price = sign * leg["start"]
    entry_price = sign * leg["entry"]
    move = leg["extreme"] - leg["start"]
    start_time = stamps[leg["start_idx"]]
    return {
        "direction": direction,
        "bucket": bucket_start(start_time, bucket_minutes),
        "zone": zone_label(start_time),
        "start_time": start_time,
        "confirm_time": stamps[leg["confirm_idx"]] + bar,
        "peak_time": stamps[leg["extreme_idx"]] + bar,
        "end_time": stamps[leg["end_idx"]] + bar,
        "start_price": start_price,
        "extreme_price": sign * leg["extreme"],
        "move_usd": move,
        "move_pct": move / start_price * 100,
        "mins_to_confirm": (leg["confirm_idx"] - leg["start_idx"] + 1) * BAR_MINUTES,
        "mins_to_peak": (leg["extreme_idx"] - leg["start_idx"] + 1) * BAR_MINUTES,
        "mins_to_retrace": (leg["end_idx"] - leg["start_idx"] + 1) * BAR_MINUTES,
        "retraced": leg["retraced"],
        "entry_price": entry_price,
        "exit_price": sign * leg["exit"],
        "capture_pct": (leg["exit"] - leg["entry"]) / entry_price * 100,
    }


def find_session_legs(frame, min_move_pct, impulse_bars=DEFAULT_IMPULSE_BARS,
                      retrace_frac=DEFAULT_RETRACE, bucket_minutes=DEFAULT_BUCKET_MINUTES,
                      close_basis=False):
    """Every non-overlapping up and down leg in one session, ordered by start time.

    Scanning resumes on the bar after a leg ends, so a single move is counted once
    per direction even though several nearby bars could each have started it.
    """
    stamps = frame.index
    o, h, l, c = (frame[col].to_numpy(dtype=float) for col in ("Open", "High", "Low", "Close"))
    views = {"up": (o, h, l, c), "down": (-o, -l, -h, -c)}

    legs = []
    for direction, (opens, highs, lows, closes) in views.items():
        idx = 0
        while idx < len(opens):
            leg = track_leg(
                opens, highs, lows, closes, idx, min_move_pct, impulse_bars, retrace_frac,
                close_basis,
            )
            if leg is None:
                idx += 1
                continue
            legs.append(_describe_leg(leg, direction, stamps, bucket_minutes))
            idx = leg["end_idx"] + 1
    return sorted(legs, key=lambda row: row["start_time"])


def collect_ticker_legs(bars, sessions, min_move_adr, min_move_pct, impulse_bars,
                        retrace_frac, bucket_minutes, close_basis=False):
    """Legs across the trailing `sessions` that have a full ADR lookback behind them."""
    frames = regular_sessions(bars)
    adr = prior_session_adr(frames)
    scored = [(session, frame) for session, frame in frames if adr.get(session)][-sessions:]

    legs = []
    for session, frame in scored:
        threshold = max(min_move_adr * adr[session], min_move_pct)
        for leg in find_session_legs(
            frame, threshold, impulse_bars, retrace_frac, bucket_minutes, close_basis
        ):
            leg.update(
                session=session,
                adr_pct=adr[session],
                threshold_pct=threshold,
                adr_multiple=leg["move_pct"] / adr[session],
            )
            legs.append(leg)
    return legs, len(scored)


def summarize_group(legs, session_count):
    if not legs or not session_count:
        return None
    captures = [leg["capture_pct"] for leg in legs]
    return {
        "legs": len(legs),
        "up": sum(1 for leg in legs if leg["direction"] == "up"),
        "down": sum(1 for leg in legs if leg["direction"] == "down"),
        "session_hit_pct": len({leg["session"] for leg in legs}) / session_count * 100,
        "median_move_pct": statistics.median(leg["move_pct"] for leg in legs),
        "median_move_usd": statistics.median(leg["move_usd"] for leg in legs),
        "median_adr_multiple": statistics.median(leg["adr_multiple"] for leg in legs),
        "median_mins_to_peak": statistics.median(leg["mins_to_peak"] for leg in legs),
        "median_mins_to_retrace": statistics.median(leg["mins_to_retrace"] for leg in legs),
        "unretraced_pct": sum(1 for leg in legs if not leg["retraced"]) / len(legs) * 100,
        "median_capture_pct": statistics.median(captures),
        "capture_win_pct": sum(1 for value in captures if value > 0) / len(captures) * 100,
        "capture_per_session_pct": sum(captures) / session_count,
    }


def summarize_by(legs, session_count, key):
    groups = OrderedDict()
    for leg in sorted(legs, key=lambda row: row["start_time"].time()):
        groups.setdefault(leg[key], []).append(leg)
    if key == "zone":
        order = [label for label, _, _ in ZONES]
        groups = OrderedDict((label, groups[label]) for label in order if label in groups)
    return OrderedDict(
        (name, summarize_group(group, session_count)) for name, group in groups.items()
    )


def best_group(summary, min_legs):
    """Group with the highest capture per session among those with enough legs."""
    eligible = [(name, row) for name, row in summary.items() if row["legs"] >= min_legs]
    if not eligible:
        return None, None
    return max(eligible, key=lambda pair: pair[1]["capture_per_session_pct"])


def _label(name):
    return name.strftime("%H:%M") if isinstance(name, time) else zone_display(name)


def _print_group_table(title, summary):
    print(f"\n-- {title} --")
    print(
        f"{'start':>22} {'legs':>5} {'up/dn':>7} {'days hit':>9} {'med move':>9}"
        f" {'med $':>8} {'med xADR':>9} {'min->peak':>10} {'min->20%':>9} {'unretr':>7}"
        f" {'med capt':>9} {'capt win':>9} {'capt/sess':>10}"
    )
    for name, row in summary.items():
        print(
            f"{_label(name):>22} {row['legs']:>5} {row['up']:>3}/{row['down']:<3}"
            f" {row['session_hit_pct']:>8.0f}% {row['median_move_pct']:>8.2f}%"
            f" {row['median_move_usd']:>8.2f} {row['median_adr_multiple']:>9.2f}"
            f" {row['median_mins_to_peak']:>10.0f} {row['median_mins_to_retrace']:>9.0f}"
            f" {row['unretraced_pct']:>6.0f}% {row['median_capture_pct']:>+8.2f}%"
            f" {row['capture_win_pct']:>8.0f}% {row['capture_per_session_pct']:>+9.3f}%"
        )


def _print_ticker_report(ticker, report, bucket_minutes, min_legs):
    sessions, legs = report["sessions"], report["legs"]
    print("\n" + "=" * 118)
    if not legs:
        print(f"{ticker}   no qualifying legs across {sessions} session(s)")
        return
    first, last = min(leg["session"] for leg in legs), max(leg["session"] for leg in legs)
    median_adr = statistics.median(leg["adr_pct"] for leg in legs)
    print(
        f"{ticker}   {sessions} sessions ({first} .. {last})   {len(legs)} legs"
        f"   median 20d ADR {median_adr:.2f}%"
    )
    print("=" * 118)
    _print_group_table("by zone", report["zones"])
    _print_group_table(f"by {bucket_minutes}-min start bucket", report["buckets"])

    zone, zone_row = best_group(report["zones"], min_legs)
    bucket, bucket_row = best_group(report["buckets"], min_legs)
    if zone_row:
        print(
            f"\nbest zone:   {zone_display(zone)} ({zone_row['capture_per_session_pct']:+.3f}%/session,"
            f" {zone_row['legs']} legs, capture win {zone_row['capture_win_pct']:.0f}%)"
        )
    if bucket_row:
        print(
            f"best bucket: {_label(bucket)} ({bucket_row['capture_per_session_pct']:+.3f}%/session,"
            f" {bucket_row['legs']} legs, median {bucket_row['median_adr_multiple']:.2f}xADR,"
            f" lasts {bucket_row['median_mins_to_retrace']:.0f} min)"
        )
    if not zone_row and not bucket_row:
        print(f"\nno zone or bucket has {min_legs}+ legs; widen --sessions or lower --min-legs")


def _print_cross_ticker_summary(reports, min_legs):
    print("\n" + "=" * 129)
    print(f"BEST ENTRY TIME BY TICKER   (highest capture per session; groups need {min_legs}+ legs)")
    print("=" * 118)
    print(
        f"{'tkr':6} {'sess':>5} {'legs':>5} {'legs/day':>9} {'best zone':>22} {'capt/sess':>10}"
        f" {'best bucket':>12} {'capt/sess':>10} {'days hit':>9} {'xADR':>6} {'min->20%':>9}"
    )
    for ticker, report in reports.items():
        zone, zone_row = best_group(report["zones"], min_legs)
        bucket, bucket_row = best_group(report["buckets"], min_legs)
        per_day = len(report["legs"]) / report["sessions"] if report["sessions"] else 0
        zone_text = (zone_display(zone), f"{zone_row['capture_per_session_pct']:+.3f}%") if zone_row else ("n/a", "")
        bucket_text = (
            _label(bucket), f"{bucket_row['capture_per_session_pct']:+.3f}%",
            f"{bucket_row['session_hit_pct']:.0f}%", f"{bucket_row['median_adr_multiple']:.2f}",
            f"{bucket_row['median_mins_to_retrace']:.0f}",
        ) if bucket_row else ("n/a", "", "", "", "")
        print(
            f"{ticker:6} {report['sessions']:>5} {len(report['legs']):>5} {per_day:>9.2f}"
            f" {zone_text[0]:>22} {zone_text[1]:>10} {bucket_text[0]:>12} {bucket_text[1]:>10}"
            f" {bucket_text[2]:>9} {bucket_text[3]:>6} {bucket_text[4]:>9}"
        )


def _print_legend(args):
    print("\n" + "-" * 118)
    print(
        f"leg       = move of >= max({args.min_move_adr:g}xADR, {args.min_move_pct:g}%) reached within"
        f" {args.impulse_bars * BAR_MINUTES} min of a bar open, before a {args.retrace:.0%} give-back"
    )
    print("ADR       = mean regular-hours (high-low)/open of the 20 sessions BEFORE the leg's session")
    print("days hit  = share of sessions with at least one leg starting in that group")
    print("min->peak / min->20% = minutes from the leg's start bar to its extreme bar /"
          f" to the bar that retraced {args.retrace:.0%}")
    print("unretr    = legs still running at the close (exit taken at the last bar's close)")
    print("capture   = enter at the close of the bar that qualified the leg, exit at the"
          " retracement level (or the bar open if it gapped through)")
    print("capt/sess = summed capture divided by ALL sessions — rewards both frequency and quality")


def _write_csv(reports, out_path):
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for ticker, report in reports.items():
            for leg in report["legs"]:
                row = {field: leg.get(field) for field in CSV_FIELDS}
                row["ticker"] = ticker
                row["bucket"] = _label(leg["bucket"])
                writer.writerow(row)
    return out_path


def parse_args():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--tickers", nargs="+", default=DEFAULT_TICKERS)
    parser.add_argument(
        "--sessions", type=int, default=DEFAULT_SESSIONS,
        help=f"Trailing sessions to scan (default: {DEFAULT_SESSIONS})",
    )
    parser.add_argument("--end", help="Last session YYYY-MM-DD (default: today)")
    parser.add_argument("--feed", default="sip", choices=["sip", "iex"])
    parser.add_argument(
        "--bucket-minutes", type=int, default=DEFAULT_BUCKET_MINUTES,
        help=f"Start-time bucket width in minutes (default: {DEFAULT_BUCKET_MINUTES})",
    )
    parser.add_argument(
        "--impulse-bars", type=int, default=DEFAULT_IMPULSE_BARS,
        help="5-min bars a leg has to reach the threshold in (default: 3 = 15 min)",
    )
    parser.add_argument(
        "--min-move-adr", type=float, default=DEFAULT_MIN_MOVE_ADR,
        help=f"Leg threshold as a multiple of the prior 20-session ADR%% (default: {DEFAULT_MIN_MOVE_ADR})",
    )
    parser.add_argument(
        "--min-move-pct", type=float, default=0.0,
        help="Flat floor on the leg threshold in percent (default: 0)",
    )
    parser.add_argument(
        "--retrace", type=float, default=DEFAULT_RETRACE,
        help=f"Give-back fraction of the leg that ends it (default: {DEFAULT_RETRACE})",
    )
    parser.add_argument(
        "--retrace-basis", default="wick", choices=["wick", "close"],
        help="wick: extreme and give-back use highs/lows, so a single wick can end a leg; "
             "close: everything is measured on 5-min bar closes (default: wick)",
    )
    parser.add_argument(
        "--direction", default="both", choices=["both", "up", "down"],
        help="Keep up legs, down legs, or both",
    )
    parser.add_argument(
        "--min-legs", type=int, default=DEFAULT_MIN_LEGS,
        help=f"Legs a zone/bucket needs to be eligible for 'best' (default: {DEFAULT_MIN_LEGS})",
    )
    parser.add_argument("--csv-out", help="Write every leg to this CSV path")
    return parser.parse_args()


def main():
    args = parse_args()
    feed = DataFeed.SIP if args.feed == "sip" else DataFeed.IEX
    requested_end = date.fromisoformat(args.end) if args.end else date.today()
    end_date = clamp_end_for_sip(requested_end, feed)
    lookback_sessions = args.sessions + ADR_SESSIONS
    start_date = end_date - timedelta(days=int(lookback_sessions * 1.6) + 10)

    bars = fetch_bars(args.tickers, start_date, end_date, allow_intraday=True, feed=feed)

    reports = OrderedDict()
    for ticker in args.tickers:
        legs, session_count = collect_ticker_legs(
            bars.get(ticker), args.sessions, args.min_move_adr, args.min_move_pct,
            args.impulse_bars, args.retrace, args.bucket_minutes,
            args.retrace_basis == "close",
        ) if ticker in bars else ([], 0)
        if args.direction != "both":
            legs = [leg for leg in legs if leg["direction"] == args.direction]
        reports[ticker] = {
            "sessions": session_count,
            "legs": legs,
            "zones": summarize_by(legs, session_count, "zone"),
            "buckets": summarize_by(legs, session_count, "bucket"),
        }

    clamp_note = f" (clamped from {requested_end})" if end_date != requested_end else ""
    print(
        f"\nIntraday leg timing through {end_date}{clamp_note} | feed={args.feed}"
        f" | direction={args.direction} | retrace basis={args.retrace_basis}"
    )
    for ticker, report in reports.items():
        _print_ticker_report(ticker, report, args.bucket_minutes, args.min_legs)
    _print_cross_ticker_summary(reports, args.min_legs)
    _print_legend(args)

    if args.csv_out:
        print(f"\nlegs written to {_write_csv(reports, Path(args.csv_out))}")


if __name__ == "__main__":
    main()

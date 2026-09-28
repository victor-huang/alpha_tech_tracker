"""When does each session's longest clean leg happen? A hindsight study on 5-min bars.

For every session this finds, with the whole day known, the single largest up leg
and the single largest down leg that never gave back more than `--retrace` (default
32%) of its progress while it was running. The legs are then grouped by the clock
time they started and ended, to show where in the day a ticker's main move lives.

A leg is anchored on its extreme start: the low of its first bar for an up leg
(`--retrace-basis wick`) or the open of its first bar measured on closes
(`--retrace-basis close`). Until the leg has travelled `--min-progress-adr` x ADR
it only has to hold above its start, so the first tick of noise off a low does not
count as a 32% give-back of a near-zero move.

`--rank-by duration` picks the longest-lasting leg instead of the largest one;
legs then also need to travel `--min-move-adr` x ADR so a slow drift does not win.
"""

import argparse
import csv
import statistics
from collections import Counter, OrderedDict
from datetime import date, time, timedelta
from pathlib import Path

from alpaca.data.enums import DataFeed

from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.intraday_leg_timing import (
    BAR_MINUTES,
    ZONES,
    bucket_start,
    prior_session_adr,
    regular_sessions,
    zone_display,
    zone_label,
)
from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.ticker_stats_report import (
    MARKET_OPEN,
    clamp_end_for_sip,
)
from alpha_tech_tracker.op_momentum_strategy.op_momentum_backtest import fetch_bars

DEFAULT_TICKERS = ["SNDK", "APP", "NVDA", "LLY", "MRNA", "COIN", "HOOD"]
ADR_SESSIONS = 20
DEFAULT_SESSIONS = 250
DEFAULT_RETRACE = 0.32
DEFAULT_MIN_PROGRESS_ADR = 0.10
DEFAULT_MIN_MOVE_ADR = 0.25
DEFAULT_BUCKET_MINUTES = 15
DEFAULT_TOP_N = 5
DEFAULT_AVG_SESSIONS = 5
LEG_KINDS = ("up", "down", "biggest")
CSV_FIELDS = [
    "ticker", "session", "kind", "direction", "start_time", "end_time", "start_zone",
    "end_zone", "start_bucket", "duration_mins", "start_price", "end_price", "move_usd",
    "move_pct", "adr_pct", "adr_multiple", "day_range_share", "max_retrace",
]


def _holds(price, extreme, start, scale, retrace_frac, min_progress_pct):
    progress = extreme - start
    if progress / scale * 100 < min_progress_pct:
        return price >= start
    return price >= extreme - retrace_frac * progress


def longest_leg(starts, highs, lows, closes, retrace_frac, min_progress_pct,
                rank_by="move", min_move_pct=0.0):
    """Best clean up-leg of a session as bar indices and prices, or None.

    Down legs are passed in negated with highs/lows swapped. Each start bar is
    extended bar by bar until the leg breaks its retracement limit; every new
    extreme along the way is a candidate end. A bar's adverse price is checked
    against the extreme before that bar, since OHLC does not say which printed first.
    """
    n = len(starts)
    best, best_key = None, None
    for i in range(n):
        start = starts[i]
        scale = abs(start)
        if not scale:
            continue
        extreme, deepest = start, 0.0
        for k in range(i, n):
            if k > i:
                if not _holds(lows[k], extreme, start, scale, retrace_frac, min_progress_pct):
                    break
                if extreme > start:
                    deepest = max(deepest, (extreme - lows[k]) / (extreme - start))
            new_extreme = highs[k] > extreme
            if new_extreme:
                extreme = highs[k]
            if not _holds(closes[k], extreme, start, scale, retrace_frac, min_progress_pct):
                break
            if not new_extreme:
                continue

            move_pct = (extreme - start) / scale * 100
            if rank_by == "duration":
                if move_pct < min_move_pct:
                    continue
                key = (k - i, move_pct)
            else:
                key = (move_pct, k - i)
            if best_key is None or key > best_key:
                best_key = key
                best = {"start_idx": i, "end_idx": k, "start": start, "extreme": extreme,
                        "max_retrace": deepest}
    return best


def session_longest_legs(frame, adr_pct, retrace_frac=DEFAULT_RETRACE,
                         min_progress_adr=DEFAULT_MIN_PROGRESS_ADR, close_basis=False,
                         rank_by="move", min_move_adr=DEFAULT_MIN_MOVE_ADR,
                         bucket_minutes=DEFAULT_BUCKET_MINUTES):
    """{'up': leg, 'down': leg, 'biggest': leg} for one session; missing sides are omitted."""
    o, h, l, c = (frame[col].to_numpy(dtype=float) for col in ("Open", "High", "Low", "Close"))
    if close_basis:
        views = {"up": (o, c, c, c), "down": (-o, -c, -c, -c)}
    else:
        views = {"up": (l, h, l, c), "down": (-h, -l, -h, -c)}

    session_open = o[0]
    day_range = h.max() - l.min()
    stamps = frame.index
    legs = {}
    for direction, (starts, highs, lows, closes) in views.items():
        leg = longest_leg(
            starts, highs, lows, closes, retrace_frac, min_progress_adr * adr_pct,
            rank_by, min_move_adr * adr_pct,
        )
        if leg is None:
            continue
        sign = 1 if direction == "up" else -1
        start_price = sign * leg["start"]
        move = leg["extreme"] - leg["start"]
        start_time = stamps[leg["start_idx"]]
        end_time = stamps[leg["end_idx"]] + timedelta(minutes=BAR_MINUTES)
        legs[direction] = {
            "direction": direction,
            "start_time": start_time,
            "end_time": end_time,
            "start_zone": zone_label(start_time),
            "end_zone": zone_label(stamps[leg["end_idx"]]),
            "start_bucket": bucket_start(start_time, bucket_minutes),
            "duration_mins": (leg["end_idx"] - leg["start_idx"] + 1) * BAR_MINUTES,
            "start_price": start_price,
            "end_price": sign * leg["extreme"],
            "move_usd": move,
            "move_pct": move / start_price * 100,
            "adr_pct": adr_pct,
            "adr_multiple": move / start_price * 100 / adr_pct if adr_pct else None,
            "day_range_share": move / day_range if day_range else None,
            "max_retrace": leg["max_retrace"],
            "session_open": session_open,
        }
    if legs:
        rank = "duration_mins" if rank_by == "duration" else "move_pct"
        top = max(legs.values(), key=lambda leg: (leg[rank], leg["move_pct"]))
        legs["biggest"] = dict(top)
    return legs


def collect_ticker(bars, sessions, retrace_frac, min_progress_adr, close_basis, rank_by,
                   min_move_adr, bucket_minutes):
    frames = regular_sessions(bars)
    adr = prior_session_adr(frames, ADR_SESSIONS)
    scored = [(session, frame) for session, frame in frames if adr.get(session)][-sessions:]
    rows = []
    for session, frame in scored:
        legs = session_longest_legs(
            frame, adr[session], retrace_frac, min_progress_adr, close_basis, rank_by,
            min_move_adr, bucket_minutes,
        )
        for kind, leg in legs.items():
            leg.update(session=session, kind=kind)
            rows.append(leg)
    return rows, len(scored)


def _minutes_after_open(stamp):
    return stamp.hour * 60 + stamp.minute - (MARKET_OPEN.hour * 60 + MARKET_OPEN.minute)


def _clock(minutes_after_open):
    total = MARKET_OPEN.hour * 60 + MARKET_OPEN.minute + int(round(minutes_after_open))
    return time(total // 60, total % 60)


def summarize_kind(legs):
    if not legs:
        return None
    count = len(legs)
    start_zones = Counter(leg["start_zone"] for leg in legs)
    end_zones = Counter(leg["end_zone"] for leg in legs)
    buckets = Counter(leg["start_bucket"] for leg in legs)
    multiples = [leg["adr_multiple"] for leg in legs if leg["adr_multiple"] is not None]
    shares = [leg["day_range_share"] for leg in legs if leg["day_range_share"] is not None]
    return {
        "legs": count,
        "start_zone_share": OrderedDict(
            (label, start_zones.get(label, 0) / count * 100) for label, _, _ in ZONES
        ),
        "end_zone_share": OrderedDict(
            (label, end_zones.get(label, 0) / count * 100) for label, _, _ in ZONES
        ),
        "bucket_share": OrderedDict(
            (bucket, buckets[bucket] / count * 100) for bucket in sorted(buckets)
        ),
        "median_start": _clock(statistics.median(_minutes_after_open(l["start_time"]) for l in legs)),
        "median_end": _clock(statistics.median(_minutes_after_open(l["end_time"]) for l in legs)),
        "median_duration": statistics.median(leg["duration_mins"] for leg in legs),
        "median_move_pct": statistics.median(leg["move_pct"] for leg in legs),
        "median_move_usd": statistics.median(leg["move_usd"] for leg in legs),
        "median_adr_multiple": statistics.median(multiples) if multiples else None,
        "median_day_share": statistics.median(shares) * 100 if shares else None,
        "median_max_retrace": statistics.median(leg["max_retrace"] for leg in legs) * 100,
    }


def _top_zone(summary):
    label = max(summary["start_zone_share"], key=summary["start_zone_share"].get)
    return zone_display(label), summary["start_zone_share"][label]


def _print_ticker(ticker, report, bucket_minutes):
    sessions, summaries = report["sessions"], report["summaries"]
    print("\n" + "=" * 112)
    if not any(summaries.values()):
        print(f"{ticker}   no legs across {sessions} session(s)")
        return
    first = min(leg["session"] for leg in report["legs"])
    last = max(leg["session"] for leg in report["legs"])
    biggest = summaries["biggest"]
    up_days = biggest["legs"] and sum(
        1 for leg in report["legs"] if leg["kind"] == "biggest" and leg["direction"] == "up"
    )
    print(f"{ticker}   {sessions} sessions ({first} .. {last})   biggest leg was UP on"
          f" {up_days}/{biggest['legs']} days")
    print("=" * 112)

    print(f"\n{'':22}" + "".join(f"{label:>12}" for label, _, _ in ZONES))
    print(f"{'':22}" + "".join(
        f"{start.strftime('%H:%M') + '-' + end.strftime('%H:%M'):>12}" for _, start, end in ZONES
    ))
    for kind in LEG_KINDS:
        summary = summaries[kind]
        if not summary:
            continue
        print(f"{kind + ' starts in':22}"
              + "".join(f"{share:>11.0f}%" for share in summary["start_zone_share"].values()))
        print(f"{kind + ' ends in':22}"
              + "".join(f"{share:>11.0f}%" for share in summary["end_zone_share"].values()))

    print(
        f"\n{'':10} {'legs':>5} {'med start':>10} {'med end':>8} {'med mins':>9}"
        f" {'med move':>9} {'med $':>8} {'med xADR':>9} {'of day rng':>11} {'med retr':>9}"
    )
    for kind in LEG_KINDS:
        s = summaries[kind]
        if not s:
            continue
        adr = f"{s['median_adr_multiple']:.2f}" if s["median_adr_multiple"] is not None else "n/a"
        share = f"{s['median_day_share']:.0f}%" if s["median_day_share"] is not None else "n/a"
        print(
            f"{kind:10} {s['legs']:>5} {s['median_start'].strftime('%H:%M'):>10}"
            f" {s['median_end'].strftime('%H:%M'):>8} {s['median_duration']:>9.0f}"
            f" {s['median_move_pct']:>8.2f}% {s['median_move_usd']:>8.2f} {adr:>9}"
            f" {share:>11} {s['median_max_retrace']:>8.0f}%"
        )

    buckets = sorted({b for kind in LEG_KINDS if summaries[kind] for b in summaries[kind]["bucket_share"]})
    print(f"\nstart {bucket_minutes}-min bucket  " + "  ".join(f"{kind:>7}" for kind in LEG_KINDS))
    for bucket in buckets:
        cells = []
        for kind in LEG_KINDS:
            share = summaries[kind]["bucket_share"].get(bucket, 0) if summaries[kind] else 0
            cells.append(f"{share:>6.0f}%")
        print(f"{bucket.strftime('%H:%M'):>20}  " + "  ".join(cells))


def _print_summary(reports):
    print("\n" + "=" * 156)
    print("WHEN THE DAY'S LONGEST LEG STARTS   (top start zone and its share of sessions;"
          " median start/end clock time and duration)")
    print("=" * 156)
    header = f"{'tkr':6} {'sess':>5}"
    for kind in LEG_KINDS:
        header += f" | {kind + ' zone':>25} {'start':>6} {'end':>6} {'mins':>5} {'xADR':>5}"
    header += f" | {'big up%':>7}"
    print(header)
    for ticker, report in reports.items():
        line = f"{ticker:6} {report['sessions']:>5}"
        for kind in LEG_KINDS:
            s = report["summaries"][kind]
            if not s:
                line += f" | {'n/a':>25} {'':>6} {'':>6} {'':>5} {'':>5}"
                continue
            label, share = _top_zone(s)
            adr = f"{s['median_adr_multiple']:.2f}" if s["median_adr_multiple"] is not None else "n/a"
            line += (
                f" | {label + f' {share:.0f}%':>25} {s['median_start'].strftime('%H:%M'):>6}"
                f" {s['median_end'].strftime('%H:%M'):>6} {s['median_duration']:>5.0f} {adr:>5}"
            )
        biggest = [leg for leg in report["legs"] if leg["kind"] == "biggest"]
        up_share = sum(1 for leg in biggest if leg["direction"] == "up") / len(biggest) * 100 \
            if biggest else 0
        line += f" | {up_share:>6.0f}%"
        print(line)


def top_legs_for_day(reports, day, direction, top_n=DEFAULT_TOP_N,
                     avg_sessions=DEFAULT_AVG_SESSIONS, rank_by="pct"):
    """The `top_n` tickers with the strongest `direction` leg on `day`.

    Each row carries that ticker's average leg of the same direction over the
    `avg_sessions` sessions before `day`, so the day's move can be read against its
    own recent norm. Sessions without a leg in that direction are left out of the
    average, and `avg_n` says how many sessions it covers.
    """
    rank_key = "adr_multiple" if rank_by == "adr" else "move_pct"
    rows = []
    for ticker, report in reports.items():
        legs = [leg for leg in report["legs"] if leg["kind"] == direction]
        today = next((leg for leg in legs if leg["session"] == day), None)
        if today is None:
            continue
        prior_sessions = sorted({leg["session"] for leg in report["legs"] if leg["session"] < day})
        window = set(prior_sessions[-avg_sessions:])
        prior = [leg for leg in legs if leg["session"] in window]
        avg_pct = statistics.mean(leg["move_pct"] for leg in prior) if prior else None
        rows.append({
            "ticker": ticker,
            "start_time": today["start_time"],
            "end_time": today["end_time"],
            "duration_mins": today["duration_mins"],
            "start_price": today["start_price"],
            "end_price": today["end_price"],
            "move_pct": today["move_pct"],
            "move_usd": today["move_usd"],
            "adr_multiple": today["adr_multiple"],
            "avg_move_pct": avg_pct,
            "avg_move_usd": statistics.mean(leg["move_usd"] for leg in prior) if prior else None,
            "avg_n": len(prior),
            "vs_avg": today["move_pct"] / avg_pct if avg_pct else None,
        })
    rows.sort(
        key=lambda row: row[rank_key] if row[rank_key] is not None else float("-inf"),
        reverse=True,
    )
    return rows[:top_n]


def _print_top_legs(day, direction, rows, avg_sessions, rank_by):
    sign = "+" if direction == "up" else "-"
    basis = "move x ADR" if rank_by == "adr" else "% move"
    print("\n" + "=" * 118)
    print(f"TOP {len(rows)} {direction.upper()} LEGS ON {day}   (ranked by {basis};"
          f" avg = the same ticker's {direction} leg over the prior {avg_sessions} sessions)")
    print("=" * 118)
    if not rows:
        print(f"no {direction} legs on {day}")
        return
    print(
        f"{'#':>2} {'tkr':6} {'start':>6} {'end':>6} {'mins':>5} {'from':>9} {'to':>9}"
        f" {'move %':>8} {'move $':>9} {'xADR':>5} | {f'{avg_sessions}d avg %':>9}"
        f" {f'{avg_sessions}d avg $':>10} {'n':>2} {'vs avg':>7}"
    )
    for rank, row in enumerate(rows, 1):
        avg_pct = f"{sign}{row['avg_move_pct']:.2f}%" if row["avg_move_pct"] is not None else "n/a"
        avg_usd = f"{sign}${row['avg_move_usd']:.2f}" if row["avg_move_usd"] is not None else "n/a"
        vs_avg = f"{row['vs_avg']:.2f}x" if row["vs_avg"] is not None else "n/a"
        adr = f"{row['adr_multiple']:.2f}" if row["adr_multiple"] is not None else "n/a"
        print(
            f"{rank:>2} {row['ticker']:6} {row['start_time'].strftime('%H:%M'):>6}"
            f" {row['end_time'].strftime('%H:%M'):>6} {row['duration_mins']:>5}"
            f" {row['start_price']:>9.2f} {row['end_price']:>9.2f}"
            f" {sign + format(row['move_pct'], '.2f') + '%':>8}"
            f" {sign + '$' + format(row['move_usd'], '.2f'):>9}"
            f" {adr:>5} | {avg_pct:>9} {avg_usd:>10} {row['avg_n']:>2} {vs_avg:>7}"
        )


def _print_legend(args):
    print("\n" + "-" * 132)
    print(f"leg      = largest move{' (by duration)' if args.rank_by == 'duration' else ''} of the session"
          f" that never retraced more than {args.retrace:.0%} of its progress ({args.retrace_basis} basis)")
    print("biggest  = the larger of that session's up and down leg")
    print("zones    = " + ", ".join(f"{label} {start.strftime('%H:%M')}-{end.strftime('%H:%M')}"
                                   for label, start, end in ZONES))
    print("xADR     = leg move / prior 20-session average regular-hours range;"
          " of day rng = leg move / that session's high-low range")
    print("med retr = deepest give-back the leg absorbed while it was running")
    if args.top:
        print("top legs = start is the first bar's open time, end is the close of the bar that set"
              " the extreme; $ is per share; vs avg = today's % move / the prior-session average")


def _write_csv(reports, out_path):
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for ticker, report in reports.items():
            for leg in report["legs"]:
                row = dict(leg, ticker=ticker)
                row["start_bucket"] = leg["start_bucket"].strftime("%H:%M")
                writer.writerow(row)
    return out_path


def parse_args():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--tickers", nargs="+", default=DEFAULT_TICKERS)
    parser.add_argument("--sessions", type=int, default=DEFAULT_SESSIONS)
    parser.add_argument("--end", help="Last session YYYY-MM-DD (default: today)")
    parser.add_argument("--feed", default="sip", choices=["sip", "iex"])
    parser.add_argument(
        "--retrace", type=float, default=DEFAULT_RETRACE,
        help=f"Largest give-back a leg may absorb, as a fraction of its progress (default: {DEFAULT_RETRACE})",
    )
    parser.add_argument(
        "--retrace-basis", default="close", choices=["wick", "close"],
        help="close: legs measured on 5-min closes (default); wick: on highs/lows",
    )
    parser.add_argument(
        "--min-progress-adr", type=float, default=DEFAULT_MIN_PROGRESS_ADR,
        help="Progress (x ADR) a leg needs before the retracement limit applies",
    )
    parser.add_argument(
        "--rank-by", default="move", choices=["move", "duration"],
        help="Pick the largest leg (move) or the longest-lasting one (duration)",
    )
    parser.add_argument(
        "--min-move-adr", type=float, default=DEFAULT_MIN_MOVE_ADR,
        help="With --rank-by duration, the smallest move (x ADR) a leg must make",
    )
    parser.add_argument("--bucket-minutes", type=int, default=DEFAULT_BUCKET_MINUTES)
    parser.add_argument("--csv-out", help="Write every session's legs to this CSV path")
    parser.add_argument(
        "--date",
        help="Session YYYY-MM-DD for the top-leg tables (default: the latest session). "
             "Also sets --end when --end is not given",
    )
    parser.add_argument(
        "--top", type=int, default=DEFAULT_TOP_N,
        help=f"Tickers per top up/down leg table (default: {DEFAULT_TOP_N}; 0 turns them off)",
    )
    parser.add_argument(
        "--avg-sessions", type=int, default=DEFAULT_AVG_SESSIONS,
        help=f"Prior sessions averaged for each top ticker's leg (default: {DEFAULT_AVG_SESSIONS})",
    )
    parser.add_argument(
        "--top-rank-by", default="pct", choices=["pct", "adr"],
        help="Rank top legs by % move (default) or by move as a multiple of ADR",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    feed = DataFeed.SIP if args.feed == "sip" else DataFeed.IEX
    top_day = date.fromisoformat(args.date) if args.date else None
    requested_end = date.fromisoformat(args.end) if args.end else (top_day or date.today())
    end_date = clamp_end_for_sip(requested_end, feed)
    if top_day and top_day > end_date:
        raise SystemExit(f"{top_day} is not settled yet; {args.feed} serves through {end_date}")
    sessions = max(args.sessions, args.avg_sessions + 1) if args.top else args.sessions
    start_date = end_date - timedelta(days=int((sessions + ADR_SESSIONS) * 1.6) + 10)
    bars = fetch_bars(args.tickers, start_date, end_date, allow_intraday=True, feed=feed)

    reports = OrderedDict()
    for ticker in args.tickers:
        legs, session_count = collect_ticker(
            bars.get(ticker), sessions, args.retrace, args.min_progress_adr,
            args.retrace_basis == "close", args.rank_by, args.min_move_adr, args.bucket_minutes,
        ) if ticker in bars else ([], 0)
        reports[ticker] = {
            "sessions": session_count,
            "legs": legs,
            "summaries": {
                kind: summarize_kind([leg for leg in legs if leg["kind"] == kind])
                for kind in LEG_KINDS
            },
        }

    clamp_note = f" (clamped from {requested_end})" if end_date != requested_end else ""
    print(
        f"\nDaily longest leg through {end_date}{clamp_note} | feed={args.feed}"
        f" | retrace<={args.retrace:.0%} ({args.retrace_basis}) | rank by {args.rank_by}"
    )
    for ticker, report in reports.items():
        _print_ticker(ticker, report, args.bucket_minutes)
    _print_summary(reports)

    all_sessions = [leg["session"] for report in reports.values() for leg in report["legs"]]
    if args.top and all_sessions:
        day = top_day or max(all_sessions)
        for direction in ("up", "down"):
            rows = top_legs_for_day(
                reports, day, direction, args.top, args.avg_sessions, args.top_rank_by
            )
            _print_top_legs(day, direction, rows, args.avg_sessions, args.top_rank_by)
    _print_legend(args)

    if args.csv_out:
        print(f"\nlegs written to {_write_csv(reports, Path(args.csv_out))}")


if __name__ == "__main__":
    main()

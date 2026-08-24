"""Write one dated watch-list folder: stats text, candidates, option OI, chart."""

import argparse
import json
import subprocess
import sys
from argparse import Namespace
from pathlib import Path

from alpha_tech_tracker.op_momentum_strategy.analysis_scripts import ticker_stats_report as R

DEFAULT_TICKERS = [
    "QQQ", "LLY", "MRNA", "APP", "META", "SNDK", "SPCX", "HOOD", "COIN",
    "AMD", "CRWV", "AMAT", "SPOT", "PLTR", "FN", "RH", "DECK", "GWRE",
]
LOG_ROOT = Path(__file__).resolve().parent.parent / "dt_stock_watch_list_log"
BANDS = [12, 16, 20]
SHORTLIST_SIZE = 3
REPORT_MODULE = (
    "alpha_tech_tracker.op_momentum_strategy.analysis_scripts.ticker_stats_report"
)


def _report_args(tickers, weeks, end, bands, skip_options=False):
    """Build the namespace collect_results expects, matching the CLI defaults."""
    return Namespace(
        tickers=tickers,
        weeks=weeks,
        or_bars=3,
        bands=bands,
        followthrough_adr_factor=0.25,
        followthrough_pct=0.8,
        expiry=None,
        end=end,
        feed="sip",
        trend_slope_lookback=R.TREND_SLOPE_LOOKBACK,
        trend_flat_pct=R.TREND_FLAT_PCT,
        trend_cross_lookback=R.TREND_CROSS_LOOKBACK,
        trend_thrust_vol=R.TREND_THRUST_VOL_MULT,
        skip_options=skip_options,
        regime_symbol="QQQ",
        chart_out=None,
    )


def write_stats_text(out_dir, tickers, weeks, end, chart_path):
    """Capture the report exactly as the CLI prints it."""
    command = [
        sys.executable, "-m", REPORT_MODULE,
        "--tickers", *tickers,
        "--weeks", *[str(w) for w in weeks],
        "--chart-out", str(chart_path),
    ]
    if end:
        command += ["--end", end]
    completed = subprocess.run(command, capture_output=True, text=True)
    target = out_dir / "ticker_stats.txt"
    target.write_text(completed.stdout + completed.stderr)
    return target, completed.returncode


def build_shortlist(results, week_count, benchmark_allows_longs):
    """Mechanically rank the enterable candidates on each side.

    Only the ranking is automated. The bias label has no demonstrated forecasting
    power, so a reviewer still has to weigh trend, option skew and volume.
    """
    rows = R.build_watchlist(results, week_count)
    enterable, blocked = {"long": [], "short": []}, {"long": [], "short": []}
    for row in rows:
        if row["bucket"] not in ("long-bias", "short-bias"):
            continue
        side = "long" if row["bucket"] == "long-bias" else "short"
        if side == "long" and benchmark_allows_longs is False:
            blocked[side].append((row, "benchmark regime"))
        elif row["gate"] != "ok":
            blocked[side].append((row, "MA20 extension"))
        else:
            enterable[side].append(row)
    for side in enterable:
        enterable[side].sort(key=lambda r: -r["edge"])
    return enterable, blocked


def dump_option_open_interest(out_dir, results, context):
    """Snapshot the OI behind the report. Alpaca serves live values only, so this
    file is the sole record of the day's figures.
    """
    payload = {
        "as_of": str(context["end_date"]),
        "expiry": str(context["expiry"]),
        "bands": BANDS,
        "note": "open interest is the prior session's OCC figure; see open_interest_date",
        "tickers": {},
    }
    for ticker, stats in results.items():
        skew = stats["option_skew"]
        if "error" in skew:
            payload["tickers"][ticker] = {"error": skew["error"]}
            continue
        payload["tickers"][ticker] = {
            "reference_price": round(stats["spot"], 2) if stats["spot"] else None,
            "atm_strike": skew["atm_strike"],
            "open_interest_date": skew["open_interest_date"],
            "bands": {
                str(band["band"]): {
                    "strikes": band["strikes"],
                    "strike_low": band["strike_low"],
                    "strike_high": band["strike_high"],
                    "call_open_interest": band["calls"],
                    "put_open_interest": band["puts"],
                    "call_put_ratio": band["call_put"],
                    "put_call_ratio": band["put_call"],
                }
                for band in skew["bands"]
            },
        }
    target = out_dir / "option_open_interest.json"
    target.write_text(json.dumps(payload, indent=2))
    return target


def _candidate_table(rows):
    if not rows:
        return "_none enterable_\n"
    header = (
        "| tkr | intraday hit | EOD hit | avg 15:50 | worst | trend | C/P | vol |\n"
        "|---|---:|---:|---:|---:|---|---:|---:|\n"
    )
    lines = []
    for row in rows:
        eod = f"{row['eod_hit']:.0f}%" if row["eod_hit"] is not None else "n/a"
        vol = f"{row['vol_ratio']:.2f}x" if row["vol_ratio"] else "n/a"
        ratio = f"{row['call_put']:.2f}" if row["call_put"] is not None else "n/a"
        lines.append(
            f"| {row['ticker']} | {row['intraday_hit']:.0f}% | {eod} |"
            f" {row['edge']:+.2f}% | {row['worst']:+.2f}% | {row['trend']} |"
            f" {ratio} | {vol} |"
        )
    return header + "\n".join(lines) + "\n"


def _blocked_note(blocked):
    if not blocked:
        return ""
    parts = [f"{row['ticker']} ({reason}, {row['edge']:+.2f}%)" for row, reason in blocked]
    return f"\nBlocked: {', '.join(parts)}\n"


def write_watchlist(out_dir, enterable, blocked, context, week_count):
    allows = context["benchmark_allows_longs"]
    gate_line = (
        f"{context['regime_symbol']} regime unavailable" if allows is None
        else f"{context['regime_symbol']} closed "
             f"{'ABOVE' if allows else 'BELOW'} its daily MA20 -> longs "
             f"{'allowed' if allows else 'BLOCKED'}"
    )
    body = f"""# Watch list — as of {context['end_date']}

Ranked over the trailing {week_count} week(s). **{gate_line}**

Direction is decided by each ticker's opening range at 09:45, not in advance. A
candidate only trades if its OR closes on the biased side.

## Long candidates

{_candidate_table(enterable['long'][:SHORTLIST_SIZE])}{_blocked_note(blocked['long'])}
## Short candidates

{_candidate_table(enterable['short'][:SHORTLIST_SIZE])}{_blocked_note(blocked['short'])}
## Review notes

_Fill in: which candidates the trend, option skew and volume columns agree with,
and which to drop despite a high ranking._

## Reliability

Recent-behaviour screen, not a forecast. A 2023-2026 walk-forward over 4,293
trades put ranking-based selection at +3.5bp per trade over taking every signal.
Average favourable excursion runs 1.5-2.2% per trade while holding to 15:50
captures near zero — any edge is in the exit, not the pick. See
`research/experiments/OR_WINRATE_STRATEGY_STUDY.md`.

## Files

| file | |
|---|---|
| `ticker_stats.txt` | full report output |
| `option_open_interest.json` | OI at bands {BANDS} for the {context['expiry']} expiry |
| `range_distribution.pdf` | 20-session daily range% histogram per ticker |
"""
    target = out_dir / "watchlist.md"
    target.write_text(body)
    return target


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tickers", nargs="+", default=DEFAULT_TICKERS)
    parser.add_argument("--weeks", nargs="+", type=int, default=[1, 2])
    parser.add_argument(
        "--end", help="Last session YYYY-MM-DD (default: today, clamped for SIP)"
    )
    parser.add_argument(
        "--rank-weeks", type=int,
        help="Window used to rank candidates (default: the longest --weeks value)",
    )
    parser.add_argument("--log-root", default=str(LOG_ROOT))
    parser.add_argument(
        "--skip-options", action="store_true",
        help="Skip the OI section — required when --end is a past date",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    rank_weeks = args.rank_weeks or max(args.weeks)

    report_args = _report_args(args.tickers, args.weeks, args.end, BANDS, args.skip_options)
    results, context = R.collect_results(report_args)

    out_dir = Path(args.log_root) / str(context["end_date"])
    out_dir.mkdir(parents=True, exist_ok=True)

    stats_path, code = write_stats_text(
        out_dir, args.tickers, args.weeks, args.end, out_dir / "range_distribution.pdf"
    )
    if code != 0:
        print(f"WARNING: report exited {code}; see {stats_path}")

    enterable, blocked = build_shortlist(
        results, rank_weeks, context["benchmark_allows_longs"]
    )
    watchlist_path = write_watchlist(out_dir, enterable, blocked, context, rank_weeks)
    oi_path = (
        dump_option_open_interest(out_dir, results, context)
        if not args.skip_options else None
    )

    print(f"\nwatch-list log written to {out_dir}")
    for path in (stats_path, watchlist_path, oi_path, out_dir / "range_distribution.pdf"):
        if path and path.exists():
            print(f"  {path.name:28} {path.stat().st_size:>9,} bytes")
    for side in ("long", "short"):
        picks = ", ".join(r["ticker"] for r in enterable[side][:SHORTLIST_SIZE]) or "none"
        print(f"  {side:>5} candidates: {picks}")


if __name__ == "__main__":
    main()

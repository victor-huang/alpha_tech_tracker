"""
analyze_big_winners.py

For trades that exited via hard_stop / fallback_20pct (the only exits affected by
exit_at_bar_close), identify which would qualify as a "big winner" (gain ≥ 0.8%)
under each fill model, and quantify their P&L impact and live-engine reachability.

Reads the detail JSON produced by verify_1min_fills.py.
"""

import argparse
import json
from collections import defaultdict
from pathlib import Path

BIG_WIN_PCT = 0.008  # +0.8%

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def pnl_pct(entry: float, exit_: float, sig: str) -> float:
    if sig == "BULLISH":
        return (exit_ - entry) / entry
    return (entry - exit_) / entry


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        default=str(PROJECT_ROOT / "logs" / "verify_1min_fills_2024-01-02_2024-12-31.json"),
    )
    parser.add_argument("--threshold", type=float, default=BIG_WIN_PCT)
    args = parser.parse_args()

    rows = json.load(open(args.input))
    print(f"Loaded {len(rows)} hard_stop/fallback trade rows from {args.input}")
    print(f"Big-winner threshold: gain ≥ {args.threshold * 100:.2f}%")
    print()

    # Classify each trade by which model produced a big win.
    buckets = {
        "opt_only": [],      # ≥0.8% only in optimistic
        "opt_and_1min": [],  # ≥0.8% in both optimistic and 1-min
        "opt_and_5min": [],  # ≥0.8% in both optimistic and 5-min (rare; should be real wins)
        "all_three": [],     # ≥0.8% in all three
        "1min_only": [],     # ≥0.8% in 1-min but not optimistic (≈ impossible by construction)
        "5min_only": [],     # ≥0.8% in 5-min but not others (also impossible)
        "none": [],
    }
    for r in rows:
        e = r["entry"]
        sig = r["sig"]
        p_5 = pnl_pct(e, r["exit_5min"], sig)
        p_1 = pnl_pct(e, r["exit_1min"], sig)
        p_o = pnl_pct(e, r["exit_opt"], sig)
        big_5 = p_5 >= args.threshold
        big_1 = p_1 >= args.threshold
        big_o = p_o >= args.threshold
        r["pct_5min"] = p_5
        r["pct_1min"] = p_1
        r["pct_opt"] = p_o

        if big_o and big_1 and big_5:
            buckets["all_three"].append(r)
        elif big_o and big_1:
            buckets["opt_and_1min"].append(r)
        elif big_o and big_5:
            buckets["opt_and_5min"].append(r)
        elif big_o:
            buckets["opt_only"].append(r)
        elif big_1 and not big_o:
            buckets["1min_only"].append(r)
        elif big_5 and not big_o:
            buckets["5min_only"].append(r)
        else:
            buckets["none"].append(r)

    def cap_sum(rs, key):
        return sum(r[key] for r in rs)

    print("━" * 96)
    print(f"  {'Bucket':<24} {'Trades':>7} {'5min$':>10} {'1min$':>10} {'Opt$':>10}  Description")
    print("━" * 96)
    desc = {
        "all_three": "Genuine big winners (≥0.8% in all 3 models)",
        "opt_and_1min": "Recoverable: opt + 1min are big wins, 5min isn't",
        "opt_and_5min": "Big in 5min and opt but 1min lost it (rare)",
        "opt_only": "Artifact-only: only optimistic shows big win",
        "1min_only": "1min big but opt isn't (shouldn't happen)",
        "5min_only": "5min big but opt isn't (shouldn't happen)",
        "none": "None of the models showed a big win",
    }
    for b in ["all_three", "opt_and_1min", "opt_and_5min", "opt_only",
              "1min_only", "5min_only", "none"]:
        rs = buckets[b]
        if not rs and b in ("1min_only", "5min_only"):
            continue
        print(
            f"  {b:<24} {len(rs):>7} "
            f"{cap_sum(rs, 'pnl_5min_cap'):>+10.2f} "
            f"{cap_sum(rs, 'pnl_1min_cap'):>+10.2f} "
            f"{cap_sum(rs, 'pnl_opt_cap'):>+10.2f}  {desc[b]}"
        )
    print("━" * 96)

    # Focused: trades where optimistic ≥ 0.8%.
    opt_big = buckets["all_three"] + buckets["opt_and_1min"] + buckets["opt_and_5min"] + buckets["opt_only"]
    print(f"\n  Trades where OPTIMISTIC mode shows ≥{args.threshold*100:.1f}% gain: {len(opt_big)}")
    print(f"    Optimistic total cap P&L for these: {cap_sum(opt_big, 'pnl_opt_cap'):+,.2f}")
    print(f"    5-min default cap P&L for the SAME trades: {cap_sum(opt_big, 'pnl_5min_cap'):+,.2f}")
    print(f"    1-min realistic cap P&L for the SAME trades: {cap_sum(opt_big, 'pnl_1min_cap'):+,.2f}")
    print(f"    Inflation vs 5-min: {cap_sum(opt_big, 'pnl_opt_cap') - cap_sum(opt_big, 'pnl_5min_cap'):+,.2f}")
    print(f"    Recovered by 1-min: {cap_sum(opt_big, 'pnl_1min_cap') - cap_sum(opt_big, 'pnl_5min_cap'):+,.2f}")

    # How many of these "big winners" are actually achievable?
    reachable = buckets["all_three"] + buckets["opt_and_1min"]
    artifact = buckets["opt_only"]
    print(f"\n  Of {len(opt_big)} optimistic big winners:")
    print(f"    Achievable (≥0.8% in 1-min realistic too): {len(reachable)} "
          f"({len(reachable)/len(opt_big)*100:.1f}%)")
    print(f"    Pure artifact (only optimistic ≥0.8%):    {len(artifact)} "
          f"({len(artifact)/len(opt_big)*100:.1f}%)")

    # Distribution of how big the gap is for opt_only artifacts
    if buckets["opt_only"]:
        gaps = sorted([r["pct_opt"] - r["pct_1min"] for r in buckets["opt_only"]])
        print(f"\n  Artifact gap distribution (opt_pct − 1min_pct), opt_only bucket:")
        print(f"    p25={gaps[len(gaps)//4]*100:.2f}%  p50={gaps[len(gaps)//2]*100:.2f}%  "
              f"p75={gaps[3*len(gaps)//4]*100:.2f}%  max={gaps[-1]*100:.2f}%")

    # Sample of biggest artifacts
    print(f"\n  Top 10 'pure artifact' big winners (highest optimistic %, but small 1-min %):")
    print(f"  {'Date':<12} {'Win':<4} {'Ticker':<6} {'Sig':<8} {'Entry':>8} "
          f"{'Exit5m':>8} {'Exit1m':>8} {'ExitOpt':>8} "
          f"{'%5m':>7} {'%1m':>7} {'%opt':>7}")
    by_opt_pct = sorted(buckets["opt_only"], key=lambda r: -r["pct_opt"])[:10]
    for r in by_opt_pct:
        print(
            f"  {r['date']:<12} {r['win']:<4} {r['ticker']:<6} {r['sig']:<8} "
            f"{r['entry']:>8.2f} {r['exit_5min']:>8.2f} {r['exit_1min']:>8.2f} "
            f"{r['exit_opt']:>8.2f} "
            f"{r['pct_5min']*100:>+6.2f}% {r['pct_1min']*100:>+6.2f}% {r['pct_opt']*100:>+6.2f}%"
        )

    # Per-window breakdown of artifact P&L
    print(f"\n  Per-window: artifact vs achievable big-winner impact")
    win_stats = defaultdict(lambda: {"artifact_cap_opt": 0.0, "artifact_cap_5min": 0.0,
                                     "reachable_cap_opt": 0.0, "reachable_cap_5min": 0.0,
                                     "reachable_cap_1min": 0.0,
                                     "n_artifact": 0, "n_reachable": 0})
    for r in artifact:
        s = win_stats[r["win"]]
        s["n_artifact"] += 1
        s["artifact_cap_opt"] += r["pnl_opt_cap"]
        s["artifact_cap_5min"] += r["pnl_5min_cap"]
    for r in reachable:
        s = win_stats[r["win"]]
        s["n_reachable"] += 1
        s["reachable_cap_opt"] += r["pnl_opt_cap"]
        s["reachable_cap_5min"] += r["pnl_5min_cap"]
        s["reachable_cap_1min"] += r["pnl_1min_cap"]
    print(f"  {'Win':<4} {'#Artifact':>9} {'Art Opt$':>10} {'Art 5m$':>10} "
          f"{'#Reach':>7} {'Reach Opt$':>11} {'Reach 5m$':>11} {'Reach 1m$':>11}")
    for w in sorted(win_stats.keys()):
        s = win_stats[w]
        print(
            f"  {w:<4} {s['n_artifact']:>9} "
            f"{s['artifact_cap_opt']:>+10.2f} {s['artifact_cap_5min']:>+10.2f} "
            f"{s['n_reachable']:>7} "
            f"{s['reachable_cap_opt']:>+11.2f} {s['reachable_cap_5min']:>+11.2f} "
            f"{s['reachable_cap_1min']:>+11.2f}"
        )


if __name__ == "__main__":
    main()

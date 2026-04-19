"""
Analyze trades bucketed by hold duration (mins_held).
Buckets: 0, 5, 10, 15, 20, 30, 60, 120, 120+ min.
Shows capital-weighted P&L impact per bucket and counterfactual.

Runs two configs for comparison:
  - Baseline: standard entry (no confirmation delay)
  - Confirmed: 1-bar delay, price must still be above OR high (BULL) / below OR low (BEAR),
               hard stop = avg of last 3 bars' low (BULL) / high (BEAR)

bars_held / mins_held live in the raw backtest DataFrames (all_window_results),
not in the aggregated trade_rows — so we cross-join by (window, ticker, date).
"""
import sys
from datetime import date

sys.path.insert(0, "/Users/victorhuang/work/alpha_tech_tracker")

from alpaca.data.enums import DataFeed

from alpha_tech_tracker.op_momentum_strategy.op_momentum_selector_backtest import (
    run_selector_backtest,
    _apply_capital_flow,
    DEFAULT_TICKERS,
)

WINDOWS_RAW = [
    {"label": "M1", "opening_start": "09:30", "opening_bars": 3},
    {"label": "A1", "opening_start": "13:15", "opening_bars": 1},
    {"label": "A2", "opening_start": "15:00", "opening_bars": 1},
]
START = date(2025, 1, 1)   # overridden by --year CLI arg
END = date(2025, 12, 31)  # overridden by --year CLI arg
TOP_N = 2
WEIGHTS = [0.60, 0.40]
MORNING_SPLIT = [1.0]
CAPITAL = 10_000

BUCKET_ORDER = ["0 min", "5 min", "10 min", "15 min", "20 min", "30 min", "60 min", "120 min", "120+ min"]
SHORT_DURATION_MINS = 10


def bucket_label(mins_held):
    if mins_held == 0:
        return "0 min"
    elif mins_held == 5:
        return "5 min"
    elif mins_held == 10:
        return "10 min"
    elif mins_held == 15:
        return "15 min"
    elif mins_held == 20:
        return "20 min"
    elif mins_held <= 30:
        return "30 min"
    elif mins_held <= 60:
        return "60 min"
    elif mins_held <= 120:
        return "120 min"
    else:
        return "120+ min"


def stats_for_trades(trades):
    """Use cap_pnl (capital-weighted dollar P&L) for all stats."""
    if not trades:
        return {"count": 0, "wins": 0, "losses": 0, "win_rate": 0.0,
                "avg_pnl": 0.0, "total_pnl": 0.0, "avg_win": 0.0, "avg_loss": 0.0}
    wins = [t for t in trades if t["cap_pnl"] > 0]
    losses = [t for t in trades if t["cap_pnl"] <= 0]
    total_pnl = sum(t["cap_pnl"] for t in trades)
    avg_pnl = total_pnl / len(trades)
    avg_win = sum(t["cap_pnl"] for t in wins) / len(wins) if wins else 0.0
    avg_loss = sum(t["cap_pnl"] for t in losses) / len(losses) if losses else 0.0
    return {
        "count": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": len(wins) / len(trades) * 100,
        "avg_pnl": avg_pnl,
        "total_pnl": total_pnl,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
    }


def enrich_trades(trade_rows, all_window_results):
    """Cross-join trade_rows with raw backtest to attach mins_held."""
    bt_lookup = {}
    for window_label, ticker_results in all_window_results.items():
        for ticker, df in ticker_results.items():
            if df is None or df.empty:
                continue
            primary = df[
                (df["is_reversal"] != True)  # noqa: E712
                & (df["is_bearish_reentry"] != True)  # noqa: E712
                & (df["is_bullish_reentry"] != True)  # noqa: E712
            ]
            for _, row in primary.iterrows():
                key = (window_label, ticker, row["date"])
                bt_lookup[key] = row

    enriched = []
    missing = 0
    for t in trade_rows:
        if t.get("skipped"):
            continue
        key = (t["window"], t["ticker"], t["date"])
        raw_row = bt_lookup.get(key)
        if raw_row is None:
            missing += 1
            mins = None
        else:
            mins = int(raw_row.get("mins_held", 0))
        enriched.append({**t, "mins_held": mins})

    if missing:
        print(f"WARNING: {missing} trades could not be matched to raw backtest rows.\n")

    return [t for t in enriched if t["mins_held"] is not None]


def run_and_enrich(label="BASELINE", min_or_range=0.0, min_or_range_windows=None,
                   filter_flat_or=True):
    print(f"\n[{label}] Running backtest {START} → {END} ...")
    trade_rows, all_window_results, _ = run_selector_backtest(
        n=TOP_N,
        tickers=DEFAULT_TICKERS,
        eval_start=START,
        eval_end=END,
        windows=WINDOWS_RAW,
        enable_reversal=True,
        enable_bearish_reentry=True,
        enable_bullish_reentry=True,
        enable_doubledown=True,
        doubledown_start_min=10,
        feed=DataFeed.IEX,
        min_or_range=min_or_range,
        min_or_range_windows=min_or_range_windows,
        filter_flat_or=filter_flat_or,
    )

    _apply_capital_flow(
        trade_rows,
        WINDOWS_RAW,
        CAPITAL,
        WEIGHTS,
        TOP_N,
        morning_split=MORNING_SPLIT,
        compound=False,
        enable_doubledown=True,
    )

    valid = enrich_trades(trade_rows, all_window_results)
    print(f"[{label}] Total selected trades: {len(valid)}")
    return valid


def print_short_duration_detail(trades, threshold_mins):
    """Print per-trade listing for trades held ≤ threshold_mins."""
    short = [t for t in trades if t["mins_held"] <= threshold_mins]
    if not short:
        print(f"  No trades held ≤ {threshold_mins} min.\n")
        return

    short.sort(key=lambda t: (t["date"], t["window"], t["mins_held"]))

    print(f"\n  {'Date':<12}  {'Win':<4}  {'Tkr':<6}  {'Dir':<8}  {'Mins':>5}  "
          f"{'ExitReason':<22}  {'Entry':>8}  {'Exit':>8}  {'CapP&L':>9}")
    print("  " + "─" * 100)
    for t in short:
        signal = t.get("signal", "")
        direction = "BULL" if signal == "BULLISH" else "BEAR" if signal == "BEARISH" else signal
        entry = t.get("entry_price") or t.get("entry_mid", 0)
        exit_ = t.get("exit_price") or t.get("exit_mid", 0)
        exit_reason = t.get("exit_reason", "")
        win_flag = "W" if t["cap_pnl"] > 0 else "L"
        print(
            f"  {str(t['date']):<12}  {win_flag:<4}  {t['ticker']:<6}  {direction:<8}  "
            f"{t['mins_held']:>5}  {exit_reason:<22}  {float(entry):>8.2f}  "
            f"{float(exit_):>8.2f}  {t['cap_pnl']:>+9.2f}"
        )
    print()


def print_bucket_table(valid, title):
    buckets = {b: [] for b in BUCKET_ORDER}
    for t in valid:
        buckets[bucket_label(t["mins_held"])].append(t)

    s_all = stats_for_trades(valid)

    print("\n" + "━" * 94)
    print(f"  {title}")
    print("━" * 94)
    print(f"  {'Bucket':<12}  {'Count':>6}  {'Wins':>5}  {'Loss':>5}  {'WinRate':>8}  "
          f"{'Avg P&L':>9}  {'Avg Win':>9}  {'Avg Loss':>9}  {'Total P&L':>11}")
    print("  " + "─" * 90)

    for bucket in BUCKET_ORDER:
        trades = buckets[bucket]
        if not trades:
            print(f"  {bucket:<12}  {'0':>6}")
            continue
        s = stats_for_trades(trades)
        marker = " ◄" if bucket in ("0 min", "5 min", "10 min") else ""
        print(
            f"  {bucket:<12}  {s['count']:>6}  {s['wins']:>5}  {s['losses']:>5}  "
            f"{s['win_rate']:>7.0f}%  {s['avg_pnl']:>+9.2f}  {s['avg_win']:>+9.2f}  "
            f"{s['avg_loss']:>+9.2f}  {s['total_pnl']:>+11.2f}{marker}"
        )

    print("  " + "─" * 90)
    print(
        f"  {'ALL':.<12}  {s_all['count']:>6}  {s_all['wins']:>5}  {s_all['losses']:>5}  "
        f"{s_all['win_rate']:>7.0f}%  {s_all['avg_pnl']:>+9.2f}  {s_all['avg_win']:>+9.2f}  "
        f"{s_all['avg_loss']:>+9.2f}  {s_all['total_pnl']:>+11.2f}"
    )
    return buckets, s_all


def print_counterfactual(valid, s_all):
    print("\n" + "━" * 74)
    print("  COUNTERFACTUAL: P&L impact of removing short-duration trades")
    print("━" * 74)

    thresholds = [0, 5, 10, 15, 20, 30, 60, 120]
    total_pnl = s_all["total_pnl"]

    print(f"\n  {'Filter out ≤':<16}  {'Kept':>5}  {'Removed':>7}  "
          f"{'WR kept':>8}  {'P&L kept':>10}  {'Delta':>10}  {'Impact'}")
    print("  " + "─" * 72)
    for thr in thresholds:
        kept = [t for t in valid if t["mins_held"] > thr]
        removed = [t for t in valid if t["mins_held"] <= thr]
        if not removed:
            continue
        s_kept = stats_for_trades(kept)
        delta = s_kept["total_pnl"] - total_pnl
        impact = "BETTER" if delta > 0 else "WORSE"
        print(
            f"  {thr:>3} min trades   {len(kept):>5}  {len(removed):>7}  "
            f"{s_kept['win_rate']:>7.0f}%  {s_kept['total_pnl']:>+10.2f}  "
            f"{delta:>+10.2f}  {impact}"
        )


def print_per_window_breakdown(valid):
    print("\n" + "━" * 80)
    print("  PER-WINDOW × BUCKET BREAKDOWN")
    print("━" * 80)
    window_labels = sorted({t["window"] for t in valid})

    for wlabel in window_labels:
        w_trades = [t for t in valid if t["window"] == wlabel]
        s_w = stats_for_trades(w_trades)
        w_short = [t for t in w_trades if t["mins_held"] <= SHORT_DURATION_MINS]
        print(f"\n  Window {wlabel}  ({len(w_trades)} trades | WR {s_w['win_rate']:.0f}% | "
              f"total P&L {s_w['total_pnl']:+.2f} | short ≤{SHORT_DURATION_MINS}min: {len(w_short)})")
        print(f"  {'Bucket':<12}  {'Count':>5}  {'WinRate':>8}  {'Avg P&L':>9}  "
              f"{'Avg Win':>9}  {'Avg Loss':>9}  {'Total P&L':>11}")
        print("  " + "─" * 60)
        for bucket in BUCKET_ORDER:
            bt = [t for t in w_trades if bucket_label(t["mins_held"]) == bucket]
            if not bt:
                continue
            s2 = stats_for_trades(bt)
            marker = " ◄" if bucket in ("0 min", "5 min", "10 min") else ""
            print(f"  {bucket:<12}  {s2['count']:>5}  {s2['win_rate']:>7.0f}%  "
                  f"{s2['avg_pnl']:>+9.2f}  {s2['avg_win']:>+9.2f}  "
                  f"{s2['avg_loss']:>+9.2f}  {s2['total_pnl']:>+11.2f}{marker}")


def print_comparison(baseline, filtered, filter_label):
    s_base = stats_for_trades(baseline)
    s_filt = stats_for_trades(filtered)
    base_short = [t for t in baseline if t["mins_held"] <= SHORT_DURATION_MINS]
    filt_short = [t for t in filtered if t["mins_held"] <= SHORT_DURATION_MINS]
    s_base_short = stats_for_trades(base_short)
    s_filt_short = stats_for_trades(filt_short)

    removed = [t for t in baseline if not any(
        f["date"] == t["date"] and f["ticker"] == t["ticker"] and f["window"] == t["window"]
        for f in filtered
    )]

    print("\n" + "━" * 80)
    print(f"  BASELINE vs {filter_label} — side-by-side comparison")
    print("━" * 80)
    print(f"\n  {'Metric':<30}  {'Baseline':>12}  {filter_label:>16}  {'Delta':>10}")
    print("  " + "─" * 74)
    rows = [
        ("Total trades", f"{s_base['count']}", f"{s_filt['count']}",
         f"{s_filt['count'] - s_base['count']:+d}"),
        ("Win rate", f"{s_base['win_rate']:.1f}%", f"{s_filt['win_rate']:.1f}%",
         f"{s_filt['win_rate'] - s_base['win_rate']:+.1f}pp"),
        ("Total cap P&L", f"${s_base['total_pnl']:+.2f}", f"${s_filt['total_pnl']:+.2f}",
         f"${s_filt['total_pnl'] - s_base['total_pnl']:+.2f}"),
        ("Avg P&L / trade", f"${s_base['avg_pnl']:+.2f}", f"${s_filt['avg_pnl']:+.2f}",
         f"${s_filt['avg_pnl'] - s_base['avg_pnl']:+.2f}"),
        (f"Short (≤{SHORT_DURATION_MINS}min) count",
         f"{len(base_short)}", f"{len(filt_short)}",
         f"{len(filt_short) - len(base_short):+d}"),
        ("Short total P&L",
         f"${s_base_short['total_pnl']:+.2f}", f"${s_filt_short['total_pnl']:+.2f}",
         f"${s_filt_short['total_pnl'] - s_base_short['total_pnl']:+.2f}"),
    ]
    for metric, bval, cval, delta in rows:
        print(f"  {metric:<30}  {bval:>12}  {cval:>16}  {delta:>10}")

    # Show the removed trades
    if removed:
        print(f"\n  Removed {len(removed)} trade(s) (flat OR range = 0):")
        print(f"\n  {'Date':<12}  {'Win':<4}  {'Tkr':<6}  {'Dir':<8}  {'Win':>5}  "
              f"{'ExitReason':<22}  {'Entry':>8}  {'Exit':>8}  {'CapP&L':>9}")
        print("  " + "─" * 90)
        for t in sorted(removed, key=lambda x: (x["date"], x["window"])):
            signal = t.get("signal", "")
            direction = "BULL" if signal == "BULLISH" else "BEAR"
            entry = t.get("entry_price") or t.get("entry_mid", 0)
            exit_ = t.get("exit_price") or t.get("exit_mid", 0)
            win_flag = "W" if t["cap_pnl"] > 0 else "L"
            print(
                f"  {str(t['date']):<12}  {win_flag:<4}  {t['ticker']:<6}  {direction:<8}  "
                f"{t.get('mins_held', '?'):>5}  {t.get('exit_reason', ''):.<22}  "
                f"{float(entry):>8.2f}  {float(exit_):>8.2f}  {t['cap_pnl']:>+9.2f}"
            )

    print_bucket_table(baseline, "BASELINE — ALL BUCKETS")
    print_bucket_table(filtered, f"{filter_label} — ALL BUCKETS")


def main():
    # flat-OR filter is always on for all runs (matches live engine behavior)
    base = run_and_enrich(label="flat-OR (base)", filter_flat_or=True)
    s_base = stats_for_trades(base)

    thresholds = [0.05, 0.08, 0.10, 0.12]
    results = [(base, "flat-OR (base)", 0.0)]
    for pct in thresholds:
        label = f"minOR≥{pct:.2f}%"
        valid = run_and_enrich(label=label, filter_flat_or=True, min_or_range=pct)
        results.append((valid, label, pct))

    # ── Sweep summary table ───────────────────────────────────────────────────
    print("\n" + "━" * 110)
    print("  OR RANGE % SWEEP (flat-OR always filtered) — all windows")
    print("━" * 110)
    print(f"  {'Config':<20}  {'Trades':>6}  {'Removed':>7}  {'WR':>6}  "
          f"{'Total P&L':>11}  {'Delta':>10}  {'Avg/trade':>9}  "
          f"{'Short≤10m':>9}  {'Short P&L':>10}")
    print("  " + "─" * 106)

    for valid, label, pct in results:
        s = stats_for_trades(valid)
        short = [t for t in valid if t["mins_held"] <= SHORT_DURATION_MINS]
        s_short = stats_for_trades(short)
        removed = s_base["count"] - s["count"]
        delta = s["total_pnl"] - s_base["total_pnl"]
        delta_str = f"{delta:+.2f}" if pct > 0 else "—"
        removed_str = str(removed) if pct > 0 else "—"
        print(
            f"  {label:<20}  {s['count']:>6}  {removed_str:>7}  {s['win_rate']:>5.1f}%  "
            f"{s['total_pnl']:>+11.2f}  {delta_str:>10}  {s['avg_pnl']:>+9.2f}  "
            f"{len(short):>9}  {s_short['total_pnl']:>+10.2f}"
        )

    # ── Per-bucket table for each threshold ──────────────────────────────────
    for valid, label, pct in results:
        print_bucket_table(valid, f"{label} — ALL BUCKETS")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, help="Run for a single calendar year")
    args = parser.parse_args()
    if args.year:
        START = date(args.year, 1, 1)
        END = date(args.year, 12, 31)
    main()

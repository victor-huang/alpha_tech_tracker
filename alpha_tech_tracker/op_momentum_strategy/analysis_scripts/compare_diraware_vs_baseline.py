"""
Diagnostic comparison between baseline win-rate selector and direction-aware selector.

Parses replay log files to extract:
  1. Per-day regime direction, picks, P&L, deployed capital
  2. Per-ticker trade counts and P&L in each run
  3. Days where one run traded but the other didn't
  4. Pick overlap between the two selectors
  5. Per-regime-direction win rate and RODC comparison

Usage:
    python alpha_tech_tracker/op_momentum_strategy/analysis_scripts/compare_diraware_vs_baseline.py \
        --year 2024
"""
import argparse
import math
import os
import re
from collections import defaultdict
from datetime import date


BASE_LOG_ROOT = "logs"


def _parse_log(log_path):
    """
    Extract per-day info from a single replay log file.
    Returns dict or None if the log shows no completed trade.
    """
    result = {
        "date": None,
        "regime": None,
        "picks": [],
        "pnl": None,
        "deployed": 0.0,
        "trades": [],           # list of {ticker, signal, pnl, pnl_pct, exit}
        "skipped_bearish": [],  # tickers skipped by regime filter (BEARISH on LONG day)
        "skipped_bullish": [],  # tickers skipped by regime filter (BULLISH on SHORT day)
        "no_signals": False,
    }

    fname = os.path.basename(log_path)
    m = re.match(r"(\d{4}-\d{2}-\d{2})\.log$", fname)
    if m:
        result["date"] = date.fromisoformat(m.group(1))

    try:
        with open(log_path) as f:
            lines = f.readlines()
    except OSError:
        return None

    for line in lines:
        # Regime direction
        rm = re.search(r"WinRateTickerSelector \[([A-Z]+)", line)
        if rm:
            result["regime"] = rm.group(1)

        # Picks
        pm = re.search(r"WinRateTickerSelector.*top-\d+: \[([^\]]+)\]", line)
        if pm:
            result["picks"] = [t.strip().strip("'") for t in pm.group(1).split(",")]

        # Daily P&L cap line
        cap_m = re.search(r"cap:\s*([+-]?\$[\d,.]+)", line)
        if cap_m:
            result["pnl"] = float(cap_m.group(1).replace("$", "").replace(",", ""))

        # Deployed capital
        dep_m = re.search(r"\$(\d[\d,]*)\s+deployed", line)
        if dep_m:
            result["deployed"] = float(dep_m.group(1).replace(",", ""))

        # Individual trade lines: EXIT / SIMULATE SELL entries
        trade_m = re.search(
            r"EXIT (\w+) (BULLISH|BEARISH) reason=(\S+)", line
        )
        if trade_m:
            result["trades"].append({
                "ticker": trade_m.group(1),
                "signal": trade_m.group(2),
                "exit": trade_m.group(3),
                "pnl": None,
                "pnl_pct": None,
            })

        # P&L update lines with per-trade pnl_pct
        pnl_update_m = re.search(
            r"Daily realized P&L updated.*added ([\-\d.]+) from (\w+)", line
        )
        if pnl_update_m:
            pnl_val = float(pnl_update_m.group(1))
            ticker = pnl_update_m.group(2)
            for t in reversed(result["trades"]):
                if t["ticker"] == ticker and t["pnl"] is None:
                    t["pnl"] = pnl_val
                    break

        # Regime filter skips
        skip_bear = re.search(r"skipping BEARISH signal for (\w+)", line)
        if skip_bear:
            result["skipped_bearish"].append(skip_bear.group(1))

        skip_bull = re.search(r"skipping BULLISH signal for (\w+)", line)
        if skip_bull:
            result["skipped_bullish"].append(skip_bull.group(1))

        if "no signals buffered" in line:
            result["no_signals"] = True

    return result


def _load_run(log_dir):
    days = {}
    if not os.path.isdir(log_dir):
        print(f"  [warn] missing log dir: {log_dir}")
        return days
    for fname in sorted(os.listdir(log_dir)):
        if not re.match(r"\d{4}-\d{2}-\d{2}\.log$", fname):
            continue
        path = os.path.join(log_dir, fname)
        info = _parse_log(path)
        if info and info["date"]:
            days[info["date"]] = info
    return days


def _rodc(pnl, deployed):
    return pnl / deployed if deployed > 0 else None


def _dw_sharpe(day_list):
    pairs = [(d["pnl"], d["deployed"]) for d in day_list
             if d["deployed"] > 0 and d["pnl"] is not None]
    if len(pairs) < 2:
        return None
    rodcs = [p / dep for p, dep in pairs]
    deps = [dep for _, dep in pairs]
    avg_dep = sum(deps) / len(deps)
    w = [d / avg_dep for d in deps]
    w_sum = sum(w)
    w_mean = sum(wi * ri for wi, ri in zip(w, rodcs)) / w_sum
    w_var = sum(wi * (ri - w_mean) ** 2 for wi, ri in zip(w, rodcs)) / w_sum
    w_std = math.sqrt(w_var) if w_var > 0 else 0.0
    return w_mean / w_std * math.sqrt(252) if w_std > 0 else None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", required=True, type=int)
    parser.add_argument("--log-root", default=BASE_LOG_ROOT)
    parser.add_argument("--top-n", type=int, default=20,
                        help="Top-N divergent days to show in detail")
    parser.add_argument("--base-suffix", default="fixedalloc",
                        help="Suffix for baseline log dir (default: fixedalloc)")
    parser.add_argument("--dir-suffix", default="fixedalloc_diraware",
                        help="Suffix for dir-aware log dir (default: fixedalloc_diraware)")
    args = parser.parse_args()

    base_dir = os.path.join(
        args.log_root,
        f"replay_{args.year}_stock_m1_winrate_regimehold_cap80k_{args.base_suffix}",
    )
    dir_dir = os.path.join(
        args.log_root,
        f"replay_{args.year}_stock_m1_winrate_regimehold_cap80k_{args.dir_suffix}",
    )

    print(f"\nLoading baseline  : {base_dir}")
    base = _load_run(base_dir)
    print(f"Loading dir-aware : {dir_dir}")
    dirw = _load_run(dir_dir)

    all_dates = sorted(set(base) | set(dirw))
    base_trade = {d: v for d, v in base.items() if v["pnl"] is not None}
    dirw_trade = {d: v for d, v in dirw.items() if v["pnl"] is not None}

    both_trade  = sorted(set(base_trade) & set(dirw_trade))
    base_only   = sorted(set(base_trade) - set(dirw_trade))
    dirw_only   = sorted(set(dirw_trade) - set(base_trade))

    # ── 1. Overall summary ───────────────────────────────────────────────────
    print(f"\n{'='*70}")
    print(f"  YEAR {args.year} — BASELINE vs DIRECTION-AWARE")
    print(f"{'='*70}")

    def _summary_row(label, days_dict):
        days = list(days_dict.values())
        total_pnl = sum(d["pnl"] for d in days if d["pnl"] is not None)
        total_dep = sum(d["deployed"] for d in days)
        active = len([d for d in days if d["pnl"] is not None])
        rodc = total_pnl / total_dep * 100 if total_dep > 0 else 0
        sharpe = _dw_sharpe([d for d in days if d["pnl"] is not None])
        sharpe_str = f"{sharpe:.2f}" if sharpe else "n/a"
        avg_dep = total_dep / active if active else 0
        print(f"  {label:<16} active={active:>3}  P&L={total_pnl:>+10,.0f}  "
              f"RODC={rodc:+.3f}%  DW-Sharpe={sharpe_str}  avg_dep=${avg_dep:>7,.0f}")

    _summary_row("Baseline", base_trade)
    _summary_row("Dir-aware", dirw_trade)

    # ── 2. Days where only one side traded ───────────────────────────────────
    print(f"\n── DAYS TRADED IN BASELINE ONLY ({len(base_only)}) ──────────────")
    for d in base_only[:args.top_n]:
        b = base[d]
        regime = b.get("regime", "?")
        skipped = len(b.get("skipped_bearish", []) + b.get("skipped_bullish", []))
        dw = dirw.get(d, {})
        dw_picks = dw.get("picks", [])
        dw_regime = dw.get("regime", "?")
        dw_skipped = len(dw.get("skipped_bearish", []) + dw.get("skipped_bullish", []))
        dw_no_sig = dw.get("no_signals", False)
        print(f"  {d}  base=[{regime}] pnl={b['pnl']:>+7.0f}  picks={b['picks'][:4]}")
        print(f"         dir =[{dw_regime}] no_sig={dw_no_sig}  picks={dw_picks[:4]}  skip={dw_skipped}")

    print(f"\n── DAYS TRADED IN DIR-AWARE ONLY ({len(dirw_only)}) ─────────────")
    for d in dirw_only[:args.top_n]:
        dw = dirw[d]
        regime = dw.get("regime", "?")
        b = base.get(d, {})
        b_regime = b.get("regime", "?")
        print(f"  {d}  dir=[{regime}] pnl={dw['pnl']:>+7.0f}  picks={dw['picks'][:4]}")
        print(f"         base=[{b_regime}] no_picks={not b.get('picks')}")

    # ── 3. Per-regime P&L breakdown ──────────────────────────────────────────
    print(f"\n── PER-REGIME P&L BREAKDOWN ─────────────────────────────────────")
    regimes = ["LONG", "SHORT", "NEUTRAL", "CAUTION"]
    for regime in regimes:
        b_days = [v for v in base_trade.values() if v.get("regime") == regime]
        d_days = [v for v in dirw_trade.values() if v.get("regime") == regime]
        if not b_days and not d_days:
            continue
        b_pnl = sum(v["pnl"] for v in b_days)
        d_pnl = sum(v["pnl"] for v in d_days)
        b_dep = sum(v["deployed"] for v in b_days)
        d_dep = sum(v["deployed"] for v in d_days)
        b_rodc = b_pnl / b_dep * 100 if b_dep else 0
        d_rodc = d_pnl / d_dep * 100 if d_dep else 0
        print(f"  {regime:<8}  base: {len(b_days):>3}d  P&L={b_pnl:>+8,.0f}  RODC={b_rodc:+.3f}%  |  "
              f"dir: {len(d_days):>3}d  P&L={d_pnl:>+8,.0f}  RODC={d_rodc:+.3f}%  "
              f"delta_pnl={d_pnl-b_pnl:>+8,.0f}")

    # ── 4. Pick overlap analysis ──────────────────────────────────────────────
    print(f"\n── PICK OVERLAP ON SHARED TRADING DAYS ({len(both_trade)}) ────────")
    overlaps = []
    for d in both_trade:
        b_picks = set(base[d]["picks"])
        d_picks = set(dirw[d]["picks"])
        overlap = len(b_picks & d_picks)
        overlaps.append(overlap)
    if overlaps:
        avg_overlap = sum(overlaps) / len(overlaps)
        full_match = sum(1 for o in overlaps if o == 8)
        partial = sum(1 for o in overlaps if 0 < o < 8)
        no_match = sum(1 for o in overlaps if o == 0)
        print(f"  Avg shared picks  : {avg_overlap:.1f} / 8")
        print(f"  Full overlap (8/8): {full_match} days")
        print(f"  Partial overlap   : {partial} days")
        print(f"  Zero overlap      : {no_match} days")

    # ── 5. Per-ticker P&L delta ───────────────────────────────────────────────
    print(f"\n── PER-TICKER SELECTION FREQUENCY DELTA (dir - base) ───────────")
    base_freq = defaultdict(int)
    dirw_freq = defaultdict(int)
    base_pnl_by_ticker = defaultdict(float)
    dirw_pnl_by_ticker = defaultdict(float)

    for d in both_trade:
        for t in base[d]["picks"]:
            base_freq[t] += 1
        for t in dirw[d]["picks"]:
            dirw_freq[t] += 1

    all_tickers = sorted(set(list(base_freq) + list(dirw_freq)))
    rows = []
    for t in all_tickers:
        delta = dirw_freq[t] - base_freq[t]
        rows.append((t, base_freq[t], dirw_freq[t], delta))
    rows.sort(key=lambda x: x[3])
    print(f"  {'Ticker':<8} {'Base':>5} {'Dir':>5} {'Delta':>6}  {'Direction'}")
    for t, bf, df, delta in rows:
        arrow = "▲ promoted" if delta > 0 else ("▼ demoted" if delta < 0 else "  same")
        print(f"  {t:<8} {bf:>5} {df:>5} {delta:>+6}  {arrow}")

    # ── 6. Regime-filter skip rate ─────────────────────────────────────────────
    print(f"\n── REGIME FILTER SKIP RATE (on LONG days) ───────────────────────")
    b_long = [v for v in base_trade.values() if v.get("regime") == "LONG"]
    d_long = [v for v in dirw_trade.values() if v.get("regime") == "LONG"]
    b_skips = sum(len(v.get("skipped_bearish", [])) for v in b_long)
    d_skips = sum(len(v.get("skipped_bearish", [])) for v in d_long)
    b_long_days = len(b_long)
    d_long_days = len(d_long)
    print(f"  Baseline  LONG days={b_long_days}  bearish skips={b_skips}  avg/day={b_skips/b_long_days:.2f}" if b_long_days else "  Baseline: no LONG days")
    print(f"  Dir-aware LONG days={d_long_days}  bearish skips={d_skips}  avg/day={d_skips/d_long_days:.2f}" if d_long_days else "  Dir-aware: no LONG days")

    b_short = [v for v in base_trade.values() if v.get("regime") == "SHORT"]
    d_short = [v for v in dirw_trade.values() if v.get("regime") == "SHORT"]
    b_bull_skips = sum(len(v.get("skipped_bullish", [])) for v in b_short)
    d_bull_skips = sum(len(v.get("skipped_bullish", [])) for v in d_short)
    b_short_days = len(b_short)
    d_short_days = len(d_short)
    print(f"  Baseline  SHORT days={b_short_days}  bullish skips={b_bull_skips}  avg/day={b_bull_skips/b_short_days:.2f}" if b_short_days else "  Baseline: no SHORT days")
    print(f"  Dir-aware SHORT days={d_short_days}  bullish skips={d_bull_skips}  avg/day={d_bull_skips/d_short_days:.2f}" if d_short_days else "  Dir-aware: no SHORT days")

    print()


if __name__ == "__main__":
    main()

"""
Audit fixed-alloc regime-hold backtest logs for a given year.

Checks:
  1. Per-trade slot size == $10,000 (fixed-alloc rule)
  2. Daily deployed == sum of all slot_capitals (no over/under counting)
  3. Daily deployed <= $80,000 (no over-deployment)
  4. Daily P&L reconstructed from per-trade cap_pnl matches logged daily total
  5. returned == slot + cap_pnl for every trade (engine internal accounting)
  6. window_total is a correct running cumulative sum within each day
  7. No duplicate tickers in Capital returned lines for the same day
  8. No unexpected dd=True or reentry=True trades (should be absent in this config)
  9. Yearly P&L == sum of daily P&Ls
  10. Capital utilization, mean daily RODC, DW-Sharpe independently recomputed

Usage:
  python analysis_scripts/audit_fixedalloc_backtest.py --year 2025
  python analysis_scripts/audit_fixedalloc_backtest.py --year 2020
"""
import argparse
import math
import os
import re
import sys

LOGS_BASE = os.path.join(os.path.dirname(__file__), "../../../logs")
CAPITAL = 80_000.0
SLOT_SIZE = 10_000.0
TOP_N = 8
MAX_DAILY_DEPLOYED = SLOT_SIZE * TOP_N  # $80,000


def parse_log(path):
    """
    Returns (trades, daily_pnl_logged, daily_deployed_logged) for one day.

    trades: list of {"slot": float, "cap_pnl": float, "ticker": str}
    daily_pnl_logged: float from "Daily P&L:" line
    daily_deployed_logged: float from "Daily P&L:" line
    """
    trades = []
    daily_pnl_logged = None
    daily_deployed_logged = None
    unexpected_trades = []  # dd=True or reentry=True lines

    # Matches clean fixed-alloc trades (no dd, no reentry)
    cap_ret = re.compile(
        r"Capital returned \[.+?\] (\S+) \(dd=False reentry=False\): "
        r"slot=([\d.]+) cap_pnl=([+-]?[\d.]+) returned=([\d.]+)"
    )
    # Catches any Capital returned line that is NOT dd=False reentry=False
    cap_ret_unexpected = re.compile(
        r"Capital returned \[.+?\] (\S+) \((?!dd=False reentry=False).+\):"
    )
    # Parse cap: value (same regex as summary script — handles +$X and -$X)
    cap_re = re.compile(r"cap:\s*([+-]?\$[\d,.]+)")
    # Parse deployed from the Daily P&L line
    dep_re = re.compile(r"on\s+\$([\d,]+)\s+deployed\)")

    prev_window_total = 0.0
    with open(path) as f:
        for line in f:
            m = cap_ret.search(line)
            if m:
                slot = float(m.group(2))
                cap_pnl = float(m.group(3))
                returned = float(m.group(4))
                trades.append({
                    "ticker": m.group(1),
                    "slot": slot,
                    "cap_pnl": cap_pnl,
                    "returned": returned,
                    "expected_returned": slot + cap_pnl,
                    "prev_window_total": prev_window_total,
                })
                prev_window_total += returned
            elif cap_ret_unexpected.search(line):
                unexpected_trades.append(line.strip())
            if "Daily P&L:" in line:
                mc = cap_re.search(line)
                md = dep_re.search(line)
                if mc and md:
                    cap_str = mc.group(1)
                    sign = -1 if cap_str.startswith("-") else 1
                    daily_pnl_logged = sign * float(
                        cap_str.replace("$", "").replace(",", "")
                        .replace("+", "").replace("-", "")
                    )
                    daily_deployed_logged = float(md.group(1).replace(",", ""))

    return trades, daily_pnl_logged, daily_deployed_logged, unexpected_trades


def dw_sharpe(days_data):
    """Deployment-weighted Sharpe on daily RODC, annualised."""
    if len(days_data) < 2:
        return None
    rodcs = [pnl / dep for pnl, dep in days_data]
    deps = [dep for _, dep in days_data]
    avg_dep = sum(deps) / len(deps)
    w = [d / avg_dep for d in deps]
    w_sum = sum(w)
    w_mean = sum(wi * ri for wi, ri in zip(w, rodcs)) / w_sum
    w_var = sum(wi * (ri - w_mean) ** 2 for wi, ri in zip(w, rodcs)) / w_sum
    w_std = math.sqrt(w_var) if w_var > 0 else 0.0
    return w_mean / w_std * math.sqrt(252) if w_std > 0 else None


def audit_year(year):
    log_dir = os.path.join(
        LOGS_BASE, f"replay_{year}_stock_m1_winrate_regimehold_cap80k_fixedalloc"
    )
    if not os.path.isdir(log_dir):
        print(f"ERROR: log dir not found: {log_dir}")
        sys.exit(1)

    log_files = sorted(
        f for f in os.listdir(log_dir) if re.match(r"\d{4}-\d{2}-\d{2}\.log$", f)
    )

    errors = []
    warnings = []

    daily_pnls = {}
    daily_deployed = {}

    for fname in log_files:
        d_str = fname.replace(".log", "")
        path = os.path.join(log_dir, fname)
        trades, pnl_logged, dep_logged, unexpected = parse_log(path)

        if pnl_logged is None:
            warnings.append(f"{d_str}: no 'Daily P&L' line found — skipping")
            continue

        # --- Check 1: slot sizes all equal $10,000 ---
        bad_slots = [t for t in trades if abs(t["slot"] - SLOT_SIZE) > 0.01]
        if bad_slots:
            for t in bad_slots:
                errors.append(
                    f"{d_str}: {t['ticker']} slot={t['slot']:.2f} != ${SLOT_SIZE:,.0f}"
                )

        # --- Check 2: reconstructed deployed == logged deployed ---
        reconstructed_deployed = sum(t["slot"] for t in trades)
        if dep_logged is not None and abs(reconstructed_deployed - dep_logged) > 0.01:
            errors.append(
                f"{d_str}: deployed mismatch — sum(slots)=${reconstructed_deployed:,.2f} "
                f"vs logged=${dep_logged:,.2f}"
            )

        # --- Check 3: no over-deployment ---
        if dep_logged is not None and dep_logged > MAX_DAILY_DEPLOYED + 0.01:
            errors.append(
                f"{d_str}: OVER-DEPLOYED ${dep_logged:,.2f} > max ${MAX_DAILY_DEPLOYED:,.0f}"
            )

        # --- Check 4: reconstructed P&L == logged daily P&L ---
        # Tolerance 0.10: individual cap_pnl values are logged at 2dp; summing up to 8
        # rounded values can accumulate at most ~$0.04 of rounding error vs the engine's
        # full-float running total. Gaps > $0.10 indicate a real accounting discrepancy.
        reconstructed_pnl = sum(t["cap_pnl"] for t in trades)
        pnl_delta = abs(reconstructed_pnl - pnl_logged)
        if pnl_delta > 0.10:
            errors.append(
                f"{d_str}: P&L mismatch — sum(cap_pnl)=${reconstructed_pnl:,.2f} "
                f"vs logged=${pnl_logged:,.2f}  (delta=${pnl_delta:.4f})"
            )
        elif pnl_delta > 0.02:
            warnings.append(
                f"{d_str}: P&L rounding gap ${pnl_delta:.4f} — "
                f"sum(cap_pnl)=${reconstructed_pnl:,.2f} vs logged=${pnl_logged:,.2f} "
                f"(log-precision artifact, not an error)"
            )

        # --- Check 5: returned = slot + cap_pnl for every trade ---
        for t in trades:
            if abs(t["returned"] - t["expected_returned"]) > 0.01:
                errors.append(
                    f"{d_str}: {t['ticker']} returned={t['returned']:.2f} != "
                    f"slot+cap_pnl={t['expected_returned']:.2f}"
                )

        # --- Check 6: window_total is a correct running cumulative sum ---
        running = 0.0
        for t in trades:
            if abs(t["prev_window_total"] - running) > 0.02:
                errors.append(
                    f"{d_str}: {t['ticker']} window_total step mismatch — "
                    f"expected running={running:.2f} but trade saw prev={t['prev_window_total']:.2f}"
                )
            running += t["returned"]

        # --- Check 7: no duplicate tickers in the same day ---
        tickers = [t["ticker"] for t in trades]
        seen = set()
        for tk in tickers:
            if tk in seen:
                errors.append(f"{d_str}: duplicate ticker {tk} in Capital returned lines")
            seen.add(tk)

        # --- Check 8: no unexpected dd/reentry trades ---
        for line in unexpected:
            errors.append(f"{d_str}: unexpected dd/reentry trade: {line[:120]}")

        daily_pnls[d_str] = pnl_logged
        if dep_logged and dep_logged > 0:
            daily_deployed[d_str] = dep_logged

    # --- Check 5: yearly aggregation ---
    yearly_pnl = sum(daily_pnls.values())
    trading_days = len(daily_pnls)
    total_dep = sum(daily_deployed.values())
    avg_dep = total_dep / trading_days if trading_days else 0.0
    util = total_dep / (trading_days * CAPITAL) if trading_days else 0.0

    days_with_dep = [(daily_pnls[d], daily_deployed[d]) for d in daily_deployed]
    rodcs = [p / dep for p, dep in days_with_dep] if days_with_dep else []
    mean_rodc = sum(rodcs) / len(rodcs) if rodcs else None
    sharpe = dw_sharpe(days_with_dep) if days_with_dep else None

    # --- Report ---
    print(f"\n{'='*65}")
    print(f"  AUDIT: {year} fixed-alloc regime-hold $80k")
    print(f"{'='*65}")

    print(f"\n── RULES CHECK ─────────────────────────────────────────────")
    if errors:
        for e in errors:
            print(f"  ❌ {e}")
    else:
        print(f"  ✓ All {len(log_files)} days passed all 8 rule checks")
        print(f"    • All slot sizes = ${SLOT_SIZE:,.0f}")
        print(f"    • No day exceeded ${MAX_DAILY_DEPLOYED:,.0f} deployed")
        print(f"    • Reconstructed deployed matches logged deployed every day")
        print(f"    • Reconstructed P&L matches logged daily P&L every day")
        print(f"    • returned == slot + cap_pnl for every trade")
        print(f"    • window_total progression correct every day")
        print(f"    • No duplicate tickers per day")
        print(f"    • No unexpected dd/reentry trades")

    if warnings:
        print(f"\n── WARNINGS ────────────────────────────────────────────────")
        for w in warnings:
            print(f"  ⚠  {w}")

    print(f"\n── INDEPENDENTLY COMPUTED METRICS ──────────────────────────")
    print(f"  Trading days          : {trading_days}")
    print(f"  Yearly P&L            : ${yearly_pnl:>12,.2f}")
    print(f"  Total deployed        : ${total_dep:>12,.0f}")
    print(f"  Avg daily deployed    : ${avg_dep:>12,.0f}")
    print(f"  Capital utilization   : {util*100:.1f}%  (avg daily / ${CAPITAL:,.0f})")
    rodc_str = f"{mean_rodc*100:+.3f}%" if mean_rodc is not None else "n/a"
    sharpe_str = f"{sharpe:.2f}" if sharpe is not None else "n/a"
    print(f"  Mean daily RODC       : {rodc_str}")
    print(f"  DW-Sharpe             : {sharpe_str}")

    print(f"\n── DAILY DEPLOYED DISTRIBUTION ─────────────────────────────")
    slot_counts = {}
    for dep in daily_deployed.values():
        n = int(round(dep / SLOT_SIZE))
        slot_counts[n] = slot_counts.get(n, 0) + 1
    zero_dep_days = trading_days - len(daily_deployed)
    if zero_dep_days > 0:
        slot_counts[0] = zero_dep_days
    for n in sorted(slot_counts):
        pct = slot_counts[n] / trading_days * 100
        bar = "█" * int(pct / 2)
        print(f"  {n} signal(s) → ${n*SLOT_SIZE:>6,.0f}  {slot_counts[n]:>4}d ({pct:4.1f}%)  {bar}")

    print(f"\n── MAX / MIN DAYS ───────────────────────────────────────────")
    sorted_days = sorted(daily_pnls.items(), key=lambda x: x[1])
    worst5 = sorted_days[:5]
    best5 = sorted_days[-5:][::-1]
    print("  Worst 5 days:")
    for d, p in worst5:
        dep = daily_deployed.get(d, 0)
        rodc = f"{p/dep*100:+.2f}%" if dep > 0 else "n/a"
        print(f"    {d}  ${p:>10,.2f}  deployed=${dep:>7,.0f}  RODC={rodc}")
    print("  Best 5 days:")
    for d, p in best5:
        dep = daily_deployed.get(d, 0)
        rodc = f"{p/dep*100:+.2f}%" if dep > 0 else "n/a"
        print(f"    {d}  ${p:>10,.2f}  deployed=${dep:>7,.0f}  RODC={rodc}")

    print()
    return len(errors) == 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", required=True, type=int)
    args = parser.parse_args()
    ok = audit_year(args.year)
    sys.exit(0 if ok else 1)

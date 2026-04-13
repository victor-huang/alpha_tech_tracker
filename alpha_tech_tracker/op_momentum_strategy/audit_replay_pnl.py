#!/usr/bin/env python3
"""
Replay P&L Audit Script — verifies live trade engine replay logs.

Audits output from:
    python -m alpha_tech_tracker.op_momentum_strategy.op_momentum_trade_engine run \
        --replay-start ... --replay-end ... --mock-trade-execution [--trade-type stock|options]

What it verifies (per position):
  1. cap_pnl formula:
       Options (any direction): contracts × 100 × (exit_mid − entry_mid)
       Stock BULLISH:           slot × (exit_mid − entry_mid) / entry_mid
       Stock BEARISH:           slot × (entry_mid − exit_mid) / entry_mid
  2. returned capital:
       non-reentry: slot + cap_pnl
       reentry:     cap_pnl only (slot not returned — capital slot shared with primary)
  3. window_total progression per window label
  4. per-day total cap_pnl = sum of all individual cap_pnl values for that day
  5. range total cap_pnl = sum of all daily totals vs logged "Total cap P&L"

Usage:
    cd alpha_tech_tracker/op_momentum_strategy
    pyenv exec python audit_replay_pnl.py --log /tmp/replay_stock_2026_apr.txt
    pyenv exec python audit_replay_pnl.py --log /tmp/replay_opts_2026_apr.txt --date 2026-04-01
    pyenv exec python audit_replay_pnl.py --log /tmp/replay_stock_2025_mar.txt --verbose
"""

import argparse
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Optional, Tuple

# ─── Tolerances ──────────────────────────────────────────────────────────────

# Tolerances for verification. Stock cap_pnl uses float(slot)/float(entry)*raw while
# the engine uses full Decimal precision; for high-priced, high-share-count positions
# this produces up to ~$0.63 discrepancy. Options use contracts×100×price_diff which
# is exact in float. A genuine formula bug would manifest as >> $1 difference.
TRADE_TOL = 1.00    # per-position cap_pnl tolerance
RETURNED_TOL = 1.00 # per-position returned capital tolerance
DAY_TOL = 2.00      # per-day total cap_pnl tolerance (accumulated rounding)
RANGE_TOL = 3.00    # range total tolerance (float vs Decimal accumulation)
WINDOW_TOL = 0.06   # window_total progression tolerance

# ─── Log line patterns ───────────────────────────────────────────────────────

_LOG_MSG_RE = re.compile(
    r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:,\d+)? \w+ \S+ — (.*)"
)

_REPLAY_HEADER_RE = re.compile(
    r"REPLAY (\d+)/(\d+) — (\d{4}-\d{2}-\d{2})\s+\(starting capital: \$([\d.]+)\)"
)

_ENTERING_POS_RE = re.compile(
    r"Entering position \[(\w+)\]: (\w+) (BULLISH|BEARISH) @ ([\d.]+) \(rank=(\d+)(.*?)\)"
)

_REENTRY_LINE_RE = re.compile(
    r"Re-entry \[(\S+)\] (\w+) (BULLISH|BEARISH) trigger=([\d.]+)"
)

_SIM_BUY_OPT_RE = re.compile(
    r"SIMULATE BUY_OPEN (\S+) (CALL|PUT) contracts=(\d+) simulated_fill=([\d.]+)"
)

_SIM_BUY_STK_RE = re.compile(
    r"SIMULATE BUY_OPEN stock (\w+) shares=(\d+) simulated_fill=([\d.]+)"
)

_SIM_SELL_OPT_RE = re.compile(
    r"SIMULATE SELL_CLOSE (\S+) contracts=(\d+) simulated_fill=([\d.]+)"
)

_SIM_SELL_STK_RE = re.compile(
    r"SIMULATE SELL_CLOSE (\w+) shares=(\d+) simulated_fill=([\d.]+)"
)

_CAP_RETURNED_RE = re.compile(
    r"Capital returned \[(\w+)\] (\w+) \(reentry=(True|False)\): "
    r"slot=([\d.]+) cap_pnl=(-?[\d.]+) returned=(-?[\d.]+) window_total=(-?[\d.]+)"
)

_DD_FIRING_RE = re.compile(
    r"DD \[(\w+)\] firing: winner=(\w+) freed=([\d.]+)"
)

_RANGE_TOTAL_RE = re.compile(r"Total cap P&L: ([+-][\d.]+)")


# ─── Data structures ─────────────────────────────────────────────────────────

@dataclass
class TradeRecord:
    date: date
    window_label: str
    ticker: str
    signal: str            # BULLISH / BEARISH
    rank: int
    is_dd_addon: bool
    reentry_type: Optional[str]  # None / "reversal" / "bearish_reentry" etc.
    trade_type: str        # "stock" / "options"
    option_symbol: str     # for options, else ""
    shares: int            # for stocks, else 0
    contracts: int         # for options, else 0
    entry_mid: float
    exit_mid: float
    # Filled from Capital returned line:
    is_reentry: Optional[bool] = None
    logged_slot: Optional[float] = None
    logged_cap_pnl: Optional[float] = None
    logged_returned: Optional[float] = None
    logged_window_total: Optional[float] = None
    # Computed later:
    calc_cap_pnl: Optional[float] = None
    calc_returned: Optional[float] = None


# ─── Log parser ──────────────────────────────────────────────────────────────

def _extract_msg(line: str) -> str:
    """Strip the logger timestamp/level prefix; return raw message."""
    m = _LOG_MSG_RE.match(line)
    return m.group(1) if m else line.rstrip()


def parse_log(path: str):
    """
    Parse a replay log file.

    Returns:
        days_trades   : {date: [TradeRecord, ...]}
        day_starts    : {date: starting_capital}
        range_total   : float or None  (logged "Total cap P&L")
        dd_events     : {date: [(window_label, freed_capital), ...]}
    """
    days_trades: Dict[date, List[TradeRecord]] = defaultdict(list)
    day_starts: Dict[date, float] = {}
    range_total: Optional[float] = None
    dd_events: Dict[date, List[Tuple[str, float]]] = defaultdict(list)

    current_date: Optional[date] = None
    # pending_signal: most recent "Entering position" not yet matched to a BUY_OPEN
    pending_signal: Optional[dict] = None

    # Open entry queues, deferred until Capital returned provides window/reentry context.
    # For options: keyed by (window_label, ticker, is_reentry).
    # For stocks:  keyed by (window_label, ticker, is_reentry, shares).
    #   Shares disambiguates DD add-on from primary when both share the same
    #   window/ticker/is_reentry and the add-on closes before the primary.
    opt_open: Dict[Tuple[str, str, bool], List[TradeRecord]] = defaultdict(list)
    stk_open: Dict[Tuple[str, str, bool, int], List[TradeRecord]] = defaultdict(list)

    # Reverse map: occ_sym → ticker (populated from options BUY events so the
    # options SELL handler can retrieve the ticker for pending_exit_opt).
    occ_ticker: Dict[str, str] = {}

    # pending_exit / pending_exit_opt: buffered SELL info consumed by the next
    # Capital returned line (which always follows its SELL immediately in the log).
    pending_exit: Optional[dict] = None      # stocks  {ticker, shares, exit_mid}
    pending_exit_opt: Optional[dict] = None  # options {ticker, occ_sym, contracts, exit_mid}

    window_totals: Dict[str, float] = {}

    with open(path) as fh:
        for raw_line in fh:
            msg = _extract_msg(raw_line)

            # ── Range total (end of file) ──
            m = _RANGE_TOTAL_RE.search(msg)
            if m:
                range_total = float(m.group(1))
                continue

            # ── Day boundary ──
            m = _REPLAY_HEADER_RE.search(msg)
            if m:
                current_date = date.fromisoformat(m.group(3))
                day_starts[current_date] = float(m.group(4))
                # Reset per-day state
                pending_signal = None
                pending_exit = None
                pending_exit_opt = None
                opt_open.clear()
                stk_open.clear()
                occ_ticker.clear()
                window_totals.clear()
                continue

            if current_date is None:
                continue

            # ── DD firing (subtract from window_total) ──
            m = _DD_FIRING_RE.search(msg)
            if m:
                dd_label = m.group(1)
                freed = float(m.group(3))
                dd_events[current_date].append((dd_label, freed))
                continue

            # ── Entering position (sets pending signal for next BUY_OPEN) ──
            m = _ENTERING_POS_RE.search(msg)
            if m:
                label, ticker, signal, price_str, rank_str, suffix = m.groups()
                # Preserve reentry_type set by a preceding Re-entry line for the same ticker.
                # The Re-entry line fires before Entering position, so pending_signal may
                # already carry the reentry_type (e.g. "reversal", "bearish_reentry", etc.).
                prev_reentry_type = None
                if pending_signal and pending_signal.get("ticker") == ticker:
                    prev_reentry_type = pending_signal.get("reentry_type")
                pending_signal = {
                    "window_label": label,
                    "ticker": ticker,
                    "signal": signal,
                    "rank": int(rank_str),
                    "is_dd_addon": "[DD add-on]" in suffix,
                    "reentry_type": prev_reentry_type,
                }
                continue

            # ── Re-entry line (sets reentry_type on pending signal) ──
            m = _REENTRY_LINE_RE.search(msg)
            if m:
                rtype, ticker, signal, trigger = m.groups()
                # Re-entry line precedes the Entering position line;
                # update if pending_signal already exists for same ticker
                if pending_signal and pending_signal["ticker"] == ticker:
                    pending_signal["reentry_type"] = rtype
                else:
                    # Store for the upcoming Entering position line
                    pending_signal = {
                        "window_label": None,
                        "ticker": ticker,
                        "signal": signal,
                        "rank": -1,
                        "is_dd_addon": False,
                        "reentry_type": rtype,
                    }
                continue

            # ── Options BUY_OPEN ──
            m = _SIM_BUY_OPT_RE.search(msg)
            if m:
                occ_sym, opt_type, contracts_str, fill_str = m.groups()
                contracts = int(contracts_str)
                entry_mid = float(fill_str)
                ticker = None
                signal = "BULLISH" if opt_type == "CALL" else "BEARISH"
                window_label = "?"
                rank = 0
                is_dd_addon = False
                reentry_type = None
                if pending_signal:
                    ticker = pending_signal.get("ticker") or occ_sym[:4]
                    # Signal inferred from CALL/PUT is authoritative for options
                    window_label = pending_signal.get("window_label") or "?"
                    rank = pending_signal.get("rank", 0)
                    is_dd_addon = pending_signal.get("is_dd_addon", False)
                    reentry_type = pending_signal.get("reentry_type")
                    pending_signal = None
                if ticker is None:
                    ticker = occ_sym[:4]
                rec = TradeRecord(
                    date=current_date,
                    window_label=window_label,
                    ticker=ticker,
                    signal=signal,
                    rank=rank,
                    is_dd_addon=is_dd_addon,
                    reentry_type=reentry_type,
                    trade_type="options",
                    option_symbol=occ_sym,
                    shares=0,
                    contracts=contracts,
                    entry_mid=entry_mid,
                    exit_mid=0.0,
                )
                # Key by (window_label, ticker, is_reentry).  Matching is deferred to
                # Capital returned (which carries slot) so we can handle the case where
                # primary and DD add-on produce the same contract count at different
                # entry prices and the add-on closes before the primary.
                is_reentry_from_buy = reentry_type is not None
                opt_open[(window_label, ticker, is_reentry_from_buy)].append(rec)
                occ_ticker[occ_sym] = ticker  # reverse map for options SELL
                continue

            # ── Stock BUY_OPEN ──
            m = _SIM_BUY_STK_RE.search(msg)
            if m:
                ticker, shares_str, fill_str = m.groups()
                shares = int(shares_str)
                entry_mid = float(fill_str)
                signal = "BULLISH"
                window_label = "?"
                rank = 0
                is_dd_addon = False
                reentry_type = None
                if pending_signal:
                    signal = pending_signal.get("signal", "BULLISH")
                    window_label = pending_signal.get("window_label") or "?"
                    rank = pending_signal.get("rank", 0)
                    is_dd_addon = pending_signal.get("is_dd_addon", False)
                    reentry_type = pending_signal.get("reentry_type")
                    pending_signal = None
                rec = TradeRecord(
                    date=current_date,
                    window_label=window_label,
                    ticker=ticker,
                    signal=signal,
                    rank=rank,
                    is_dd_addon=is_dd_addon,
                    reentry_type=reentry_type,
                    trade_type="stock",
                    option_symbol="",
                    shares=shares,
                    contracts=0,
                    entry_mid=entry_mid,
                    exit_mid=0.0,
                )
                # Key by (window_label, ticker, is_reentry, shares).
                # Shares disambiguates DD add-on from primary when both share the same
                # window/ticker/is_reentry and the add-on closes before the primary.
                is_reentry_from_buy = reentry_type is not None
                stk_open[(window_label, ticker, is_reentry_from_buy, shares)].append(rec)
                continue

            # ── Options SELL_CLOSE ──
            # Buffer the exit; the immediately-following Capital returned line carries
            # window_label and is_reentry needed to identify the correct open record.
            # Slot-based matching handles the case where primary and DD add-on produce
            # the same contract count (Capital returned provides the slot).
            m = _SIM_SELL_OPT_RE.search(msg)
            if m:
                occ_sym, contracts_str, fill_str = m.groups()
                contracts = int(contracts_str)
                exit_mid = float(fill_str)
                ticker_for_opt = occ_ticker.get(occ_sym, occ_sym[:4])
                pending_exit_opt = {
                    "ticker": ticker_for_opt,
                    "occ_sym": occ_sym,
                    "contracts": contracts,
                    "exit_mid": exit_mid,
                }
                continue

            # ── Stock SELL_CLOSE ──
            # Buffer the exit; the immediately-following Capital returned line carries
            # the window_label and is_reentry flag needed to identify which open record
            # to close. This avoids cross-window FIFO confusion when the same ticker
            # has concurrent open positions with identical share counts.
            m = _SIM_SELL_STK_RE.search(msg)
            if m:
                ticker, shares_str, fill_str = m.groups()
                pending_exit = {
                    "ticker": ticker,
                    "shares": int(shares_str),
                    "exit_mid": float(fill_str),
                }
                continue

            # ── Capital returned ──
            m = _CAP_RETURNED_RE.search(msg)
            if m:
                label, ticker, reentry_str, slot_s, cpnl_s, ret_s, wtot_s = m.groups()
                is_reentry = reentry_str == "True"
                slot = float(slot_s)
                logged_cap_pnl = float(cpnl_s)
                logged_returned = float(ret_s)
                logged_window_total = float(wtot_s)

                rec = None

                # Stock trade: pending_exit was just buffered by the preceding SELL_CLOSE.
                # Use (label, ticker, is_reentry, shares) to find the correct open record.
                if pending_exit and pending_exit["ticker"] == ticker:
                    key = (label, ticker, is_reentry, pending_exit["shares"])
                    queue = stk_open.get(key, [])
                    if queue:
                        rec = queue.pop(0)
                        rec.exit_mid = pending_exit["exit_mid"]
                        days_trades[current_date].append(rec)
                    pending_exit = None

                # Options trade: pending_exit_opt was buffered by the preceding OCC SELL_CLOSE.
                # Matching strategy (applied in order until a unique match is found):
                #  1. Match by rec.contracts == pending contracts (different DD/primary counts)
                #  2. If still ambiguous, derive expected entry from logged_cap_pnl and
                #     match to the record closest to that expected entry price.
                #  3. FIFO fallback.
                if rec is None and pending_exit_opt and pending_exit_opt["ticker"] == ticker:
                    key = (label, ticker, is_reentry)
                    queue = opt_open.get(key, [])
                    if queue:
                        contracts_exp = pending_exit_opt["contracts"]
                        exit_mid_opt = pending_exit_opt["exit_mid"]
                        match_idx = 0  # default FIFO

                        # Pass 1: unique match by contract count stored in record
                        contract_matches = [
                            i for i, r in enumerate(queue) if r.contracts == contracts_exp
                        ]
                        if len(contract_matches) == 1:
                            match_idx = contract_matches[0]
                        elif len(contract_matches) > 1 or not contract_matches:
                            # Pass 2: expected entry derived from logged_cap_pnl
                            # cap_pnl = contracts × 100 × (exit - entry)
                            # → entry = exit - cap_pnl / (contracts × 100)
                            if contracts_exp > 0:
                                expected_entry = exit_mid_opt - logged_cap_pnl / (contracts_exp * 100)
                                best_diff = float("inf")
                                for i, r in enumerate(queue):
                                    diff = abs(r.entry_mid - expected_entry)
                                    if diff < best_diff:
                                        best_diff = diff
                                        match_idx = i

                        rec = queue.pop(match_idx)
                        rec.exit_mid = exit_mid_opt
                        rec.option_symbol = pending_exit_opt["occ_sym"]
                        days_trades[current_date].append(rec)
                    pending_exit_opt = None

                if rec is not None:
                    rec.is_reentry = is_reentry
                    rec.logged_slot = slot
                    rec.logged_cap_pnl = logged_cap_pnl
                    rec.logged_returned = logged_returned
                    rec.logged_window_total = logged_window_total
                    rec.window_label = label  # update in case ? was set

                    # Window total progression check
                    prev_total = window_totals.get(label, 0.0)
                    window_totals[label] = logged_window_total
                    _ = (prev_total, logged_window_total, logged_returned)

    return days_trades, day_starts, range_total, dd_events


# ─── P&L recalculation ───────────────────────────────────────────────────────

def _compute_cap_pnl(rec: TradeRecord) -> float:
    """Independently recompute cap_pnl from entry/exit prices."""
    if rec.entry_mid == 0 or rec.logged_slot is None:
        return 0.0
    if rec.trade_type == "options":
        # Options: always (exit - entry) × contracts × 100
        return rec.contracts * 100 * (rec.exit_mid - rec.entry_mid)
    else:
        # Stock BULLISH: slot × (exit - entry) / entry
        # Stock BEARISH: slot × (entry - exit) / entry
        if rec.signal == "BULLISH":
            raw = rec.exit_mid - rec.entry_mid
        else:
            raw = rec.entry_mid - rec.exit_mid
        return rec.logged_slot / rec.entry_mid * raw


def _compute_returned(rec: TradeRecord) -> float:
    """Independently recompute returned capital."""
    if rec.is_reentry:
        return rec.calc_cap_pnl
    return rec.logged_slot + rec.calc_cap_pnl


# ─── Main audit ──────────────────────────────────────────────────────────────

def run_audit(
    log_path: str,
    focus_date: Optional[date] = None,
    verbose: bool = False,
):
    print(f"Loading log: {log_path}\n")
    days_trades, day_starts, range_total, dd_events = parse_log(log_path)

    trading_days = sorted(days_trades)
    total_parsed = sum(len(v) for v in days_trades.values())
    print(f"Parsed {len(trading_days)} trading days, {total_parsed} completed positions.\n")

    if not trading_days:
        print("  No trading days found.")
        return

    # ── Per-position recalculation ──
    position_errors = []
    returned_errors = []

    for d in trading_days:
        for rec in days_trades[d]:
            if rec.logged_slot is None:
                continue  # Capital returned line not matched (open at EOD)
            rec.calc_cap_pnl = _compute_cap_pnl(rec)
            rec.calc_returned = _compute_returned(rec)

            pnl_diff = rec.calc_cap_pnl - rec.logged_cap_pnl
            ret_diff = rec.calc_returned - rec.logged_returned
            if abs(pnl_diff) > TRADE_TOL:
                position_errors.append((d, rec, pnl_diff))
            if abs(ret_diff) > RETURNED_TOL:
                returned_errors.append((d, rec, ret_diff))

    # ── Per-day total check ──
    day_errors = []
    calc_daily = {}
    for d in trading_days:
        calc_total = sum(
            r.calc_cap_pnl for r in days_trades[d]
            if r.calc_cap_pnl is not None
        )
        calc_daily[d] = calc_total

    # ── Window-total progression check ──
    window_total_errors = []

    # ── Range total check ──
    calc_range_total = sum(calc_daily.values())
    range_diff = None
    if range_total is not None:
        range_diff = calc_range_total - range_total

    # ── Print per-day table ──
    print("=" * 90)
    print(
        f"  {'Date':<12}  {'Positions':>10}  {'Calc cap P&L':>14}  "
        f"{'Errors':>8}  {'Start cap':>10}"
    )
    print("=" * 90)

    for d in trading_days:
        if focus_date and d != focus_date:
            continue
        trades = days_trades[d]
        pos_errors_today = [e for e in position_errors if e[0] == d]
        calc_total = calc_daily[d]
        start_cap = day_starts.get(d, float("nan"))
        err_flag = f"  ✗ {len(pos_errors_today)} err" if pos_errors_today else "  ✓"
        print(
            f"  {str(d):<12}  {len(trades):>10}  {calc_total:>+14.2f}  "
            f"{err_flag:<12}  {start_cap:>10,.2f}"
        )

        if verbose or focus_date == d:
            _print_day_detail(d, trades, dd_events.get(d, []))

    print("=" * 90)

    # ── Range total summary ──
    print(f"\n  Calc range total : {calc_range_total:>+12.2f}")
    if range_total is not None:
        print(f"  Logged range total: {range_total:>+12.2f}")
        flag = "✓" if range_diff is not None and abs(range_diff) <= RANGE_TOL else "✗ MISMATCH"
        print(f"  Difference        : {range_diff:>+12.4f}   {flag}")

    # ── Error summary ──
    print(f"\n{'=' * 60}")
    if not position_errors and not returned_errors:
        print(f"  ✓ All {total_parsed} position cap_pnl and returned values match")
        print(f"    (tolerance: ${TRADE_TOL:.2f} per position).")
    else:
        if position_errors:
            print(f"  ✗ {len(position_errors)} position(s) with cap_pnl mismatch > ${TRADE_TOL:.2f}:")
            for d, rec, diff in position_errors[:20]:
                sym = rec.option_symbol if rec.trade_type == "options" else f"{rec.ticker} [{rec.shares}sh]"
                print(
                    f"    {d} [{rec.window_label}] {sym}  "
                    f"logged={rec.logged_cap_pnl:+.2f}  calc={rec.calc_cap_pnl:+.2f}  diff={diff:+.4f}"
                )
        if returned_errors:
            print(f"  ✗ {len(returned_errors)} position(s) with returned capital mismatch > ${RETURNED_TOL:.2f}:")
            for d, rec, diff in returned_errors[:20]:
                sym = rec.option_symbol if rec.trade_type == "options" else f"{rec.ticker} [{rec.shares}sh]"
                print(
                    f"    {d} [{rec.window_label}] {sym}  "
                    f"logged={rec.logged_returned:+.2f}  calc={rec.calc_returned:+.2f}  diff={diff:+.4f}"
                )
    print(f"{'=' * 60}")

    if not focus_date:
        _print_signal_summary(days_trades)


def _print_day_detail(d: date, trades: list, dd_day_events: list):
    print(f"\n    ── Detail for {d} ──")
    if dd_day_events:
        for lbl, freed in dd_day_events:
            print(f"       DD [{lbl}] fired: freed=${freed:.2f} (subtracted from window_total)")
    print(
        f"    {'Win':3} {'Rk':3}  {'Ticker':7} {'Type':7} {'Signal':8}"
        f"  {'Entry':8} {'Exit':8}  {'Calc PnL':>10}  {'Log PnL':>10}  {'Diff':>7}"
        f"  {'Reentry':8} {'wTotal':>10}"
    )
    for rec in trades:
        if rec.calc_cap_pnl is None:
            continue
        diff = rec.calc_cap_pnl - rec.logged_cap_pnl if rec.logged_cap_pnl is not None else 0.0
        flag = "" if abs(diff) <= TRADE_TOL else " ✗"
        reentry_str = rec.reentry_type or ("reentry" if rec.is_reentry else "primary")
        wtotal_str = f"{rec.logged_window_total:.2f}" if rec.logged_window_total is not None else "—"
        print(
            f"    {rec.window_label:3} {rec.rank:3}  {rec.ticker:7} {rec.trade_type:7} {rec.signal:8}"
            f"  {rec.entry_mid:8.2f} {rec.exit_mid:8.2f}  {rec.calc_cap_pnl:>+10.2f}  "
            f"{rec.logged_cap_pnl:>+10.2f}  {diff:>+7.4f}{flag}"
            f"  {reentry_str:8} {wtotal_str:>10}"
        )
    total = sum(r.calc_cap_pnl for r in trades if r.calc_cap_pnl is not None)
    logged_total = sum(r.logged_cap_pnl for r in trades if r.logged_cap_pnl is not None)
    print(f"    {'─' * 105}")
    print(f"    Day total:  calc={total:+.2f}  logged_sum={logged_total:+.2f}\n")


def _print_signal_summary(days_trades: dict):
    """Print signal and re-entry statistics across all days."""
    total = 0
    primary = 0
    reversals = 0
    bres = 0
    bues = 0
    dds = 0
    wins = 0

    for trades in days_trades.values():
        for rec in trades:
            if rec.logged_cap_pnl is None:
                continue
            total += 1
            if rec.reentry_type == "reversal":
                reversals += 1
            elif rec.reentry_type == "bearish_reentry":
                bres += 1
            elif rec.reentry_type == "bullish_reentry":
                bues += 1
            elif rec.is_dd_addon or rec.reentry_type == "doubledown":
                dds += 1
            else:
                primary += 1
            if rec.logged_cap_pnl > 0:
                wins += 1

    print(f"\n{'=' * 55}")
    print(f"  SIGNAL / TRADE BREAKDOWN")
    print(f"{'=' * 55}")
    print(f"  Total positions : {total}")
    print(f"  Primary         : {primary}")
    print(f"  Reversal        : {reversals}")
    print(f"  Bearish re-entry: {bres}")
    print(f"  Bullish re-entry: {bues}")
    print(f"  Doubledown addon: {dds}")
    win_rate = wins / total * 100 if total else 0.0
    print(f"  Win rate        : {wins}/{total} = {win_rate:.1f}%")
    print(f"{'=' * 55}")


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Audit replay P&L calculations from live trade engine logs."
    )
    parser.add_argument("--log", required=True, help="Path to replay log file.")
    parser.add_argument(
        "--date",
        help="Focus on a single trading day (YYYY-MM-DD) and show full detail.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show per-trade detail for every day.",
    )
    args = parser.parse_args()

    focus = date.fromisoformat(args.date) if args.date else None
    run_audit(log_path=args.log, focus_date=focus, verbose=args.verbose)


if __name__ == "__main__":
    main()

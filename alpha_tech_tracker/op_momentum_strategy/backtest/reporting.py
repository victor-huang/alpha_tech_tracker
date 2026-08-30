"""Terminal reporting for the selector backtest.

Every function here formats output; none participates in trade selection,
execution, or capital accounting. Extracted verbatim from
op_momentum_selector_backtest.py.
"""
import math
from datetime import date

import pandas as pd

from .constants import INITIAL_CAPITAL, REGIME_ADAPTIVE_CONFIGS, _EOD_DISPLAY_TIME
from .weights import _parse_weights, _weights_label

def _print_regime_summary(trade_rows: list, trading_days: list):
    from collections import defaultdict
    bucket_order = list(REGIME_ADAPTIVE_CONFIGS.keys()) + ["fallback", None]
    stats = defaultdict(lambda: {"days": 0, "trades": 0, "wins": 0, "pnl": 0.0})

    day_buckets = {}
    for row in trade_rows:
        if row.get("window") != "M1" or row.get("skipped"):
            continue
        d = row["date"]
        bucket = row.get("regime") or "fallback"
        day_buckets[d] = bucket
        stats[bucket]["trades"] += 1
        stats[bucket]["wins"] += 1 if row.get("success") else 0
        stats[bucket]["pnl"] += row.get("cap_pnl", 0.0)

    all_days_set = set(trading_days)
    traded_days = set(day_buckets.keys())
    untraded_days = all_days_set - traded_days
    for d in untraded_days:
        stats[None]["days"] += 1

    for d, bkt in day_buckets.items():
        stats[bkt]["days"] += 1

    n_total = len(trading_days)
    print(f"\n{'─'*70}")
    print("  Regime Adaptive — M1 Day Distribution")
    print(f"{'─'*70}")
    print(f"  {'Bucket':<22} {'Days':>5}  {'Trades':>6}  {'Win%':>6}  {'P&L':>10}")
    for bkt in bucket_order:
        s = stats.get(bkt)
        if not s or s["days"] == 0:
            continue
        label = bkt if bkt else "(no trades)"
        n_trades = s["trades"]
        wr = f"{s['wins']/n_trades*100:.0f}%" if n_trades else "  —"
        pnl_str = f"${s['pnl']:>+,.0f}"
        pct = f"({s['days']/n_total*100:.0f}%)"
        print(f"  {label:<22} {s['days']:>4}{pct:>4}  {n_trades:>6}  {wr:>6}  {pnl_str:>10}")
    print(f"{'─'*70}")


def _print_skip_log(skip_log: list, windows: list):
    if not skip_log:
        return
    sep = "\u2501" * 80
    print(f"\n{sep}")
    print(f"  WINDOW EXECUTION LOG")
    print(sep)
    print(f"  {'Date':<12} {'Window':<8} {'Status':<22} {'Capital':>10}  {'Picks':>5}")
    print(f"  {'─' * 76}")

    skipped_count = 0
    executed_count = 0
    no_signal_count = 0

    prev_date = None
    for entry in skip_log:
        d = entry["date"]
        if d != prev_date and prev_date is not None:
            print(f"  {'─' * 76}")
        prev_date = d

        status = entry["status"]
        cap = entry["available_capital"]
        picks = entry["picks"]

        if status == "skipped_low_capital":
            skipped_count += 1
            status_display = "SKIPPED (low capital)"
        elif status == "no_signal":
            no_signal_count += 1
            status_display = "no signal"
        else:
            executed_count += 1
            status_display = f"executed ({picks} picks)"

        print(
            f"  {str(d):<12} {entry['window']:<8} {status_display:<22} ${cap:>9,.2f}  {picks:>5}"
        )

    print(f"  {'─' * 76}")
    print(
        f"  Executed: {executed_count}  |  No signal: {no_signal_count}  |  Skipped (low capital): {skipped_count}"
    )
    print(sep)


_REENTRY_TYPES = [
    ("[REV]", "rev_entry_price", "rev_pnl", "rev_exit_price", "rev_exit_reason", "rev_entry_idx", "rev_bars_held"),
    ("[BRE]", "br_entry_price", "br_pnl", "br_exit_price", "br_exit_reason", "br_entry_idx", "br_bars_held"),
    ("[BRU]", "bru_entry_price", "bru_pnl", "bru_exit_price", "bru_exit_reason", "bru_entry_idx", "bru_bars_held"),
]


def _print_reentry_subrow(
    row: dict,
    label: str,
    ep_key: str,
    pnl_key: str,
    exit_price_key: str,
    exit_reason_key: str,
    entry_idx_key: str,
    bars_held_key: str,
    multi_window: bool,
    fmt_bar_time,
):
    ep = row.get(ep_key, 0)
    if not ep:
        return None
    blank_win = f"{'':5} " if multi_window else ""

    or_close = row.get("or_close_min")
    primary_bars = row.get("bars_held", 0)
    entry_idx = row.get(entry_idx_key, 0)
    sub_bars = row.get(bars_held_key, 0)
    if or_close is not None:
        sub_entry_min = or_close + (primary_bars + entry_idx + 2) * 5
        exit_reason = row.get(exit_reason_key, "")
        if exit_reason == "end_of_day":
            sub_exit_str = _EOD_DISPLAY_TIME
        else:
            sub_exit_min = sub_entry_min + (sub_bars + 1) * 5
            sub_exit_str = fmt_bar_time(sub_exit_min)
        sub_entry_str = fmt_bar_time(sub_entry_min)
    else:
        sub_entry_str = "—"
        sub_exit_str = "—"

    cancelled = row.get("reentry_cancelled_by_dd") or row.get("bru_cancelled")
    if cancelled:
        cancel_reason = "cancelled by DD" if row.get("reentry_cancelled_by_dd") else "cancelled (capital recycled)"
        print(
            f"  {'':12} {blank_win}{'':5} {'':6} "
            f"{label:<9} {'':>5}  "
            f"{sub_entry_str:>5} {'':>5}  "
            f"{ep:>7.2f} {'':>7} "
            f"{'':>7} {'':>7}  {'':6}  {cancel_reason}"
        )
        return None
    p = row[pnl_key]
    pct = p / ep * 100
    pnl_str = f"+${abs(p):.2f}" if p >= 0 else f"-${abs(p):.2f}"
    pct_str = f"+{abs(pct):.2f}%" if pct >= 0 else f"{pct:.2f}%"
    result = "WIN" if p > 0 else "LOSS"
    print(
        f"  {'':12} {blank_win}{'':5} {'':6} "
        f"{label:<9} {'':>5}  "
        f"{sub_entry_str:>5} {sub_exit_str:>5}  "
        f"{ep:>7.2f} {row[exit_price_key]:>7.2f} "
        f"{pnl_str:>7} {pct_str:>7}  {result:<6}  {row[exit_reason_key]}"
    )
    return p, pct


def _print_daily_table(
    trade_rows: list,
    n: int,
    initial_capital: float = INITIAL_CAPITAL,
    weights: list = None,
    multi_window: bool = False,
):
    def _fmt_bar_time(minutes: int) -> str:
        return f"{minutes // 60:02d}:{minutes % 60:02d}"

    def _entry_exit_times(row) -> tuple:
        or_close = row.get("or_close_min")
        if or_close is None:
            return "—", "—"
        entry_str = _fmt_bar_time(or_close)
        if row.get("exit_reason") == "end_of_day":
            exit_str = _EOD_DISPLAY_TIME
        else:
            exit_str = _fmt_bar_time(or_close + (row.get("bars_held", 0) + 1) * 5)
        return entry_str, exit_str

    weights = weights or _parse_weights(None, n)
    active_rows = [r for r in trade_rows if not r.get("skipped")]
    sep = "\u2501" * 110
    win_col = f"{'Win':<5} " if multi_window else ""
    print(f"\n{sep}")
    print(
        f"  {'Date':<12} {win_col}{'Rank':<5} {'Ticker':<6} {'Signal':<9} {'Score':>5}  "
        f"{'In':>5} {'Out':>5}  {'Entry':>7} {'Exit':>7} {'P&L$':>7} {'P&L%':>7}  {'Result':<6}  Exit Reason"
    )
    print(sep)

    current_date = None
    current_window = None
    day_pnl = 0.0
    day_pnl_pcts = []
    day_wins = 0
    day_losses = 0
    running_total = 0.0
    day_cap_pnl = 0.0
    portfolio = initial_capital

    for row in active_rows:
        row_date = row["date"]
        row_window = row["window"]

        if row_date != current_date:
            if current_date is not None:
                portfolio += day_cap_pnl
                _print_day_summary(
                    day_wins,
                    day_losses,
                    day_pnl,
                    day_pnl_pcts,
                    running_total,
                    day_cap_pnl,
                    initial_capital,
                    portfolio,
                    multi_window=multi_window,
                )
            current_date = row_date
            current_window = None
            day_pnl = 0.0
            day_pnl_pcts = []
            day_wins = 0
            day_losses = 0
            day_cap_pnl = 0.0

        if multi_window and row_window != current_window:
            if current_window is not None:
                print(f"  {'·' * 108}")
            current_window = row_window

        pnl = row["pnl"]
        pnl_pct = pnl / row["entry_price"] * 100
        result = "WIN" if pnl > 0 else "LOSS"
        pnl_str = f"+${abs(pnl):.2f}" if pnl >= 0 else f"-${abs(pnl):.2f}"
        pnl_pct_str = f"+{abs(pnl_pct):.2f}%" if pnl_pct >= 0 else f"{pnl_pct:.2f}%"
        win_str = f"{row_window:<5} " if multi_window else ""
        t_in, t_out = _entry_exit_times(row)

        print(
            f"  {str(row_date):<12} {win_str}{row['rank']:<5} {row['ticker']:<6} "
            f"{row['signal']:<9} {row['score']:>5.2f}  "
            f"{t_in:>5} {t_out:>5}  "
            f"{row['entry_price']:>7.2f} {row['exit_price']:>7.2f} "
            f"{pnl_str:>7} {pnl_pct_str:>7}  {result:<6}  {row['exit_reason']}"
        )

        day_pnl += pnl
        day_pnl_pcts.append(pnl_pct)
        running_total += pnl
        day_cap_pnl += row["cap_pnl"]
        if pnl > 0:
            day_wins += 1
        else:
            day_losses += 1

        for (
            _label,
            _ep_key,
            _pnl_key,
            _exit_price_key,
            _exit_reason_key,
            _entry_idx_key,
            _bars_held_key,
        ) in _REENTRY_TYPES:
            sub = _print_reentry_subrow(
                row,
                _label,
                _ep_key,
                _pnl_key,
                _exit_price_key,
                _exit_reason_key,
                _entry_idx_key,
                _bars_held_key,
                multi_window,
                _fmt_bar_time,
            )
            if sub is not None:
                p, pct = sub
                day_pnl += p
                day_pnl_pcts.append(pct)
                running_total += p
                if p > 0:
                    day_wins += 1
                else:
                    day_losses += 1

        dd_cap_pnl = row.get("dd_addon_cap_pnl", 0.0)
        if dd_cap_pnl != 0.0:
            freed = row.get("dd_freed_capital", 0.0)
            addon_entry = row.get("dd_addon_entry", 0.0)
            freed_ranks = row.get("dd_freed_ranks", [])
            effective_exit = row.get("dd_addon_effective_exit", float(row["exit_price"]))
            if row["signal"] == "BULLISH":
                per_share = effective_exit - addon_entry
            else:
                per_share = addon_entry - effective_exit
            pnl_pct = per_share / addon_entry * 100 if addon_entry else 0.0
            pnl_str = f"+${per_share:.2f}" if per_share >= 0 else f"-${abs(per_share):.2f}"
            pct_str = f"+{pnl_pct:.2f}%" if pnl_pct >= 0 else f"{pnl_pct:.2f}%"
            outcome = "WIN" if per_share >= 0 else "LOSS"
            blank_win = f"{'':5} " if multi_window else ""
            ranks_str = "/".join(f"R{r}" for r in freed_ranks)
            dd_fire_min = row.get("dd_fire_min")
            if dd_fire_min is not None:
                dd_in_str = _fmt_bar_time(dd_fire_min)
                dd_out_str = _EOD_DISPLAY_TIME if row.get("exit_reason") == "end_of_day" \
                    else _fmt_bar_time(row.get("or_close_min", 0) + (row.get("bars_held", 0) + 1) * 5)
            else:
                dd_in_str = "—"
                dd_out_str = "—"
            print(
                f"  {'':12} {blank_win}{'':5} {'':6} "
                f"{'[DD]':<9} {'':>5}  "
                f"{dd_in_str:>5} {dd_out_str:>5}  "
                f"{addon_entry:>7.2f} {effective_exit:>7.2f} "
                f"{pnl_str:>7} {pct_str:>7}  {outcome:<6}  freed ${freed:.0f} ← {ranks_str}"
            )

        opp_cap_pnl = row.get("opp_cap_pnl")
        if opp_cap_pnl is not None:
            opp_deployed = row.get("opp_deployed", 0.0)
            opp_returned = row.get("opp_returned", 0.0)
            addon_entry = row.get("dd_addon_entry", 0.0)
            effective_exit = row.get("dd_addon_effective_exit", float(row["exit_price"]))
            if row["signal"] == "BULLISH":
                per_share = effective_exit - addon_entry
            else:
                per_share = addon_entry - effective_exit
            pnl_pct = per_share / addon_entry * 100 if addon_entry else 0.0
            pnl_str = f"+${per_share:.2f}" if per_share >= 0 else f"-${abs(per_share):.2f}"
            pct_str = f"+{pnl_pct:.2f}%" if pnl_pct >= 0 else f"{pnl_pct:.2f}%"
            outcome = "WIN" if opp_cap_pnl >= 0 else "LOSS"
            opp_net_str = (
                f"+${abs(opp_cap_pnl):.2f}" if opp_cap_pnl >= 0 else f"-${abs(opp_cap_pnl):.2f}"
            )
            blank_win = f"{'':5} " if multi_window else ""
            dd_fire_min = row.get("dd_fire_min")
            if dd_fire_min is not None:
                opp_in_str = _fmt_bar_time(dd_fire_min)
                opp_out_str = _EOD_DISPLAY_TIME if row.get("exit_reason") == "end_of_day" \
                    else _fmt_bar_time(row.get("or_close_min", 0) + (row.get("bars_held", 0) + 1) * 5)
            else:
                opp_in_str = "—"
                opp_out_str = "—"
            print(
                f"  {'':12} {blank_win}{'':5} {'':6} "
                f"{'[OPP]':<9} {'':>5}  "
                f"{opp_in_str:>5} {opp_out_str:>5}  "
                f"{addon_entry:>7.2f} {effective_exit:>7.2f} "
                f"{pnl_str:>7} {pct_str:>7}  {outcome:<6}  "
                f"pool ${opp_deployed:,.0f} → ${opp_returned:,.0f}  ({opp_net_str})"
            )

    if current_date is not None:
        portfolio += day_cap_pnl
        _print_day_summary(
            day_wins,
            day_losses,
            day_pnl,
            day_pnl_pcts,
            running_total,
            day_cap_pnl,
            initial_capital,
            portfolio,
            multi_window=multi_window,
        )

    print(sep)


def _print_day_summary(
    wins,
    losses,
    day_pnl,
    day_pnl_pcts,
    running_total,
    day_cap_pnl,
    initial_capital,
    portfolio,
    multi_window: bool = False,
):
    total = wins + losses
    if total == 0:
        return
    pnl_str = f"+${abs(day_pnl):.2f}" if day_pnl >= 0 else f"-${abs(day_pnl):.2f}"
    avg_pct = sum(day_pnl_pcts) / len(day_pnl_pcts)
    avg_pct_str = f"+{abs(avg_pct):.2f}%" if avg_pct >= 0 else f"{avg_pct:.2f}%"
    cap_pnl_str = (
        f"+${abs(day_cap_pnl):.2f}" if day_cap_pnl >= 0 else f"-${abs(day_cap_pnl):.2f}"
    )
    day_ret_pct = day_cap_pnl / initial_capital * 100
    day_ret_str = (
        f"+{abs(day_ret_pct):.2f}%" if day_ret_pct >= 0 else f"{day_ret_pct:.2f}%"
    )
    win_pad = "      " if multi_window else ""
    print(
        f"  {'':12} {win_pad}{'':5} {'':6} {'':9} {'':5}  "
        f"{'':>5} {'':>5}  {'':>7} {'':>7} {pnl_str:>7} {avg_pct_str:>7}  "
        f"{wins}W/{losses}L  │  cap: {cap_pnl_str} ({day_ret_str})  portfolio: ${portfolio:.2f}"
    )
    print(f"  {'─' * 108}")


def _stats_from_trades(trade_rows: list) -> dict:
    active = [r for r in trade_rows if not r.get("skipped")]
    total = len(active)
    if total == 0:
        return None
    wins = sum(1 for r in active if r["success"])
    losses = total - wins
    win_rate = wins / total
    win_pct_vals = [r["pnl_pct"] for r in active if r["success"]]
    loss_pct_vals = [abs(r["pnl_pct"]) for r in active if not r["success"]]
    avg_win_pct = sum(win_pct_vals) / len(win_pct_vals) if win_pct_vals else 0.0
    avg_loss_pct = sum(loss_pct_vals) / len(loss_pct_vals) if loss_pct_vals else 0.0
    ev = win_rate * avg_win_pct - (1 - win_rate) * avg_loss_pct
    net_pnl = sum(r["pnl"] for r in active)

    rev_rows = [r for r in active if r.get("rev_entry_price", 0)]
    rev_total = len(rev_rows)
    rev_wins = sum(1 for r in rev_rows if r.get("rev_pnl", 0) > 0)
    rev_losses = rev_total - rev_wins

    br_rows = [r for r in active if r.get("br_entry_price", 0)]
    br_total = len(br_rows)
    br_wins = sum(1 for r in br_rows if r.get("br_pnl", 0) > 0)
    br_losses = br_total - br_wins

    bru_rows = [r for r in active if r.get("bru_entry_price", 0)]
    bru_total = len(bru_rows)
    bru_wins = sum(1 for r in bru_rows if r.get("bru_pnl", 0) > 0)
    bru_losses = bru_total - bru_wins

    dd_rows = [r for r in active if r.get("dd_addon_cap_pnl", 0.0) != 0.0]
    dd_total = len(dd_rows)
    dd_wins = sum(1 for r in dd_rows if r.get("dd_addon_cap_pnl", 0.0) > 0)
    dd_losses = dd_total - dd_wins
    dd_net_cap_pnl = sum(r.get("dd_addon_cap_pnl", 0.0) for r in dd_rows)

    opp_rows = [r for r in active if r.get("opp_cap_pnl") is not None]
    opp_total = len(opp_rows)
    opp_wins = sum(1 for r in opp_rows if r.get("opp_cap_pnl", 0.0) > 0)
    opp_losses = opp_total - opp_wins
    opp_net_cap_pnl = sum(r.get("opp_cap_pnl", 0.0) for r in opp_rows)

    short_rows = [r for r in active if r.get("mins_held", 999) <= 15]
    short_total = len(short_rows)
    short_wins = sum(1 for r in short_rows if r["success"])

    vshort_rows = [r for r in active if r.get("mins_held", 999) <= 10]
    vshort_total = len(vshort_rows)
    vshort_wins = sum(1 for r in vshort_rows if r["success"])

    return {
        "total": total,
        "wins": wins,
        "losses": losses,
        "win_rate": win_rate,
        "avg_win_pct": avg_win_pct,
        "avg_loss_pct": avg_loss_pct,
        "ev": ev,
        "net_pnl": net_pnl,
        "rev_total": rev_total,
        "rev_wins": rev_wins,
        "rev_losses": rev_losses,
        "br_total": br_total,
        "br_wins": br_wins,
        "br_losses": br_losses,
        "bru_total": bru_total,
        "bru_wins": bru_wins,
        "bru_losses": bru_losses,
        "dd_total": dd_total,
        "dd_wins": dd_wins,
        "dd_losses": dd_losses,
        "dd_net_cap_pnl": dd_net_cap_pnl,
        "opp_total": opp_total,
        "opp_wins": opp_wins,
        "opp_losses": opp_losses,
        "opp_net_cap_pnl": opp_net_cap_pnl,
        "short_total": short_total,
        "short_wins": short_wins,
        "vshort_total": vshort_total,
        "vshort_wins": vshort_wins,
    }


def _print_stats_block(label: str, stats: dict):
    if stats is None:
        print(f"  {label}: no trades")
        return
    net_str = (
        f"+${stats['net_pnl']:.2f}"
        if stats["net_pnl"] >= 0
        else f"-${abs(stats['net_pnl']):.2f}"
    )
    ev_str = f"+{stats['ev']:.3f}%" if stats["ev"] >= 0 else f"{stats['ev']:.3f}%"
    print(f"\n  {label}")
    print(f"  {'─' * 48}")
    print(
        f"  Trades          : {stats['total']}  ({stats['wins']}W / {stats['losses']}L)"
    )
    if stats.get("rev_total", 0):
        print(
            f"  Reversals       : {stats['rev_total']}  ({stats['rev_wins']}W / {stats['rev_losses']}L)"
        )
    if stats.get("br_total", 0):
        print(
            f"  Bearish re-entry: {stats['br_total']}  ({stats['br_wins']}W / {stats['br_losses']}L)"
        )
    if stats.get("bru_total", 0):
        print(
            f"  Bullish re-entry: {stats['bru_total']}  ({stats['bru_wins']}W / {stats['bru_losses']}L)"
        )
    if stats.get("dd_total", 0):
        dd_net = stats["dd_net_cap_pnl"]
        dd_net_str = f"+${dd_net:.2f}" if dd_net >= 0 else f"-${abs(dd_net):.2f}"
        print(
            f"  Double-down     : {stats['dd_total']}  ({stats['dd_wins']}W / {stats['dd_losses']}L)"
            f"  net cap P&L: {dd_net_str}"
        )
    if stats.get("opp_total", 0):
        opp_net = stats["opp_net_cap_pnl"]
        opp_net_str = f"+${opp_net:.2f}" if opp_net >= 0 else f"-${abs(opp_net):.2f}"
        print(
            f"  Opportunity pool: {stats['opp_total']}  ({stats['opp_wins']}W / {stats['opp_losses']}L)"
            f"  net cap P&L: {opp_net_str}"
        )
    print(f"  Win rate        : {stats['win_rate'] * 100:.0f}%")
    if stats.get("vshort_total", 0):
        vshort_wr = stats["vshort_wins"] / stats["vshort_total"] * 100
        short_wr = stats["short_wins"] / stats["short_total"] * 100 if stats.get("short_total") else 0
        print(
            f"  Short trades    : {stats['vshort_total']}  (≤10 min)  WR: {vshort_wr:.0f}%"
            f"  |  {stats['short_total']}  (≤15 min)  WR: {short_wr:.0f}%"
        )
    elif stats.get("short_total", 0):
        short_wr = stats["short_wins"] / stats["short_total"] * 100
        print(f"  Short trades    : {stats['short_total']}  (≤15 min)  WR: {short_wr:.0f}%")
    print(f"  Avg win  %      : +{stats['avg_win_pct']:.2f}%  per trade")
    print(f"  Avg loss %      : -{stats['avg_loss_pct']:.2f}%  per trade")
    print(f"  EV / trade      : {ev_str}")
    print(f"  Net P&L (1 sh)  : {net_str}")


def _capital_stats_from_trades(trade_rows: list, initial_capital: float) -> dict:
    active = [r for r in trade_rows if not r.get("skipped")]
    total_cap_pnl = sum(r["cap_pnl"] for r in active)
    days_with_picks = set(r["date"] for r in active)

    daily_cap_pnls = {}
    daily_deployed = {}
    for row in active:
        d = row["date"]
        daily_cap_pnls[d] = daily_cap_pnls.get(d, 0.0) + row["cap_pnl"]
        daily_deployed[d] = daily_deployed.get(d, 0.0) + row.get("slot_capital", 0.0)

    daily_returns = list(daily_cap_pnls.values())
    avg_daily_ret = sum(daily_returns) / len(daily_returns) if daily_returns else 0.0

    # Deployment metrics
    total_deployed = sum(daily_deployed.values())
    pnl_per_dollar = total_cap_pnl / total_deployed if total_deployed > 0 else 0.0
    capital_utilization = (
        sum(v / initial_capital for v in daily_deployed.values()) / len(daily_deployed)
        if daily_deployed else 0.0
    )

    # Daily RODC and derived metrics — exclude days with no deployment.
    rodc_days = [(daily_cap_pnls[d], daily_deployed[d]) for d in daily_deployed if daily_deployed[d] > 0]
    mean_daily_rodc = None
    dw_sharpe = None
    if rodc_days:
        rodcs = [pnl / dep for pnl, dep in rodc_days]
        mean_daily_rodc = sum(rodcs) / len(rodcs)
        if len(rodc_days) >= 2:
            deps = [dep for _, dep in rodc_days]
            avg_dep = sum(deps) / len(deps)
            w = [d / avg_dep for d in deps]
            w_sum = sum(w)
            w_mean = sum(wi * ri for wi, ri in zip(w, rodcs)) / w_sum
            w_var = sum(wi * (ri - w_mean) ** 2 for wi, ri in zip(w, rodcs)) / w_sum
            w_std = math.sqrt(w_var) if w_var > 0 else 0.0
            dw_sharpe = (w_mean / w_std * math.sqrt(252)) if w_std > 0 else None

    return {
        "initial_capital": initial_capital,
        "total_cap_pnl": total_cap_pnl,
        "total_return_pct": total_cap_pnl / initial_capital * 100,
        "final_portfolio": initial_capital + total_cap_pnl,
        "days_with_picks": len(days_with_picks),
        "avg_daily_ret": avg_daily_ret,
        "avg_daily_ret_pct": avg_daily_ret / initial_capital * 100,
        "total_deployed": total_deployed,
        "pnl_per_dollar_deployed": pnl_per_dollar,
        "mean_daily_rodc": mean_daily_rodc,
        "capital_utilization": capital_utilization,
        "deployment_weighted_sharpe": dw_sharpe,
    }


def _print_capital_stats_block(stats: dict, weights_label: str = ""):
    cap_pnl_str = (
        f"+${stats['total_cap_pnl']:.2f}"
        if stats["total_cap_pnl"] >= 0
        else f"-${abs(stats['total_cap_pnl']):.2f}"
    )
    ret_pct_str = (
        f"+{stats['total_return_pct']:.2f}%"
        if stats["total_return_pct"] >= 0
        else f"{stats['total_return_pct']:.2f}%"
    )
    avg_str = (
        f"+${stats['avg_daily_ret']:.2f}"
        if stats["avg_daily_ret"] >= 0
        else f"-${abs(stats['avg_daily_ret']):.2f}"
    )
    avg_pct_str = (
        f"+{stats['avg_daily_ret_pct']:.2f}%"
        if stats["avg_daily_ret_pct"] >= 0
        else f"{stats['avg_daily_ret_pct']:.2f}%"
    )
    pnl_per_dollar = stats.get("pnl_per_dollar_deployed", 0.0)
    mean_rodc = stats.get("mean_daily_rodc")
    util = stats.get("capital_utilization", 0.0)
    dw_sharpe = stats.get("deployment_weighted_sharpe")
    total_deployed = stats.get("total_deployed", 0.0)

    pnl_per_dollar_str = (
        f"+${pnl_per_dollar:.4f}" if pnl_per_dollar >= 0 else f"-${abs(pnl_per_dollar):.4f}"
    )
    mean_rodc_str = (
        f"{mean_rodc * 100:+.3f}%" if mean_rodc is not None else "n/a"
    )
    sharpe_str = f"{dw_sharpe:.2f}" if dw_sharpe is not None else "n/a"

    label = f"${stats['initial_capital']:,.0f} initial"
    if weights_label:
        label += f" | {weights_label}"
    print(f"\n  CAPITAL SIMULATION  ({label})")
    print(f"  {'─' * 54}")
    print(f"  Total return ($)         : {cap_pnl_str}")
    print(f"  Total return (%)         : {ret_pct_str}")
    print(f"  Final portfolio          : ${stats['final_portfolio']:,.2f}")
    print(f"  Days with picks          : {stats['days_with_picks']}")
    print(f"  Avg daily return         : {avg_str}  ({avg_pct_str})")
    print(f"  {'─' * 54}")
    print(f"  Total deployed           : ${total_deployed:,.2f}")
    print(f"  Capital utilization      : {util * 100:.1f}%  (avg daily deployed / initial)")
    print(f"  P&L per $ deployed       : {pnl_per_dollar_str}  (cumulative)")
    print(f"  Mean daily RODC          : {mean_rodc_str}  (avg per-day return on deployed)")
    print(f"  Deployment-weighted Sharpe: {sharpe_str}")


def _print_per_window_stats(
    trade_rows: list,
    windows: list,
    initial_capital: float,
    morning_split: list,
):
    n_first = len(morning_split)
    split_pct = " / ".join(f"{s * 100:.0f}%" for s in morning_split)
    sep = "\u2501" * 96
    print(f"\n{sep}")
    print(
        f"  PER-WINDOW BREAKDOWN  (first group: {split_pct} of portfolio | sequential: inherits all returned capital)"
    )
    print(sep)
    print(
        f"  {'Window':<8} {'Start':<7} {'Bars':<5} {'Group':<12} {'Trades':>7}  {'W/L':<10} "
        f"{'WinRate':>8}  {'EV/trade':>9}  {'Cap P&L':>10}  {'Return%':>8}  {'≤10m':>5}  {'Short':>6}  {'Sh%':>5}  {'ShWR':>5}"
    )
    print(f"  {'─' * 102}")

    for i, win in enumerate(windows):
        label = win["label"]
        if i < n_first:
            group = f"first({morning_split[i] * 100:.0f}%)"
        else:
            group = "sequential"
        win_rows = [
            r for r in trade_rows if r["window"] == label and not r.get("skipped")
        ]
        if not win_rows:
            print(
                f"  {label:<8} {win['opening_start']:<7} {win['opening_bars']:<5} {group:<10} {'—':>7}"
            )
            continue
        stats = _stats_from_trades(win_rows)
        cap_stats = _capital_stats_from_trades(win_rows, initial_capital)
        ev_str = f"+{stats['ev']:.3f}%" if stats["ev"] >= 0 else f"{stats['ev']:.3f}%"
        cap_pnl_str = (
            f"+${cap_stats['total_cap_pnl']:.2f}"
            if cap_stats["total_cap_pnl"] >= 0
            else f"-${abs(cap_stats['total_cap_pnl']):.2f}"
        )
        ret_str = (
            f"+{cap_stats['total_return_pct']:.2f}%"
            if cap_stats["total_return_pct"] >= 0
            else f"{cap_stats['total_return_pct']:.2f}%"
        )
        wl = f"{stats['wins']}W/{stats['losses']}L"
        short_total = stats.get("short_total", 0)
        short_pct = short_total / stats["total"] * 100 if stats["total"] else 0.0
        short_wr = stats["short_wins"] / short_total * 100 if short_total else 0.0
        vshort_total = stats.get("vshort_total", 0)
        print(
            f"  {label:<8} {win['opening_start']:<7} {win['opening_bars']:<5} {group:<10} "
            f"{stats['total']:>7}  {wl:<10} {stats['win_rate'] * 100:>7.0f}%  "
            f"{ev_str:>9}  {cap_pnl_str:>10}  {ret_str:>8}"
            f"  {vshort_total:>5}  {short_total:>6}  {short_pct:>4.0f}%  {short_wr:>4.0f}%"
        )
    print(sep)


def _period_capital_groups(trade_rows: list, initial_capital: float, key_fn) -> dict:
    active = [r for r in trade_rows if not r.get("skipped")]
    groups = {}
    for row in active:
        key = key_fn(row["date"])
        if key not in groups:
            groups[key] = {"picks": 0, "wins": 0, "losses": 0, "cap_pnl": 0.0}
        groups[key]["picks"] += 1
        groups[key]["cap_pnl"] += row["cap_pnl"]
        if row["success"]:
            groups[key]["wins"] += 1
        else:
            groups[key]["losses"] += 1
    return groups


def _print_period_table(title: str, groups: dict, initial_capital: float):
    if not groups:
        return
    sep = "\u2501" * 72
    print(f"\n{sep}")
    print(f"  {title}")
    print(sep)
    print(
        f"  {'Period':<12} {'Picks':>6}  {'W/L':<11} {'Cap P&L$':>10}  {'Return%':>8}  Portfolio"
    )
    print(f"  {'─' * 68}")

    portfolio = initial_capital
    total_picks = total_wins = total_losses = 0
    total_cap_pnl = 0.0

    for key in sorted(groups):
        g = groups[key]
        portfolio += g["cap_pnl"]
        total_picks += g["picks"]
        total_wins += g["wins"]
        total_losses += g["losses"]
        total_cap_pnl += g["cap_pnl"]

        wl = f"{g['wins']}W/{g['losses']}L"
        pnl_s = (
            f"+${g['cap_pnl']:.2f}"
            if g["cap_pnl"] >= 0
            else f"-${abs(g['cap_pnl']):.2f}"
        )
        ret = g["cap_pnl"] / initial_capital * 100
        ret_s = f"+{ret:.2f}%" if ret >= 0 else f"{ret:.2f}%"
        print(
            f"  {key:<12} {g['picks']:>6}  {wl:<11} {pnl_s:>10}  {ret_s:>8}  ${portfolio:,.2f}"
        )

    print(f"  {'─' * 68}")
    total_pnl_s = (
        f"+${total_cap_pnl:.2f}"
        if total_cap_pnl >= 0
        else f"-${abs(total_cap_pnl):.2f}"
    )
    total_ret = total_cap_pnl / initial_capital * 100
    total_ret_s = f"+{total_ret:.2f}%" if total_ret >= 0 else f"{total_ret:.2f}%"
    print(
        f"  {'TOTAL':<12} {total_picks:>6}  {total_wins}W/{total_losses}L{'':<7} "
        f"{total_pnl_s:>10}  {total_ret_s:>8}  ${initial_capital + total_cap_pnl:,.2f}"
    )
    print(sep)


def _bnh_period_groups(daily_closes: pd.Series, initial_capital: float, key_fn) -> dict:
    if daily_closes.empty:
        return {}
    shares = initial_capital / daily_closes.iloc[0]
    groups = {}
    for d, close in daily_closes.items():
        key = key_fn(d)
        if key not in groups:
            groups[key] = {"last_close": close}
        groups[key]["last_close"] = close

    prev_value = initial_capital
    for key in sorted(groups):
        end_value = shares * groups[key]["last_close"]
        groups[key]["pnl"] = end_value - prev_value
        prev_value = end_value
    return groups


def _print_bnh_period_table(title: str, groups: dict, initial_capital: float):
    if not groups:
        return
    sep = "\u2501" * 60
    print(f"\n{sep}")
    print(f"  {title}")
    print(sep)
    print(f"  {'Period':<12} {'P&L$':>10}  {'Return%':>8}  Portfolio")
    print(f"  {'─' * 54}")

    portfolio = initial_capital
    total_pnl = 0.0
    for key in sorted(groups):
        pnl = groups[key]["pnl"]
        portfolio += pnl
        total_pnl += pnl
        pnl_s = f"+${pnl:.2f}" if pnl >= 0 else f"-${abs(pnl):.2f}"
        ret = pnl / initial_capital * 100
        ret_s = f"+{ret:.2f}%" if ret >= 0 else f"{ret:.2f}%"
        print(f"  {key:<12} {pnl_s:>10}  {ret_s:>8}  ${portfolio:,.2f}")

    print(f"  {'─' * 54}")
    total_pnl_s = f"+${total_pnl:.2f}" if total_pnl >= 0 else f"-${abs(total_pnl):.2f}"
    total_ret = total_pnl / initial_capital * 100
    total_ret_s = f"+{total_ret:.2f}%" if total_ret >= 0 else f"{total_ret:.2f}%"
    print(
        f"  {'TOTAL':<12} {total_pnl_s:>10}  {total_ret_s:>8}  ${initial_capital + total_pnl:,.2f}"
    )
    print(sep)


def _print_summary(
    trade_rows: list,
    baseline_df: pd.DataFrame,
    n: int,
    eval_start: date,
    eval_end: date,
    lookback_days: int,
    stop_pct: float,
    windows: list,
    initial_capital: float = INITIAL_CAPITAL,
    qqq_closes: pd.Series = None,
    weights: list = None,
    morning_split: list = None,
):
    sep = "\u2501" * 70
    print(f"\n{sep}")
    print(f"  SUMMARY — Selector Backtest")
    print(
        f"  {eval_start} → {eval_end}  |  top-{n}  |  {lookback_days}d rolling  |  stop-pct {stop_pct}"
    )
    print(sep)

    _print_stats_block(
        f"SELECTED  (top-{n} per window per day, scoring + EV gate)",
        _stats_from_trades(trade_rows),
    )

    if not baseline_df.empty:
        baseline_rows = [
            {
                "pnl": r["pnl"],
                "pnl_pct": r["pnl"] / r["entry_price"] * 100,
                "success": bool(r["success"]),
                "skipped": False,
            }
            for r in baseline_df.to_dict("records")
        ]
        _print_stats_block(
            "BASELINE  (all signals, no selection, first window only)",
            _stats_from_trades(baseline_rows),
        )

    if trade_rows:
        weights = weights or _parse_weights(None, n)
        wlabel = _weights_label(weights, initial_capital)
        _print_capital_stats_block(
            _capital_stats_from_trades(trade_rows, initial_capital), wlabel
        )

        if len(windows) > 1:
            _print_per_window_stats(
                trade_rows, windows, initial_capital, morning_split or [1.0]
            )

        def _week_key(d):
            iso = d.isocalendar()
            return f"{iso[0]}-W{iso[1]:02d}"

        def _month_key(d):
            return f"{d.year}-{d.month:02d}"

        _print_period_table(
            f"WEEKLY BREAKDOWN  (${initial_capital:,.0f} initial | {wlabel})",
            _period_capital_groups(trade_rows, initial_capital, _week_key),
            initial_capital,
        )
        if qqq_closes is not None and not qqq_closes.empty:
            _print_bnh_period_table(
                f"WEEKLY BREAKDOWN  QQQ buy-and-hold (${initial_capital:,.0f} initial)",
                _bnh_period_groups(qqq_closes, initial_capital, _week_key),
                initial_capital,
            )

        _print_period_table(
            f"MONTHLY BREAKDOWN  (${initial_capital:,.0f} initial | {wlabel})",
            _period_capital_groups(trade_rows, initial_capital, _month_key),
            initial_capital,
        )
        if qqq_closes is not None and not qqq_closes.empty:
            _print_bnh_period_table(
                f"MONTHLY BREAKDOWN  QQQ buy-and-hold (${initial_capital:,.0f} initial)",
                _bnh_period_groups(qqq_closes, initial_capital, _month_key),
                initial_capital,
            )

    print(f"\n{sep}\n")


def _print_opportunity_pool_block(
    trade_rows: list, initial_pool: float, compound: bool
):
    opp_rows = [r for r in trade_rows if not r.get("skipped") and r.get("opp_cap_pnl") is not None]
    if not opp_rows:
        return
    opp_total = len(opp_rows)
    opp_wins = sum(1 for r in opp_rows if r.get("opp_cap_pnl", 0.0) > 0)
    opp_losses = opp_total - opp_wins
    win_rate = opp_wins / opp_total * 100
    opp_net_cap_pnl = sum(r.get("opp_cap_pnl", 0.0) for r in opp_rows)
    final_balance = initial_pool + opp_net_cap_pnl
    pool_return_pct = opp_net_cap_pnl / initial_pool * 100 if initial_pool else 0.0

    net_str = f"+${opp_net_cap_pnl:.2f}" if opp_net_cap_pnl >= 0 else f"-${abs(opp_net_cap_pnl):.2f}"
    ret_str = f"+{pool_return_pct:.2f}%" if pool_return_pct >= 0 else f"{pool_return_pct:.2f}%"
    compound_note = "compounded" if compound else "resets daily"

    sep = "━" * 60
    print(f"\n{sep}")
    print(f"  OPPORTUNITY POOL  (${initial_pool:,.0f} initial | {compound_note})")
    print(f"  {'─' * 56}")
    print(f"  Deployments         : {opp_total}  ({opp_wins}W / {opp_losses}L)")
    print(f"  Win rate            : {win_rate:.0f}%")
    print(f"  Net cap P&L         : {net_str}")
    print(f"  Net pool return (%) : {ret_str}")
    if compound:
        final_str = f"${final_balance:,.2f}"
        print(f"  Final pool balance  : {final_str}")
    print(sep)

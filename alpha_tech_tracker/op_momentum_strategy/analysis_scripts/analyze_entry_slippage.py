"""Analyze entry slippage: gap between signal bar close (backtest price) and actual fill.

For each ENTRY fill, pairs the Alpaca fill against the engine's "Entering position @ X"
log line and computes:
  gap         = fill_price - trigger_price
  gap_bps     = gap / trigger_price * 10_000
  pnl_impact  = (trigger - fill) * qty  for longs   (positive = favorable)
                (fill - trigger) * qty  for shorts   (positive = favorable)

If the fills CSV does not yet exist for the target date, fetches orders from Alpaca first.

Produces:
  logs/fills/{date}/entry_slippage_{date}.csv  — one row per entry fill

Usage:
  python -m alpha_tech_tracker.op_momentum_strategy.analyze_entry_slippage
  python -m alpha_tech_tracker.op_momentum_strategy.analyze_entry_slippage --date 2026-05-01
  python -m alpha_tech_tracker.op_momentum_strategy.analyze_entry_slippage \\
      --date 2026-05-01 --log-file logs/op_momentum_stock_2026-05-01.log --live
"""

import argparse
import csv
import logging
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

_ET = timezone(timedelta(hours=-4))  # EDT (UTC-4); adjust to -5 for EST in winter


def _now_et() -> datetime:
    return datetime.now(tz=_ET)


# ---------------------------------------------------------------------------
# Fills CSV — ensure it exists, generating via Alpaca API if needed
# ---------------------------------------------------------------------------

def _ensure_fills_csv(fills_csv: Path, target_date: date, log_file: str, paper: bool) -> bool:
    """Return True if the fills CSV is ready (existing or freshly generated)."""
    if fills_csv.exists():
        logger.info("Fills CSV found: %s", fills_csv)
        return True

    logger.info("Fills CSV not found — fetching from Alpaca API (%s)...",
                "paper" if paper else "live")
    try:
        from alpha_tech_tracker.op_momentum_strategy import fetch_alpaca_orders as fao
        from alpha_tech_tracker.op_momentum_strategy.config import _load_config
        _load_config()

        trading_client = fao._build_trading_client(paper=paper)
        alpaca_data_client = fao._build_alpaca_stock_data_client()
        raw_orders = fao._fetch_orders(trading_client, target_date)

        log_actions = fao._scan_log_for_actions(log_file)
        records = fao._parse_orders(raw_orders, target_date, log_actions=log_actions)

        if not records:
            logger.warning("No filled stock orders found for %s", target_date)
            return False

        log_quotes = fao._parse_stock_quotes_from_log(log_file, records)
        records = fao._enrich_records(alpaca_data_client, records, log_quotes)
        fao._write_csv(fills_csv, records, fao._STOCK_COLS)
        logger.info("Fills CSV created: %s (%d rows)", fills_csv, len(records))
        return True

    except Exception as exc:
        logger.error("Failed to fetch fills from Alpaca: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Log parsing — extract "Entering position" events with trigger prices
# ---------------------------------------------------------------------------

_RE_TS = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")
_RE_ENTERING = re.compile(
    r"Entering position \[(\w+)\]: (\w+) (BULLISH|BEARISH) @ ([\d.]+)"
    r"(?:\s+\(rank=\d+(?:\s+\[([^\]]+)\])?\))?"
)
_RE_REENTRY = re.compile(
    r"Re-entry \[(bullish_reentry|bearish_reentry|reversal|doubledown)\] "
    r"(\w+) (?:BULLISH|BEARISH) trigger=([\d.]+)"
)
_REENTRY_TYPE_MAP = {
    "reversal": "REV",
    "doubledown": "DD",
    "bullish_reentry": "BRE",
    "bearish_reentry": "BRE",
}


def _parse_log_entries(log_path: str) -> list:
    """Return one dict per 'Entering position' line found in log_path.

    Each dict contains:
      log_ts_et     — datetime (ET) of the log line
      window        — e.g. "M1", "A1"
      ticker        — e.g. "SNDK"
      direction     — "BULLISH" or "BEARISH"
      trigger_price — bar close price the engine used (backtest reference)
      entry_type    — "Primary", "BRE", "DD", or "REV"
    """
    if not log_path or not os.path.exists(log_path):
        logger.warning("Log file not found: %s", log_path)
        return []

    entries = []
    pending_reentry: dict = {}  # ticker → (reentry_type_str, log_ts_et)

    with open(log_path) as f:
        for line in f:
            ts_m = _RE_TS.match(line)
            if not ts_m:
                continue
            try:
                log_ts_et = datetime.strptime(
                    ts_m.group(1), "%Y-%m-%d %H:%M:%S"
                ).replace(tzinfo=timezone.utc).astimezone(_ET)
            except ValueError:
                continue

            m = _RE_REENTRY.search(line)
            if m:
                rtype, ticker, _ = m.groups()
                pending_reentry[ticker] = (rtype, log_ts_et)
                continue

            m = _RE_ENTERING.search(line)
            if m:
                window, ticker, direction, price_str, qualifier = (
                    m.group(1), m.group(2), m.group(3), m.group(4), m.group(5)
                )

                if qualifier and "DD add-on" in qualifier:
                    entry_type = "DD"
                elif ticker in pending_reentry:
                    rtype, reentry_ts = pending_reentry.pop(ticker)
                    if (log_ts_et - reentry_ts).total_seconds() <= 60:
                        entry_type = _REENTRY_TYPE_MAP.get(rtype, "BRE")
                    else:
                        entry_type = "Primary"
                else:
                    entry_type = "Primary"

                entries.append({
                    "log_ts_et": log_ts_et,
                    "window": window,
                    "ticker": ticker,
                    "direction": direction,
                    "trigger_price": float(price_str),
                    "entry_type": entry_type,
                })

    logger.info("Parsed %d entry events from log", len(entries))
    return entries


# ---------------------------------------------------------------------------
# Fills CSV loading
# ---------------------------------------------------------------------------

def _load_fills(fills_csv: Path, target_date: date) -> list:
    """Return ENTRY rows from fills CSV, with fill_datetime added (ET)."""
    rows = []
    with open(fills_csv, newline="") as f:
        for row in csv.DictReader(f):
            if row.get("side") != "ENTRY":
                continue
            try:
                t = datetime.strptime(row["fill_time"], "%H:%M:%S")
                fill_dt = datetime(
                    target_date.year, target_date.month, target_date.day,
                    t.hour, t.minute, t.second, tzinfo=_ET,
                )
                rows.append({**row, "fill_datetime": fill_dt})
            except (ValueError, KeyError):
                continue
    logger.info("Loaded %d ENTRY fills from %s", len(rows), fills_csv)
    return rows


# ---------------------------------------------------------------------------
# Matching and metric computation
# ---------------------------------------------------------------------------

def _match_and_compute(log_entries: list, fills: list) -> list:
    """Pair each fill with its log entry and compute slippage metrics.

    Matching rule: most recent 'Entering position' event for the same ticker
    that occurred within 10 minutes before the fill time.
    """
    results = []

    for fill in fills:
        ticker = fill["ticker"]
        fill_dt = fill["fill_datetime"]

        candidates = [
            e for e in log_entries
            if e["ticker"] == ticker
            and e["log_ts_et"] <= fill_dt
            and (fill_dt - e["log_ts_et"]).total_seconds() <= 600
        ]
        log_entry = (
            max(candidates, key=lambda e: e["log_ts_et"]) if candidates else None
        )

        fill_price_str = fill.get("fill_price", "")
        qty_str = fill.get("qty", "")
        try:
            fill_price = float(fill_price_str) if fill_price_str else None
        except ValueError:
            fill_price = None
        try:
            qty = float(qty_str) if qty_str else None
        except ValueError:
            qty = None

        trade_action = fill.get("trade_action", "")
        is_long = trade_action in ("BUY_OPEN", "BUY_COVER")

        row = {
            "fill_time": fill.get("fill_time", ""),
            "ticker": ticker,
            "direction": "BUY" if is_long else "SHORT",
            "qty": qty,
            "fill_price": fill_price,
            "log_step": fill.get("log_step", ""),
            "log_wide_spread": fill.get("log_wide_spread", ""),
            "slippage_bps": fill.get("slippage_bps", ""),
            "fill_vs_log_mid": fill.get("fill_vs_log_mid", ""),
        }

        if log_entry and fill_price is not None and qty is not None:
            trigger = log_entry["trigger_price"]
            gap = round(fill_price - trigger, 4)
            gap_bps = round(gap / trigger * 10000, 1) if trigger else None
            if log_entry["direction"] == "BULLISH":
                pnl_impact = round((trigger - fill_price) * qty, 2)
            else:
                pnl_impact = round((fill_price - trigger) * qty, 2)

            row.update({
                "window": log_entry["window"],
                "entry_type": log_entry["entry_type"],
                "trigger_price": trigger,
                "gap": gap,
                "gap_bps": gap_bps,
                "pnl_impact": pnl_impact,
            })
        elif log_entry:
            row.update({
                "window": log_entry["window"],
                "entry_type": log_entry["entry_type"],
                "trigger_price": log_entry["trigger_price"],
                "gap": None,
                "gap_bps": None,
                "pnl_impact": None,
            })
        else:
            logger.debug("No log entry matched for %s fill at %s", ticker, fill_dt)
            row.update({
                "window": "",
                "entry_type": "?",
                "trigger_price": None,
                "gap": None,
                "gap_bps": None,
                "pnl_impact": None,
            })

        results.append(row)

    return results


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

_CSV_COLS = [
    "fill_time", "window", "entry_type", "ticker", "direction", "qty",
    "trigger_price", "fill_price", "gap", "gap_bps", "pnl_impact",
    "log_step", "log_wide_spread", "slippage_bps", "fill_vs_log_mid",
]

_TABLE_COLS = [
    ("window",         5),
    ("entry_type",     8),
    ("ticker",         6),
    ("direction",      6),
    ("qty",            5),
    ("trigger_price", 10),
    ("fill_price",    10),
    ("gap",            8),
    ("gap_bps",        8),
    ("pnl_impact",    11),
    ("log_step",       5),
    ("log_wide_spread", 5),
]


def _fmt_val(v) -> str:
    if v is None or v == "" or v == "None":
        return "-"
    if isinstance(v, bool):
        return "Y" if v else "N"
    if v == "True":
        return "Y"
    if v == "False":
        return "N"
    if isinstance(v, float):
        if abs(v) >= 1000:
            return f"{v:,.2f}"
        return f"{v:.2f}"
    try:
        fv = float(v)
        if abs(fv) >= 1000:
            return f"{fv:,.2f}"
        return f"{fv:.2f}"
    except (ValueError, TypeError):
        return str(v)


def _fmt(v, width: int) -> str:
    s = _fmt_val(v)
    if len(s) > width:
        s = s[:width]
    return s.ljust(width)


def _parse_daily_pnl(log_path: str):
    """Return the day's actual P&L by parsing 'Daily P&L: +$NNN.NN' from the log."""
    if not log_path or not os.path.exists(log_path):
        return None
    pattern = re.compile(r"Daily P&L:\s*([+-]?)\$?([\d,]+\.?\d*)")
    with open(log_path) as f:
        for line in f:
            m = pattern.search(line)
            if m:
                sign, val = m.group(1), m.group(2)
                try:
                    result = float(val.replace(",", ""))
                    return -result if sign == "-" else result
                except ValueError:
                    continue
    return None


def _print_table(rows: list, target_date: date, daily_pnl=None) -> None:
    impacts = [float(r["pnl_impact"]) for r in rows if r.get("pnl_impact") is not None]
    total_impact = sum(impacts)
    total_favorable = sum(x for x in impacts if x >= 0)
    total_unfavorable = sum(x for x in impacts if x < 0)

    total_notional = sum(
        float(r.get("trigger_price") or 0) * float(r.get("qty") or 0)
        for r in rows
        if r.get("trigger_price") and r.get("qty")
    )

    line_width = sum(w for _, w in _TABLE_COLS) + 2 * (len(_TABLE_COLS) - 1)

    print(f"\n{'=' * (line_width + 2)}")
    print(f"  ENTRY SLIPPAGE — {target_date}")
    print(f"{'=' * (line_width + 2)}")
    print("  " + "  ".join(_fmt(h, w) for h, w in _TABLE_COLS))
    print("  " + "-" * line_width)
    for row in rows:
        print("  " + "  ".join(_fmt(row.get(col, ""), w) for col, w in _TABLE_COLS))
    print("  " + "-" * line_width)

    def _pct(value: float) -> str:
        if not total_notional:
            return ""
        return f"  ({value / total_notional * 100:+.3f}%)"

    print(f"\n  Net P&L impact vs backtest : ${total_impact:+,.2f}{_pct(total_impact)}")
    print(f"  Favorable entries          : ${total_favorable:+,.2f}{_pct(total_favorable)}")
    print(f"  Unfavorable entries        : ${total_unfavorable:+,.2f}{_pct(total_unfavorable)}")
    if total_notional:
        shortfall_bps = -total_impact / total_notional * 10000
        print(f"  Avg shortfall on notional  : {shortfall_bps:+.1f} bps  "
              f"(notional ${total_notional:,.0f})")

    # Step breakdown
    step_groups: dict = {}
    for r in rows:
        step = str(r.get("log_step") or "?")
        imp = r.get("pnl_impact")
        if step not in step_groups:
            step_groups[step] = {"count": 0, "impact": 0.0}
        step_groups[step]["count"] += 1
        if imp is not None:
            step_groups[step]["impact"] += float(imp)

    print("\n  By execution step:")
    for step in sorted(step_groups):
        g = step_groups[step]
        print(f"    Step {step}: {g['count']:2d} fills   impact ${g['impact']:+,.2f}{_pct(g['impact'])}")

    if daily_pnl is not None and daily_pnl != 0:
        pct_of_pnl = total_impact / daily_pnl * 100
        print(f"\n  Slippage as % of daily P&L : {pct_of_pnl:+.1f}%  (actual P&L: ${daily_pnl:+,.2f})")
    print()


def _write_slippage_csv(out_path: Path, rows: list, cols: list) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    logger.info("Saved %d rows → %s", len(rows), out_path)


# ---------------------------------------------------------------------------
# Options-specific helpers
# ---------------------------------------------------------------------------

_OPTIONS_CSV_COLS = [
    "fill_time", "window", "entry_type", "ticker", "symbol", "direction", "qty",
    "fill_price", "opt_log_mid", "opt_log_fair",
    "fill_vs_mid", "fill_vs_fair", "pnl_vs_mid", "pnl_vs_fair",
    "time_value_paid", "time_value_vs_hourly_avg",
    "opt_log_step", "opt_log_spread_pct",
]

_OPTIONS_TABLE_COLS = [
    ("window",                    5),
    ("entry_type",                8),
    ("ticker",                    6),
    ("qty",                       4),
    ("fill_price",               10),
    ("opt_log_mid",              10),
    ("opt_log_fair",             10),
    ("fill_vs_mid",               9),
    ("fill_vs_fair",              9),
    ("pnl_vs_mid",               10),
    ("pnl_vs_fair",              10),
    ("time_value_paid",           8),
    ("time_value_vs_hourly_avg",  8),
    ("opt_log_step",              5),
]


def _ensure_options_fills_csv(fills_csv: Path, target_date: date, log_file: str) -> bool:
    if fills_csv.exists():
        logger.info("Options fills CSV found: %s", fills_csv)
        return True
    logger.error(
        "Options fills CSV not found: %s\n"
        "  Generate it with:\n"
        "    source ~/.pyenv/versions/alpha_tech_tracker/bin/activate\n"
        "    PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker \\\n"
        "      python -m alpha_tech_tracker.op_momentum_strategy.fetch_ts_orders \\\n"
        "      --date %s --log-file %s",
        fills_csv, target_date, log_file,
    )
    return False


def _load_options_fills(fills_csv: Path, target_date: date) -> list:
    rows = []
    with open(fills_csv, newline="") as f:
        for row in csv.DictReader(f):
            if row.get("side") != "ENTRY":
                continue
            try:
                t = datetime.strptime(row["fill_time"], "%H:%M:%S")
                fill_dt = datetime(
                    target_date.year, target_date.month, target_date.day,
                    t.hour, t.minute, t.second, tzinfo=_ET,
                )
                rows.append({**row, "fill_datetime": fill_dt})
            except (ValueError, KeyError):
                continue
    logger.info("Loaded %d ENTRY option fills from %s", len(rows), fills_csv)
    return rows


def _to_float(v):
    try:
        return float(v) if v not in (None, "", "None") else None
    except (ValueError, TypeError):
        return None


def _match_and_compute_options(log_entries: list, fills: list) -> list:
    results = []
    for fill in fills:
        ticker = fill["ticker"]
        fill_dt = fill["fill_datetime"]

        candidates = [
            e for e in log_entries
            if e["ticker"] == ticker
            and e["log_ts_et"] <= fill_dt
            and (fill_dt - e["log_ts_et"]).total_seconds() <= 600
        ]
        log_entry = max(candidates, key=lambda e: e["log_ts_et"]) if candidates else None

        fill_price = _to_float(fill.get("fill_price"))
        qty = _to_float(fill.get("qty"))
        opt_log_mid = _to_float(fill.get("opt_log_mid"))
        opt_log_fair = _to_float(fill.get("opt_log_fair"))

        fill_vs_mid = None
        fill_vs_fair = None
        pnl_vs_mid = None
        pnl_vs_fair = None

        if fill_price is not None and qty is not None:
            if opt_log_mid is not None:
                fill_vs_mid = round(fill_price - opt_log_mid, 4)
                pnl_vs_mid = round(-fill_vs_mid * qty * 100, 2)
            if opt_log_fair is not None:
                fill_vs_fair = round(fill_price - opt_log_fair, 4)
                pnl_vs_fair = round(-fill_vs_fair * qty * 100, 2)

        row = {
            "fill_time": fill.get("fill_time", ""),
            "ticker": ticker,
            "symbol": fill.get("symbol", ""),
            "qty": qty,
            "fill_price": fill_price,
            "opt_log_mid": opt_log_mid,
            "opt_log_fair": opt_log_fair,
            "fill_vs_mid": fill_vs_mid,
            "fill_vs_fair": fill_vs_fair,
            "pnl_vs_mid": pnl_vs_mid,
            "pnl_vs_fair": pnl_vs_fair,
            "time_value_paid": _to_float(fill.get("time_value_paid")),
            "time_value_vs_hourly_avg": _to_float(fill.get("time_value_vs_hourly_avg")),
            "opt_log_step": fill.get("opt_log_step", ""),
            "opt_log_spread_pct": _to_float(fill.get("opt_log_spread_pct")),
        }

        if log_entry:
            row.update({
                "window": log_entry["window"],
                "entry_type": log_entry["entry_type"],
                "direction": log_entry["direction"],
            })
        else:
            logger.debug("No log entry matched for %s option fill at %s", ticker, fill_dt)
            row.update({"window": "", "entry_type": "?", "direction": ""})

        results.append(row)
    return results


def _print_options_table(rows: list, target_date: date, daily_pnl=None) -> None:
    mid_impacts = [r["pnl_vs_mid"] for r in rows if r.get("pnl_vs_mid") is not None]
    fair_impacts = [r["pnl_vs_fair"] for r in rows if r.get("pnl_vs_fair") is not None]
    total_mid = sum(mid_impacts)
    total_fair = sum(fair_impacts)

    tv_paid_vals = [
        r["time_value_paid"] * (r["qty"] or 0) * 100
        for r in rows
        if r.get("time_value_paid") is not None and r.get("qty") is not None
    ]
    total_tv_paid = sum(tv_paid_vals)

    line_width = sum(w for _, w in _OPTIONS_TABLE_COLS) + 2 * (len(_OPTIONS_TABLE_COLS) - 1)

    print(f"\n{'=' * (line_width + 2)}")
    print(f"  ENTRY SLIPPAGE (OPTIONS) — {target_date}")
    print(f"{'=' * (line_width + 2)}")
    print("  " + "  ".join(_fmt(h, w) for h, w in _OPTIONS_TABLE_COLS))
    print("  " + "-" * line_width)
    for row in rows:
        print("  " + "  ".join(_fmt(row.get(col, ""), w) for col, w in _OPTIONS_TABLE_COLS))
    print("  " + "-" * line_width)

    fav_mid = sum(x for x in mid_impacts if x >= 0)
    overhead_mid = sum(x for x in mid_impacts if x < 0)
    fav_fair = sum(x for x in fair_impacts if x >= 0)
    overhead_fair = sum(x for x in fair_impacts if x < 0)

    print(f"\n  ── vs bid-ask mid ──────────────────────────────────────────────")
    print(f"  Net P&L impact           : ${total_mid:+,.2f}")
    print(f"  Favorable fills          : ${fav_mid:+,.2f}  (filled below mid)")
    print(f"  Execution overhead       : ${overhead_mid:+,.2f}  (filled above mid)")
    print(f"\n  ── vs engine fair price ────────────────────────────────────────")
    print(f"  Net P&L impact           : ${total_fair:+,.2f}")
    print(f"  Favorable fills          : ${fav_fair:+,.2f}  (filled below fair)")
    print(f"  Execution overhead       : ${overhead_fair:+,.2f}  (filled above fair)")
    print(f"\n  ── time value ──────────────────────────────────────────────────")
    print(f"  Total time value paid    : ${total_tv_paid:+,.2f}  (intrinsic premium × contracts × 100)")

    step_groups = {}
    for r in rows:
        step = str(r.get("opt_log_step") or "?")
        if step not in step_groups:
            step_groups[step] = {"count": 0, "mid": 0.0, "fair": 0.0}
        step_groups[step]["count"] += 1
        if r.get("pnl_vs_mid") is not None:
            step_groups[step]["mid"] += r["pnl_vs_mid"]
        if r.get("pnl_vs_fair") is not None:
            step_groups[step]["fair"] += r["pnl_vs_fair"]

    print("\n  By execution step:")
    for step in sorted(step_groups):
        g = step_groups[step]
        print(f"    Step {step}: {g['count']:2d} fills   "
              f"vs_mid ${g['mid']:+,.2f}   vs_fair ${g['fair']:+,.2f}")

    if daily_pnl is not None and daily_pnl != 0:
        pct_mid = total_mid / daily_pnl * 100
        pct_fair = total_fair / daily_pnl * 100
        print(f"\n  Slippage vs mid as % of daily P&L  : {pct_mid:+.1f}%  (actual P&L: ${daily_pnl:+,.2f})")
        print(f"  Slippage vs fair as % of daily P&L : {pct_fair:+.1f}%")
    print()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Analyze entry slippage: gap between signal bar close and actual fill"
    )
    parser.add_argument(
        "--engine", choices=["stock", "options"], default="stock",
        help="Which engine's fills to analyze (default: stock)",
    )
    parser.add_argument(
        "--date", default=None,
        help="Trade date YYYY-MM-DD (default: today ET)",
    )
    parser.add_argument(
        "--log-file", default=None,
        help="Engine log file (default: logs/op_momentum_{engine}_YYYY-MM-DD.log)",
    )
    parser.add_argument(
        "--fills-dir", default="logs/fills",
        help="Root directory for per-date fill CSVs (default: logs/fills)",
    )
    parser.add_argument(
        "--daily-pnl", type=float, default=None,
        help="Override actual daily P&L (default: parsed from log file)",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--paper", dest="paper", action="store_true", default=True,
        help="Use paper trading account when fetching stock fills (default)",
    )
    group.add_argument(
        "--live", dest="paper", action="store_false",
        help="Use live trading account when fetching stock fills",
    )
    args = parser.parse_args()

    target_date = date.fromisoformat(args.date) if args.date else _now_et().date()
    fills_dir = Path(args.fills_dir) / str(target_date)

    daily_pnl = args.daily_pnl

    if args.engine == "options":
        log_file = args.log_file or f"logs/op_momentum_option_{target_date}.log"
        fills_csv = fills_dir / f"options_fills_{target_date}.csv"
        slippage_csv = fills_dir / f"entry_slippage_options_{target_date}.csv"

        if not _ensure_options_fills_csv(fills_csv, target_date, log_file):
            sys.exit(1)

        log_entries = _parse_log_entries(log_file)
        if not log_entries:
            logger.error("No 'Entering position' events found in %s", log_file)
            sys.exit(1)

        fills = _load_options_fills(fills_csv, target_date)
        if not fills:
            logger.info("No ENTRY option fills for %s — nothing to analyze", target_date)
            return

        rows = _match_and_compute_options(log_entries, fills)
        matched = sum(1 for r in rows if r.get("window"))

        if daily_pnl is None:
            daily_pnl = _parse_daily_pnl(log_file)
        if daily_pnl is not None:
            logger.info("Daily P&L: $%+.2f", daily_pnl)

        _print_options_table(rows, target_date, daily_pnl=daily_pnl)
        _write_slippage_csv(slippage_csv, rows, _OPTIONS_CSV_COLS)

        print(f"Output : {slippage_csv}")
        print(f"Entries: {len(rows)} fills analyzed, {matched} matched to log entry event")

    else:
        log_file = args.log_file or f"logs/op_momentum_stock_{target_date}.log"
        fills_csv = fills_dir / f"stocks_fills_{target_date}.csv"
        slippage_csv = fills_dir / f"entry_slippage_{target_date}.csv"

        if not _ensure_fills_csv(fills_csv, target_date, log_file, args.paper):
            logger.error("Cannot proceed: fills CSV unavailable for %s", target_date)
            sys.exit(1)

        log_entries = _parse_log_entries(log_file)
        if not log_entries:
            logger.error("No 'Entering position' events found in %s", log_file)
            sys.exit(1)

        fills = _load_fills(fills_csv, target_date)
        if not fills:
            logger.info("No ENTRY fills for %s — nothing to analyze", target_date)
            return

        rows = _match_and_compute(log_entries, fills)
        matched = sum(1 for r in rows if r.get("trigger_price") is not None)

        if daily_pnl is None:
            daily_pnl = _parse_daily_pnl(log_file)
        if daily_pnl is not None:
            logger.info("Daily P&L: $%+.2f", daily_pnl)

        _print_table(rows, target_date, daily_pnl=daily_pnl)
        _write_slippage_csv(slippage_csv, rows, _CSV_COLS)

        print(f"Output : {slippage_csv}")
        print(f"Entries: {len(rows)} fills analyzed, {matched} matched to log trigger price")


if __name__ == "__main__":
    main()

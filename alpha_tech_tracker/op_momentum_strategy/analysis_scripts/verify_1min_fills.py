"""
verify_1min_fills.py

Verify whether the optimistic gain from `--no-exit-at-bar-close` is reachable
with 1-min bar detection in the live engine.

Method:
  1. Run the default-mode (`exit_at_bar_close=True`) selector backtest for the
     user's configured period.  This produces the SAME trade selection that the
     live engine would make.
  2. For each primary trade (and re-entry sub-trade: REV / BR / BRU) that
     exited via `hard_stop` or `fallback_20pct`, re-fill using 1-min bars:
       - Compute the stop level (or_high/or_low/midpoint based on signal/type).
       - Walk the 1-min bars inside the 5-min exit bar.
       - First 1-min close that crosses the stop becomes the new fill.
       - If no 1-min close crosses (rare; the 5-min close did cross), fall back
         to the 5-min bar close.
  3. Recompute `cap_pnl` per trade using the slot_capital allocated by the
     default-mode backtest.  (Compounding effect of changed capital is not
     propagated -- this is a fill-realism check, not a full re-simulation.)
  4. Aggregate vs 5-min default and vs 5-min --no-exit-at-bar-close optimistic
     (which fills at the stop level exactly).

Usage:
  python alpha_tech_tracker/op_momentum_strategy/verify_1min_fills.py \\
      --start 2024-01-01 --end 2024-03-31
"""

import argparse
import json
import os
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from alpaca.data.enums import DataFeed
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

from alpha_tech_tracker.op_momentum_strategy.op_momentum_selector import DEFAULT_TICKERS
from alpha_tech_tracker.op_momentum_strategy.op_momentum_selector_backtest import (
    INITIAL_CAPITAL,
    _apply_capital_flow,
    _parse_weights,
    run_selector_backtest,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CACHE_DIR = PROJECT_ROOT / "market_data" / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

STOP_PCT = 0.15
FALLBACK_PCT = 0.20

DST_START_2024 = date(2024, 3, 10)
DST_END_2024 = date(2024, 11, 3)


def _et_offset(d: date) -> int:
    if DST_START_2024 <= d < DST_END_2024:
        return -4
    return -5


def _et_min_to_utc(d: date, et_min: int) -> datetime:
    off = _et_offset(d)
    h, m = divmod(et_min, 60)
    return datetime(d.year, d.month, d.day, h - off, m, tzinfo=timezone.utc)


def _1min_cache_path(ticker: str, start_str: str, end_str: str) -> Path:
    return CACHE_DIR / f"alpaca_sip_1min_{ticker}_{start_str}_{end_str}.json"


def _load_1min_cache(path: Path) -> dict:
    raw = json.loads(path.read_text())
    cols = raw["columns"]
    oi = cols.index("Open")
    hi = cols.index("High")
    li = cols.index("Low")
    ci = cols.index("Close")
    bars = {}
    for ts_str, row in zip(raw["index"], raw["data"]):
        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        bars[ts] = {"open": row[oi], "high": row[hi], "low": row[li], "close": row[ci]}
    return bars


def fetch_1min_bars(tickers: list, start_str: str, end_str: str) -> dict:
    key = os.environ.get("ALPACA_API_KEY", "")
    secret = os.environ.get("ALPACA_SECRET_KEY", "")
    client = StockHistoricalDataClient(key, secret)

    result = {}
    for ticker in tickers:
        path = _1min_cache_path(ticker, start_str, end_str)
        if path.exists():
            print(f"  {ticker}: cache hit")
            result[ticker] = _load_1min_cache(path)
            continue

        print(f"  {ticker}: fetching from Alpaca...", end=" ", flush=True)
        req = StockBarsRequest(
            symbol_or_symbols=ticker,
            timeframe=TimeFrame(amount=1, unit=TimeFrameUnit.Minute),
            start=datetime.fromisoformat(start_str),
            end=datetime.fromisoformat(end_str),
            feed=DataFeed.SIP,
            adjustment="raw",
        )
        bars_resp = client.get_stock_bars(req)
        df = bars_resp.df
        if df.empty:
            print("0 bars")
            result[ticker] = {}
            continue
        if ticker in df.index.get_level_values(0):
            df = df.loc[ticker]
        df.index = df.index.tz_convert("UTC")

        raw = {
            "columns": ["Open", "High", "Low", "Close", "Volume"],
            "index": [ts.isoformat() for ts in df.index],
            "data": [
                [r.open, r.high, r.low, r.close, r.volume]
                for _, r in df.iterrows()
            ],
        }
        path.write_text(json.dumps(raw))
        result[ticker] = _load_1min_cache(path)
        print(f"{len(df)} bars")
    return result


def _primary_stop_and_dir(row: dict):
    """For PRIMARY trade exit (hard_stop or fallback_20pct)."""
    sig = row["signal"]
    or_range = row["or_high"] - row["or_low"]
    reason = row["exit_reason"]
    if reason == "hard_stop":
        pct = STOP_PCT
    elif reason == "fallback_20pct":
        pct = FALLBACK_PCT
    else:
        return None, None
    if sig == "BULLISH":
        return row["or_high"] - pct * or_range, "long"
    return row["or_low"] + pct * or_range, "short"


def _sub_stop_and_dir(row: dict, sub_signal: str):
    """For REV/BR/BRU sub-trade exit. All use midpoint as hard_stop."""
    return row["midpoint"], "long" if sub_signal == "BULLISH" else "short"


def _exit_bar_window_utc(d: date, exit_min_end_et: int):
    """5-min bar [exit_min_end - 5, exit_min_end) in UTC."""
    start_utc = _et_min_to_utc(d, exit_min_end_et - 5)
    end_utc = _et_min_to_utc(d, exit_min_end_et)
    return start_utc, end_utc


def _find_1min_cross(bars: dict, start_utc: datetime, end_utc: datetime,
                     stop: float, direction: str):
    """First 1-min close in [start, end) that crosses stop. Returns (close, ts) or None."""
    ts = start_utc
    while ts < end_utc:
        bar = bars.get(ts)
        if bar is not None:
            c = bar["close"]
            if (direction == "long" and c <= stop) or (direction == "short" and c >= stop):
                return c, ts
        ts += timedelta(minutes=1)
    return None


def _refill_primary(row, bars_by_ticker):
    """Returns (new_exit_price, kind). Kind: 'unchanged' | '1min_cross' | '5min_close_fallback'."""
    if row["exit_reason"] not in ("hard_stop", "fallback_20pct"):
        return row["exit_price"], "unchanged"
    stop, direction = _primary_stop_and_dir(row)
    if stop is None:
        return row["exit_price"], "unchanged"
    bars = bars_by_ticker.get(row["ticker"], {})
    if not bars:
        return row["exit_price"], "unchanged"
    or_close = row["or_close_min"]
    exit_min_end = or_close + (row["bars_held"] + 1) * 5
    s_utc, e_utc = _exit_bar_window_utc(row["date"], exit_min_end)
    hit = _find_1min_cross(bars, s_utc, e_utc, stop, direction)
    if hit is None:
        return row["exit_price"], "5min_close_fallback"
    return hit[0], "1min_cross"


def _refill_subtrade(row, prefix: str, sub_signal: str, bars_by_ticker):
    """Returns (new_exit_price, kind)."""
    ep_key = f"{prefix}_entry_price"
    ep = row.get(ep_key, 0)
    if not ep:
        return None, "no_subtrade"
    exit_reason = row.get(f"{prefix}_exit_reason", "")
    old_exit = row.get(f"{prefix}_exit_price", 0)
    if exit_reason != "hard_stop":
        return old_exit, "unchanged"
    stop, direction = _sub_stop_and_dir(row, sub_signal)
    bars = bars_by_ticker.get(row["ticker"], {})
    if not bars:
        return old_exit, "unchanged"
    or_close = row["or_close_min"]
    primary_bars = row.get("bars_held", 0)
    entry_idx = row.get(f"{prefix}_entry_idx", 0)
    sub_bars = row.get(f"{prefix}_bars_held", 0)
    sub_entry_min = or_close + (primary_bars + entry_idx + 2) * 5
    sub_exit_min_end = sub_entry_min + (sub_bars + 1) * 5
    s_utc, e_utc = _exit_bar_window_utc(row["date"], sub_exit_min_end)
    hit = _find_1min_cross(bars, s_utc, e_utc, stop, direction)
    if hit is None:
        return old_exit, "5min_close_fallback"
    return hit[0], "1min_cross"


def _optimistic_primary(row):
    """Stop-level fill for primary (matches --no-exit-at-bar-close)."""
    if row["exit_reason"] not in ("hard_stop", "fallback_20pct"):
        return row["exit_price"]
    stop, _ = _primary_stop_and_dir(row)
    return stop if stop is not None else row["exit_price"]


def _primary_pnl(row, exit_price):
    if row["signal"] == "BULLISH":
        return exit_price - row["entry_price"]
    return row["entry_price"] - exit_price


def _sub_pnl(row, prefix, sub_signal, exit_price):
    ep = row[f"{prefix}_entry_price"]
    if sub_signal == "BULLISH":
        return exit_price - ep
    return ep - exit_price


SUB_DEFS = [
    # (prefix, sub_signal_resolver)
    # REV: BULLISH (after BEARISH primary)
    ("rev", lambda r: "BULLISH"),
    # BR: BEARISH (after BULLISH primary)
    ("br", lambda r: "BEARISH"),
    # BRU: BULLISH (after BULLISH primary that stopped out, bearish-flip then bullish-recover)
    ("bru", lambda r: "BULLISH"),
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2024-01-01")
    parser.add_argument("--end", default="2024-03-31")
    args = parser.parse_args()

    eval_start = date.fromisoformat(args.start)
    eval_end = date.fromisoformat(args.end)

    windows = [
        {"label": "M1", "opening_start": "09:30", "opening_bars": 3,
         "group": "first", "split_pct": 1.0},
        {"label": "A1", "opening_start": "10:00", "opening_bars": 3,
         "group": "sequential", "split_pct": 1.0},
        {"label": "A2", "opening_start": "11:45", "opening_bars": 2,
         "group": "sequential", "split_pct": 1.0},
        {"label": "A3", "opening_start": "13:15", "opening_bars": 1,
         "group": "sequential", "split_pct": 1.0},
        {"label": "A4", "opening_start": "15:15", "opening_bars": 2,
         "group": "sequential", "split_pct": 1.0},
    ]

    print(f"Running default backtest {eval_start} → {eval_end}...")
    n = 2
    weights = _parse_weights(None, n)
    trade_rows, _, _ = run_selector_backtest(
        n=n,
        tickers=list(DEFAULT_TICKERS),
        eval_start=eval_start,
        eval_end=eval_end,
        windows=windows,
        feed=DataFeed.SIP,
        source="alpaca",
        enable_reversal=True,
        enable_bearish_reentry=True,
        enable_bullish_reentry=True,
        min_hold_bars=1,
        exit_at_bar_close=True,
    )

    print("Applying capital flow (sequential windows, $10k/day reset)...")
    _apply_capital_flow(
        trade_rows,
        windows,
        initial_capital=INITIAL_CAPITAL,
        weights=weights,
        n=n,
        morning_split=[1.0],
        compound=False,
        enable_doubledown=False,
    )

    active = [r for r in trade_rows if not r.get("skipped")]
    print(f"\nActive trade rows: {len(active)}")

    tickers_needed = sorted({r["ticker"] for r in active})
    start_iso = eval_start.isoformat()
    end_iso = (eval_end + timedelta(days=1)).isoformat()
    print(f"\nFetching 1-min bars for {len(tickers_needed)} tickers...")
    bars_by_ticker = fetch_1min_bars(tickers_needed, start_iso, end_iso)

    print("\nRe-filling exits...")

    # accumulators: (window, month) -> dict of totals
    agg = defaultdict(lambda: {
        "default_cap": 0.0, "optimistic_cap": 0.0, "onemin_cap": 0.0,
        "default_wins": 0, "default_losses": 0,
        "onemin_wins": 0, "onemin_losses": 0,
        "trades": 0,
        "primary_refilled": 0, "primary_no_cross": 0,
        "sub_refilled": 0, "sub_no_cross": 0,
    })

    detail_rows = []

    for row in active:
        slot_cap = row.get("slot_capital", 0.0)
        if slot_cap == 0:
            continue
        entry_price = row["entry_price"]
        ym = f"{row['date'].year}-{row['date'].month:02d}"
        win_label = row["window"]
        key = (win_label, ym)

        # --- PRIMARY ---
        primary_default_exit = row["exit_price"]
        primary_default_pnl = _primary_pnl(row, primary_default_exit)
        primary_opt_exit = _optimistic_primary(row)
        primary_opt_pnl = _primary_pnl(row, primary_opt_exit)
        primary_1min_exit, primary_kind = _refill_primary(row, bars_by_ticker)
        primary_1min_pnl = _primary_pnl(row, primary_1min_exit)

        if primary_kind == "1min_cross":
            agg[key]["primary_refilled"] += 1
        elif primary_kind == "5min_close_fallback":
            agg[key]["primary_no_cross"] += 1

        # Per-dollar P&L for the primary leg
        scale = slot_cap / entry_price
        primary_default_cap = scale * primary_default_pnl
        primary_opt_cap = scale * primary_opt_pnl
        primary_1min_cap = scale * primary_1min_pnl

        # --- SUB-TRADES ---
        sub_default_cap = 0.0
        sub_opt_cap = 0.0
        sub_1min_cap = 0.0
        for prefix, sig_fn in SUB_DEFS:
            ep = row.get(f"{prefix}_entry_price", 0) or 0
            if not ep:
                continue
            # cap_pnl for sub-trades: slot_cap / ep * pnl
            sub_sig = sig_fn(row)
            sub_default_exit = row[f"{prefix}_exit_price"]
            sub_default_pnl = _sub_pnl(row, prefix, sub_sig, sub_default_exit)
            sub_default_cap += (slot_cap / ep) * sub_default_pnl

            # Sub-trades already fill at stop level when hard_stop, so optimistic == default
            sub_opt_cap += (slot_cap / ep) * sub_default_pnl

            sub_1min_exit, sub_kind = _refill_subtrade(row, prefix, sub_sig, bars_by_ticker)
            sub_1min_pnl = _sub_pnl(row, prefix, sub_sig, sub_1min_exit)
            sub_1min_cap += (slot_cap / ep) * sub_1min_pnl

            if sub_kind == "1min_cross":
                agg[key]["sub_refilled"] += 1
            elif sub_kind == "5min_close_fallback":
                agg[key]["sub_no_cross"] += 1

        agg[key]["default_cap"] += primary_default_cap + sub_default_cap
        agg[key]["optimistic_cap"] += primary_opt_cap + sub_opt_cap
        agg[key]["onemin_cap"] += primary_1min_cap + sub_1min_cap
        agg[key]["trades"] += 1

        if primary_default_cap + sub_default_cap > 0:
            agg[key]["default_wins"] += 1
        else:
            agg[key]["default_losses"] += 1
        if primary_1min_cap + sub_1min_cap > 0:
            agg[key]["onemin_wins"] += 1
        else:
            agg[key]["onemin_losses"] += 1

        if row["exit_reason"] in ("hard_stop", "fallback_20pct"):
            detail_rows.append({
                "date": str(row["date"]),
                "win": win_label,
                "ticker": row["ticker"],
                "sig": row["signal"],
                "reason": row["exit_reason"],
                "entry": entry_price,
                "exit_5min": primary_default_exit,
                "exit_1min": primary_1min_exit,
                "exit_opt": primary_opt_exit,
                "kind": primary_kind,
                "pnl_5min_cap": round(primary_default_cap, 2),
                "pnl_1min_cap": round(primary_1min_cap, 2),
                "pnl_opt_cap": round(primary_opt_cap, 2),
            })

    # --- print summary ---
    print()
    print("━" * 110)
    print(f"  {'Window':<8} {'Month':<10} {'Trades':>7} "
          f"{'5min$':>12} {'1min$':>12} {'Opt$':>12} "
          f"{'Δ1min vs 5min':>14} {'Δ1min vs Opt':>13} {'P refilled':>11}")
    print("━" * 110)

    totals = {"default_cap": 0.0, "optimistic_cap": 0.0, "onemin_cap": 0.0,
              "trades": 0, "primary_refilled": 0, "primary_no_cross": 0,
              "sub_refilled": 0, "sub_no_cross": 0}
    for key in sorted(agg.keys()):
        a = agg[key]
        win, ym = key
        delta_5 = a["onemin_cap"] - a["default_cap"]
        delta_opt = a["onemin_cap"] - a["optimistic_cap"]
        print(f"  {win:<8} {ym:<10} {a['trades']:>7} "
              f"{a['default_cap']:>+12.2f} {a['onemin_cap']:>+12.2f} "
              f"{a['optimistic_cap']:>+12.2f} "
              f"{delta_5:>+14.2f} {delta_opt:>+13.2f} "
              f"{a['primary_refilled']:>11}")
        for k in totals:
            totals[k] += a[k]
    print("━" * 110)
    delta_5 = totals["onemin_cap"] - totals["default_cap"]
    delta_opt = totals["onemin_cap"] - totals["optimistic_cap"]
    print(f"  {'TOTAL':<19} {totals['trades']:>7} "
          f"{totals['default_cap']:>+12.2f} {totals['onemin_cap']:>+12.2f} "
          f"{totals['optimistic_cap']:>+12.2f} "
          f"{delta_5:>+14.2f} {delta_opt:>+13.2f} "
          f"{totals['primary_refilled']:>11}")
    print("━" * 110)

    # Per-window roll-up across months
    win_agg = defaultdict(lambda: {"default_cap": 0.0, "onemin_cap": 0.0,
                                   "optimistic_cap": 0.0, "trades": 0})
    for (win, _), a in agg.items():
        win_agg[win]["default_cap"] += a["default_cap"]
        win_agg[win]["onemin_cap"] += a["onemin_cap"]
        win_agg[win]["optimistic_cap"] += a["optimistic_cap"]
        win_agg[win]["trades"] += a["trades"]
    print(f"\n  Per-window roll-up ({eval_start} → {eval_end}):")
    print(f"  {'Window':<8} {'Trades':>7} {'5min$':>12} {'1min$':>12} {'Opt$':>12} "
          f"{'1min recovers % of opt-vs-5min gap':>40}")
    for win in sorted(win_agg.keys()):
        a = win_agg[win]
        opt_gap = a["optimistic_cap"] - a["default_cap"]
        onemin_gap = a["onemin_cap"] - a["default_cap"]
        recover_pct = (onemin_gap / opt_gap * 100) if abs(opt_gap) > 1e-6 else float("nan")
        print(f"  {win:<8} {a['trades']:>7} "
              f"{a['default_cap']:>+12.2f} {a['onemin_cap']:>+12.2f} "
              f"{a['optimistic_cap']:>+12.2f} {recover_pct:>39.1f}%")

    print(f"\n  Re-fill statistics:")
    print(f"    Primary hard_stop/fallback exits re-filled at 1-min cross: {totals['primary_refilled']}")
    print(f"    Primary exits with no 1-min cross (fell back to 5min close): {totals['primary_no_cross']}")
    print(f"    Sub-trade hard_stop exits re-filled: {totals['sub_refilled']}")
    print(f"    Sub-trade exits with no 1-min cross: {totals['sub_no_cross']}")

    # save detail rows
    out_path = PROJECT_ROOT / "logs" / f"verify_1min_fills_{args.start}_{args.end}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(detail_rows, indent=2))
    print(f"\n  Detail saved: {out_path}")


if __name__ == "__main__":
    main()

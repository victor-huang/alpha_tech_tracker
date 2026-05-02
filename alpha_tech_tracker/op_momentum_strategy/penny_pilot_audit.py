#!/usr/bin/env python3
"""
Penny Pilot Audit — probes each DEFAULT_TICKERS ticker against TradeStation's
live order placement API to determine the actual options tick schedule.

Method: selects next week's ITM call using the same strike-offset logic as
ITMOptionContractSelector, then places a LIMIT order at floor(mid) + $0.07.
That price is never a valid multiple of $0.05 (Penny Pilot, option >= $3) or
$0.10 (Non-Pilot, option >= $3), so TradeStation immediately rejects it and
includes the required increment in the RejectReason field.

  Penny Pilot:  "Price = 14.07 not rounded to a valid price increment [ 0.05 ]"
  Non-Pilot:    "Price = 14.07 not rounded to a valid price increment [ 0.1 ]"

For sub-$3 options (edge case — should not occur for this pool's ITM strikes):
  Uses $0.06 — invalid for the $0.05 non-pilot tick, valid for the $0.01 penny tick.
  If TradeStation accepts the order (penny pilot), it is cancelled immediately.

Usage (requires an active TradeStation session):
  source ~/.pyenv/versions/alpha_tech_tracker/bin/activate
  PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker \\
    python alpha_tech_tracker/op_momentum_strategy/penny_pilot_audit.py

  # Custom tickers:
    ... penny_pilot_audit.py --tickers TSLA NVDA

  # Dry-run (select contracts + fetch quotes, no orders placed):
    ... penny_pilot_audit.py --dry-run
"""

import argparse
import logging
import math
import sys
import time
from datetime import datetime
from decimal import Decimal
from typing import Optional

import pytz

from alpha_tech_tracker.op_momentum_strategy.config import (
    _load_config,
    build_execution_client,
)
from alpha_tech_tracker.op_momentum_strategy.contract_selector import (
    _fetch_contracts_with_expiry_fallback,
    _strike_increment,
    _strike_offsets,
)
from alpha_tech_tracker.op_momentum_strategy.models import _stock_bid_ask
from alpha_tech_tracker.op_momentum_strategy.op_momentum_selector import DEFAULT_TICKERS
from alpha_tech_tracker.op_momentum_strategy.option_price_monitor import (
    ticker_is_penny_pilot,
)
from alpha_tech_tracker.trade_api.tradestation.client import _parse_tick_from_error

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s — %(message)s")

_D = Decimal
_PROBE_RATE_LIMIT_S = 0.5


def _select_itm_call(client, ticker: str, stock_price: float) -> Optional[dict]:
    """Select next week's ITM call using the same logic as ITMOptionContractSelector."""
    incr = _strike_increment(stock_price)
    call_offset, _ = _strike_offsets(stock_price)
    raw_target = _D(str(stock_price)) * call_offset
    target_strike = (raw_target // incr) * incr
    search_radius = incr * 3

    contracts, expiry = _fetch_contracts_with_expiry_fallback(
        client,
        ticker,
        "CALL",
        target_strike - search_radius,
        target_strike + search_radius,
    )
    if not contracts:
        return None
    best = min(contracts, key=lambda c: abs(_D(str(c["strike_price"])) - target_strike))
    return {
        "occ_symbol": best["symbol"],
        "strike": float(best["strike_price"]),
        "expiry": expiry,
        "target_strike": float(target_strike),
    }


def _invalid_test_price(mid: float) -> float:
    """Return a limit price guaranteed to trigger a tick-size rejection.

    For mid >= $3.00:
      floor(mid) + $0.07 is never a multiple of $0.05 (Penny Pilot) or
      $0.10 (Non-Pilot), so both schedules reject the order.

    For mid < $3.00 (edge case — not expected for ITM pool tickers):
      $0.06 is invalid for the $0.05 non-pilot tick but valid for the
      $0.01 penny-pilot tick; caller must handle the non-rejection case.
    """
    if mid >= 3.0:
        return math.floor(mid) + 0.07
    return 0.06


def _classify_from_tick(tick: Optional[Decimal], mid: float) -> Optional[str]:
    if tick is None:
        return None
    if mid >= 3.0:
        if tick == _D("0.05"):
            return "penny_pilot"
        if tick in (_D("0.1"), _D("0.10")):
            return "non_pilot"
    else:
        if tick == _D("0.05"):
            return "non_pilot"
        if tick == _D("0.01"):
            return "penny_pilot"
    return f"unknown_tick_{tick}"


def probe_ticker(client, ticker: str, dry_run: bool = False) -> dict:
    """
    Probe one ticker. Returns a dict with:
      ticker, stock_price, occ_symbol, strike, expiry, option_mid,
      test_price, reject_reason, tick, classification, error
    """
    result = {
        "ticker": ticker,
        "stock_price": None,
        "occ_symbol": None,
        "strike": None,
        "expiry": None,
        "option_mid": None,
        "test_price": None,
        "reject_reason": None,
        "tick": None,
        "classification": None,
        "error": None,
    }

    try:
        quote = client.get_stock_quote(ticker)
        bid, ask = _stock_bid_ask(quote)
        all_data = quote.get("QuoteResponse", {}).get("QuoteData", [{}])[0].get("All", {})
        last = float(all_data.get("last") or 0)
        stock_price = float(ask or bid or last)
        result["stock_price"] = stock_price
        if stock_price == 0:
            result["error"] = "stock quote returned 0"
            return result

        contract = _select_itm_call(client, ticker, stock_price)
        if not contract:
            result["error"] = "no ITM call contracts found"
            return result
        result.update(contract)

        occ_symbol = contract["occ_symbol"]
        option_quote = client.get_option_quote_by_occ(occ_symbol)
        mid = float(option_quote.get("mid") or 0)
        result["option_mid"] = mid
        if mid == 0:
            result["error"] = "option quote returned mid=0"
            return result

        test_price = _invalid_test_price(mid)
        result["test_price"] = test_price

        if dry_run:
            return result

        order_result = client.place_option_order(
            symbol=ticker,
            price=test_price,
            price_type="LIMIT",
            order_action="BUY_OPEN",
            quantity=1,
            _option_symbol_override=occ_symbol,
        )

        raw = order_result.get("raw_response", {})
        order_data = (raw.get("Orders") or [{}])[0] if isinstance(raw, dict) else {}
        ts_status = order_data.get("Status", "")
        reject_reason = order_data.get("RejectReason", "") or ""
        result["reject_reason"] = reject_reason

        if ts_status == "REJ" or reject_reason:
            tick = _parse_tick_from_error(reject_reason)
            result["tick"] = tick
            result["classification"] = _classify_from_tick(tick, mid)
        else:
            # Order was accepted without tick rejection.
            # During market hours this means penny pilot (0.01 tick, valid price).
            # After market hours TS queues DAY orders without tick validation — unreliable.
            order_id = order_result.get("order_id")
            if order_id:
                client.cancel_order(order_id)
            et_now = datetime.now(pytz.timezone("America/New_York"))
            market_open = et_now.replace(hour=9, minute=30, second=0, microsecond=0)
            market_close = et_now.replace(hour=16, minute=0, second=0, microsecond=0)
            is_market_hours = market_open <= et_now <= market_close and et_now.weekday() < 5
            if is_market_hours:
                result["classification"] = "penny_pilot"
                result["tick"] = _D("0.01")
                result["reject_reason"] = "(order placed + cancelled — confirmed penny pilot)"
            else:
                result["classification"] = None
                result["error"] = (
                    f"order accepted without tick rejection at {et_now.strftime('%H:%M ET')} "
                    f"(market closed) — rerun during market hours 9:30–16:00 ET"
                )

    except Exception as exc:
        result["error"] = str(exc)

    return result


def _print_results(results: list, dry_run: bool):
    print()
    print("=" * 100)
    hdr = (
        f"  {'Ticker':<6}  {'Stock':>8}  {'Strike':>8}  {'Expiry':<12}  "
        f"{'Mid':>7}  {'TestPx':>7}  {'Tick':>6}  {'API Classification':<20}  Code Match?"
    )
    print(hdr)
    print("-" * 100)

    mismatches = []

    for r in results:
        ticker = r["ticker"]
        code_is_penny = ticker_is_penny_pilot(ticker)
        api_class = r["classification"]

        if r["error"]:
            print(
                f"  {ticker:<6}  {'—':>8}  {'—':>8}  {'—':<12}  "
                f"{'—':>7}  {'—':>7}  {'—':>6}  {'ERROR':<20}  {r['error']}"
            )
            continue

        stock = f"${r['stock_price']:.2f}"
        strike = f"${r['strike']:.0f}"
        expiry = str(r["expiry"])
        mid = f"${r['option_mid']:.2f}"
        test = f"${r['test_price']:.2f}" if r["test_price"] else "—"
        tick_str = str(r["tick"]) if r["tick"] else "?"

        if dry_run or api_class is None:
            api_label = "(dry run)"
            match_str = "—"
        elif api_class == "penny_pilot":
            api_label = "PENNY PILOT"
            match_str = "✓ match" if code_is_penny else "✗ MISMATCH (code=non_pilot)"
        elif api_class == "non_pilot":
            api_label = "NON-PILOT"
            match_str = "✓ match" if not code_is_penny else "✗ MISMATCH (code=penny_pilot)"
        else:
            api_label = api_class
            match_str = "?"

        if "MISMATCH" in match_str:
            mismatches.append(ticker)

        print(
            f"  {ticker:<6}  {stock:>8}  {strike:>8}  {expiry:<12}  "
            f"{mid:>7}  {test:>7}  {tick_str:>6}  {api_label:<20}  {match_str}"
        )

    print("=" * 100)

    if dry_run:
        print("\n  Dry-run complete — no orders placed. Re-run without --dry-run to probe tick sizes.")
    elif mismatches:
        print(f"\n  !! {len(mismatches)} mismatch(es) found: {', '.join(mismatches)}")
        api_non_pilot = sorted(r["ticker"] for r in results if r["classification"] == "non_pilot")
        print(f"\n  Suggested update to option_price_monitor.py:")
        print(f"    _NON_PENNY_PILOT_TICKERS: frozenset = frozenset({set(api_non_pilot)!r})")
    else:
        probed = [r for r in results if not r["error"] and r["classification"]]
        print(f"\n  All {len(probed)} probed tickers match the current _NON_PENNY_PILOT_TICKERS set.")

    print()


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--tickers",
        nargs="+",
        default=DEFAULT_TICKERS,
        metavar="TICKER",
        help="Tickers to probe (default: all DEFAULT_TICKERS)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Select contracts and fetch quotes but do not place any orders",
    )
    args = parser.parse_args()

    _load_config()

    print("\nBuilding TradeStation client...")
    try:
        client = build_execution_client(broker="tradestation")
    except Exception as exc:
        print(f"ERROR: could not build TradeStation client: {exc}", file=sys.stderr)
        print(
            "Run: python -m alpha_tech_tracker.op_momentum_strategy.tradestation_auth --verify",
            file=sys.stderr,
        )
        sys.exit(1)

    et_now = datetime.now(pytz.timezone("America/New_York"))
    market_open = et_now.replace(hour=9, minute=30, second=0, microsecond=0)
    market_close = et_now.replace(hour=16, minute=0, second=0, microsecond=0)
    is_market_hours = market_open <= et_now <= market_close and et_now.weekday() < 5

    mode = "DRY RUN (no orders)" if args.dry_run else "LIVE (places + rejects orders)"
    print(f"Mode     : {mode}")
    print(f"Tickers  : {', '.join(args.tickers)}")
    print(f"Pool size: {len(args.tickers)}")
    print(f"ET time  : {et_now.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    if not args.dry_run and not is_market_hours:
        print(
            "\n  WARNING: market is currently closed. TradeStation skips tick validation "
            "on after-hours DAY orders, so results will be unreliable.\n"
            "  Re-run between 9:30 AM and 4:00 PM ET on a trading day.\n"
        )
    else:
        print()

    results = []
    for ticker in args.tickers:
        print(f"  [{ticker}] probing...", end="", flush=True)
        r = probe_ticker(client, ticker, dry_run=args.dry_run)
        results.append(r)

        if r["error"]:
            print(f" ERROR — {r['error']}")
        elif r["classification"]:
            tick_display = str(r["tick"]) if r["tick"] else "?"
            print(
                f" {r['classification'].upper():<11}  tick=${tick_display:<5}  "
                f"strike=${r['strike']:.0f}  mid=${r['option_mid']:.2f}"
            )
        else:
            print(f" strike=${r['strike']:.0f}  mid=${r['option_mid']:.2f}  (dry run)")

        if not args.dry_run:
            time.sleep(_PROBE_RATE_LIMIT_S)

    _print_results(results, dry_run=args.dry_run)


if __name__ == "__main__":
    main()

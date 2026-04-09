"""
option_fair_price_tester.py

Live shadow-test for get_fair_price() against the paper Alpaca account.

Flow per test cycle:
  1. Select the relevant ITM contract via TimePremiumContractSelector.
  2. Buy 1 contract at market (paper) to establish a position.
  3. Poll option bid/ask every 5s while building a quote log.
  4. Compute fair_price via OptionPriceMonitor.get_fair_price().
  5. Place a limit SELL at fair_price.
  6. Poll every 5s for up to 15s — if filled, record the limit fill price.
  7. If not filled within 15s: cancel + market SELL to close.
  8. Write quote log and trade summary to CSV in output_dir.

Usage:
    python -m alpha_tech_tracker.op_momentum_strategy.option_fair_price_tester \\
        --ticker TSLA --option-type call

    # Run multiple cycles (separate manual invocations) and review CSVs afterward.
"""

import argparse
import csv
import logging
import os
import time
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP

import pytz

from alpaca.data.requests import OptionLatestQuoteRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.trading.requests import LimitOrderRequest, MarketOrderRequest

from alpha_tech_tracker.trade_api.alpaca_client.client import AlpacaAPIClient

from .config import _load_config
from .contract_selector import TimePremiumContractSelector
from .models import _D, _stock_bid_ask
from .option_price_monitor import OptionPriceMonitor, _quantize_option_price

logger = logging.getLogger(__name__)

ET = pytz.timezone("America/New_York")

_QUOTE_POLL_INTERVAL = 5   # seconds between bid/ask snapshots
_FILL_WAIT_SECONDS = 15    # max seconds to wait for limit sell to fill
_ENTRY_FILL_WAIT = 10      # seconds to wait for entry market order to fill
_DEFAULT_OUTPUT_DIR = "market_data/fair_price_test"


def _nearest_weekly_expiry(ref: date) -> date:
    """Return ref if it is Friday, otherwise the next Friday."""
    if ref.weekday() == 4:
        return ref
    days_ahead = 4 - ref.weekday()
    if days_ahead < 0:
        days_ahead += 7
    return ref + timedelta(days=days_ahead)


def _build_occ_symbol(ticker: str, expiry: date, option_type: str, strike: float) -> str:
    """Build an OCC option symbol from its components.

    e.g. ticker=TSLA, expiry=2026-04-10, option_type=call, strike=280
         → "TSLA260410C00280000"
    """
    cp = "C" if option_type.lower() == "call" else "P"
    strike_str = f"{float(strike):09.3f}".replace(".", "")
    return f"{ticker}{expiry.strftime('%y%m%d')}{cp}{strike_str}"

_QUOTE_FIELDS = [
    "elapsed_s", "timestamp",
    "bid", "ask", "mid", "spread_pct",
    "fair_price", "spread_position",
    "order_status",
]

_SUMMARY_FIELDS = [
    "run_timestamp", "ticker", "option_type", "option_symbol",
    "strike", "expiry", "days_to_expiry", "stock_price_at_entry",
    "entry_fill_price",
    "fair_price", "fair_branch", "spread_position_at_placement",
    "fill_method",         # "limit" or "market"
    "fill_price",
    "fill_time_seconds",   # None if market fallback
    "intrinsic_value",
    "below_intrinsic",     # True if fill_price < intrinsic — should never happen
    "improvement_vs_mid",  # fill_price - mid_at_placement (positive = better than mid for sell)
    "notes",
]


class FairPriceTester:
    """
    Single-ticker, single-option-type live paper test for get_fair_price().

    Instantiate, call run(), read the CSVs in output_dir for results.
    """

    def __init__(
        self,
        client: AlpacaAPIClient,
        ticker: str,
        option_type: str = "call",
        strike: float = None,
        expiry: date = None,
        output_dir: str = _DEFAULT_OUTPUT_DIR,
    ):
        self._client = client
        self._ticker = ticker
        self._option_type = option_type.lower()
        self._strike = strike
        self._expiry = expiry or _nearest_weekly_expiry(date.today())
        self._output_dir = output_dir
        self._monitor = OptionPriceMonitor(
            client=client,
            tickers=[ticker],
            output_dir=output_dir,
        )
        self._selector = TimePremiumContractSelector(client)

    # ------------------------------------------------------------------
    # Main test cycle
    # ------------------------------------------------------------------

    def run(self) -> dict:
        """
        Execute one full test cycle. Returns the summary dict.
        Writes quote_log and summary CSVs to output_dir.
        """
        run_ts = datetime.now(ET).strftime("%Y%m%d_%H%M%S")

        stock_price, option_symbol = self._select_contract()
        logger.info("Test cycle: %s  contract=%s  stock=%.2f", self._ticker, option_symbol, float(stock_price))

        entry_fill_price = self._enter_position(option_symbol)
        if entry_fill_price is None:
            logger.error("Could not confirm entry fill — aborting test cycle")
            return {}

        logger.info("Entry fill confirmed: %.2f", float(entry_fill_price))

        quote_log, fair_price, fair_branch, bid_at_place, ask_at_place, intrinsic = \
            self._run_sell_phase(option_symbol, stock_price)

        mid_at_placement = (bid_at_place + ask_at_place) / _D("2")
        spread_at_place = ask_at_place - bid_at_place
        spread_position = (
            float((fair_price - bid_at_place) / spread_at_place)
            if spread_at_place > _D("0") else None
        )

        fill_method = quote_log[-1]["order_status"]
        fill_price = _D(str(quote_log[-1].get("fill_price") or 0)) if quote_log else _D("0")
        fill_time_s = quote_log[-1].get("fill_time_seconds")
        improvement = float(fill_price - mid_at_placement) if fill_price else None
        below_intrinsic = fill_price > _D("0") and fill_price < intrinsic

        from .option_price_monitor import _parse_occ_symbol
        parsed = _parse_occ_symbol(option_symbol)

        summary = {
            "run_timestamp": run_ts,
            "ticker": self._ticker,
            "option_type": self._option_type,
            "option_symbol": option_symbol,
            "strike": parsed.get("strike", ""),
            "expiry": parsed.get("expiry_str", ""),
            "days_to_expiry": parsed.get("days_to_expiry", ""),
            "stock_price_at_entry": float(stock_price.quantize(_D("0.01"), rounding=ROUND_HALF_UP)),
            "entry_fill_price": float(entry_fill_price),
            "fair_price": float(fair_price),
            "fair_branch": fair_branch,
            "spread_position_at_placement": round(spread_position, 3) if spread_position is not None else "",
            "fill_method": fill_method,
            "fill_price": float(fill_price) if fill_price else "",
            "fill_time_seconds": fill_time_s if fill_time_s is not None else "",
            "intrinsic_value": float(intrinsic.quantize(_D("0.01"), rounding=ROUND_HALF_UP)),
            "below_intrinsic": below_intrinsic,
            "improvement_vs_mid": round(improvement, 3) if improvement is not None else "",
            "notes": "",
        }

        self._write_quote_log(run_ts, option_symbol, quote_log)
        self._write_summary(run_ts, summary)
        self._print_report(summary, quote_log)
        return summary

    # ------------------------------------------------------------------
    # Contract selection and entry
    # ------------------------------------------------------------------

    def _select_contract(self):
        raw_quote = self._client.get_stock_quote(self._ticker)
        bid_f, ask_f = _stock_bid_ask(raw_quote)
        stock_price = _D(str((bid_f + ask_f) / 2))

        if self._strike is not None:
            option_symbol = _build_occ_symbol(
                self._ticker, self._expiry, self._option_type, self._strike
            )
            logger.info(
                "Using manual strike=%.2f expiry=%s → %s",
                self._strike, self._expiry, option_symbol,
            )
        else:
            signal = "BULLISH" if self._option_type == "call" else "BEARISH"
            option_symbol = self._selector.select(self._ticker, signal, float(stock_price))

        return stock_price, option_symbol

    def _enter_position(self, option_symbol: str):
        """
        Buy 1 contract with limit escalation toward ask.
        Each step re-fetches the quote and raises the limit by 20% of spread from mid,
        capped at ask. Steps: mid, mid+20%, mid+40%, ... ask.
        Falls back to market only after the ask-level limit also fails to fill.
        Each step waits up to _FILL_WAIT_SECONDS.
        """
        _STEP_PCT = _D("0.20")
        step = 0
        while True:
            bid, ask = self._fetch_option_bid_ask(option_symbol)
            spread = ask - bid
            mid = (bid + ask) / _D("2")

            raw_price = mid + spread * _STEP_PCT * step
            price = _quantize_option_price(min(raw_price, ask))
            at_ask = price >= ask

            logger.info(
                "Entry step %d: limit BUY at %s (bid=%s ask=%s mid=%s)%s",
                step + 1, price, bid, ask, mid,
                " [at ask]" if at_ask else "",
            )
            order = self._place_order(option_symbol, side="BUY", price_type="LIMIT", price=price)
            order_id = order["order_id"]

            deadline = time.time() + _FILL_WAIT_SECONDS
            while time.time() < deadline:
                time.sleep(2)
                status = self._client.order_status(order_id)
                if status["status"] == "filled":
                    fill = _D(str(status["filled_avg_price"]))
                    logger.info("Entry filled at %s (step %d)", fill, step + 1)
                    return fill

            logger.info("Entry step %d unfilled — cancelling", step + 1)
            try:
                self._client.cancel_order(order_id)
            except Exception:
                logger.warning("Cancel may have failed for entry order %s", order_id)
            time.sleep(1)

            if at_ask:
                break
            step += 1

        logger.info("Entry escalation exhausted (reached ask) — placing market buy")
        order = self._place_order(option_symbol, side="BUY", price_type="MARKET")
        order_id = order["order_id"]
        deadline = time.time() + _ENTRY_FILL_WAIT
        while time.time() < deadline:
            time.sleep(2)
            status = self._client.order_status(order_id)
            if status["status"] == "filled":
                fill = _D(str(status["filled_avg_price"]))
                logger.info("Entry market fill at %s", fill)
                return fill

        logger.warning("Entry market order not filled within %ds", _ENTRY_FILL_WAIT)
        return None

    # ------------------------------------------------------------------
    # Sell phase: place fair-price limit, poll 5s, fallback market
    # ------------------------------------------------------------------

    def _run_sell_phase(self, option_symbol: str, stock_price):
        """
        Returns:
            quote_log        — list of per-5s snapshot dicts
            fair_price       — Decimal
            fair_branch      — str ("liquid" / "wide_spread" / "stale_bid" / "no_cache")
            bid_at_placement — Decimal
            ask_at_placement — Decimal
        """
        quote_log = []
        t0 = time.time()

        bid, ask, fair_price, fair_branch, intrinsic = self._compute_fair_price(option_symbol, stock_price)
        bid_at_place = bid
        ask_at_place = ask
        mid = (bid + ask) / _D("2")
        spread = ask - bid
        spread_pct = float(spread / mid * _D("100")) if mid > _D("0") else 0.0
        sp = float((fair_price - bid) / spread) if spread > _D("0") else None

        quote_log.append({
            "elapsed_s": 0,
            "timestamp": datetime.now(ET).strftime("%H:%M:%S"),
            "bid": float(bid),
            "ask": float(ask),
            "mid": float(mid),
            "spread_pct": round(spread_pct, 2),
            "fair_price": float(fair_price),
            "spread_position": round(sp, 3) if sp is not None else "",
            "order_status": "pre_order",
        })

        logger.info(
            "Placing limit SELL at fair_price=%s (branch=%s, bid=%s ask=%s)",
            fair_price, fair_branch, bid, ask,
        )
        sell_order = self._place_order(option_symbol, side="SELL", price_type="LIMIT", price=fair_price)
        sell_order_id = sell_order["order_id"]
        logger.info("Limit sell placed: %s", sell_order_id)

        # Poll every 5s for up to _FILL_WAIT_SECONDS
        filled = False
        fill_price = None
        fill_time_s = None
        polls = _FILL_WAIT_SECONDS // _QUOTE_POLL_INTERVAL

        for _ in range(polls):
            time.sleep(_QUOTE_POLL_INTERVAL)
            elapsed = round(time.time() - t0)

            status = self._client.order_status(sell_order_id)
            bid, ask = self._fetch_option_bid_ask(option_symbol)
            mid = (bid + ask) / _D("2")
            spread = ask - bid
            spread_pct = float(spread / mid * _D("100")) if mid > _D("0") else 0.0

            row = {
                "elapsed_s": elapsed,
                "timestamp": datetime.now(ET).strftime("%H:%M:%S"),
                "bid": float(bid),
                "ask": float(ask),
                "mid": float(mid),
                "spread_pct": round(spread_pct, 2),
                "fair_price": float(fair_price),
                "spread_position": "",
                "order_status": status["status"],
            }

            if status["status"] == "filled":
                fill_price = _D(str(status["filled_avg_price"]))
                fill_time_s = elapsed
                row["fill_price"] = float(fill_price)
                row["fill_time_seconds"] = fill_time_s
                row["order_status"] = "limit"
                filled = True
                quote_log.append(row)
                logger.info("Limit fill confirmed at %.2f after %ds", float(fill_price), fill_time_s)
                break

            quote_log.append(row)

        if not filled:
            logger.info("Limit unfilled after %ds — cancelling and placing market sell", _FILL_WAIT_SECONDS)
            try:
                self._client.cancel_order(sell_order_id)
            except Exception:
                logger.warning("Cancel may have failed (order could already be filled)")

            time.sleep(1)
            market_order = self._place_order(option_symbol, side="SELL", price_type="MARKET")
            market_order_id = market_order["order_id"]
            logger.info("Market sell placed: %s", market_order_id)

            deadline = time.time() + _ENTRY_FILL_WAIT
            while time.time() < deadline:
                time.sleep(2)
                status = self._client.order_status(market_order_id)
                if status["status"] == "filled":
                    fill_price = _D(str(status["filled_avg_price"]))
                    if fill_price < intrinsic:
                        logger.warning(
                            "BELOW INTRINSIC: market fill=%.2f < intrinsic=%.2f"
                            " (gave away $%.2f per contract)",
                            float(fill_price),
                            float(intrinsic),
                            float(intrinsic - fill_price),
                        )
                    break

            elapsed = round(time.time() - t0)
            bid, ask = self._fetch_option_bid_ask(option_symbol)
            mid = (bid + ask) / _D("2")
            spread = ask - bid
            spread_pct = float(spread / mid * _D("100")) if mid > _D("0") else 0.0
            quote_log.append({
                "elapsed_s": elapsed,
                "timestamp": datetime.now(ET).strftime("%H:%M:%S"),
                "bid": float(bid),
                "ask": float(ask),
                "mid": float(mid),
                "spread_pct": round(spread_pct, 2),
                "fair_price": float(fair_price),
                "spread_position": "",
                "order_status": "market",
                "fill_price": float(fill_price) if fill_price else "",
                "fill_time_seconds": "",
            })

        return quote_log, fair_price, fair_branch, bid_at_place, ask_at_place, intrinsic

    # ------------------------------------------------------------------
    # Pricing
    # ------------------------------------------------------------------

    def _compute_fair_price(self, option_symbol: str, stock_price):
        """
        Fetch live quote and run get_fair_price() logic, returning
        (bid, ask, fair_price, branch_name).
        """
        bid, ask = self._fetch_option_bid_ask(option_symbol)
        mid = (bid + ask) / _D("2")

        from .option_price_monitor import _parse_occ_symbol, _LIQUID_SPREAD_THRESHOLD
        parsed = _parse_occ_symbol(option_symbol)
        strike = parsed.get("strike", _D("0"))
        if self._option_type == "call":
            intrinsic = max(_D("0"), stock_price - strike)
        else:
            intrinsic = max(_D("0"), strike - stock_price)

        spread = ask - bid
        spread_pct = (spread / mid * _D("100")) if mid > _D("0") else _D("0")

        if spread_pct <= _LIQUID_SPREAD_THRESHOLD and bid >= intrinsic:
            fair = mid
            branch = "liquid"
        else:
            median_tv = self._monitor._median_time_value(option_symbol)
            if median_tv is None:
                median_tv = spread * _D("0.20")
                branch = "no_cache"
            else:
                branch = "stale_bid" if bid < intrinsic else "wide_spread"
            fair = intrinsic + median_tv

        fair = max(fair, intrinsic)  # hard floor — never sell below exercise value
        fair = min(ask, fair)        # cap at ask; don't drag down to bid when bid < intrinsic
        if fair < intrinsic:
            logger.warning(
                "Entire quote below intrinsic (bid=%s ask=%s intrinsic=%s)"
                " — best available=%s",
                bid.quantize(_D("0.01"), rounding=ROUND_HALF_UP),
                ask.quantize(_D("0.01"), rounding=ROUND_HALF_UP),
                intrinsic.quantize(_D("0.01"), rounding=ROUND_HALF_UP),
                fair.quantize(_D("0.01"), rounding=ROUND_HALF_UP),
            )
        fair = _quantize_option_price(fair)
        logger.info(
            "fair_price=%s branch=%s bid=%s ask=%s intrinsic=%s spread_pct=%.1f",
            fair, branch, bid, ask, intrinsic, float(spread_pct),
        )
        return bid, ask, fair, branch, intrinsic

    def _place_order(self, option_symbol: str, side: str, price_type: str, price=None, quantity: int = 1) -> dict:
        """Place a market or limit option order directly via the trading client."""
        order_side = OrderSide.BUY if side == "BUY" else OrderSide.SELL
        if price_type == "MARKET":
            order_data = MarketOrderRequest(
                symbol=option_symbol,
                qty=quantity,
                side=order_side,
                time_in_force=TimeInForce.DAY,
            )
        else:
            order_data = LimitOrderRequest(
                symbol=option_symbol,
                qty=quantity,
                side=order_side,
                time_in_force=TimeInForce.DAY,
                limit_price=float(price),
            )
        order = self._client._trading_client.submit_order(order_data=order_data)
        return {"order_id": str(order.id), "status": order.status.value}

    def _fetch_option_bid_ask(self, option_symbol: str):
        resp = self._client._option_data_client.get_option_latest_quote(
            OptionLatestQuoteRequest(symbol_or_symbols=[option_symbol])
        )
        q = resp[option_symbol]
        return _D(str(q.bid_price)), _D(str(q.ask_price))

    # ------------------------------------------------------------------
    # CSV output
    # ------------------------------------------------------------------

    def _run_dir(self, run_ts: str) -> str:
        today = datetime.now(ET).strftime("%Y-%m-%d")
        d = os.path.join(self._output_dir, today)
        os.makedirs(d, exist_ok=True)
        return d

    def _write_quote_log(self, run_ts: str, option_symbol: str, quote_log: list):
        d = self._run_dir(run_ts)
        path = os.path.join(d, f"quotes_{self._ticker}_{self._option_type}_{run_ts}.csv")
        extra_fields = ["fill_price", "fill_time_seconds"]
        all_fields = _QUOTE_FIELDS + extra_fields
        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=all_fields, extrasaction="ignore")
            writer.writeheader()
            for row in quote_log:
                writer.writerow({k: row.get(k, "") for k in all_fields})
        logger.info("Quote log written: %s", path)

    def _write_summary(self, run_ts: str, summary: dict):
        d = self._run_dir(run_ts)
        path = os.path.join(d, f"summary_{self._ticker}_{self._option_type}_{run_ts}.csv")
        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=_SUMMARY_FIELDS, extrasaction="ignore")
            writer.writeheader()
            writer.writerow(summary)
        logger.info("Summary written: %s", path)

    # ------------------------------------------------------------------
    # Console report
    # ------------------------------------------------------------------

    def _print_report(self, summary: dict, quote_log: list):
        print("\n" + "=" * 60)
        print(f"FAIR PRICE TEST — {summary['ticker']} {summary['option_type'].upper()}")
        print(f"Contract : {summary['option_symbol']}")
        print(f"Strike   : {summary['strike']}  Expiry: {summary['expiry']}  DTE: {summary['days_to_expiry']}")
        print(f"Stock    : ${summary['stock_price_at_entry']:.2f}")
        print()
        print(f"Entry fill     : ${summary['entry_fill_price']:.2f}")
        print(f"Fair price     : ${summary['fair_price']:.2f}  (branch: {summary['fair_branch']})")
        sp = summary['spread_position_at_placement']
        print(f"Spread pos     : {sp:.3f}  (0=bid  0.5=mid  1.0=ask)" if sp != "" else "Spread pos     : n/a")
        print()
        print(f"Intrinsic value: ${summary['intrinsic_value']:.2f}")
        print(f"Fill method    : {summary['fill_method'].upper()}")
        fp = summary['fill_price']
        print(f"Fill price     : ${fp:.2f}" if fp != "" else "Fill price     : n/a")
        if summary['below_intrinsic']:
            below_amt = summary['intrinsic_value'] - fp
            print(f"  *** BELOW INTRINSIC by ${below_amt:.2f} — sold below exercise value ***")
        ft = summary['fill_time_seconds']
        print(f"Fill time      : {ft}s" if ft != "" else "Fill time      : >15s (market fallback)")
        imp = summary['improvement_vs_mid']
        if imp != "":
            sign = "+" if imp >= 0 else ""
            print(f"vs mid         : {sign}{imp:.3f}  ({'better' if imp >= 0 else 'worse'} than mid for sell)")
        print()
        print("Quote log:")
        print(f"  {'t':>4}  {'bid':>6}  {'ask':>6}  {'mid':>6}  {'sprd%':>5}  {'status'}")
        for row in quote_log:
            print(
                f"  {row['elapsed_s']:>4}s  "
                f"{row['bid']:>6.2f}  {row['ask']:>6.2f}  {row['mid']:>6.2f}  "
                f"{row['spread_pct']:>5.1f}  {row['order_status']}"
            )
        print("=" * 60 + "\n")


# ------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------

def _parse_args():
    parser = argparse.ArgumentParser(
        description="Live paper-account test for get_fair_price() option pricing"
    )
    parser.add_argument("--ticker", required=True, help="Ticker to test (e.g. TSLA)")
    parser.add_argument(
        "--option-type", default="call", choices=["call", "put"],
        help="Option type to test (default: call)",
    )
    parser.add_argument(
        "--strike", type=float, default=None,
        help="Strike price to use (e.g. 280). If omitted, TimePremiumContractSelector picks it.",
    )
    parser.add_argument(
        "--expiry", type=str, default=None,
        help="Expiry date as YYYY-MM-DD (e.g. 2026-04-11). Defaults to next Friday.",
    )
    parser.add_argument(
        "--output-dir", default=_DEFAULT_OUTPUT_DIR,
        help="Directory for CSV output (default: market_data/fair_price_test)",
    )
    parser.add_argument(
        "--duration", type=float, default=None,
        help="Run repeated cycles for this many minutes (e.g. 2). Omit for a single cycle.",
    )
    parser.add_argument(
        "--log-level", default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    _load_config()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    expiry = date.fromisoformat(args.expiry) if args.expiry else None

    client = AlpacaAPIClient(is_paper_trading=True)
    tester = FairPriceTester(
        client=client,
        ticker=args.ticker,
        option_type=args.option_type,
        strike=args.strike,
        expiry=expiry,
        output_dir=args.output_dir,
    )

    if args.duration:
        deadline = time.time() + args.duration * 60
        cycle = 0
        while time.time() < deadline:
            cycle += 1
            remaining = (deadline - time.time()) / 60
            logger.info("=== Cycle %d — %.1f min remaining ===", cycle, remaining)
            tester.run()
            if time.time() >= deadline:
                break
            logger.info("Cycle %d complete. Starting next cycle immediately.", cycle)
        logger.info("Duration %.1f min elapsed — done after %d cycle(s).", args.duration, cycle)
    else:
        tester.run()

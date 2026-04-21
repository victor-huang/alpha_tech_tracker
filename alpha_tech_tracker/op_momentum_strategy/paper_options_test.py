"""
paper_options_test.py

Probes what a paper/sim broker account can and cannot do with options:
  1. Look up option contracts  (get_options_contracts — trading client)
  2. Fetch option quotes       (get_option_quotes_by_occ_batch — data client)
  3. Place a BUY_OPEN order    (place_option_order — trading client)
  4. Place a SELL_CLOSE order  (place_option_order — trading client)

Each step is attempted independently so partial failures are visible.

Usage:
    source ~/.pyenv/versions/alpha_tech_tracker/bin/activate
    export PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker

    # Alpaca paper account (default)
    python -m alpha_tech_tracker.op_momentum_strategy.paper_options_test --ticker AMD

    # Alpaca live account
    python -m alpha_tech_tracker.op_momentum_strategy.paper_options_test --ticker AMD --live

    # TradeStation sim account
    python -m alpha_tech_tracker.op_momentum_strategy.paper_options_test --ticker AMD --broker tradestation

    # TradeStation live account
    python -m alpha_tech_tracker.op_momentum_strategy.paper_options_test --ticker AMD --broker tradestation --live
"""

import argparse
import logging
import time

from alpha_tech_tracker.trade_api.alpaca_client.client import AlpacaAPIClient
from .config import (
    _TRADESTATION_SESSION_TOKENS,
    _load_config,
    TRADESTATION_ACCOUNT_KEY,
)
from .contract_selector import TimePremiumContractSelector
from .order_executor import _place_with_fill_escalation

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

_SEPARATOR = "-" * 60


def _step(label):
    print(f"\n{_SEPARATOR}")
    print(f"  {label}")
    print(_SEPARATOR)


def _ok(msg):
    print(f"  [OK]  {msg}")


def _fail(msg):
    print(f"  [FAIL] {msg}")


def _build_client(broker: str, is_live: bool):
    if broker == "tradestation":
        from alpha_tech_tracker.trade_api.tradestation.client import TradeStationAPIClient
        env = "live" if is_live else "sim"
        client = TradeStationAPIClient(
            selected_account_key=TRADESTATION_ACCOUNT_KEY or None,
            environment=env,
        )
        if _TRADESTATION_SESSION_TOKENS.get("access_token"):
            client.restore_session(_TRADESTATION_SESSION_TOKENS)
            if client.verify_session():
                logger.info("TradeStation session restored from stored tokens")
                return client
            logger.warning("Stored TradeStation session expired — re-authorizing")
        client.authorize_session()
        return client

    return AlpacaAPIClient(is_paper_trading=not is_live)


def _build_occ_symbol(ticker: str, strike: int, expiry: str, option_type: str = "C") -> str:
    """Build an OCC symbol from components.

    expiry: YYYY-MM-DD
    Returns e.g. 'TSLA260417C00380000'
    """
    from datetime import datetime
    dt = datetime.strptime(expiry, "%Y-%m-%d")
    return f"{ticker}{dt.strftime('%y%m%d')}{option_type}{strike * 1000:08d}"


def run_test(ticker: str, broker: str, is_live: bool, strike: int = None, expiry: str = None, option_type: str = "call", quote_only: bool = False, price_type: str = "MARKET", limit_price: float = None, use_fair_price: bool = False, penny_pilot: bool = True, escalate: bool = False):
    account_type = "LIVE" if is_live else ("SIM" if broker == "tradestation" else "PAPER")
    print(f"\n{'='*60}")
    print(f"  Options capability test — ticker={ticker}  broker={broker.upper()}  account={account_type}")
    print(f"{'='*60}")

    client = _build_client(broker, is_live)

    # ------------------------------------------------------------------
    # Step 1: get current stock quote
    # ------------------------------------------------------------------
    _step("Step 1: fetch stock quote")
    try:
        if broker == "alpaca":
            from alpaca.data.enums import DataFeed
            raw = client.get_stock_quote(ticker, feed=DataFeed.IEX)
        else:
            raw = client.get_stock_quote(ticker)
        from .models import _stock_bid_ask
        bid, ask = _stock_bid_ask(raw)
        stock_mid = (bid + ask) / 2
        _ok(f"stock quote: bid={bid:.2f} ask={ask:.2f} mid={stock_mid:.2f}")
    except Exception as e:
        _fail(f"stock quote failed: {e}")
        print("  Cannot continue without stock price — aborting.")
        return

    # ------------------------------------------------------------------
    # Step 2: resolve OCC symbol
    # ------------------------------------------------------------------
    _step("Step 2: resolve option contract")
    occ_symbol = None
    if strike is not None and expiry is not None:
        cp = "P" if option_type.lower() == "put" else "C"
        occ_symbol = _build_occ_symbol(ticker, strike, expiry, option_type=cp)
        _ok(f"manual OCC symbol: {occ_symbol}")
    else:
        try:
            selector = TimePremiumContractSelector(client)
            occ_symbol = selector.select(ticker, "BULLISH", stock_mid)
            _ok(f"auto-selected contract: {occ_symbol}")
        except Exception as e:
            _fail(f"contract lookup failed: {e}")
            # Last-resort: nearest $5 strike at next Friday
            try:
                from datetime import date
                from .contract_selector import _next_friday
                friday = _next_friday(date.today())
                fallback_strike = int(round(stock_mid / 5) * 5)
                occ_symbol = _build_occ_symbol(ticker, fallback_strike, friday.strftime("%Y-%m-%d"))
                logger.info("Trying fallback OCC symbol: %s", occ_symbol)
                _ok(f"fallback OCC symbol: {occ_symbol}")
            except Exception as e2:
                _fail(f"fallback OCC build failed: {e2}")

    # ------------------------------------------------------------------
    # Step 3: fetch option quote
    # ------------------------------------------------------------------
    _step("Step 3: get_option_quotes_by_occ_batch")
    last_bid, last_ask, last_mid = 0.0, 0.0, 0.0
    if not occ_symbol:
        print("  Skipped (no OCC symbol resolved)")
    else:
        try:
            quotes = client.get_option_quotes_by_occ_batch([occ_symbol])
            q = quotes.get(occ_symbol, {})
            last_bid, last_ask, last_mid = q.get("bid", 0), q.get("ask", 0), q.get("mid", 0)
            _ok(f"option quote: bid={last_bid:.2f}  ask={last_ask:.2f}  mid={last_mid:.2f}")
            if use_fair_price and last_mid > 0:
                try:
                    from decimal import Decimal
                    import re as _re
                    from .option_price_monitor import OptionPriceMonitor
                    monitor = OptionPriceMonitor(client, [ticker])
                    option_type = "call" if _re.search(r"\d{6}C", occ_symbol) else "put"
                    fair = monitor.get_fair_price(ticker, occ_symbol, option_type, Decimal(str(stock_mid)))
                    print(f"  fair price: {float(fair):.2f}")
                except Exception as e:
                    print(f"  fair price error: {e}")
            if last_bid == 0 and last_ask == 0:
                print("  [DEBUG] Zero quote — fetching raw API response for diagnosis...")
                try:
                    from alpha_tech_tracker.trade_api.tradestation.client import _occ_to_ts
                    ts_sym = _occ_to_ts(occ_symbol)
                    raw_data = client._get(f"/data/quote/{ts_sym}")
                    print(f"  [DEBUG] raw API response: {raw_data}")
                except Exception as de:
                    print(f"  [DEBUG] raw fetch error: {de}")
        except Exception as e:
            _fail(f"option quote fetch failed: {e}")

    if quote_only:
        print(f"\n{'='*60}\n  Quote-only mode — skipping order placement.\n{'='*60}\n")
        return

    # ------------------------------------------------------------------
    # Step 4: place BUY_OPEN
    # ------------------------------------------------------------------
    _step("Step 4: place BUY_OPEN option order")
    if occ_symbol is None:
        print("  Skipped (no OCC symbol available)")
        return

    order_id = None
    fill_price = None

    if escalate:
        import re as _re
        _otype = "call" if _re.search(r"\d{6}C", occ_symbol) else "put"

        get_fair_price_fn = None
        if use_fair_price:
            from decimal import Decimal
            from .option_price_monitor import OptionPriceMonitor
            monitor = OptionPriceMonitor(client, [ticker])
            def get_fair_price_fn():
                return monitor.get_fair_price(
                    ticker, occ_symbol, _otype,
                    Decimal(str(stock_mid)),
                    penny_pilot=penny_pilot,
                )

        try:
            print(f"  Using fill escalation (BUY_OPEN) — penny_pilot={penny_pilot}")
            order = _place_with_fill_escalation(
                client=client,
                ticker=ticker,
                option_symbol=occ_symbol,
                option_type=_otype,
                contracts=1,
                order_action="BUY_OPEN",
                get_fair_price_fn=get_fair_price_fn,
                penny_pilot=penny_pilot,
            )
            order_id = order.get("order_id")
            _ok(f"BUY_OPEN escalation done: order_id={order_id} status={order.get('status')}")
            fp = order.get("filled_avg_price") or client.order_status(order_id).get("filled_avg_price")
            if fp:
                fill_price = fp
                print(f"  Fill price: {fill_price:.2f}")
        except Exception as e:
            _fail(f"BUY_OPEN escalation failed: {e}")
            return
    else:
        buy_price = limit_price
        if price_type.upper() == "LIMIT" and buy_price is None:
            if use_fair_price:
                try:
                    from decimal import Decimal
                    import re as _re
                    from .option_price_monitor import OptionPriceMonitor
                    monitor = OptionPriceMonitor(client, [ticker])
                    _otype = "call" if _re.search(r"\d{6}C", occ_symbol) else "put"
                    fair = monitor.get_fair_price(ticker, occ_symbol, _otype, Decimal(str(stock_mid)))
                    buy_price = float(fair)
                    print(f"  Using fair price as limit: {buy_price:.2f}  (bid={last_bid:.2f} ask={last_ask:.2f} mid={last_mid:.2f})")
                except Exception as e:
                    _fail(f"get_fair_price failed: {e} — falling back to mid")
                    buy_price = round(last_mid, 2)
            else:
                buy_price = round(last_mid, 2)
                print(f"  Using mid price as limit: {buy_price:.2f}")

        try:
            order = client.place_option_order(
                symbol=ticker,
                price_type=price_type,
                price=buy_price,
                order_action="BUY_OPEN",
                quantity=1,
                _option_symbol_override=occ_symbol,
            )
            order_id = order.get("order_id")
            price_desc = f"limit={buy_price:.2f}" if price_type.upper() == "LIMIT" else "market"
            _ok(f"BUY_OPEN placed: order_id={order_id} status={order.get('status')} ({price_desc})")
        except Exception as e:
            _fail(f"BUY_OPEN failed: {e}")
            return

    # ------------------------------------------------------------------
    # Step 5: place SELL_CLOSE
    # ------------------------------------------------------------------
    _step("Step 5: place SELL_CLOSE option order")

    if escalate:
        import re as _re
        _otype = "call" if _re.search(r"\d{6}C", occ_symbol) else "put"

        if fill_price is None and order_id:
            for attempt in range(10):
                time.sleep(1)
                try:
                    status = client.order_status(order_id)
                    fp = status.get("filled_avg_price")
                    if fp:
                        fill_price = fp
                        print(f"  Buy filled at {fill_price:.2f} after {attempt + 1}s")
                        break
                    print(f"  [{attempt + 1}s] buy status={status['status']} — waiting...", flush=True)
                except Exception as e:
                    print(f"  Could not check order status: {e}", flush=True)
                    break

        try:
            print(f"  Using fill escalation (SELL_CLOSE) — entry_fill_price={fill_price} penny_pilot={penny_pilot}")
            order = _place_with_fill_escalation(
                client=client,
                ticker=ticker,
                option_symbol=occ_symbol,
                option_type=_otype,
                contracts=1,
                order_action="SELL_CLOSE",
                entry_fill_price=fill_price,
                penny_pilot=penny_pilot,
            )
            _ok(f"SELL_CLOSE escalation done: order_id={order.get('order_id')} status={order.get('status')}")
        except Exception as e:
            _fail(f"SELL_CLOSE escalation failed: {e}")
            if order_id:
                print(f"  WARNING: open position may remain for {occ_symbol} — close manually!")
    else:
        sell_price = buy_price
        sell_price_type = price_type

        if order_id and not fill_price:
            for attempt in range(10):
                time.sleep(1)
                try:
                    status = client.order_status(order_id)
                    fp = status.get("filled_avg_price")
                    if fp:
                        fill_price = fp
                        print(f"  Buy filled at {fill_price:.2f} after {attempt + 1}s")
                        break
                    print(f"  [{attempt + 1}s] buy status={status['status']} — waiting for fill...", flush=True)
                except Exception as e:
                    print(f"  Could not check order status: {e}", flush=True)
                    break

        if fill_price:
            from decimal import Decimal
            from .option_price_monitor import _quantize_option_price
            sell_price = float(_quantize_option_price(Decimal(str(fill_price)), penny_pilot=penny_pilot))
            sell_price_type = "LIMIT"
        elif price_type.upper() == "LIMIT" and buy_price:
            print(f"  Buy unfilled after 10s — selling at original limit {buy_price:.2f}")
        else:
            print("  Buy unfilled after 10s — selling at market")

        try:
            order = client.place_option_order(
                symbol=ticker,
                price_type=sell_price_type,
                price=sell_price,
                order_action="SELL_CLOSE",
                quantity=1,
                _option_symbol_override=occ_symbol,
            )
            price_desc = f"limit={sell_price:.2f}" if sell_price_type.upper() == "LIMIT" else "market"
            _ok(f"SELL_CLOSE placed: order_id={order.get('order_id')} status={order.get('status')} ({price_desc})")
        except Exception as e:
            _fail(f"SELL_CLOSE failed: {e}")
            if order_id:
                print(f"  WARNING: open position may remain for {occ_symbol} — close manually!")

    print(f"\n{'='*60}\n  Test complete.\n{'='*60}\n")


def _parse_args():
    parser = argparse.ArgumentParser(description="Test broker options capabilities")
    parser.add_argument("--ticker", default="AMD", help="Ticker to test (default: AMD)")
    parser.add_argument(
        "--broker",
        default="alpaca",
        choices=["alpaca", "tradestation"],
        help="Broker to use: alpaca (default) or tradestation",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        default=False,
        help="Use live account; default is paper (Alpaca) or sim (TradeStation)",
    )
    parser.add_argument(
        "--strike",
        type=int,
        default=None,
        help="Strike price for manual OCC symbol (e.g. 380); requires --expiry",
    )
    parser.add_argument(
        "--option-type",
        default="call",
        choices=["call", "put"],
        help="Option type: call (default) or put",
    )
    parser.add_argument(
        "--expiry",
        default=None,
        help="Expiry date YYYY-MM-DD for manual OCC symbol; requires --strike",
    )
    parser.add_argument(
        "--quote-only",
        action="store_true",
        default=False,
        help="Fetch quotes only; skip order placement steps",
    )
    parser.add_argument(
        "--price-type",
        default="MARKET",
        choices=["MARKET", "LIMIT"],
        help="Order price type for BUY_OPEN (default: MARKET)",
    )
    parser.add_argument(
        "--limit-price",
        type=float,
        default=None,
        help="Explicit limit price for LIMIT orders; omit to auto-use mid from last quote",
    )
    parser.add_argument(
        "--fair-price",
        action="store_true",
        default=False,
        help="Use get_fair_price() instead of raw mid for LIMIT buy (intrinsic floor + time-premium cache)",
    )
    parser.add_argument(
        "--non-penny-pilot",
        action="store_true",
        default=False,
        help="Use standard (non-Penny Pilot) tick increments: $0.05 < $3, $0.10 >= $3",
    )
    parser.add_argument(
        "--escalate",
        action="store_true",
        default=False,
        help=(
            "Use _place_with_fill_escalation for BUY and SELL. "
            "Tries limit at entry/fair/mid/mid±spread/ask across 4 steps (20s/20s/15s/15s). "
            "Ignores --price-type when set."
        ),
    )
    return parser.parse_args()


if __name__ == "__main__":
    _load_config()
    args = _parse_args()
    run_test(
        ticker=args.ticker.upper(),
        broker=args.broker,
        is_live=args.live,
        strike=args.strike,
        expiry=args.expiry,
        option_type=args.option_type,
        quote_only=args.quote_only,
        price_type=args.price_type,
        limit_price=args.limit_price,
        use_fair_price=args.fair_price,
        penny_pilot=not args.non_penny_pilot,
        escalate=args.escalate,
    )

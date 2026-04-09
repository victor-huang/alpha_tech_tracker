import logging
import time
from decimal import ROUND_HALF_UP
from typing import Optional

from alpha_tech_tracker.trade_api.execution_client import ExecutionClient

from .models import _D, _stock_bid_ask
from .option_price_monitor import _quantize_option_price

logger = logging.getLogger(__name__)


def _place_with_fill_escalation(
    client: ExecutionClient,
    ticker: str,
    option_symbol: str,
    option_type: str,
    contracts: int,
    order_action: str,
    entry_fill_price: Optional[float] = None,
) -> dict:
    """
    Place a limit order at mid price, then escalate if unfilled:
      - After 60s unfilled: cancel + re-place at ask (buy) or bid (sell)
      - After another 60s unfilled: cancel + market order

    When entry_fill_price is provided (quick-exit scenario: position held < 10 min),
    an extra step 0 is prepended: try a limit at entry_fill_price for 60s first.
    If unfilled, the normal mid → ask/bid → market escalation follows.
    This protects against selling at a loss when the position was just opened and
    the market hasn't had time to reflect the entry price.
    """
    is_buy = order_action == "BUY_OPEN"

    def _fetch_mid_bid_ask():
        q = client.get_option_quote_by_occ(option_symbol)
        bid = _D(str(q["bid"]))
        ask = _D(str(q["ask"]))
        mid = _D(str(q["mid"]))
        return bid, ask, mid

    def _place_limit(price) -> dict:
        rounded = _quantize_option_price(price)
        return client.place_option_order(
            symbol=ticker,
            option_key=None,
            price=float(rounded),
            price_type="LIMIT",
            option_type=option_type,
            order_action=order_action,
            quantity=contracts,
            _option_symbol_override=option_symbol,
        )

    def _place_market() -> dict:
        return client.place_option_order(
            symbol=ticker,
            option_key=None,
            price_type="MARKET",
            option_type=option_type,
            order_action=order_action,
            quantity=contracts,
            _option_symbol_override=option_symbol,
        )

    def _is_filled(order_id: str) -> bool:
        try:
            status = client.order_status(order_id)
            return status.get("status") == "filled"
        except Exception:
            return False

    def _cancel_safely(order_id: str):
        try:
            client.cancel_order(order_id)
        except Exception:
            logger.warning(
                "Could not cancel order %s (may already be filled)", order_id
            )

    if entry_fill_price is not None:
        step0_price = _D(str(entry_fill_price))
        logger.info(
            "FILL_ESC step0 %s %s: quick-exit, trying entry_fill_price=%s",
            order_action,
            option_symbol,
            step0_price.quantize(_D("0.01"), rounding=ROUND_HALF_UP),
        )
        order = _place_limit(step0_price)
        order_id = order.get("order_id")
        logger.info("FILL_ESC step0 order placed: id=%s", order_id)
        time.sleep(60)
        if _is_filled(order_id):
            logger.info("FILL_ESC step0 filled at entry price: %s", order_id)
            return order
        _cancel_safely(order_id)
        logger.info("FILL_ESC step0 unfilled, escalating to normal flow: %s", option_symbol)

    try:
        bid, ask, mid = _fetch_mid_bid_ask()
        logger.info(
            "FILL_ESC step1 %s %s: bid=%s ask=%s mid=%s",
            order_action,
            option_symbol,
            bid,
            ask,
            mid.quantize(_D("0.01"), rounding=ROUND_HALF_UP),
        )
    except Exception:
        logger.warning(
            "Could not fetch quote for %s, falling back to market", option_symbol
        )
        return _place_market()

    order = _place_limit(mid)
    order_id = order.get("order_id")
    logger.info("FILL_ESC step1 order placed: id=%s", order_id)

    time.sleep(60)
    if _is_filled(order_id):
        logger.info("FILL_ESC step1 filled: %s", order_id)
        return order

    _cancel_safely(order_id)
    try:
        bid, ask, mid = _fetch_mid_bid_ask()
        aggressive_price = ask if is_buy else bid
        logger.info(
            "FILL_ESC step2 %s %s: aggressive_price=%s",
            order_action,
            option_symbol,
            aggressive_price.quantize(_D("0.01"), rounding=ROUND_HALF_UP),
        )
    except Exception:
        logger.warning(
            "Could not fetch quote for step2 %s, using market", option_symbol
        )
        return _place_market()

    order = _place_limit(aggressive_price)
    order_id = order.get("order_id")
    logger.info("FILL_ESC step2 order placed: id=%s", order_id)

    time.sleep(60)
    if _is_filled(order_id):
        logger.info("FILL_ESC step2 filled: %s", order_id)
        return order

    _cancel_safely(order_id)
    logger.info(
        "FILL_ESC step3 %s %s: placing market order", order_action, option_symbol
    )
    order = _place_market()
    logger.info("FILL_ESC step3 market order placed: id=%s", order.get("order_id"))
    return order


def place_stock_order(
    client: ExecutionClient,
    ticker: str,
    shares: int,
    order_action: str,
    mock: bool = False,
) -> dict:
    """
    Place a stock buy or sell order with the same 3-step fill escalation as options:
      Step 1 (0-60s):   limit order at mid price
      Step 2 (60-120s): cancel unfilled -> re-place at ask (buy) or bid (sell)
      Step 3 (120s+):   cancel unfilled -> market order
    order_action: "BUY_OPEN" or "SELL_CLOSE"
    Returns: {order_id, status, filled_qty, filled_avg_price}
    """
    is_buy = order_action == "BUY_OPEN"

    side = "BUY" if is_buy else "SELL"

    def _fetch_mid_bid_ask():
        raw_quote = client.get_stock_quote(ticker)
        bid_f, ask_f = _stock_bid_ask(raw_quote)
        bid = _D(str(bid_f))
        ask = _D(str(ask_f))
        mid = (bid + ask) / _D("2")
        return bid, ask, mid

    def _place_limit(price) -> dict:
        rounded = float(price.quantize(_D("0.01"), rounding=ROUND_HALF_UP))
        return client.place_stock_order(
            symbol=ticker,
            quantity=shares,
            side=side,
            order_type="LIMIT",
            limit_price=rounded,
        )

    def _place_market() -> dict:
        return client.place_stock_order(
            symbol=ticker,
            quantity=shares,
            side=side,
            order_type="MARKET",
        )

    def _is_filled(order_id: str) -> bool:
        try:
            status = client.order_status(order_id)
            return status.get("status") == "filled"
        except Exception:
            return False

    def _cancel_safely(order_id: str):
        try:
            client.cancel_order(order_id)
        except Exception:
            logger.warning(
                "Could not cancel order %s (may already be filled)", order_id
            )

    try:
        bid, ask, mid = _fetch_mid_bid_ask()
        logger.info(
            "STOCK FILL_ESC step1 %s %s: bid=%s ask=%s mid=%s",
            order_action,
            ticker,
            bid,
            ask,
            mid.quantize(_D("0.01"), rounding=ROUND_HALF_UP),
        )
    except Exception:
        logger.warning("Could not fetch stock quote for %s, falling back to market", ticker)
        return _place_market()

    order = _place_limit(mid)
    order_id = order.get("order_id")
    logger.info("STOCK FILL_ESC step1 order placed: id=%s", order_id)

    time.sleep(60)
    if _is_filled(order_id):
        logger.info("STOCK FILL_ESC step1 filled: %s", order_id)
        return order

    _cancel_safely(order_id)
    try:
        bid, ask, mid = _fetch_mid_bid_ask()
        aggressive_price = ask if is_buy else bid
        logger.info(
            "STOCK FILL_ESC step2 %s %s: aggressive_price=%s",
            order_action,
            ticker,
            aggressive_price.quantize(_D("0.01"), rounding=ROUND_HALF_UP),
        )
    except Exception:
        logger.warning("Could not fetch stock quote for step2 %s, using market", ticker)
        return _place_market()

    order = _place_limit(aggressive_price)
    order_id = order.get("order_id")
    logger.info("STOCK FILL_ESC step2 order placed: id=%s", order_id)

    time.sleep(60)
    if _is_filled(order_id):
        logger.info("STOCK FILL_ESC step2 filled: %s", order_id)
        return order

    _cancel_safely(order_id)
    logger.info("STOCK FILL_ESC step3 %s %s: placing market order", order_action, ticker)
    order = _place_market()
    logger.info("STOCK FILL_ESC step3 market order placed: id=%s", order.get("order_id"))
    return order

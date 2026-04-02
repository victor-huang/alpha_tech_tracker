import logging
import time
from decimal import ROUND_HALF_UP

from alpaca.data.requests import OptionLatestQuoteRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.trading.requests import LimitOrderRequest, MarketOrderRequest

from alpha_tech_tracker.trade_api.alpaca_client.client import (
    AlpacaAPIClient,
    APIInvalidArgumentError,
)

from .models import _D

logger = logging.getLogger(__name__)


def _place_with_fill_escalation(
    client: AlpacaAPIClient,
    ticker: str,
    option_symbol: str,
    option_type: str,
    contracts: int,
    order_action: str,
) -> dict:
    """
    Place a limit order at mid price, then escalate if unfilled:
      - After 60s unfilled: cancel + re-place at ask (buy) or bid (sell)
      - After another 60s unfilled: cancel + market order
    """
    is_buy = order_action == "BUY_OPEN"

    def _fetch_mid_bid_ask():
        quote_resp = client._option_data_client.get_option_latest_quote(
            OptionLatestQuoteRequest(symbol_or_symbols=[option_symbol])
        )
        q = quote_resp[option_symbol]
        bid = _D(q.bid_price)
        ask = _D(q.ask_price)
        mid = (bid + ask) / _D("2")
        return bid, ask, mid

    def _place_limit(price) -> dict:
        rounded = price.quantize(_D("0.01"), rounding=ROUND_HALF_UP)
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


# ---------------------------------------------------------------------------
# Patch AlpacaAPIClient.place_option_order to accept _option_symbol_override
# ---------------------------------------------------------------------------

_original_place_option_order = AlpacaAPIClient.place_option_order


def _patched_place_option_order(
    self,
    symbol,
    option_key=None,
    price=None,
    order_id=None,
    preview_order=None,
    price_type="LIMIT",
    option_type="CALL",
    order_action="BUY_OPEN",
    quantity=1,
    _option_symbol_override=None,
):
    """Extends place_option_order to accept a pre-built OCC symbol directly."""
    if _option_symbol_override:
        option_symbol = _option_symbol_override
    else:
        option_symbol = self._build_option_symbol(symbol, option_key, option_type)

    side_mapping = {
        "BUY_OPEN": "BUY",
        "BUY_CLOSE": "BUY",
        "SELL_OPEN": "SELL",
        "SELL_CLOSE": "SELL",
    }
    side = side_mapping.get(order_action, "BUY")

    if price_type.upper() == "SMART_MARKET":
        quote = self.get_option_quote(symbol, option_key, option_type=option_type)
        price_info = self.get_price_from_quote(quote)
        price = price_info["s-mid"]
        price_type = "LIMIT"

    order_side = OrderSide.BUY if side == "BUY" else OrderSide.SELL

    if price_type.upper() == "MARKET":
        order_data = MarketOrderRequest(
            symbol=option_symbol,
            qty=quantity,
            side=order_side,
            time_in_force=TimeInForce.DAY,
        )
    elif price_type.upper() == "LIMIT":
        if price is None:
            raise APIInvalidArgumentError(
                code="MISSING_LIMIT_PRICE",
                message="price is required for LIMIT orders",
            )
        order_data = LimitOrderRequest(
            symbol=option_symbol,
            qty=quantity,
            side=order_side,
            time_in_force=TimeInForce.DAY,
            limit_price=float(price),
        )
    else:
        raise APIInvalidArgumentError(
            code="INVALID_PRICE_TYPE",
            message=f"Unsupported price type: {price_type}",
        )

    order = self._trading_client.submit_order(order_data=order_data)
    return {
        "order_id": order.id,
        "client_order_id": order.client_order_id,
        "symbol": order.symbol,
        "quantity": float(order.qty),
        "filled_qty": float(order.filled_qty) if order.filled_qty else 0,
        "side": order.side.value,
        "type": order.type.value,
        "status": order.status.value,
        "limit_price": float(order.limit_price) if order.limit_price else None,
        "filled_avg_price": (
            float(order.filled_avg_price) if order.filled_avg_price else None
        ),
        "submitted_at": order.submitted_at,
        "raw_response": order,
    }


AlpacaAPIClient.place_option_order = _patched_place_option_order


def place_stock_order(
    client: AlpacaAPIClient,
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

    def _fetch_mid_bid_ask():
        quote = client.get_stock_quote(ticker)
        bid = _D(str(quote.get("bid_price") or quote.get("last_price", 0)))
        ask = _D(str(quote.get("ask_price") or quote.get("last_price", 0)))
        mid = (bid + ask) / _D("2")
        return bid, ask, mid

    def _place_limit(price) -> dict:
        rounded = price.quantize(_D("0.01"), rounding=ROUND_HALF_UP)
        return client.place_stock_order(
            symbol=ticker,
            price=float(rounded),
            price_type="LIMIT",
            order_action=order_action,
            quantity=shares,
        )

    def _place_market() -> dict:
        return client.place_stock_order(
            symbol=ticker,
            price_type="MARKET",
            order_action=order_action,
            quantity=shares,
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

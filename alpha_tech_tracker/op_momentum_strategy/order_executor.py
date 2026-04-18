import logging
import time
from decimal import ROUND_HALF_UP
from typing import Optional

from alpha_tech_tracker.trade_api.execution_client import ExecutionClient

from .models import _D, _stock_bid_ask
from .option_price_monitor import _parse_occ_symbol, _quantize_option_price

logger = logging.getLogger(__name__)


def _place_with_fill_escalation(
    client: ExecutionClient,
    ticker: str,
    option_symbol: str,
    option_type: str,
    contracts: int,
    order_action: str,
    entry_fill_price: Optional[float] = None,
    get_fair_price_fn=None,
    feed=None,
    penny_pilot: bool = True,
) -> dict:
    """
    Place a limit order and escalate if unfilled.

    Escalation ladder:
      Step 0   (20s, quick-exit only): limit at entry_fill_price — protects against
        selling at a loss when the position was just opened.
      Step 0.5 (20s, when get_fair_price_fn is provided): limit at fair price from
        OptionPriceMonitor. Skipped if no fn or fn returns None.
      Step 1   (15s): limit at mid.
      Step 2   (15s): limit at mid + (ask-bid)/4 [buy] or mid - (ask-bid)/4 [sell].
        For sells, a live stock quote is fetched to compute intrinsic value; if the
        computed step2_price falls below intrinsic it is floored at intrinsic.
      Step 3   (15s buy / 60s sell, final): limit at ask [buy] or max(bid, intrinsic)
        [sell]. After 60s unfilled on a sell, cancels and places a market order to
        ensure the position is closed. Buys log a FILL_ESC MISS warning if unfilled.

    get_fair_price_fn: optional zero-argument callable that returns a Decimal
      fair price for the option. Called fresh at each step to get the latest value.
    """
    is_buy = order_action == "BUY_OPEN"

    def _fetch_mid_bid_ask():
        q = client.get_option_quote_by_occ(option_symbol)
        bid = _D(str(q["bid"]))
        ask = _D(str(q["ask"]))
        mid = _D(str(q["mid"]))
        return bid, ask, mid

    def _place_limit(price) -> dict:
        rounded = _quantize_option_price(price, penny_pilot=penny_pilot)
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

    def _place_market() -> dict:
        return client.place_option_order(
            symbol=ticker,
            option_key=None,
            price=None,
            price_type="MARKET",
            option_type=option_type,
            order_action=order_action,
            quantity=contracts,
            _option_symbol_override=option_symbol,
        )

    def _get_fair_price():
        if get_fair_price_fn is None:
            return None
        try:
            return get_fair_price_fn()
        except Exception:
            logger.warning("get_fair_price_fn failed for %s", option_symbol)
            return None

    # --- Step 0: quick-exit entry-price protection ---
    if entry_fill_price is not None:
        step0_price = _D(str(entry_fill_price))
        logger.info(
            "FILL_ESC step0 %s %s: quick-exit, trying entry_fill_price=%s",
            order_action, option_symbol,
            step0_price.quantize(_D("0.01"), rounding=ROUND_HALF_UP),
        )
        order = _place_limit(step0_price)
        order_id = order.get("order_id")
        logger.info("FILL_ESC step0 order placed: id=%s", order_id)
        time.sleep(20)
        if _is_filled(order_id):
            logger.info("FILL_ESC step0 filled at entry price: %s", order_id)
            return order
        _cancel_safely(order_id)
        logger.info("FILL_ESC step0 unfilled, escalating: %s", option_symbol)

    # --- Step 0.5: limit at fair price (when monitor is active) ---
    fair = _get_fair_price()
    if fair is not None:
        logger.info(
            "FILL_ESC step0.5 %s %s: limit at fair_price=%s",
            order_action, option_symbol,
            fair.quantize(_D("0.01"), rounding=ROUND_HALF_UP),
        )
        order = _place_limit(fair)
        order_id = order.get("order_id")
        logger.info("FILL_ESC step0.5 order placed: id=%s", order_id)
        time.sleep(20)
        if _is_filled(order_id):
            logger.info("FILL_ESC step0.5 filled at fair price: %s", order_id)
            return order
        _cancel_safely(order_id)
        logger.info("FILL_ESC step0.5 unfilled, escalating: %s", option_symbol)

    # --- Step 1: limit at mid ---
    try:
        bid, ask, mid = _fetch_mid_bid_ask()
    except Exception:
        logger.warning("Could not fetch quote for %s at step1, skipping to step3", option_symbol)
        bid, ask, mid = None, None, None

    if mid is not None:
        logger.info(
            "FILL_ESC step1 %s %s: bid=%s ask=%s mid=%s → limit at mid",
            order_action, option_symbol, bid, ask,
            mid.quantize(_D("0.01"), rounding=ROUND_HALF_UP),
        )
        order = _place_limit(mid)
        order_id = order.get("order_id")
        logger.info("FILL_ESC step1 order placed: id=%s", order_id)
        time.sleep(15)
        if _is_filled(order_id):
            logger.info("FILL_ESC step1 filled: %s", order_id)
            return order
        _cancel_safely(order_id)

    # --- Step 2: limit at mid ± (ask-bid)/4 ---
    try:
        bid, ask, mid = _fetch_mid_bid_ask()
        quarter_spread = (ask - bid) / _D("4")
        step2_price = (mid + quarter_spread) if is_buy else (mid - quarter_spread)
        logger.info(
            "FILL_ESC step2 %s %s: bid=%s ask=%s mid=%s spread/4=%s → limit at %s",
            order_action, option_symbol, bid, ask,
            mid.quantize(_D("0.01"), rounding=ROUND_HALF_UP),
            quarter_spread.quantize(_D("0.01"), rounding=ROUND_HALF_UP),
            step2_price.quantize(_D("0.01"), rounding=ROUND_HALF_UP),
        )
    except Exception:
        logger.warning("Could not fetch quote for %s at step2, skipping to step3", option_symbol)
        step2_price = None

    if not is_buy and step2_price is not None:
        try:
            kwargs = {"feed": feed} if feed is not None else {}
            raw_quote = client.get_stock_quote(ticker, **kwargs)
            bid_f, ask_f = _stock_bid_ask(raw_quote)
            stock_mid = (_D(str(bid_f)) + _D(str(ask_f))) / _D("2")
            parsed = _parse_occ_symbol(option_symbol)
            if parsed:
                strike = parsed["strike"]
                intrinsic = max(_D("0"), strike - stock_mid) if option_type.upper() == "PUT" \
                    else max(_D("0"), stock_mid - strike)
                if step2_price < intrinsic:
                    logger.warning(
                        "FILL_ESC step2 %s %s: step2_price=%s below intrinsic=%s — flooring at intrinsic",
                        order_action, option_symbol,
                        step2_price.quantize(_D("0.01"), rounding=ROUND_HALF_UP),
                        intrinsic.quantize(_D("0.01"), rounding=ROUND_HALF_UP),
                    )
                    step2_price = intrinsic
        except Exception:
            logger.warning("Could not compute intrinsic floor for %s at step2", option_symbol)

    if step2_price is not None:
        order = _place_limit(step2_price)
        order_id = order.get("order_id")
        logger.info("FILL_ESC step2 order placed: id=%s", order_id)
        time.sleep(15)
        if _is_filled(order_id):
            logger.info("FILL_ESC step2 filled: %s", order_id)
            return order
        _cancel_safely(order_id)

    # --- Step 3 (final): limit at ask (buy) or max(bid, intrinsic) (sell) ---
    try:
        bid, ask, _ = _fetch_mid_bid_ask()
        step3_price = ask if is_buy else bid
    except Exception:
        logger.warning("Could not fetch quote for %s at step3, using last known ask/bid", option_symbol)
        step3_price = ask if (ask is not None) else bid

    if not is_buy and step3_price is not None:
        try:
            kwargs = {"feed": feed} if feed is not None else {}
            raw_quote = client.get_stock_quote(ticker, **kwargs)
            bid_f, ask_f = _stock_bid_ask(raw_quote)
            stock_mid = (_D(str(bid_f)) + _D(str(ask_f))) / _D("2")
            parsed = _parse_occ_symbol(option_symbol)
            if parsed:
                strike = parsed["strike"]
                intrinsic = max(_D("0"), strike - stock_mid) if option_type.upper() == "PUT" \
                    else max(_D("0"), stock_mid - strike)
                if intrinsic > step3_price:
                    logger.warning(
                        "FILL_ESC step3 %s %s: bid=%s is below intrinsic=%s — flooring at intrinsic",
                        order_action, option_symbol,
                        step3_price.quantize(_D("0.01"), rounding=ROUND_HALF_UP),
                        intrinsic.quantize(_D("0.01"), rounding=ROUND_HALF_UP),
                    )
                    step3_price = intrinsic
        except Exception:
            logger.warning("Could not compute intrinsic floor for %s at step3", option_symbol)

    logger.info(
        "FILL_ESC step3 %s %s: final limit at %s",
        order_action, option_symbol,
        step3_price.quantize(_D("0.01"), rounding=ROUND_HALF_UP) if step3_price else "unknown",
    )
    order = _place_limit(step3_price)
    order_id = order.get("order_id")
    logger.info("FILL_ESC step3 order placed: id=%s", order_id)
    time.sleep(60 if not is_buy else 15)
    if _is_filled(order_id):
        logger.info("FILL_ESC step3 filled: %s", order_id)
        return order
    _cancel_safely(order_id)
    if not is_buy:
        logger.warning(
            "FILL_ESC step3 %s %s: limit unfilled after 60s — placing market order to close",
            order_action, option_symbol,
        )
        market_order = _place_market()
        logger.info("FILL_ESC market order placed: id=%s", market_order.get("order_id"))
        return market_order
    logger.warning(
        "FILL_ESC MISS %s %s: all steps exhausted, order %s cancelled — manual intervention may be required",
        order_action, option_symbol, order_id,
    )
    return order


def place_stock_order(
    client: ExecutionClient,
    ticker: str,
    shares: int,
    order_action: str,
    mock: bool = False,
    signal_price: Optional[float] = None,
    feed=None,
) -> dict:
    """
    Place a stock buy or sell order with 3-step fill escalation:
      Step 1 (0-10s):   limit at mid — quote fetched fresh before placing
      Step 2 (10-20s):  cancel unfilled -> re-fetch quote -> limit at ask (buy) or bid (sell)
      Step 3 (20s+):    cancel unfilled -> market order
    order_action: "BUY_OPEN", "SELL_CLOSE", "SELL_SHORT", or "BUY_COVER"
      BUY_OPEN   — buy to open a long position
      SELL_CLOSE — sell to close a long position
      SELL_SHORT — sell short to open a short position
      BUY_COVER  — buy to cover a short position
    signal_price: the stock price at signal time (from streaming bars); used as fallback
      mid when the broker quote has a spread > 3% (stale IEX snapshot).
    Returns: {order_id, status, filled_qty, filled_avg_price}
    """
    is_buy = order_action in ("BUY_OPEN", "BUY_COVER")

    side = "BUY" if is_buy else "SELL"

    _STALE_SPREAD_THRESHOLD = _D("0.03")

    def _fetch_mid_bid_ask():
        kwargs = {"feed": feed} if feed is not None else {}
        raw_quote = client.get_stock_quote(ticker, **kwargs)
        bid_f, ask_f = _stock_bid_ask(raw_quote)
        bid = _D(str(bid_f))
        ask = _D(str(ask_f))
        if is_buy and ask == _D("0"):
            raise ValueError(f"ask=0 for {ticker} — cannot compute limit price for buy")
        if not is_buy and bid == _D("0"):
            raise ValueError(f"bid=0 for {ticker} — cannot compute limit price for sell")
        mid = (bid + ask) / _D("2")
        spread_pct = (ask - bid) / mid
        if spread_pct > _STALE_SPREAD_THRESHOLD:
            if signal_price is None:
                raise ValueError(
                    f"stale quote for {ticker}: spread={float(spread_pct):.1%}"
                    " and no signal_price fallback — cannot compute limit price"
                )
            logger.warning(
                "Stale quote for %s: bid=%.2f ask=%.2f spread=%.1f%% "
                "— using signal_price=%.2f as mid",
                ticker, float(bid), float(ask), float(spread_pct * 100), signal_price,
            )
            anchor = _D(str(signal_price))
            return anchor - _D("0.05"), anchor + _D("0.05"), anchor
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

    for attempt in range(1, 4):
        try:
            bid, ask, mid = _fetch_mid_bid_ask()
            logger.info(
                "STOCK FILL_ESC step1 attempt=%d %s %s: bid=%s ask=%s mid=%s",
                attempt,
                order_action,
                ticker,
                bid,
                ask,
                mid.quantize(_D("0.01"), rounding=ROUND_HALF_UP),
            )
        except Exception:
            logger.warning(
                "Could not fetch stock quote for step1 attempt=%d %s, falling back to market",
                attempt, ticker, exc_info=True,
            )
            return _place_market()

        order = _place_limit(mid)
        order_id = order.get("order_id")
        logger.info("STOCK FILL_ESC step1 attempt=%d order placed: id=%s", attempt, order_id)

        time.sleep(5)
        if _is_filled(order_id):
            logger.info("STOCK FILL_ESC step1 attempt=%d filled: %s", attempt, order_id)
            return order

        _cancel_safely(order_id)
    for attempt in range(1, 4):
        try:
            bid, ask, mid = _fetch_mid_bid_ask()
            aggressive_price = ask if is_buy else bid
            logger.info(
                "STOCK FILL_ESC step2 attempt=%d %s %s: bid=%s ask=%s aggressive_price=%s",
                attempt,
                order_action,
                ticker,
                bid,
                ask,
                aggressive_price.quantize(_D("0.01"), rounding=ROUND_HALF_UP),
            )
        except Exception:
            logger.warning(
                "Could not fetch stock quote for step2 attempt=%d %s, using market",
                attempt, ticker, exc_info=True,
            )
            return _place_market()

        order = _place_limit(aggressive_price)
        order_id = order.get("order_id")
        logger.info("STOCK FILL_ESC step2 attempt=%d order placed: id=%s", attempt, order_id)

        time.sleep(10)
        if _is_filled(order_id):
            logger.info("STOCK FILL_ESC step2 attempt=%d filled: %s", attempt, order_id)
            return order

        _cancel_safely(order_id)

    logger.info("STOCK FILL_ESC step3 %s %s: placing market order", order_action, ticker)
    order = _place_market()
    logger.info("STOCK FILL_ESC step3 market order placed: id=%s", order.get("order_id"))
    return order

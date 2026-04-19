import logging
import re
import time
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional, Tuple

from alpha_tech_tracker.trade_api.execution_client import ExecutionClient

from .models import _D, _stock_bid_ask
from .option_price_monitor import _quantize_option_price

logger = logging.getLogger(__name__)


def _parse_tick_from_reject_reason(message: str) -> Optional[Decimal]:
    """Extract the required tick from a broker order-rejection message.

    Confirmed TradeStation format (from production RejectReason, 2026-04-17):
      "Price = 41.65000000 not rounded to a valid price increment [ 0.1 ]"

    Returns a Decimal tick if found, else None.
    """
    m = re.search(r"price increment\s*\[\s*([\d.]+)\s*\]", message, re.IGNORECASE)
    if m:
        try:
            return Decimal(m.group(1))
        except Exception:
            pass
    return None


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
      Steps 1-N (5s each, escalating loop): refreshes option quote and calls
        get_fair_price_fn at the start of each iteration.
        BUY: starts at min(fair_price, mid); increments by 0.25×half_spread while
          below mid, then 0.10×half_spread once above mid; caps at ask. Loop exits
          when ask is reached unfilled.
        SELL: starts at max(fair_price, mid); decrements by 0.25×half_spread while
          above mid, then 0.10×half_spread once below mid; floors at
          max(bid, fair_price). Loop exits when floor is reached unfilled.
        Falls through to step 3 if the option quote fetch fails.
      Step 3   (15s buy / 60s sell, final fallback): limit at ask [buy] or
        max(bid, fair_price) [sell]. After 60s unfilled on a sell, cancels and
        places a market order to ensure the position is closed. Buys log a
        FILL_ESC MISS warning if unfilled.

    get_fair_price_fn: optional zero-argument callable that returns a Decimal
      fair price for the option. Called fresh at each loop iteration; internally
      fetches a fresh stock quote and calls OptionPriceMonitor.get_fair_price().
    """
    is_buy = order_action == "BUY_OPEN"

    def _fetch_mid_bid_ask():
        q = client.get_option_quote_by_occ(option_symbol)
        bid = _D(str(q["bid"]))
        ask = _D(str(q["ask"]))
        mid = _D(str(q["mid"]))
        _last_known_quote[0] = bid
        _last_known_quote[1] = ask
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

    def _check_fill(order_id: str) -> Tuple[Optional[bool], Optional[str]]:
        """Return (is_filled, reject_reason). is_filled=None means unknown status."""
        try:
            status = client.order_status(order_id)
        except Exception:
            logger.warning(
                "order_status call failed for %s — fill status unknown, not cancelling",
                order_id,
            )
            return None, None
        if status.get("status") == "filled":
            return True, None
        return False, status.get("reject_reason")

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

    _last_known_quote = [None, None]  # [bid, ask] — updated after each successful fetch

    # --- Step 0: quick-exit entry-price protection ---
    if entry_fill_price is not None:
        step0_price = _D(str(entry_fill_price))
        logger.info(
            "FILL_ESC step0 %s %s: quick-exit, trying entry_fill_price=%s",
            order_action, option_symbol,
            step0_price.quantize(_D("0.01"), rounding=ROUND_HALF_UP),
        )
        try:
            order = _place_limit(step0_price)
        except Exception:
            logger.warning(
                "FILL_ESC step0 %s %s: placement failed, escalating",
                order_action, option_symbol, exc_info=True,
            )
        else:
            order_id = order.get("order_id")
            logger.info("FILL_ESC step0 order placed: id=%s", order_id)
            time.sleep(20)
            fill_status, _ = _check_fill(order_id)
            if fill_status:
                logger.info("FILL_ESC step0 filled at entry price: %s", order_id)
                return order
            if fill_status is None:
                logger.warning(
                    "FILL_ESC step0 %s %s: fill status unknown — not cancelling, returning order",
                    order_action, option_symbol,
                )
                return order
            _cancel_safely(order_id)
            logger.info("FILL_ESC step0 unfilled, escalating: %s", option_symbol)

    # --- Steps 1-N: escalating limit loop ---
    # Each iteration refreshes the option quote and calls get_fair_price_fn
    # (which internally fetches a fresh stock price).
    # BUY:  start=min(fair,mid), escalate toward ask.
    # SELL: start=max(fair,mid), descend toward max(bid,fair) floor.
    current_price = None
    step_num = 0

    while True:
        step_num += 1

        try:
            bid, ask, mid = _fetch_mid_bid_ask()
            half_spread = (ask - bid) / _D("2")
        except Exception:
            logger.warning(
                "FILL_ESC loop step%d %s %s: quote fetch failed, falling to step3",
                step_num, order_action, option_symbol, exc_info=True,
            )
            break

        fair = _get_fair_price()
        if fair is not None and fair <= _D("0"):
            fair = None

        if current_price is None:
            current_price = min(fair, mid) if (is_buy and fair is not None) \
                else (max(fair, mid) if (not is_buy and fair is not None) else mid)
        else:
            if is_buy:
                increment = _D("0.25") * half_spread if current_price < mid \
                    else _D("0.10") * half_spread
                current_price = min(current_price + increment, ask)
            else:
                sell_floor = max(bid, fair) if fair is not None else bid
                decrement = _D("0.25") * half_spread if current_price > mid \
                    else _D("0.10") * half_spread
                current_price = max(current_price - decrement, sell_floor)

        logger.info(
            "FILL_ESC loop step%d %s %s: bid=%s ask=%s mid=%s fair=%s → limit at %s",
            step_num, order_action, option_symbol,
            bid.quantize(_D("0.01"), rounding=ROUND_HALF_UP),
            ask.quantize(_D("0.01"), rounding=ROUND_HALF_UP),
            mid.quantize(_D("0.01"), rounding=ROUND_HALF_UP),
            fair.quantize(_D("0.01"), rounding=ROUND_HALF_UP) if fair is not None else "n/a",
            current_price.quantize(_D("0.01"), rounding=ROUND_HALF_UP),
        )

        try:
            order = _place_limit(current_price)
        except Exception:
            logger.warning(
                "FILL_ESC loop step%d %s %s: placement failed, escalating",
                step_num, order_action, option_symbol, exc_info=True,
            )
        else:
            order_id = order.get("order_id")
            logger.info("FILL_ESC loop step%d order placed: id=%s", step_num, order_id)
            time.sleep(5)
            fill_status, reject_reason = _check_fill(order_id)
            if fill_status:
                logger.info("FILL_ESC loop step%d filled: %s", step_num, order_id)
                return order
            if fill_status is None:
                logger.warning(
                    "FILL_ESC loop step%d %s %s: fill status unknown — not cancelling, returning order",
                    step_num, order_action, option_symbol,
                )
                return order
            tick = _parse_tick_from_reject_reason(reject_reason) \
                if isinstance(reject_reason, str) else None
            if tick is not None:
                adjusted = (current_price / tick).to_integral_value(rounding=ROUND_HALF_UP) * tick
                logger.warning(
                    "FILL_ESC loop step%d %s %s: tick rejection (required=%s),"
                    " adjusting %s → %s, retrying",
                    step_num, order_action, option_symbol, tick,
                    current_price.quantize(_D("0.01"), rounding=ROUND_HALF_UP),
                    adjusted.quantize(_D("0.01"), rounding=ROUND_HALF_UP),
                )
                current_price = adjusted
                try:
                    order = _place_limit(current_price)
                except Exception:
                    logger.warning(
                        "FILL_ESC loop step%d %s %s: tick-retry placement failed",
                        step_num, order_action, option_symbol, exc_info=True,
                    )
                else:
                    order_id = order.get("order_id")
                    logger.info(
                        "FILL_ESC loop step%d tick-retry order placed: id=%s", step_num, order_id
                    )
                    time.sleep(5)
                    fill_status, _ = _check_fill(order_id)
                    if fill_status:
                        logger.info(
                            "FILL_ESC loop step%d tick-retry filled: %s", step_num, order_id
                        )
                        return order
                    if fill_status is None:
                        logger.warning(
                            "FILL_ESC loop step%d %s %s: tick-retry fill status unknown"
                            " — not cancelling, returning order",
                            step_num, order_action, option_symbol,
                        )
                        return order
                    _cancel_safely(order_id)
            else:
                _cancel_safely(order_id)

        if is_buy and current_price >= ask:
            logger.warning(
                "FILL_ESC loop %s %s: reached ask price after step%d, escalating to step3",
                order_action, option_symbol, step_num,
            )
            break
        if not is_buy:
            sell_floor = max(bid, fair) if fair is not None else bid
            if current_price <= sell_floor:
                logger.warning(
                    "FILL_ESC loop %s %s: reached floor after step%d, escalating to step3",
                    order_action, option_symbol, step_num,
                )
                break

    # --- Step 3 (final): limit at ask (buy) or max(bid, fair_price) (sell) ---
    try:
        bid, ask, _ = _fetch_mid_bid_ask()
        step3_price = ask if is_buy else bid
    except Exception:
        logger.warning(
            "Could not fetch quote for %s at step3, using last known ask/bid",
            option_symbol, exc_info=True,
        )
        last_bid, last_ask = _last_known_quote
        step3_price = last_ask if is_buy else last_bid

    if not is_buy and step3_price is not None:
        fair = _get_fair_price()
        if fair is not None and fair > _D("0") and fair > step3_price:
            logger.warning(
                "FILL_ESC step3 %s %s: bid=%s is below fair_price=%s — flooring at fair_price",
                order_action, option_symbol,
                step3_price.quantize(_D("0.01"), rounding=ROUND_HALF_UP),
                fair.quantize(_D("0.01"), rounding=ROUND_HALF_UP),
            )
            step3_price = fair

    logger.info(
        "FILL_ESC step3 %s %s: final limit at %s",
        order_action, option_symbol,
        step3_price.quantize(_D("0.01"), rounding=ROUND_HALF_UP) if step3_price else "unknown",
    )
    try:
        order = _place_limit(step3_price)
    except Exception:
        logger.warning(
            "FILL_ESC step3 %s %s: limit placement failed",
            order_action, option_symbol, exc_info=True,
        )
        if not is_buy:
            logger.warning(
                "FILL_ESC step3 %s %s: falling back to market order after limit placement failure",
                order_action, option_symbol,
            )
            market_order = _place_market()
            logger.info("FILL_ESC market order placed: id=%s", market_order.get("order_id"))
            return market_order
        logger.warning(
            "FILL_ESC MISS %s %s: all steps exhausted — manual intervention may be required",
            order_action, option_symbol,
        )
        return {}
    order_id = order.get("order_id")
    logger.info("FILL_ESC step3 order placed: id=%s", order_id)
    time.sleep(60 if not is_buy else 15)
    fill_status, _ = _check_fill(order_id)
    if fill_status:
        logger.info("FILL_ESC step3 filled: %s", order_id)
        return order
    if fill_status is None:
        logger.warning(
            "FILL_ESC step3 %s %s: fill status unknown — not cancelling, returning order",
            order_action, option_symbol,
        )
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

    def _is_filled(order_id: str) -> Optional[bool]:
        try:
            status = client.order_status(order_id)
            return status.get("status") == "filled"
        except Exception:
            logger.warning(
                "order_status call failed for %s — fill status unknown, not cancelling",
                order_id,
            )
            return None

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

        try:
            order = _place_limit(mid)
        except Exception:
            logger.warning(
                "STOCK FILL_ESC step1 attempt=%d %s %s: placement failed, escalating",
                attempt, order_action, ticker, exc_info=True,
            )
            continue

        order_id = order.get("order_id")
        logger.info("STOCK FILL_ESC step1 attempt=%d order placed: id=%s", attempt, order_id)

        time.sleep(5)
        fill_status = _is_filled(order_id)
        if fill_status:
            logger.info("STOCK FILL_ESC step1 attempt=%d filled: %s", attempt, order_id)
            return order
        if fill_status is None:
            logger.warning(
                "STOCK FILL_ESC step1 attempt=%d %s %s: fill status unknown — not cancelling, returning order",
                attempt, order_action, ticker,
            )
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

        try:
            order = _place_limit(aggressive_price)
        except Exception:
            logger.warning(
                "STOCK FILL_ESC step2 attempt=%d %s %s: placement failed, escalating",
                attempt, order_action, ticker, exc_info=True,
            )
            continue

        order_id = order.get("order_id")
        logger.info("STOCK FILL_ESC step2 attempt=%d order placed: id=%s", attempt, order_id)

        time.sleep(10)
        fill_status = _is_filled(order_id)
        if fill_status:
            logger.info("STOCK FILL_ESC step2 attempt=%d filled: %s", attempt, order_id)
            return order
        if fill_status is None:
            logger.warning(
                "STOCK FILL_ESC step2 attempt=%d %s %s: fill status unknown — not cancelling, returning order",
                attempt, order_action, ticker,
            )
            return order
        _cancel_safely(order_id)

    logger.info("STOCK FILL_ESC step3 %s %s: placing market order", order_action, ticker)
    order = _place_market()
    logger.info("STOCK FILL_ESC step3 market order placed: id=%s", order.get("order_id"))
    return order

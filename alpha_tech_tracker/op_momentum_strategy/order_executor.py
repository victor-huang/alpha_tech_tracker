import logging
import re
import time
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional, Tuple

from alpha_tech_tracker.trade_api.execution_client import ExecutionClient, InsufficientFundsError

from .models import _D, _stock_bid_ask
from .option_price_monitor import _quantize_option_price, ticker_is_penny_pilot

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


def _shrink_shares_for_insufficient_buying_power(
    message: str, current_shares: int
) -> Optional[int]:
    """Parse Alpaca's insufficient-buying-power error and compute a reduced share
    count that should fit within the reported buying power.

    Confirmed Alpaca format (production rejection, 2026-07-31):
      {"buying_power":"7727.51","code":40310000,"cost_basis":"12161.98",
       "message":"insufficient buying power"}

    Reg-T short-sale margin requires ~150% of a short's market value, so
    cost_basis already reflects that multiplier — buying_power/cost_basis is
    the fraction of the attempted order that actually fits. A 5% safety
    margin is applied so the retry doesn't bump the same limit again from
    price movement or rounding between attempts.

    Returns a reduced share count (>=1 and < current_shares), or None if the
    message can't be parsed or no safe reduction is possible.
    """
    bp_match = re.search(r'"buying_power"\s*:\s*"?([\d.]+)"?', message)
    cost_match = re.search(r'"cost_basis"\s*:\s*"?([\d.]+)"?', message)
    if not bp_match or not cost_match:
        return None
    try:
        buying_power = float(bp_match.group(1))
        cost_basis = float(cost_match.group(1))
    except ValueError:
        return None
    if buying_power <= 0 or cost_basis <= 0:
        return None
    safe_ratio = (buying_power / cost_basis) * 0.95
    new_shares = int(current_shares * safe_ratio)
    if new_shares < 1 or new_shares >= current_shares:
        return None
    return new_shares


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
) -> Tuple[dict, int]:
    """
    Place a limit order and escalate if unfilled.

    Escalation ladder:
      Step 0   (20s, quick-exit only): limit at entry_fill_price — protects against
        selling at a loss when the position was just opened.
      Steps 1-N (adaptive wait, escalating loop): refreshes option quote and calls
        get_fair_price_fn at the start of each iteration. Wait scales 3–10s:
        more patience at conservative prices (near mid), less near the limit (ask/floor).
        BUY: starts at min(fair_price, mid); increments by 0.25×half_spread while
          below mid, then 0.10×half_spread once above mid; caps at ask. Loop exits
          when ask is reached unfilled.
        SELL: starts at max(fair_price, mid); decrements by 0.25×half_spread while
          above mid, then 0.10×half_spread once below mid; floors at
          max(bid, fair_price). Loop exits when floor is reached unfilled.
        Falls through to step 3 if the option quote fetch fails.
      Step 3   (30s buy / 60s sell, final fallback): limit at ask [buy] or
        max(bid, fair_price) [sell]. If unfilled after the timeout, cancels and
        logs FILL_ESC MISS — no market order fallback. Manual intervention
        required for both buys and sells.

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
            quantity=_contracts_remaining[0],
            _option_symbol_override=option_symbol,
        )

    def _check_fill(order_id: str) -> Tuple[Optional[bool], Optional[str], int]:
        """Return (is_filled, reject_reason, filled_qty).

        is_filled=None means status is unknown.
        filled_qty is the number of contracts confirmed filled so far (0 if unknown or unfilled).
        """
        try:
            status = client.order_status(order_id)
        except Exception:
            logger.warning(
                "order_status call failed for %s — fill status unknown, not cancelling",
                order_id,
            )
            return None, None, 0
        try:
            filled_qty = int(status.get("filled_qty") or 0)
        except (TypeError, ValueError):
            filled_qty = 0
        if status.get("status") == "filled":
            return True, None, filled_qty
        return False, status.get("reject_reason"), filled_qty

    def _cancel_safely(order_id: str):
        try:
            client.cancel_order(order_id)
        except Exception:
            logger.warning(
                "Could not cancel order %s (may already be filled)", order_id
            )

    def _get_fair_price():
        if get_fair_price_fn is None:
            return None
        try:
            return get_fair_price_fn()
        except Exception:
            logger.warning("get_fair_price_fn failed for %s", option_symbol)
            return None

    def _adaptive_wait(price: Decimal, bid: Decimal, ask: Decimal, spread: Decimal) -> int:
        """
        Return a wait time (seconds) that scales with how far price is from the limit.

        BUY:  distance = ask - price  (large when price is near mid, small near ask)
        SELL: distance = price - bid  (large when price is near mid, small near floor)

        Range: 3s (at the limit/floor) → 10s (at mid, best-value price).
        """
        if spread <= _D("0"):
            return 5
        if is_buy:
            ratio = (ask - price) / spread
        else:
            ratio = (price - bid) / spread
        ratio = float(max(_D("0"), min(_D("1"), ratio)))
        return max(3, round(3 + 7 * ratio))

    _last_known_quote = [None, None]   # [bid, ask] — updated after each successful fetch
    _anchor_half_spread = [None]       # set on first successful quote; used as minimum increment size
    _last_placed_price = [None]        # last quantized limit price placed in the loop
    _our_price_streak = [0]            # consecutive iterations where the quote side we drive
                                       # (bid for BUY, ask for SELL) ≈ last placed price;
                                       # streak >= 2 → use anchor half_spread, not compressed current
    _contracts_remaining = [contracts] # decremented on each confirmed partial fill
    _confirmed_filled = [0]            # running total of contracts confirmed filled; returned to caller

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
            fill_status, _, filled_qty = _check_fill(order_id)
            if fill_status:
                logger.info("FILL_ESC step0 filled at entry price: %s", order_id)
                _confirmed_filled[0] += _contracts_remaining[0]
                return order, _confirmed_filled[0]
            if fill_status is None:
                logger.warning(
                    "FILL_ESC step0 %s %s: fill status unknown — not cancelling, returning order",
                    order_action, option_symbol,
                )
                _confirmed_filled[0] += _contracts_remaining[0]
                return order, _confirmed_filled[0]
            _cancel_safely(order_id)
            if filled_qty > 0:
                partial = min(filled_qty, _contracts_remaining[0])
                _confirmed_filled[0] += partial
                _contracts_remaining[0] -= partial
                logger.info(
                    "FILL_ESC step0 %s %s: partial fill %d contracts, %d remaining, escalating",
                    order_action, option_symbol, partial, _contracts_remaining[0],
                )
                if _contracts_remaining[0] == 0:
                    return order, _confirmed_filled[0]
            else:
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
            current_half_spread = (ask - bid) / _D("2")
            if current_half_spread <= _D("0"):
                logger.warning(
                    "FILL_ESC loop step%d %s %s: crossed quote bid=%s ask=%s,"
                    " waiting up to 15s for normalization",
                    step_num, order_action, option_symbol, bid, ask,
                )
                normalized = False
                for _retry in range(3):
                    time.sleep(5)
                    try:
                        bid, ask, mid = _fetch_mid_bid_ask()
                        current_half_spread = (ask - bid) / _D("2")
                        if current_half_spread > _D("0"):
                            normalized = True
                            break
                    except Exception:
                        pass
                if not normalized:
                    logger.warning(
                        "FILL_ESC loop step%d %s %s: quote still crossed after 15s,"
                        " falling to step3",
                        step_num, order_action, option_symbol,
                    )
                    break
            if _anchor_half_spread[0] is None:
                _anchor_half_spread[0] = current_half_spread
            if _last_placed_price[0] is not None:
                driven_side = bid if is_buy else ask
                if abs(driven_side - _last_placed_price[0]) <= _D("0.05"):
                    _our_price_streak[0] += 1
                else:
                    _our_price_streak[0] = 0
            half_spread = _anchor_half_spread[0] if _our_price_streak[0] >= 2 \
                else max(_anchor_half_spread[0], current_half_spread)
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
                # Re-anchor upward if fair/mid has risen above current_price (rising market).
                # Mirrors the SELL floor: max(bid, fair) used every iteration on the sell side.
                anchor = min(fair, mid) if fair is not None else mid
                current_price = max(current_price, anchor)
                increment = _D("0.25") * half_spread if current_price < mid \
                    else _D("0.10") * half_spread
                current_price = min(current_price + increment, ask)
            else:
                sell_floor = max(bid, fair) if fair is not None else bid
                # Re-anchor downward if fair/mid has fallen below current_price (falling market).
                # Mirrors the BUY re-anchor: max(current_price, min(fair, mid)) for rising market.
                anchor = max(fair, mid) if fair is not None else mid
                current_price = min(current_price, anchor)
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
            _last_placed_price[0] = _quantize_option_price(current_price, penny_pilot=penny_pilot)
            order = _place_limit(current_price)
        except Exception as exc:
            if isinstance(exc, InsufficientFundsError):
                logger.warning(
                    "FILL_ESC loop step%d %s %s: insufficient options buying power"
                    " — aborting escalation",
                    step_num, order_action, option_symbol,
                )
                return {}, 0
            logger.warning(
                "FILL_ESC loop step%d %s %s: placement failed, escalating",
                step_num, order_action, option_symbol, exc_info=True,
            )
        else:
            order_id = order.get("order_id")
            wait = _adaptive_wait(current_price, bid, ask, half_spread)
            logger.info(
                "FILL_ESC loop step%d order placed: id=%s (wait=%ds)", step_num, order_id, wait
            )
            time.sleep(wait)
            fill_status, reject_reason, filled_qty = _check_fill(order_id)
            if fill_status:
                logger.info("FILL_ESC loop step%d filled: %s", step_num, order_id)
                _confirmed_filled[0] += _contracts_remaining[0]
                return order, _confirmed_filled[0]
            if fill_status is None:
                logger.warning(
                    "FILL_ESC loop step%d %s %s: fill status unknown — not cancelling, returning order",
                    step_num, order_action, option_symbol,
                )
                _confirmed_filled[0] += _contracts_remaining[0]
                return order, _confirmed_filled[0]
            if filled_qty > 0:
                partial = min(filled_qty, _contracts_remaining[0])
                _confirmed_filled[0] += partial
                _contracts_remaining[0] -= partial
                logger.info(
                    "FILL_ESC loop step%d %s %s: partial fill %d contracts, %d remaining",
                    step_num, order_action, option_symbol, partial, _contracts_remaining[0],
                )
                _cancel_safely(order_id)
                if _contracts_remaining[0] == 0:
                    return order, _confirmed_filled[0]
                current_price = None
                continue
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
                    _last_placed_price[0] = _quantize_option_price(current_price, penny_pilot=penny_pilot)
                    order = _place_limit(current_price)
                except Exception as exc:
                    if isinstance(exc, InsufficientFundsError):
                        logger.warning(
                            "FILL_ESC loop step%d %s %s: insufficient options buying power"
                            " — aborting escalation",
                            step_num, order_action, option_symbol,
                        )
                        return {}, 0
                    logger.warning(
                        "FILL_ESC loop step%d %s %s: tick-retry placement failed",
                        step_num, order_action, option_symbol, exc_info=True,
                    )
                else:
                    order_id = order.get("order_id")
                    wait = _adaptive_wait(current_price, bid, ask, half_spread)
                    logger.info(
                        "FILL_ESC loop step%d tick-retry order placed: id=%s (wait=%ds)",
                        step_num, order_id, wait,
                    )
                    time.sleep(wait)
                    fill_status, _, filled_qty = _check_fill(order_id)
                    if fill_status:
                        logger.info(
                            "FILL_ESC loop step%d tick-retry filled: %s", step_num, order_id
                        )
                        _confirmed_filled[0] += _contracts_remaining[0]
                        return order, _confirmed_filled[0]
                    if fill_status is None:
                        logger.warning(
                            "FILL_ESC loop step%d %s %s: tick-retry fill status unknown"
                            " — not cancelling, returning order",
                            step_num, order_action, option_symbol,
                        )
                        _confirmed_filled[0] += _contracts_remaining[0]
                        return order, _confirmed_filled[0]
                    if filled_qty > 0:
                        partial = min(filled_qty, _contracts_remaining[0])
                        _confirmed_filled[0] += partial
                        _contracts_remaining[0] -= partial
                        logger.info(
                            "FILL_ESC loop step%d tick-retry %s %s: partial fill %d contracts,"
                            " %d remaining",
                            step_num, order_action, option_symbol,
                            partial, _contracts_remaining[0],
                        )
                        _cancel_safely(order_id)
                        if _contracts_remaining[0] == 0:
                            return order, _confirmed_filled[0]
                        current_price = None
                        continue
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

    if step3_price is None:
        logger.warning(
            "FILL_ESC step3 %s %s: no quote price available, placing market order",
            order_action, option_symbol,
        )
        try:
            order = client.place_option_order(
                symbol=ticker,
                option_key=None,
                price=None,
                price_type="MARKET",
                option_type=option_type,
                order_action=order_action,
                quantity=_contracts_remaining[0],
                _option_symbol_override=option_symbol,
            )
        except Exception:
            logger.warning(
                "FILL_ESC %s %s: market order failed — manual intervention required",
                order_action, option_symbol, exc_info=True,
            )
            return {}, 0
        order_id = order.get("order_id")
        logger.info("FILL_ESC market fallback order placed: id=%s", order_id)
        _confirmed_filled[0] += _contracts_remaining[0]
        return order, _confirmed_filled[0]

    logger.info(
        "FILL_ESC step3 %s %s: final limit at %s",
        order_action, option_symbol,
        step3_price.quantize(_D("0.01"), rounding=ROUND_HALF_UP),
    )
    try:
        order = _place_limit(step3_price)
    except Exception as exc:
        if isinstance(exc, InsufficientFundsError):
            logger.warning(
                "FILL_ESC step3 %s %s: insufficient options buying power — aborting",
                order_action, option_symbol,
            )
            return {}, 0
        logger.warning(
            "FILL_ESC step3 %s %s: limit placement failed",
            order_action, option_symbol, exc_info=True,
        )
        logger.warning(
            "FILL_ESC MISS %s %s: all steps exhausted — manual intervention required",
            order_action, option_symbol,
        )
        return {}, 0
    order_id = order.get("order_id")
    logger.info("FILL_ESC step3 order placed: id=%s", order_id)
    time.sleep(60 if not is_buy else 30)
    fill_status, reject_reason, filled_qty = _check_fill(order_id)
    if fill_status:
        logger.info("FILL_ESC step3 filled: %s", order_id)
        _confirmed_filled[0] += _contracts_remaining[0]
        return order, _confirmed_filled[0]
    if fill_status is None:
        logger.warning(
            "FILL_ESC step3 %s %s: fill status unknown — not cancelling, returning order",
            order_action, option_symbol,
        )
        _confirmed_filled[0] += _contracts_remaining[0]
        return order, _confirmed_filled[0]
    if filled_qty > 0:
        partial = min(filled_qty, _contracts_remaining[0])
        _confirmed_filled[0] += partial
        _contracts_remaining[0] -= partial
        logger.warning(
            "FILL_ESC step3 %s %s: partial fill %d contracts, %d still open"
            " — manual close required",
            order_action, option_symbol, partial, _contracts_remaining[0],
        )
        _cancel_safely(order_id)
        if _contracts_remaining[0] == 0:
            return order, _confirmed_filled[0]
        logger.warning(
            "FILL_ESC MISS %s %s: %d contracts still open after partial fill"
            " — manual intervention required",
            order_action, option_symbol, _contracts_remaining[0],
        )
        return order, _confirmed_filled[0]
    _cancel_safely(order_id)
    tick = _parse_tick_from_reject_reason(reject_reason) \
        if isinstance(reject_reason, str) else None
    if tick is not None:
        adjusted = (step3_price / tick).to_integral_value(rounding=ROUND_HALF_UP) * tick
        logger.warning(
            "FILL_ESC step3 %s %s: tick rejection (required=%s),"
            " adjusting %s → %s, retrying",
            order_action, option_symbol, tick,
            step3_price.quantize(_D("0.01"), rounding=ROUND_HALF_UP),
            adjusted.quantize(_D("0.01"), rounding=ROUND_HALF_UP),
        )
        try:
            order = _place_limit(adjusted)
        except Exception:
            logger.warning(
                "FILL_ESC step3 %s %s: tick-retry placement failed",
                order_action, option_symbol, exc_info=True,
            )
        else:
            order_id = order.get("order_id")
            logger.info("FILL_ESC step3 tick-retry order placed: id=%s", order_id)
            time.sleep(60 if not is_buy else 30)
            fill_status, _, filled_qty = _check_fill(order_id)
            if fill_status:
                logger.info("FILL_ESC step3 tick-retry filled: %s", order_id)
                _confirmed_filled[0] += _contracts_remaining[0]
                return order, _confirmed_filled[0]
            if fill_status is None:
                logger.warning(
                    "FILL_ESC step3 %s %s: tick-retry fill status unknown"
                    " — not cancelling, returning order",
                    order_action, option_symbol,
                )
                _confirmed_filled[0] += _contracts_remaining[0]
                return order, _confirmed_filled[0]
            if filled_qty > 0:
                partial = min(filled_qty, _contracts_remaining[0])
                _confirmed_filled[0] += partial
                _contracts_remaining[0] -= partial
                logger.warning(
                    "FILL_ESC step3 tick-retry %s %s: partial fill %d contracts,"
                    " %d still open — manual close required",
                    order_action, option_symbol, partial, _contracts_remaining[0],
                )
                _cancel_safely(order_id)
                if _contracts_remaining[0] == 0:
                    return order, _confirmed_filled[0]
            else:
                _cancel_safely(order_id)
    logger.warning(
        "FILL_ESC MISS %s %s: all steps exhausted, order %s cancelled — manual intervention required",
        order_action, option_symbol, order_id,
    )
    return order, _confirmed_filled[0]


def place_option_order_in_tranches(
    client: ExecutionClient,
    ticker: str,
    option_symbol: str,
    option_type: str,
    contracts: int,
    order_action: str,
    tranche_size: int = 2,
    entry_fill_price: Optional[float] = None,
    get_fair_price_fn=None,
    feed=None,
) -> Tuple[dict, int]:
    """
    Fill `contracts` option contracts by sending sequential tranches of at most
    `tranche_size` through the standard limit-escalation policy.

    Each tranche starts fresh from the current market mid so later tranches adapt
    to price movements between fills.  Stops on the first MISS; contracts filled
    in prior tranches remain open at the broker.

    entry_fill_price (quick-exit protection) is forwarded to the first tranche only.

    Returns:
        (last_order, filled_so_far)
        last_order    — order dict from the last attempted tranche ({} on MISS)
        filled_so_far — total contracts confirmed filled across all tranches
    """
    penny_pilot = ticker_is_penny_pilot(ticker)
    if contracts <= tranche_size:
        order, confirmed_filled = _place_with_fill_escalation(
            client=client,
            ticker=ticker,
            option_symbol=option_symbol,
            option_type=option_type,
            contracts=contracts,
            order_action=order_action,
            entry_fill_price=entry_fill_price,
            get_fair_price_fn=get_fair_price_fn,
            feed=feed,
            penny_pilot=penny_pilot,
        )
        return order, confirmed_filled

    total_tranches = -(-contracts // tranche_size)   # ceiling division
    remaining = contracts
    filled_so_far = 0
    last_order: dict = {}
    tranche_num = 0
    total_cost = _D("0")
    total_weighted_filled = 0

    while remaining > 0:
        tranche_num += 1
        batch = min(remaining, tranche_size)
        logger.info(
            "TRANCHE %d/%d %s %s: placing %d contracts (%d of %d remaining)",
            tranche_num, total_tranches, order_action, option_symbol,
            batch, remaining, contracts,
        )
        order, confirmed_filled = _place_with_fill_escalation(
            client=client,
            ticker=ticker,
            option_symbol=option_symbol,
            option_type=option_type,
            contracts=batch,
            order_action=order_action,
            entry_fill_price=entry_fill_price if tranche_num == 1 else None,
            get_fair_price_fn=get_fair_price_fn,
            feed=feed,
            penny_pilot=penny_pilot,
        )
        last_order = order
        if confirmed_filled == 0:
            logger.warning(
                "TRANCHE %d/%d %s %s: MISS — stopping, %d/%d contracts filled",
                tranche_num, total_tranches, order_action, option_symbol,
                filled_so_far, contracts,
            )
            break
        filled_so_far += confirmed_filled
        remaining -= confirmed_filled

        tranche_order_id = order.get("order_id")
        if tranche_order_id:
            try:
                status = client.order_status(tranche_order_id)
                price_raw = status.get("filled_avg_price")
                if price_raw is not None:
                    total_cost += _D(str(price_raw)) * confirmed_filled
                    total_weighted_filled += confirmed_filled
            except Exception:
                logger.warning(
                    "TRANCHE %d/%d: could not poll fill price for order %s",
                    tranche_num, total_tranches, tranche_order_id,
                )

    if last_order and total_weighted_filled > 0:
        last_order["avg_fill_price"] = total_cost / total_weighted_filled

    return last_order, filled_so_far


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
      Step 1: limit at mid — 1 attempt for exits, up to 3 for entries.
              Buy orders with spread > $0.50 skip step1 (mid-limit won't fill on IEX).
              Poll interval: 2s per attempt.
      Step 2: cancel unfilled -> re-fetch quote -> limit at ask (buy) or bid (sell).
              Up to 3 attempts, 10s each.
      Step 3: cancel unfilled -> market order.
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
    is_exit = order_action in ("BUY_COVER", "SELL_CLOSE")

    side = "BUY" if is_buy else "SELL"

    _STALE_SPREAD_THRESHOLD = _D("0.03")

    def _fetch_mid_bid_ask():
        kwargs = {"feed": feed} if feed is not None else {}
        raw_quote = client.get_stock_quote(ticker, **kwargs)
        bid_f, ask_f = _stock_bid_ask(raw_quote)
        bid = _D(str(bid_f))
        ask = _D(str(ask_f))
        if ask == _D("0"):
            raise ValueError(f"ask=0 for {ticker} — stale quote, cannot compute mid price")
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

    _shares_remaining = [shares]
    _total_filled = [0]

    def _enrich_result(order: dict) -> dict:
        result = dict(order)
        result["total_filled_qty"] = _total_filled[0]
        return result

    def _place_limit(price) -> dict:
        rounded = float(price.quantize(_D("0.01"), rounding=ROUND_HALF_UP))
        return client.place_stock_order(
            symbol=ticker,
            quantity=_shares_remaining[0],
            side=side,
            order_type="LIMIT",
            limit_price=rounded,
            trade_action=order_action,
        )

    def _place_market() -> dict:
        return client.place_stock_order(
            symbol=ticker,
            quantity=_shares_remaining[0],
            side=side,
            order_type="MARKET",
            trade_action=order_action,
        )

    def _check_fill_status(order_id: str):
        """Return (is_filled, filled_qty). is_filled=None means status unknown."""
        try:
            status = client.order_status(order_id)
            filled_qty = int(status.get("filled_qty") or 0)
            return status.get("status") == "filled", filled_qty
        except Exception:
            logger.warning(
                "order_status call failed for %s — fill status unknown, not cancelling",
                order_id,
            )
            return None, 0

    def _cancel_safely(order_id: str):
        try:
            client.cancel_order(order_id)
        except Exception:
            logger.warning(
                "Could not cancel order %s (may already be filled)", order_id
            )

    def _absorb_partial(order_id: str, step: str, attempt: int, filled_qty: int):
        """Record a partial fill from a cancelled order and reduce _shares_remaining."""
        partial = min(filled_qty, _shares_remaining[0])
        if partial > 0:
            _shares_remaining[0] -= partial
            _total_filled[0] += partial
            logger.warning(
                "STOCK FILL_ESC %s attempt=%d %s %s: partial fill %d shares on cancel "
                "— %d remaining (order=%s)",
                step, attempt, order_action, ticker,
                partial, _shares_remaining[0], order_id,
            )

    for attempt in range(1, 2 if is_exit else 4):
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
            _total_filled[0] += _shares_remaining[0]
            return _enrich_result(_place_market())

        if is_buy and (ask - bid) > _D("0.50"):
            logger.info(
                "STOCK FILL_ESC step1 attempt=%d %s %s: wide spread $%.2f > $0.50, skipping to step2",
                attempt, order_action, ticker, float(ask - bid),
            )
            break

        try:
            order = _place_limit(mid)
        except Exception as exc:
            if isinstance(exc, InsufficientFundsError):
                if order_action == "SELL_SHORT":
                    new_shares = _shrink_shares_for_insufficient_buying_power(
                        str(exc), _shares_remaining[0]
                    )
                    if new_shares is not None:
                        logger.warning(
                            "STOCK FILL_ESC step1 attempt=%d %s %s: insufficient buying power for "
                            "%d shares — reducing to %d shares and retrying",
                            attempt, order_action, ticker, _shares_remaining[0], new_shares,
                        )
                        _shares_remaining[0] = new_shares
                        continue
                logger.warning(
                    "STOCK FILL_ESC step1 attempt=%d %s %s: insufficient funds — aborting",
                    attempt, order_action, ticker,
                )
                raise
            logger.warning(
                "STOCK FILL_ESC step1 attempt=%d %s %s: placement failed, escalating",
                attempt, order_action, ticker, exc_info=True,
            )
            continue

        order_id = order.get("order_id")
        logger.info("STOCK FILL_ESC step1 attempt=%d order placed: id=%s", attempt, order_id)

        time.sleep(2)
        fill_status, filled_qty = _check_fill_status(order_id)
        if fill_status:
            logger.info("STOCK FILL_ESC step1 attempt=%d filled: %s", attempt, order_id)
            _total_filled[0] += _shares_remaining[0]
            return _enrich_result(order)
        if fill_status is None:
            logger.warning(
                "STOCK FILL_ESC step1 attempt=%d %s %s: fill status unknown — not cancelling, returning order",
                attempt, order_action, ticker,
            )
            _total_filled[0] += _shares_remaining[0]
            return _enrich_result(order)
        _absorb_partial(order_id, "step1", attempt, filled_qty)
        _cancel_safely(order_id)
        time.sleep(0.5)
        _, post_cancel_filled_qty = _check_fill_status(order_id)
        incremental = post_cancel_filled_qty - filled_qty
        if incremental > 0:
            _absorb_partial(order_id, "step1-post-cancel", attempt, incremental)
        if _shares_remaining[0] <= 0:
            return _enrich_result(order)
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
            _total_filled[0] += _shares_remaining[0]
            return _enrich_result(_place_market())

        try:
            order = _place_limit(aggressive_price)
        except Exception as exc:
            if isinstance(exc, InsufficientFundsError):
                if order_action == "SELL_SHORT":
                    new_shares = _shrink_shares_for_insufficient_buying_power(
                        str(exc), _shares_remaining[0]
                    )
                    if new_shares is not None:
                        logger.warning(
                            "STOCK FILL_ESC step2 attempt=%d %s %s: insufficient buying power for "
                            "%d shares — reducing to %d shares and retrying",
                            attempt, order_action, ticker, _shares_remaining[0], new_shares,
                        )
                        _shares_remaining[0] = new_shares
                        continue
                logger.warning(
                    "STOCK FILL_ESC step2 attempt=%d %s %s: insufficient funds — aborting",
                    attempt, order_action, ticker,
                )
                raise
            logger.warning(
                "STOCK FILL_ESC step2 attempt=%d %s %s: placement failed, escalating",
                attempt, order_action, ticker, exc_info=True,
            )
            continue

        order_id = order.get("order_id")
        logger.info("STOCK FILL_ESC step2 attempt=%d order placed: id=%s", attempt, order_id)

        time.sleep(10)
        fill_status, filled_qty = _check_fill_status(order_id)
        if fill_status:
            logger.info("STOCK FILL_ESC step2 attempt=%d filled: %s", attempt, order_id)
            _total_filled[0] += _shares_remaining[0]
            return _enrich_result(order)
        if fill_status is None:
            logger.warning(
                "STOCK FILL_ESC step2 attempt=%d %s %s: fill status unknown — not cancelling, returning order",
                attempt, order_action, ticker,
            )
            _total_filled[0] += _shares_remaining[0]
            return _enrich_result(order)
        _absorb_partial(order_id, "step2", attempt, filled_qty)
        _cancel_safely(order_id)
        if _shares_remaining[0] <= 0:
            return _enrich_result(order)

    logger.info("STOCK FILL_ESC step3 %s %s: placing market order", order_action, ticker)
    order = _place_market()
    logger.info("STOCK FILL_ESC step3 market order placed: id=%s", order.get("order_id"))
    _total_filled[0] += _shares_remaining[0]
    return _enrich_result(order)

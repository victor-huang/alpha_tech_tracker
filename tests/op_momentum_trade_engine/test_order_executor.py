import pytest
from decimal import Decimal
from unittest.mock import MagicMock, patch

from alpha_tech_tracker.op_momentum_strategy.order_executor import (
    _parse_tick_from_reject_reason,
    _place_with_fill_escalation,
    place_stock_order,
)

_D = Decimal

_MODULE = "alpha_tech_tracker.op_momentum_strategy.order_executor"


def _make_client(bid=4.90, ask=5.10, order_status="open"):
    """Return a mock ExecutionClient with a pre-configured option quote and order status."""
    client = MagicMock()

    mid = (bid + ask) / 2
    client.get_option_quote_by_occ.return_value = {"bid": bid, "ask": ask, "mid": mid}

    client.place_option_order.return_value = {
        "order_id": "ord-001",
        "status": order_status,
    }
    client.order_status.return_value = {"status": order_status}

    return client


_TICKER = "TSLA"
_SYMBOL = "TSLA260328C00280000"
_OPTION_TYPE = "CALL"
_CONTRACTS = 1
_SELL = "SELL_CLOSE"


class TestFillEscalationStep0:
    """
    When entry_fill_price is supplied, _place_with_fill_escalation() should
    try a limit at that price first (step 0) for 60 seconds before falling
    through to the normal mid → ask/bid → market escalation.
    """

    def _run(self, client, entry_fill_price=None, step0_filled=False):
        def fake_order_status(order_id):
            if order_id == "ord-001" and step0_filled:
                return {"status": "filled"}
            return {"status": "open"}

        client.order_status.side_effect = fake_order_status

        with patch(f"{_MODULE}.time.sleep", lambda _: None):
            result = _place_with_fill_escalation(
                client=client,
                ticker=_TICKER,
                option_symbol=_SYMBOL,
                option_type=_OPTION_TYPE,
                contracts=_CONTRACTS,
                order_action=_SELL,
                entry_fill_price=entry_fill_price,
            )
        return result

    def test_without_entry_fill_price_skips_step0(self):
        client = _make_client()
        self._run(client, entry_fill_price=None)
        # No step-0: loop runs 11 steps (mid→bid in 0.01 decrements) + step3 = 12 status checks
        assert client.order_status.call_count == 12

    def test_with_entry_fill_price_places_step0_order_first(self):
        client = _make_client()
        self._run(client, entry_fill_price=5.0, step0_filled=False)
        # step0 + 11 loop steps + step3 = 13 status checks
        assert client.order_status.call_count == 13

    def test_step0_filled_returns_immediately_without_further_orders(self):
        client = _make_client()
        self._run(client, entry_fill_price=5.0, step0_filled=True)
        # Filled at step0 — only 1 status check; no further limit/market orders placed
        assert client.order_status.call_count == 1
        # place_option_order called exactly once (the step0 limit order)
        assert client.place_option_order.call_count == 1

    def test_step0_uses_entry_fill_price_as_limit(self):
        client = _make_client()
        self._run(client, entry_fill_price=5.0, step0_filled=False)
        first_call_kwargs = client.place_option_order.call_args_list[0].kwargs
        # entry_fill_price=5.0 → quantize ≥$3 → $0.05 tick → $5.00
        assert first_call_kwargs["price"] == 5.0
        assert first_call_kwargs["price_type"] == "LIMIT"

    def test_step0_unfilled_cancels_order_and_continues(self):
        client = _make_client()
        self._run(client, entry_fill_price=5.0, step0_filled=False)
        # cancel_order should have been called at least once (step0 cancel)
        assert client.cancel_order.call_count >= 1

    def test_step0_unfilled_then_loop_then_step3_miss(self):
        client = _make_client()
        self._run(client, entry_fill_price=5.0, step0_filled=False)
        # step0(1) + loop 11 steps + step3 limit = 13 calls; no market order fallback
        assert client.place_option_order.call_count == 13


class TestFillEscalationMissCancellation:
    """
    When all escalation steps exhaust without a fill (FILL_ESC MISS),
    the final unfilled step-3 order must be cancelled before returning.
    """

    def _run_all_unfilled(self, client):
        client.order_status.return_value = {"status": "open"}
        with patch(f"{_MODULE}.time.sleep", lambda _: None):
            return _place_with_fill_escalation(
                client=client,
                ticker=_TICKER,
                option_symbol=_SYMBOL,
                option_type=_OPTION_TYPE,
                contracts=_CONTRACTS,
                order_action=_SELL,
            )

    def test_miss_cancels_step3_order(self):
        client = _make_client()
        self._run_all_unfilled(client)
        # loop(11) + step3(1) = 12 cancels
        assert client.cancel_order.call_count == 12

    def test_miss_cancel_uses_step3_order_id(self):
        client = _make_client()
        self._run_all_unfilled(client)
        last_cancel_arg = client.cancel_order.call_args_list[-1].args[0]
        assert last_cancel_arg == "ord-001"


class TestFillEscalationLoop:
    """
    The escalating limit loop (steps 1-N):
    - BUY:  starts at min(fair_price, mid); +0.25×half_spread below mid, +0.10× above mid
    - SELL: starts at max(fair_price, mid); -0.25×half_spread above mid, -0.10× below mid
    - Option quote and get_fair_price_fn are refreshed at the start of each iteration.
    """

    # Wide spread: bid=4.00, ask=8.00 → mid=6.00, half_spread=2.00
    # Fast increment (below mid): 0.25×2=0.50
    # Slow increment (above/at mid): 0.10×2=0.20
    _BID = 4.00
    _ASK = 8.00

    def _make_loop_client(self, fill_on=None):
        client = MagicMock()
        mid = (self._BID + self._ASK) / 2
        client.get_option_quote_by_occ.return_value = {
            "bid": self._BID, "ask": self._ASK, "mid": mid
        }
        client.place_option_order.return_value = {"order_id": "ord-001", "status": "open"}
        status_count = [0]

        def order_status(_order_id):
            status_count[0] += 1
            if fill_on is not None and status_count[0] == fill_on:
                return {"status": "filled"}
            return {"status": "open"}

        client.order_status.side_effect = order_status
        return client

    def _run(self, client, order_action, get_fair_price_fn=None):
        with patch(f"{_MODULE}.time.sleep", lambda _: None):
            return _place_with_fill_escalation(
                client=client,
                ticker=_TICKER,
                option_symbol=_SYMBOL,
                option_type=_OPTION_TYPE,
                contracts=1,
                order_action=order_action,
                get_fair_price_fn=get_fair_price_fn,
            )

    def _limit_prices(self, client):
        return [
            c.kwargs["price"]
            for c in client.place_option_order.call_args_list
            if c.kwargs.get("price_type") == "LIMIT"
        ]

    # --- BUY: start price ---

    def test_buy_without_fair_price_fn_starts_at_mid(self):
        client = self._make_loop_client(fill_on=1)
        self._run(client, "BUY_OPEN")
        assert self._limit_prices(client)[0] == 6.00

    def test_buy_with_fair_below_mid_starts_at_fair(self):
        client = self._make_loop_client(fill_on=1)
        fair_fn = MagicMock(return_value=_D("4.50"))
        self._run(client, "BUY_OPEN", get_fair_price_fn=fair_fn)
        assert self._limit_prices(client)[0] == 4.50

    def test_buy_with_fair_above_mid_starts_at_mid(self):
        client = self._make_loop_client(fill_on=1)
        fair_fn = MagicMock(return_value=_D("7.00"))
        self._run(client, "BUY_OPEN", get_fair_price_fn=fair_fn)
        assert self._limit_prices(client)[0] == 6.00

    # --- BUY: escalation rate ---

    def test_buy_escalates_fast_below_mid_then_slow_above(self):
        # fair=4.50 → start=4.50; +0.50 while < mid=6.00, +0.20 once at/above mid
        # step1: 4.50  step2: 5.00  step3: 5.50  step4: 6.00  step5: 6.20 (filled)
        client = self._make_loop_client(fill_on=5)
        fair_fn = MagicMock(return_value=_D("4.50"))
        self._run(client, "BUY_OPEN", get_fair_price_fn=fair_fn)
        prices = self._limit_prices(client)
        assert prices[0] == 4.50   # start at fair
        assert prices[1] == 5.00   # +0.50 (fast, below mid)
        assert prices[2] == 5.50   # +0.50 (fast, below mid)
        assert prices[3] == 6.00   # +0.50 (fast, 5.50 < 6.00 → still fast)
        assert prices[4] == 6.20   # +0.20 (slow, 6.00 is at mid → not < mid)

    def test_buy_fills_on_first_step_returns_immediately(self):
        client = self._make_loop_client(fill_on=1)
        result = self._run(client, "BUY_OPEN")
        assert len(self._limit_prices(client)) == 1
        assert result.get("order_id") == "ord-001"

    # --- SELL: start price ---

    def test_sell_without_fair_price_fn_starts_at_mid(self):
        client = self._make_loop_client(fill_on=1)
        self._run(client, "SELL_CLOSE")
        assert self._limit_prices(client)[0] == 6.00

    def test_sell_with_fair_below_mid_starts_at_mid(self):
        # max(fair=4.50, mid=6.00) = 6.00
        client = self._make_loop_client(fill_on=1)
        fair_fn = MagicMock(return_value=_D("4.50"))
        self._run(client, "SELL_CLOSE", get_fair_price_fn=fair_fn)
        assert self._limit_prices(client)[0] == 6.00

    def test_sell_with_fair_above_mid_starts_at_fair(self):
        # max(fair=7.00, mid=6.00) = 7.00
        client = self._make_loop_client(fill_on=1)
        fair_fn = MagicMock(return_value=_D("7.00"))
        self._run(client, "SELL_CLOSE", get_fair_price_fn=fair_fn)
        assert self._limit_prices(client)[0] == 7.00

    # --- SELL: escalation rate ---

    def test_sell_decrements_slow_when_at_or_below_mid(self):
        # fair=5.00 → start=max(5.00, 6.00)=6.00 (at mid); -0.20 per step (slow)
        # step1: 6.00  step2: 5.80  step3: 5.60 (filled)
        client = self._make_loop_client(fill_on=3)
        fair_fn = MagicMock(return_value=_D("5.00"))
        self._run(client, "SELL_CLOSE", get_fair_price_fn=fair_fn)
        prices = self._limit_prices(client)
        assert prices[0] == 6.00   # start at mid (fair < mid)
        assert prices[1] == 5.80   # -0.20 (slow: 6.00 not > 6.00)
        assert prices[2] == 5.60   # -0.20

    def test_sell_fills_on_first_step_returns_immediately(self):
        client = self._make_loop_client(fill_on=1)
        result = self._run(client, "SELL_CLOSE")
        assert len(self._limit_prices(client)) == 1
        assert result.get("order_id") == "ord-001"

    # --- edge cases ---

    def test_fair_price_zero_treated_as_none_buy_starts_at_mid(self):
        client = self._make_loop_client(fill_on=1)
        fair_fn = MagicMock(return_value=_D("0"))
        self._run(client, "BUY_OPEN", get_fair_price_fn=fair_fn)
        assert self._limit_prices(client)[0] == 6.00

    def test_fair_price_fn_called_each_loop_iteration(self):
        # fill on step 3 → fn called exactly 3 times (one per iteration)
        client = self._make_loop_client(fill_on=3)
        fair_fn = MagicMock(return_value=_D("5.00"))
        self._run(client, "BUY_OPEN", get_fair_price_fn=fair_fn)
        assert fair_fn.call_count == 3

    def test_option_quote_refreshed_each_loop_iteration(self):
        # fill on step 3 → get_option_quote_by_occ called 3 times (no step3 fallback)
        client = self._make_loop_client(fill_on=3)
        self._run(client, "BUY_OPEN")
        assert client.get_option_quote_by_occ.call_count == 3


class TestParseTickFromRejectReason:
    def test_confirmed_production_format(self):
        msg = "Price = 41.65000000 not rounded to a valid price increment [ 0.1 ]"
        assert _parse_tick_from_reject_reason(msg) == _D("0.1")

    def test_five_cent_tick(self):
        msg = "Price = 0.09000000 not rounded to a valid price increment [ 0.05 ]"
        assert _parse_tick_from_reject_reason(msg) == _D("0.05")

    def test_non_tick_message_returns_none(self):
        assert _parse_tick_from_reject_reason("You are long 0 contracts!") is None

    def test_buying_power_message_returns_none(self):
        assert _parse_tick_from_reject_reason(
            "ECL1000: This order requires $8,000 of Day Trade Buying Power"
        ) is None


class TestTickRejectionRetry:
    """
    When an order is immediately REJ'd with a tick increment error, the loop
    re-quantizes current_price to the required tick and retries once.

    Confirmed production RejectReason format (2026-04-17):
      "Price = 41.65000000 not rounded to a valid price increment [ 0.1 ]"
    """

    _TICK_REJ_MSG = (
        "Price = 6.05000000 not rounded to a valid price increment [ 0.1 ]"
    )

    def _make_client(self, rej_then_fill=True):
        client = MagicMock()
        client.get_option_quote_by_occ.return_value = {"bid": 5.90, "ask": 6.20, "mid": 6.05}
        client.place_option_order.return_value = {"order_id": "ord-001"}
        if rej_then_fill:
            # First order_status call → REJ with tick error; second → filled
            client.order_status.side_effect = [
                {"status": "canceled", "reject_reason": self._TICK_REJ_MSG},
                {"status": "filled"},
            ]
        return client

    def test_tick_rejection_triggers_retry_order(self):
        client = self._make_client()
        with patch("alpha_tech_tracker.op_momentum_strategy.order_executor.time.sleep", lambda _: None):
            _place_with_fill_escalation(
                client=client, ticker="APP", option_symbol="APP260418C00500000",
                option_type="CALL", contracts=1, order_action="BUY_OPEN",
            )
        # Two orders placed: original ($0.05-rounded) + tick-retry ($0.10-rounded)
        assert client.place_option_order.call_count == 2

    def test_tick_retry_uses_required_increment(self):
        client = self._make_client()
        with patch("alpha_tech_tracker.op_momentum_strategy.order_executor.time.sleep", lambda _: None):
            _place_with_fill_escalation(
                client=client, ticker="APP", option_symbol="APP260418C00500000",
                option_type="CALL", contracts=1, order_action="BUY_OPEN",
            )
        # Original attempt: mid=6.05 → penny_pilot rounds to $0.05 tick → 6.05
        first_price = client.place_option_order.call_args_list[0][1]["price"]
        # Retry: re-quantized to $0.10 tick → 6.10
        retry_price = client.place_option_order.call_args_list[1][1]["price"]
        assert first_price == pytest.approx(6.05)
        assert retry_price == pytest.approx(6.10)

    def test_tick_retry_fills_and_returns(self):
        client = self._make_client(rej_then_fill=True)
        with patch("alpha_tech_tracker.op_momentum_strategy.order_executor.time.sleep", lambda _: None):
            result = _place_with_fill_escalation(
                client=client, ticker="APP", option_symbol="APP260418C00500000",
                option_type="CALL", contracts=1, order_action="BUY_OPEN",
            )
        assert result.get("order_id") == "ord-001"
        assert client.order_status.call_count == 2

    def test_non_tick_rejection_does_not_retry(self):
        client = MagicMock()
        client.get_option_quote_by_occ.return_value = {"bid": 5.90, "ask": 6.20, "mid": 6.05}
        client.place_option_order.return_value = {"order_id": "ord-001"}
        client.order_status.return_value = {
            "status": "canceled",
            "reject_reason": "You are long 0 contracts!",
        }
        with patch("alpha_tech_tracker.op_momentum_strategy.order_executor.time.sleep", lambda _: None):
            _place_with_fill_escalation(
                client=client, ticker="APP", option_symbol="APP260418C00500000",
                option_type="CALL", contracts=1, order_action="BUY_OPEN",
            )
        # No tick retry — order just keeps escalating without doubling up
        assert client.cancel_order.called

    def test_no_reject_reason_does_not_retry(self):
        # Alpaca does not return reject_reason — order_status has no such key.
        # Verify the isinstance guard prevents any retry attempt.
        client = MagicMock()
        client.get_option_quote_by_occ.return_value = {"bid": 5.90, "ask": 6.20, "mid": 6.05}
        client.place_option_order.return_value = {"order_id": "ord-001"}
        client.order_status.return_value = {"status": "canceled"}
        with patch("alpha_tech_tracker.op_momentum_strategy.order_executor.time.sleep", lambda _: None):
            _place_with_fill_escalation(
                client=client, ticker="APP", option_symbol="APP260418C00500000",
                option_type="CALL", contracts=1, order_action="BUY_OPEN",
            )
        assert client.cancel_order.called
        # One place_option_order per order_status check — no retry doubling
        assert client.place_option_order.call_count == client.order_status.call_count


class TestAnchorHalfSpread:
    """
    Two related protections for illiquid / fast-moving options on the BUY side:

    1. Compressed spread: when our unfilled limit shows up as the new best bid,
       the loop uses the original (anchored) half_spread so increments stay meaningful.

    2. Rising market re-anchor: when the underlying rips higher and fair/mid rises
       above current_price, the loop jumps current_price up to min(fair, mid) before
       incrementing — mirrors the SELL-side floor (max(bid, fair)) already in place.
    """

    def test_compressed_quote_uses_anchor_spread_for_increment(self):
        client = MagicMock()
        quote_calls = [0]

        def quote_side_effect(symbol):
            quote_calls[0] += 1
            if quote_calls[0] == 1:
                return {"bid": 4.90, "ask": 5.10, "mid": 5.00}  # original spread = $0.20
            return {"bid": 5.00, "ask": 5.10, "mid": 5.05}      # compressed: our order is now bid

        client.get_option_quote_by_occ.side_effect = quote_side_effect
        client.place_option_order.return_value = {"order_id": "ord-001"}
        client.order_status.side_effect = [
            {"status": "open"},    # step 1 unfilled
            {"status": "filled"},  # step 2 filled
        ]

        with patch(f"{_MODULE}.time.sleep", lambda _: None):
            _place_with_fill_escalation(
                client=client,
                ticker=_TICKER,
                option_symbol=_SYMBOL,
                option_type=_OPTION_TYPE,
                contracts=_CONTRACTS,
                order_action="BUY_OPEN",
            )

        step1_price = client.place_option_order.call_args_list[0].kwargs["price"]
        step2_price = client.place_option_order.call_args_list[1].kwargs["price"]
        # Anchor half_spread=0.10 → increment = 0.25 × 0.10 = 0.025 → step2 > step1.
        # Without anchor (compressed half_spread=0.05) → increment = 0.0125
        # → quantizes back to the same price as step1 (no progress).
        assert step2_price > step1_price

    def test_buy_bid_at_our_price_streak_uses_anchor_spread(self):
        # BUY streak: our limit buy shows up as new best bid each iteration,
        # while ask widens (current_half_spread > anchor).
        # streak >= 2 → use anchor so we don't chase the apparently-wide spread.
        client = MagicMock()
        placed_prices = []

        def place_side_effect(**kw):
            placed_prices.append(Decimal(str(kw.get("price", 0))))
            return {"order_id": "ord-001"}

        def quote_side_effect(symbol):
            if not placed_prices:
                # Step 1: original tight spread; anchor = 0.10
                return {"bid": 4.90, "ask": 5.10, "mid": 5.00}
            # Subsequent steps: bid rises to our last placed price,
            # but ask shoots up (genuinely wider current spread).
            last = float(placed_prices[-1])
            return {"bid": last, "ask": last + 0.60, "mid": last + 0.30}

        client.get_option_quote_by_occ.side_effect = quote_side_effect
        client.place_option_order.side_effect = place_side_effect
        client.order_status.side_effect = [
            {"status": "open"},    # step 1 unfilled
            {"status": "open"},    # step 2 unfilled (streak = 1)
            {"status": "filled"},  # step 3 filled (streak = 2 → anchor fires)
        ]

        with patch(f"{_MODULE}.time.sleep", lambda _: None):
            result = _place_with_fill_escalation(
                client=client,
                ticker=_TICKER,
                option_symbol=_SYMBOL,
                option_type=_OPTION_TYPE,
                contracts=_CONTRACTS,
                order_action="BUY_OPEN",
            )

        assert result.get("order_id") == "ord-001"
        # Prices must be strictly increasing — streak must not stall escalation
        assert placed_prices[1] > placed_prices[0]
        assert placed_prices[2] > placed_prices[1]

    def test_sell_ask_at_our_price_streak_uses_anchor_spread(self):
        # SELL streak: our limit sell shows up as new best ask each iteration,
        # while bid drops (current_half_spread > anchor).
        # streak >= 2 → use anchor so we don't use artificially wide spread.
        client = MagicMock()
        placed_prices = []

        def place_side_effect(**kw):
            placed_prices.append(Decimal(str(kw.get("price", 0))))
            return {"order_id": "ord-001"}

        def quote_side_effect(symbol):
            if not placed_prices:
                return {"bid": 4.90, "ask": 5.10, "mid": 5.00}
            # ask falls to our last placed price; bid drops (wider current spread)
            last = float(placed_prices[-1])
            return {"bid": last - 0.60, "ask": last, "mid": last - 0.30}

        client.get_option_quote_by_occ.side_effect = quote_side_effect
        client.place_option_order.side_effect = place_side_effect
        client.order_status.side_effect = [
            {"status": "open"},    # step 1 unfilled
            {"status": "open"},    # step 2 unfilled (streak = 1)
            {"status": "filled"},  # step 3 filled (streak = 2 → anchor fires)
        ]

        with patch(f"{_MODULE}.time.sleep", lambda _: None):
            result = _place_with_fill_escalation(
                client=client,
                ticker=_PUT_TICKER,
                option_symbol=_PUT_SYMBOL,
                option_type=_PUT_TYPE,
                contracts=_CONTRACTS,
                order_action="SELL_CLOSE",
            )

        assert result.get("order_id") == "ord-001"
        # Prices must be strictly decreasing — streak must not stall escalation
        assert placed_prices[1] < placed_prices[0]
        assert placed_prices[2] < placed_prices[1]

    def test_bid_away_from_our_price_resets_streak(self):
        client = MagicMock()
        quote_calls = [0]

        def quote_side_effect(symbol):
            quote_calls[0] += 1
            if quote_calls[0] <= 2:
                return {"bid": 4.90, "ask": 5.10, "mid": 5.00}
            # bid moved independently — streak must reset
            return {"bid": 4.70, "ask": 5.10, "mid": 4.90}

        client.get_option_quote_by_occ.side_effect = quote_side_effect
        client.place_option_order.return_value = {"order_id": "ord-001"}
        client.order_status.side_effect = [
            {"status": "open"},
            {"status": "open"},
            {"status": "filled"},
        ]

        with patch(f"{_MODULE}.time.sleep", lambda _: None):
            _place_with_fill_escalation(
                client=client,
                ticker=_TICKER,
                option_symbol=_SYMBOL,
                option_type=_OPTION_TYPE,
                contracts=_CONTRACTS,
                order_action="BUY_OPEN",
            )

        # Should complete without error — streak reset, uses max(anchor, current)
        assert client.place_option_order.call_count == 3

    def test_rising_market_reanchors_to_fair_price(self):
        client = MagicMock()
        quote_calls = [0]

        def quote_side_effect(symbol):
            quote_calls[0] += 1
            if quote_calls[0] == 1:
                return {"bid": 5.00, "ask": 5.40, "mid": 5.20}  # original
            return {"bid": 5.40, "ask": 5.80, "mid": 5.60}       # market ripped up

        client.get_option_quote_by_occ.side_effect = quote_side_effect
        client.place_option_order.return_value = {"order_id": "ord-001"}
        client.order_status.side_effect = [
            {"status": "open"},    # step 1 unfilled
            {"status": "filled"},  # step 2 filled
        ]

        # fair_price follows the risen stock: starts at 5.10 (step1), rises to 5.50 (step2)
        fair_calls = [0]

        def fair_price_fn():
            fair_calls[0] += 1
            return _D("5.10") if fair_calls[0] == 1 else _D("5.50")

        with patch(f"{_MODULE}.time.sleep", lambda _: None):
            _place_with_fill_escalation(
                client=client,
                ticker=_TICKER,
                option_symbol=_SYMBOL,
                option_type=_OPTION_TYPE,
                contracts=_CONTRACTS,
                order_action="BUY_OPEN",
                get_fair_price_fn=fair_price_fn,
            )

        step1_price = client.place_option_order.call_args_list[0].kwargs["price"]
        step2_price = client.place_option_order.call_args_list[1].kwargs["price"]
        # Step 1: current_price = min(fair=5.10, mid=5.20) = 5.10
        assert step1_price == pytest.approx(5.10)
        # Step 2: re-anchor to max(5.10, min(fair=5.50, mid=5.60)) = max(5.10, 5.50) = 5.50
        # then increment → 5.50 + step → quantized above 5.50
        # Without re-anchor: 5.10 + small_increment → still around 5.10, far behind market
        assert step2_price > 5.40

    def test_falling_market_reanchors_sell_price_down(self):
        client = MagicMock()
        quote_calls = [0]

        def quote_side_effect(symbol):
            quote_calls[0] += 1
            if quote_calls[0] == 1:
                return {"bid": 4.00, "ask": 6.00, "mid": 5.00}  # original
            return {"bid": 2.50, "ask": 4.00, "mid": 3.25}       # market dropped hard

        client.get_option_quote_by_occ.side_effect = quote_side_effect
        client.place_option_order.return_value = {"order_id": "ord-001"}
        client.order_status.side_effect = [
            {"status": "open"},    # step 1 unfilled
            {"status": "filled"},  # step 2 filled
        ]

        fair_calls = [0]

        def fair_price_fn():
            fair_calls[0] += 1
            return _D("4.80") if fair_calls[0] == 1 else _D("2.80")

        with patch(f"{_MODULE}.time.sleep", lambda _: None):
            _place_with_fill_escalation(
                client=client,
                ticker=_PUT_TICKER,
                option_symbol=_PUT_SYMBOL,
                option_type=_PUT_TYPE,
                contracts=_CONTRACTS,
                order_action="SELL_CLOSE",
                get_fair_price_fn=fair_price_fn,
            )

        step1_price = client.place_option_order.call_args_list[0].kwargs["price"]
        step2_price = client.place_option_order.call_args_list[1].kwargs["price"]
        # Step 1: max(fair=4.80, mid=5.00) = 5.00
        assert step1_price == pytest.approx(5.00)
        # Step 2: re-anchor to min(5.00, max(fair=2.80, mid=3.25)) = min(5.00, 3.25) = 3.25
        # then decrement → well below original step1 price, tracking the market
        # Without re-anchor: 5.00 - small_decrement ≈ 4.75, far above the new mid of 3.25
        assert step2_price < 4.00


_PUT_SYMBOL = "COIN260418P00220000"
_PUT_TYPE = "PUT"
_PUT_TICKER = "COIN"


def _make_option_client_with_stock(
    opt_bid=10.50,
    opt_ask=15.50,
    stock_bid=207.0,
    stock_ask=209.0,
    order_status="open",
):
    """Client with both option and stock quotes for intrinsic-floor tests."""
    client = MagicMock()
    opt_mid = (opt_bid + opt_ask) / 2
    client.get_option_quote_by_occ.return_value = {
        "bid": opt_bid,
        "ask": opt_ask,
        "mid": opt_mid,
    }
    client.get_stock_quote.return_value = {
        "QuoteResponse": {
            "QuoteData": [{"All": {"bid": stock_bid, "ask": stock_ask, "lastTrade": stock_bid}}]
        }
    }
    client.place_option_order.return_value = {"order_id": "ord-001", "status": order_status}
    client.order_status.return_value = {"status": order_status}
    return client


class TestSellFloorBehavior:
    """
    On SELL_CLOSE, the escalation loop floor is max(bid, fair_price).
    Without get_fair_price_fn the floor falls back to bid.
    The floor is enforced via get_fair_price_fn (OptionPriceMonitor); no raw
    stock quote is fetched directly by the escalation loop.
    """

    def _run_sell(self, client, get_fair_price_fn=None):
        client.order_status.return_value = {"status": "open"}
        with patch(f"{_MODULE}.time.sleep", lambda _: None):
            return _place_with_fill_escalation(
                client=client,
                ticker=_PUT_TICKER,
                option_symbol=_PUT_SYMBOL,
                option_type=_PUT_TYPE,
                contracts=1,
                order_action="SELL_CLOSE",
                feed=None,
                get_fair_price_fn=get_fair_price_fn,
            )

    def _limit_prices(self, client):
        return [
            c.kwargs["price"]
            for c in client.place_option_order.call_args_list
            if c.kwargs.get("price_type") == "LIMIT"
        ]

    def test_without_fair_price_fn_floor_is_bid(self):
        # No get_fair_price_fn → floor=bid=10.50; no stock quote ever fetched.
        client = _make_option_client_with_stock(opt_bid=10.50, opt_ask=15.50)
        self._run_sell(client)
        assert all(p >= 10.50 for p in self._limit_prices(client))
        assert client.get_stock_quote.call_count == 0

    def test_with_fair_price_fn_floor_is_max_bid_fair(self):
        # fair_price=12.00 > bid=10.50 → floor=12.00; no loop price should go below 12.00
        client = _make_option_client_with_stock(opt_bid=10.50, opt_ask=15.50)
        fair_fn = MagicMock(return_value=_D("12.00"))
        self._run_sell(client, get_fair_price_fn=fair_fn)
        assert all(p >= 12.00 for p in self._limit_prices(client))

    def test_with_fair_price_fn_failure_falls_back_to_bid_floor(self):
        # get_fair_price_fn raises → treated as no fair → floor=bid
        client = _make_option_client_with_stock(opt_bid=10.50, opt_ask=15.50)
        fair_fn = MagicMock(side_effect=RuntimeError("monitor unavailable"))
        self._run_sell(client, get_fair_price_fn=fair_fn)
        assert all(p >= 10.50 for p in self._limit_prices(client))

    def test_no_stock_quote_fetched_for_buys_without_fair_price_fn(self):
        # BUY_OPEN without get_fair_price_fn never calls get_stock_quote
        client = _make_option_client_with_stock()
        client.order_status.return_value = {"status": "open"}
        with patch(f"{_MODULE}.time.sleep", lambda _: None):
            _place_with_fill_escalation(
                client=client,
                ticker=_PUT_TICKER,
                option_symbol=_PUT_SYMBOL,
                option_type=_PUT_TYPE,
                contracts=1,
                order_action="BUY_OPEN",
                feed=None,
            )
        assert client.get_stock_quote.call_count == 0


class TestStep3NoMarketFallback:
    """
    After step3 limit times out on either BUY_OPEN or SELL_CLOSE, the engine
    logs FILL_ESC MISS and returns without placing a market order — manual
    intervention is required for both sides.
    """

    def _run_sell_all_unfilled(self, client):
        client.order_status.return_value = {"status": "open"}
        with patch(f"{_MODULE}.time.sleep", lambda _: None):
            return _place_with_fill_escalation(
                client=client,
                ticker=_PUT_TICKER,
                option_symbol=_PUT_SYMBOL,
                option_type=_PUT_TYPE,
                contracts=1,
                order_action="SELL_CLOSE",
                feed=None,
            )

    def _run_buy_all_unfilled(self, client):
        client.order_status.return_value = {"status": "open"}
        with patch(f"{_MODULE}.time.sleep", lambda _: None):
            return _place_with_fill_escalation(
                client=client,
                ticker=_PUT_TICKER,
                option_symbol=_PUT_SYMBOL,
                option_type=_PUT_TYPE,
                contracts=1,
                order_action="BUY_OPEN",
                feed=None,
            )

    def test_sell_does_not_place_market_order_on_step3_miss(self):
        client = _make_option_client_with_stock()
        self._run_sell_all_unfilled(client)
        price_types = [c.kwargs["price_type"] for c in client.place_option_order.call_args_list]
        assert "MARKET" not in price_types

    def test_sell_step3_limit_is_cancelled_on_miss(self):
        client = _make_option_client_with_stock()
        call_order = []
        client.cancel_order.side_effect = lambda oid: call_order.append(("cancel", oid))
        client.place_option_order.side_effect = lambda **kw: call_order.append(
            ("place", kw.get("price_type"))
        ) or {"order_id": "ord-001", "status": "open"}

        self._run_sell_all_unfilled(client)

        # Step3 limit must be cancelled; no market order placed after
        assert any(event[0] == "cancel" for event in call_order)
        assert call_order[-1][0] == "cancel"

    def test_buy_does_not_place_market_order_on_step3_miss(self):
        client = _make_option_client_with_stock()
        self._run_buy_all_unfilled(client)
        price_types = [c.kwargs["price_type"] for c in client.place_option_order.call_args_list]
        assert "MARKET" not in price_types


def _make_stock_client(bid=329.0, ask=330.0, order_status="open"):
    client = MagicMock()
    client.get_stock_quote.return_value = {
        "QuoteResponse": {
            "QuoteData": [{"All": {"bid": bid, "ask": ask, "lastTrade": bid}}]
        }
    }
    client.place_stock_order.return_value = {"order_id": "stock-ord-001", "status": order_status}
    client.order_status.return_value = {"status": order_status}
    return client


class TestPlaceStockOrderAskZeroGuard:
    """
    When ask=0 is returned by the broker for a buy order, place_stock_order()
    must fall back to a market order rather than submitting a $0 limit price.
    """

    def test_ask_zero_on_buy_falls_back_to_market_order(self):
        client = _make_stock_client(bid=329.0, ask=0.0)
        with patch(f"{_MODULE}.time.sleep", lambda _: None):
            place_stock_order(client=client, ticker="FN", shares=1, order_action="BUY_OPEN")

        calls = client.place_stock_order.call_args_list
        assert calls[-1].kwargs["order_type"] == "MARKET"

    def test_ask_zero_on_buy_does_not_submit_zero_limit_price(self):
        client = _make_stock_client(bid=329.0, ask=0.0)
        with patch(f"{_MODULE}.time.sleep", lambda _: None):
            place_stock_order(client=client, ticker="FN", shares=1, order_action="BUY_OPEN")

        for call in client.place_stock_order.call_args_list:
            if call.kwargs.get("order_type") == "LIMIT":
                assert call.kwargs["limit_price"] > 0, "limit price must never be 0"

    def test_bid_zero_on_sell_falls_back_to_market_order(self):
        client = _make_stock_client(bid=0.0, ask=330.0)
        with patch(f"{_MODULE}.time.sleep", lambda _: None):
            place_stock_order(client=client, ticker="FN", shares=1, order_action="SELL_CLOSE")

        calls = client.place_stock_order.call_args_list
        assert calls[-1].kwargs["order_type"] == "MARKET"

    def test_normal_quote_places_limit_first(self):
        client = _make_stock_client(bid=329.0, ask=331.0)
        with patch(f"{_MODULE}.time.sleep", lambda _: None):
            place_stock_order(client=client, ticker="FN", shares=1, order_action="BUY_OPEN")

        first_call = client.place_stock_order.call_args_list[0]
        assert first_call.kwargs["order_type"] == "LIMIT"
        assert first_call.kwargs["limit_price"] == 330.0


class TestPlaceStockOrderStaleQuoteGuard:
    """
    When bid/ask spread exceeds 3% of mid, the quote is considered stale.
    With signal_price provided the limit should be anchored at signal_price.
    Without signal_price the order must fall back to market.
    """

    # RH real-world case: bid=120.64 ask=132.99 on a ~$126 stock → spread ≈ 9.7%
    _STALE_BID = 120.64
    _STALE_ASK = 132.99
    _SIGNAL_PRICE = 126.50

    def test_stale_quote_with_signal_price_anchors_limit_at_signal_price(self):
        client = _make_stock_client(bid=self._STALE_BID, ask=self._STALE_ASK)
        with patch(f"{_MODULE}.time.sleep", lambda _: None):
            place_stock_order(
                client=client,
                ticker="RH",
                shares=1,
                order_action="BUY_OPEN",
                signal_price=self._SIGNAL_PRICE,
            )

        first_call = client.place_stock_order.call_args_list[0]
        assert first_call.kwargs["order_type"] == "LIMIT"
        assert first_call.kwargs["limit_price"] == self._SIGNAL_PRICE

    def test_stale_quote_without_signal_price_falls_back_to_market(self):
        client = _make_stock_client(bid=self._STALE_BID, ask=self._STALE_ASK)
        with patch(f"{_MODULE}.time.sleep", lambda _: None):
            place_stock_order(
                client=client,
                ticker="RH",
                shares=1,
                order_action="BUY_OPEN",
                signal_price=None,
            )

        calls = client.place_stock_order.call_args_list
        assert calls[-1].kwargs["order_type"] == "MARKET"

    def test_tight_spread_quote_is_not_flagged_as_stale(self):
        client = _make_stock_client(bid=125.95, ask=126.05)
        with patch(f"{_MODULE}.time.sleep", lambda _: None):
            place_stock_order(
                client=client,
                ticker="RH",
                shares=1,
                order_action="BUY_OPEN",
                signal_price=self._SIGNAL_PRICE,
            )

        first_call = client.place_stock_order.call_args_list[0]
        assert first_call.kwargs["order_type"] == "LIMIT"
        # mid of tight quote used, not signal_price
        assert first_call.kwargs["limit_price"] == 126.0

    def test_stale_quote_sell_without_signal_price_falls_back_to_market(self):
        client = _make_stock_client(bid=self._STALE_BID, ask=self._STALE_ASK)
        with patch(f"{_MODULE}.time.sleep", lambda _: None):
            place_stock_order(
                client=client,
                ticker="RH",
                shares=1,
                order_action="SELL_CLOSE",
                signal_price=None,
            )

        calls = client.place_stock_order.call_args_list
        assert calls[-1].kwargs["order_type"] == "MARKET"


class TestPlaceStockOrderStep1Loop:
    """
    Step 1 retries up to 3 times at mid price (5s each) before escalating
    to step 2.
    """

    def _run(self, client, order_action="BUY_OPEN", filled_on_step1_attempt=None):
        attempt_count = [0]

        def fake_order_status(order_id):
            attempt_count[0] += 1
            if filled_on_step1_attempt is not None and attempt_count[0] == filled_on_step1_attempt:
                return {"status": "filled"}
            return {"status": "open"}

        client.order_status.side_effect = fake_order_status
        with patch(f"{_MODULE}.time.sleep", lambda _: None):
            return place_stock_order(
                client=client,
                ticker="FN",
                shares=1,
                order_action=order_action,
            )

    def test_step1_fills_on_first_attempt_returns_without_escalating(self):
        client = _make_stock_client(bid=329.0, ask=331.0)
        self._run(client, filled_on_step1_attempt=1)
        calls = client.place_stock_order.call_args_list
        assert len(calls) == 1
        assert calls[0].kwargs["order_type"] == "LIMIT"
        assert calls[0].kwargs["limit_price"] == 330.0

    def test_step1_fills_on_second_attempt_returns_without_escalating(self):
        client = _make_stock_client(bid=329.0, ask=331.0)
        self._run(client, filled_on_step1_attempt=2)
        limit_calls = [c for c in client.place_stock_order.call_args_list if c.kwargs["order_type"] == "LIMIT"]
        assert len(limit_calls) == 2
        assert all(c.kwargs["limit_price"] == 330.0 for c in limit_calls)

    def test_step1_fills_on_third_attempt_returns_without_escalating(self):
        client = _make_stock_client(bid=329.0, ask=331.0)
        self._run(client, filled_on_step1_attempt=3)
        limit_calls = [c for c in client.place_stock_order.call_args_list if c.kwargs["order_type"] == "LIMIT"]
        assert len(limit_calls) == 3
        assert all(c.kwargs["limit_price"] == 330.0 for c in limit_calls)

    def test_step1_all_attempts_exhausted_escalates_to_step2(self):
        client = _make_stock_client(bid=329.0, ask=331.0)
        self._run(client, filled_on_step1_attempt=None)
        # step1(3) + step2(3) + step3 market(1) = 7 total orders
        assert client.place_stock_order.call_count == 7

    def test_step1_quote_fetch_failure_falls_back_to_market_immediately(self):
        client = _make_stock_client(bid=329.0, ask=331.0)
        client.get_stock_quote.side_effect = RuntimeError("quote unavailable")
        client.order_status.return_value = {"status": "open"}
        with patch(f"{_MODULE}.time.sleep", lambda _: None):
            place_stock_order(client=client, ticker="FN", shares=1, order_action="BUY_OPEN")

        last_call = client.place_stock_order.call_args_list[-1]
        assert last_call.kwargs["order_type"] == "MARKET"


class TestPlaceStockOrderStep2Loop:
    """
    Step 2 retries up to 3 times at ask (buy) / bid (sell) before falling
    back to a market order at step 3.
    """

    def _run(self, client, order_action="BUY_OPEN", signal_price=None, filled_on_attempt=None):
        # step 1 always unfilled (first 3 status checks), step 2 fills on given attempt
        attempt_count = [0]

        def fake_order_status(order_id):
            attempt_count[0] += 1
            step2_attempt = attempt_count[0] - 3  # step 2 starts after 3 step1 checks
            if filled_on_attempt is not None and step2_attempt == filled_on_attempt:
                return {"status": "filled"}
            return {"status": "open"}

        client.order_status.side_effect = fake_order_status
        with patch(f"{_MODULE}.time.sleep", lambda _: None):
            return place_stock_order(
                client=client,
                ticker="FN",
                shares=1,
                order_action=order_action,
                signal_price=signal_price,
            )

    def test_step2_all_attempts_exhausted_falls_back_to_market(self):
        client = _make_stock_client(bid=329.0, ask=331.0)
        self._run(client, filled_on_attempt=None)
        last_call = client.place_stock_order.call_args_list[-1]
        assert last_call.kwargs["order_type"] == "MARKET"

    def test_step2_all_attempts_exhausted_places_exactly_seven_orders(self):
        # step1(3) + step2(3) + step3 market(1) = 7
        client = _make_stock_client(bid=329.0, ask=331.0)
        self._run(client, filled_on_attempt=None)
        assert client.place_stock_order.call_count == 7

    def test_step2_fills_on_first_attempt_returns_without_market(self):
        client = _make_stock_client(bid=329.0, ask=331.0)
        self._run(client, filled_on_attempt=1)
        calls = client.place_stock_order.call_args_list
        assert all(c.kwargs["order_type"] == "LIMIT" for c in calls)

    def test_step2_fills_on_second_attempt_returns_without_market(self):
        client = _make_stock_client(bid=329.0, ask=331.0)
        self._run(client, filled_on_attempt=2)
        calls = client.place_stock_order.call_args_list
        assert all(c.kwargs["order_type"] == "LIMIT" for c in calls)

    def test_step2_fills_on_third_attempt_returns_without_market(self):
        client = _make_stock_client(bid=329.0, ask=331.0)
        self._run(client, filled_on_attempt=3)
        calls = client.place_stock_order.call_args_list
        assert all(c.kwargs["order_type"] == "LIMIT" for c in calls)

    def test_step2_buy_limit_price_is_ask(self):
        client = _make_stock_client(bid=329.0, ask=331.0)
        self._run(client, order_action="BUY_OPEN", filled_on_attempt=None)
        step2_calls = client.place_stock_order.call_args_list[3:6]
        for call in step2_calls:
            assert call.kwargs["order_type"] == "LIMIT"
            assert call.kwargs["limit_price"] == 331.0

    def test_step2_sell_limit_price_is_bid(self):
        client = _make_stock_client(bid=329.0, ask=331.0)
        self._run(client, order_action="SELL_CLOSE", filled_on_attempt=None)
        step2_calls = client.place_stock_order.call_args_list[3:6]
        for call in step2_calls:
            assert call.kwargs["order_type"] == "LIMIT"
            assert call.kwargs["limit_price"] == 329.0

    def test_step2_quote_fetch_failure_falls_back_to_market_immediately(self):
        client = _make_stock_client(bid=329.0, ask=331.0)
        call_count = [0]

        def quote_side_effect(symbol, **kwargs):
            call_count[0] += 1
            if call_count[0] > 3:  # step 1 uses 3 quotes; fail on step 2's first fetch
                raise RuntimeError("quote unavailable")
            return {
                "QuoteResponse": {
                    "QuoteData": [{"All": {"bid": 329.0, "ask": 331.0, "lastTrade": 329.0}}]
                }
            }

        client.get_stock_quote.side_effect = quote_side_effect
        client.order_status.return_value = {"status": "open"}
        with patch(f"{_MODULE}.time.sleep", lambda _: None):
            place_stock_order(client=client, ticker="FN", shares=1, order_action="BUY_OPEN")

        last_call = client.place_stock_order.call_args_list[-1]
        assert last_call.kwargs["order_type"] == "MARKET"


class TestPlaceStockOrderFeedForwarding:
    """
    When a feed is provided to place_stock_order(), it must be forwarded to
    get_stock_quote() so the quote uses IEX (or whichever feed is configured)
    rather than defaulting to SIP.
    """

    def test_feed_forwarded_to_get_stock_quote(self):
        from alpaca.data.enums import DataFeed
        client = _make_stock_client(bid=329.0, ask=331.0, order_status="filled")
        client.order_status.return_value = {"status": "filled"}
        with patch(f"{_MODULE}.time.sleep", lambda _: None):
            place_stock_order(
                client=client,
                ticker="FN",
                shares=1,
                order_action="BUY_OPEN",
                feed=DataFeed.IEX,
            )
        client.get_stock_quote.assert_called_with("FN", feed=DataFeed.IEX)

    def test_no_feed_calls_get_stock_quote_without_feed_kwarg(self):
        client = _make_stock_client(bid=329.0, ask=331.0, order_status="filled")
        client.order_status.return_value = {"status": "filled"}
        with patch(f"{_MODULE}.time.sleep", lambda _: None):
            place_stock_order(
                client=client,
                ticker="FN",
                shares=1,
                order_action="BUY_OPEN",
            )
        client.get_stock_quote.assert_called_with("FN")


class TestFillStatusUnknownDoesNotCancelOrder:
    """
    Fix 1: when order_status() raises an exception, _is_filled() returns None.
    The escalation must not cancel the order (it may already be filled) and must
    return immediately rather than escalating to the next step.
    """

    def test_option_status_error_does_not_cancel(self):
        client = _make_client()
        client.order_status.side_effect = RuntimeError("broker API error")
        with patch(f"{_MODULE}.time.sleep", lambda _: None):
            result = _place_with_fill_escalation(
                client=client,
                ticker=_TICKER,
                option_symbol=_SYMBOL,
                option_type=_OPTION_TYPE,
                contracts=_CONTRACTS,
                order_action=_SELL,
            )
        assert client.cancel_order.call_count == 0
        assert result.get("order_id") == "ord-001"

    def test_option_status_error_returns_after_first_step_without_escalating(self):
        client = _make_client()
        client.order_status.side_effect = RuntimeError("broker API error")
        with patch(f"{_MODULE}.time.sleep", lambda _: None):
            _place_with_fill_escalation(
                client=client,
                ticker=_TICKER,
                option_symbol=_SYMBOL,
                option_type=_OPTION_TYPE,
                contracts=_CONTRACTS,
                order_action=_SELL,
            )
        # Only step1 should be attempted; status error causes immediate return
        assert client.place_option_order.call_count == 1

    def test_option_step3_status_error_does_not_place_market_order(self):
        client = _make_client()
        call_count = [0]

        def order_status_side_effect(order_id):
            call_count[0] += 1
            if call_count[0] < 3:
                return {"status": "open"}
            raise RuntimeError("API timeout at step3")

        client.order_status.side_effect = order_status_side_effect
        with patch(f"{_MODULE}.time.sleep", lambda _: None):
            result = _place_with_fill_escalation(
                client=client,
                ticker=_TICKER,
                option_symbol=_SYMBOL,
                option_type=_OPTION_TYPE,
                contracts=_CONTRACTS,
                order_action=_SELL,
            )
        market_calls = [
            c for c in client.place_option_order.call_args_list
            if c.kwargs.get("price_type") == "MARKET"
        ]
        assert len(market_calls) == 0
        assert result.get("order_id") == "ord-001"

    def test_stock_status_error_does_not_cancel(self):
        client = _make_stock_client()
        client.order_status.side_effect = RuntimeError("broker API error")
        with patch(f"{_MODULE}.time.sleep", lambda _: None):
            place_stock_order(client=client, ticker="FN", shares=1, order_action="BUY_OPEN")
        assert client.cancel_order.call_count == 0

    def test_stock_status_error_returns_after_first_step(self):
        client = _make_stock_client()
        client.order_status.side_effect = RuntimeError("broker API error")
        with patch(f"{_MODULE}.time.sleep", lambda _: None):
            result = place_stock_order(
                client=client, ticker="FN", shares=1, order_action="BUY_OPEN"
            )
        assert client.place_stock_order.call_count == 1
        assert result.get("order_id") == "stock-ord-001"


class TestStep3StaleQuoteFallback:
    """
    Fix 4: when the step-3 quote fetch fails, the escalation uses the last
    successfully fetched bid/ask (stored in _last_known_quote) rather than
    leaked Python locals which may be stale from an earlier step.
    """

    def test_step3_buy_uses_last_known_ask_when_quote_fails(self):
        client = _make_client(bid=4.90, ask=5.10)
        quote_call_count = [0]

        def quote_side_effect(symbol):
            quote_call_count[0] += 1
            if quote_call_count[0] <= 2:
                return {"bid": 4.90, "ask": 5.10, "mid": 5.00}
            raise RuntimeError("quote unavailable at step3")

        client.get_option_quote_by_occ.side_effect = quote_side_effect
        client.order_status.return_value = {"status": "open"}
        with patch(f"{_MODULE}.time.sleep", lambda _: None):
            _place_with_fill_escalation(
                client=client,
                ticker=_TICKER,
                option_symbol=_SYMBOL,
                option_type=_OPTION_TYPE,
                contracts=_CONTRACTS,
                order_action="BUY_OPEN",
            )
        # step1(mid=5.00), step2(5.05), step3(last_known_ask=5.10)
        step3_call = client.place_option_order.call_args_list[2]
        assert step3_call.kwargs["price_type"] == "LIMIT"
        assert step3_call.kwargs["price"] == 5.10

    def test_step3_sell_uses_last_known_bid_when_quote_fails(self):
        client = _make_option_client_with_stock(
            opt_bid=4.90, opt_ask=5.10, stock_bid=270.0, stock_ask=270.0
        )
        quote_call_count = [0]

        def quote_side_effect(symbol):
            quote_call_count[0] += 1
            if quote_call_count[0] <= 2:
                return {"bid": 4.90, "ask": 5.10, "mid": 5.00}
            raise RuntimeError("quote unavailable at step3")

        client.get_option_quote_by_occ.side_effect = quote_side_effect
        client.order_status.return_value = {"status": "open"}
        with patch(f"{_MODULE}.time.sleep", lambda _: None):
            _place_with_fill_escalation(
                client=client,
                ticker=_PUT_TICKER,
                option_symbol=_PUT_SYMBOL,
                option_type=_PUT_TYPE,
                contracts=_CONTRACTS,
                order_action="SELL_CLOSE",
                feed=None,
            )
        # step1(mid=5.00), step2(4.95), step3(last_known_bid=4.90)
        step3_call = client.place_option_order.call_args_list[2]
        assert step3_call.kwargs["price_type"] == "LIMIT"
        assert step3_call.kwargs["price"] == 4.90


class TestStep3TickRejection:
    """
    When the step3 limit is rejected with a tick-increment error, the escalation
    re-quantizes the price to the required tick and retries once. A non-tick
    rejection (e.g. buying power) must not trigger the retry.
    """

    _TICK_REJECT = (
        "Price = 5.10000000 not rounded to a valid price increment [ 0.1 ]"
    )

    def _run_buy_loop_fails_immediately(self, client):
        """Force the loop to skip straight to step3 by making the first quote fetch raise."""
        quote_calls = [0]
        original = client.get_option_quote_by_occ.side_effect

        def quote_side_effect(symbol):
            quote_calls[0] += 1
            if quote_calls[0] == 1:
                raise RuntimeError("quote unavailable in loop")
            return {"bid": 4.90, "ask": 5.10, "mid": 5.00}

        client.get_option_quote_by_occ.side_effect = quote_side_effect
        with patch(f"{_MODULE}.time.sleep", lambda _: None):
            return _place_with_fill_escalation(
                client=client,
                ticker=_TICKER,
                option_symbol=_SYMBOL,
                option_type=_OPTION_TYPE,
                contracts=_CONTRACTS,
                order_action="BUY_OPEN",
            )

    def test_tick_rejection_triggers_step3_retry(self):
        client = _make_client()
        client.order_status.side_effect = [
            {"status": "open", "reject_reason": self._TICK_REJECT},
            {"status": "filled"},
        ]
        self._run_buy_loop_fails_immediately(client)
        assert client.place_option_order.call_count == 2

    def test_tick_retry_places_limit_order(self):
        client = _make_client()
        client.order_status.side_effect = [
            {"status": "open", "reject_reason": self._TICK_REJECT},
            {"status": "filled"},
        ]
        self._run_buy_loop_fails_immediately(client)
        retry_call = client.place_option_order.call_args_list[1]
        assert retry_call.kwargs["price_type"] == "LIMIT"

    def test_tick_retry_fills_and_returns(self):
        client = _make_client()
        client.order_status.side_effect = [
            {"status": "open", "reject_reason": self._TICK_REJECT},
            {"status": "filled"},
        ]
        result = self._run_buy_loop_fails_immediately(client)
        assert result.get("order_id") == "ord-001"

    def test_non_tick_rejection_does_not_retry(self):
        client = _make_client()
        client.order_status.return_value = {
            "status": "open",
            "reject_reason": "Insufficient buying power",
        }
        self._run_buy_loop_fails_immediately(client)
        assert client.place_option_order.call_count == 1


class TestCrossedQuoteGuard:
    """
    When bid >= ask (crossed or flat market), the loop must not place any order
    with an invalid spread. Instead it polls up to 15s (3 × 5s) for the quote
    to normalize, then:
      - Proceeds normally if it normalizes within 15s.
      - Breaks to step3 if still crossed after 15s.
    """

    def _run(self, client, order_action="BUY_OPEN"):
        sleeps = []
        with patch(f"{_MODULE}.time.sleep", side_effect=lambda t: sleeps.append(t)):
            result = _place_with_fill_escalation(
                client=client,
                ticker=_TICKER,
                option_symbol=_SYMBOL,
                option_type=_OPTION_TYPE,
                contracts=_CONTRACTS,
                order_action=order_action,
            )
        return result, sleeps

    def test_crossed_quote_normalizes_on_first_retry_proceeds_normally(self):
        client = MagicMock()
        client.get_option_quote_by_occ.side_effect = [
            {"bid": 5.10, "ask": 5.00, "mid": 5.05},  # crossed
            {"bid": 4.90, "ask": 5.10, "mid": 5.00},  # normalized (retry 1)
        ]
        client.place_option_order.return_value = {"order_id": "ord-001"}
        client.order_status.return_value = {"status": "filled"}

        result, _ = self._run(client)
        assert result.get("order_id") == "ord-001"
        assert client.place_option_order.call_count == 1

    def test_crossed_quote_no_order_placed_during_wait(self):
        client = MagicMock()
        client.get_option_quote_by_occ.side_effect = [
            {"bid": 5.10, "ask": 5.00, "mid": 5.05},  # crossed
            {"bid": 4.90, "ask": 5.10, "mid": 5.00},  # normalized (retry 1)
        ]
        client.place_option_order.return_value = {"order_id": "ord-001"}
        client.order_status.return_value = {"status": "filled"}

        _, sleeps = self._run(client)
        # The first sleep must be the 5s retry poll, not an order wait
        assert sleeps[0] == 5

    def test_crossed_quote_times_out_falls_to_step3(self):
        client = MagicMock()
        crossed = {"bid": 5.10, "ask": 5.00, "mid": 5.05}
        normal = {"bid": 4.90, "ask": 5.10, "mid": 5.00}
        client.get_option_quote_by_occ.side_effect = [
            crossed,   # initial — crossed
            crossed,   # retry 1 — still crossed
            crossed,   # retry 2 — still crossed
            crossed,   # retry 3 — still crossed → timeout → break to step3
            normal,    # step3 quote fetch
        ]
        client.place_option_order.return_value = {"order_id": "ord-001"}
        client.order_status.return_value = {"status": "open"}

        result, sleeps = self._run(client)
        # Exactly one limit order placed (step3 at ask)
        assert client.place_option_order.call_count == 1
        # Three 5s retry polls before giving up
        assert sleeps[:3] == [5, 5, 5]

    def test_crossed_quote_normalizes_on_third_retry(self):
        client = MagicMock()
        crossed = {"bid": 5.10, "ask": 5.00, "mid": 5.05}
        normal = {"bid": 4.90, "ask": 5.10, "mid": 5.00}
        client.get_option_quote_by_occ.side_effect = [
            crossed,   # initial — crossed
            crossed,   # retry 1
            crossed,   # retry 2
            normal,    # retry 3 — normalized → proceed with loop
        ]
        client.place_option_order.return_value = {"order_id": "ord-001"}
        client.order_status.return_value = {"status": "filled"}

        result, sleeps = self._run(client)
        assert result.get("order_id") == "ord-001"
        # Three 5s retry polls then one order wait
        assert sleeps[:3] == [5, 5, 5]
        assert len(sleeps) == 4  # 3 retries + 1 order wait

    def test_crossed_quote_retry_fetch_fails_then_normalizes(self):
        client = MagicMock()
        normal = {"bid": 4.90, "ask": 5.10, "mid": 5.00}
        client.get_option_quote_by_occ.side_effect = [
            {"bid": 5.10, "ask": 5.00, "mid": 5.05},  # initial — crossed
            RuntimeError("feed timeout"),               # retry 1 — fails
            normal,                                     # retry 2 — normalized
        ]
        client.place_option_order.return_value = {"order_id": "ord-001"}
        client.order_status.return_value = {"status": "filled"}

        result, _ = self._run(client)
        assert result.get("order_id") == "ord-001"
        assert client.place_option_order.call_count == 1

    def test_flat_quote_bid_equals_ask_also_waits(self):
        # bid == ask → half_spread == 0 → same crossed-quote path
        client = MagicMock()
        client.get_option_quote_by_occ.side_effect = [
            {"bid": 5.00, "ask": 5.00, "mid": 5.00},  # flat
            {"bid": 4.90, "ask": 5.10, "mid": 5.00},  # normalized
        ]
        client.place_option_order.return_value = {"order_id": "ord-001"}
        client.order_status.return_value = {"status": "filled"}

        result, sleeps = self._run(client)
        assert result.get("order_id") == "ord-001"
        assert sleeps[0] == 5  # crossed-quote retry poll


class TestAdaptiveWait:
    """
    Loop wait scales 3–10s based on how far current_price is from the limit:
      BUY:  more patience near mid (far from ask), less patience near ask.
      SELL: more patience near mid (far from bid/floor), less patience near floor.

    At the very first step, current_price = mid, so distance-to-limit = half_spread
    and ratio = 1.0 → maximum wait = 10s.
    As the price escalates (BUY) or descends (SELL) toward the limit, ratio → 0 → 3s.
    """

    def _capture_sleeps(self, client, order_action, get_fair_price_fn=None):
        sleeps = []
        with patch(f"{_MODULE}.time.sleep", side_effect=lambda t: sleeps.append(t)):
            _place_with_fill_escalation(
                client=client,
                ticker=_TICKER,
                option_symbol=_SYMBOL,
                option_type=_OPTION_TYPE,
                contracts=_CONTRACTS,
                order_action=order_action,
                get_fair_price_fn=get_fair_price_fn,
            )
        return sleeps

    def test_buy_first_sleep_is_max_when_starting_at_mid(self):
        # bid=4.90, ask=5.10, half_spread=0.10
        # start=mid=5.00; ratio=(5.10-5.00)/0.10=1.0 → wait=10s
        client = _make_client(bid=4.90, ask=5.10)
        client.order_status.side_effect = [{"status": "filled"}]
        sleeps = self._capture_sleeps(client, "BUY_OPEN")
        assert sleeps[0] == 10

    def test_buy_sleeps_decrease_monotonically_toward_ask(self):
        # Wide spread bid=4.00 ask=8.00: price escalates from mid=6.00 to ask over ~11 steps.
        # Each successive loop wait must be ≤ the previous.
        client = MagicMock()
        client.get_option_quote_by_occ.return_value = {"bid": 4.00, "ask": 8.00, "mid": 6.00}
        client.place_option_order.return_value = {"order_id": "ord-001"}
        client.order_status.return_value = {"status": "open"}

        sleeps = self._capture_sleeps(client, "BUY_OPEN")
        # Exclude step3 sleep (30s for buy)
        loop_sleeps = [s for s in sleeps if s != 30]
        assert loop_sleeps[0] == 10
        assert loop_sleeps[-1] == 3
        assert loop_sleeps == sorted(loop_sleeps, reverse=True)

    def test_sell_first_sleep_is_max_when_starting_at_mid(self):
        # bid=4.90, ask=5.10, half_spread=0.10
        # start=mid=5.00; ratio=(5.00-4.90)/0.10=1.0 → wait=10s
        client = _make_client(bid=4.90, ask=5.10)
        client.order_status.side_effect = [{"status": "filled"}]
        sleeps = self._capture_sleeps(client, "SELL_CLOSE")
        assert sleeps[0] == 10

    def test_sell_sleeps_decrease_monotonically_toward_floor(self):
        # Wide spread bid=4.00 ask=8.00: price descends from mid=6.00 to floor=bid over ~11 steps.
        client = MagicMock()
        client.get_option_quote_by_occ.return_value = {"bid": 4.00, "ask": 8.00, "mid": 6.00}
        client.place_option_order.return_value = {"order_id": "ord-001"}
        client.order_status.return_value = {"status": "open"}

        sleeps = self._capture_sleeps(client, "SELL_CLOSE")
        # Exclude step3 sleep (60s for sell)
        loop_sleeps = [s for s in sleeps if s != 60]
        assert loop_sleeps[0] == 10
        assert loop_sleeps[-1] == 3
        assert loop_sleeps == sorted(loop_sleeps, reverse=True)


class TestEscalationScenarios:
    """
    End-to-end scenario tests covering real-world market conditions.
    Each test encodes the expected escalation behavior as a regression
    baseline so future changes to the escalation logic can be validated.

    Scenarios:
      1. Rapidly rising stock — BUY re-anchor tracks the market in one step
      2. Rapidly falling stock — SELL re-anchor snaps down in one step
      3. Liquid option (tight $0.05 spread) — quantization stalls at mid for several iters
      4. Illiquid option BUY — full 12-step escalation with decaying adaptive wait
      5. Illiquid option SELL — fair_price floor terminates loop after 2 iters
      6. Stale quotes (unchanged bid/ask) — prices still escalate via internal state
      7. Quote fetch always fails — MISS with no orders placed
    """

    def _run(self, client, order_action, get_fair_price_fn=None):
        """Run escalation and return (result, placed_prices, sleep_values)."""
        placed = []

        def capture_place(**kw):
            placed.append(kw.get("price"))
            return {"order_id": "ord-001"}

        client.place_option_order.side_effect = capture_place
        sleeps = []
        with patch(f"{_MODULE}.time.sleep", side_effect=lambda t: sleeps.append(t)):
            result = _place_with_fill_escalation(
                client=client,
                ticker=_TICKER,
                option_symbol=_SYMBOL,
                option_type=_OPTION_TYPE,
                contracts=_CONTRACTS,
                order_action=order_action,
                get_fair_price_fn=get_fair_price_fn,
            )
        return result, placed, sleeps

    # -----------------------------------------------------------------------
    # Scenario 1 — Rapidly rising stock, BUY
    # -----------------------------------------------------------------------

    def test_rapidly_rising_stock_buy_reanchors_to_new_market(self):
        """
        When the underlying rips $5 between iterations the BUY re-anchor jumps
        current_price to min(new_fair, new_mid) before incrementing, tracking
        the market in a single step.

        Without re-anchor iter 2 would only advance by ~$0.25 (one slow increment),
        placing far below the new mid at $7.50.

        iter 1: bid=5.00 ask=7.00 fair=5.80 → places at min(5.80, 6.00) = 5.80
        iter 2: bid=6.50 ask=8.50 fair=7.20 → re-anchors to 7.20, +0.25 fast → 7.45
        """
        client = MagicMock()
        client.get_option_quote_by_occ.side_effect = [
            {"bid": 5.00, "ask": 7.00, "mid": 6.00},
            {"bid": 6.50, "ask": 8.50, "mid": 7.50},
        ]
        client.order_status.side_effect = [
            {"status": "open"},
            {"status": "filled"},
        ]
        fair_calls = [0]
        def fair_fn():
            fair_calls[0] += 1
            return _D("5.80") if fair_calls[0] == 1 else _D("7.20")

        _, placed, _ = self._run(client, "BUY_OPEN", get_fair_price_fn=fair_fn)

        assert placed[0] == pytest.approx(5.80)   # initial: min(fair=5.80, mid=6.00)
        assert placed[1] == pytest.approx(7.45)   # re-anchored to 7.20, then +0.25 fast
        # Jump is $1.65, not the $0.25 a non-re-anchored step would give
        assert placed[1] - placed[0] > 1.0

    # -----------------------------------------------------------------------
    # Scenario 2 — Rapidly falling stock, SELL
    # -----------------------------------------------------------------------

    def test_rapidly_falling_stock_sell_reanchors_to_new_market(self):
        """
        When the underlying drops $4 between iterations the SELL re-anchor
        snaps current_price to max(new_fair, new_mid), tracking the market in
        a single step.

        Without re-anchor iter 2 would only fall by ~$0.10, placing at ~$5.90
        while the new mid is already $4.50.

        iter 1: bid=5.00 ask=7.00 fair=5.50 → places at max(5.50, 6.00)=6.00
                sell_floor=max(5.00, 5.50)=5.50; 6.00>5.50 → loop continues
        iter 2: bid=3.50 ask=5.50 fair=3.80 → re-anchors to max(3.80, 4.50)=4.50,
                -0.10 slow decrement → max(4.40, floor=3.80) = 4.40; fills.

        Note: fair must be < mid on iter 1 so sell_floor < current_price and
        the loop doesn't exit immediately after the first order.
        """
        client = MagicMock()
        client.get_option_quote_by_occ.side_effect = [
            {"bid": 5.00, "ask": 7.00, "mid": 6.00},
            {"bid": 3.50, "ask": 5.50, "mid": 4.50},
        ]
        client.order_status.side_effect = [
            {"status": "open"},
            {"status": "filled"},
        ]
        fair_calls = [0]
        def fair_fn():
            fair_calls[0] += 1
            return _D("5.50") if fair_calls[0] == 1 else _D("3.80")

        _, placed, _ = self._run(client, "SELL_CLOSE", get_fair_price_fn=fair_fn)

        assert placed[0] == pytest.approx(6.00)   # initial: max(fair=5.50, mid=6.00) = 6.00
        assert placed[1] == pytest.approx(4.40)   # re-anchored to 4.50, then -0.10 slow
        # Drop is $1.60, not the $0.10 a non-re-anchored step would give
        assert placed[0] - placed[1] > 1.0

    # -----------------------------------------------------------------------
    # Scenario 3 — Liquid option, tight $0.05 spread (BUY)
    # -----------------------------------------------------------------------

    def test_liquid_option_buy_quantization_stalls_at_mid_before_tick_jump(self):
        """
        When half_spread == one tick ($0.05), the slow increment (0.10 × $0.05 = $0.005)
        is sub-tick. The unquantized current_price creeps up but the placed (quantized)
        price stays at mid=$5.05 for 5 iterations, then jumps directly to $5.10 once
        the unquantized value crosses the $0.075 ROUND_HALF_UP boundary.

        This leaves a gap: no price between $5.05 and $5.10 is ever tried.
        In practice liquid mid-price limits fill almost immediately so this
        is mostly harmless, but the pattern is documented here as a known baseline.

        bid=5.00 ask=5.10 mid=5.05 half_spread=0.05, penny_pilot=True:
          iters 1–5 : unquantized 5.055→5.070 → quantize down → placed at 5.05
          iters 6–11: unquantized 5.075→5.10  → quantize up  → placed at 5.10
          iter 11 : current_price=5.10 >= ask → break
        """
        client = MagicMock()
        client.get_option_quote_by_occ.return_value = {"bid": 5.00, "ask": 5.10, "mid": 5.05}
        client.order_status.return_value = {"status": "open"}

        _, placed, _ = self._run(client, "BUY_OPEN")

        loop_prices = placed[:-1]   # last entry is step3 order at ask

        # First 5 loop orders stall at mid due to sub-tick increment
        assert all(p == pytest.approx(5.05) for p in loop_prices[:5])
        # Remaining loop orders jump one full tick to ask
        assert all(p == pytest.approx(5.10) for p in loop_prices[5:])
        # No intermediate price is ever placed
        assert not any(5.05 < p < 5.10 for p in loop_prices)

    # -----------------------------------------------------------------------
    # Scenario 4 — Illiquid option BUY, full escalation with adaptive wait
    # -----------------------------------------------------------------------

    def test_illiquid_option_buy_full_escalation_sequence_and_adaptive_wait(self):
        """
        With a $6 wide spread (bid=3, ask=9, mid=6, fair=5.50):
        - Iteration 1 starts at fair=5.50 (below mid); +0.75 fast increment → 6.25.
        - Iterations 2–11 use $0.30 slow increments from 6.25 → 9.00.
        - Adaptive wait decays from 10s (near fair) to 3s (near ask).
        - 12 loop orders total before current_price reaches ask and step3 takes over.

        bid=3.00 ask=9.00 mid=6.00 half_spread=3.00 fair=5.50:
          placed: [5.50, 6.25, 6.55, 6.85, 7.15, 7.45, 7.75, 8.05, 8.35, 8.65, 8.95, 9.00]
          waits:  [10,   9,    9,    8,    7,    7,    6,    5,    5,    4,    3,    3   ]
        """
        client = MagicMock()
        client.get_option_quote_by_occ.return_value = {"bid": 3.00, "ask": 9.00, "mid": 6.00}
        client.order_status.return_value = {"status": "open"}

        _, placed, sleeps = self._run(client, "BUY_OPEN", get_fair_price_fn=lambda: _D("5.50"))

        loop_prices = placed[:-1]
        expected = [5.50, 6.25, 6.55, 6.85, 7.15, 7.45, 7.75, 8.05, 8.35, 8.65, 8.95, 9.00]
        assert loop_prices == [pytest.approx(e) for e in expected]

        loop_sleeps = [s for s in sleeps if s != 30]   # exclude step3 wait
        assert loop_sleeps == [10, 9, 9, 8, 7, 7, 6, 5, 5, 4, 3, 3]

    # -----------------------------------------------------------------------
    # Scenario 5 — Illiquid option SELL, fair_price floor
    # -----------------------------------------------------------------------

    def test_illiquid_option_sell_fair_price_floor_limits_loop_to_two_orders(self):
        """
        With a $6 wide spread and fair_price=5.80, sell_floor=max(bid=3, fair=5.80)=5.80.
        The $0.30 slow decrement overshoots below fair in one step:
          iter 1: places at max(fair=5.80, mid=6.00) = 6.00; decrement → max(5.70, 5.80) = 5.80.
          iter 2: places at 5.80 = sell_floor → loop exits.
        Step3 floors at fair_price=5.80 (not at raw bid=3.00) and waits 60s.

        Intermediate SELL prices between 5.80 and 6.00 (e.g. 5.90, 5.95) are never tried —
        a known structural limitation of wide-spread illiquid options.
        """
        client = MagicMock()
        client.get_option_quote_by_occ.return_value = {"bid": 3.00, "ask": 9.00, "mid": 6.00}
        client.order_status.return_value = {"status": "open"}

        _, placed, sleeps = self._run(
            client, "SELL_CLOSE", get_fair_price_fn=lambda: _D("5.80")
        )

        loop_prices = placed[:-1]
        step3_price = placed[-1]

        assert loop_prices == [pytest.approx(6.00), pytest.approx(5.80)]
        assert step3_price == pytest.approx(5.80)   # floored at fair_price, not raw bid=3.00
        assert 60 in sleeps                          # SELL step3 waits 60s

    # -----------------------------------------------------------------------
    # Scenario 6 — Stale quotes (bid/ask never change), BUY
    # -----------------------------------------------------------------------

    def test_stale_quotes_escalate_price_via_internal_state(self):
        """
        Even when the market maker's quote never moves, escalation keeps
        incrementing current_price by 0.10×half_spread each iteration via
        internal state — no quote change is required to make progress.

        bid=4.00 ask=6.00 mid=5.00 half_spread=1.00, no fair_price:
          iter 1 (initial): 5.00 (mid)
          iter 2: 5.00 + 0.10 = 5.10
          iter 3: 5.10 + 0.10 = 5.20
          iter 4: 5.20 + 0.10 = 5.30
          ...all prices strictly increasing until ask is reached.
        """
        client = MagicMock()
        client.get_option_quote_by_occ.return_value = {"bid": 4.00, "ask": 6.00, "mid": 5.00}
        client.order_status.return_value = {"status": "open"}

        _, placed, _ = self._run(client, "BUY_OPEN")

        loop_prices = placed[:-1]

        assert loop_prices[0] == pytest.approx(5.00)   # initial: mid (no increment yet)
        assert loop_prices[1] == pytest.approx(5.10)   # +0.10 slow increment
        assert loop_prices[2] == pytest.approx(5.20)
        assert loop_prices[3] == pytest.approx(5.30)
        # All loop prices strictly increasing despite stale bid/ask
        assert all(loop_prices[i] < loop_prices[i + 1] for i in range(len(loop_prices) - 1))

    # -----------------------------------------------------------------------
    # Scenario 7 — Quote fetch always fails (feed down)
    # -----------------------------------------------------------------------

    def test_quote_fetch_always_fails_places_market_order_fallback(self):
        """
        If every get_option_quote_by_occ call raises (e.g. IEX feed is down):
        - The loop breaks immediately after step1's quote fetch fails.
        - Step3 also fails to fetch; _last_known_quote is still [None, None] → step3_price=None.
        - A MARKET order (price=None) is placed as a last resort.
        No limit orders are placed and no cancels are called.
        """
        client = MagicMock()
        client.get_option_quote_by_occ.side_effect = RuntimeError("feed down")

        result, placed, _ = self._run(client, "BUY_OPEN")

        # _run's capture_place always returns {"order_id": "ord-001"}; one MARKET order placed
        assert result == {"order_id": "ord-001"}
        # placed tracks price arg; MARKET order has price=None
        assert placed == [None]
        assert client.cancel_order.call_count == 0
        market_calls = [
            c for c in client.place_option_order.call_args_list
            if c.kwargs.get("price_type") == "MARKET"
        ]
        assert len(market_calls) == 1

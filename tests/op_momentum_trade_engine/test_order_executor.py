import pytest
from decimal import Decimal
from unittest.mock import MagicMock, patch

from alpha_tech_tracker.op_momentum_strategy.order_executor import (
    _parse_tick_from_reject_reason,
    _place_with_fill_escalation,
    place_option_order_in_tranches,
    place_stock_order,
)
from alpha_tech_tracker.trade_api.execution_client import InsufficientFundsError

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
            result, _ = _place_with_fill_escalation(
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
            order, _ = _place_with_fill_escalation(
                client=client,
                ticker=_TICKER,
                option_symbol=_SYMBOL,
                option_type=_OPTION_TYPE,
                contracts=_CONTRACTS,
                order_action=_SELL,
            )
        return order

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
            order, _ = _place_with_fill_escalation(
                client=client,
                ticker=_TICKER,
                option_symbol=_SYMBOL,
                option_type=_OPTION_TYPE,
                contracts=1,
                order_action=order_action,
                get_fair_price_fn=get_fair_price_fn,
            )
        return order

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


class TestAlpacaInsufficientFundsConversion:
    """AlpacaAPIClient re-raises Alpaca 40310000 errors as InsufficientFundsError."""

    def _make_alpaca_client(self):
        from alpha_tech_tracker.trade_api.alpaca_client.client import AlpacaAPIClient
        client = AlpacaAPIClient.__new__(AlpacaAPIClient)
        from unittest.mock import MagicMock
        client._trading_client = MagicMock()
        return client

    def test_place_option_order_40310000_raises_insufficient_funds_error(self):
        client = self._make_alpaca_client()
        client._trading_client.submit_order.side_effect = Exception(
            '{"code":40310000,"message":"insufficient options buying power"}'
        )
        with pytest.raises(InsufficientFundsError):
            client.place_option_order(
                symbol="NVDA",
                price=3.50,
                price_type="LIMIT",
                order_action="BUY_OPEN",
                quantity=1,
                _option_symbol_override="NVDA260418C00120000",
            )

    def test_place_stock_order_40310000_raises_insufficient_funds_error(self):
        client = self._make_alpaca_client()
        client._trading_client.submit_order.side_effect = Exception(
            '{"code":40310000,"message":"insufficient qty available for order"}'
        )
        with pytest.raises(InsufficientFundsError):
            client.place_stock_order(symbol="MU", quantity=26, side="BUY", order_type="LIMIT", limit_price=100.0)

    def test_non_40310000_error_is_not_converted(self):
        client = self._make_alpaca_client()
        client._trading_client.submit_order.side_effect = Exception("network timeout")
        with pytest.raises(Exception, match="network timeout"):
            client.place_stock_order(symbol="MU", quantity=1, side="BUY", order_type="LIMIT", limit_price=100.0)
        assert not isinstance(Exception("network timeout"), InsufficientFundsError)


class TestInsufficientBuyingPowerAbort:
    """
    When place_option_order raises an Alpaca 40310000 error, the escalation
    must abort immediately and return ({}, 0) — no further placement attempts.
    """

    _BP_ERROR = InsufficientFundsError("insufficient options buying power")

    def _make_client_with_bp_error(self, fail_on_call=1):
        client = MagicMock()
        client.get_option_quote_by_occ.return_value = {"bid": 4.90, "ask": 5.10, "mid": 5.00}
        call_count = [0]

        def place_order_side_effect(**kwargs):
            call_count[0] += 1
            if call_count[0] >= fail_on_call:
                raise self._BP_ERROR
            return {"order_id": "ord-001"}

        client.place_option_order.side_effect = place_order_side_effect
        client.order_status.return_value = {"status": "open"}
        return client

    def test_loop_step1_bp_error_returns_empty_order_and_zero_filled(self):
        client = self._make_client_with_bp_error(fail_on_call=1)
        with patch(f"{_MODULE}.time.sleep", lambda _: None):
            order, filled = _place_with_fill_escalation(
                client=client,
                ticker=_TICKER,
                option_symbol=_SYMBOL,
                option_type=_OPTION_TYPE,
                contracts=_CONTRACTS,
                order_action="BUY_OPEN",
            )
        assert order == {}
        assert filled == 0

    def test_loop_step1_bp_error_stops_after_one_placement_attempt(self):
        client = self._make_client_with_bp_error(fail_on_call=1)
        with patch(f"{_MODULE}.time.sleep", lambda _: None):
            _place_with_fill_escalation(
                client=client,
                ticker=_TICKER,
                option_symbol=_SYMBOL,
                option_type=_OPTION_TYPE,
                contracts=_CONTRACTS,
                order_action="BUY_OPEN",
            )
        assert client.place_option_order.call_count == 1

    def test_loop_step1_bp_error_does_not_check_fill_status(self):
        client = self._make_client_with_bp_error(fail_on_call=1)
        with patch(f"{_MODULE}.time.sleep", lambda _: None):
            _place_with_fill_escalation(
                client=client,
                ticker=_TICKER,
                option_symbol=_SYMBOL,
                option_type=_OPTION_TYPE,
                contracts=_CONTRACTS,
                order_action="BUY_OPEN",
            )
        client.order_status.assert_not_called()

    def test_tick_retry_bp_error_aborts_escalation(self):
        """40310000 on the tick-retry path also aborts immediately."""
        client = MagicMock()
        client.get_option_quote_by_occ.return_value = {"bid": 5.90, "ask": 6.20, "mid": 6.05}
        call_count = [0]
        _TICK_REJ_MSG = "Price = 6.05000000 not rounded to a valid price increment [ 0.1 ]"

        def place_order_side_effect(**kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return {"order_id": "ord-001"}
            raise self._BP_ERROR

        client.place_option_order.side_effect = place_order_side_effect
        client.order_status.return_value = {"status": "canceled", "reject_reason": _TICK_REJ_MSG}
        with patch(f"{_MODULE}.time.sleep", lambda _: None):
            order, filled = _place_with_fill_escalation(
                client=client,
                ticker="APP",
                option_symbol="APP260418C00500000",
                option_type="CALL",
                contracts=1,
                order_action="BUY_OPEN",
            )
        assert order == {}
        assert filled == 0
        assert client.place_option_order.call_count == 2

    def test_step3_bp_error_aborts_escalation(self):
        """40310000 at the step3 final limit also aborts and returns ({}, 0)."""
        client = MagicMock()
        client.get_option_quote_by_occ.return_value = {"bid": 4.90, "ask": 5.10, "mid": 5.00}
        call_count = [0]

        def place_order_side_effect(**kwargs):
            call_count[0] += 1
            if call_count[0] < 12:
                return {"order_id": "ord-001"}
            raise self._BP_ERROR

        client.place_option_order.side_effect = place_order_side_effect
        client.order_status.return_value = {"status": "open"}
        with patch(f"{_MODULE}.time.sleep", lambda _: None):
            order, filled = _place_with_fill_escalation(
                client=client,
                ticker=_TICKER,
                option_symbol=_SYMBOL,
                option_type=_OPTION_TYPE,
                contracts=_CONTRACTS,
                order_action=_SELL,
            )
        assert order == {}
        assert filled == 0


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
            result, _ = _place_with_fill_escalation(
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
            result, _ = _place_with_fill_escalation(
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
            result, _ = _place_with_fill_escalation(
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
            _place_with_fill_escalation(
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
            _place_with_fill_escalation(
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
            _place_with_fill_escalation(
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
        client = _make_stock_client(bid=329.75, ask=330.25)
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
    Step 1 retries up to 3 times at mid price (2s each) for entries before
    escalating to step 2. Uses narrow spread (≤$0.50) so the wide-spread skip
    does not interfere with these tests.
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
        client = _make_stock_client(bid=329.75, ask=330.25)
        self._run(client, filled_on_step1_attempt=1)
        calls = client.place_stock_order.call_args_list
        assert len(calls) == 1
        assert calls[0].kwargs["order_type"] == "LIMIT"
        assert calls[0].kwargs["limit_price"] == 330.0

    def test_step1_fills_on_second_attempt_returns_without_escalating(self):
        # Each step1 attempt now makes 2 order_status calls (pre-cancel + post-cancel).
        # Call sequence: attempt-1-pre(open), attempt-1-post(open), attempt-2-pre(filled).
        client = _make_stock_client(bid=329.75, ask=330.25)
        open_s = {"status": "open"}
        filled_s = {"status": "filled"}
        client.order_status.side_effect = [open_s, open_s, filled_s]
        with patch(f"{_MODULE}.time.sleep", lambda _: None):
            place_stock_order(client=client, ticker="FN", shares=1, order_action="BUY_OPEN")
        limit_calls = [c for c in client.place_stock_order.call_args_list if c.kwargs["order_type"] == "LIMIT"]
        assert len(limit_calls) == 2
        assert all(c.kwargs["limit_price"] == 330.0 for c in limit_calls)

    def test_step1_fills_on_third_attempt_returns_without_escalating(self):
        # Call sequence: a1-pre(open), a1-post(open), a2-pre(open), a2-post(open), a3-pre(filled).
        client = _make_stock_client(bid=329.75, ask=330.25)
        open_s = {"status": "open"}
        filled_s = {"status": "filled"}
        client.order_status.side_effect = [open_s, open_s, open_s, open_s, filled_s]
        with patch(f"{_MODULE}.time.sleep", lambda _: None):
            place_stock_order(client=client, ticker="FN", shares=1, order_action="BUY_OPEN")
        limit_calls = [c for c in client.place_stock_order.call_args_list if c.kwargs["order_type"] == "LIMIT"]
        assert len(limit_calls) == 3
        assert all(c.kwargs["limit_price"] == 330.0 for c in limit_calls)

    def test_step1_all_attempts_exhausted_escalates_to_step2(self):
        client = _make_stock_client(bid=329.75, ask=330.25)
        self._run(client, filled_on_step1_attempt=None)
        # step1(3) + step2(3) + step3 market(1) = 7 total orders
        assert client.place_stock_order.call_count == 7

    def test_step1_quote_fetch_failure_falls_back_to_market_immediately(self):
        client = _make_stock_client(bid=329.75, ask=330.25)
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
            step2_attempt = attempt_count[0] - 6  # step 2 starts after 6 step1 checks (3 pre + 3 post)
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
        client = _make_stock_client(bid=329.75, ask=330.25)
        self._run(client, filled_on_attempt=None)
        last_call = client.place_stock_order.call_args_list[-1]
        assert last_call.kwargs["order_type"] == "MARKET"

    def test_step2_all_attempts_exhausted_places_exactly_seven_orders(self):
        # step1(3) + step2(3) + step3 market(1) = 7
        client = _make_stock_client(bid=329.75, ask=330.25)
        self._run(client, filled_on_attempt=None)
        assert client.place_stock_order.call_count == 7

    def test_step2_fills_on_first_attempt_returns_without_market(self):
        client = _make_stock_client(bid=329.75, ask=330.25)
        self._run(client, filled_on_attempt=1)
        calls = client.place_stock_order.call_args_list
        assert all(c.kwargs["order_type"] == "LIMIT" for c in calls)

    def test_step2_fills_on_second_attempt_returns_without_market(self):
        client = _make_stock_client(bid=329.75, ask=330.25)
        self._run(client, filled_on_attempt=2)
        calls = client.place_stock_order.call_args_list
        assert all(c.kwargs["order_type"] == "LIMIT" for c in calls)

    def test_step2_fills_on_third_attempt_returns_without_market(self):
        client = _make_stock_client(bid=329.75, ask=330.25)
        self._run(client, filled_on_attempt=3)
        calls = client.place_stock_order.call_args_list
        assert all(c.kwargs["order_type"] == "LIMIT" for c in calls)

    def test_step2_buy_limit_price_is_ask(self):
        client = _make_stock_client(bid=329.75, ask=330.25)
        self._run(client, order_action="BUY_OPEN", filled_on_attempt=None)
        step2_calls = client.place_stock_order.call_args_list[3:6]
        for call in step2_calls:
            assert call.kwargs["order_type"] == "LIMIT"
            assert call.kwargs["limit_price"] == 330.25

    def test_step2_sell_limit_price_is_bid(self):
        # SELL_CLOSE is an exit: only 1 step1 attempt before step2 starts at index [1]
        client = _make_stock_client(bid=329.75, ask=330.25)
        self._run(client, order_action="SELL_CLOSE", filled_on_attempt=None)
        step2_calls = client.place_stock_order.call_args_list[1:4]
        for call in step2_calls:
            assert call.kwargs["order_type"] == "LIMIT"
            assert call.kwargs["limit_price"] == 329.75

    def test_step2_quote_fetch_failure_falls_back_to_market_immediately(self):
        client = _make_stock_client(bid=329.75, ask=330.25)
        call_count = [0]

        def quote_side_effect(symbol, **kwargs):
            call_count[0] += 1
            if call_count[0] > 3:  # step 1 uses 3 quotes; fail on step 2's first fetch
                raise RuntimeError("quote unavailable")
            return {
                "QuoteResponse": {
                    "QuoteData": [{"All": {"bid": 329.75, "ask": 330.25, "lastTrade": 329.75}}]
                }
            }

        client.get_stock_quote.side_effect = quote_side_effect
        client.order_status.return_value = {"status": "open"}
        with patch(f"{_MODULE}.time.sleep", lambda _: None):
            place_stock_order(client=client, ticker="FN", shares=1, order_action="BUY_OPEN")

        last_call = client.place_stock_order.call_args_list[-1]
        assert last_call.kwargs["order_type"] == "MARKET"


class TestPlaceStockOrderInsufficientFundsAbort:
    """
    When the broker client raises InsufficientFundsError on a stock placement,
    the escalation must abort immediately without burning through all remaining
    step 1 / step 2 retries.
    """

    _INSUF_ERROR = InsufficientFundsError(
        "insufficient qty available for order (requested: 26, available: 24)"
    )

    def test_step1_insufficient_funds_raises_immediately(self):
        client = _make_stock_client(bid=473.0, ask=484.49)
        client.place_stock_order.side_effect = self._INSUF_ERROR

        with patch(f"{_MODULE}.time.sleep", lambda _: None), \
             pytest.raises(InsufficientFundsError):
            place_stock_order(
                client=client, ticker="MU", shares=26, order_action="BUY_OPEN"
            )

    def test_step1_insufficient_funds_places_only_one_order(self):
        client = _make_stock_client(bid=473.0, ask=484.49)
        client.place_stock_order.side_effect = self._INSUF_ERROR

        with patch(f"{_MODULE}.time.sleep", lambda _: None), \
             pytest.raises(InsufficientFundsError):
            place_stock_order(
                client=client, ticker="MU", shares=26, order_action="BUY_OPEN"
            )

        assert client.place_stock_order.call_count == 1

    def test_step2_insufficient_funds_raises_immediately_after_step1_exhausted(self):
        client = _make_stock_client(bid=473.0, ask=484.49)
        call_count = [0]

        def side_effect(**kwargs):
            call_count[0] += 1
            if call_count[0] <= 3:
                return {"order_id": f"ord-step1-{call_count[0]}", "status": "open"}
            raise self._INSUF_ERROR

        client.place_stock_order.side_effect = side_effect
        client.order_status.return_value = {"status": "open"}

        with patch(f"{_MODULE}.time.sleep", lambda _: None), \
             pytest.raises(InsufficientFundsError):
            place_stock_order(
                client=client, ticker="MU", shares=26, order_action="BUY_OPEN"
            )

        assert client.place_stock_order.call_count == 4  # 3 step1 + 1 step2

    def test_non_insufficient_funds_step1_failure_still_escalates(self):
        client = _make_stock_client(bid=473.0, ask=473.40)
        client.place_stock_order.side_effect = Exception("network timeout")
        client.order_status.return_value = {"status": "open"}

        with patch(f"{_MODULE}.time.sleep", lambda _: None), \
             pytest.raises(Exception):
            place_stock_order(
                client=client, ticker="MU", shares=26, order_action="BUY_OPEN"
            )

        # Non-40310000: all 3 step1 + all 3 step2 + market = 7 attempts
        assert client.place_stock_order.call_count == 7


class TestPlaceStockOrderShortSaleInsufficientBuyingPowerShrink:
    """
    When Alpaca rejects an entry order (SELL_SHORT or BUY_OPEN) with a
    parseable insufficient buying-power message, the escalation must shrink
    the share count to fit within the reported buying power and retry,
    rather than aborting the entire entry. Confirmed live incidents:
    2026-07-31 CRWV SELL_SHORT (Reg-T short margin exceeded window budget)
    and 2026-08-04 CRWV BUY_OPEN (account's real-time Intraday Margin
    Framework buying power fell short of the account-snapshot figure the
    position sizer used) — both cost a fully missed, otherwise-valid signal.
    """

    _BP_ERROR = InsufficientFundsError(
        '{"buying_power":"7727.51","code":40310000,"cost_basis":"12161.98",'
        '"message":"insufficient buying power"}'
    )

    def test_step1_shrinks_shares_and_retries_on_short_sale(self):
        client = _make_stock_client(bid=73.10, ask=73.20, order_status="filled")
        call_count = [0]

        def side_effect(**kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise self._BP_ERROR
            return {"order_id": "stock-ord-002", "status": "filled"}

        client.place_stock_order.side_effect = side_effect

        with patch(f"{_MODULE}.time.sleep", lambda _: None):
            result = place_stock_order(
                client=client, ticker="CRWV", shares=161, order_action="SELL_SHORT"
            )

        assert client.place_stock_order.call_count == 2
        # 7727.51 / 12161.98 * 0.95 ≈ 0.6039 → int(161 * 0.6039) = 97
        second_call = client.place_stock_order.call_args_list[1]
        assert second_call.kwargs["quantity"] == 97
        assert result["total_filled_qty"] == 97

    def test_shrink_also_applied_to_buy_open(self):
        # Margin/buying-power shortfalls affect both entry directions (2026-08-04
        # CRWV incident — a BUY_OPEN long was rejected the same way a SELL_SHORT
        # was on 2026-07-31), so BUY_OPEN gets the same shrink-and-retry treatment.
        client = _make_stock_client(bid=90.54, ask=90.60, order_status="filled")
        call_count = [0]

        def side_effect(**kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise self._BP_ERROR
            return {"order_id": "stock-ord-003", "status": "filled"}

        client.place_stock_order.side_effect = side_effect

        with patch(f"{_MODULE}.time.sleep", lambda _: None):
            result = place_stock_order(
                client=client, ticker="CRWV", shares=133, order_action="BUY_OPEN"
            )

        assert client.place_stock_order.call_count == 2
        # 7727.51 / 12161.98 * 0.95 ≈ 0.6039 → int(133 * 0.6039) = 80
        second_call = client.place_stock_order.call_args_list[1]
        assert second_call.kwargs["quantity"] == 80
        assert result["total_filled_qty"] == 80

    def test_shrink_not_applied_to_exit_actions(self):
        # Margin shrink only makes sense for orders that OPEN exposure —
        # SELL_CLOSE/BUY_COVER (exits) still abort immediately on the same error.
        client = _make_stock_client(bid=73.10, ask=73.20)
        client.place_stock_order.side_effect = self._BP_ERROR

        with patch(f"{_MODULE}.time.sleep", lambda _: None), \
             pytest.raises(InsufficientFundsError):
            place_stock_order(
                client=client, ticker="CRWV", shares=161, order_action="SELL_CLOSE"
            )

        assert client.place_stock_order.call_count == 1

    def test_unparseable_message_still_aborts(self):
        # Falls back to the original abort behavior when the error can't be parsed.
        client = _make_stock_client(bid=73.10, ask=73.20)
        client.place_stock_order.side_effect = InsufficientFundsError(
            "insufficient qty available for order (requested: 161, available: 100)"
        )

        with patch(f"{_MODULE}.time.sleep", lambda _: None), \
             pytest.raises(InsufficientFundsError):
            place_stock_order(
                client=client, ticker="CRWV", shares=161, order_action="SELL_SHORT"
            )

        assert client.place_stock_order.call_count == 1

    def test_persistent_rejection_falls_through_to_market_then_raises(self):
        # Every attempt rejected with the same message — each retry shrinks
        # further (161→97→58→35→21→12→7), exhausting all 3 step1 + 3 step2
        # attempts. This is bounded, not an infinite loop: it falls through to
        # the existing step3 market-order fallback (same as any other
        # exhausted escalation), which also fails and raises — it must not
        # loop forever or silently swallow the failure.
        client = _make_stock_client(bid=73.10, ask=73.20)
        client.place_stock_order.side_effect = self._BP_ERROR

        with patch(f"{_MODULE}.time.sleep", lambda _: None), \
             pytest.raises(InsufficientFundsError):
            place_stock_order(
                client=client, ticker="CRWV", shares=161, order_action="SELL_SHORT"
            )

        # 3 step1 + 3 step2 shrink-and-retry attempts + 1 final step3 market attempt
        assert client.place_stock_order.call_count == 7


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
            result, _ = _place_with_fill_escalation(
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
            result, _ = _place_with_fill_escalation(
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
            order, _ = _place_with_fill_escalation(
                client=client,
                ticker=_TICKER,
                option_symbol=_SYMBOL,
                option_type=_OPTION_TYPE,
                contracts=_CONTRACTS,
                order_action="BUY_OPEN",
            )
        return order

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
            result, _ = _place_with_fill_escalation(
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
            result, _ = _place_with_fill_escalation(
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


class TestPartialFillHandling:
    """
    Partial fill handling: when order_status returns filled_qty > 0 but status != "filled",
    the escalation must cancel the remainder, reduce _contracts_remaining, and continue
    for the unfilled portion.

    Scenarios:
      1. Loop partial fill — remainder continues at fresh market price
      2. All remaining filled on second order — terminates immediately
      3. Second-order quantity uses remaining count, not original
      4. Step3 partial fill — logs warning, returns order, does not raise
      5. Step0 partial fill — reduces remaining, falls through to loop
    """

    def _run(self, client, order_action, contracts=10):
        """Run escalation capturing placed (price, qty) pairs and return (result, placed, confirmed_filled)."""
        placed = []

        def capture_place(**kw):
            placed.append((kw.get("price"), kw.get("quantity")))
            order_num = len(placed)
            return {"order_id": f"ord-{order_num:03d}"}

        client.place_option_order.side_effect = capture_place
        with patch(f"{_MODULE}.time.sleep", lambda _: None):
            result, confirmed_filled = _place_with_fill_escalation(
                client=client,
                ticker=_TICKER,
                option_symbol=_SYMBOL,
                option_type=_OPTION_TYPE,
                contracts=contracts,
                order_action=order_action,
            )
        return result, placed, confirmed_filled

    def test_loop_partial_fill_continues_with_remaining_contracts(self):
        """
        10 contracts, step1 fills 7 → cancel remainder → loop continues for 3.
        Step2 fills all 3 → done.

        quote: bid=4.90, ask=5.10, mid=5.00
        First order: placed at 5.00 (mid), qty=10, partial fill qty=7
        Second order: placed at 5.00 (fresh mid after reset), qty=3, full fill
        """
        client = MagicMock()
        client.get_option_quote_by_occ.return_value = {"bid": 4.90, "ask": 5.10, "mid": 5.00}
        status_calls = [0]

        def order_status(order_id):
            status_calls[0] += 1
            if order_id == "ord-001":
                return {"status": "open", "filled_qty": 7}
            return {"status": "filled", "filled_qty": 3}

        client.order_status.side_effect = order_status

        result, placed, confirmed_filled = self._run(client, "BUY_OPEN", contracts=10)

        assert result == {"order_id": "ord-002"}
        assert confirmed_filled == 10   # 7 partial + 3 full = all 10 confirmed
        assert len(placed) == 2
        _, qty1 = placed[0]
        _, qty2 = placed[1]
        assert qty1 == 10
        assert qty2 == 3   # only the remaining 3
        assert client.cancel_order.call_args_list[0].args[0] == "ord-001"

    def test_loop_partial_fill_resets_price_to_fresh_market(self):
        """
        After a partial fill the next order starts at mid, not the escalated price.
        Even if the loop had escalated to 5.05 before the partial fill, the reset
        brings current_price back to None → re-initialised from mid=5.00.
        """
        client = MagicMock()
        client.get_option_quote_by_occ.return_value = {"bid": 4.90, "ask": 5.10, "mid": 5.00}
        status_calls = [0]

        def order_status(order_id):
            status_calls[0] += 1
            if order_id == "ord-001":
                return {"status": "open", "filled_qty": 5}
            return {"status": "filled", "filled_qty": 5}

        client.order_status.side_effect = order_status

        result, placed, confirmed_filled = self._run(client, "BUY_OPEN", contracts=10)

        assert confirmed_filled == 10   # 5 partial + 5 full = all 10 confirmed
        price1, _ = placed[0]
        price2, _ = placed[1]
        assert price1 == pytest.approx(5.00)   # mid on first iteration
        assert price2 == pytest.approx(5.00)   # reset to mid after partial fill

    def test_loop_partial_fill_zero_remaining_returns_immediately(self):
        """
        If filled_qty exactly equals contracts_remaining the loop returns without
        placing another order.
        """
        client = MagicMock()
        client.get_option_quote_by_occ.return_value = {"bid": 4.90, "ask": 5.10, "mid": 5.00}

        def order_status(order_id):
            return {"status": "open", "filled_qty": 10}   # full amount "partial"

        client.order_status.side_effect = order_status

        result, placed, confirmed_filled = self._run(client, "BUY_OPEN", contracts=10)

        assert len(placed) == 1
        assert result == {"order_id": "ord-001"}
        assert confirmed_filled == 10   # all 10 filled "as partial" in one shot

    def test_step3_partial_fill_returns_order_and_logs_warning(self, caplog):
        """
        At step3 a partial fill (7/10) must:
        - Cancel the remainder
        - Log a MISS warning about the 3 still-open contracts
        - Return the order dict (not {})
        So position_monitor knows something filled and won't retry the full position.
        """
        import logging
        client = MagicMock()
        # Loop quote fetch always fails → falls straight to step3
        quote_calls = [0]

        def get_quote(sym):
            quote_calls[0] += 1
            if quote_calls[0] == 1:
                raise RuntimeError("feed down")   # loop fetch fails → step3
            return {"bid": 4.90, "ask": 5.10, "mid": 5.00}   # step3 quote fetch succeeds

        client.get_option_quote_by_occ.side_effect = get_quote

        def order_status(order_id):
            return {"status": "open", "filled_qty": 7}   # partial at step3

        client.order_status.side_effect = order_status

        with caplog.at_level(logging.WARNING, logger="alpha_tech_tracker"):
            result, placed, confirmed_filled = self._run(client, "BUY_OPEN", contracts=10)

        assert result.get("order_id") is not None   # not {}
        assert confirmed_filled == 7   # only the 7 that actually filled — not 10
        assert any("still open" in r.message for r in caplog.records)

    def test_step0_partial_fill_continues_to_loop_with_remainder(self):
        """
        Step0 (quick-exit) partially fills 2 of 5 contracts → cancel remainder →
        loop picks up for the remaining 3.
        """
        client = MagicMock()
        client.get_option_quote_by_occ.return_value = {"bid": 4.90, "ask": 5.10, "mid": 5.00}
        status_calls = [0]

        def order_status(order_id):
            status_calls[0] += 1
            if order_id == "ord-001":   # step0
                return {"status": "open", "filled_qty": 2}
            return {"status": "filled", "filled_qty": 3}   # loop fills remainder

        client.order_status.side_effect = order_status

        placed = []

        def capture_place(**kw):
            placed.append((kw.get("price"), kw.get("quantity")))
            return {"order_id": f"ord-{len(placed):03d}"}

        client.place_option_order.side_effect = capture_place

        with patch(f"{_MODULE}.time.sleep", lambda _: None):
            result, confirmed_filled = _place_with_fill_escalation(
                client=client,
                ticker=_TICKER,
                option_symbol=_SYMBOL,
                option_type=_OPTION_TYPE,
                contracts=5,
                order_action="SELL_CLOSE",
                entry_fill_price=5.00,   # triggers step0
            )

        assert len(placed) >= 2
        _, qty0 = placed[0]   # step0
        _, qty1 = placed[1]   # first loop order
        assert qty0 == 5      # step0 uses full original count
        assert qty1 == 3      # loop uses remaining after partial step0 fill
        assert confirmed_filled == 5   # 2 (step0 partial) + 3 (loop full) = all 5


_TRANCHE_MODULE = "alpha_tech_tracker.op_momentum_strategy.order_executor"


class TestTrancheFilling:
    """
    place_option_order_in_tranches() slices large orders into sequential
    batches of at most tranche_size contracts, each going through the full
    escalation policy.

    Scenarios:
      1. contracts <= tranche_size — single escalation call, identical to no-tranche
      2. 2 tranches both fill — filled_so_far == contracts, last order returned
      3. Tranche 1 fills, tranche 2 MISSes — filled_so_far == tranche_size, stop
      4. Tranche 1 MISSes immediately — filled_so_far == 0, last_order == {}
      5. entry_fill_price forwarded only to first tranche
    """

    _INNER = f"{_TRANCHE_MODULE}._place_with_fill_escalation"

    def _filled_order(self, order_id="ord-001", confirmed=5):
        return ({"order_id": order_id}, confirmed)

    def _miss_order(self):
        return ({}, 0)

    def test_no_tranche_when_contracts_at_or_below_size(self):
        """contracts=5, tranche_size=5 → single _place_with_fill_escalation call."""
        client = _make_client()
        with patch(self._INNER, return_value=self._filled_order()) as mock_inner, \
             patch(f"{_TRANCHE_MODULE}.time.sleep", lambda _: None):
            order, filled = place_option_order_in_tranches(
                client=client,
                ticker=_TICKER,
                option_symbol=_SYMBOL,
                option_type=_OPTION_TYPE,
                contracts=5,
                order_action=_SELL,
                tranche_size=5,
            )
        assert mock_inner.call_count == 1
        assert mock_inner.call_args.kwargs["contracts"] == 5
        assert filled == 5
        assert order == {"order_id": "ord-001"}

    def test_two_tranches_both_fill_returns_total_filled(self):
        """contracts=10, tranche_size=5 → two calls, both fill → filled_so_far=10."""
        client = _make_client()
        with patch(self._INNER, return_value=self._filled_order()) as mock_inner, \
             patch(f"{_TRANCHE_MODULE}.time.sleep", lambda _: None):
            order, filled = place_option_order_in_tranches(
                client=client,
                ticker=_TICKER,
                option_symbol=_SYMBOL,
                option_type=_OPTION_TYPE,
                contracts=10,
                order_action="BUY_OPEN",
                tranche_size=5,
            )
        assert mock_inner.call_count == 2
        assert mock_inner.call_args_list[0].kwargs["contracts"] == 5
        assert mock_inner.call_args_list[1].kwargs["contracts"] == 5
        assert filled == 10

    def test_tranche1_fills_tranche2_misses_stops_early(self):
        """contracts=10, tranche_size=5, tranche 2 MISSes → filled_so_far=5."""
        client = _make_client()
        call_num = [0]

        def side_effect(**kw):
            call_num[0] += 1
            return self._filled_order() if call_num[0] == 1 else self._miss_order()

        with patch(self._INNER, side_effect=side_effect) as mock_inner, \
             patch(f"{_TRANCHE_MODULE}.time.sleep", lambda _: None):
            order, filled = place_option_order_in_tranches(
                client=client,
                ticker=_TICKER,
                option_symbol=_SYMBOL,
                option_type=_OPTION_TYPE,
                contracts=10,
                order_action="BUY_OPEN",
                tranche_size=5,
            )
        assert mock_inner.call_count == 2
        assert filled == 5
        assert order == {}

    def test_tranche1_misses_immediately_stops_with_zero_filled(self):
        """contracts=10, tranche 1 MISSes (confirmed_filled=0) → filled_so_far=0, last_order={}."""
        client = _make_client()
        with patch(self._INNER, return_value=self._miss_order()) as mock_inner, \
             patch(f"{_TRANCHE_MODULE}.time.sleep", lambda _: None):
            order, filled = place_option_order_in_tranches(
                client=client,
                ticker=_TICKER,
                option_symbol=_SYMBOL,
                option_type=_OPTION_TYPE,
                contracts=10,
                order_action="BUY_OPEN",
                tranche_size=5,
            )
        assert mock_inner.call_count == 1
        assert filled == 0
        assert order == {}

    def test_entry_fill_price_forwarded_only_to_first_tranche(self):
        """entry_fill_price must be passed to tranche 1 and None to tranche 2+."""
        client = _make_client()
        with patch(self._INNER, return_value=self._filled_order()) as mock_inner, \
             patch(f"{_TRANCHE_MODULE}.time.sleep", lambda _: None):
            place_option_order_in_tranches(
                client=client,
                ticker=_TICKER,
                option_symbol=_SYMBOL,
                option_type=_OPTION_TYPE,
                contracts=10,
                order_action=_SELL,
                tranche_size=5,
                entry_fill_price=5.00,
            )
        assert mock_inner.call_args_list[0].kwargs["entry_fill_price"] == 5.00
        assert mock_inner.call_args_list[1].kwargs["entry_fill_price"] is None


class TestStockOrderEscalationPolicy:
    """
    Tests for the three 2026-04-28 escalation policy changes:
      1. Buy orders with spread > $0.50 skip step1 and go straight to step2 at ask.
      2. Exit orders (BUY_COVER, SELL_CLOSE) get only 1 step1 attempt.
      3. Step1 sleep is 2s (tested via captured sleep args).
    """

    _NARROW_BID = 329.75
    _NARROW_ASK = 330.25  # spread = $0.50 — exactly at boundary, NOT skipped
    _WIDE_BID = 1050.0
    _WIDE_ASK = 1070.0    # spread = $20.00 >> $0.50

    def _run(self, client, order_action, sleep_calls=None):
        def capture_sleep(secs):
            if sleep_calls is not None:
                sleep_calls.append(secs)

        with patch(f"{_MODULE}.time.sleep", side_effect=capture_sleep):
            return place_stock_order(
                client=client,
                ticker="SNDK",
                shares=1,
                order_action=order_action,
            )

    # ── wide-spread buy skips step1 ──────────────────────────────────────────

    def test_wide_spread_buy_open_skips_step1_first_order_is_at_ask(self):
        client = _make_stock_client(bid=self._WIDE_BID, ask=self._WIDE_ASK)
        self._run(client, order_action="BUY_OPEN")
        first_order = client.place_stock_order.call_args_list[0]
        assert first_order.kwargs["order_type"] == "LIMIT"
        assert first_order.kwargs["limit_price"] == self._WIDE_ASK

    def test_wide_spread_buy_cover_skips_step1_first_order_is_at_ask(self):
        client = _make_stock_client(bid=self._WIDE_BID, ask=self._WIDE_ASK)
        self._run(client, order_action="BUY_COVER")
        first_order = client.place_stock_order.call_args_list[0]
        assert first_order.kwargs["order_type"] == "LIMIT"
        assert first_order.kwargs["limit_price"] == self._WIDE_ASK

    def test_wide_spread_sell_short_does_not_skip_step1(self):
        # spread check only applies to buy orders
        client = _make_stock_client(bid=self._WIDE_BID, ask=self._WIDE_ASK)
        client.order_status.return_value = {"status": "filled"}
        self._run(client, order_action="SELL_SHORT")
        first_order = client.place_stock_order.call_args_list[0]
        mid = (self._WIDE_BID + self._WIDE_ASK) / 2
        assert first_order.kwargs["order_type"] == "LIMIT"
        assert first_order.kwargs["limit_price"] == mid

    def test_narrow_spread_buy_uses_step1_at_mid(self):
        # spread = $0.50 is exactly at boundary — not skipped
        client = _make_stock_client(bid=self._NARROW_BID, ask=self._NARROW_ASK)
        client.order_status.return_value = {"status": "filled"}
        self._run(client, order_action="BUY_OPEN")
        first_order = client.place_stock_order.call_args_list[0]
        assert first_order.kwargs["order_type"] == "LIMIT"
        assert first_order.kwargs["limit_price"] == 330.0  # mid

    def test_wide_spread_buy_total_orders_is_four(self):
        # 0 step1 + 3 step2 + 1 market = 4
        client = _make_stock_client(bid=self._WIDE_BID, ask=self._WIDE_ASK)
        self._run(client, order_action="BUY_OPEN")
        assert client.place_stock_order.call_count == 4

    # ── exit orders limited to 1 step1 attempt ──────────────────────────────

    def test_sell_close_escalates_to_step2_after_one_step1_attempt(self):
        client = _make_stock_client(bid=self._NARROW_BID, ask=self._NARROW_ASK)
        self._run(client, order_action="SELL_CLOSE")
        orders = client.place_stock_order.call_args_list
        # first order: step1 limit at mid; second order: step2 limit at bid
        assert orders[0].kwargs["limit_price"] == 330.0
        assert orders[1].kwargs["limit_price"] == self._NARROW_BID

    def test_buy_cover_escalates_to_step2_after_one_step1_attempt(self):
        # BUY_COVER + narrow spread: goes through step1 once (wide-spread skip not triggered)
        client = _make_stock_client(bid=self._NARROW_BID, ask=self._NARROW_ASK)
        self._run(client, order_action="BUY_COVER")
        orders = client.place_stock_order.call_args_list
        assert orders[0].kwargs["limit_price"] == 330.0  # step1 at mid
        assert orders[1].kwargs["limit_price"] == self._NARROW_ASK  # step2 at ask

    def test_sell_close_total_orders_is_five(self):
        # 1 step1 + 3 step2 + 1 market = 5
        client = _make_stock_client(bid=self._NARROW_BID, ask=self._NARROW_ASK)
        self._run(client, order_action="SELL_CLOSE")
        assert client.place_stock_order.call_count == 5

    def test_buy_cover_narrow_spread_total_orders_is_five(self):
        client = _make_stock_client(bid=self._NARROW_BID, ask=self._NARROW_ASK)
        self._run(client, order_action="BUY_COVER")
        assert client.place_stock_order.call_count == 5

    def test_entry_order_still_gets_three_step1_attempts(self):
        # BUY_OPEN / SELL_SHORT with narrow spread: 3 step1 attempts
        client = _make_stock_client(bid=self._NARROW_BID, ask=self._NARROW_ASK)
        self._run(client, order_action="BUY_OPEN")
        assert client.place_stock_order.call_count == 7  # 3+3+1

    # ── step1 sleep is 2s ───────────────────────────────────────────────────

    def test_step1_sleep_interval_is_two_seconds(self):
        # Each step1 attempt: 2s (wait for fill) + 0.5s (post-cancel re-check) × 3 attempts.
        sleep_calls = []
        client = _make_stock_client(bid=self._NARROW_BID, ask=self._NARROW_ASK)
        self._run(client, order_action="BUY_OPEN", sleep_calls=sleep_calls)
        assert sleep_calls[:6] == [2, 0.5, 2, 0.5, 2, 0.5]


# ---------------------------------------------------------------------------
# TestStep3FairPriceFloorNotDecayed — G33
# ---------------------------------------------------------------------------


class TestStep3FairPriceFloorNotDecayed:
    """
    G33: When bid is materially below fair_price, the step3 floor is max(bid, fair_price)
    = fair_price. Since fair_price is re-fetched from the (stale) option-price cache on
    each call to _place_with_fill_escalation, the floor does not decay between retry
    attempts. The exit order gets stuck 1-2 min above the market bid until the market
    recovers.

    Observed 2026-04-28: EXPE retry ran steps 1-8 (~2 min) all at 20.05-20.10 while bid
    sat at 18.70-18.80. Fix: pass a retry_attempt counter and decay the floor by
    25% of the bid-gap per retry.
    """

    _BID = 18.80
    _FAIR = 20.05

    def _run_sell_all_miss(self, bid=None, fair_price=None):
        bid = bid if bid is not None else self._BID
        fair_price = fair_price if fair_price is not None else self._FAIR
        ask = bid + 2.0
        client = MagicMock()
        client.get_option_quote_by_occ.return_value = {
            "bid": bid, "ask": ask, "mid": (bid + ask) / 2,
        }
        client.place_option_order.return_value = {"order_id": "ord-1", "status": "open"}
        client.order_status.return_value = {"status": "open"}
        with patch(f"{_MODULE}.time.sleep", lambda _: None):
            result = _place_with_fill_escalation(
                client=client,
                ticker="EXPE",
                option_symbol="EXPE260501P00260000",
                option_type="PUT",
                contracts=1,
                order_action="SELL_CLOSE",
                feed=None,
                get_fair_price_fn=MagicMock(return_value=_D(str(fair_price))),
            )
        limit_prices = [
            c.kwargs["price"]
            for c in client.place_option_order.call_args_list
            if c.kwargs.get("price_type") == "LIMIT"
        ]
        return result, limit_prices

    def test_bid_below_fair_price_all_limits_floored_at_fair(self):
        # bid=18.80 << fair=20.05: every limit must be >= 20.05 (the floor)
        _, limit_prices = self._run_sell_all_miss()
        assert limit_prices, "expected at least one LIMIT order to be placed"
        assert all(p >= self._FAIR for p in limit_prices)

    def test_bid_below_fair_price_results_in_miss(self):
        # orders placed above bid → unfilled → MISS (0 contracts)
        (_, filled), _ = self._run_sell_all_miss()
        assert filled == 0

    def test_second_call_same_floor_no_decay(self):
        # G33 core: a second _place_with_fill_escalation call (the retry) receives a
        # fresh fair_price from the same stale cache — identical floor, same MISS.
        # Fix should decay the floor per retry_attempt so the exit eventually fills.
        for attempt in range(2):
            (_, filled), limit_prices = self._run_sell_all_miss()
            assert filled == 0, f"attempt {attempt}: expected MISS"
            assert all(p >= self._FAIR for p in limit_prices), \
                f"attempt {attempt}: floor not decayed — all limits still at fair_price"


class TestPlaceStockOrderPartialFillOnCancel:
    """
    When a step-1 limit order is partially filled before being cancelled,
    the next attempt must be for the remaining shares only (not the original
    full quantity), preventing a double-position in the broker.

    Real-world failure (2026-05-04, COIN): attempt-1 BUY 58 shares partially
    filled 44 before cancel; attempt-2 placed another BUY for 58 → broker held
    44+58=102 shares but engine tracked only 58. User had to close 44 manually.
    """

    def _make_partial_fill_client(self, total_shares=58, partial_on_attempt1=44):
        client = MagicMock()
        client.get_stock_quote.return_value = {
            "QuoteResponse": {
                "QuoteData": [{"All": {"bid": 204.81, "ask": 205.08, "lastTrade": 204.95}}]
            }
        }
        order_ids = ["order-attempt-1", "order-attempt-2"]
        call_count = [0]

        def place_side_effect(**kwargs):
            idx = call_count[0]
            call_count[0] += 1
            return {"order_id": order_ids[min(idx, len(order_ids) - 1)], "status": "open",
                    "filled_qty": 0}

        client.place_stock_order.side_effect = place_side_effect

        def order_status_side_effect(order_id):
            if order_id == "order-attempt-1":
                # attempt-1: partially filled, not complete
                return {"status": "partially_filled", "filled_qty": partial_on_attempt1}
            # attempt-2: fully filled for the remaining shares
            remaining = total_shares - partial_on_attempt1
            return {"status": "filled", "filled_qty": remaining}

        client.order_status.side_effect = order_status_side_effect
        return client

    def test_second_attempt_uses_remaining_shares_after_partial_cancel(self):
        client = self._make_partial_fill_client(total_shares=58, partial_on_attempt1=44)
        with patch(f"{_MODULE}.time.sleep", lambda _: None):
            place_stock_order(client=client, ticker="COIN", shares=58, order_action="BUY_OPEN")

        calls = client.place_stock_order.call_args_list
        assert len(calls) == 2
        assert calls[0].kwargs["quantity"] == 58
        assert calls[1].kwargs["quantity"] == 14, (
            "second attempt must request only the 14 remaining shares, not the full 58"
        )

    def test_no_extra_order_when_partial_fills_complete_the_position(self):
        # attempt-1 partially fills all requested shares before cancel fires
        client = self._make_partial_fill_client(total_shares=58, partial_on_attempt1=58)
        with patch(f"{_MODULE}.time.sleep", lambda _: None):
            place_stock_order(client=client, ticker="COIN", shares=58, order_action="BUY_OPEN")

        calls = client.place_stock_order.call_args_list
        assert len(calls) == 1, "no second order needed when partial fills all shares"

    def test_full_fill_on_attempt1_still_returns_immediately(self):
        client = _make_stock_client(bid=204.81, ask=205.08, order_status="filled")
        client.order_status.return_value = {"status": "filled", "filled_qty": 58}
        with patch(f"{_MODULE}.time.sleep", lambda _: None):
            place_stock_order(client=client, ticker="COIN", shares=58, order_action="BUY_OPEN")

        calls = client.place_stock_order.call_args_list
        assert len(calls) == 1, "fully filled on attempt-1 must not place a second order"


class TestPlaceStockOrderPostCancelRaceDetection:
    """
    After cancelling a step-1 order the engine waits 0.5 s and re-checks fill status.
    This catches the race where the broker propagates a partial fill between the
    pre-cancel check (shows 0) and the cancel acknowledgement.

    Real-world failure (2026-05-21, SHOP): step-1 partially filled 101/114 shares;
    pre-cancel order_status returned 0 (broker propagation lag); step-2 attempted
    to sell all 114 shares against the 13-share remainder and was rejected.
    """

    def _make_race_client(self, total_shares, pre_cancel_qty, post_cancel_qty):
        """
        pre_cancel_qty: what order_status shows right after the 2s sleep (before cancel)
        post_cancel_qty: what order_status shows after cancel + 0.5s sleep
        step-2 fully fills the remaining shares.
        """
        client = MagicMock()
        client.get_stock_quote.return_value = {
            "QuoteResponse": {
                "QuoteData": [{"All": {"bid": 103.70, "ask": 103.76, "lastTrade": 103.73}}]
            }
        }
        order_ids = ["order-step1", "order-step2"]
        place_count = [0]

        def place_side_effect(**kwargs):
            idx = place_count[0]
            place_count[0] += 1
            return {"order_id": order_ids[min(idx, len(order_ids) - 1)], "status": "open", "filled_qty": 0}

        client.place_stock_order.side_effect = place_side_effect

        status_call_count = [0]

        def order_status_side_effect(order_id):
            status_call_count[0] += 1
            if order_id == "order-step1":
                # call 1: pre-cancel (after 2s sleep); call 2: post-cancel (after 0.5s)
                if status_call_count[0] == 1:
                    return {"status": "open", "filled_qty": pre_cancel_qty}
                return {"status": "open", "filled_qty": post_cancel_qty}
            # order-step2: immediately filled for remaining shares
            remaining = total_shares - post_cancel_qty
            return {"status": "filled", "filled_qty": remaining}

        client.order_status.side_effect = order_status_side_effect
        return client

    def test_post_cancel_race_partial_fill_uses_remaining_for_step2(self):
        # Pre-cancel shows 0 filled; post-cancel reveals 101 of 114 filled (SHOP scenario).
        client = self._make_race_client(total_shares=114, pre_cancel_qty=0, post_cancel_qty=101)
        with patch(f"{_MODULE}.time.sleep", lambda _: None):
            place_stock_order(client=client, ticker="SHOP", shares=114, order_action="SELL_CLOSE")

        calls = client.place_stock_order.call_args_list
        assert len(calls) == 2
        assert calls[0].kwargs["quantity"] == 114
        assert calls[1].kwargs["quantity"] == 13, (
            "step-2 must sell only the 13 remaining shares, not all 114"
        )

    def test_post_cancel_race_full_fill_skips_step2(self):
        # Post-cancel reveals all 114 shares filled — no step-2 needed.
        client = self._make_race_client(total_shares=114, pre_cancel_qty=0, post_cancel_qty=114)
        with patch(f"{_MODULE}.time.sleep", lambda _: None):
            place_stock_order(client=client, ticker="SHOP", shares=114, order_action="SELL_CLOSE")

        calls = client.place_stock_order.call_args_list
        assert len(calls) == 1, "all shares filled post-cancel; must not place a second order"

    def test_no_double_count_when_pre_cancel_already_absorbed_partial(self):
        # Pre-cancel shows 50 filled; post-cancel also shows 50 (no new fill during cancel).
        # incremental = 50 - 50 = 0, so step-2 uses remaining 64 shares.
        client = self._make_race_client(total_shares=114, pre_cancel_qty=50, post_cancel_qty=50)
        with patch(f"{_MODULE}.time.sleep", lambda _: None):
            place_stock_order(client=client, ticker="SHOP", shares=114, order_action="SELL_CLOSE")

        calls = client.place_stock_order.call_args_list
        assert len(calls) == 2
        assert calls[1].kwargs["quantity"] == 64, (
            "step-2 must use 64 remaining shares; pre-cancel fill must not be double-counted"
        )


_TRANCHE_MODULE = "alpha_tech_tracker.op_momentum_strategy.order_executor"


class TestTrancheWeightedAvgFillPrice:
    """place_option_order_in_tranches() must embed a weighted-average fill price
    in last_order["avg_fill_price"] when multiple tranches fill at different prices,
    so callers can record accurate per-trade entry/exit fill prices.
    """

    _INNER = f"{_TRANCHE_MODULE}._place_with_fill_escalation"

    def test_two_tranches_different_prices_sets_weighted_avg_fill_price(self):
        """Tranche 1: 2 contracts @ $30.00, tranche 2: 2 contracts @ $32.00 → avg = $31.00."""
        client = _make_client()
        call_num = [0]

        def inner_side_effect(**kw):
            call_num[0] += 1
            return ({"order_id": f"ord-00{call_num[0]}"}, 2)

        def order_status_side_effect(order_id):
            prices = {"ord-001": "30.00", "ord-002": "32.00"}
            return {"status": "filled", "filled_avg_price": prices.get(order_id, "30.00")}

        client.order_status.side_effect = order_status_side_effect

        with patch(self._INNER, side_effect=inner_side_effect), \
             patch(f"{_TRANCHE_MODULE}.time.sleep", lambda _: None):
            order, filled = place_option_order_in_tranches(
                client=client,
                ticker=_TICKER,
                option_symbol=_SYMBOL,
                option_type=_OPTION_TYPE,
                contracts=4,
                order_action="BUY_OPEN",
                tranche_size=2,
            )

        assert filled == 4
        assert order.get("avg_fill_price") == Decimal("31.00")

    def test_three_tranches_unequal_sizes_sets_correct_weighted_avg(self):
        """3 contracts in tranches of 2+1 filling at $30 and $34 → weighted avg = $31.33."""
        client = _make_client()
        call_num = [0]

        def inner_side_effect(**kw):
            call_num[0] += 1
            qty = kw.get("contracts", 1)
            return ({"order_id": f"ord-00{call_num[0]}"}, qty)

        def order_status_side_effect(order_id):
            prices = {"ord-001": "30.00", "ord-002": "34.00"}
            return {"status": "filled", "filled_avg_price": prices.get(order_id, "30.00")}

        client.order_status.side_effect = order_status_side_effect

        with patch(self._INNER, side_effect=inner_side_effect), \
             patch(f"{_TRANCHE_MODULE}.time.sleep", lambda _: None):
            order, filled = place_option_order_in_tranches(
                client=client,
                ticker=_TICKER,
                option_symbol=_SYMBOL,
                option_type=_OPTION_TYPE,
                contracts=3,
                order_action="BUY_OPEN",
                tranche_size=2,
            )

        assert filled == 3
        expected_avg = (Decimal("30.00") * 2 + Decimal("34.00") * 1) / 3
        assert order.get("avg_fill_price") == expected_avg

    def test_single_tranche_does_not_set_avg_fill_price(self):
        """contracts <= tranche_size → single escalation, no avg_fill_price embedded."""
        client = _make_client()
        with patch(self._INNER, return_value=({"order_id": "ord-001"}, 2)), \
             patch(f"{_TRANCHE_MODULE}.time.sleep", lambda _: None):
            order, filled = place_option_order_in_tranches(
                client=client,
                ticker=_TICKER,
                option_symbol=_SYMBOL,
                option_type=_OPTION_TYPE,
                contracts=2,
                order_action="BUY_OPEN",
                tranche_size=2,
            )

        assert "avg_fill_price" not in order

    def test_tranche1_miss_does_not_set_avg_fill_price(self):
        """First tranche misses → last_order is empty, no avg_fill_price."""
        client = _make_client()
        with patch(self._INNER, return_value=({}, 0)), \
             patch(f"{_TRANCHE_MODULE}.time.sleep", lambda _: None):
            order, filled = place_option_order_in_tranches(
                client=client,
                ticker=_TICKER,
                option_symbol=_SYMBOL,
                option_type=_OPTION_TYPE,
                contracts=4,
                order_action="BUY_OPEN",
                tranche_size=2,
            )

        assert "avg_fill_price" not in order


# ---------------------------------------------------------------------------
# TestStockOrderTradeActionForwarding
# ---------------------------------------------------------------------------


class TestStockOrderTradeActionForwarding:
    """place_stock_order passes trade_action= to client.place_stock_order so that
    brokers like TradeStation can send SELLSHORT / BUYTOCOVER instead of SELL / BUY."""

    def _run(self, order_action, bid=329.0, ask=330.0):
        client = _make_stock_client(bid=bid, ask=ask)
        client.order_status.return_value = {"status": "filled"}
        with patch(f"{_MODULE}.time.sleep"):
            place_stock_order(
                client=client,
                ticker="MU",
                shares=10,
                order_action=order_action,
            )
        return client.place_stock_order.call_args_list

    def test_sell_short_forwards_trade_action(self):
        calls = self._run("SELL_SHORT")
        assert all(c.kwargs["trade_action"] == "SELL_SHORT" for c in calls)

    def test_buy_cover_forwards_trade_action(self):
        calls = self._run("BUY_COVER")
        assert all(c.kwargs["trade_action"] == "BUY_COVER" for c in calls)

    def test_buy_open_forwards_trade_action(self):
        calls = self._run("BUY_OPEN")
        assert all(c.kwargs["trade_action"] == "BUY_OPEN" for c in calls)

    def test_sell_close_forwards_trade_action(self):
        calls = self._run("SELL_CLOSE")
        assert all(c.kwargs["trade_action"] == "SELL_CLOSE" for c in calls)

    def test_trade_action_forwarded_on_market_order_step3(self):
        """Step 3 market order must also carry trade_action, not just limit orders."""
        client = _make_stock_client(bid=329.0, ask=330.0)
        with patch(f"{_MODULE}.time.sleep"):
            place_stock_order(
                client=client,
                ticker="MU",
                shares=10,
                order_action="SELL_SHORT",
            )
        market_order = client.place_stock_order.call_args_list[-1]
        assert market_order.kwargs["order_type"] == "MARKET"
        assert market_order.kwargs["trade_action"] == "SELL_SHORT"


class TestPlaceStockOrderTotalFilledQty:
    """
    place_stock_order must return total_filled_qty in the result dict so that
    trade_engine can set the correct position size when partial fills across
    multiple step-1 attempts add up to more than the last order alone.

    Real-world failure (2026-06-22, MSTR): attempt-1 SELL_SHORT 69 shares partially
    filled 48 before cancel; attempt-2 filled the remaining 21. The executor returned
    the attempt-2 order (filled_qty=21), trade_engine polled that order and set
    pos.shares=21, leaving 48 untracked short shares at the broker.
    """

    def _make_partial_fill_client(self, total_shares, partial_on_attempt1):
        client = MagicMock()
        client.get_stock_quote.return_value = {
            "QuoteResponse": {
                "QuoteData": [{"All": {"bid": 114.83, "ask": 114.92, "lastTrade": 114.87}}]
            }
        }
        order_ids = ["order-attempt-1", "order-attempt-2"]
        call_count = [0]

        def place_side_effect(**kwargs):
            idx = call_count[0]
            call_count[0] += 1
            return {"order_id": order_ids[min(idx, len(order_ids) - 1)], "status": "open", "filled_qty": 0}

        client.place_stock_order.side_effect = place_side_effect

        def order_status_side_effect(order_id):
            if order_id == "order-attempt-1":
                return {"status": "partially_filled", "filled_qty": partial_on_attempt1}
            remaining = total_shares - partial_on_attempt1
            return {"status": "filled", "filled_qty": remaining}

        client.order_status.side_effect = order_status_side_effect
        return client

    def test_partial_then_retry_total_filled_qty_is_sum_of_both_fills(self):
        client = self._make_partial_fill_client(total_shares=69, partial_on_attempt1=48)
        with patch(f"{_MODULE}.time.sleep", lambda _: None):
            result = place_stock_order(
                client=client, ticker="MSTR", shares=69, order_action="SELL_SHORT"
            )

        assert result["total_filled_qty"] == 69, (
            "total_filled_qty must be 48 (attempt-1 partial) + 21 (attempt-2 full) = 69"
        )

    def test_no_partial_total_filled_qty_equals_requested_shares(self):
        client = _make_stock_client(bid=114.83, ask=114.92, order_status="filled")
        client.order_status.return_value = {"status": "filled", "filled_qty": 69}
        with patch(f"{_MODULE}.time.sleep", lambda _: None):
            result = place_stock_order(
                client=client, ticker="MSTR", shares=69, order_action="SELL_SHORT"
            )

        assert result["total_filled_qty"] == 69

    def test_partial_fills_entire_position_total_filled_qty_is_original(self):
        # attempt-1 partial-fills the full 69 before cancel fires
        client = self._make_partial_fill_client(total_shares=69, partial_on_attempt1=69)
        with patch(f"{_MODULE}.time.sleep", lambda _: None):
            result = place_stock_order(
                client=client, ticker="MSTR", shares=69, order_action="SELL_SHORT"
            )

        assert result["total_filled_qty"] == 69

    def test_step2_fill_after_step1_partial_total_filled_qty_is_sum(self):
        # step-1 exhausted (3 attempts, no fill) — step-2 fills after step-1 partial on attempt-3
        client = MagicMock()
        client.get_stock_quote.return_value = {
            "QuoteResponse": {
                "QuoteData": [{"All": {"bid": 204.81, "ask": 205.20, "lastTrade": 205.0}}]
            }
        }
        order_ids = ["s1a1", "s1a2", "s1a3", "s2a1"]
        call_count = [0]

        def place_side_effect(**kwargs):
            idx = call_count[0]
            call_count[0] += 1
            return {"order_id": order_ids[min(idx, len(order_ids) - 1)], "status": "open", "filled_qty": 0}

        client.place_stock_order.side_effect = place_side_effect

        def order_status_side_effect(order_id):
            if order_id == "s1a1":
                return {"status": "open", "filled_qty": 0}       # attempt-1: nothing
            if order_id == "s1a2":
                return {"status": "open", "filled_qty": 0}       # attempt-2: nothing
            if order_id == "s1a3":
                return {"status": "partially_filled", "filled_qty": 10}  # attempt-3: partial 10/40
            # step-2: fills remaining 30
            return {"status": "filled", "filled_qty": 30}

        client.order_status.side_effect = order_status_side_effect

        with patch(f"{_MODULE}.time.sleep", lambda _: None):
            result = place_stock_order(
                client=client, ticker="COIN", shares=40, order_action="BUY_OPEN"
            )

        assert result["total_filled_qty"] == 40, (
            "10 (step-1 attempt-3 partial) + 30 (step-2) must equal 40"
        )

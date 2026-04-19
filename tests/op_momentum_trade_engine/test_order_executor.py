from unittest.mock import MagicMock, patch

from alpha_tech_tracker.op_momentum_strategy.order_executor import (
    _place_with_fill_escalation,
    place_stock_order,
)

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
        # No step-0: step1(mid) + step2(ask/bid) + step3(final) = 3 order_status calls
        assert client.order_status.call_count == 3

    def test_with_entry_fill_price_places_step0_order_first(self):
        client = _make_client()
        self._run(client, entry_fill_price=5.0, step0_filled=False)
        # step0 + step1(mid) + step2(ask/bid) + step3(final) = 4 order_status checks
        assert client.order_status.call_count == 4

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

    def test_step0_unfilled_then_normal_mid_escalation_places_three_total_orders(self):
        client = _make_client()
        self._run(client, entry_fill_price=5.0, step0_filled=False)
        # step0 + step1 mid + step2 + step3 limit + step3 market fallback = 5 calls
        assert client.place_option_order.call_count == 5


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
        # 3 orders placed (step1 mid, step2 bid, step3 final); 3 cancels expected
        assert client.cancel_order.call_count == 3

    def test_miss_cancel_uses_step3_order_id(self):
        client = _make_client()
        self._run_all_unfilled(client)
        last_cancel_arg = client.cancel_order.call_args_list[-1].args[0]
        assert last_cancel_arg == "ord-001"


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


class TestStep2IntrinsicFloorForSells:
    """
    On SELL_CLOSE, the step2 price (mid - spread/4) must be floored at intrinsic
    value when the wide option spread would otherwise push the limit below exercise value.
    PUT intrinsic = strike - stock_mid.
    """

    # COIN260418P00220000: strike=220, PUT
    # stock_mid=208 → intrinsic=12.00
    # opt: bid=10.50, ask=15.50 → mid=13.00, spread=5.00, quarter=1.25
    # raw step2 = 13.00 - 1.25 = 11.75 < 12.00 → should be floored to 12.00

    def _run_sell(self, client):
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

    def test_step2_price_floored_at_intrinsic_when_below(self):
        client = _make_option_client_with_stock(
            opt_bid=10.50, opt_ask=15.50, stock_bid=207.0, stock_ask=209.0
        )
        self._run_sell(client)
        step2_call = client.place_option_order.call_args_list[1]
        step2_price = step2_call.kwargs["price"]
        # floor at intrinsic $12.00 (quantized to $0.05 tick) instead of raw $11.75
        assert step2_price == 12.00

    def test_step2_price_unchanged_when_above_intrinsic(self):
        # stock drops to $194 → intrinsic = 220 - 194 = 26; step2 = 13 - 1.25 = 11.75 < 26
        # Actually let's use a stock mid where intrinsic is lower than step2:
        # stock_mid = 210 → intrinsic = 10; step2 = 11.75 > 10 → no floor
        client = _make_option_client_with_stock(
            opt_bid=10.50, opt_ask=15.50, stock_bid=210.0, stock_ask=210.0
        )
        self._run_sell(client)
        step2_call = client.place_option_order.call_args_list[1]
        step2_price = step2_call.kwargs["price"]
        # step2 = 11.75 → quantized to $11.75 (≥$3, $0.05 tick → $11.75)
        assert step2_price == 11.75

    def test_step2_floor_skipped_for_buys(self):
        # For BUY_OPEN, no intrinsic floor — get_stock_quote should not be called at step2
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
        # get_stock_quote is only called at step3 (intrinsic floor) and step2 for sells
        # For buys step3 does NOT call get_stock_quote either → call_count == 0
        assert client.get_stock_quote.call_count == 0

    def test_step2_floor_continues_gracefully_when_stock_quote_fails(self):
        client = _make_option_client_with_stock()
        client.get_stock_quote.side_effect = Exception("quote fetch failed")
        # Should not raise; step2_price falls back to original value
        self._run_sell(client)
        step2_call = client.place_option_order.call_args_list[1]
        # raw step2 price = 11.75 (no floor applied on exception)
        assert step2_call.kwargs["price"] == 11.75


class TestStep3MarketFallbackForSells:
    """
    After step3 limit times out on a SELL_CLOSE, a market order must be placed
    to ensure the position is closed. BUY_OPEN should still log FILL_ESC MISS
    and return without placing a market order.
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

    def test_sell_places_market_order_after_step3_timeout(self):
        client = _make_option_client_with_stock()
        self._run_sell_all_unfilled(client)
        all_calls = client.place_option_order.call_args_list
        last_call = all_calls[-1]
        assert last_call.kwargs["price_type"] == "MARKET"

    def test_sell_market_order_has_no_price(self):
        client = _make_option_client_with_stock()
        self._run_sell_all_unfilled(client)
        last_call = client.place_option_order.call_args_list[-1]
        assert last_call.kwargs["price"] is None

    def test_sell_step3_limit_is_cancelled_before_market_order(self):
        client = _make_option_client_with_stock()
        # Track cancel and place calls in order
        call_order = []
        client.cancel_order.side_effect = lambda oid: call_order.append(("cancel", oid))
        original_place = MagicMock(return_value={"order_id": "ord-001", "status": "open"})
        client.place_option_order.side_effect = lambda **kw: call_order.append(
            ("place", kw.get("price_type"))
        ) or {"order_id": "ord-001", "status": "open"}

        self._run_sell_all_unfilled(client)

        # Last two events: cancel step3 limit then place market
        assert call_order[-2][0] == "cancel"
        assert call_order[-1] == ("place", "MARKET")

    def test_buy_does_not_place_market_order_on_step3_miss(self):
        client = _make_option_client_with_stock()
        self._run_buy_all_unfilled(client)
        all_calls = client.place_option_order.call_args_list
        price_types = [c.kwargs["price_type"] for c in all_calls]
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

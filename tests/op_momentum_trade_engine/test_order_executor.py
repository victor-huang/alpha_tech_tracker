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
        # step0 limit + step1 mid limit + step2 bid limit = 3 limit orders
        # (no market order since step2 also returns unfilled and escalates to market=4th call)
        assert client.place_option_order.call_count == 4


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

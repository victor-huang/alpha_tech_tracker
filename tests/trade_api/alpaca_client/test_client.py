import pytest
from datetime import datetime, date
from unittest.mock import MagicMock, patch

from alpha_tech_tracker.trade_api.alpaca_client.client import AlpacaAPIClient


@pytest.mark.alpaca
@pytest.mark.credentials
def test_get_accounts():
    client = AlpacaAPIClient(is_paper_trading=True)
    account_info = client.get_accounts()

    assert account_info is not None
    assert "account_id" in account_info
    assert "buying_power" in account_info
    assert "portfolio_value" in account_info


@pytest.mark.alpaca
@pytest.mark.credentials
def test_get_stock_quote():
    client = AlpacaAPIClient(is_paper_trading=True)
    quote_response = client.get_stock_quote("TSLA")

    assert quote_response["QuoteResponse"] is not None
    assert quote_response["QuoteResponse"]["QuoteData"] is not None
    assert "bid" in quote_response["QuoteResponse"]["QuoteData"][0]["All"]
    assert "ask" in quote_response["QuoteResponse"]["QuoteData"][0]["All"]


@pytest.mark.alpaca
@pytest.mark.credentials
def test_get_multiple_stock_quotes():
    client = AlpacaAPIClient(is_paper_trading=True)
    quotes = client.get_stock_quote(["TSLA", "AAPL"])

    assert "TSLA" in quotes
    assert "AAPL" in quotes
    assert quotes["TSLA"]["QuoteResponse"] is not None
    assert quotes["AAPL"]["QuoteResponse"] is not None


@pytest.mark.alpaca
@pytest.mark.credentials
def test_get_option_quote():
    client = AlpacaAPIClient(is_paper_trading=True)

    try:
        contracts = client.get_options_contracts(
            underlying_symbol="TSLA", option_type="call", limit=1
        )

        if len(contracts) == 0:
            pytest.skip("No option contracts available")

        expiration = contracts[0]["expiration_date"]
        strike = contracts[0]["strike_price"]
        option_key = f"{expiration} s{strike}"

        quote_response = client.get_option_quote(
            symbol="TSLA", option_key=option_key, option_type="CALL"
        )

        assert quote_response["QuoteResponse"] is not None
        assert quote_response["QuoteResponse"]["QuoteData"] is not None
        assert "bid" in quote_response["QuoteResponse"]["QuoteData"][0]["All"]
        assert "ask" in quote_response["QuoteResponse"]["QuoteData"][0]["All"]
    except Exception as e:
        if "400" in str(e) or "subscription" in str(e).lower():
            pytest.skip(
                f"Options data not available (may require subscription): {str(e)}"
            )
        raise


@pytest.mark.alpaca
@pytest.mark.credentials
def test_get_price_from_quote():
    client = AlpacaAPIClient(is_paper_trading=True)
    quote = client.get_stock_quote("TSLA")
    price_info = client.get_price_from_quote(quote)

    assert "bid" in price_info
    assert "ask" in price_info
    assert "mid" in price_info
    assert "s-mid" in price_info
    assert price_info["bid"] < price_info["ask"]


@pytest.mark.alpaca
@pytest.mark.credentials
def test_get_options_contracts():
    client = AlpacaAPIClient(is_paper_trading=True)
    contracts = client.get_options_contracts(
        underlying_symbol="TSLA", option_type="call", limit=5
    )

    assert contracts is not None
    assert len(contracts) > 0
    assert "symbol" in contracts[0]
    assert "underlying_symbol" in contracts[0]
    assert "strike_price" in contracts[0]
    assert contracts[0]["underlying_symbol"] == "TSLA"


@pytest.mark.alpaca
@pytest.mark.credentials
def test_place_stock_order():
    client = AlpacaAPIClient(is_paper_trading=True)

    order = client.place_stock_order(
        symbol="TSLA", quantity=1, side="BUY", order_type="LIMIT", limit_price=1.00
    )

    assert order is not None
    assert "order_id" in order
    assert order["symbol"] == "TSLA"
    assert order["quantity"] == 1
    assert order["side"] == "buy"

    client.cancel_order(order["order_id"])


@pytest.mark.alpaca
@pytest.mark.credentials
def test_place_option_order():
    client = AlpacaAPIClient(is_paper_trading=True)

    try:
        contracts = client.get_options_contracts(
            underlying_symbol="TSLA", option_type="call", limit=1
        )

        if len(contracts) == 0:
            pytest.skip("No option contracts available")

        contract_symbol = contracts[0]["symbol"]
        expiration = contracts[0]["expiration_date"]
        strike = contracts[0]["strike_price"]

        option_key = f"{expiration} s{strike}"

        order = client.place_option_order(
            symbol="TSLA",
            option_key=option_key,
            price=0.10,
            option_type="CALL",
            order_action="BUY_OPEN",
            quantity=1,
        )

        assert order is not None
        assert "order_id" in order
        assert order["quantity"] == 1

        client.cancel_order(order["order_id"])
    except Exception as e:
        if "not found" in str(e).lower() or "42210000" in str(e):
            pytest.skip(f"Options trading not available in paper account: {str(e)}")
        raise


@pytest.mark.alpaca
@pytest.mark.credentials
def test_order_status():
    client = AlpacaAPIClient(is_paper_trading=True)

    order = client.place_stock_order(
        symbol="TSLA", quantity=1, side="BUY", order_type="LIMIT", limit_price=1.00
    )

    order_id = order["order_id"]
    status = client.order_status(order_id)

    assert status is not None
    assert status["order_id"] == order_id
    assert "status" in status
    assert status["symbol"] == "TSLA"

    client.cancel_order(order_id)


@pytest.mark.alpaca
@pytest.mark.credentials
def test_cancel_order():
    client = AlpacaAPIClient(is_paper_trading=True)

    order = client.place_stock_order(
        symbol="TSLA", quantity=1, side="BUY", order_type="LIMIT", limit_price=1.00
    )

    order_id = order["order_id"]
    cancel_result = client.cancel_order(order_id)

    assert cancel_result is not None
    assert cancel_result["order_id"] == order_id
    assert cancel_result["status"] == "cancelled"


class TestGetFilledOrders:
    def _make_mock_order(self, order_id, side, filled_avg_price, filled_qty, filled_at):
        o = MagicMock()
        o.id = order_id
        o.side.value = side
        o.filled_avg_price = filled_avg_price
        o.filled_qty = filled_qty
        o.filled_at = filled_at
        return o

    def test_returns_filled_orders_with_correct_fields(self):
        client = AlpacaAPIClient.__new__(AlpacaAPIClient)
        client._trading_client = MagicMock()
        client._trading_client.get_orders.return_value = [
            self._make_mock_order("abc123", "sell", 63.4, 4.0, datetime(2026, 4, 13, 19, 53, 14)),
            self._make_mock_order("def456", "buy", 65.75, 1.0, datetime(2026, 4, 13, 19, 52, 15)),
        ]

        result = client.get_filled_orders("META260417C00570000")

        assert len(result) == 2
        assert result[0]["order_id"] == "abc123"
        assert result[0]["filled_avg_price"] == 63.4
        assert result[0]["filled_qty"] == 4.0
        assert result[0]["side"] == "sell"

    def test_excludes_orders_with_no_fill_price(self):
        client = AlpacaAPIClient.__new__(AlpacaAPIClient)
        client._trading_client = MagicMock()
        client._trading_client.get_orders.return_value = [
            self._make_mock_order("abc123", "sell", 63.4, 4.0, datetime(2026, 4, 13, 19, 53, 14)),
            self._make_mock_order("canceled1", "buy", None, 0.0, None),
        ]

        result = client.get_filled_orders("META260417C00570000")

        assert len(result) == 1
        assert result[0]["order_id"] == "abc123"

    def test_uses_today_midnight_as_after_param(self):
        client = AlpacaAPIClient.__new__(AlpacaAPIClient)
        client._trading_client = MagicMock()
        client._trading_client.get_orders.return_value = []
        today = date(2026, 4, 25)

        with patch("alpha_tech_tracker.trade_api.alpaca_client.client.date") as mock_date:
            mock_date.today.return_value = today
            client.get_filled_orders("META260417C00570000")

        call_kwargs = client._trading_client.get_orders.call_args[0][0]
        assert call_kwargs.after.date() == today

    def test_uses_limit_500_regardless_of_limit_param(self):
        client = AlpacaAPIClient.__new__(AlpacaAPIClient)
        client._trading_client = MagicMock()
        client._trading_client.get_orders.return_value = []

        client.get_filled_orders("META260417C00570000", limit=3)

        call_kwargs = client._trading_client.get_orders.call_args[0][0]
        assert call_kwargs.limit == 500

    def test_returns_empty_list_when_no_fills_today(self):
        client = AlpacaAPIClient.__new__(AlpacaAPIClient)
        client._trading_client = MagicMock()
        client._trading_client.get_orders.return_value = []

        result = client.get_filled_orders("NVDA260417C00800000")

        assert result == []

    def test_passes_symbol_as_list(self):
        client = AlpacaAPIClient.__new__(AlpacaAPIClient)
        client._trading_client = MagicMock()
        client._trading_client.get_orders.return_value = []

        client.get_filled_orders("META260417C00570000")

        call_kwargs = client._trading_client.get_orders.call_args[0][0]
        assert call_kwargs.symbols == ["META260417C00570000"]

    @pytest.mark.alpaca
    @pytest.mark.credentials
    def test_live_api_returns_list_and_accepts_today_scope(self):
        client = AlpacaAPIClient(is_paper_trading=True)

        result = client.get_filled_orders("META260417C00570000")

        assert isinstance(result, list)
        for r in result:
            assert "order_id" in r
            assert "filled_avg_price" in r
            assert "filled_qty" in r
            assert "side" in r
            assert "filled_at" in r
            assert r["filled_avg_price"] is not None

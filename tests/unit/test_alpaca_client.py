"""
Unit tests for Alpaca API Client critical paths.

Tests quote retrieval, order placement, and order management with mocked responses.
These tests ensure API integration logic works correctly without making real API calls.

Coverage Target: Critical paths only
"""

import pytest
from unittest.mock import Mock, patch
from alpaca.data.enums import DataFeed
from alpha_tech_tracker.trade_api.alpaca_client.client import (
    AlpacaAPIClient,
    APIError,
    APIInvalidArgumentError,
)


class TestAlpacaClientInitialization:
    """Test client initialization and configuration."""

    def test_client_init_with_credentials(self):
        """Client should initialize with provided credentials."""
        client = AlpacaAPIClient(
            api_key="test_key", secret_key="test_secret", is_paper_trading=True
        )

        assert client._api_key == "test_key"
        assert client._secret_key == "test_secret"
        assert client._is_paper_trading == True

    @patch.dict(
        "os.environ", {"ALPACA_API_KEY": "env_key", "ALPACA_SECRET_KEY": "env_secret"}
    )
    def test_client_init_from_environment(self):
        """Client should fallback to environment variables."""
        client = AlpacaAPIClient(is_paper_trading=False)

        assert client._api_key == "env_key"
        assert client._secret_key == "env_secret"
        assert client._is_paper_trading == False


class TestAccountOperations:
    """Test account information retrieval."""

    @patch("alpha_tech_tracker.trade_api.alpaca_client.client.TradingClient")
    def test_get_accounts(self, mock_trading_client):
        """Should retrieve and format account information."""
        # Mock account response
        mock_account = Mock()
        mock_account.account_number = "12345"
        mock_account.account_blocked = False
        mock_account.cash = "10000.50"
        mock_account.buying_power = "40000.00"
        mock_account.portfolio_value = "50000.00"
        mock_account.equity = "50000.00"

        mock_client_instance = Mock()
        mock_client_instance.get_account.return_value = mock_account
        mock_trading_client.return_value = mock_client_instance

        client = AlpacaAPIClient(api_key="test", secret_key="test")
        account_info = client.get_accounts()

        assert account_info["account_id"] == "12345"
        assert account_info["cash"] == 10000.50
        assert account_info["buying_power"] == 40000.00
        assert account_info["portfolio_value"] == 50000.00
        assert account_info["raw_response"] == mock_account


class TestStockQuoteRetrieval:
    """Test stock quote retrieval."""

    @patch(
        "alpha_tech_tracker.trade_api.alpaca_client.client.StockHistoricalDataClient"
    )
    def test_get_stock_quote_single_symbol(self, mock_data_client):
        """Should retrieve quote for single stock symbol."""
        # Mock quote response
        mock_quote = Mock()
        mock_quote.bid_price = 150.50
        mock_quote.ask_price = 150.75
        mock_quote.bid_size = 100
        mock_quote.ask_size = 200

        mock_client_instance = Mock()
        mock_client_instance.get_stock_latest_quote.return_value = {"AAPL": mock_quote}
        mock_data_client.return_value = mock_client_instance

        client = AlpacaAPIClient(api_key="test", secret_key="test")
        quote = client.get_stock_quote("AAPL")

        assert quote["QuoteResponse"]["QuoteData"][0]["All"]["bid"] == 150.50
        assert quote["QuoteResponse"]["QuoteData"][0]["All"]["ask"] == 150.75
        assert quote["QuoteResponse"]["QuoteData"][0]["All"]["bid_size"] == 100
        assert quote["QuoteResponse"]["QuoteData"][0]["All"]["ask_size"] == 200

    @patch(
        "alpha_tech_tracker.trade_api.alpaca_client.client.StockHistoricalDataClient"
    )
    def test_get_stock_quote_multiple_symbols(self, mock_data_client):
        """Should retrieve quotes for multiple symbols."""
        mock_quote_aapl = Mock()
        mock_quote_aapl.bid_price = 150.50
        mock_quote_aapl.ask_price = 150.75
        mock_quote_aapl.bid_size = 100
        mock_quote_aapl.ask_size = 200

        mock_quote_tsla = Mock()
        mock_quote_tsla.bid_price = 250.00
        mock_quote_tsla.ask_price = 250.25
        mock_quote_tsla.bid_size = 50
        mock_quote_tsla.ask_size = 75

        mock_client_instance = Mock()
        mock_client_instance.get_stock_latest_quote.return_value = {
            "AAPL": mock_quote_aapl,
            "TSLA": mock_quote_tsla,
        }
        mock_data_client.return_value = mock_client_instance

        client = AlpacaAPIClient(api_key="test", secret_key="test")
        quotes = client.get_stock_quote(["AAPL", "TSLA"])

        assert "AAPL" in quotes
        assert "TSLA" in quotes
        assert quotes["AAPL"]["QuoteResponse"]["QuoteData"][0]["All"]["bid"] == 150.50
        assert quotes["TSLA"]["QuoteResponse"]["QuoteData"][0]["All"]["bid"] == 250.00


class TestOptionQuoteRetrieval:
    """Test option quote retrieval."""

    @patch(
        "alpha_tech_tracker.trade_api.alpaca_client.client.OptionHistoricalDataClient"
    )
    def test_get_option_quote(self, mock_option_client):
        """Should retrieve and format option quote."""
        # Mock option quote response
        mock_quote = Mock()
        mock_quote.bid_price = 5.50
        mock_quote.ask_price = 5.75
        mock_quote.bid_size = 10
        mock_quote.ask_size = 20

        mock_client_instance = Mock()
        mock_client_instance.get_option_latest_quote.return_value = {
            "TSLA241020C00200000": mock_quote
        }
        mock_option_client.return_value = mock_client_instance

        client = AlpacaAPIClient(api_key="test", secret_key="test")
        quote = client.get_option_quote(
            symbol="TSLA", option_key="2024-10-20 s200", option_type="CALL"
        )

        assert quote["QuoteResponse"]["QuoteData"][0]["All"]["bid"] == 5.50
        assert quote["QuoteResponse"]["QuoteData"][0]["All"]["ask"] == 5.75

    def test_build_option_symbol(self):
        """Should correctly build option symbol from components."""
        client = AlpacaAPIClient(api_key="test", secret_key="test")

        option_symbol = client._build_option_symbol(
            symbol="TSLA", option_key="2024-10-20 s200", option_type="CALL"
        )

        assert option_symbol == "TSLA241020C00200000"

    def test_build_option_symbol_put(self):
        """Should correctly build PUT option symbol."""
        client = AlpacaAPIClient(api_key="test", secret_key="test")

        option_symbol = client._build_option_symbol(
            symbol="AAPL", option_key="2024-11-15 s150", option_type="PUT"
        )

        assert option_symbol == "AAPL241115P00150000"


class TestStockOrderPlacement:
    """Test stock order placement."""

    @patch("alpha_tech_tracker.trade_api.alpaca_client.client.TradingClient")
    def test_place_stock_market_order(self, mock_trading_client):
        """Should place market order for stock."""
        mock_order = Mock()
        mock_order.id = "order-123"
        mock_order.client_order_id = "client-123"
        mock_order.symbol = "AAPL"
        mock_order.qty = "10"
        mock_order.filled_qty = "0"
        mock_order.side = Mock(value="buy")
        mock_order.type = Mock(value="market")
        mock_order.status = Mock(value="accepted")
        mock_order.limit_price = None
        mock_order.filled_avg_price = None
        mock_order.submitted_at = "2024-01-01T10:00:00Z"

        mock_client_instance = Mock()
        mock_client_instance.submit_order.return_value = mock_order
        mock_trading_client.return_value = mock_client_instance

        client = AlpacaAPIClient(api_key="test", secret_key="test")
        order_result = client.place_stock_order(
            symbol="AAPL", quantity=10, side="BUY", order_type="MARKET"
        )

        assert order_result["order_id"] == "order-123"
        assert order_result["symbol"] == "AAPL"
        assert order_result["quantity"] == 10.0
        assert order_result["side"] == "buy"
        assert order_result["type"] == "market"

    @patch("alpha_tech_tracker.trade_api.alpaca_client.client.TradingClient")
    def test_place_stock_limit_order(self, mock_trading_client):
        """Should place limit order for stock."""
        mock_order = Mock()
        mock_order.id = "order-456"
        mock_order.client_order_id = "client-456"
        mock_order.symbol = "TSLA"
        mock_order.qty = "5"
        mock_order.filled_qty = "0"
        mock_order.side = Mock(value="sell")
        mock_order.type = Mock(value="limit")
        mock_order.status = Mock(value="accepted")
        mock_order.limit_price = "250.50"
        mock_order.filled_avg_price = None
        mock_order.submitted_at = "2024-01-01T11:00:00Z"

        mock_client_instance = Mock()
        mock_client_instance.submit_order.return_value = mock_order
        mock_trading_client.return_value = mock_client_instance

        client = AlpacaAPIClient(api_key="test", secret_key="test")
        order_result = client.place_stock_order(
            symbol="TSLA",
            quantity=5,
            side="SELL",
            order_type="LIMIT",
            limit_price=250.50,
        )

        assert order_result["order_id"] == "order-456"
        assert order_result["limit_price"] == 250.50

    @patch("alpha_tech_tracker.trade_api.alpaca_client.client.TradingClient")
    def test_place_limit_order_without_price_raises_error(self, mock_trading_client):
        """Should raise error when limit_price missing for LIMIT order."""
        mock_trading_client.return_value = Mock()

        client = AlpacaAPIClient(api_key="test", secret_key="test")

        with pytest.raises(APIInvalidArgumentError, match="limit_price is required"):
            client.place_stock_order(
                symbol="AAPL",
                quantity=10,
                side="BUY",
                order_type="LIMIT",
                # Missing limit_price!
            )

    @patch("alpha_tech_tracker.trade_api.alpaca_client.client.TradingClient")
    def test_place_invalid_order_type_raises_error(self, mock_trading_client):
        """Should raise error for unsupported order type."""
        mock_trading_client.return_value = Mock()

        client = AlpacaAPIClient(api_key="test", secret_key="test")

        with pytest.raises(APIInvalidArgumentError, match="Unsupported order type"):
            client.place_stock_order(
                symbol="AAPL",
                quantity=10,
                side="BUY",
                order_type="STOP_LOSS",  # Unsupported
            )


class TestOptionOrderPlacement:
    """Test option order placement."""

    @patch("alpha_tech_tracker.trade_api.alpaca_client.client.TradingClient")
    def test_place_option_limit_order(self, mock_trading_client):
        """Should place limit order for option."""
        mock_order = Mock()
        mock_order.id = "option-order-123"
        mock_order.client_order_id = "client-opt-123"
        mock_order.symbol = "TSLA241020C00200000"
        mock_order.qty = "1"
        mock_order.filled_qty = "0"
        mock_order.side = Mock(value="buy")
        mock_order.type = Mock(value="limit")
        mock_order.status = Mock(value="accepted")
        mock_order.limit_price = "5.50"
        mock_order.filled_avg_price = None
        mock_order.submitted_at = "2024-01-01T10:00:00Z"

        mock_client_instance = Mock()
        mock_client_instance.submit_order.return_value = mock_order
        mock_trading_client.return_value = mock_client_instance

        client = AlpacaAPIClient(api_key="test", secret_key="test")
        order_result = client.place_option_order(
            symbol="TSLA",
            option_key="2024-10-20 s200",
            price=5.50,
            option_type="CALL",
            order_action="BUY_OPEN",
            quantity=1,
        )

        assert order_result["order_id"] == "option-order-123"
        assert "TSLA241020C00200000" in order_result["symbol"]
        assert order_result["limit_price"] == 5.50

    @patch("alpha_tech_tracker.trade_api.alpaca_client.client.TradingClient")
    def test_place_option_order_without_price_raises_error(self, mock_trading_client):
        """Should raise error when price missing for LIMIT option order."""
        mock_trading_client.return_value = Mock()

        client = AlpacaAPIClient(api_key="test", secret_key="test")

        with pytest.raises(APIInvalidArgumentError, match="price is required"):
            client.place_option_order(
                symbol="TSLA",
                option_key="2024-10-20 s200",
                option_type="CALL",
                order_action="BUY_OPEN",
                quantity=1,
                # Missing price!
            )


class TestOrderManagement:
    """Test order status and cancellation."""

    @patch("alpha_tech_tracker.trade_api.alpaca_client.client.TradingClient")
    def test_order_status(self, mock_trading_client):
        """Should retrieve order status."""
        mock_order = Mock()
        mock_order.id = "order-123"
        mock_order.client_order_id = "client-123"
        mock_order.symbol = "AAPL"
        mock_order.qty = "10"
        mock_order.filled_qty = "5"
        mock_order.side = Mock(value="buy")
        mock_order.type = Mock(value="limit")
        mock_order.status = Mock(value="partially_filled")
        mock_order.limit_price = "150.00"
        mock_order.stop_price = None
        mock_order.filled_avg_price = "149.75"
        mock_order.submitted_at = "2024-01-01T10:00:00Z"
        mock_order.filled_at = "2024-01-01T10:05:00Z"
        mock_order.canceled_at = None
        mock_order.expired_at = None

        mock_client_instance = Mock()
        mock_client_instance.get_order_by_id.return_value = mock_order
        mock_trading_client.return_value = mock_client_instance

        client = AlpacaAPIClient(api_key="test", secret_key="test")
        status = client.order_status("order-123")

        assert status["order_id"] == "order-123"
        assert status["status"] == "partially_filled"
        assert status["filled_qty"] == 5.0
        assert status["filled_avg_price"] == 149.75

    @patch("alpha_tech_tracker.trade_api.alpaca_client.client.TradingClient")
    def test_cancel_order_success(self, mock_trading_client):
        """Should successfully cancel order."""
        mock_client_instance = Mock()
        mock_client_instance.cancel_order_by_id.return_value = None
        mock_trading_client.return_value = mock_client_instance

        client = AlpacaAPIClient(api_key="test", secret_key="test")
        result = client.cancel_order("order-123")

        assert result["order_id"] == "order-123"
        assert result["status"] == "cancelled"
        assert "successfully" in result["message"].lower()

    @patch("alpha_tech_tracker.trade_api.alpaca_client.client.TradingClient")
    def test_cancel_order_failure(self, mock_trading_client):
        """Should handle order cancellation failure."""
        mock_client_instance = Mock()
        mock_client_instance.cancel_order_by_id.side_effect = Exception(
            "Order not found"
        )
        mock_trading_client.return_value = mock_client_instance

        client = AlpacaAPIClient(api_key="test", secret_key="test")

        with pytest.raises(APIError, match="Order not found"):
            client.cancel_order("invalid-order-id")


class TestPriceCalculations:
    """Test price calculation utilities."""

    def test_get_price_from_quote(self):
        """Should calculate smart mid price from quote."""
        client = AlpacaAPIClient(api_key="test", secret_key="test")

        quote = {"QuoteResponse": {"QuoteData": [{"All": {"bid": 5.00, "ask": 5.50}}]}}

        prices = client.get_price_from_quote(
            quote, percentage_deviate_from_mid_point=-0.1
        )

        assert prices["bid"] == 5.00
        assert prices["ask"] == 5.50
        assert prices["mid"] == 5.25
        # Smart mid should be slightly below mid (10% toward bid)
        assert prices["s-mid"] < prices["mid"]
        assert prices["s-mid"] > prices["bid"]

    def test_round_nearest(self):
        """Should round to nearest smallest unit."""
        client = AlpacaAPIClient(api_key="test", secret_key="test")

        assert client.round_nearest(5.27, 0.05) == pytest.approx(5.25)
        assert client.round_nearest(5.28, 0.05) == pytest.approx(5.30)
        assert client.round_nearest(5.25, 0.05) == pytest.approx(5.25)
        assert client.round_nearest(150.51, 1.0) == pytest.approx(151.0)


_ALPACA_PATCH = "alpha_tech_tracker.trade_api.alpaca_client.client"


def _make_alpaca_raw_quote(bid=150.50, ask=150.75):
    q = Mock()
    q.bid_price = bid
    q.ask_price = ask
    q.bid_size = 100
    q.ask_size = 200
    return q


def _make_ts_response(bid, ask):
    return {
        "QuoteResponse": {
            "QuoteData": [{"All": {"bid": bid, "ask": ask, "bid_size": 50, "ask_size": 50, "last": None}}]
        }
    }


class TestGetStockQuoteWithFallback:
    """Tests for get_stock_quote IEX → TradeStation SIP quote routing.

    Multi-symbol error paths (TS failure fallback, both-fail RuntimeError) are not
    covered — primary use case is single-symbol and those branches differ only in
    the final return (result vs result[symbols[0]]).
    """

    def test_sip_quote_client_stored_on_init(self):
        ts_client = Mock()
        with patch(f"{_ALPACA_PATCH}.TradingClient"), \
             patch(f"{_ALPACA_PATCH}.StockHistoricalDataClient"), \
             patch(f"{_ALPACA_PATCH}.OptionHistoricalDataClient"):
            client = AlpacaAPIClient(api_key="test", secret_key="test", sip_quote_client=ts_client)

        assert client._sip_quote_client is ts_client

    def test_no_fallback_uses_alpaca_on_iex(self):
        with patch(f"{_ALPACA_PATCH}.TradingClient"), \
             patch(f"{_ALPACA_PATCH}.StockHistoricalDataClient") as mock_data, \
             patch(f"{_ALPACA_PATCH}.OptionHistoricalDataClient"):
            mock_data.return_value.get_stock_latest_quote.return_value = {"TSLA": _make_alpaca_raw_quote(150.50, 150.75)}
            client = AlpacaAPIClient(api_key="test", secret_key="test")

            quote = client.get_stock_quote("TSLA", feed=DataFeed.IEX)

        assert quote["QuoteResponse"]["QuoteData"][0]["All"]["bid"] == 150.50
        mock_data.return_value.get_stock_latest_quote.assert_called_once()

    def test_fallback_ignored_when_feed_is_sip(self):
        ts_client = Mock()
        with patch(f"{_ALPACA_PATCH}.TradingClient"), \
             patch(f"{_ALPACA_PATCH}.StockHistoricalDataClient") as mock_data, \
             patch(f"{_ALPACA_PATCH}.OptionHistoricalDataClient"):
            mock_data.return_value.get_stock_latest_quote.return_value = {"TSLA": _make_alpaca_raw_quote(150.50, 150.75)}
            client = AlpacaAPIClient(api_key="test", secret_key="test", sip_quote_client=ts_client)

            quote = client.get_stock_quote("TSLA", feed=DataFeed.SIP)

        assert quote["QuoteResponse"]["QuoteData"][0]["All"]["bid"] == 150.50
        ts_client.get_stock_quote.assert_not_called()

    def test_returns_ts_quote_when_feed_is_iex(self):
        ts_client = Mock()
        ts_client.get_stock_quote.return_value = _make_ts_response(150.52, 150.73)
        with patch(f"{_ALPACA_PATCH}.TradingClient"), \
             patch(f"{_ALPACA_PATCH}.StockHistoricalDataClient") as mock_data, \
             patch(f"{_ALPACA_PATCH}.OptionHistoricalDataClient"):
            mock_data.return_value.get_stock_latest_quote.return_value = {"TSLA": _make_alpaca_raw_quote(150.50, 150.75)}
            client = AlpacaAPIClient(api_key="test", secret_key="test", sip_quote_client=ts_client)

            quote = client.get_stock_quote("TSLA", feed=DataFeed.IEX)

        assert quote["QuoteResponse"]["QuoteData"][0]["All"]["bid"] == 150.52
        assert quote["QuoteResponse"]["QuoteData"][0]["All"]["ask"] == 150.73

    def test_both_apis_called_for_comparison(self):
        ts_client = Mock()
        ts_client.get_stock_quote.return_value = _make_ts_response(150.52, 150.73)
        with patch(f"{_ALPACA_PATCH}.TradingClient"), \
             patch(f"{_ALPACA_PATCH}.StockHistoricalDataClient") as mock_data, \
             patch(f"{_ALPACA_PATCH}.OptionHistoricalDataClient"):
            mock_data.return_value.get_stock_latest_quote.return_value = {"TSLA": _make_alpaca_raw_quote()}
            client = AlpacaAPIClient(api_key="test", secret_key="test", sip_quote_client=ts_client)

            client.get_stock_quote("TSLA", feed=DataFeed.IEX)

        mock_data.return_value.get_stock_latest_quote.assert_called_once()
        ts_client.get_stock_quote.assert_called_once_with("TSLA")

    def test_ts_failure_falls_back_to_alpaca_result(self):
        ts_client = Mock()
        ts_client.get_stock_quote.side_effect = Exception("TS connection error")
        with patch(f"{_ALPACA_PATCH}.TradingClient"), \
             patch(f"{_ALPACA_PATCH}.StockHistoricalDataClient") as mock_data, \
             patch(f"{_ALPACA_PATCH}.OptionHistoricalDataClient"):
            mock_data.return_value.get_stock_latest_quote.return_value = {"TSLA": _make_alpaca_raw_quote(150.50, 150.75)}
            client = AlpacaAPIClient(api_key="test", secret_key="test", sip_quote_client=ts_client)

            quote = client.get_stock_quote("TSLA", feed=DataFeed.IEX)

        assert quote["QuoteResponse"]["QuoteData"][0]["All"]["bid"] == 150.50
        assert quote["QuoteResponse"]["QuoteData"][0]["All"]["ask"] == 150.75

    def test_alpaca_failure_still_returns_ts_quote(self):
        ts_client = Mock()
        ts_client.get_stock_quote.return_value = _make_ts_response(150.52, 150.73)
        with patch(f"{_ALPACA_PATCH}.TradingClient"), \
             patch(f"{_ALPACA_PATCH}.StockHistoricalDataClient") as mock_data, \
             patch(f"{_ALPACA_PATCH}.OptionHistoricalDataClient"):
            mock_data.return_value.get_stock_latest_quote.side_effect = Exception("Alpaca timeout")
            client = AlpacaAPIClient(api_key="test", secret_key="test", sip_quote_client=ts_client)

            quote = client.get_stock_quote("TSLA", feed=DataFeed.IEX)

        assert quote["QuoteResponse"]["QuoteData"][0]["All"]["bid"] == 150.52

    def test_multi_symbol_returns_ts_quotes_keyed_by_symbol(self):
        ts_client = Mock()
        ts_client.get_stock_quote.return_value = {
            "TSLA": _make_ts_response(310.1, 310.4),
            "AAPL": _make_ts_response(150.1, 150.4),
        }
        with patch(f"{_ALPACA_PATCH}.TradingClient"), \
             patch(f"{_ALPACA_PATCH}.StockHistoricalDataClient") as mock_data, \
             patch(f"{_ALPACA_PATCH}.OptionHistoricalDataClient"):
            mock_data.return_value.get_stock_latest_quote.return_value = {
                "TSLA": _make_alpaca_raw_quote(310.0, 310.5),
                "AAPL": _make_alpaca_raw_quote(150.0, 150.5),
            }
            client = AlpacaAPIClient(api_key="test", secret_key="test", sip_quote_client=ts_client)

            quotes = client.get_stock_quote(["TSLA", "AAPL"], feed=DataFeed.IEX)

        assert quotes["TSLA"]["QuoteResponse"]["QuoteData"][0]["All"]["bid"] == 310.1
        assert quotes["AAPL"]["QuoteResponse"]["QuoteData"][0]["All"]["bid"] == 150.1
        ts_client.get_stock_quote.assert_called_once_with(["TSLA", "AAPL"])

    def test_quote_compare_log_contains_both_bid_ask(self, caplog):
        import logging
        ts_client = Mock()
        ts_client.get_stock_quote.return_value = _make_ts_response(150.52, 150.73)
        with patch(f"{_ALPACA_PATCH}.TradingClient"), \
             patch(f"{_ALPACA_PATCH}.StockHistoricalDataClient") as mock_data, \
             patch(f"{_ALPACA_PATCH}.OptionHistoricalDataClient"):
            mock_data.return_value.get_stock_latest_quote.return_value = {"TSLA": _make_alpaca_raw_quote(150.50, 150.75)}
            client = AlpacaAPIClient(api_key="test", secret_key="test", sip_quote_client=ts_client)

            with caplog.at_level(logging.INFO, logger="trade_api.alpaca"):
                client.get_stock_quote("TSLA", feed=DataFeed.IEX)

        assert "QUOTE COMPARE" in caplog.text
        assert "TSLA" in caplog.text
        assert "150.50" in caplog.text
        assert "150.52" in caplog.text

    def test_both_sources_fail_raises_runtime_error(self):
        ts_client = Mock()
        ts_client.get_stock_quote.side_effect = Exception("TS down")
        with patch(f"{_ALPACA_PATCH}.TradingClient"), \
             patch(f"{_ALPACA_PATCH}.StockHistoricalDataClient") as mock_data, \
             patch(f"{_ALPACA_PATCH}.OptionHistoricalDataClient"):
            mock_data.return_value.get_stock_latest_quote.side_effect = Exception("Alpaca down")
            client = AlpacaAPIClient(api_key="test", secret_key="test", sip_quote_client=ts_client)

            with pytest.raises(RuntimeError, match="Both quote sources failed"):
                client.get_stock_quote("TSLA", feed=DataFeed.IEX)

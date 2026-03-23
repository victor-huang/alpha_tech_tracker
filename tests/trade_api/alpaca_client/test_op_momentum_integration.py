import threading

import pytest
from alpaca.data.live import StockDataStream

from alpha_tech_tracker.op_momentum_strategy.op_momentum_trade_engine import (
    OptionContractSelector,
    PositionSizer,
    TickerSelector,
)
from alpha_tech_tracker.trade_api.alpaca_client.client import AlpacaAPIClient

_OPTIONS_NOT_ENABLED_CODES = ("40110000", "42210000")
_NO_POSITION_CODE = "40310000"  # account not eligible to trade uncovered contracts


def _skip_if_options_not_enabled(exc: Exception):
    msg = str(exc)
    if (
        any(code in msg for code in _OPTIONS_NOT_ENABLED_CODES)
        or "not authorized" in msg.lower()
    ):
        pytest.skip(f"Options trading not enabled on this account: {exc}")


def _skip_if_no_position(exc: Exception):
    if _NO_POSITION_CODE in str(exc):
        pytest.skip(
            f"SELL_CLOSE requires an existing position (expected for test accounts): {exc}"
        )


def _fetch_qqq_price(client: AlpacaAPIClient) -> float:
    from alpaca.data.requests import StockLatestQuoteRequest

    resp = client._stock_data_client.get_stock_latest_quote(
        StockLatestQuoteRequest(symbol_or_symbols=["QQQ"])
    )
    quote = resp["QQQ"]
    return float((quote.bid_price + quote.ask_price) / 2)


_TEST_TICKERS = ["NVDA", "TSLA", "AAPL"]
_TEST_TICKER = "QQQ"
_IS_PAPER = False  # set to True if using a paper trading account


@pytest.mark.alpaca
@pytest.mark.credentials
class TestTickerSelectorIntegration:
    def test_select_returns_top_tickers(self):
        client = AlpacaAPIClient(is_paper_trading=_IS_PAPER)
        selector = TickerSelector(
            tickers=_TEST_TICKERS,
            top_n=2,
            api_key=client._api_key,
            secret_key=client._secret_key,
        )

        selected = selector.select()

        assert isinstance(selected, list)
        assert len(selected) == 2
        for ticker in selected:
            assert ticker in _TEST_TICKERS

    def test_select_returns_fewer_when_top_n_exceeds_universe(self):
        client = AlpacaAPIClient(is_paper_trading=_IS_PAPER)
        selector = TickerSelector(
            tickers=["NVDA"],
            top_n=2,
            api_key=client._api_key,
            secret_key=client._secret_key,
        )

        selected = selector.select()

        assert isinstance(selected, list)
        assert len(selected) <= 2
        assert "NVDA" in selected


@pytest.mark.alpaca
@pytest.mark.credentials
class TestOptionContractSelectorIntegration:
    def test_select_bullish_returns_call_symbol(self):
        client = AlpacaAPIClient(is_paper_trading=_IS_PAPER)
        selector = OptionContractSelector(alpaca_client=client)
        stock_price = _fetch_qqq_price(client)

        try:
            symbol = selector.select(
                ticker=_TEST_TICKER,
                signal="BULLISH",
                stock_price=stock_price,
            )
        except RuntimeError as e:
            if "No call contracts found" in str(e):
                pytest.skip(f"No call contracts available for {_TEST_TICKER}: {e}")
            _skip_if_options_not_enabled(e)
            raise
        except Exception as e:
            _skip_if_options_not_enabled(e)
            raise

        assert isinstance(symbol, str)
        assert len(symbol) > 0
        assert _TEST_TICKER in symbol

    def test_select_bearish_returns_put_symbol(self):
        client = AlpacaAPIClient(is_paper_trading=_IS_PAPER)
        selector = OptionContractSelector(alpaca_client=client)
        stock_price = _fetch_qqq_price(client)

        try:
            symbol = selector.select(
                ticker=_TEST_TICKER,
                signal="BEARISH",
                stock_price=stock_price,
            )
        except RuntimeError as e:
            if "No put contracts found" in str(e):
                pytest.skip(f"No put contracts available for {_TEST_TICKER}: {e}")
            _skip_if_options_not_enabled(e)
            raise
        except Exception as e:
            _skip_if_options_not_enabled(e)
            raise

        assert isinstance(symbol, str)
        assert len(symbol) > 0
        assert _TEST_TICKER in symbol


@pytest.mark.alpaca
@pytest.mark.credentials
class TestPositionSizerIntegration:
    def _get_option_symbol(self, client: AlpacaAPIClient, option_type: str) -> str:
        try:
            contracts = client.get_options_contracts(
                underlying_symbol=_TEST_TICKER, option_type=option_type, limit=1
            )
        except Exception as e:
            _skip_if_options_not_enabled(e)
            raise
        if not contracts:
            pytest.skip(f"No {option_type} contracts available for {_TEST_TICKER}")
        return contracts[0]["symbol"]

    def test_compute_returns_valid_contracts_and_price_for_call(self):
        client = AlpacaAPIClient(is_paper_trading=_IS_PAPER)
        option_symbol = self._get_option_symbol(client, "call")
        sizer = PositionSizer(alpaca_client=client)

        try:
            contracts, limit_price = sizer.compute(option_symbol)
        except Exception as e:
            if "subscription" in str(e).lower() or "400" in str(e):
                pytest.skip(f"Option quote data not available: {e}")
            _skip_if_options_not_enabled(e)
            raise

        assert isinstance(contracts, int)
        assert contracts >= 1
        from decimal import Decimal

        assert isinstance(limit_price, Decimal)
        assert limit_price > Decimal("0")

    def test_compute_returns_valid_contracts_and_price_for_put(self):
        client = AlpacaAPIClient(is_paper_trading=_IS_PAPER)
        option_symbol = self._get_option_symbol(client, "put")
        sizer = PositionSizer(alpaca_client=client)

        try:
            contracts, limit_price = sizer.compute(option_symbol)
        except Exception as e:
            if "subscription" in str(e).lower() or "400" in str(e):
                pytest.skip(f"Option quote data not available: {e}")
            _skip_if_options_not_enabled(e)
            raise

        assert isinstance(contracts, int)
        assert contracts >= 1
        from decimal import Decimal

        assert isinstance(limit_price, Decimal)
        assert limit_price > Decimal("0")


@pytest.mark.alpaca
@pytest.mark.credentials
class TestPlaceOptionOrderWithSymbolOverrideIntegration:
    def _get_any_call_symbol(self, client: AlpacaAPIClient) -> str:
        try:
            contracts = client.get_options_contracts(
                underlying_symbol=_TEST_TICKER, option_type="call", limit=1
            )
        except Exception as e:
            _skip_if_options_not_enabled(e)
            raise
        if not contracts:
            pytest.skip(f"No call contracts available for {_TEST_TICKER}")
        return contracts[0]["symbol"]

    def test_buy_open_with_symbol_override_places_and_cancels(self):
        client = AlpacaAPIClient(is_paper_trading=_IS_PAPER)
        option_symbol = self._get_any_call_symbol(client)

        order_id = None
        try:
            order = client.place_option_order(
                symbol=_TEST_TICKER,
                option_key=None,
                price=0.01,
                price_type="LIMIT",
                option_type="CALL",
                order_action="BUY_OPEN",
                quantity=1,
                _option_symbol_override=option_symbol,
            )

            assert order is not None
            assert "order_id" in order
            assert order["symbol"] == option_symbol
            assert order["quantity"] == 1
            assert order["side"] == "buy"
            order_id = order["order_id"]
        except Exception as e:
            _skip_if_options_not_enabled(e)
            raise
        finally:
            if order_id:
                client.cancel_order(order_id)

    def test_place_qqq_call_order_at_low_limit_then_cancel(self):
        """
        End-to-end: select a QQQ BULLISH call contract using the live stock price,
        place a BUY_OPEN limit order at $0.01 (will not fill), verify it is pending,
        then cancel it.
        """
        client = AlpacaAPIClient(is_paper_trading=_IS_PAPER)
        stock_price = _fetch_qqq_price(client)
        selector = OptionContractSelector(alpaca_client=client)

        try:
            option_symbol = selector.select(
                ticker=_TEST_TICKER, signal="BULLISH", stock_price=stock_price
            )
        except RuntimeError as e:
            pytest.skip(f"No call contracts found for {_TEST_TICKER}: {e}")
        except Exception as e:
            _skip_if_options_not_enabled(e)
            raise

        order_id = None
        try:
            order = client.place_option_order(
                symbol=_TEST_TICKER,
                option_key=None,
                price=0.01,
                price_type="LIMIT",
                option_type="CALL",
                order_action="BUY_OPEN",
                quantity=1,
                _option_symbol_override=option_symbol,
            )

            assert order is not None
            assert "order_id" in order
            assert order["symbol"] == option_symbol
            assert order["quantity"] == 1
            assert order["side"] == "buy"
            assert order["limit_price"] == 0.01
            assert order["status"] in ("new", "pending_new", "accepted")
            order_id = order["order_id"]
        except Exception as e:
            _skip_if_options_not_enabled(e)
            raise
        finally:
            if order_id:
                cancel_result = client.cancel_order(order_id)
                assert cancel_result["order_id"] == order_id

    def test_sell_close_with_symbol_override_places_and_cancels(self):
        client = AlpacaAPIClient(is_paper_trading=_IS_PAPER)
        option_symbol = self._get_any_call_symbol(client)

        order_id = None
        try:
            order = client.place_option_order(
                symbol=_TEST_TICKER,
                option_key=None,
                price=0.01,
                price_type="LIMIT",
                option_type="CALL",
                order_action="SELL_CLOSE",
                quantity=1,
                _option_symbol_override=option_symbol,
            )

            assert order is not None
            assert "order_id" in order
            assert order["symbol"] == option_symbol
            assert order["side"] == "sell"
            order_id = order["order_id"]
        except Exception as e:
            _skip_if_options_not_enabled(e)
            _skip_if_no_position(e)
            raise
        finally:
            if order_id:
                client.cancel_order(order_id)


@pytest.mark.alpaca
@pytest.mark.credentials
class TestMarketDataStreamIntegration:
    def test_subscribe_to_qqq_quote_feed_receives_data(self):
        """
        Connects to Alpaca's live data stream for QQQ, subscribes to quote updates,
        and waits up to 15 seconds for at least one quote to arrive.

        Skips gracefully outside market hours when no quotes are streaming.
        """
        client = AlpacaAPIClient(is_paper_trading=_IS_PAPER)
        received = threading.Event()
        received_quote = {}

        async def on_quote(quote):
            received_quote["symbol"] = quote.symbol
            received_quote["bid"] = quote.bid_price
            received_quote["ask"] = quote.ask_price
            received.set()

        stream = StockDataStream(client._api_key, client._secret_key)
        stream.subscribe_quotes(on_quote, _TEST_TICKER)

        stream_thread = threading.Thread(target=stream.run, daemon=True)
        stream_thread.start()

        try:
            data_arrived = received.wait(timeout=15)
        finally:
            stream.stop()
            stream_thread.join(timeout=5)

        if not data_arrived:
            pytest.skip(
                f"No quote data received for {_TEST_TICKER} within 15s "
                "(market may be closed or stream delayed)"
            )

        assert received_quote["symbol"] == _TEST_TICKER
        assert received_quote["bid"] >= 0
        assert received_quote["ask"] >= received_quote["bid"]

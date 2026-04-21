import threading
from unittest.mock import MagicMock, patch

from alpha_tech_tracker.trade_api.alpaca_client.market_data_client import (
    AlpacaMarketDataClient,
)

_STREAM_CLS = "alpha_tech_tracker.trade_api.alpaca_client.market_data_client.StockDataStream"
_THREAD_CLS = "alpha_tech_tracker.trade_api.alpaca_client.market_data_client.threading.Thread"


def _make_client():
    return AlpacaMarketDataClient("test_key", "test_secret")


class TestReconnect:
    def test_reconnect_joins_old_thread_before_starting_new_one(self):
        client = _make_client()
        old_thread = MagicMock(spec=threading.Thread)
        client._thread = old_thread
        client._stream = MagicMock()
        client._callback = None
        client._tickers = ["AAPL"]

        call_order = []
        old_thread.join.side_effect = lambda timeout=None: call_order.append("join")

        mock_new_thread = MagicMock(spec=threading.Thread)
        mock_new_thread.start.side_effect = lambda: call_order.append("start")

        with patch(_STREAM_CLS), \
             patch(_THREAD_CLS, return_value=mock_new_thread):
            client.reconnect()

        assert call_order == ["join", "start"]

    def test_reconnect_joins_with_5s_timeout(self):
        client = _make_client()
        old_thread = MagicMock(spec=threading.Thread)
        client._thread = old_thread
        client._stream = MagicMock()
        client._callback = None
        client._tickers = ["AAPL"]

        with patch(_STREAM_CLS), \
             patch(_THREAD_CLS, return_value=MagicMock(spec=threading.Thread)):
            client.reconnect()

        old_thread.join.assert_called_once_with(timeout=5)

    def test_reconnect_skips_join_when_no_prior_thread(self):
        client = _make_client()
        client._stream = MagicMock()
        client._callback = None
        client._tickers = ["AAPL"]
        # _thread is None by default

        with patch(_STREAM_CLS), \
             patch(_THREAD_CLS, return_value=MagicMock(spec=threading.Thread)):
            client.reconnect()  # must not raise

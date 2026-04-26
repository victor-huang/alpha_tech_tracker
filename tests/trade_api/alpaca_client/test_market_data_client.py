import threading
from unittest.mock import MagicMock, patch

import pandas as pd

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


_HIST_CLIENT_CLS = "alpha_tech_tracker.trade_api.alpaca_client.market_data_client.StockHistoricalDataClient"


def _make_multiindex_df(tickers, timestamps):
    """Build a minimal MultiIndex DataFrame matching the Alpaca multi-ticker shape."""
    import pytz
    ET = pytz.timezone("America/New_York")
    index = pd.MultiIndex.from_tuples(
        [(t, ts) for t in tickers for ts in timestamps],
        names=["symbol", "timestamp"],
    )
    return pd.DataFrame(
        {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 1000},
        index=index,
    )


def _make_flat_df(timestamps):
    """Build a flat-index DataFrame matching the Alpaca single-ticker shape."""
    import pytz
    ET = pytz.timezone("America/New_York")
    index = pd.DatetimeIndex(timestamps, name="timestamp")
    return pd.DataFrame(
        {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 1000},
        index=index,
    )


class TestFetchBars:
    _START = pd.Timestamp("2026-04-24 13:15:00", tz="America/New_York")
    _END = pd.Timestamp("2026-04-24 13:20:00", tz="America/New_York")
    # 17:15 UTC = 13:15 ET — inside market hours, survives between_time("09:30","16:00")
    _TS = [pd.Timestamp("2026-04-24 17:15:00", tz="UTC")]

    def test_multi_ticker_all_no_data_returns_empty_dfs_without_error(self):
        client = _make_client()
        mock_bars = MagicMock()
        mock_bars.df = pd.DataFrame()  # empty, no MultiIndex

        with patch(_HIST_CLIENT_CLS) as mock_hist_cls:
            mock_hist_cls.return_value.get_stock_bars.return_value = mock_bars
            result = client.fetch_bars(["EXPE", "RH", "FN"], self._START, self._END)

        assert set(result.keys()) == {"EXPE", "RH", "FN"}
        for df in result.values():
            assert df.empty

    def test_multi_ticker_all_no_data_does_not_log_error(self, caplog):
        import logging
        client = _make_client()
        mock_bars = MagicMock()
        mock_bars.df = pd.DataFrame()

        with patch(_HIST_CLIENT_CLS) as mock_hist_cls, \
             caplog.at_level(logging.ERROR):
            mock_hist_cls.return_value.get_stock_bars.return_value = mock_bars
            client.fetch_bars(["EXPE", "RH", "FN"], self._START, self._END)

        assert "fetch_bars failed" not in caplog.text

    def test_single_ticker_flat_index_wrapped_into_multiindex(self):
        client = _make_client()
        mock_bars = MagicMock()
        mock_bars.df = _make_flat_df(self._TS)

        with patch(_HIST_CLIENT_CLS) as mock_hist_cls:
            mock_hist_cls.return_value.get_stock_bars.return_value = mock_bars
            result = client.fetch_bars(["AAPL"], self._START, self._END)

        assert "AAPL" in result
        assert not result["AAPL"].empty

    def test_multi_ticker_with_data_returns_per_ticker_dfs(self):
        client = _make_client()
        mock_bars = MagicMock()
        mock_bars.df = _make_multiindex_df(["AAPL", "TSLA"], self._TS)

        with patch(_HIST_CLIENT_CLS) as mock_hist_cls:
            mock_hist_cls.return_value.get_stock_bars.return_value = mock_bars
            result = client.fetch_bars(["AAPL", "TSLA"], self._START, self._END)

        assert "AAPL" in result
        assert "TSLA" in result
        assert not result["AAPL"].empty
        assert not result["TSLA"].empty

    def test_ticker_missing_from_response_gets_empty_df(self):
        client = _make_client()
        mock_bars = MagicMock()
        # Only AAPL has data; TSLA is absent from the response
        mock_bars.df = _make_multiindex_df(["AAPL"], self._TS)

        with patch(_HIST_CLIENT_CLS) as mock_hist_cls:
            mock_hist_cls.return_value.get_stock_bars.return_value = mock_bars
            result = client.fetch_bars(["AAPL", "TSLA"], self._START, self._END)

        assert not result["AAPL"].empty
        assert result["TSLA"].empty

    def test_api_exception_returns_empty_dfs_for_all_tickers(self):
        client = _make_client()

        with patch(_HIST_CLIENT_CLS) as mock_hist_cls:
            mock_hist_cls.return_value.get_stock_bars.side_effect = RuntimeError("API down")
            result = client.fetch_bars(["AAPL", "TSLA"], self._START, self._END)

        assert result["AAPL"].empty
        assert result["TSLA"].empty

    def test_multi_ticker_one_has_data_flat_index_labelled_from_bars_data(self):
        # Reproduces the 2026-04-24 A1 bug: fetch_bars(['EXPE','RH','FN']) where only
        # FN (tickers[2]) has trades — Alpaca returns a flat index, old code labelled
        # it as EXPE (tickers[0]) and returned empty DataFrames for RH and FN.
        client = _make_client()
        mock_bars = MagicMock()
        mock_bars.df = _make_flat_df(self._TS)
        mock_bars.data = {"FN": [object()]}  # only FN has data

        with patch(_HIST_CLIENT_CLS) as mock_hist_cls:
            mock_hist_cls.return_value.get_stock_bars.return_value = mock_bars
            result = client.fetch_bars(["EXPE", "RH", "FN"], self._START, self._END)

        assert not result["FN"].empty
        assert result["EXPE"].empty
        assert result["RH"].empty

    def test_multi_ticker_one_has_data_does_not_raise_type_error(self, caplog):
        import logging
        client = _make_client()
        mock_bars = MagicMock()
        mock_bars.df = _make_flat_df(self._TS)
        mock_bars.data = {"RH": [object()]}

        with patch(_HIST_CLIENT_CLS) as mock_hist_cls, \
             caplog.at_level(logging.ERROR):
            mock_hist_cls.return_value.get_stock_bars.return_value = mock_bars
            client.fetch_bars(["EXPE", "RH", "FN"], self._START, self._END)

        assert "fetch_bars failed" not in caplog.text


class TestWarmup:
    _START = pd.Timestamp("2026-01-02 09:30:00", tz="America/New_York")
    _END = pd.Timestamp("2026-04-24 16:00:00", tz="America/New_York")
    _TS = [pd.Timestamp("2026-04-24 17:15:00", tz="UTC")]

    def test_normal_multi_ticker_returns_per_ticker_dfs(self):
        client = _make_client()
        mock_bars = MagicMock()
        mock_bars.df = _make_multiindex_df(["AAPL", "TSLA"], self._TS)

        with patch(_HIST_CLIENT_CLS) as mock_hist_cls:
            mock_hist_cls.return_value.get_stock_bars.return_value = mock_bars
            result = client.warmup(["AAPL", "TSLA"], self._START, self._END)

        assert not result["AAPL"].empty
        assert not result["TSLA"].empty

    def test_single_ticker_flat_index_does_not_raise(self):
        client = _make_client()
        mock_bars = MagicMock()
        mock_bars.df = _make_flat_df(self._TS)
        mock_bars.data = {"AAPL": [object()]}

        with patch(_HIST_CLIENT_CLS) as mock_hist_cls:
            mock_hist_cls.return_value.get_stock_bars.return_value = mock_bars
            result = client.warmup(["AAPL", "TSLA"], self._START, self._END)

        assert not result["AAPL"].empty
        assert result["TSLA"].empty

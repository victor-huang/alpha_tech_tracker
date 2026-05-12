import pandas as pd
import pytest
import pytz
from datetime import datetime
from unittest.mock import MagicMock

from alpha_tech_tracker.trade_api.tradestation.market_data_client import (
    TradeStationMarketDataClient,
    _validate_open_timestamps,
)

ET = pytz.timezone("America/New_York")


def _make_df(timestamps: list) -> pd.DataFrame:
    """Build a minimal OHLCV DataFrame with the given ET-aware timestamps as index."""
    idx = pd.DatetimeIndex([ET.localize(datetime.strptime(ts, "%Y-%m-%d %H:%M")) for ts in timestamps])
    return pd.DataFrame(
        {"Open": 100.0, "High": 101.0, "Low": 99.0, "Close": 100.5, "Volume": 1000.0},
        index=idx,
    )


def _session_open_timestamps(date_str: str, count: int = 78) -> list:
    """Return `count` 5-min open-time timestamps starting at 09:30 for the given date."""
    from datetime import timedelta
    base = datetime.strptime(f"{date_str} 09:30", "%Y-%m-%d %H:%M")
    return [(base + timedelta(minutes=5 * i)).strftime("%Y-%m-%d %H:%M") for i in range(count)]


def _session_close_timestamps(date_str: str, count: int = 78) -> list:
    """Return `count` 5-min close-time timestamps starting at 09:35 for the given date."""
    from datetime import timedelta
    base = datetime.strptime(f"{date_str} 09:35", "%Y-%m-%d %H:%M")
    return [(base + timedelta(minutes=5 * i)).strftime("%Y-%m-%d %H:%M") for i in range(count)]


class TestValidateOpenTimestamps:
    def test_passes_for_empty_dataframe(self):
        df = pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
        _validate_open_timestamps(df, "TSLA")  # must not raise

    def test_passes_for_correct_open_timestamps(self):
        df = _make_df(_session_open_timestamps("2026-04-16"))
        _validate_open_timestamps(df, "TSLA")  # must not raise

    def test_raises_when_first_bar_is_at_09_35(self):
        df = _make_df(_session_close_timestamps("2026-04-16"))
        with pytest.raises(RuntimeError, match="09:35"):
            _validate_open_timestamps(df, "TSLA")

    def test_raises_error_includes_ticker_name(self):
        df = _make_df(_session_close_timestamps("2026-04-16"))
        with pytest.raises(RuntimeError, match="META"):
            _validate_open_timestamps(df, "META")

    def test_raises_error_includes_session_date(self):
        df = _make_df(_session_close_timestamps("2026-04-16"))
        with pytest.raises(RuntimeError, match="2026-04-16"):
            _validate_open_timestamps(df, "TSLA")

    def test_skips_incomplete_session_under_20_bars(self):
        # Only 5 bars — not enough to be a complete session, should not raise
        df = _make_df(_session_close_timestamps("2026-04-16", count=5))
        _validate_open_timestamps(df, "TSLA")  # must not raise

    def test_passes_when_multiple_sessions_all_correct(self):
        ts = _session_open_timestamps("2026-04-15") + _session_open_timestamps("2026-04-16")
        df = _make_df(ts)
        _validate_open_timestamps(df, "TSLA")  # must not raise

    def test_does_not_raise_for_single_09_35_session_among_correct_sessions(self):
        # 1 of 2 sessions at 09:35 — could be a legitimate thin open, not a systemic bug
        ts = _session_open_timestamps("2026-04-15") + _session_close_timestamps("2026-04-16")
        df = _make_df(ts)
        _validate_open_timestamps(df, "TSLA")  # must not raise

    def test_does_not_raise_for_one_09_35_session_among_five(self):
        # Mirrors the CHTR case: 1 sparse-open day in a 5-day warmup window
        ts = (
            _session_open_timestamps("2026-04-14")
            + _session_close_timestamps("2026-04-15")   # thin open
            + _session_open_timestamps("2026-04-16")
            + _session_open_timestamps("2026-04-17")
            + _session_open_timestamps("2026-04-18")
        )
        df = _make_df(ts)
        _validate_open_timestamps(df, "CHTR")  # must not raise

    def test_raises_when_majority_of_sessions_are_at_09_35(self):
        # 2 of 3 sessions at 09:35 → systemic timestamp misconfiguration
        ts = (
            _session_close_timestamps("2026-04-14")
            + _session_close_timestamps("2026-04-15")
            + _session_open_timestamps("2026-04-16")
        )
        df = _make_df(ts)
        with pytest.raises(RuntimeError):
            _validate_open_timestamps(df, "TSLA")


class TestTradeStationMarketDataClientWarmup:
    def _make_client(self, bars_by_ticker: dict) -> TradeStationMarketDataClient:
        ts_client = MagicMock()

        def get_historical_bars(ticker, start, end, interval=5, unit="Minute"):
            from alpha_tech_tracker.trade_api.tradestation.bar_stream import _TSBar
            from datetime import timezone
            raw_bars = []
            for ts_str, o, h, l, c, v in bars_by_ticker.get(ticker, []):
                raw_ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
                raw_bars.append(_TSBar(symbol=ticker, timestamp=raw_ts, open=o, high=h, low=l, close=c, volume=v))
            return raw_bars

        ts_client.get_historical_bars.side_effect = get_historical_bars
        return TradeStationMarketDataClient(ts_client)

    def _open_bar_tuples(self, date_str: str, count: int = 78):
        from datetime import timedelta
        base = datetime.strptime(f"{date_str} 13:30", "%Y-%m-%d %H:%M")  # 09:30 ET = 13:30 UTC
        return [
            ((base + timedelta(minutes=5 * i)).strftime("%Y-%m-%d %H:%M"), 100.0, 101.0, 99.0, 100.5, 1000.0)
            for i in range(count)
        ]

    def test_warmup_raises_on_close_timestamp_data(self):
        pass
        # Simulate TS returning close-timestamp bars (09:35 UTC = 05:35 ET, but we fake UTC)
        # The key is: after _ts_bars_to_df, the first bar of the day in ET is at 09:35
        # We achieve this by having the already-normalized bars start at 09:35 (skip the fix)
        ts_client = MagicMock()

        # Return a DataFrame that looks like close-timestamp data (first bar at 09:35)
        close_ts_df = _make_df(_session_close_timestamps("2026-04-16"))

        with MagicMock() as mock_to_df:
            from unittest.mock import patch
            with patch(
                "alpha_tech_tracker.trade_api.tradestation.market_data_client._ts_bars_to_df",
                return_value=close_ts_df,
            ):
                ts_client.get_historical_bars.return_value = [MagicMock()]
                client = TradeStationMarketDataClient(ts_client)
                start = ET.localize(datetime(2026, 4, 15, 9, 30))
                end = ET.localize(datetime(2026, 4, 16, 16, 0))
                with pytest.raises(RuntimeError, match="09:35"):
                    client.warmup(["TSLA"], start, end)

    def test_fetch_bars_raises_on_close_timestamp_data(self):
        close_ts_df = _make_df(_session_close_timestamps("2026-04-16"))
        ts_client = MagicMock()

        from unittest.mock import patch
        with patch(
            "alpha_tech_tracker.trade_api.tradestation.market_data_client._ts_bars_to_df",
            return_value=close_ts_df,
        ):
            ts_client.get_historical_bars.return_value = [MagicMock()]
            client = TradeStationMarketDataClient(ts_client)
            start = ET.localize(datetime(2026, 4, 15, 9, 30))
            end = ET.localize(datetime(2026, 4, 16, 16, 0))
            with pytest.raises(RuntimeError, match="09:35"):
                client.fetch_bars(["TSLA"], start, end)

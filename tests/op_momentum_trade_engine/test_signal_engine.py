from datetime import datetime, timedelta
from unittest.mock import patch

import pandas as pd
import pytz

from alpha_tech_tracker.op_momentum_strategy.models import _FiveMinBar
from alpha_tech_tracker.op_momentum_strategy.signal_engine import LiveSignalEngine

from conftest import (
    _build_history_df,
    _make_mock_bars,
    _make_signal_engine_with_history,
)

ET = pytz.timezone("America/New_York")


class TestLiveSignalEngine:
    def _make_history_df(self, closes, ma20=None, ma50=None, ma200=None):
        n = len(closes)
        today = datetime.now(ET).date()
        timestamps = [
            ET.localize(
                datetime.combine(today, datetime.min.time())
                + timedelta(hours=9, minutes=30 + i * 5)
            )
            for i in range(n)
        ]
        df = pd.DataFrame(
            {
                "Open": closes,
                "High": [c + 1.0 for c in closes],
                "Low": [c - 1.0 for c in closes],
                "Close": closes,
                "Volume": [1000.0] * n,
            },
            index=timestamps,
        )
        df["MA20"] = ma20 if ma20 is not None else closes[-1] - 5.0
        df["MA50"] = ma50 if ma50 is not None else closes[-1] - 3.0
        df["MA200"] = ma200 if ma200 is not None else closes[-1] - 10.0
        return df

    def test_bullish_signal_fires_when_close_above_midpoint_and_mas(self):
        fired_events = []
        engine = LiveSignalEngine(
            tickers=["NVDA"],
            api_key="k",
            secret_key="s",
            opening_bars=3,
            on_signal=fired_events.append,
        )

        closes = [102.0, 103.0, 106.0]
        df = self._make_history_df(closes, ma20=100.0, ma200=90.0)
        engine._history["NVDA"] = df

        opening_bars = _make_mock_bars(
            "NVDA", highs=[103.0, 104.0, 107.0], lows=[101.0, 102.0, 105.0]
        )
        engine._opening_buf["W1"]["NVDA"] = opening_bars

        engine._try_fire_signal("NVDA", df.iloc[-1], engine._windows[0])

        assert len(fired_events) == 1
        assert fired_events[0].signal == "BULLISH"
        assert fired_events[0].ticker == "NVDA"

    def test_bearish_signal_fires_when_close_at_bottom_and_below_ma20(self):
        fired_events = []
        engine = LiveSignalEngine(
            tickers=["NVDA"],
            api_key="k",
            secret_key="s",
            opening_bars=3,
            on_signal=fired_events.append,
        )

        # OR range 95-105, bottom_30 = 95 + 0.2*10 = 97, close=96 is below bottom_30
        closes = [100.0, 98.0, 96.0]
        df = self._make_history_df(closes, ma20=105.0, ma200=110.0)
        engine._history["NVDA"] = df

        opening_bars = _make_mock_bars(
            "NVDA", highs=[101.0, 99.0, 97.0], lows=[99.0, 97.0, 95.0]
        )
        engine._opening_buf["W1"]["NVDA"] = opening_bars

        engine._try_fire_signal("NVDA", df.iloc[-1], engine._windows[0])

        assert len(fired_events) == 1
        assert fired_events[0].signal == "BEARISH"

    def test_neutral_signal_does_not_fire_callback(self):
        fired_events = []
        engine = LiveSignalEngine(
            tickers=["NVDA"],
            api_key="k",
            secret_key="s",
            opening_bars=3,
            on_signal=fired_events.append,
        )

        # close is at midpoint exactly — neither bullish nor bearish condition met
        closes = [100.0, 100.0, 100.0]
        df = self._make_history_df(closes, ma20=100.0, ma200=100.0)
        engine._history["NVDA"] = df

        opening_bars = _make_mock_bars(
            "NVDA", highs=[101.0, 101.0, 101.0], lows=[99.0, 99.0, 99.0]
        )
        engine._opening_buf["W1"]["NVDA"] = opening_bars

        engine._try_fire_signal("NVDA", df.iloc[-1], engine._windows[0])

        assert len(fired_events) == 0

    def test_no_signal_when_ma_data_not_ready(self):
        fired_events = []
        engine = LiveSignalEngine(
            tickers=["NVDA"],
            api_key="k",
            secret_key="s",
            opening_bars=3,
            on_signal=fired_events.append,
        )

        closes = [106.0, 107.0, 108.0]
        df = self._make_history_df(closes)
        df["MA20"] = float("nan")
        df["MA200"] = float("nan")
        engine._history["NVDA"] = df

        opening_bars = _make_mock_bars(
            "NVDA", highs=[107.0, 108.0, 109.0], lows=[105.0, 106.0, 107.0]
        )
        engine._opening_buf["W1"]["NVDA"] = opening_bars

        engine._try_fire_signal("NVDA", df.iloc[-1], engine._windows[0])

        assert len(fired_events) == 0

    def test_get_latest_bar_returns_none_when_no_history(self):
        engine = LiveSignalEngine(
            tickers=["NVDA"],
            api_key="k",
            secret_key="s",
            opening_bars=3,
        )

        assert engine.get_latest_bar("NVDA") is None

    def test_get_latest_bar_returns_last_row(self):
        closes = [100.0, 102.0, 104.0]
        df = _build_history_df(closes, ma20=95.0, ma50=93.0, ma200=90.0)
        engine = _make_signal_engine_with_history("NVDA", df)

        latest = engine.get_latest_bar("NVDA")

        assert latest is not None
        assert latest["Close"] == 104.0

    def test_aggregate_bars_builds_correct_ohlcv(self):
        engine = LiveSignalEngine(
            tickers=["AMD"], api_key="k", secret_key="s", opening_bars=3
        )
        period_start = ET.localize(datetime(2026, 3, 24, 9, 30))
        bars = _make_mock_bars(
            "AMD",
            highs=[101.0, 102.0, 103.0, 104.0, 105.0],
            lows=[99.0, 100.0, 101.0, 102.0, 103.0],
        )
        for i, b in enumerate(bars):
            b.open = 100.0 + i
            b.close = 100.5 + i
            b.volume = 1000.0

        result = engine._aggregate_bars("AMD", period_start, bars)

        assert result.symbol == "AMD"
        assert result.timestamp == period_start
        assert result.open == 100.0
        assert result.high == 105.0
        assert result.low == 99.0
        assert result.close == 104.5
        assert result.volume == 5000.0

    def test_process_five_min_bar_accumulates_opening_bars(self):
        fired_events = []
        engine = LiveSignalEngine(
            tickers=["AMD"],
            api_key="k",
            secret_key="s",
            opening_bars=3,
            on_signal=fired_events.append,
        )
        closes = [104.0, 105.0, 106.0]
        df = self._make_history_df(closes, ma20=100.0, ma200=90.0)
        engine._history["AMD"] = df

        bar1 = _FiveMinBar(
            "AMD",
            ET.localize(datetime(2026, 3, 24, 9, 30)),
            102.0,
            103.0,
            101.0,
            102.5,
            1000.0,
        )
        bar2 = _FiveMinBar(
            "AMD",
            ET.localize(datetime(2026, 3, 24, 9, 35)),
            103.0,
            104.0,
            102.0,
            103.5,
            1000.0,
        )

        engine._process_five_min_bar(bar1)
        assert len(engine._opening_buf["W1"]["AMD"]) == 1
        assert len(fired_events) == 0

        engine._process_five_min_bar(bar2)
        assert len(engine._opening_buf["W1"]["AMD"]) == 2
        assert len(fired_events) == 0

    def test_process_five_min_bar_calls_try_fire_signal_on_third_bar(self):
        engine = LiveSignalEngine(
            tickers=["AMD"],
            api_key="k",
            secret_key="s",
            opening_bars=3,
        )
        closes = [104.0, 105.0, 106.0]
        engine._history["AMD"] = self._make_history_df(closes, ma20=100.0, ma200=90.0)

        bars = [
            _FiveMinBar(
                "AMD",
                ET.localize(datetime(2026, 3, 24, 9, 30)),
                104.0,
                105.0,
                99.0,
                104.0,
                1000.0,
            ),
            _FiveMinBar(
                "AMD",
                ET.localize(datetime(2026, 3, 24, 9, 35)),
                104.0,
                106.0,
                100.0,
                105.0,
                1000.0,
            ),
            _FiveMinBar(
                "AMD",
                ET.localize(datetime(2026, 3, 24, 9, 40)),
                105.0,
                107.0,
                103.0,
                106.0,
                1000.0,
            ),
        ]

        with patch.object(engine, "_try_fire_signal") as mock_fire:
            for b in bars:
                engine._process_five_min_bar(b)

        mock_fire.assert_called_once()
        assert mock_fire.call_args[0][0] == "AMD"
        assert engine._signal_fired["W1"]["AMD"] is True

    def test_regime_filter_suppresses_bullish_signal_on_bearish_day(self):
        fired_events = []
        engine = LiveSignalEngine(
            tickers=["NVDA"],
            api_key="k",
            secret_key="s",
            opening_bars=3,
            on_signal=fired_events.append,
            regime_filter=True,
        )
        today = datetime.now(ET).date()
        engine._bearish_regime_dates = {today}

        closes = [102.0, 103.0, 106.0]
        df = self._make_history_df(closes, ma20=100.0, ma200=90.0)
        engine._history["NVDA"] = df

        opening_bars = _make_mock_bars(
            "NVDA", highs=[103.0, 104.0, 107.0], lows=[101.0, 102.0, 105.0]
        )
        engine._opening_buf["W1"]["NVDA"] = opening_bars

        engine._try_fire_signal("NVDA", df.iloc[-1], engine._windows[0])

        assert len(fired_events) == 0

    def test_regime_filter_allows_bullish_signal_on_non_bearish_day(self):
        fired_events = []
        engine = LiveSignalEngine(
            tickers=["NVDA"],
            api_key="k",
            secret_key="s",
            opening_bars=3,
            on_signal=fired_events.append,
            regime_filter=True,
        )
        engine._bearish_regime_dates = set()

        closes = [102.0, 103.0, 106.0]
        df = self._make_history_df(closes, ma20=100.0, ma200=90.0)
        engine._history["NVDA"] = df

        opening_bars = _make_mock_bars(
            "NVDA", highs=[103.0, 104.0, 107.0], lows=[101.0, 102.0, 105.0]
        )
        engine._opening_buf["W1"]["NVDA"] = opening_bars

        engine._try_fire_signal("NVDA", df.iloc[-1], engine._windows[0])

        assert len(fired_events) == 1
        assert fired_events[0].signal == "BULLISH"

    def test_regime_filter_does_not_suppress_bearish_signal(self):
        fired_events = []
        engine = LiveSignalEngine(
            tickers=["NVDA"],
            api_key="k",
            secret_key="s",
            opening_bars=3,
            on_signal=fired_events.append,
            regime_filter=True,
        )
        today = datetime.now(ET).date()
        engine._bearish_regime_dates = {today}

        # OR range 95-105, bottom_30=97, close=96 → BEARISH
        closes = [100.0, 98.0, 96.0]
        df = self._make_history_df(closes, ma20=105.0, ma200=110.0)
        engine._history["NVDA"] = df

        opening_bars = _make_mock_bars(
            "NVDA", highs=[101.0, 99.0, 97.0], lows=[99.0, 97.0, 95.0]
        )
        engine._opening_buf["W1"]["NVDA"] = opening_bars

        engine._try_fire_signal("NVDA", df.iloc[-1], engine._windows[0])

        assert len(fired_events) == 1
        assert fired_events[0].signal == "BEARISH"


class TestMultiWindowSignalEngine:
    def _make_history_df(self, closes, ma20=None, ma200=None):
        import pandas as pd
        from datetime import timedelta

        n = len(closes)
        today = datetime.now(ET).date()
        timestamps = [
            ET.localize(
                datetime.combine(today, datetime.min.time())
                + timedelta(hours=9, minutes=30 + i * 5)
            )
            for i in range(n)
        ]
        df = pd.DataFrame(
            {
                "Open": closes,
                "High": [c + 1.0 for c in closes],
                "Low": [c - 1.0 for c in closes],
                "Close": closes,
                "Volume": [1000.0] * n,
            },
            index=timestamps,
        )
        df["MA20"] = ma20 if ma20 is not None else closes[-1] - 5.0
        df["MA50"] = closes[-1] - 3.0
        df["MA200"] = ma200 if ma200 is not None else closes[-1] - 10.0
        return df

    def _make_multi_window_engine(self, m1_callback=None, a1_callback=None):
        return LiveSignalEngine(
            tickers=["NVDA"],
            api_key="k",
            secret_key="s",
            windows=[
                {
                    "label": "M1",
                    "opening_start": "09:30",
                    "opening_bars": 3,
                    "on_signal": m1_callback,
                },
                {
                    "label": "A1",
                    "opening_start": "13:15",
                    "opening_bars": 1,
                    "on_signal": a1_callback,
                },
            ],
        )

    def test_two_windows_have_independent_opening_buffers(self):
        engine = self._make_multi_window_engine()

        assert "M1" in engine._opening_buf
        assert "A1" in engine._opening_buf
        assert "NVDA" in engine._opening_buf["M1"]
        assert "NVDA" in engine._opening_buf["A1"]

    def test_two_windows_have_independent_signal_fired_flags(self):
        engine = self._make_multi_window_engine()

        engine._signal_fired["M1"]["NVDA"] = True

        assert engine._signal_fired["M1"]["NVDA"] is True
        assert engine._signal_fired["A1"]["NVDA"] is False

    def test_each_window_fires_its_own_callback(self):
        m1_events = []
        a1_events = []
        engine = self._make_multi_window_engine(
            m1_callback=m1_events.append,
            a1_callback=a1_events.append,
        )

        closes = [102.0, 103.0, 106.0]
        df = self._make_history_df(closes, ma20=100.0, ma200=90.0)
        engine._history["NVDA"] = df
        engine._opening_buf["M1"]["NVDA"] = _make_mock_bars(
            "NVDA", highs=[103.0, 104.0, 107.0], lows=[101.0, 102.0, 105.0]
        )

        engine._try_fire_signal("NVDA", df.iloc[-1], engine._windows[0])

        assert len(m1_events) == 1
        assert len(a1_events) == 0

    def test_m1_fired_flag_does_not_affect_a1_fired_flag(self):
        engine = self._make_multi_window_engine(
            m1_callback=lambda e: None,
            a1_callback=lambda e: None,
        )

        engine._signal_fired["M1"]["NVDA"] = True

        assert engine._signal_fired["A1"]["NVDA"] is False

    def test_two_windows_each_have_independent_catchup_done_flags(self):
        engine = self._make_multi_window_engine()

        assert engine._opening_catchup_done["M1"] is False
        assert engine._opening_catchup_done["A1"] is False

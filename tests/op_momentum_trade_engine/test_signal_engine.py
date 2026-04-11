import asyncio
from datetime import date, datetime, timedelta
from unittest.mock import Mock, patch

import pandas as pd
import pytz

from alpha_tech_tracker.op_momentum_strategy.models import _FiveMinBar
from alpha_tech_tracker.op_momentum_strategy.replay import _now_et
from alpha_tech_tracker.op_momentum_strategy.signal_engine import LiveSignalEngine

from conftest import (
    _build_history_df,
    _make_mock_bars,
    _make_signal_engine_with_history,
)

ET = pytz.timezone("America/New_York")
_SE_MODULE = "alpha_tech_tracker.op_momentum_strategy.signal_engine"


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


class TestCatchUpOpeningBarsForWindow:
    """Tests for _catch_up_opening_bars_for_window client-side bar preference."""

    def _empty_alpaca_df(self):
        """Return an empty multi-index DataFrame matching Alpaca's bar response schema."""
        return pd.DataFrame(
            columns=["open", "high", "low", "close", "volume"],
            index=pd.MultiIndex.from_tuples([], names=["symbol", "timestamp"]),
        )

    def _make_a1_engine(self, ticker="FN"):
        return LiveSignalEngine(
            tickers=[ticker],
            api_key="k",
            secret_key="s",
            windows=[
                {
                    "label": "A1",
                    "opening_start": "13:15",
                    "opening_bars": 1,
                    "on_signal": None,
                }
            ],
        )

    def _make_m1_engine(self, ticker="AMD"):
        return LiveSignalEngine(
            tickers=[ticker],
            api_key="k",
            secret_key="s",
            windows=[
                {
                    "label": "M1",
                    "opening_start": "09:30",
                    "opening_bars": 3,
                    "on_signal": None,
                }
            ],
        )

    def _make_1min_bar(self, open_, high, low, close, volume=500.0):
        bar = Mock()
        bar.open, bar.high, bar.low, bar.close, bar.volume = open_, high, low, close, volume
        return bar

    def test_uses_minute_buf_bars_instead_of_alpaca_for_recent_period(self):
        today = date(2026, 4, 6)
        engine = self._make_a1_engine("FN")
        or_start = ET.localize(
            datetime.combine(today, datetime.strptime("13:15", "%H:%M").time())
        )

        bar1 = self._make_1min_bar(550.0, 551.5, 549.5, 551.0)
        bar2 = self._make_1min_bar(551.0, 552.0, 550.5, 551.06)
        engine._minute_buf["FN"] = {"period_start": or_start, "bars": [bar1, bar2]}

        injected_bars = []

        def fake_process(bar):
            injected_bars.append(bar)
            engine._opening_buf["A1"]["FN"].append(bar)
            engine._signal_fired["A1"]["FN"] = True

        with patch.object(engine, "_process_five_min_bar", side_effect=fake_process), \
             patch(
                 "alpha_tech_tracker.op_momentum_strategy.signal_engine.StockHistoricalDataClient"
             ) as mock_alpaca:
            engine._catch_up_opening_bars_for_window(today, engine._windows[0])

        assert len(injected_bars) == 1
        injected = injected_bars[0]
        assert injected.symbol == "FN"
        assert injected.timestamp == or_start
        assert injected.open == 550.0
        assert injected.high == 552.0
        assert injected.low == 549.5
        assert injected.close == 551.06
        mock_alpaca.assert_not_called()

    def test_falls_back_to_alpaca_when_minute_buf_bars_list_is_empty(self):
        today = date(2026, 4, 6)
        engine = self._make_a1_engine("FN")
        or_start = ET.localize(
            datetime.combine(today, datetime.strptime("13:15", "%H:%M").time())
        )
        engine._minute_buf["FN"] = {"period_start": or_start, "bars": []}

        mock_alpaca_instance = Mock()
        mock_alpaca_instance.get_stock_bars.return_value = Mock(df=self._empty_alpaca_df())

        with patch(
            "alpha_tech_tracker.op_momentum_strategy.signal_engine.StockHistoricalDataClient",
            return_value=mock_alpaca_instance,
        ) as mock_alpaca:
            engine._catch_up_opening_bars_for_window(today, engine._windows[0])

        mock_alpaca.assert_called_once()
        mock_alpaca_instance.get_stock_bars.assert_called_once()

    def test_falls_back_to_alpaca_when_minute_buf_is_on_a_different_period(self):
        today = date(2026, 4, 6)
        engine = self._make_a1_engine("FN")
        or_start = ET.localize(
            datetime.combine(today, datetime.strptime("13:15", "%H:%M").time())
        )
        engine._minute_buf["FN"] = {
            "period_start": or_start - timedelta(minutes=5),
            "bars": [self._make_1min_bar(550.0, 551.0, 549.0, 550.5)],
        }

        mock_alpaca_instance = Mock()
        mock_alpaca_instance.get_stock_bars.return_value = Mock(df=self._empty_alpaca_df())

        with patch(
            "alpha_tech_tracker.op_momentum_strategy.signal_engine.StockHistoricalDataClient",
            return_value=mock_alpaca_instance,
        ) as mock_alpaca:
            engine._catch_up_opening_bars_for_window(today, engine._windows[0])

        mock_alpaca.assert_called_once()

    def test_bar_already_in_history_is_not_reprocessed(self):
        today = date(2026, 4, 6)
        engine = self._make_a1_engine("FN")
        or_start = ET.localize(
            datetime.combine(today, datetime.strptime("13:15", "%H:%M").time())
        )

        engine._minute_buf["FN"] = {
            "period_start": or_start,
            "bars": [self._make_1min_bar(551.0, 552.0, 550.0, 551.06)],
        }
        engine._history["FN"] = pd.DataFrame(
            {"Open": [551.0], "High": [552.0], "Low": [550.0], "Close": [551.06],
             "Volume": [500.0], "MA20": [540.0], "MA50": [535.0], "MA200": [520.0]},
            index=[or_start],
        )

        with patch.object(engine, "_process_five_min_bar") as mock_process, \
             patch(
                 "alpha_tech_tracker.op_momentum_strategy.signal_engine.StockHistoricalDataClient"
             ):
            engine._catch_up_opening_bars_for_window(today, engine._windows[0])

        mock_process.assert_not_called()

    def test_m1_three_bar_window_fills_last_two_from_minute_buf(self):
        """For a 3-bar M1 window, the last 2 OR bars come from _minute_buf; the
        first (older) bar triggers the Alpaca fallback. When Alpaca also has no data,
        a flat bar is synthesized for the fully missing 09:30 slot."""
        today = date(2026, 4, 6)
        engine = self._make_m1_engine("AMD")
        or_start = ET.localize(
            datetime.combine(today, datetime.strptime("09:30", "%H:%M").time())
        )
        bar_09_35 = or_start + timedelta(minutes=5)
        bar_09_40 = or_start + timedelta(minutes=10)

        # 09:35 already processed live and in _history; 09:40 accumulating in _minute_buf
        engine._history["AMD"] = pd.DataFrame(
            {"Open": [99.0], "High": [101.0], "Low": [98.0], "Close": [100.0],
             "Volume": [1000.0], "MA20": [95.0], "MA50": [93.0], "MA200": [90.0]},
            index=[bar_09_35],
        )
        engine._minute_buf["AMD"] = {
            "period_start": bar_09_40,
            "bars": [self._make_1min_bar(100.0, 101.0, 99.0, 100.5)],
        }

        injected_bars = []

        def fake_process(bar):
            injected_bars.append(bar)
            engine._opening_buf["M1"]["AMD"].append(bar)

        mock_alpaca_instance = Mock()
        mock_alpaca_instance.get_stock_bars.return_value = Mock(df=self._empty_alpaca_df())

        with patch.object(engine, "_process_five_min_bar", side_effect=fake_process), \
             patch(
                 "alpha_tech_tracker.op_momentum_strategy.signal_engine.StockHistoricalDataClient",
                 return_value=mock_alpaca_instance,
             ):
            engine._catch_up_opening_bars_for_window(today, engine._windows[0])

        # 09:40 real bar from minute_buf + 09:30 flat bar synthesized (no Alpaca data)
        # 09:35 is already in history so it is skipped (not re-injected)
        assert len(injected_bars) == 2
        timestamps = {b.timestamp for b in injected_bars}
        assert bar_09_40 in timestamps
        assert or_start in timestamps  # 09:30 flat bar
        flat_bars = [b for b in injected_bars if b.volume == 0.0]
        assert len(flat_bars) == 1
        assert flat_bars[0].timestamp == or_start
        mock_alpaca_instance.get_stock_bars.assert_called_once()

    def test_late_start_engine_gets_uncovered_recent_bar_from_alpaca(self):
        """Regression: engine starts late (e.g. 10:39 for a 10:25/3bar window).
        _minute_buf is on period 10:35, so pass 1 covers 10:35 but cannot serve
        10:30. Pass 2 must fetch 10:30 from Alpaca — not skip it — so all 3 OR
        bars are available and the signal can fire."""
        today = date(2026, 4, 7)
        engine = LiveSignalEngine(
            tickers=["APP"],
            api_key="k",
            secret_key="s",
            windows=[
                {
                    "label": "M1",
                    "opening_start": "10:25",
                    "opening_bars": 3,
                    "on_signal": None,
                }
            ],
        )
        or_start = ET.localize(
            datetime.combine(today, datetime.strptime("10:25", "%H:%M").time())
        )
        bar_10_25 = or_start
        bar_10_30 = or_start + timedelta(minutes=5)
        bar_10_35 = or_start + timedelta(minutes=10)

        # Engine started at 10:39 — only 1-min bar 10:39 in _minute_buf for period 10:35
        engine._minute_buf["APP"] = {
            "period_start": bar_10_35,
            "bars": [self._make_1min_bar(403.0, 404.0, 402.0, 403.5)],
        }

        def _make_alpaca_df(*period_starts):
            """Build a minimal multi-index DataFrame like Alpaca returns."""
            tuples = [(sym, ts) for sym in ["APP"] for ts in period_starts]
            idx = pd.MultiIndex.from_tuples(tuples, names=["symbol", "timestamp"])
            return pd.DataFrame(
                {
                    "open": [400.0] * len(tuples),
                    "high": [401.0] * len(tuples),
                    "low":  [399.0] * len(tuples),
                    "close": [400.5] * len(tuples),
                    "volume": [1000.0] * len(tuples),
                },
                index=idx,
            )

        # Alpaca returns 10:25 and 10:30 bars (the two older OR bars)
        alpaca_df = _make_alpaca_df(bar_10_25, bar_10_30)
        mock_alpaca_instance = Mock()
        mock_alpaca_instance.get_stock_bars.return_value = Mock(df=alpaca_df)

        injected_bars = []

        def fake_process(bar):
            injected_bars.append(bar)
            engine._opening_buf["M1"]["APP"].append(bar)

        with patch.object(engine, "_process_five_min_bar", side_effect=fake_process), \
             patch(
                 "alpha_tech_tracker.op_momentum_strategy.signal_engine.StockHistoricalDataClient",
                 return_value=mock_alpaca_instance,
             ):
            engine._catch_up_opening_bars_for_window(today, engine._windows[0])

        injected_timestamps = {b.timestamp for b in injected_bars}
        # All 3 OR bars must be present
        assert bar_10_25 in injected_timestamps, "10:25 bar missing — Alpaca pass skipped it"
        assert bar_10_30 in injected_timestamps, "10:30 bar missing — incorrectly skipped as recent_period"
        assert bar_10_35 in injected_timestamps, "10:35 bar missing — client-side pass failed"
        assert len(engine._opening_buf["M1"]["APP"]) == 3


class TestCatchUpSingleTickerMultiIndex:
    """Regression tests for single-ticker catchup crash.

    When only one ticker needs API catchup, Alpaca returns a flat DatetimeIndex
    instead of a (symbol, timestamp) MultiIndex.  The fix normalises the frame
    with pd.concat before the per-ticker loop so .xs() works uniformly.
    """

    def _make_a1_engine(self, ticker="MU"):
        return LiveSignalEngine(
            tickers=[ticker],
            api_key="k",
            secret_key="s",
            windows=[
                {
                    "label": "A1",
                    "opening_start": "13:15",
                    "opening_bars": 1,
                    "on_signal": None,
                }
            ],
        )

    def _make_flat_alpaca_df(self, ticker, ts):
        """Simulate what Alpaca returns when exactly one ticker is requested."""
        idx = pd.DatetimeIndex([ts], name="timestamp")
        return pd.DataFrame(
            {"open": [408.0], "high": [409.0], "low": [407.5], "close": [408.5], "volume": [500.0]},
            index=idx,
        )

    def test_single_ticker_flat_index_does_not_raise(self):
        today = date(2026, 4, 9)
        engine = self._make_a1_engine("MU")
        or_start = ET.localize(
            datetime.combine(today, datetime.strptime("13:15", "%H:%M").time())
        )
        flat_df = self._make_flat_alpaca_df("MU", or_start)

        mock_alpaca_instance = Mock()
        mock_alpaca_instance.get_stock_bars.return_value = Mock(df=flat_df)

        with patch.object(engine, "_process_five_min_bar"), \
             patch(
                 "alpha_tech_tracker.op_momentum_strategy.signal_engine.StockHistoricalDataClient",
                 return_value=mock_alpaca_instance,
             ):
            engine._catch_up_opening_bars_for_window(today, engine._windows[0])

    def test_single_ticker_flat_index_injects_bar(self):
        today = date(2026, 4, 9)
        engine = self._make_a1_engine("MU")
        or_start = ET.localize(
            datetime.combine(today, datetime.strptime("13:15", "%H:%M").time())
        )
        flat_df = self._make_flat_alpaca_df("MU", or_start)

        mock_alpaca_instance = Mock()
        mock_alpaca_instance.get_stock_bars.return_value = Mock(df=flat_df)

        injected = []

        def fake_process(bar):
            injected.append(bar)
            engine._opening_buf["A1"]["MU"].append(bar)

        with patch.object(engine, "_process_five_min_bar", side_effect=fake_process), \
             patch(
                 "alpha_tech_tracker.op_momentum_strategy.signal_engine.StockHistoricalDataClient",
                 return_value=mock_alpaca_instance,
             ):
            engine._catch_up_opening_bars_for_window(today, engine._windows[0])

        assert len(injected) == 1
        assert injected[0].symbol == "MU"
        assert injected[0].open == 408.0
        assert injected[0].close == 408.5

    def test_multi_ticker_multi_index_still_works(self):
        """Existing multi-ticker path (MultiIndex) is unaffected by the fix."""
        today = date(2026, 4, 9)
        engine = LiveSignalEngine(
            tickers=["MU", "NVDA"],
            api_key="k",
            secret_key="s",
            windows=[{"label": "A1", "opening_start": "13:15", "opening_bars": 1, "on_signal": None}],
        )
        or_start = ET.localize(
            datetime.combine(today, datetime.strptime("13:15", "%H:%M").time())
        )
        tuples = [("MU", or_start), ("NVDA", or_start)]
        idx = pd.MultiIndex.from_tuples(tuples, names=["symbol", "timestamp"])
        multi_df = pd.DataFrame(
            {"open": [408.0, 183.0], "high": [409.0, 184.0], "low": [407.0, 182.0],
             "close": [408.5, 183.5], "volume": [500.0, 1000.0]},
            index=idx,
        )

        mock_alpaca_instance = Mock()
        mock_alpaca_instance.get_stock_bars.return_value = Mock(df=multi_df)

        injected = []

        def fake_process(bar):
            injected.append(bar)
            engine._opening_buf["A1"][bar.symbol].append(bar)

        with patch.object(engine, "_process_five_min_bar", side_effect=fake_process), \
             patch(
                 "alpha_tech_tracker.op_momentum_strategy.signal_engine.StockHistoricalDataClient",
                 return_value=mock_alpaca_instance,
             ):
            engine._catch_up_opening_bars_for_window(today, engine._windows[0])

        symbols = {b.symbol for b in injected}
        assert "MU" in symbols
        assert "NVDA" in symbols


class TestFlatOrSignalGuard:
    """When all OR bars are synthetic (volume=0, or_range=0), _try_fire_signal
    must not emit a signal — no real price discovery took place."""

    def test_zero_range_or_does_not_fire_signal(self):
        closes = [25.0] * 25
        ma_vals = [30.0] * 25  # close < MA20 → would trigger BEARISH if not guarded
        engine = _make_signal_engine_with_history(
            "ANAB", _build_history_df(closes, ma_vals, ma_vals, ma_vals)
        )
        fired = []
        engine._windows[0]["on_signal"] = fired.append

        today = _now_et().date()
        or_start = ET.localize(
            datetime.combine(today, datetime.strptime("09:30", "%H:%M").time())
        )
        flat_bars = [
            _FiveMinBar("ANAB", or_start + timedelta(minutes=i * 5),
                        25.0, 25.0, 25.0, 25.0, 0.0)
            for i in range(3)
        ]
        for bar in flat_bars:
            engine._process_five_min_bar(bar)

        assert len(fired) == 0

    def test_partial_real_bar_with_nonzero_range_can_fire(self):
        # Need 200+ bars so MA200 is not NaN after _append_bar recalculates it
        n = 210
        closes = [100.0] * n
        ma_vals = [90.0] * n  # close > MA20/MA200 → BULLISH possible
        engine = _make_signal_engine_with_history(
            "NVDA", _build_history_df(closes, ma_vals, ma_vals, ma_vals)
        )
        fired = []
        engine._windows[0]["on_signal"] = fired.append

        today = _now_et().date()
        or_start = ET.localize(
            datetime.combine(today, datetime.strptime("09:30", "%H:%M").time())
        )
        # Two flat bars + one real bar with a higher high → nonzero OR range
        flat_bar_0 = _FiveMinBar("NVDA", or_start, 100.0, 100.0, 100.0, 100.0, 0.0)
        flat_bar_1 = _FiveMinBar("NVDA", or_start + timedelta(minutes=5),
                                  100.0, 100.0, 100.0, 100.0, 0.0)
        real_bar = _FiveMinBar("NVDA", or_start + timedelta(minutes=10),
                               100.0, 106.0, 99.0, 104.0, 1500.0)
        for bar in [flat_bar_0, flat_bar_1, real_bar]:
            engine._process_five_min_bar(bar)

        # OR range = 106 - 99 = 7 (nonzero) → signal evaluation proceeds
        assert len(fired) == 1


class TestMakeFlatBar:
    def _make_engine_with_last_close(self, ticker, last_close):
        engine = LiveSignalEngine(tickers=[ticker], api_key="k", secret_key="s")
        engine._history[ticker] = _build_history_df(
            closes=[last_close] * 5,
            ma20=[last_close] * 5,
            ma50=[last_close] * 5,
            ma200=[last_close] * 5,
        )
        return engine

    def test_flat_bar_ohlc_equals_last_close(self):
        engine = self._make_engine_with_last_close("ANAB", 25.0)
        ts = ET.localize(datetime(2026, 4, 10, 9, 35))
        bar = engine._make_flat_bar("ANAB", ts)
        assert bar.open == 25.0
        assert bar.high == 25.0
        assert bar.low == 25.0
        assert bar.close == 25.0

    def test_flat_bar_volume_is_zero(self):
        engine = self._make_engine_with_last_close("ANAB", 25.0)
        ts = ET.localize(datetime(2026, 4, 10, 9, 35))
        bar = engine._make_flat_bar("ANAB", ts)
        assert bar.volume == 0.0

    def test_flat_bar_symbol_and_timestamp(self):
        engine = self._make_engine_with_last_close("ANAB", 25.0)
        ts = ET.localize(datetime(2026, 4, 10, 9, 35))
        bar = engine._make_flat_bar("ANAB", ts)
        assert bar.symbol == "ANAB"
        assert bar.timestamp == ts

    def test_returns_none_when_no_history(self):
        engine = LiveSignalEngine(tickers=["ANAB"], api_key="k", secret_key="s")
        ts = ET.localize(datetime(2026, 4, 10, 9, 35))
        assert engine._make_flat_bar("ANAB", ts) is None


class TestFillOrGapsWithFlatBars:
    def _make_m1_engine(self, ticker="ANAB", last_close=25.0):
        engine = LiveSignalEngine(
            tickers=[ticker],
            api_key="k",
            secret_key="s",
            windows=[{"label": "M1", "opening_start": "09:30", "opening_bars": 3, "on_signal": None}],
        )
        engine._history[ticker] = _build_history_df(
            closes=[last_close] * 5,
            ma20=[last_close] * 5,
            ma50=[last_close] * 5,
            ma200=[last_close] * 5,
        )
        return engine

    def _or_bar_period_starts(self, today, opening_start="09:30", opening_bars=3):
        or_start = ET.localize(datetime.combine(today, datetime.strptime(opening_start, "%H:%M").time()))
        return [or_start + timedelta(minutes=i * 5) for i in range(opening_bars)]

    def test_fills_all_three_missing_or_slots(self):
        today = date(2026, 1, 15)  # past date — does not overlap warmup history timestamps
        engine = self._make_m1_engine("ANAB")
        injected = []

        def fake_process(bar):
            injected.append(bar)
            engine._opening_buf["M1"]["ANAB"].append(bar)

        with patch.object(engine, "_process_five_min_bar", side_effect=fake_process):
            engine._fill_or_gaps_with_flat_bars(
                "ANAB", "M1", self._or_bar_period_starts(today), engine._windows[0]
            )

        assert len(injected) == 3
        assert all(b.symbol == "ANAB" for b in injected)
        assert all(b.volume == 0.0 for b in injected)
        assert all(b.open == b.high == b.low == b.close == 25.0 for b in injected)

    def test_does_not_overwrite_existing_real_bar(self):
        today = date(2026, 1, 15)
        engine = self._make_m1_engine("ANAB")
        or_starts = self._or_bar_period_starts(today)

        # Pre-populate history with a real bar at the first OR slot
        real_row = pd.Series(
            {"Open": 26.0, "High": 27.0, "Low": 25.0, "Close": 26.5, "Volume": 1000.0,
             "MA20": 25.0, "MA50": 25.0, "MA200": 25.0},
            name=or_starts[0],
        )
        engine._history["ANAB"] = pd.concat(
            [engine._history["ANAB"], real_row.to_frame().T]
        )
        engine._opening_buf["M1"]["ANAB"].append(Mock())  # 1 bar already in buf

        injected = []

        def fake_process(bar):
            injected.append(bar)
            engine._opening_buf["M1"]["ANAB"].append(bar)

        with patch.object(engine, "_process_five_min_bar", side_effect=fake_process):
            engine._fill_or_gaps_with_flat_bars(
                "ANAB", "M1", or_starts, engine._windows[0]
            )

        # Only 2 flat bars should be synthesized (slots 2 and 3)
        assert len(injected) == 2

    def test_does_nothing_when_or_buffer_already_full(self):
        today = date(2026, 1, 15)
        engine = self._make_m1_engine("ANAB")
        engine._opening_buf["M1"]["ANAB"] = [Mock(), Mock(), Mock()]

        with patch.object(engine, "_process_five_min_bar") as mock_process:
            engine._fill_or_gaps_with_flat_bars(
                "ANAB", "M1", self._or_bar_period_starts(today), engine._windows[0]
            )

        mock_process.assert_not_called()


class TestHandleBarGapFill:
    """When a bar arrives for a period that is multiple slots ahead of the last
    known period, _handle_bar should synthesize flat bars for each skipped slot."""

    def _make_engine_with_history(self, ticker="ANAB", last_close=25.0):
        today = date(2026, 4, 10)
        engine = LiveSignalEngine(
            tickers=[ticker],
            api_key="k",
            secret_key="s",
            windows=[{"label": "M1", "opening_start": "09:30", "opening_bars": 3, "on_signal": None}],
        )
        engine._session_date = today
        engine._history[ticker] = _build_history_df(
            closes=[last_close] * 5,
            ma20=[last_close] * 5,
            ma50=[last_close] * 5,
            ma200=[last_close] * 5,
        )
        return engine

    def _make_ws_bar(self, ticker, ts_et, open_=25.0, high=25.5, low=24.5, close=25.0, volume=500):
        bar = Mock()
        bar.symbol = ticker
        bar.open, bar.high, bar.low, bar.close, bar.volume = open_, high, low, close, volume
        bar.timestamp = ts_et
        return bar

    def _run_handle_bar(self, engine, ws_bar, today, capture_fn):
        fake_now = ET.localize(datetime.combine(today, datetime.strptime("10:00", "%H:%M").time()))
        with patch(f"{_SE_MODULE}._now_et", return_value=fake_now), \
             patch.object(engine, "_process_five_min_bar", side_effect=capture_fn):
            asyncio.run(engine._handle_bar(ws_bar))

    def test_gap_of_one_period_emits_one_flat_bar(self):
        today = date(2026, 4, 10)
        engine = self._make_engine_with_history("ANAB")
        # Seed minute buf at 09:30 with a real bar
        period_930 = ET.localize(datetime.combine(today, datetime.strptime("09:30", "%H:%M").time()))
        mock_min_bar = Mock()
        mock_min_bar.open = mock_min_bar.high = mock_min_bar.low = mock_min_bar.close = 25.0
        mock_min_bar.volume = 200.0
        engine._minute_buf["ANAB"] = {"period_start": period_930, "bars": [mock_min_bar]}

        injected = []
        original_process = engine._process_five_min_bar

        def capture_process(bar):
            injected.append(bar)
            original_process(bar)

        # Deliver a bar that belongs to period 09:40 (skipping 09:35)
        period_940 = period_930 + timedelta(minutes=10)
        ws_bar = self._make_ws_bar("ANAB", period_940 + timedelta(seconds=30))
        self._run_handle_bar(engine, ws_bar, today, capture_process)

        flat_bars = [b for b in injected if b.volume == 0.0]
        assert len(flat_bars) == 1
        assert flat_bars[0].timestamp == period_930 + timedelta(minutes=5)

    def test_gap_of_two_periods_emits_two_flat_bars(self):
        today = date(2026, 4, 10)
        engine = self._make_engine_with_history("ANAB")
        period_930 = ET.localize(datetime.combine(today, datetime.strptime("09:30", "%H:%M").time()))
        mock_min_bar = Mock()
        mock_min_bar.open = mock_min_bar.high = mock_min_bar.low = mock_min_bar.close = 25.0
        mock_min_bar.volume = 200.0
        engine._minute_buf["ANAB"] = {"period_start": period_930, "bars": [mock_min_bar]}

        injected = []
        original_process = engine._process_five_min_bar

        def capture_process(bar):
            injected.append(bar)
            original_process(bar)

        # Deliver a bar that belongs to period 09:45 (skipping 09:35 and 09:40)
        period_945 = period_930 + timedelta(minutes=15)
        ws_bar = self._make_ws_bar("ANAB", period_945 + timedelta(seconds=30))
        self._run_handle_bar(engine, ws_bar, today, capture_process)

        flat_bars = [b for b in injected if b.volume == 0.0]
        assert len(flat_bars) == 2
        flat_timestamps = sorted(b.timestamp for b in flat_bars)
        assert flat_timestamps[0] == period_930 + timedelta(minutes=5)
        assert flat_timestamps[1] == period_930 + timedelta(minutes=10)

    def test_flat_bar_close_matches_last_known_close(self):
        today = date(2026, 4, 10)
        engine = self._make_engine_with_history("ANAB", last_close=31.5)
        period_930 = ET.localize(datetime.combine(today, datetime.strptime("09:30", "%H:%M").time()))
        mock_min_bar = Mock()
        mock_min_bar.open = mock_min_bar.high = mock_min_bar.low = mock_min_bar.close = 31.5
        mock_min_bar.volume = 200.0
        engine._minute_buf["ANAB"] = {"period_start": period_930, "bars": [mock_min_bar]}

        injected = []
        original_process = engine._process_five_min_bar

        def capture_process(bar):
            injected.append(bar)
            original_process(bar)

        period_940 = period_930 + timedelta(minutes=10)
        ws_bar = self._make_ws_bar("ANAB", period_940 + timedelta(seconds=30), open_=31.5, close=31.5)
        self._run_handle_bar(engine, ws_bar, today, capture_process)

        flat_bars = [b for b in injected if b.volume == 0.0]
        assert len(flat_bars) == 1
        assert flat_bars[0].open == flat_bars[0].high == flat_bars[0].low == flat_bars[0].close


class TestCatchUpWithFlatBarFallback:
    """When Alpaca has no IEX data for a ticker's OR slots, the catchup should
    synthesize flat bars so the signal can still fire."""

    def _make_m1_engine(self, ticker="ANAB", last_close=25.0):
        today = date(2026, 4, 10)
        engine = LiveSignalEngine(
            tickers=[ticker],
            api_key="k",
            secret_key="s",
            windows=[{"label": "M1", "opening_start": "09:30", "opening_bars": 3, "on_signal": None}],
        )
        engine._history[ticker] = _build_history_df(
            closes=[last_close] * 5,
            ma20=[last_close] * 5,
            ma50=[last_close] * 5,
            ma200=[last_close] * 5,
        )
        return engine

    def _empty_alpaca_df(self):
        return pd.DataFrame(
            columns=["open", "high", "low", "close", "volume"],
            index=pd.MultiIndex.from_tuples([], names=["symbol", "timestamp"]),
        )

    def test_no_alpaca_data_synthesizes_three_flat_or_bars(self):
        today = date(2026, 1, 15)
        engine = self._make_m1_engine("ANAB")
        injected = []

        def fake_process(bar):
            injected.append(bar)
            engine._opening_buf["M1"]["ANAB"].append(bar)
            engine._signal_fired["M1"]["ANAB"] = len(engine._opening_buf["M1"]["ANAB"]) >= 3

        mock_alpaca = Mock()
        mock_alpaca.get_stock_bars.return_value = Mock(df=self._empty_alpaca_df())

        with patch.object(engine, "_process_five_min_bar", side_effect=fake_process), \
             patch(
                 "alpha_tech_tracker.op_momentum_strategy.signal_engine.StockHistoricalDataClient",
                 return_value=mock_alpaca,
             ):
            engine._catch_up_opening_bars_for_window(today, engine._windows[0])

        assert len(injected) == 3
        assert all(b.volume == 0.0 for b in injected)
        assert all(b.symbol == "ANAB" for b in injected)

    def test_partial_alpaca_data_fills_remaining_slots_with_flat_bars(self):
        today = date(2026, 1, 15)
        engine = self._make_m1_engine("ANAB")
        or_start = ET.localize(datetime.combine(today, datetime.strptime("09:30", "%H:%M").time()))

        injected = []

        def fake_process(bar):
            injected.append(bar)
            engine._opening_buf["M1"]["ANAB"].append(bar)

        # Alpaca returns only 1 of the 3 OR bars
        idx = pd.MultiIndex.from_tuples(
            [("ANAB", or_start.astimezone(pytz.utc))],
            names=["symbol", "timestamp"],
        )
        alpaca_df = pd.DataFrame(
            [{"open": 26.0, "high": 27.0, "low": 25.0, "close": 26.5, "volume": 500.0}],
            index=idx,
        )
        mock_alpaca = Mock()
        mock_alpaca.get_stock_bars.return_value = Mock(df=alpaca_df)

        with patch.object(engine, "_process_five_min_bar", side_effect=fake_process), \
             patch(
                 "alpha_tech_tracker.op_momentum_strategy.signal_engine.StockHistoricalDataClient",
                 return_value=mock_alpaca,
             ):
            engine._catch_up_opening_bars_for_window(today, engine._windows[0])

        # 1 real bar + 2 flat bars = 3 total
        assert len(injected) == 3
        real_bars = [b for b in injected if b.volume > 0]
        flat_bars = [b for b in injected if b.volume == 0.0]
        assert len(real_bars) == 1
        assert len(flat_bars) == 2

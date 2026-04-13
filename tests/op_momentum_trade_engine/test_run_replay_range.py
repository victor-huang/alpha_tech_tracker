from datetime import date
from decimal import Decimal
from unittest.mock import patch

from alpha_tech_tracker.op_momentum_strategy.trade_engine import (
    OpMomentumTradeEngine,
    _trading_days_in_range,
)

from conftest import _make_alpaca_client

_IS_NYSE_HOLIDAY_PATH = (
    "alpha_tech_tracker.op_momentum_strategy.trade_engine._is_nyse_holiday"
)


def _D(x) -> Decimal:
    return Decimal(str(x))


def _make_engine(replay_capital=10000.0):
    client = _make_alpaca_client()
    return OpMomentumTradeEngine(
        alpaca_client=client,
        mock_trade_execution=True,
        replay_capital=replay_capital,
    )


# ---------------------------------------------------------------------------
# TestTradingDaysInRange
# ---------------------------------------------------------------------------


class TestTradingDaysInRange:
    def test_returns_all_weekdays_in_range(self):
        # 2026-03-16 Mon → 2026-03-18 Wed
        days = _trading_days_in_range(date(2026, 3, 16), date(2026, 3, 18))
        assert days == [date(2026, 3, 16), date(2026, 3, 17), date(2026, 3, 18)]

    def test_includes_start_and_end_dates(self):
        days = _trading_days_in_range(date(2026, 3, 16), date(2026, 3, 20))
        assert date(2026, 3, 16) in days
        assert date(2026, 3, 20) in days

    def test_excludes_saturday_and_sunday(self):
        # 2026-03-13 Fri → 2026-03-16 Mon
        days = _trading_days_in_range(date(2026, 3, 13), date(2026, 3, 16))
        assert date(2026, 3, 14) not in days  # Saturday
        assert date(2026, 3, 15) not in days  # Sunday
        assert days == [date(2026, 3, 13), date(2026, 3, 16)]

    def test_returns_empty_for_weekend_only_range(self):
        days = _trading_days_in_range(date(2026, 3, 14), date(2026, 3, 15))
        assert days == []

    def test_returns_empty_for_inverted_range(self):
        days = _trading_days_in_range(date(2026, 3, 18), date(2026, 3, 16))
        assert days == []

    def test_single_trading_day(self):
        days = _trading_days_in_range(date(2026, 3, 17), date(2026, 3, 17))
        assert days == [date(2026, 3, 17)]

    def test_single_weekend_day_returns_empty(self):
        days = _trading_days_in_range(date(2026, 3, 14), date(2026, 3, 14))
        assert days == []

    def test_skips_nyse_holiday(self):
        # Good Friday 2026 is April 3 — NYSE is closed
        days = _trading_days_in_range(date(2026, 4, 2), date(2026, 4, 6))
        assert date(2026, 4, 3) not in days
        assert date(2026, 4, 2) in days   # Thursday before
        assert date(2026, 4, 6) in days   # Monday after

    def test_full_week_returns_five_days(self):
        # 2026-03-16 Mon → 2026-03-20 Fri
        with patch(_IS_NYSE_HOLIDAY_PATH, return_value=False):
            days = _trading_days_in_range(date(2026, 3, 16), date(2026, 3, 20))
        assert len(days) == 5


# ---------------------------------------------------------------------------
# TestRunReplayRange
# ---------------------------------------------------------------------------


class TestRunReplayRange:
    def test_calls_run_replay_once_per_trading_day(self):
        engine = _make_engine()
        called_dates = []

        def fake_replay(day, **kwargs):
            called_dates.append(day)

        with patch.object(engine, "run_replay", side_effect=fake_replay), \
             patch(_IS_NYSE_HOLIDAY_PATH, return_value=False):
            engine.run_replay_range(date(2026, 3, 16), date(2026, 3, 18))

        assert called_dates == [date(2026, 3, 16), date(2026, 3, 17), date(2026, 3, 18)]

    def test_skips_weekends_between_dates(self):
        engine = _make_engine()
        called_dates = []

        def fake_replay(day, **kwargs):
            called_dates.append(day)

        with patch.object(engine, "run_replay", side_effect=fake_replay), \
             patch(_IS_NYSE_HOLIDAY_PATH, return_value=False):
            engine.run_replay_range(date(2026, 3, 13), date(2026, 3, 16))

        assert called_dates == [date(2026, 3, 13), date(2026, 3, 16)]

    def test_empty_range_does_not_call_run_replay(self):
        engine = _make_engine()

        with patch.object(engine, "run_replay") as mock_replay, \
             patch(_IS_NYSE_HOLIDAY_PATH, return_value=False):
            engine.run_replay_range(date(2026, 3, 18), date(2026, 3, 16))

        mock_replay.assert_not_called()

    def test_no_compound_does_not_update_replay_capital(self):
        engine = _make_engine(replay_capital=10000.0)
        captured_capitals = []

        def fake_replay(day, **kwargs):
            captured_capitals.append(engine._replay_capital)
            engine._daily_realized_pnl = _D("500")

        with patch.object(engine, "run_replay", side_effect=fake_replay), \
             patch(_IS_NYSE_HOLIDAY_PATH, return_value=False):
            engine.run_replay_range(date(2026, 3, 16), date(2026, 3, 18), compound=False)

        assert all(c == 10000.0 for c in captured_capitals)

    def test_compound_carries_pnl_forward_each_day(self):
        engine = _make_engine(replay_capital=10000.0)
        captured_capitals = []

        def fake_replay(day, **kwargs):
            captured_capitals.append(float(engine._replay_capital))
            engine._daily_realized_pnl = _D("500")

        with patch.object(engine, "run_replay", side_effect=fake_replay), \
             patch(_IS_NYSE_HOLIDAY_PATH, return_value=False):
            engine.run_replay_range(date(2026, 3, 16), date(2026, 3, 18), compound=True)

        assert captured_capitals == [10000.0, 10500.0, 11000.0]

    def test_compound_negative_pnl_reduces_next_day_capital(self):
        engine = _make_engine(replay_capital=10000.0)
        captured_capitals = []

        def fake_replay(day, **kwargs):
            captured_capitals.append(float(engine._replay_capital))
            engine._daily_realized_pnl = _D("-300")

        with patch.object(engine, "run_replay", side_effect=fake_replay), \
             patch(_IS_NYSE_HOLIDAY_PATH, return_value=False):
            engine.run_replay_range(date(2026, 3, 16), date(2026, 3, 17), compound=True)

        assert captured_capitals == [10000.0, 9700.0]

    def test_restores_original_replay_capital_after_range(self):
        engine = _make_engine(replay_capital=10000.0)

        def fake_replay(day, **kwargs):
            engine._daily_realized_pnl = _D("999")

        with patch.object(engine, "run_replay", side_effect=fake_replay), \
             patch(_IS_NYSE_HOLIDAY_PATH, return_value=False):
            engine.run_replay_range(date(2026, 3, 16), date(2026, 3, 18), compound=True)

        assert engine._replay_capital == 10000.0

    def test_passes_tickers_override_to_each_day(self):
        engine = _make_engine()
        captured_kwargs = []

        def fake_replay(day, **kwargs):
            captured_kwargs.append(kwargs.get("tickers_override"))

        with patch.object(engine, "run_replay", side_effect=fake_replay), \
             patch(_IS_NYSE_HOLIDAY_PATH, return_value=False):
            engine.run_replay_range(
                date(2026, 3, 16), date(2026, 3, 17),
                tickers_override=["NVDA", "AMD"],
            )

        assert all(t == ["NVDA", "AMD"] for t in captured_kwargs)

    def test_passes_replay_exit_time_to_each_day(self):
        engine = _make_engine()
        captured_kwargs = []

        def fake_replay(day, **kwargs):
            captured_kwargs.append(kwargs.get("replay_exit_time"))

        with patch.object(engine, "run_replay", side_effect=fake_replay), \
             patch(_IS_NYSE_HOLIDAY_PATH, return_value=False):
            engine.run_replay_range(
                date(2026, 3, 16), date(2026, 3, 17),
                replay_exit_time="16:05",
            )

        assert all(t == "16:05" for t in captured_kwargs)

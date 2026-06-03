import json
import os
import tempfile
from datetime import date
from unittest.mock import patch

import pytest

from alpha_tech_tracker.op_momentum_strategy.regime_engine import (
    DailyRegimeMetrics,
    RegimeEngine,
)


def _metrics(
    d,
    eod_wr=0.60,
    avg_gain=0.5,
    avg_win=1.2,
    avg_loss=-0.6,
    signal_count=5,
    hold_curve=None,
):
    if hold_curve is None:
        hold_curve = {"+15m": 0.7, "+30m": 0.65, "+1h": 0.6, "+2h": 0.55, "+3h": 0.52, "+5h": 0.50, "EOD": 0.60}
    return DailyRegimeMetrics(
        date=d,
        signal_count=signal_count,
        eod_wr=eod_wr,
        avg_gain=avg_gain,
        avg_win=avg_win,
        avg_loss=avg_loss,
        hold_curve=hold_curve,
    )


def _rising_bull_curve():
    return {"+15m": 0.55, "+30m": 0.60, "+1h": 0.65, "+2h": 0.68, "+3h": 0.72, "+5h": 0.75, "EOD": 0.78}


def _am_pop_fade_curve():
    # +15m positive, drops ≥15pp by +30m
    return {"+15m": 0.75, "+30m": 0.55, "+1h": 0.50, "+2h": 0.45, "+3h": 0.42, "+5h": 0.40, "EOD": 0.38}


def _bear_curve():
    return {"+15m": 0.45, "+30m": 0.40, "+1h": 0.35, "+2h": 0.30, "+3h": 0.28, "+5h": 0.25, "EOD": 0.22}


def _engine_with_history(metrics_list):
    with tempfile.TemporaryDirectory() as tmpdir:
        engine = RegimeEngine(data_dir=tmpdir)
        for m in metrics_list:
            engine.add_daily_result(m)
        yield engine


class TestDailyRegimeMetrics:
    def test_fields_stored_correctly(self):
        m = _metrics(date(2026, 1, 5))
        assert m.date == date(2026, 1, 5)
        assert m.eod_wr == 0.60
        assert m.signal_count == 5
        assert "+15m" in m.hold_curve


class TestRegimeEngineInit:
    def test_starts_with_empty_history(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = RegimeEngine(data_dir=tmpdir)
            assert engine._history == []

    def test_loads_existing_json_on_init(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            m = _metrics(date(2026, 1, 5))
            engine1 = RegimeEngine(data_dir=tmpdir)
            engine1.add_daily_result(m)

            engine2 = RegimeEngine(data_dir=tmpdir)
            assert len(engine2._history) == 1
            assert engine2._history[0].date == date(2026, 1, 5)

    def test_loads_only_last_10_trading_days(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            engine1 = RegimeEngine(data_dir=tmpdir)
            for i in range(15):
                engine1.add_daily_result(_metrics(date(2026, 1, i + 2)))

            engine2 = RegimeEngine(data_dir=tmpdir)
            assert len(engine2._history) == 10


class TestAddDailyResult:
    def test_appends_to_in_memory_history(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = RegimeEngine(data_dir=tmpdir)
            engine.add_daily_result(_metrics(date(2026, 1, 5)))
            engine.add_daily_result(_metrics(date(2026, 1, 6)))
            assert len(engine._history) == 2

    def test_persists_to_json_by_year(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = RegimeEngine(data_dir=tmpdir)
            engine.add_daily_result(_metrics(date(2026, 3, 10)))

            json_path = os.path.join(tmpdir, "regime_metrics_2026.json")
            assert os.path.exists(json_path)
            with open(json_path) as f:
                records = json.load(f)
            assert len(records) == 1
            assert records[0]["date"] == "2026-03-10"

    def test_does_not_duplicate_existing_date(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = RegimeEngine(data_dir=tmpdir)
            engine.add_daily_result(_metrics(date(2026, 1, 5), eod_wr=0.60))
            engine.add_daily_result(_metrics(date(2026, 1, 5), eod_wr=0.75))
            assert len(engine._history) == 1
            assert engine._history[0].eod_wr == 0.60


class TestSeasonalPrior:
    @pytest.mark.parametrize("month,expected_direction,expected_hold", [
        (1, "LONG", "EOD"),
        (2, "NEUTRAL", "+30m"),
        (3, "NO_POSITION", None),
        (4, "NEUTRAL", "+1h"),
        (5, "LONG", "+1h"),
        (6, "NEUTRAL", "+1h"),
        (7, "NEUTRAL", "EOD"),
        (8, "NEUTRAL", "+15m"),
        (9, "SHORT", "+15m"),
        (10, "LONG", "EOD"),
        (11, "NEUTRAL", None),
        (12, "SHORT", "+1h"),
    ])
    def test_seasonal_prior_direction(self, month, expected_direction, expected_hold):
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = RegimeEngine(data_dir=tmpdir)
            regime = engine._seasonal_prior(month)
            assert regime.direction == expected_direction
            if expected_hold is not None:
                assert regime.hold_window == expected_hold

    def test_march_returns_no_position(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = RegimeEngine(data_dir=tmpdir)
            regime = engine._seasonal_prior(3)
            assert regime.direction == "NO_POSITION"
            assert regime.source == "seasonal"

    def test_november_returns_neutral_with_wait_note(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = RegimeEngine(data_dir=tmpdir)
            regime = engine._seasonal_prior(11)
            assert regime.direction == "NEUTRAL"
            assert "week-1" in regime.notes.lower() or "ev" in regime.notes.lower()


class TestRollingCheck:
    def test_rising_bull_detected(self):
        history = [
            _metrics(date(2026, 1, d), eod_wr=0.65, hold_curve=_rising_bull_curve())
            for d in range(2, 6)
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = RegimeEngine(data_dir=tmpdir)
            regime = engine._rolling_check(history)
        assert regime.direction == "LONG"
        assert regime.hold_window == "EOD"
        assert regime.regime_type == "Rising Bull"

    def test_am_pop_fade_detected(self):
        history = [
            _metrics(date(2026, 1, d), hold_curve=_am_pop_fade_curve())
            for d in range(2, 6)
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = RegimeEngine(data_dir=tmpdir)
            regime = engine._rolling_check(history)
        assert regime.direction == "LONG"
        assert regime.hold_window == "+15m"
        assert regime.regime_type == "AM Pop-Fade"

    def test_persistent_bear_detected(self):
        history = [
            _metrics(date(2026, 1, d), eod_wr=0.35, hold_curve=_bear_curve())
            for d in range(2, 6)
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = RegimeEngine(data_dir=tmpdir)
            regime = engine._rolling_check(history)
        assert regime.direction == "SHORT"
        assert regime.hold_window == "EOD"
        assert regime.regime_type == "Persistent Bear"

    def test_high_wr_trap_detected(self):
        # EOD WR ≥ 55% but avg_gain ≤ 0
        history = [
            _metrics(date(2026, 1, d), eod_wr=0.60, avg_gain=-0.1, hold_curve=_rising_bull_curve())
            for d in range(2, 6)
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = RegimeEngine(data_dir=tmpdir)
            regime = engine._rolling_check(history)
        assert regime.regime_type == "High-WR Trap"
        assert regime.hold_window == "+15m"

    def test_low_wr_positive_ev_detected(self):
        # EOD WR < 50%, avg_win ≥ 1.5 × |avg_loss|
        history = [
            _metrics(date(2026, 1, d), eod_wr=0.45, avg_win=2.0, avg_loss=-0.8, hold_curve=_rising_bull_curve())
            for d in range(2, 6)
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = RegimeEngine(data_dir=tmpdir)
            regime = engine._rolling_check(history)
        assert regime.regime_type == "Low-WR Positive EV"
        assert regime.hold_window == "+5h"

    def test_u_curve_detected(self):
        # AM negative, midday bear, EOD recovery
        u_curve = {"+15m": 0.38, "+30m": 0.35, "+1h": 0.32, "+2h": 0.35, "+3h": 0.42, "+5h": 0.50, "EOD": 0.62}
        history = [
            _metrics(date(2026, 1, d), eod_wr=0.62, hold_curve=u_curve)
            for d in range(2, 6)
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = RegimeEngine(data_dir=tmpdir)
            regime = engine._rolling_check(history)
        assert regime.regime_type == "U-Curve"
        assert regime.direction == "LONG"

    def test_returns_none_with_fewer_than_3_days(self):
        history = [
            _metrics(date(2026, 1, d), hold_curve=_rising_bull_curve())
            for d in range(2, 4)
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = RegimeEngine(data_dir=tmpdir)
            regime = engine._rolling_check(history)
        assert regime is None


class TestTransitionCheck:
    def test_bear_to_bull_flip_detected(self):
        # ≥5 consecutive days EOD WR < 40%, then one day ≥ 70%
        bear_days = [
            _metrics(date(2026, 1, d), eod_wr=0.30)
            for d in range(2, 8)
        ]
        flip_day = _metrics(date(2026, 1, 8), eod_wr=0.72)
        history = bear_days + [flip_day]
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = RegimeEngine(data_dir=tmpdir)
            regime = engine._transition_check(history)
        assert regime is not None
        assert regime.direction == "LONG"
        assert regime.hold_window == "EOD"
        assert regime.source == "transition"

    def test_bear_to_bull_requires_5_consecutive_bear_days(self):
        # Only 4 bear days before the flip — should NOT trigger
        bear_days = [
            _metrics(date(2026, 1, d), eod_wr=0.30)
            for d in range(2, 6)
        ]
        flip_day = _metrics(date(2026, 1, 7), eod_wr=0.72)
        history = bear_days + [flip_day]
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = RegimeEngine(data_dir=tmpdir)
            regime = engine._transition_check(history)
        assert regime is None

    def test_bull_to_bear_flip_detected(self):
        # 3 consecutive days EOD WR < 40%, declining hold curve, avg_loss/avg_win > 0.80
        bear_metrics = _metrics(
            date(2026, 1, 2),
            eod_wr=0.35,
            avg_win=0.8,
            avg_loss=-0.75,
            hold_curve={"+15m": 0.40, "+30m": 0.35, "+1h": 0.30, "+2h": 0.28, "+3h": 0.25, "+5h": 0.22, "EOD": 0.20},
        )
        history = [
            _metrics(date(2026, 1, d), eod_wr=0.35, avg_win=0.8, avg_loss=-0.75,
                     hold_curve={"+15m": 0.40, "+30m": 0.35, "+1h": 0.30, "+2h": 0.28, "+3h": 0.25, "+5h": 0.22, "EOD": 0.20})
            for d in range(2, 5)
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = RegimeEngine(data_dir=tmpdir)
            regime = engine._transition_check(history)
        assert regime is not None
        assert regime.direction == "SHORT"
        assert regime.hold_window == "EOD"
        assert regime.source == "transition"

    def test_bull_to_bear_requires_all_three_conditions(self):
        # 3 days low WR, but avg_loss/avg_win ratio ≤ 0.80 — should NOT trigger
        history = [
            _metrics(date(2026, 1, d), eod_wr=0.35, avg_win=1.0, avg_loss=-0.50,
                     hold_curve={"+15m": 0.40, "+30m": 0.35, "+1h": 0.30, "+2h": 0.28, "+3h": 0.25, "+5h": 0.22, "EOD": 0.20})
            for d in range(2, 5)
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = RegimeEngine(data_dir=tmpdir)
            regime = engine._transition_check(history)
        assert regime is None

    def test_no_transition_with_empty_history(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = RegimeEngine(data_dir=tmpdir)
            assert engine._transition_check([]) is None


class TestGetCurrentRegime:
    def test_uses_seasonal_prior_when_no_history(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = RegimeEngine(data_dir=tmpdir)
            # October with no history — should return seasonal LONG/EOD
            with patch("alpha_tech_tracker.op_momentum_strategy.regime_engine._today_month", return_value=10):
                regime = engine.get_current_regime()
        assert regime.direction == "LONG"
        assert regime.source == "seasonal"

    def test_rolling_check_overrides_seasonal(self):
        # Persistent Bear rolling data overrides October seasonal (LONG)
        history = [
            _metrics(date(2026, 10, d), eod_wr=0.30, hold_curve=_bear_curve())
            for d in range(1, 6)
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = RegimeEngine(data_dir=tmpdir)
            for m in history:
                engine.add_daily_result(m)
            with patch("alpha_tech_tracker.op_momentum_strategy.regime_engine._today_month", return_value=10):
                regime = engine.get_current_regime()
        assert regime.direction == "SHORT"
        assert regime.source == "rolling_confirmed"

    def test_transition_check_overrides_rolling(self):
        # Rolling check would say Rising Bull but transition check fires bear→bull flip
        # Build 6 bear days then a flip day in an otherwise rolling-neutral context
        bear_days = [
            _metrics(date(2026, 9, d), eod_wr=0.30, hold_curve=_bear_curve())
            for d in range(1, 7)
        ]
        flip_day = _metrics(date(2026, 9, 7), eod_wr=0.75)
        history = bear_days + [flip_day]
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = RegimeEngine(data_dir=tmpdir)
            for m in history:
                engine.add_daily_result(m)
            with patch("alpha_tech_tracker.op_momentum_strategy.regime_engine._today_month", return_value=9):
                regime = engine.get_current_regime()
        assert regime.direction == "LONG"
        assert regime.source == "transition"

    def test_neutral_passes_both_directions_unchanged(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = RegimeEngine(data_dir=tmpdir)
            with patch("alpha_tech_tracker.op_momentum_strategy.regime_engine._today_month", return_value=6):
                regime = engine.get_current_regime()
        assert regime.direction == "NEUTRAL"

    def test_no_position_march_day_1_through_3(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = RegimeEngine(data_dir=tmpdir)
            with patch("alpha_tech_tracker.op_momentum_strategy.regime_engine._today_month", return_value=3):
                regime = engine.get_current_regime()
        assert regime.direction == "NO_POSITION"


class TestSummaryStr:
    def test_returns_non_empty_string(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = RegimeEngine(data_dir=tmpdir)
            with patch("alpha_tech_tracker.op_momentum_strategy.regime_engine._today_month", return_value=1):
                s = engine.summary_str()
        assert isinstance(s, str)
        assert len(s) > 0

    def test_includes_direction_and_hold_window(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = RegimeEngine(data_dir=tmpdir)
            with patch("alpha_tech_tracker.op_momentum_strategy.regime_engine._today_month", return_value=10):
                s = engine.summary_str()
        assert "LONG" in s
        assert "EOD" in s


class TestJsonPersistence:
    def test_records_split_across_year_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = RegimeEngine(data_dir=tmpdir)
            engine.add_daily_result(_metrics(date(2025, 12, 31)))
            engine.add_daily_result(_metrics(date(2026, 1, 2)))

            assert os.path.exists(os.path.join(tmpdir, "regime_metrics_2025.json"))
            assert os.path.exists(os.path.join(tmpdir, "regime_metrics_2026.json"))

    def test_reload_across_year_boundary(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            engine1 = RegimeEngine(data_dir=tmpdir)
            engine1.add_daily_result(_metrics(date(2025, 12, 31), eod_wr=0.55))
            engine1.add_daily_result(_metrics(date(2026, 1, 2), eod_wr=0.70))

            engine2 = RegimeEngine(data_dir=tmpdir)
            dates = [m.date for m in engine2._history]
            assert date(2025, 12, 31) in dates
            assert date(2026, 1, 2) in dates

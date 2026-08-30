"""
Tests that EOD exits are recorded and displayed at 15:50 (_EOD_DISPLAY_TIME),
not the old hardcoded 16:00 or the bar-cutoff time 15:55.

Covers two surfaces:
  1. trade_engine.run_replay — replay clock is pinned to last_bar_time (15:55)
     without a +5-minute offset when close_all fires.
  2. op_momentum_selector_backtest display functions — EOD exit rows render
     _EOD_DISPLAY_TIME ("15:50") for all exit sites: primary row, reversal subrow, DD row.
"""

import io
from contextlib import redirect_stdout
from datetime import date, datetime
from unittest.mock import MagicMock, Mock, patch

import pytz

from alpha_tech_tracker.op_momentum_strategy.op_momentum_selector_backtest import (
    _EOD_DISPLAY_TIME,
    _print_daily_table,
)
from alpha_tech_tracker.op_momentum_strategy.replay import clear_replay_clock

ET = pytz.timezone("America/New_York")

_REPLAY_DATE = date(2026, 5, 5)
_BAR_PATH = "alpha_tech_tracker.op_momentum_strategy.trade_engine.BarReplayDriver"
_SET_CLOCK_PATH = "alpha_tech_tracker.op_momentum_strategy.trade_engine.set_replay_clock"
_CLEAR_CLOCK_PATH = "alpha_tech_tracker.op_momentum_strategy.trade_engine.clear_replay_clock"
_ENABLE_NOTIF_PATH = "alpha_tech_tracker.op_momentum_strategy.trade_engine.enable_notifications"
_DISABLE_NOTIF_PATH = "alpha_tech_tracker.op_momentum_strategy.trade_engine.disable_notifications"
# run_replay runs the pre-market ticker selectors before the replay driver, which
# fetches bars from Alpaca over the network. These tests only assert on replay-clock
# behaviour, so the selection step is stubbed out — without this the tests make a
# real HTTP call and fail with 401 on any machine without live credentials.
_WINDOW_SELECTORS_PATH = (
    "alpha_tech_tracker.op_momentum_strategy.trade_engine."
    "OpMomentumTradeEngine._run_window_selectors"
)
# The signal engine also warms its MA history from Alpaca on start_replay. Only the
# warmup is stubbed, so start_replay still sets _session_date and applies the regime
# filter as it normally would.
_WARMUP_PATH = (
    "alpha_tech_tracker.op_momentum_strategy.signal_engine."
    "LiveSignalEngine._warmup_from_cache"
)


def _et(h, m, d=_REPLAY_DATE):
    return ET.localize(datetime.combine(d, datetime.strptime(f"{h:02d}:{m:02d}", "%H:%M").time()))


def _make_engine():
    from conftest import _make_alpaca_client
    from alpha_tech_tracker.op_momentum_strategy.trade_engine import OpMomentumTradeEngine

    engine = OpMomentumTradeEngine(
        alpaca_client=_make_alpaca_client(),
        mock_trade_execution=True,
        replay_capital=10_000.0,
    )
    engine._monitor = Mock()
    return engine


# ---------------------------------------------------------------------------
# trade_engine: replay clock is pinned to last_bar_time (15:55), not 16:00
# ---------------------------------------------------------------------------

class TestReplayClockPinnedToEodBar:
    def teardown_method(self, _):
        clear_replay_clock()

    def _run_with_last_bar(self, last_bar_time):
        """Run run_replay with a mocked driver and capture all set_replay_clock calls."""
        engine = _make_engine()
        mock_driver = MagicMock()
        mock_driver.last_bar_time = last_bar_time

        captured = []

        def capture_set_clock(fn):
            captured.append(fn)

        with patch(_BAR_PATH, return_value=mock_driver), \
             patch(_SET_CLOCK_PATH, side_effect=capture_set_clock), \
             patch(_CLEAR_CLOCK_PATH), \
             patch(_ENABLE_NOTIF_PATH), \
             patch(_DISABLE_NOTIF_PATH), \
             patch(_WINDOW_SELECTORS_PATH, return_value=[]), \
             patch(_WARMUP_PATH):
            engine.run_replay(_REPLAY_DATE)

        return captured

    def test_replay_clock_set_to_1555_when_last_bar_is_eod(self):
        eod_bar_time = _et(15, 55)
        captured = self._run_with_last_bar(eod_bar_time)

        # The last set_replay_clock call should pin to 15:55 (the EOD bar)
        eod_clock_fns = [fn for fn in captured if fn() == eod_bar_time]
        assert eod_clock_fns, "set_replay_clock was never called with the 15:55 EOD bar time"

    def test_replay_clock_not_set_to_1600_when_last_bar_is_eod(self):
        eod_bar_time = _et(15, 55)
        eod_plus_5 = _et(16, 0)
        captured = self._run_with_last_bar(eod_bar_time)

        for fn in captured:
            assert fn() != eod_plus_5, "set_replay_clock was called with 16:00 — old +5 min offset still present"

    def test_replay_clock_not_set_to_eod_when_last_bar_is_none(self):
        captured = self._run_with_last_bar(last_bar_time=None)

        # No clock fn should return a time >= 15:55 (the driver had no bars)
        for fn in captured:
            result = fn()
            assert result.hour < 15 or (result.hour == 15 and result.minute < 55), \
                f"set_replay_clock unexpectedly set to EOD time {result} when last_bar_time was None"


# ---------------------------------------------------------------------------
# backtest display: EOD exit renders as _EOD_DISPLAY_TIME ("15:50") in all call sites
# ---------------------------------------------------------------------------

def _base_row(**overrides):
    """Minimal trade row that _print_daily_table can render without KeyError."""
    row = {
        "date": str(_REPLAY_DATE),
        "window": "M1",
        "rank": 1,
        "ticker": "MU",
        "signal": "BEARISH",
        "score": 0.40,
        "entry_price": 640.88,
        "exit_price": 636.17,
        "pnl": 4.71,
        "cap_pnl": 47.1,
        "or_close_min": 570,
        "bars_held": 3,
        "exit_reason": "end_of_day",
        "skipped": False,
    }
    row.update(overrides)
    return row


def _capture(fn, *args, **kwargs) -> str:
    buf = io.StringIO()
    with redirect_stdout(buf):
        fn(*args, **kwargs)
    return buf.getvalue()


class TestBacktestPrimaryRowEodTime:
    def test_eod_primary_row_shows_eod_display_time(self):
        row = _base_row(exit_reason="end_of_day")
        output = _capture(_print_daily_table, [row], n=1)
        assert "16:00" not in output
        assert _EOD_DISPLAY_TIME in output

    def test_bullish_eod_primary_row_shows_eod_display_time(self):
        row = _base_row(signal="BULLISH", pnl=-4.71, exit_reason="end_of_day")
        output = _capture(_print_daily_table, [row], n=1)
        assert "16:00" not in output
        assert _EOD_DISPLAY_TIME in output

    def test_non_eod_primary_row_does_not_show_eod_display_time(self):
        # bars_held=3, or_close_min=570: exit = 570 + (3+1)*5 = 590 = 09:50
        row = _base_row(exit_reason="trailing_stop_ma20", bars_held=3, or_close_min=570)
        output = _capture(_print_daily_table, [row], n=1)
        assert _EOD_DISPLAY_TIME not in output


class TestBacktestReentrySubrowEodTime:
    def test_reversal_subrow_eod_exit_shows_eod_display_time(self):
        row = _base_row(
            exit_reason="end_of_day",
            rev_entry_price=636.17,
            rev_pnl=4.71,
            rev_exit_price=640.88,
            rev_exit_reason="end_of_day",
            rev_entry_idx=1,
            rev_bars_held=2,
            rev_cancelled_by_dd=False,
        )
        output = _capture(_print_daily_table, [row], n=1)
        assert "16:00" not in output
        assert _EOD_DISPLAY_TIME in output

    def test_reversal_subrow_non_eod_exit_does_not_show_eod_display_time(self):
        row = _base_row(
            exit_reason="trailing_stop_ma20",
            rev_entry_price=636.17,
            rev_pnl=4.71,
            rev_exit_price=640.88,
            rev_exit_reason="trailing_stop_ma20",
            rev_entry_idx=1,
            rev_bars_held=2,
            rev_cancelled_by_dd=False,
        )
        output = _capture(_print_daily_table, [row], n=1)
        assert "16:00" not in output


class TestBacktestDoubledownEodTime:
    def test_dd_eod_exit_shows_eod_display_time(self):
        row = _base_row(
            exit_reason="end_of_day",
            dd_addon_cap_pnl=9.42,
            dd_freed_capital=1000.0,
            dd_addon_entry=636.17,
            dd_addon_effective_exit=640.88,
            dd_fire_min=585,
            dd_freed_ranks=[2],
        )
        output = _capture(_print_daily_table, [row], n=1)
        assert "16:00" not in output
        assert _EOD_DISPLAY_TIME in output

    def test_dd_non_eod_exit_does_not_show_eod_display_time(self):
        row = _base_row(
            exit_reason="trailing_stop_ma20",
            dd_addon_cap_pnl=9.42,
            dd_freed_capital=1000.0,
            dd_addon_entry=636.17,
            dd_addon_effective_exit=640.88,
            dd_fire_min=585,
            dd_freed_ranks=[2],
        )
        output = _capture(_print_daily_table, [row], n=1)
        assert "16:00" not in output

from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
import pytz

from alpha_tech_tracker.op_momentum_strategy.op_momentum_backtest import (
    _CACHE_WARMUP_DAYS,
    _evict_contained_cache_pieces,
    _partial_stitch_cache,
    _save_cache,
    _stitch_cache,
    _trim_bars_to_range,
    compute_signals_with_backtest,
    fetch_bars,
)
from alpha_tech_tracker.op_momentum_strategy.op_momentum_selector_backtest import (
    _apply_capital_flow,
)

_M = "alpha_tech_tracker.op_momentum_strategy.op_momentum_backtest"


ET = pytz.timezone("America/New_York")

_W1 = {"label": "W1", "opening_start": "09:30", "opening_bars": 3}
_WEIGHTS = [0.5, 0.3, 0.2]
_D1 = date(2025, 1, 2)

# MA values chosen so that MA-based trailing stops never fire in primary/re-entry trades.
# BEARISH: MA20 must be > or_low for trailing to fire; using 102 (above or_high) disables it.
# BULLISH: MA20 must be > hard_stop_price for trailing to fire; using 98 (below hard_stop) disables it.
_BEAR_MA20 = 102.0
_BEAR_MA50 = 102.0
_BULL_MA20 = 98.0
_BULL_MA50 = 98.0
_MA200 = 95.0


def _make_bars(date_str, bar_specs):
    """
    bar_specs: list of (time_str, open, high, low, close, ma20, ma50, ma200)
    Returns a DataFrame with ET-localized timestamps as index.
    """
    index = [
        ET.localize(datetime.strptime(f"{date_str} {t}", "%Y-%m-%d %H:%M"))
        for t, *_ in bar_specs
    ]
    rows = [
        {"Open": o, "High": h, "Low": l, "Close": c, "MA20": m20, "MA50": m50, "MA200": m200}
        for _, o, h, l, c, m20, m50, m200 in bar_specs
    ]
    return pd.DataFrame(rows, index=pd.DatetimeIndex(index))


# ---------------------------------------------------------------------------
# Shared bar sequences
# ---------------------------------------------------------------------------
#
# OR: or_high=102, or_low=98, or_range=4, midpoint=100
# stop_pct=0.40 (function default): bear_hard_stop=99.6, bear_fallback=98.8
# Signal bar close=98.5 ≤ bottom_30_threshold=98.8 → BEARISH

_BEARISH_OPENING = [
    ("09:30", 100, 101,  99,  100.0, _BEAR_MA20, _BEAR_MA50, _MA200),
    ("09:35", 100, 102,  98,  100.0, _BEAR_MA20, _BEAR_MA50, _MA200),
    ("09:40",  99, 100,  98,   98.5, _BEAR_MA20, _BEAR_MA50, _MA200),  # signal bar
]

# Post-open bars producing hard_stop exit at bar 1 (bars_held=1, exit_bar_idx=1)
_BEARISH_POST_HARDSTOP = [
    ("09:45",  99,  99.5, 98.5,  99.0, _BEAR_MA20, _BEAR_MA50, _MA200),  # arm
    ("09:50", 100, 100.0, 99.5,  99.7, _BEAR_MA20, _BEAR_MA50, _MA200),  # hard_stop hit
]

# OR: or_high=102, or_low=98, or_range=4, midpoint=100
# stop_pct=0.40: bull_hard_stop=100.4, bull_fallback=101.2
# Signal bar close=101.5 > midpoint=100 → BULLISH

_BULLISH_OPENING = [
    ("09:30", 100, 101,  99,  100.0, _BULL_MA20, _BULL_MA50, _MA200),
    ("09:35", 100, 102,  98,  100.0, _BULL_MA20, _BULL_MA50, _MA200),
    ("09:40", 101, 102,  99,  101.5, _BULL_MA20, _BULL_MA50, _MA200),  # signal bar
]

# Post-open bars producing hard_stop exit at bar 1 (bars_held=1, exit_bar_idx=1)
_BULLISH_POST_HARDSTOP = [
    ("09:45", 102, 102, 101,  101.8, _BULL_MA20, _BULL_MA50, _MA200),  # arm
    ("09:50", 100, 101, 100,  100.3, _BULL_MA20, _BULL_MA50, _MA200),  # hard_stop hit
]


# ---------------------------------------------------------------------------
# TestComputeSignalsBearishReentry
# ---------------------------------------------------------------------------


class TestComputeSignalsBearishReentry:
    def test_bre_fires_when_price_drops_below_or_low(self):
        # BRE scan bar at 09:55 closes below or_low=98, triggering re-entry at 97.5.
        # Remaining bar holds to EOD at 96.0 → br_pnl = 97.5 - 96.0 = 1.5 (profit).
        df = _make_bars("2025-01-02", _BEARISH_OPENING + _BEARISH_POST_HARDSTOP + [
            ("09:55",  97,  98,  96.5,  97.5, _BEAR_MA20, _BEAR_MA50, _MA200),
            ("10:00",  96,  97,  95.5,  96.0, _BEAR_MA20, _BEAR_MA50, _MA200),
        ])
        result = compute_signals_with_backtest(
            df, opening_bars=3, enable_bearish_reentry=True
        )

        assert len(result) == 2
        primary = result[result["is_bearish_reentry"] == False].iloc[0]
        reentry = result[result["is_bearish_reentry"] == True].iloc[0]
        assert primary["exit_reason"] == "hard_stop"
        assert reentry["entry_price"] == pytest.approx(97.5)
        assert reentry["pnl"] == pytest.approx(1.5)
        assert reentry["exit_reason"] == "end_of_day"

    def test_bre_does_not_fire_when_disabled(self):
        df = _make_bars("2025-01-02", _BEARISH_OPENING + _BEARISH_POST_HARDSTOP + [
            ("09:55",  97,  98,  96.5,  97.5, _BEAR_MA20, _BEAR_MA50, _MA200),
            ("10:00",  96,  97,  95.5,  96.0, _BEAR_MA20, _BEAR_MA50, _MA200),
        ])
        result = compute_signals_with_backtest(
            df, opening_bars=3, enable_bearish_reentry=False
        )

        assert len(result) == 1
        assert result.iloc[0]["is_bearish_reentry"] == False

    def test_bre_does_not_fire_when_price_never_drops_below_or_low(self):
        # Post-BRE-scan bars stay above or_low=98 → no BRE trigger.
        df = _make_bars("2025-01-02", _BEARISH_OPENING + _BEARISH_POST_HARDSTOP + [
            ("09:55",  98.5, 99, 98, 98.5, _BEAR_MA20, _BEAR_MA50, _MA200),
            ("10:00",  98.5, 99, 98, 98.5, _BEAR_MA20, _BEAR_MA50, _MA200),
        ])
        result = compute_signals_with_backtest(
            df, opening_bars=3, enable_bearish_reentry=True
        )

        assert len(result) == 1
        assert result.iloc[0]["is_bearish_reentry"] == False

    def test_bre_does_not_fire_when_primary_held_too_many_bars(self):
        # bearish_reentry_max_bars=0 means bars_held=1 > 0 → ineligible.
        df = _make_bars("2025-01-02", _BEARISH_OPENING + _BEARISH_POST_HARDSTOP + [
            ("09:55",  97, 98, 96.5, 97.5, _BEAR_MA20, _BEAR_MA50, _MA200),
            ("10:00",  96, 97, 95.5, 96.0, _BEAR_MA20, _BEAR_MA50, _MA200),
        ])
        result = compute_signals_with_backtest(
            df, opening_bars=3, enable_bearish_reentry=True, bearish_reentry_max_bars=0
        )

        assert len(result) == 1

    def test_bre_blocked_when_reversal_fires_first(self):
        # After BEARISH primary stops out, price closes above or_high=102 → reversal fires.
        # Reversal claims rev_entry_price, blocking BRE mutual exclusion guard.
        df = _make_bars("2025-01-02", _BEARISH_OPENING + _BEARISH_POST_HARDSTOP + [
            ("09:55", 103, 104, 102, 103.5, _BEAR_MA20, _BEAR_MA50, _MA200),  # reversal trigger
            ("10:00", 103, 104, 102, 103.0, _BEAR_MA20, _BEAR_MA50, _MA200),
        ])
        result = compute_signals_with_backtest(
            df, opening_bars=3,
            enable_reversal=True,
            enable_bearish_reentry=True,
        )

        assert any(result["is_reversal"])
        assert not any(result["is_bearish_reentry"])

    def test_bre_hard_stop_exits_at_midpoint(self):
        # BRE entry at 97.5; next bar closes at 100.5 (>= midpoint=100) → hard_stop at 100.
        df = _make_bars("2025-01-02", _BEARISH_OPENING + _BEARISH_POST_HARDSTOP + [
            ("09:55",  97,  98,  96.5,  97.5, _BEAR_MA20, _BEAR_MA50, _MA200),
            ("10:00", 100, 101,  99.5, 100.5, _BEAR_MA20, _BEAR_MA50, _MA200),
        ])
        result = compute_signals_with_backtest(
            df, opening_bars=3, enable_bearish_reentry=True
        )

        reentry = result[result["is_bearish_reentry"] == True].iloc[0]
        assert reentry["exit_reason"] == "hard_stop"
        assert reentry["exit_price"] == pytest.approx(100.0)  # midpoint
        assert reentry["pnl"] < 0

    def test_bre_trailing_armed_and_exits_via_ma20_when_ma20_below_midpoint(self):
        # OR: high=102, low=98, midpoint=100.
        # BRE entry at 97.0 (close < or_low=98).
        # MA20=99.5 < midpoint=100 → arm fires immediately on the first remaining bar.
        # Second bar: close=99.8 > MA20=99.5 → trailing_stop_ma20 exit.
        # MA20=102 (_BEAR_MA20) is used only for the primary trade bars to suppress primary trailing.
        _ma20_below_mid = 99.5
        df = _make_bars("2025-01-02", _BEARISH_OPENING + _BEARISH_POST_HARDSTOP + [
            ("09:55",  97.0, 98.0, 96.5,  97.0, _BEAR_MA20,      _BEAR_MA50, _MA200),  # BRE entry
            ("10:00",  97.5, 98.5, 97.0,  97.5, _ma20_below_mid, _BEAR_MA50, _MA200),  # arm; close < MA20
            ("10:05",  99.5, 100,  98.5,  99.8, _ma20_below_mid, _BEAR_MA50, _MA200),  # close > MA20 → exit
        ])
        result = compute_signals_with_backtest(
            df, opening_bars=3, enable_bearish_reentry=True
        )

        reentry = result[result["is_bearish_reentry"] == True].iloc[0]
        assert reentry["exit_reason"] == "trailing_stop_ma20"
        assert reentry["exit_price"] == pytest.approx(99.8)
        assert reentry["entry_price"] == pytest.approx(97.0)

    def test_bre_holds_to_eod_when_ma20_above_midpoint(self):
        # MA20=102 > midpoint=100 throughout BRE bars → trailing never arms → EOD exit.
        df = _make_bars("2025-01-02", _BEARISH_OPENING + _BEARISH_POST_HARDSTOP + [
            ("09:55",  97.0, 98.0, 96.5,  97.0, _BEAR_MA20, _BEAR_MA50, _MA200),  # BRE entry
            ("10:00",  97.5, 98.5, 97.0,  97.5, _BEAR_MA20, _BEAR_MA50, _MA200),
            ("10:05",  97.0, 97.5, 96.5,  96.0, _BEAR_MA20, _BEAR_MA50, _MA200),
        ])
        result = compute_signals_with_backtest(
            df, opening_bars=3, enable_bearish_reentry=True
        )

        reentry = result[result["is_bearish_reentry"] == True].iloc[0]
        assert reentry["exit_reason"] == "end_of_day"
        assert reentry["exit_price"] == pytest.approx(96.0)
        assert reentry["pnl"] == pytest.approx(97.0 - 96.0)

    def test_bre_trailing_arm_latches_once_set(self):
        # MA20 drops below midpoint on bar 1 (arm latches), rises back above on bar 2,
        # drops below again on bar 3.  Bar 4 has close > MA20 → trailing fires because
        # arm is already latched from bar 1, not re-evaluated each bar.
        _ma20_below_mid = 99.5
        _ma20_above_mid = 100.5
        df = _make_bars("2025-01-02", _BEARISH_OPENING + _BEARISH_POST_HARDSTOP + [
            ("09:55",  97.0, 98.0, 96.5,  97.0, _BEAR_MA20,      _BEAR_MA50, _MA200),  # BRE entry
            ("10:00",  97.5, 98.0, 97.0,  97.5, _ma20_below_mid, _BEAR_MA50, _MA200),  # arm latches
            ("10:05",  97.5, 98.5, 97.0,  98.0, _ma20_above_mid, _BEAR_MA50, _MA200),  # MA20>mid; arm still held
            ("10:10",  98.5, 99.5, 98.0,  98.5, _ma20_below_mid, _BEAR_MA50, _MA200),  # close < MA20; no exit
            ("10:15",  99.5, 100,  98.5,  99.8, _ma20_below_mid, _BEAR_MA50, _MA200),  # close > MA20 → exit
        ])
        result = compute_signals_with_backtest(
            df, opening_bars=3, enable_bearish_reentry=True
        )

        reentry = result[result["is_bearish_reentry"] == True].iloc[0]
        assert reentry["exit_reason"] == "trailing_stop_ma20"
        assert reentry["exit_price"] == pytest.approx(99.8)


# ---------------------------------------------------------------------------
# TestComputeSignalsBullishReentry
# ---------------------------------------------------------------------------


class TestComputeSignalsBullishReentry:
    def test_bru_fires_when_price_rises_above_or_high(self):
        # BRU scan bar at 09:55 closes above or_high=102, triggering re-entry at 102.5.
        # Remaining bar holds to EOD at 103.0 → bru_pnl = 103.0 - 102.5 = 0.5 (profit).
        df = _make_bars("2025-01-02", _BULLISH_OPENING + _BULLISH_POST_HARDSTOP + [
            ("09:55", 103, 103, 102, 102.5, _BULL_MA20, _BULL_MA50, _MA200),
            ("10:00", 103, 104, 102, 103.0, _BULL_MA20, _BULL_MA50, _MA200),
        ])
        result = compute_signals_with_backtest(
            df, opening_bars=3, enable_bullish_reentry=True
        )

        assert len(result) == 2
        primary = result[result["is_bullish_reentry"] == False].iloc[0]
        reentry = result[result["is_bullish_reentry"] == True].iloc[0]
        assert primary["exit_reason"] == "hard_stop"
        assert reentry["entry_price"] == pytest.approx(102.5)
        assert reentry["pnl"] == pytest.approx(0.5)
        assert reentry["exit_reason"] == "end_of_day"

    def test_bru_does_not_fire_when_disabled(self):
        df = _make_bars("2025-01-02", _BULLISH_OPENING + _BULLISH_POST_HARDSTOP + [
            ("09:55", 103, 103, 102, 102.5, _BULL_MA20, _BULL_MA50, _MA200),
            ("10:00", 103, 104, 102, 103.0, _BULL_MA20, _BULL_MA50, _MA200),
        ])
        result = compute_signals_with_backtest(
            df, opening_bars=3, enable_bullish_reentry=False
        )

        assert len(result) == 1
        assert result.iloc[0]["is_bullish_reentry"] == False

    def test_bru_does_not_fire_when_price_never_rises_above_or_high(self):
        # Post-BRU-scan bars stay below or_high=102 → no BRU trigger.
        df = _make_bars("2025-01-02", _BULLISH_OPENING + _BULLISH_POST_HARDSTOP + [
            ("09:55", 101, 101.5, 100, 101.0, _BULL_MA20, _BULL_MA50, _MA200),
            ("10:00", 101, 101.5, 100, 101.0, _BULL_MA20, _BULL_MA50, _MA200),
        ])
        result = compute_signals_with_backtest(
            df, opening_bars=3, enable_bullish_reentry=True
        )

        assert len(result) == 1
        assert result.iloc[0]["is_bullish_reentry"] == False

    def test_bru_does_not_fire_when_primary_held_too_many_bars(self):
        # bullish_reentry_max_bars=0 means bars_held=1 > 0 → ineligible.
        df = _make_bars("2025-01-02", _BULLISH_OPENING + _BULLISH_POST_HARDSTOP + [
            ("09:55", 103, 103, 102, 102.5, _BULL_MA20, _BULL_MA50, _MA200),
            ("10:00", 103, 104, 102, 103.0, _BULL_MA20, _BULL_MA50, _MA200),
        ])
        result = compute_signals_with_backtest(
            df, opening_bars=3, enable_bullish_reentry=True, bullish_reentry_max_bars=0
        )

        assert len(result) == 1

    def test_bru_hard_stop_exits_at_midpoint(self):
        # BRU entry at 102.5; next bar closes at 99.5 (<= midpoint=100) → hard_stop at 100.
        df = _make_bars("2025-01-02", _BULLISH_OPENING + _BULLISH_POST_HARDSTOP + [
            ("09:55", 103, 103, 102, 102.5, _BULL_MA20, _BULL_MA50, _MA200),
            ("10:00",  99, 100,  99,  99.5, _BULL_MA20, _BULL_MA50, _MA200),
        ])
        result = compute_signals_with_backtest(
            df, opening_bars=3, enable_bullish_reentry=True
        )

        reentry = result[result["is_bullish_reentry"] == True].iloc[0]
        assert reentry["exit_reason"] == "hard_stop"
        assert reentry["exit_price"] == pytest.approx(100.0)  # midpoint
        assert reentry["pnl"] < 0

    def test_bru_trailing_armed_and_exits_via_ma20_when_price_reaches_0_1x_threshold(self):
        # BRU entry at 102.5; effective_or_range=4; arm threshold = 102.5 + 4*0.1 = 102.9.
        # Bar 1: close=103.0 >= 102.9 → arm latches; MA20=101.0 > hard_stop=100.
        # Bar 2: close=100.5 < MA20=101.0 → trailing_stop_ma20 exit at 100.5.
        _bru_ma20_above_mid = 101.0
        df = _make_bars("2025-01-02", _BULLISH_OPENING + _BULLISH_POST_HARDSTOP + [
            ("09:55", 103, 103, 102, 102.5, _BULL_MA20,          _BULL_MA50, _MA200),
            ("10:00", 103, 104, 102, 103.0, _bru_ma20_above_mid, _BULL_MA50, _MA200),
            ("10:05", 101, 102, 100, 100.5, _bru_ma20_above_mid, _BULL_MA50, _MA200),
        ])
        result = compute_signals_with_backtest(
            df, opening_bars=3, enable_bullish_reentry=True
        )

        reentry = result[result["is_bullish_reentry"] == True].iloc[0]
        assert reentry["entry_price"] == pytest.approx(102.5)
        assert reentry["exit_reason"] == "trailing_stop_ma20"
        assert reentry["exit_price"] == pytest.approx(100.5)

    def test_bru_trailing_arm_does_not_fire_when_price_stays_below_0_1x_threshold(self):
        # BRU entry at 102.5; arm threshold=102.9; post-entry close stays at 102.7 → no arm.
        # MA20=101.0 would trigger trailing if armed, but since arm never latches, EOD exit.
        _bru_ma20_above_mid = 101.0
        df = _make_bars("2025-01-02", _BULLISH_OPENING + _BULLISH_POST_HARDSTOP + [
            ("09:55", 103, 103, 102, 102.5, _BULL_MA20,          _BULL_MA50, _MA200),
            ("10:00", 103, 103, 102, 102.7, _bru_ma20_above_mid, _BULL_MA50, _MA200),
            ("10:05", 101, 102, 100, 100.5, _bru_ma20_above_mid, _BULL_MA50, _MA200),
        ])
        result = compute_signals_with_backtest(
            df, opening_bars=3, enable_bullish_reentry=True
        )

        reentry = result[result["is_bullish_reentry"] == True].iloc[0]
        assert reentry["exit_reason"] == "end_of_day"
        assert reentry["exit_price"] == pytest.approx(100.5)

    def test_bru_trailing_arm_latches_once_set(self):
        # Bar 1 post-entry: close=103.2 → arm latches (103.2 >= 102.9).
        # Bar 2: close drops to 102.5 (below 102.9); arm remains held.
        # Bar 3: close=100.5 < MA20=101.0 → trailing fires because arm is still set.
        _bru_ma20_above_mid = 101.0
        df = _make_bars("2025-01-02", _BULLISH_OPENING + _BULLISH_POST_HARDSTOP + [
            ("09:55", 103,   104,   102,   102.5, _BULL_MA20,          _BULL_MA50, _MA200),
            ("10:00", 104,   105,   103,   103.2, _bru_ma20_above_mid, _BULL_MA50, _MA200),
            ("10:05", 102,   103,   102,   102.5, _bru_ma20_above_mid, _BULL_MA50, _MA200),
            ("10:10", 100.5, 102,   100,   100.5, _bru_ma20_above_mid, _BULL_MA50, _MA200),
        ])
        result = compute_signals_with_backtest(
            df, opening_bars=3, enable_bullish_reentry=True
        )

        reentry = result[result["is_bullish_reentry"] == True].iloc[0]
        assert reentry["exit_reason"] == "trailing_stop_ma20"
        assert reentry["exit_price"] == pytest.approx(100.5)


# ---------------------------------------------------------------------------
# TestOrBarLookbackEffectiveOrRange
# ---------------------------------------------------------------------------
#
# OR: or_high=100, or_low=99, or_range=1, midpoint=99.5
# Pre-opening bars: range=10 each → avg_recent_bar_range=10
# or_range=1 < avg/4=2.5 → effective_or_range substituted with 10 when lookback enabled.
#
# Without lookback (effective=1):
#   bear_hard_stop = 99 + 0.40*1 = 99.4
#   Post-open close=99.0 arms (99.0 < 99.4), then close=99.5 hits hard_stop (99.5 >= 99.4).
# With lookback=3 (effective=10):
#   bear_hard_stop = 99 + 0.40*10 = 103.0
#   Post-open close=99.0 arms (99.0 < 103), close=99.5 does not hit hard_stop (99.5 < 103).
#   Trade holds to EOD.

_NARROW_OR_OPENING = [
    ("09:30", 99.8, 100.0, 99.5, 99.8, 101.0, 101.0, _MA200),
    ("09:35", 99.5,  99.8, 99.0, 99.4, 101.0, 101.0, _MA200),
    ("09:40", 99.2,  99.5, 99.0, 99.1, 101.0, 101.0, _MA200),  # close=99.1 ≤ threshold=99.2 → BEARISH
]

_NARROW_OR_PRE_OPEN = [
    ("09:15", 105, 110, 100, 105, 101.0, 101.0, _MA200),  # range=10
    ("09:20", 105, 110, 100, 105, 101.0, 101.0, _MA200),  # range=10
    ("09:25", 105, 110, 100, 105, 101.0, 101.0, _MA200),  # range=10
]


class TestTrailingMaSwitchPeriod:
    """Configurable fast-MA period for the trailing-stop upgrade.

    Setup (shared across tests):
      OR: high=102 low=98 range=4 midpoint=100 → bull_hard_stop=100.4 (stop_pct=0.4)
      Bar 1 (09:45): close=102.5 — arms hard stop, move=2.5 (< or_range)
      Bar 2 (09:50): close=104.5, fast_MA=103.0 — move=4.5 ≥ or_range → use_ma_fast latches
      Bar 3 (09:55): close=102.0, fast_MA=103.5 — close<fast_MA → trailing exit
    MA20 is pinned below hard_stop so MA20 never triggers trailing on its own.
    """

    _BULL_OPENING = _BULLISH_OPENING

    _BULL_POST_FAST_TRAIL = [
        ("09:45", 102, 103,  101.5,  102.5, _BULL_MA20, _BULL_MA50, _MA200),
        ("09:50", 103, 105,  102.5,  104.5, _BULL_MA20, _BULL_MA50, _MA200),
        ("09:55", 104, 104,  101.5,  102.0, _BULL_MA20, _BULL_MA50, _MA200),
    ]

    def _make_df_with_fast_ma(self, period, fast_ma_values):
        df = _make_bars("2025-01-02", self._BULL_OPENING + self._BULL_POST_FAST_TRAIL)
        df[f"MA{period}"] = fast_ma_values
        return df

    def test_default_period_8_uses_ma8_in_exit_reason(self):
        df = self._make_df_with_fast_ma(8, [100.0, 100.0, 100.0, 99.0, 103.0, 103.5])
        result = compute_signals_with_backtest(
            df, opening_bars=3, trailing_ma_switch="after-arm",
        )
        assert len(result) == 1
        assert result.iloc[0]["exit_reason"] == "trailing_stop_ma8"

    def test_period_5_uses_ma5_in_exit_reason(self):
        df = self._make_df_with_fast_ma(5, [100.0, 100.0, 100.0, 99.0, 103.0, 103.5])
        result = compute_signals_with_backtest(
            df, opening_bars=3,
            trailing_ma_switch="after-arm", trailing_ma_switch_period=5,
        )
        assert len(result) == 1
        assert result.iloc[0]["exit_reason"] == "trailing_stop_ma5"

    def test_period_10_uses_ma10_in_exit_reason(self):
        df = self._make_df_with_fast_ma(10, [100.0, 100.0, 100.0, 99.0, 103.0, 103.5])
        result = compute_signals_with_backtest(
            df, opening_bars=3,
            trailing_ma_switch="after-arm", trailing_ma_switch_period=10,
        )
        assert len(result) == 1
        assert result.iloc[0]["exit_reason"] == "trailing_stop_ma10"

    def test_switch_none_ignores_period_and_does_not_use_fast_ma(self):
        # MA5 set high enough to fire if used. With switch="none" the fast MA
        # must never replace MA20, and MA20 (=98) is below hard_stop so no
        # trailing fires at all → trade rides to end_of_day.
        df = self._make_df_with_fast_ma(5, [100.0, 100.0, 100.0, 99.0, 103.0, 103.5])
        result = compute_signals_with_backtest(
            df, opening_bars=3,
            trailing_ma_switch="none", trailing_ma_switch_period=5,
        )
        assert len(result) == 1
        assert result.iloc[0]["exit_reason"] != "trailing_stop_ma5"
        assert result.iloc[0]["exit_reason"] != "trailing_stop_ma20"

    def test_fast_ma_column_computed_when_not_provided(self):
        # No MA5 column supplied — function must compute it via rolling mean
        # without raising. With only 6 bars and a rolling(5) window, the last
        # bar's MA5 is non-NaN and exit reason should reference ma5.
        df = _make_bars("2025-01-02", self._BULL_OPENING + self._BULL_POST_FAST_TRAIL)
        assert "MA5" not in df.columns
        result = compute_signals_with_backtest(
            df, opening_bars=3,
            trailing_ma_switch="after-arm", trailing_ma_switch_period=5,
        )
        assert len(result) == 1


class TestOrBarLookbackEffectiveOrRange:
    def test_narrow_or_range_changes_hard_stop_when_lookback_enabled(self):
        df = _make_bars("2025-01-02", _NARROW_OR_PRE_OPEN + _NARROW_OR_OPENING + [
            ("09:45",  99, 99.5, 98.5,  99.0, 101.0, 101.0, _MA200),
            ("09:50",  99, 99.8, 99.0,  99.5, 101.0, 101.0, _MA200),
        ])
        result = compute_signals_with_backtest(
            df, opening_bars=3, or_bar_lookback=3
        )

        # With effective_or_range=10, bear_hard_stop=103 — close=99.5 doesn't hit it.
        assert len(result) == 1
        assert result.iloc[0]["exit_reason"] == "end_of_day"

    def test_narrow_or_range_not_substituted_when_lookback_disabled(self):
        df = _make_bars("2025-01-02", _NARROW_OR_PRE_OPEN + _NARROW_OR_OPENING + [
            ("09:45",  99, 99.5, 98.5,  99.0, 101.0, 101.0, _MA200),
            ("09:50",  99, 99.8, 99.0,  99.5, 101.0, 101.0, _MA200),
        ])
        result = compute_signals_with_backtest(
            df, opening_bars=3, or_bar_lookback=0
        )

        # Without substitution, bear_hard_stop=99.4 — close=99.5 hits it.
        assert len(result) == 1
        assert result.iloc[0]["exit_reason"] == "hard_stop"


# ---------------------------------------------------------------------------
# TestApplyCapitalFlowWithReentry
# ---------------------------------------------------------------------------
#
# slot_capital for rank-1 = 10000 * 0.5 = 5000.
# BRE cap = slot_capital / br_entry_price * br_pnl.
# BRU cap = slot_capital / bru_entry_price * bru_pnl.


def _reentry_row(window, rank, entry, pnl, br_entry=0.0, br_pnl=0.0, bru_entry=0.0, bru_pnl=0.0, d=_D1):
    return {
        "date": d,
        "window": window,
        "rank": rank,
        "entry_price": entry,
        "pnl": pnl,
        "br_entry_price": br_entry,
        "br_pnl": br_pnl,
        "bru_entry_price": bru_entry,
        "bru_pnl": bru_pnl,
    }


class TestApplyCapitalFlowWithReentry:
    def test_bre_pnl_added_to_cap_pnl(self):
        # Primary pnl=0, BRE: entry=100, pnl=2 → cap += 5000/100*2 = 100
        rows = [_reentry_row("W1", 1, 100.0, 0.0, br_entry=100.0, br_pnl=2.0)]
        _apply_capital_flow(rows, [_W1], 10_000, _WEIGHTS, 3)

        assert rows[0]["cap_pnl"] == pytest.approx(100.0)

    def test_bru_pnl_added_to_cap_pnl(self):
        # Primary pnl=0, BRU: entry=100, pnl=1 → cap += 5000/100*1 = 50
        rows = [_reentry_row("W1", 1, 100.0, 0.0, bru_entry=100.0, bru_pnl=1.0)]
        _apply_capital_flow(rows, [_W1], 10_000, _WEIGHTS, 3)

        assert rows[0]["cap_pnl"] == pytest.approx(50.0)

    def test_bre_and_bru_both_contribute_to_cap_pnl(self):
        # Primary pnl=0, BRE: entry=100, pnl=2 (+100), BRU: entry=100, pnl=1 (+50)
        rows = [_reentry_row("W1", 1, 100.0, 0.0, br_entry=100.0, br_pnl=2.0, bru_entry=100.0, bru_pnl=1.0)]
        _apply_capital_flow(rows, [_W1], 10_000, _WEIGHTS, 3)

        assert rows[0]["cap_pnl"] == pytest.approx(150.0)

    def test_bre_missing_entry_price_does_not_add_cap_pnl(self):
        # br_entry_price=0 (falsy) → no BRE contribution
        rows = [_reentry_row("W1", 1, 100.0, 0.0, br_entry=0.0, br_pnl=5.0)]
        _apply_capital_flow(rows, [_W1], 10_000, _WEIGHTS, 3)

        assert rows[0]["cap_pnl"] == pytest.approx(0.0)

    def test_bre_pnl_uses_same_slot_capital_as_primary(self):
        # rank-2 slot_capital = 10000 * 0.3 = 3000
        # BRE cap = 3000 / 100 * 2 = 60
        rows = [_reentry_row("W1", 2, 100.0, 0.0, br_entry=100.0, br_pnl=2.0)]
        _apply_capital_flow(rows, [_W1], 10_000, _WEIGHTS, 3)

        assert rows[0]["cap_pnl"] == pytest.approx(60.0)


# ---------------------------------------------------------------------------
# Helpers for cache-trimming tests
# ---------------------------------------------------------------------------


def _make_date_bars(date_strs):
    """One 09:30 bar per date — minimal fixture for cache-trim tests."""
    index = [
        ET.localize(datetime.strptime(f"{d} 09:30", "%Y-%m-%d %H:%M"))
        for d in date_strs
    ]
    rows = [
        {"Open": 100.0, "High": 101.0, "Low": 99.0, "Close": 100.0, "Volume": 1000}
        for _ in date_strs
    ]
    return pd.DataFrame(rows, index=pd.DatetimeIndex(index))


def _make_intraday_bars(date_str, times):
    """One bar per (date, time) pair — for testing intraday time filtering."""
    index = [
        ET.localize(datetime.strptime(f"{date_str} {t}", "%Y-%m-%d %H:%M"))
        for t in times
    ]
    rows = [
        {"Open": 100.0, "High": 101.0, "Low": 99.0, "Close": 100.0, "Volume": 1000}
        for _ in times
    ]
    return pd.DataFrame(rows, index=pd.DatetimeIndex(index))


def _read_cache_file(path):
    df = pd.read_json(path, orient="split")
    df.index = pd.to_datetime(df.index, utc=True).tz_convert("America/New_York")
    return df


# ---------------------------------------------------------------------------
# TestTrimBarsToRange
# ---------------------------------------------------------------------------


class TestTrimBarsToRange:
    _START = date(2026, 3, 1)
    _END = date(2026, 3, 31)

    def test_removes_data_older_than_warmup_buffer(self):
        too_old = self._START - timedelta(days=_CACHE_WARMUP_DAYS + 1)
        df = _make_date_bars([str(too_old), str(self._START), str(self._END)])

        result = _trim_bars_to_range(df, self._START, self._END)

        assert too_old not in set(result.index.date)
        assert self._START in set(result.index.date)

    def test_keeps_data_within_warmup_buffer(self):
        warmup_day = self._START - timedelta(days=_CACHE_WARMUP_DAYS)
        df = _make_date_bars([str(warmup_day), str(self._START)])

        result = _trim_bars_to_range(df, self._START, self._END)

        assert warmup_day in set(result.index.date)

    def test_removes_data_after_end_date(self):
        after_end = self._END + timedelta(days=1)
        df = _make_date_bars([str(self._END), str(after_end)])

        result = _trim_bars_to_range(df, self._START, self._END)

        assert self._END in set(result.index.date)
        assert after_end not in set(result.index.date)

    def test_data_already_within_range_is_unchanged(self):
        df = _make_date_bars([str(self._START), str(self._END)])

        result = _trim_bars_to_range(df, self._START, self._END)

        assert len(result) == len(df)

    def test_multi_year_historical_bloat_removed(self):
        df = _make_date_bars(["2020-01-02", "2022-06-15", str(self._START)])

        result = _trim_bars_to_range(df, self._START, self._END)

        result_dates = set(result.index.date)
        assert date(2020, 1, 2) not in result_dates
        assert date(2022, 6, 15) not in result_dates
        assert self._START in result_dates


# ---------------------------------------------------------------------------
# TestFetchBarsCacheTrimming
# ---------------------------------------------------------------------------
#
# Verifies that fetch_bars never returns or saves data outside the requested
# [start_date - warmup, end_date] window, regardless of which cache path is
# taken (exact hit, stitch, or partial + delta).


class TestFetchBarsCacheTrimming:
    _START = date(2026, 3, 1)
    _END = date(2026, 3, 31)
    _TICKER = "NVDA"

    def _bloated_df(self):
        return _make_date_bars(["2020-01-02", "2022-06-15", str(self._START), str(self._END)])

    def _cache_filename(self):
        return f"alpaca_sip_5min_{self._TICKER}_{self._START}_{self._END}.json"

    def _write_cache(self, path, df):
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_json(path, orient="split", date_format="iso")

    # --- exact cache hit ---

    def test_exact_cache_hit_returns_trimmed_data(self, tmp_path):
        self._write_cache(tmp_path / self._cache_filename(), self._bloated_df())
        with patch(f"{_M}._CACHE_DIR", tmp_path), \
             patch(f"{_M}._stitch_cache", return_value=None), \
             patch(f"{_M}._partial_stitch_cache", return_value=(None, None)):
            result = fetch_bars([self._TICKER], self._START, self._END, source="alpaca")

        result_dates = set(result[self._TICKER].index.date)
        assert date(2020, 1, 2) not in result_dates
        assert date(2022, 6, 15) not in result_dates
        assert self._START in result_dates
        assert self._END in result_dates

    def test_exact_cache_hit_resaves_smaller_file_when_bloated(self, tmp_path):
        cache_file = tmp_path / self._cache_filename()
        self._write_cache(cache_file, self._bloated_df())
        size_before = cache_file.stat().st_size

        with patch(f"{_M}._CACHE_DIR", tmp_path), \
             patch(f"{_M}._stitch_cache", return_value=None), \
             patch(f"{_M}._partial_stitch_cache", return_value=(None, None)):
            fetch_bars([self._TICKER], self._START, self._END, source="alpaca")

        assert cache_file.stat().st_size < size_before

    def test_exact_cache_hit_does_not_resave_when_already_trimmed(self, tmp_path):
        clean_df = _make_date_bars([str(self._START), str(self._END)])
        cache_file = tmp_path / self._cache_filename()
        self._write_cache(cache_file, clean_df)

        with patch(f"{_M}._CACHE_DIR", tmp_path), \
             patch(f"{_M}._stitch_cache", return_value=None), \
             patch(f"{_M}._partial_stitch_cache", return_value=(None, None)), \
             patch(f"{_M}._save_cache") as save_spy:
            fetch_bars([self._TICKER], self._START, self._END, source="alpaca")

        save_spy.assert_not_called()

    # --- stitch path ---

    def test_stitch_path_returns_trimmed_data(self, tmp_path):
        with patch(f"{_M}._CACHE_DIR", tmp_path), \
             patch(f"{_M}._stitch_cache", return_value=self._bloated_df()), \
             patch(f"{_M}._partial_stitch_cache", return_value=(None, None)):
            result = fetch_bars([self._TICKER], self._START, self._END, source="alpaca")

        result_dates = set(result[self._TICKER].index.date)
        assert date(2020, 1, 2) not in result_dates
        assert self._START in result_dates

    def test_stitch_path_saves_trimmed_data_to_cache(self, tmp_path):
        with patch(f"{_M}._CACHE_DIR", tmp_path), \
             patch(f"{_M}._stitch_cache", return_value=self._bloated_df()), \
             patch(f"{_M}._partial_stitch_cache", return_value=(None, None)):
            fetch_bars([self._TICKER], self._START, self._END, source="alpaca")

        saved = _read_cache_file(tmp_path / self._cache_filename())
        saved_dates = set(saved.index.date)
        assert date(2020, 1, 2) not in saved_dates
        assert self._START in saved_dates

    # --- partial + delta path ---

    def test_partial_delta_path_returns_trimmed_data(self, tmp_path):
        partial_end = date(2026, 3, 15)
        partial_df = _make_date_bars(["2020-01-02", str(self._START), str(partial_end)])
        delta_df = _make_date_bars([str(self._END)])

        with patch(f"{_M}._CACHE_DIR", tmp_path), \
             patch(f"{_M}._stitch_cache", return_value=None), \
             patch(f"{_M}._partial_stitch_cache", return_value=(partial_df, partial_end)), \
             patch(f"{_M}.fetch_alpaca_bars", return_value={self._TICKER: delta_df}):
            result = fetch_bars([self._TICKER], self._START, self._END, source="alpaca")

        result_dates = set(result[self._TICKER].index.date)
        assert date(2020, 1, 2) not in result_dates
        assert self._START in result_dates
        assert self._END in result_dates

    def test_partial_delta_path_saves_trimmed_data_to_cache(self, tmp_path):
        partial_end = date(2026, 3, 15)
        partial_df = _make_date_bars(["2020-01-02", str(self._START), str(partial_end)])
        delta_df = _make_date_bars([str(self._END)])

        with patch(f"{_M}._CACHE_DIR", tmp_path), \
             patch(f"{_M}._stitch_cache", return_value=None), \
             patch(f"{_M}._partial_stitch_cache", return_value=(partial_df, partial_end)), \
             patch(f"{_M}.fetch_alpaca_bars", return_value={self._TICKER: delta_df}):
            fetch_bars([self._TICKER], self._START, self._END, source="alpaca")

        saved = _read_cache_file(tmp_path / self._cache_filename())
        assert date(2020, 1, 2) not in set(saved.index.date)
        assert self._START in set(saved.index.date)
        assert self._END in set(saved.index.date)

    # --- between_time filter: 16:00 bar exclusion ---

    def test_exact_cache_hit_excludes_1600_bar(self, tmp_path):
        df_with_1600 = _make_intraday_bars(
            str(self._START), ["09:30", "09:35", "15:55", "16:00"]
        )
        self._write_cache(tmp_path / self._cache_filename(), df_with_1600)

        with patch(f"{_M}._CACHE_DIR", tmp_path), \
             patch(f"{_M}._stitch_cache", return_value=None), \
             patch(f"{_M}._partial_stitch_cache", return_value=(None, None)):
            result = fetch_bars([self._TICKER], self._START, self._END, source="alpaca")

        assert all(ts.hour != 16 for ts in result[self._TICKER].index)

    def test_stitch_path_excludes_1600_bar(self, tmp_path):
        df_with_1600 = _make_intraday_bars(
            str(self._START), ["09:30", "09:35", "15:55", "16:00"]
        )

        with patch(f"{_M}._CACHE_DIR", tmp_path), \
             patch(f"{_M}._stitch_cache", return_value=df_with_1600), \
             patch(f"{_M}._partial_stitch_cache", return_value=(None, None)):
            result = fetch_bars([self._TICKER], self._START, self._END, source="alpaca")

        assert all(ts.hour != 16 for ts in result[self._TICKER].index)


# ---------------------------------------------------------------------------
# TestEvictContainedCachePieces
# ---------------------------------------------------------------------------
#
# Direct unit tests for _evict_contained_cache_pieces.
# The helper scans _CACHE_DIR for per-ticker files whose span is fully
# contained within [new_start, new_end] and deletes them, leaving the
# newly-saved consolidated file and any file that extends beyond the range.


def _touch_cache_file(directory, source, ticker, start, end):
    """Create a minimal placeholder cache file with the correct naming convention."""
    path = directory / f"{source}_5min_{ticker}_{start}_{end}.json"
    path.write_text("{}")
    return path


class TestEvictContainedCachePieces:
    _SOURCE = "alpaca"
    _TICKER = "NVDA"
    _NEW_START = date(2025, 1, 1)
    _NEW_END = date(2025, 12, 31)

    def _evict(self, tmp_path):
        with patch(f"{_M}._CACHE_DIR", tmp_path):
            _evict_contained_cache_pieces(
                self._TICKER, self._NEW_START, self._NEW_END, self._SOURCE, "5min"
            )

    def test_deletes_file_fully_contained_within_new_range(self, tmp_path):
        piece = _touch_cache_file(tmp_path, self._SOURCE, self._TICKER, "2025-01-01", "2025-06-30")

        self._evict(tmp_path)

        assert not piece.exists()

    def test_deletes_multiple_contained_files(self, tmp_path):
        piece1 = _touch_cache_file(tmp_path, self._SOURCE, self._TICKER, "2025-01-01", "2025-06-30")
        piece2 = _touch_cache_file(tmp_path, self._SOURCE, self._TICKER, "2025-07-01", "2025-12-31")

        self._evict(tmp_path)

        assert not piece1.exists()
        assert not piece2.exists()

    def test_does_not_delete_newly_saved_file(self, tmp_path):
        # The file whose span exactly matches [new_start, new_end] is the one just saved.
        saved = _touch_cache_file(tmp_path, self._SOURCE, self._TICKER, "2025-01-01", "2025-12-31")

        self._evict(tmp_path)

        assert saved.exists()

    def test_does_not_delete_file_extending_past_new_end(self, tmp_path):
        wider = _touch_cache_file(tmp_path, self._SOURCE, self._TICKER, "2025-01-01", "2026-03-31")

        self._evict(tmp_path)

        assert wider.exists()

    def test_does_not_delete_file_starting_before_new_start(self, tmp_path):
        wider = _touch_cache_file(tmp_path, self._SOURCE, self._TICKER, "2024-06-01", "2025-12-31")

        self._evict(tmp_path)

        assert wider.exists()

    def test_does_not_affect_different_ticker_files(self, tmp_path):
        other_ticker = _touch_cache_file(tmp_path, self._SOURCE, "TSLA", "2025-01-01", "2025-06-30")

        self._evict(tmp_path)

        assert other_ticker.exists()

    def test_does_not_affect_different_source_files(self, tmp_path):
        other_source = _touch_cache_file(tmp_path, "yfinance", self._TICKER, "2025-01-01", "2025-06-30")

        self._evict(tmp_path)

        assert other_source.exists()

    def test_does_not_affect_daily_bar_files(self, tmp_path):
        daily = tmp_path / f"alpaca_1day_{self._TICKER}_2025-01-01_2025-06-30.json"
        daily.write_text("{}")

        self._evict(tmp_path)

        assert daily.exists()

    def test_noop_when_no_matching_files_exist(self, tmp_path):
        # Should not raise even when the cache dir is empty.
        self._evict(tmp_path)


# ---------------------------------------------------------------------------
# TestFetchBarsConsolidatesCache
# ---------------------------------------------------------------------------
#
# Verifies that fetch_bars deletes contained piece files after saving a
# consolidated cache file, for both the stitch path and the partial+delta path.


class TestFetchBarsConsolidatesCache:
    _START = date(2025, 1, 1)
    _END = date(2025, 12, 31)
    _TICKER = "NVDA"
    _SOURCE = "alpaca_sip"

    def _consolidated_filename(self):
        return f"alpaca_sip_5min_{self._TICKER}_{self._START}_{self._END}.json"

    # --- stitch path ---

    def test_stitch_path_deletes_contained_pieces(self, tmp_path):
        piece1 = _touch_cache_file(tmp_path, self._SOURCE, self._TICKER, "2025-01-01", "2025-06-30")
        piece2 = _touch_cache_file(tmp_path, self._SOURCE, self._TICKER, "2025-07-01", "2025-12-31")
        stitched_df = _make_date_bars([str(self._START), str(self._END)])

        with patch(f"{_M}._CACHE_DIR", tmp_path), \
             patch(f"{_M}._stitch_cache", return_value=stitched_df), \
             patch(f"{_M}._partial_stitch_cache", return_value=(None, None)):
            fetch_bars([self._TICKER], self._START, self._END, source=self._SOURCE)

        assert not piece1.exists()
        assert not piece2.exists()

    def test_stitch_path_saves_consolidated_file(self, tmp_path):
        stitched_df = _make_date_bars([str(self._START), str(self._END)])

        with patch(f"{_M}._CACHE_DIR", tmp_path), \
             patch(f"{_M}._stitch_cache", return_value=stitched_df), \
             patch(f"{_M}._partial_stitch_cache", return_value=(None, None)):
            fetch_bars([self._TICKER], self._START, self._END, source=self._SOURCE)

        assert (tmp_path / self._consolidated_filename()).exists()

    def test_stitch_path_keeps_file_extending_beyond_new_range(self, tmp_path):
        wider = _touch_cache_file(tmp_path, self._SOURCE, self._TICKER, "2024-01-01", "2025-12-31")
        stitched_df = _make_date_bars([str(self._START), str(self._END)])

        with patch(f"{_M}._CACHE_DIR", tmp_path), \
             patch(f"{_M}._stitch_cache", return_value=stitched_df), \
             patch(f"{_M}._partial_stitch_cache", return_value=(None, None)):
            fetch_bars([self._TICKER], self._START, self._END, source=self._SOURCE)

        assert wider.exists()

    # --- partial + delta path ---

    def test_partial_delta_path_deletes_contained_piece(self, tmp_path):
        piece = _touch_cache_file(tmp_path, self._SOURCE, self._TICKER, "2025-01-01", "2025-06-30")
        partial_end = date(2025, 6, 30)
        partial_df = _make_date_bars([str(self._START), str(partial_end)])
        delta_df = _make_date_bars([str(self._END)])

        with patch(f"{_M}._CACHE_DIR", tmp_path), \
             patch(f"{_M}._stitch_cache", return_value=None), \
             patch(f"{_M}._partial_stitch_cache", return_value=(partial_df, partial_end)), \
             patch(f"{_M}.fetch_alpaca_bars", return_value={self._TICKER: delta_df}):
            fetch_bars([self._TICKER], self._START, self._END, source=self._SOURCE)

        assert not piece.exists()

    def test_partial_delta_path_saves_consolidated_file(self, tmp_path):
        partial_end = date(2025, 6, 30)
        partial_df = _make_date_bars([str(self._START), str(partial_end)])
        delta_df = _make_date_bars([str(self._END)])

        with patch(f"{_M}._CACHE_DIR", tmp_path), \
             patch(f"{_M}._stitch_cache", return_value=None), \
             patch(f"{_M}._partial_stitch_cache", return_value=(partial_df, partial_end)), \
             patch(f"{_M}.fetch_alpaca_bars", return_value={self._TICKER: delta_df}):
            fetch_bars([self._TICKER], self._START, self._END, source=self._SOURCE)

        assert (tmp_path / self._consolidated_filename()).exists()

    def test_partial_delta_path_keeps_file_extending_beyond_new_range(self, tmp_path):
        wider = _touch_cache_file(tmp_path, self._SOURCE, self._TICKER, "2024-01-01", "2025-12-31")
        partial_end = date(2025, 6, 30)
        partial_df = _make_date_bars([str(self._START), str(partial_end)])
        delta_df = _make_date_bars([str(self._END)])

        with patch(f"{_M}._CACHE_DIR", tmp_path), \
             patch(f"{_M}._stitch_cache", return_value=None), \
             patch(f"{_M}._partial_stitch_cache", return_value=(partial_df, partial_end)), \
             patch(f"{_M}.fetch_alpaca_bars", return_value={self._TICKER: delta_df}):
            fetch_bars([self._TICKER], self._START, self._END, source=self._SOURCE)

        assert wider.exists()


# ---------------------------------------------------------------------------
# TestStitchCacheStartGap  /  TestPartialStitchCacheStartGap
# ---------------------------------------------------------------------------
#
# Both _stitch_cache and _partial_stitch_cache used to seed covered_end from
# pieces[0][0] - 1 day instead of start_date - 1 day. That made the gap-check
# blind to holes between the *request* start and the *first piece* start,
# allowing a file for Jul-Dec to be returned as if it covered Jan-Dec.
#
# The corruption scenario:
#   cache: alpaca_5min_NVDA_2025-07-01_2025-12-31.json
#   request: 2025-01-01 → 2025-12-31
#   → stitch returns Jul-Dec data
#   → fetch_bars saves as 2025-01-01_2025-12-31.json (only contains Jul-Dec!)
#   → eviction deletes the original Jul-Dec file
#   → future Jan-Dec requests get silently truncated data


def _write_real_cache_file(directory, source, ticker, start, end, bar_dates):
    """Write a real (readable) cache file for the given date range."""
    df = _make_date_bars(bar_dates)
    path = directory / f"{source}_5min_{ticker}_{start}_{end}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_json(path, orient="split", date_format="iso")
    return path


class TestStitchCacheStartGap:
    _SOURCE = "alpaca"
    _TICKER = "NVDA"

    def test_returns_none_when_only_file_starts_well_after_request_start(self, tmp_path):
        # Cache covers Jul-Dec only; request is Jan-Dec — 6-month head gap.
        _write_real_cache_file(
            tmp_path, self._SOURCE, self._TICKER,
            "2025-07-01", "2025-12-31",
            ["2025-07-01", "2025-12-31"],
        )

        with patch(f"{_M}._CACHE_DIR", tmp_path):
            result = _stitch_cache(
                self._TICKER, date(2025, 1, 1), date(2025, 12, 31), self._SOURCE
            )

        assert result is None

    def test_returns_data_when_file_starts_within_7_days_of_request_start(self, tmp_path):
        # Cache covers Jan 5 - Dec 31; request starts Jan 1 — 4-day gap (holiday/weekend).
        _write_real_cache_file(
            tmp_path, self._SOURCE, self._TICKER,
            "2025-01-05", "2025-12-31",
            ["2025-01-05", "2025-12-31"],
        )

        with patch(f"{_M}._CACHE_DIR", tmp_path):
            result = _stitch_cache(
                self._TICKER, date(2025, 1, 1), date(2025, 12, 31), self._SOURCE
            )

        assert result is not None

    def test_returns_none_when_gap_between_two_pieces_and_request_start(self, tmp_path):
        # Two pieces (Jul-Sep, Oct-Dec) contiguous with each other but both
        # starting well after the Jan 1 request start.
        _write_real_cache_file(
            tmp_path, self._SOURCE, self._TICKER,
            "2025-07-01", "2025-09-30",
            ["2025-07-01", "2025-09-30"],
        )
        _write_real_cache_file(
            tmp_path, self._SOURCE, self._TICKER,
            "2025-10-01", "2025-12-31",
            ["2025-10-01", "2025-12-31"],
        )

        with patch(f"{_M}._CACHE_DIR", tmp_path):
            result = _stitch_cache(
                self._TICKER, date(2025, 1, 1), date(2025, 12, 31), self._SOURCE
            )

        assert result is None

    def test_stitches_successfully_when_pieces_cover_from_request_start(self, tmp_path):
        # Two contiguous pieces covering the full Jan-Dec range.
        _write_real_cache_file(
            tmp_path, self._SOURCE, self._TICKER,
            "2025-01-01", "2025-06-30",
            ["2025-01-01", "2025-06-30"],
        )
        _write_real_cache_file(
            tmp_path, self._SOURCE, self._TICKER,
            "2025-07-01", "2025-12-31",
            ["2025-07-01", "2025-12-31"],
        )

        with patch(f"{_M}._CACHE_DIR", tmp_path):
            result = _stitch_cache(
                self._TICKER, date(2025, 1, 1), date(2025, 12, 31), self._SOURCE
            )

        assert result is not None
        result_dates = set(result.index.date)
        assert date(2025, 1, 1) in result_dates
        assert date(2025, 12, 31) in result_dates


class TestPartialStitchCacheStartGap:
    _SOURCE = "alpaca"
    _TICKER = "NVDA"

    def test_returns_none_when_only_file_starts_well_after_request_start(self, tmp_path):
        # Cache covers Jul-Dec only; request is Jan-Dec — 6-month head gap.
        _write_real_cache_file(
            tmp_path, self._SOURCE, self._TICKER,
            "2025-07-01", "2025-12-31",
            ["2025-07-01", "2025-12-31"],
        )

        with patch(f"{_M}._CACHE_DIR", tmp_path):
            df, covered_end = _partial_stitch_cache(
                self._TICKER, date(2025, 1, 1), date(2025, 12, 31), self._SOURCE
            )

        assert df is None
        assert covered_end is None

    def test_returns_partial_when_file_starts_within_7_days_of_request_start(self, tmp_path):
        # Cache covers Jan 5 - Jun 30; request starts Jan 1 — 4-day gap (holiday).
        _write_real_cache_file(
            tmp_path, self._SOURCE, self._TICKER,
            "2025-01-05", "2025-06-30",
            ["2025-01-05", "2025-06-30"],
        )

        with patch(f"{_M}._CACHE_DIR", tmp_path):
            df, covered_end = _partial_stitch_cache(
                self._TICKER, date(2025, 1, 1), date(2025, 12, 31), self._SOURCE
            )

        assert df is not None
        assert covered_end == date(2025, 6, 30)

    def test_fetch_bars_does_not_corrupt_cache_when_only_tail_is_cached(self, tmp_path):
        # The corruption scenario: cache has Jul-Dec, request Jan-Dec.
        # Before the fix, fetch_bars would save a Jan-Dec file with only Jul-Dec data
        # and then evict the original Jul-Dec file.
        # After the fix, a full API fetch should be triggered for the complete Jan-Dec range.
        full_year_df = _make_date_bars(["2025-01-01", "2025-06-30", "2025-12-31"])
        _write_real_cache_file(
            tmp_path, self._SOURCE, self._TICKER,
            "2025-07-01", "2025-12-31",
            ["2025-07-01", "2025-12-31"],
        )

        with patch(f"{_M}._CACHE_DIR", tmp_path), \
             patch(f"{_M}.fetch_alpaca_bars", return_value={self._TICKER: full_year_df}) \
             as mock_fetch:
            result = fetch_bars(
                [self._TICKER], date(2025, 1, 1), date(2025, 12, 31), source=self._SOURCE
            )

        # Full API fetch should have been triggered for the complete range.
        mock_fetch.assert_called_once()
        # Result must contain January data, not just July onwards.
        result_dates = set(result[self._TICKER].index.date)
        assert date(2025, 1, 1) in result_dates


# ---------------------------------------------------------------------------
# TestSaveCacheAtomic
# ---------------------------------------------------------------------------
#
# _save_cache writes to a .tmp sibling then renames via Path.replace() so
# readers always see a complete file, never a partial write.


class TestSaveCacheAtomic:
    def test_final_file_exists_and_is_readable(self, tmp_path):
        df = _make_date_bars(["2025-01-01", "2025-06-30"])
        path = tmp_path / "alpaca_5min_NVDA_2025-01-01_2025-06-30.json"

        _save_cache(df, path, "5min")

        loaded = _read_cache_file(path)
        assert date(2025, 1, 1) in set(loaded.index.date)
        assert date(2025, 6, 30) in set(loaded.index.date)

    def test_no_tmp_file_left_behind(self, tmp_path):
        df = _make_date_bars(["2025-01-01"])
        path = tmp_path / "alpaca_5min_NVDA_2025-01-01_2025-01-01.json"

        _save_cache(df, path, "5min")

        assert not path.with_suffix(".tmp").exists()

    def test_data_written_to_tmp_before_rename(self, tmp_path):
        # If the rename step fails, the .tmp file exists with valid data and
        # the final file is absent — proving data flows through .tmp first.
        df = _make_date_bars(["2025-01-01"])
        path = tmp_path / "test.json"

        with patch.object(Path, "replace", side_effect=OSError("simulated rename failure")):
            try:
                _save_cache(df, path, "5min")
            except OSError:
                pass

        assert not path.exists()
        assert any(tmp_path.glob("*.tmp"))


# ---------------------------------------------------------------------------
# TestStitchCacheFileNotFound
# ---------------------------------------------------------------------------
#
# If a piece file is evicted by another process between the directory scan
# and the load, _stitch_cache must return None gracefully instead of raising.


class TestStitchCacheFileNotFound:
    _SOURCE = "alpaca"
    _TICKER = "NVDA"

    def test_returns_none_when_piece_load_raises_file_not_found(self, tmp_path):
        _write_real_cache_file(
            tmp_path, self._SOURCE, self._TICKER,
            "2025-01-01", "2025-06-30", ["2025-01-01", "2025-06-30"],
        )
        _write_real_cache_file(
            tmp_path, self._SOURCE, self._TICKER,
            "2025-07-01", "2025-12-31", ["2025-07-01", "2025-12-31"],
        )

        with patch(f"{_M}._CACHE_DIR", tmp_path), \
             patch(f"{_M}._load_cache", side_effect=FileNotFoundError):
            result = _stitch_cache(
                self._TICKER, date(2025, 1, 1), date(2025, 12, 31), self._SOURCE
            )

        assert result is None


# ---------------------------------------------------------------------------
# TestPartialStitchCacheFileNotFound
# ---------------------------------------------------------------------------
#
# If the first piece is gone, return (None, None). If a later piece is gone,
# return coverage up to the last successfully loaded piece.


class TestPartialStitchCacheFileNotFound:
    _SOURCE = "alpaca"
    _TICKER = "NVDA"

    def test_returns_none_when_only_piece_load_raises_file_not_found(self, tmp_path):
        _write_real_cache_file(
            tmp_path, self._SOURCE, self._TICKER,
            "2025-01-01", "2025-06-30", ["2025-01-01", "2025-06-30"],
        )

        with patch(f"{_M}._CACHE_DIR", tmp_path), \
             patch(f"{_M}._load_cache", side_effect=FileNotFoundError):
            df, covered_end = _partial_stitch_cache(
                self._TICKER, date(2025, 1, 1), date(2025, 12, 31), self._SOURCE
            )

        assert df is None
        assert covered_end is None

    def test_returns_first_piece_coverage_when_second_piece_load_raises(self, tmp_path):
        # Two pieces: Jan-Jun and Jul-Dec. Jul-Dec is evicted during load.
        # Should return (Jan-Jun data, Jun 30) — coverage up to the last safe piece.
        first_df = _make_date_bars(["2025-01-01", "2025-06-30"])
        _write_real_cache_file(
            tmp_path, self._SOURCE, self._TICKER,
            "2025-01-01", "2025-06-30", ["2025-01-01", "2025-06-30"],
        )
        _write_real_cache_file(
            tmp_path, self._SOURCE, self._TICKER,
            "2025-07-01", "2025-12-31", ["2025-07-01", "2025-12-31"],
        )

        with patch(f"{_M}._CACHE_DIR", tmp_path), \
             patch(f"{_M}._load_cache", side_effect=[first_df, FileNotFoundError()]):
            df, covered_end = _partial_stitch_cache(
                self._TICKER, date(2025, 1, 1), date(2025, 12, 31), self._SOURCE
            )

        assert df is not None
        assert covered_end == date(2025, 6, 30)


# ---------------------------------------------------------------------------
# TestEvictContainedCachePiecesFileNotFound
# ---------------------------------------------------------------------------
#
# If another process already deleted a contained piece, unlink raises
# FileNotFoundError. The eviction must not propagate it.


class TestEvictContainedCachePiecesFileNotFound:
    def test_does_not_raise_when_unlink_raises_file_not_found(self, tmp_path):
        _touch_cache_file(tmp_path, "alpaca", "NVDA", "2025-01-01", "2025-06-30")

        with patch(f"{_M}._CACHE_DIR", tmp_path), \
             patch.object(Path, "unlink", side_effect=FileNotFoundError):
            # Must not raise
            _evict_contained_cache_pieces(
                "NVDA", date(2025, 1, 1), date(2025, 12, 31), "alpaca", "5min"
            )


# ---------------------------------------------------------------------------
# TestFetchBarsUnlinkFileNotFound
# ---------------------------------------------------------------------------
#
# fetch_bars calls cp.unlink() in two places when a cache file is stale:
#   1. The loaded file is empty (corrupt).
#   2. The loaded file's data doesn't cover the requested range after trimming.
# Both must tolerate FileNotFoundError in case another process already deleted it.


class TestFetchBarsUnlinkFileNotFound:
    _START = date(2025, 1, 1)
    _END = date(2025, 12, 31)
    _TICKER = "NVDA"
    _SOURCE = "alpaca"

    def _cache_file(self, tmp_path):
        path = tmp_path / f"alpaca_5min_{self._TICKER}_{self._START}_{self._END}.json"
        path.write_text("{}")  # make cp.exists() True; content doesn't matter (load is mocked)
        return path

    def test_does_not_raise_when_empty_file_unlink_raises_file_not_found(self, tmp_path):
        self._cache_file(tmp_path)

        with patch(f"{_M}._CACHE_DIR", tmp_path), \
             patch(f"{_M}._load_cache", return_value=pd.DataFrame()), \
             patch.object(Path, "unlink", side_effect=FileNotFoundError), \
             patch(f"{_M}._stitch_cache", return_value=None), \
             patch(f"{_M}._partial_stitch_cache", return_value=(None, None)), \
             patch(f"{_M}.fetch_alpaca_bars", return_value={}):
            fetch_bars([self._TICKER], self._START, self._END, source=self._SOURCE)

    def test_does_not_raise_when_non_covering_file_unlink_raises_file_not_found(
        self, tmp_path
    ):
        self._cache_file(tmp_path)
        # Loaded data is from 2020 — _trim_bars_to_range will strip it all, leaving empty.
        stale_df = _make_date_bars(["2020-01-02"])

        with patch(f"{_M}._CACHE_DIR", tmp_path), \
             patch(f"{_M}._load_cache", return_value=stale_df), \
             patch.object(Path, "unlink", side_effect=FileNotFoundError), \
             patch(f"{_M}._stitch_cache", return_value=None), \
             patch(f"{_M}._partial_stitch_cache", return_value=(None, None)), \
             patch(f"{_M}.fetch_alpaca_bars", return_value={}):
            fetch_bars([self._TICKER], self._START, self._END, source=self._SOURCE)


# ---------------------------------------------------------------------------
# fetch_bars — TradeStation source + market_data_client caching
# ---------------------------------------------------------------------------

class TestFetchBarsTradeStation:
    _START = date(2026, 3, 1)
    _END = date(2026, 3, 31)
    _TICKER = "NVDA"

    def _make_client(self, df=None):
        client = MagicMock()
        if df is None:
            df = _make_date_bars([str(self._START), str(self._END)])
        client.fetch_bars.return_value = {self._TICKER: df}
        return client

    def test_calls_market_data_client_on_cache_miss(self, tmp_path):
        client = self._make_client()
        with patch(f"{_M}._CACHE_DIR", tmp_path), \
             patch(f"{_M}._stitch_cache", return_value=None), \
             patch(f"{_M}._partial_stitch_cache", return_value=(None, None)):
            fetch_bars([self._TICKER], self._START, self._END,
                       source="tradestation", market_data_client=client)

        client.fetch_bars.assert_called_once()

    def test_caches_result_under_tradestation_key(self, tmp_path):
        client = self._make_client()
        with patch(f"{_M}._CACHE_DIR", tmp_path), \
             patch(f"{_M}._stitch_cache", return_value=None), \
             patch(f"{_M}._partial_stitch_cache", return_value=(None, None)):
            fetch_bars([self._TICKER], self._START, self._END,
                       source="tradestation", market_data_client=client)

        cache_file = tmp_path / f"tradestation_5min_{self._TICKER}_{self._START}_{self._END}.json"
        assert cache_file.exists()

    def test_returns_cached_data_without_calling_client(self, tmp_path):
        df = _make_date_bars([str(self._START), str(self._END)])
        cache_file = tmp_path / f"tradestation_5min_{self._TICKER}_{self._START}_{self._END}.json"
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        df.to_json(cache_file, orient="split", date_format="iso")

        client = self._make_client()
        with patch(f"{_M}._CACHE_DIR", tmp_path), \
             patch(f"{_M}._stitch_cache", return_value=None), \
             patch(f"{_M}._partial_stitch_cache", return_value=(None, None)):
            result = fetch_bars([self._TICKER], self._START, self._END,
                                source="tradestation", market_data_client=client)

        client.fetch_bars.assert_not_called()
        assert not result[self._TICKER].empty

    def test_delta_fetches_from_tradestation_client(self, tmp_path):
        partial_end = date(2026, 3, 20)
        partial_df = _make_date_bars([str(self._START), str(partial_end)])
        tail_df = _make_date_bars([str(self._END)])
        client = MagicMock()
        client.fetch_bars.return_value = {self._TICKER: tail_df}

        with patch(f"{_M}._CACHE_DIR", tmp_path), \
             patch(f"{_M}._stitch_cache", return_value=None), \
             patch(f"{_M}._partial_stitch_cache", return_value=(partial_df, partial_end)):
            result = fetch_bars([self._TICKER], self._START, self._END,
                                source="tradestation", market_data_client=client)

        client.fetch_bars.assert_called_once()
        assert not result[self._TICKER].empty

    def test_client_receives_et_datetime_range(self, tmp_path):
        client = self._make_client()
        with patch(f"{_M}._CACHE_DIR", tmp_path), \
             patch(f"{_M}._stitch_cache", return_value=None), \
             patch(f"{_M}._partial_stitch_cache", return_value=(None, None)):
            fetch_bars([self._TICKER], self._START, self._END,
                       source="tradestation", market_data_client=client)

        _, start_dt, end_dt = client.fetch_bars.call_args[0]
        assert start_dt.tzinfo is not None
        assert start_dt.hour == 9 and start_dt.minute == 30
        assert end_dt.hour == 16 and end_dt.minute == 0

    def test_does_not_call_fetch_alpaca_bars_when_tradestation_source(self, tmp_path):
        client = self._make_client()
        with patch(f"{_M}._CACHE_DIR", tmp_path), \
             patch(f"{_M}._stitch_cache", return_value=None), \
             patch(f"{_M}._partial_stitch_cache", return_value=(None, None)), \
             patch(f"{_M}.fetch_alpaca_bars") as mock_alpaca:
            fetch_bars([self._TICKER], self._START, self._END,
                       source="tradestation", market_data_client=client)

        mock_alpaca.assert_not_called()

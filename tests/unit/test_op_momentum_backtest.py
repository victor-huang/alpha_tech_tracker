from datetime import date, datetime

import pandas as pd
import pytest
import pytz

from alpha_tech_tracker.op_momentum_strategy.op_momentum_backtest import (
    compute_signals_with_backtest,
)
from alpha_tech_tracker.op_momentum_strategy.op_momentum_selector_backtest import (
    _apply_capital_flow,
)


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

"""
Tests for _apply_capital_flow sub-trade (BRE/REV/BRU) phase logic.

Drain-time reference:
  M1: opening_start=09:30, opening_bars=3  → drain_min = 9*60+45 = 585
  A1: opening_start=10:00, opening_bars=2  → drain_min = 10*60+10 = 610

Sub-trade entry time formula:
  sub_entry_min = prior_drain + (primary_bars + 1 + sub_entry_idx + 1) * 5

Phase 3 (sub active at A1 drain): sub_entry_min <= 610 < sub_exit_min
Phase 4 (sub exited before A1 drain): sub_exit_min <= 610
"""
from datetime import date

from alpha_tech_tracker.op_momentum_strategy.op_momentum_selector_backtest import (
    _apply_capital_flow,
)

_DATE = date(2026, 3, 17)

# drain_min["M1"] = 9*60+45 = 585
# drain_min["A1"] = 10*60+10 = 610
_WINDOWS = [
    {"label": "M1", "opening_start": "09:30", "opening_bars": 3},
    {"label": "A1", "opening_start": "10:00", "opening_bars": 2},
]
_MORNING_SPLIT = [1.0]  # M1 is first group; A1 is sequential

_INITIAL_CAPITAL = 10000.0
_WEIGHTS = [1.0]  # single ticker


def _primary_row(**extra):
    base = {
        "date": _DATE,
        "window": "M1",
        "rank": 1,
        "entry_price": 100.0,
        "pnl": -2.0,
        "bars_held": 2,  # exits at 585 + 2*5 = 595, before A1 drain=610
    }
    base.update(extra)
    return base


def _get_a1_budget(rows):
    """Run _apply_capital_flow and return the window_capital assigned to A1 rows,
    or the computed available capital when A1 has no trades (inferred from skip_log)."""
    skip_log = _apply_capital_flow(
        rows,
        _WINDOWS,
        _INITIAL_CAPITAL,
        _WEIGHTS,
        n=1,
        morning_split=_MORNING_SPLIT,
    )
    a1_entry = next((e for e in skip_log if e["window"] == "A1"), None)
    return a1_entry["available_capital"]


# ---------------------------------------------------------------------------
# TestCapitalFlowSubtradePhase3 — sub-trade running at A1 drain → slot locked
# ---------------------------------------------------------------------------


class TestCapitalFlowSubtradePhase3:
    def test_bre_active_at_drain_deducts_slot_capital(self):
        # sub_entry_min = 585 + (2+1+0+1)*5 = 605; sub_exit_min = 605 + 2*5 = 615
        # Phase 3: 605 <= 610 < 615 → sub active → deduct slot_capital
        row = _primary_row(
            br_entry_price=98.0,
            br_pnl=3.0,
            br_entry_idx=0,
            br_bars_held=2,
        )
        a1_available = _get_a1_budget([row])

        # M1 deployed 10000, BRE still running → none returned → A1 gets 0
        assert a1_available == 0.0

    def test_rev_active_at_drain_deducts_slot_capital(self):
        # sub_entry_min = 585 + (2+1+0+1)*5 = 605; sub_exit_min = 605 + 2*5 = 615
        # Phase 3: 605 <= 610 < 615 → sub active → deduct slot_capital
        row = _primary_row(
            rev_entry_price=101.0,
            rev_pnl=5.0,
            rev_entry_idx=0,
            rev_bars_held=2,
        )
        a1_available = _get_a1_budget([row])

        assert a1_available == 0.0

    def test_bru_active_at_drain_deducts_slot_capital(self):
        # sub_entry_min = 585 + (2+1+0+1)*5 = 605; sub_exit_min = 605 + 2*5 = 615
        # Phase 3: 605 <= 610 < 615 → sub active → deduct slot_capital
        row = _primary_row(
            bru_entry_price=97.0,
            bru_pnl=4.0,
            bru_entry_idx=0,
            bru_bars_held=2,
        )
        a1_available = _get_a1_budget([row])

        assert a1_available == 0.0

    def test_bre_active_at_drain_deducts_actual_slot_capital_not_full_capital(self):
        # With 2 tickers and 60/40 weighting, slot_capital = 10000 * 0.6 = 6000
        row_rank1 = _primary_row(
            rank=1,
            br_entry_price=98.0,
            br_pnl=3.0,
            br_entry_idx=0,
            br_bars_held=2,
        )
        row_rank2 = dict(
            date=_DATE,
            window="M1",
            rank=2,
            entry_price=50.0,
            pnl=1.0,
            bars_held=1,  # exits at 595, no sub-trade
        )
        skip_log = _apply_capital_flow(
            [row_rank1, row_rank2],
            _WINDOWS,
            _INITIAL_CAPITAL,
            [0.6, 0.4],
            n=2,
            morning_split=[1.0],
        )
        a1_entry = next(e for e in skip_log if e["window"] == "A1")

        # available starts at 10000
        # rank1 BRE active → deduct slot_capital(6000) → available = 4000
        # rank2 exited → cap_pnl = (4000/50)*1 = 80 → available = 4080
        assert abs(a1_entry["available_capital"] - 4080.0) < 1.0


# ---------------------------------------------------------------------------
# TestCapitalFlowSubtradePhase4 — sub-trade exited before A1 drain → full P&L
# ---------------------------------------------------------------------------


class TestCapitalFlowSubtradePhase4:
    def test_bre_exited_before_drain_adds_full_cap_pnl(self):
        # sub_entry_min = 585 + (2+1+0+1)*5 = 605; sub_exit_min = 605 + 1*5 = 610
        # Phase 4: sub_exit_min=610 == this_drain=610 → NOT active → full cap_pnl
        row = _primary_row(
            entry_price=100.0,
            pnl=-2.0,
            br_entry_price=98.0,
            br_pnl=5.0,
            br_entry_idx=0,
            br_bars_held=1,
        )
        a1_available = _get_a1_budget([row])

        # cap_pnl = (10000/100)*(-2) + (10000/98)*5 = -200 + ~510.2 = ~310.2
        expected_cap_pnl = (10000.0 / 100.0) * (-2.0) + (10000.0 / 98.0) * 5.0
        assert abs(a1_available - (_INITIAL_CAPITAL + expected_cap_pnl)) < 0.01

    def test_rev_exited_before_drain_adds_full_cap_pnl(self):
        row = _primary_row(
            entry_price=100.0,
            pnl=-2.0,
            rev_entry_price=103.0,
            rev_pnl=8.0,
            rev_entry_idx=0,
            rev_bars_held=1,
        )
        a1_available = _get_a1_budget([row])

        expected_cap_pnl = (10000.0 / 100.0) * (-2.0) + (10000.0 / 103.0) * 8.0
        assert abs(a1_available - (_INITIAL_CAPITAL + expected_cap_pnl)) < 0.01

    def test_bru_exited_before_drain_adds_full_cap_pnl(self):
        row = _primary_row(
            entry_price=100.0,
            pnl=-1.5,
            bru_entry_price=97.0,
            bru_pnl=6.0,
            bru_entry_idx=0,
            bru_bars_held=1,
        )
        a1_available = _get_a1_budget([row])

        expected_cap_pnl = (10000.0 / 100.0) * (-1.5) + (10000.0 / 97.0) * 6.0
        assert abs(a1_available - (_INITIAL_CAPITAL + expected_cap_pnl)) < 0.01

    def test_no_sub_trade_primary_exited_adds_primary_only_cap_pnl(self):
        # No BRE/REV/BRU fields → fallback to slot_exit_bars
        # primary_exit_time = 585 + 2*5 = 595 < 610 → add cap_pnl
        row = _primary_row(entry_price=100.0, pnl=-2.0)
        a1_available = _get_a1_budget([row])

        primary_cap_pnl = (10000.0 / 100.0) * (-2.0)
        assert abs(a1_available - (_INITIAL_CAPITAL + primary_cap_pnl)) < 0.01


# ---------------------------------------------------------------------------
# TestCapitalFlowSubtradePhase1 — primary still running at A1 drain
# ---------------------------------------------------------------------------


class TestCapitalFlowSubtradePhase1:
    def test_primary_still_running_at_drain_deducts_slot_capital(self):
        # primary bars_held=5 → exit_time = 585 + 5*5 = 610 which equals this_drain
        # primary_exit_time > this_drain? 610 > 610? No → NOT Phase 1
        # Use bars_held=6 → exit_time=615 > 610 → Phase 1
        row = _primary_row(
            bars_held=6,
            br_entry_price=98.0,
            br_pnl=3.0,
            br_entry_idx=0,
            br_bars_held=2,
        )
        a1_available = _get_a1_budget([row])

        # Phase 1: primary still running → deduct full slot_capital (10000)
        assert a1_available == 0.0

    def test_primary_exits_exactly_at_drain_not_treated_as_phase1(self):
        # primary_exit_time = 585 + 5*5 = 610 == this_drain (610)
        # condition is primary_exit_time > this_drain → False → NOT Phase 1
        row = _primary_row(
            bars_held=5,
            # No sub-trade so fallback: slot_exit_time = 585 + 5*5 = 610
            # slot_exit_time > this_drain? 610 > 610? No → add cap_pnl
        )
        a1_available = _get_a1_budget([row])

        primary_cap_pnl = (10000.0 / 100.0) * (-2.0)
        assert abs(a1_available - (_INITIAL_CAPITAL + primary_cap_pnl)) < 0.01

import unittest.mock
from datetime import date, datetime, timedelta

import pandas as pd
import pytest
import pytz

from alpha_tech_tracker.op_momentum_strategy.op_momentum_selector_backtest import (
    _annotate_doubledown_addon,
    _apply_capital_flow,
    _apply_opportunity_pool,
    _compute_bear_ctp_dates,
    _compute_rolling_stats,
    _print_daily_table,
    _print_reentry_subrow,
    _qqq_regime_factor,
)
from alpha_tech_tracker.op_momentum_strategy.op_momentum_backtest import (
    _stitch_cache,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ET = pytz.timezone("America/New_York")

_W1 = {"label": "W1", "opening_start": "09:30", "opening_bars": 3}
_W2 = {"label": "W2", "opening_start": "13:15", "opening_bars": 1}
_W3 = {"label": "W3", "opening_start": "15:00", "opening_bars": 1}

_WEIGHTS = [0.5, 0.3, 0.2]
_D1 = date(2025, 1, 2)
_D2 = date(2025, 1, 3)


def _row(window, rank, entry, pnl, d=_D1):
    return {
        "date": d,
        "window": window,
        "rank": rank,
        "entry_price": entry,
        "pnl": pnl,
    }


def _cap_pnl(row):
    return row["cap_pnl"]


# ---------------------------------------------------------------------------
# _apply_capital_flow — single window (no-compound)
# ---------------------------------------------------------------------------


class TestApplyCapitalFlowSingleWindow:
    def test_cap_pnl_proportional_to_rank_weight(self):
        rows = [
            _row("W1", 1, 100.0, 2.0),
            _row("W1", 2, 50.0, 1.0),
        ]
        _apply_capital_flow(rows, [_W1], 10_000, _WEIGHTS, 3)

        # rank-1: 10000 * 0.5 / 100 * 2 = 100
        assert rows[0]["cap_pnl"] == pytest.approx(100.0)
        # rank-2: 10000 * 0.3 / 50 * 1 = 60
        assert rows[1]["cap_pnl"] == pytest.approx(60.0)

    def test_no_compound_resets_portfolio_each_day(self):
        rows = [
            _row("W1", 1, 100.0, 10.0, _D1),
            _row("W1", 1, 100.0, 10.0, _D2),
        ]
        _apply_capital_flow(rows, [_W1], 10_000, _WEIGHTS, 3, compound=False)

        # Both days deploy the same $10k (reset), so cap_pnl should be identical
        assert rows[0]["cap_pnl"] == pytest.approx(rows[1]["cap_pnl"])

    def test_compound_grows_portfolio_across_days(self):
        rows = [
            _row("W1", 1, 100.0, 10.0, _D1),
            _row("W1", 1, 100.0, 10.0, _D2),
        ]
        _apply_capital_flow(rows, [_W1], 10_000, _WEIGHTS, 3, compound=True)

        # Day 2 cap_pnl must be larger because portfolio grew on day 1
        assert rows[1]["cap_pnl"] > rows[0]["cap_pnl"]

    def test_window_skipped_when_capital_below_minimum(self):
        rows = [_row("W1", 1, 100.0, 5.0)]
        _apply_capital_flow(
            rows, [_W1], 10_000, _WEIGHTS, 3, min_capital=999_999
        )
        assert rows[0]["cap_pnl"] == 0.0
        assert rows[0]["skipped"] is True


# ---------------------------------------------------------------------------
# _apply_capital_flow — sequential windows
# ---------------------------------------------------------------------------


class TestApplyCapitalFlowSequentialWindows:
    def test_sequential_window_gets_first_group_plus_pnl(self):
        rows = [
            _row("W1", 1, 100.0, 5.0),   # W1 gains +$250 (10000*0.5/100*5)
            _row("W2", 1, 50.0, 1.0),    # W2 should deploy 10000+250 = 10250
        ]
        _apply_capital_flow(
            rows, [_W1, _W2], 10_000, _WEIGHTS, 3,
            morning_split=[1.0],
        )

        w1_pnl = rows[0]["cap_pnl"]           # 10000*0.5/100*5 = 250
        expected_w2_capital = 10_000 + w1_pnl
        assert rows[1]["window_capital"] == pytest.approx(expected_w2_capital)

    def test_morning_window_pnl_is_additive_regardless_of_sequential_windows(self):
        rows_single = [_row("W1", 1, 100.0, 2.0)]
        rows_combined = [
            _row("W1", 1, 100.0, 2.0),
            _row("W2", 1, 50.0, 1.0),
        ]
        _apply_capital_flow(rows_single, [_W1], 10_000, _WEIGHTS, 3)
        _apply_capital_flow(
            rows_combined, [_W1, _W2], 10_000, _WEIGHTS, 3,
            morning_split=[1.0],
        )

        assert rows_single[0]["cap_pnl"] == pytest.approx(rows_combined[0]["cap_pnl"])

    def test_two_sequential_windows_chain_capital(self):
        rows = [
            _row("W1", 1, 100.0, 10.0),  # W1 P&L raises available pot
            _row("W2", 1, 100.0, 5.0),   # W2 gets that pot
            _row("W3", 1, 100.0, 2.0),   # W3 gets W2's returned pot
        ]
        _apply_capital_flow(
            rows, [_W1, _W2, _W3], 10_000, _WEIGHTS, 3,
            morning_split=[1.0],
        )

        w1_pnl = rows[0]["cap_pnl"]
        w2_capital = 10_000 + w1_pnl
        assert rows[1]["window_capital"] == pytest.approx(w2_capital)

        w2_pnl = rows[1]["cap_pnl"]
        w3_capital = w2_capital + w2_pnl
        assert rows[2]["window_capital"] == pytest.approx(w3_capital)

    def test_60_40_morning_split_deploys_correct_capital(self):
        rows = [
            _row("W1", 1, 100.0, 0.0),  # first group, 60%
            _row("W2", 1, 100.0, 0.0),  # first group, 40%
        ]
        _apply_capital_flow(
            rows, [_W1, _W2], 10_000, _WEIGHTS, 3,
            morning_split=[0.6, 0.4],
        )

        assert rows[0]["window_capital"] == pytest.approx(6_000.0)
        assert rows[1]["window_capital"] == pytest.approx(4_000.0)

    def test_sequential_window_skipped_does_not_consume_capital(self):
        rows = [
            _row("W1", 1, 100.0, 5.0),
            _row("W2", 1, 50.0, 1.0),
        ]
        _apply_capital_flow(
            rows, [_W1, _W2], 10_000, _WEIGHTS, 3,
            morning_split=[1.0], min_capital=999_999,
        )

        assert rows[1]["cap_pnl"] == 0.0
        assert rows[1]["skipped"] is True

    def test_locked_morning_capital_reduces_sequential_window_budget(self):
        # W1 drain = 09:30 + 3 bars = 09:45 = 585 min
        # W2 drain = 13:15 + 1 bar  = 13:20 = 800 min
        # W1 row bars_held=50 → exit at 585 + 250 = 835 min (after W2 drain 800)
        # → slot_capital is locked; W2 should get 10000 - slot_capital, not 10000 + pnl
        row_w1 = {**_row("W1", 1, 100.0, 5.0), "bars_held": 50}
        row_w2 = _row("W2", 1, 50.0, 1.0)
        _apply_capital_flow(
            [row_w1, row_w2], [_W1, _W2], 10_000, _WEIGHTS, 3,
            morning_split=[1.0],
        )

        slot_w1 = row_w1["slot_capital"]   # 10000 * 0.5 = 5000
        assert row_w2["window_capital"] == pytest.approx(10_000 - slot_w1)

    def test_locked_capital_unlocks_for_later_sequential_window(self):
        # W1 exit at 835 min — after W2 drain (800) but before W3 drain (905)
        # → locked for W2, but returned (with pnl) for W3
        # W3 drain = 15:00 + 1 bar = 15:05 = 905 min
        row_w1 = {**_row("W1", 1, 100.0, 5.0), "bars_held": 50}
        row_w2 = _row("W2", 1, 50.0, 1.0)
        row_w3 = _row("W3", 1, 50.0, 0.5)
        _apply_capital_flow(
            [row_w1, row_w2, row_w3], [_W1, _W2, _W3], 10_000, _WEIGHTS, 3,
            morning_split=[1.0],
        )

        # W3 should get: 10000 + W1 pnl + W2 pnl (both returned before 905 min)
        w1_pnl = row_w1["cap_pnl"]
        w2_pnl = row_w2["cap_pnl"]
        assert row_w3["window_capital"] == pytest.approx(10_000 + w1_pnl + w2_pnl)


# ---------------------------------------------------------------------------
# _apply_capital_flow — slot_exit_bars (BRE/BRU/REV sub-trade timing fix)
#
# Windows used in this section:
#   W1        09:30 / 3 bars → drain = 09:45 = 585 min  (first group)
#   W_EARLY   10:00 / 1 bar  → drain = 10:05 = 605 min  (sequential, 20 min after W1)
#   W2        13:15 / 1 bar  → drain = 13:20 = 800 min  (sequential)
#
# A primary that exits before W_EARLY drain (bars_held=1 → exit_time=590 ≤ 605)
# normally frees its slot. When a BRU/BRE fires after that primary exit and runs
# past the drain, slot_exit_bars > bars_held, keeping the slot locked.
#
# slot_exit_bars formula (per sub-trade):
#   sub_exit = primary_bars + 1 + entry_idx + 1 + sub_bars_held
#   slot_exit_bars = max(primary_bars, br_exit, bru_exit, rev_exit)
# ---------------------------------------------------------------------------

_W_EARLY = {"label": "W_EARLY", "opening_start": "10:00", "opening_bars": 1}


def _slot_row(window, rank, entry, pnl, bars_held, slot_exit_bars=None, d=_D1, **extra):
    r = {"date": d, "window": window, "rank": rank, "entry_price": entry,
         "pnl": pnl, "bars_held": bars_held}
    if slot_exit_bars is not None:
        r["slot_exit_bars"] = slot_exit_bars
    r.update(extra)
    return r


class TestApplyCapitalFlowSlotExitBars:
    def test_no_slot_exit_bars_falls_back_to_bars_held(self):
        # Primary exits at 590 (< W_EARLY drain 605): slot freed, W_EARLY gets full pot.
        row_w1 = _slot_row("W1", 1, 100.0, 5.0, bars_held=1)
        row_we = _slot_row("W_EARLY", 1, 50.0, 1.0, bars_held=1)
        _apply_capital_flow(
            [row_w1, row_we], [_W1, _W_EARLY], 10_000, _WEIGHTS, 3,
            morning_split=[1.0],
        )

        assert row_we["window_capital"] == pytest.approx(10_000 + row_w1["cap_pnl"])

    def test_sub_trade_past_drain_locks_slot(self):
        # Primary exits at 590 (< drain 605), but BRU runs past drain:
        # slot_exit_bars=5 → exit_time = 585 + 25 = 610 > 605 → slot locked.
        # W_EARLY capital = 10000 - slot_capital(W1).
        row_w1 = _slot_row("W1", 1, 100.0, 5.0, bars_held=1, slot_exit_bars=5)
        row_we = _slot_row("W_EARLY", 1, 50.0, 1.0, bars_held=1)
        _apply_capital_flow(
            [row_w1, row_we], [_W1, _W_EARLY], 10_000, _WEIGHTS, 3,
            morning_split=[1.0],
        )

        slot_w1 = row_w1["slot_capital"]
        assert row_we["window_capital"] == pytest.approx(10_000 - slot_w1)

    def test_sub_trade_that_exits_exactly_at_drain_frees_slot(self):
        # exit_time = 585 + 4*5 = 605 == W_EARLY drain 605 → condition ≤ → freed.
        row_w1 = _slot_row("W1", 1, 100.0, 5.0, bars_held=1, slot_exit_bars=4)
        row_we = _slot_row("W_EARLY", 1, 50.0, 1.0, bars_held=1)
        _apply_capital_flow(
            [row_w1, row_we], [_W1, _W_EARLY], 10_000, _WEIGHTS, 3,
            morning_split=[1.0],
        )

        assert row_we["window_capital"] == pytest.approx(10_000 + row_w1["cap_pnl"])

    def test_both_slots_locked_by_sub_trades_skips_sequential_window(self):
        # Mirrors the real CRDO-BRU / SNDK case on 2026-01-09:
        # rank-1 primary runs past drain (bars_held=25, exit_time=710 > 605).
        # rank-2 primary exits before drain (bars_held=1) but BRU keeps slot locked
        # (slot_exit_bars=33 → exit_time=585+165=750 > 605).
        # With 60/40 weights both slots together consume 100% of capital
        # → available ≈ 0 → W_EARLY skipped.
        weights_60_40 = [0.6, 0.4]
        row_r1 = _slot_row("W1", 1, 100.0, 2.0, bars_held=25)
        row_r2 = _slot_row("W1", 2, 100.0, -1.0, bars_held=1, slot_exit_bars=33)
        row_we = _slot_row("W_EARLY", 1, 50.0, 1.0, bars_held=1)
        _apply_capital_flow(
            [row_r1, row_r2, row_we], [_W1, _W_EARLY], 10_000, weights_60_40, 2,
            morning_split=[1.0],
        )

        assert row_we["skipped"] is True

    def test_slot_locked_for_early_window_but_freed_for_later_window(self):
        # slot_exit_bars=5 → exit_time=610 > W_EARLY drain (605) but < W2 drain (800).
        # → locked for W_EARLY, returned (with pnl) for W2.
        row_w1 = _slot_row("W1", 1, 100.0, 5.0, bars_held=1, slot_exit_bars=5)
        row_we = _slot_row("W_EARLY", 1, 50.0, 2.0, bars_held=1)
        row_w2 = _slot_row("W2", 1, 50.0, 1.0, bars_held=1)
        _apply_capital_flow(
            [row_w1, row_we, row_w2], [_W1, _W_EARLY, _W2], 10_000, _WEIGHTS, 3,
            morning_split=[1.0],
        )

        slot_w1 = row_w1["slot_capital"]
        assert row_we["window_capital"] == pytest.approx(10_000 - slot_w1)
        assert row_w2["window_capital"] == pytest.approx(
            10_000 + row_w1["cap_pnl"] + row_we["cap_pnl"]
        )

    def test_add_on_rows_excluded_from_capital_flow_calculation(self):
        # A BRE add-on row (is_bearish_reentry=True) reuses the primary's slot —
        # it must not be double-counted in the available-capital formula.
        # Without the exclusion, the add-on's large slot_exit_bars would falsely
        # deduct additional capital, starving the sequential window.
        row_w1 = _slot_row("W1", 1, 100.0, 2.0, bars_held=1)
        row_bre = _slot_row(
            "W1", 1, 100.0, -1.0, bars_held=30, slot_exit_bars=35,
            is_bearish_reentry=True,
        )
        row_we = _slot_row("W_EARLY", 1, 50.0, 1.0, bars_held=1)
        _apply_capital_flow(
            [row_w1, row_bre, row_we], [_W1, _W_EARLY], 10_000, _WEIGHTS, 3,
            morning_split=[1.0],
        )

        # Primary exits at 590 (freed for W_EARLY); BRE row is excluded.
        # W_EARLY should get full pot (not have BRE's slot deducted).
        assert row_we["window_capital"] == pytest.approx(10_000 + row_w1["cap_pnl"])


# ---------------------------------------------------------------------------
# _apply_capital_flow — sub-trade phase model (Phase 2 / Phase 3 / Phase 4)
#
# Windows:
#   W1  09:30 / 3 bars → drain = 585 min (first group; prior_drain for W2)
#   W2  13:15 / 1 bar  → drain = 800 min (first sequential)
#   W3  15:00 / 1 bar  → drain = 905 min (second sequential)
#
# Sub-trade entry formula (BRU/BRE/REV):
#   sub_entry_min = prior_drain + (primary_bars + 1 + sub_entry_idx + 1) * 5
# With primary_bars=1, prior_drain=585:
#   sub_entry_idx=44 → sub_entry_min = 585 + (3+44)*5 = 820  (after W2 drain 800)
#   sub_entry_idx=20 → sub_entry_min = 585 + (3+20)*5 = 700  (before W2 drain 800)
#
# This test class captures the 2026-05-01 bug where both A1 slots had BRUs that
# fired AFTER A2's drain time, causing the batch backtest to lock those slots at
# A2 time and give A2 a $0 budget (skipped) — even though capital was genuinely
# free between the A1 primary exit and the late BRU entry.
# ---------------------------------------------------------------------------


def _bru_row(
    window,
    rank,
    bru_entry_idx,
    bru_bars_held,
    entry=100.0,
    exit_=98.0,
    signal="BEARISH",
    pnl=-5.0,
    bru_entry=99.0,
    bru_pnl=-50.0,
    d=_D1,
):
    """Row helper: primary exits after 1 bar; BRU timing set via entry_idx/bars_held."""
    primary_bars = 1
    slot_exit = max(primary_bars, primary_bars + 1 + bru_entry_idx + 1 + bru_bars_held)
    return {
        "date": d,
        "window": window,
        "rank": rank,
        "entry_price": entry,
        "exit_price": exit_,
        "signal": signal,
        "pnl": pnl,
        "bars_held": primary_bars,
        "slot_exit_bars": slot_exit,
        "bru_entry_price": bru_entry,
        "bru_entry_idx": bru_entry_idx,
        "bru_bars_held": bru_bars_held,
        "bru_pnl": bru_pnl,
    }


class TestApplyCapitalFlowSubTradeTiming:
    def test_phase2_bru_not_started_at_drain_adds_primary_cap_pnl(self):
        # BRU entry_min=820 > W2 drain (800) → Phase 2.
        # W2 window_capital = initial + primary-only cap_pnl (not combined).
        # slot_capital = 10000 * 0.5 = 5000; primary_cap_pnl = 5000/100*(100-98) = 100.
        row_w1 = _bru_row("W1", 1, bru_entry_idx=44, bru_bars_held=5)
        row_w2 = _row("W2", 1, 50.0, 1.0)
        _apply_capital_flow(
            [row_w1, row_w2], [_W1, _W2], 10_000, _WEIGHTS, 3,
            morning_split=[1.0],
        )

        slot_capital = row_w1["slot_capital"]
        primary_cap_pnl = slot_capital / 100.0 * (100.0 - 98.0)
        assert row_w2["window_capital"] == pytest.approx(10_000 + primary_cap_pnl)

    def test_phase2_combined_cap_pnl_not_applied_early(self):
        # At Phase 2, only primary P&L is added — not the BRU's (negative) P&L.
        # Combined cap_pnl is negative; primary_cap_pnl is positive.
        # W2 window_capital must be above initial (primary gain), not below (combined loss).
        row_w1 = _bru_row("W1", 1, bru_entry_idx=44, bru_bars_held=5,
                           pnl=-5.0, bru_pnl=-200.0)
        row_w2 = _row("W2", 1, 50.0, 1.0)
        _apply_capital_flow(
            [row_w1, row_w2], [_W1, _W2], 10_000, _WEIGHTS, 3,
            morning_split=[1.0],
        )

        slot_capital = row_w1["slot_capital"]
        primary_cap_pnl = slot_capital / 100.0 * (100.0 - 98.0)
        assert row_w2["window_capital"] == pytest.approx(10_000 + primary_cap_pnl)
        assert row_w2["window_capital"] > 10_000

    def test_phase3_bru_running_at_drain_locks_slot(self):
        # BRU entry_min=700 ≤ W2 drain (800) < exit_min=825 → Phase 3.
        # W2 window_capital = initial - slot_capital.
        row_w1 = _bru_row("W1", 1, bru_entry_idx=20, bru_bars_held=25)
        row_w2 = _row("W2", 1, 50.0, 1.0)
        _apply_capital_flow(
            [row_w1, row_w2], [_W1, _W2], 10_000, _WEIGHTS, 3,
            morning_split=[1.0],
        )

        slot_capital = row_w1["slot_capital"]
        assert row_w2["window_capital"] == pytest.approx(10_000 - slot_capital)

    def test_phase4_bru_already_exited_adds_combined_cap_pnl(self):
        # BRU entry_min=700, exit_min=735 — both ≤ W2 drain (800) → Phase 4.
        # W2 window_capital = initial + combined cap_pnl (primary + BRU).
        row_w1 = _bru_row("W1", 1, bru_entry_idx=20, bru_bars_held=5)
        row_w2 = _row("W2", 1, 50.0, 1.0)
        _apply_capital_flow(
            [row_w1, row_w2], [_W1, _W2], 10_000, _WEIGHTS, 3,
            morning_split=[1.0],
        )

        assert row_w2["window_capital"] == pytest.approx(10_000 + row_w1["cap_pnl"])

    def test_phase2_at_w2_then_phase4_at_w3(self):
        # BRU entry_min=820, exit_min=845. Phase 2 at W2 (820>800); Phase 4 at W3 (845≤905).
        # W2 capital = initial + primary_cap_pnl.
        # W3 capital = initial + combined cap_pnl + W2 cap_pnl.
        row_w1 = _bru_row("W1", 1, bru_entry_idx=44, bru_bars_held=5)
        row_w2 = _row("W2", 1, 50.0, 2.0)
        row_w3 = _row("W3", 1, 50.0, 1.0)
        _apply_capital_flow(
            [row_w1, row_w2, row_w3], [_W1, _W2, _W3], 10_000, _WEIGHTS, 3,
            morning_split=[1.0],
        )

        slot_capital = row_w1["slot_capital"]
        primary_cap_pnl = slot_capital / 100.0 * (100.0 - 98.0)
        assert row_w2["window_capital"] == pytest.approx(10_000 + primary_cap_pnl)
        assert row_w3["window_capital"] == pytest.approx(
            10_000 + row_w1["cap_pnl"] + row_w2["cap_pnl"]
        )

    def test_both_slots_phase2_sequential_window_not_skipped(self):
        # 2026-05-01 bug pattern: both W1 rank-1 and rank-2 have BRUs that fire
        # after W2's drain. Previously the batch locked both slots → W2 got $0 →
        # skipped. Now both contribute primary_cap_pnl → W2 receives enough capital.
        weights_60_40 = [0.6, 0.4]
        row_r1 = _bru_row("W1", 1, bru_entry_idx=44, bru_bars_held=5)
        row_r2 = _bru_row("W1", 2, bru_entry_idx=44, bru_bars_held=5)
        row_w2 = _row("W2", 1, 50.0, 1.0)
        _apply_capital_flow(
            [row_r1, row_r2, row_w2], [_W1, _W2], 10_000, weights_60_40, 2,
            morning_split=[1.0],
        )

        assert row_w2["skipped"] is False
        slot_r1 = row_r1["slot_capital"]  # 10000 * 0.6 = 6000
        slot_r2 = row_r2["slot_capital"]  # 10000 * 0.4 = 4000
        primary_pnl_r1 = slot_r1 / 100.0 * (100.0 - 98.0)
        primary_pnl_r2 = slot_r2 / 100.0 * (100.0 - 98.0)
        assert row_w2["window_capital"] == pytest.approx(
            10_000 + primary_pnl_r1 + primary_pnl_r2
        )

    def test_phase1_regression_primary_still_running_locks_slot(self):
        # When the primary trade itself hasn't exited by W2's drain, slot is locked
        # regardless of BRU fields. Regression guard for Phase 1.
        # primary_bars=20 → primary_exit_time = 585+100=685 < 800 → Phase 1... wait
        # Actually 685 < 800 means it HAS exited. Use primary_bars=44.
        # primary_bars=44 → exit = 585+220=805 > 800 → Phase 1 (locked).
        row_w1 = {
            "date": _D1, "window": "W1", "rank": 1,
            "entry_price": 100.0, "exit_price": 98.0, "signal": "BEARISH",
            "pnl": -5.0, "bars_held": 44,
            "bru_entry_price": 99.0, "bru_entry_idx": 44, "bru_bars_held": 5,
            "bru_pnl": -10.0,
        }
        row_w2 = _row("W2", 1, 50.0, 1.0)
        _apply_capital_flow(
            [row_w1, row_w2], [_W1, _W2], 10_000, _WEIGHTS, 3,
            morning_split=[1.0],
        )

        slot_capital = row_w1["slot_capital"]
        assert row_w2["window_capital"] == pytest.approx(10_000 - slot_capital)


# ---------------------------------------------------------------------------
# _apply_capital_flow — returns skip_log
# ---------------------------------------------------------------------------


class TestApplyCapitalFlowSkipLog:
    def test_returns_one_log_entry_per_window_per_day(self):
        rows = [_row("W1", 1, 100.0, 1.0)]
        log = _apply_capital_flow(rows, [_W1], 10_000, _WEIGHTS, 3)
        assert len(log) == 1
        assert log[0]["window"] == "W1"
        assert log[0]["date"] == _D1

    def test_executed_status_when_picks_present(self):
        rows = [_row("W1", 1, 100.0, 1.0)]
        log = _apply_capital_flow(rows, [_W1], 10_000, _WEIGHTS, 3)
        assert log[0]["status"] == "executed"

    def test_no_signal_status_when_no_picks(self):
        # W2 is a defined window but has no trade rows for the day
        rows = [_row("W1", 1, 100.0, 1.0)]
        log = _apply_capital_flow(rows, [_W1, _W2], 10_000, _WEIGHTS, 3)
        w2_entry = next(e for e in log if e["window"] == "W2")
        assert w2_entry["status"] == "no_signal"


# ---------------------------------------------------------------------------
# _stitch_cache
# ---------------------------------------------------------------------------

_TICKER = "AAPL"
_SOURCE = "alpaca"
_START = date(2021, 1, 1)
_END = date(2022, 12, 31)


def _make_df(timestamps):
    idx = pd.DatetimeIndex(timestamps, tz="America/New_York")
    return pd.DataFrame({"Close": [100.0] * len(timestamps)}, index=idx)


class TestStitchCache:
    def test_returns_none_when_no_cache_files(self, tmp_path, monkeypatch):
        import alpha_tech_tracker.op_momentum_strategy.op_momentum_backtest as m
        monkeypatch.setattr(m, "_CACHE_DIR", tmp_path)
        result = _stitch_cache(_TICKER, _START, _END, _SOURCE)
        assert result is None

    def test_returns_dataframe_when_single_file_covers_range(self, tmp_path, monkeypatch):
        import alpha_tech_tracker.op_momentum_strategy.op_momentum_backtest as m
        monkeypatch.setattr(m, "_CACHE_DIR", tmp_path)
        df = _make_df(["2020-11-01 09:35:00", "2022-12-30 09:35:00"])
        cache_file = tmp_path / f"{_SOURCE}_5min_{_TICKER}_2020-11-01_2022-12-31.json"
        df.to_json(cache_file, orient="split", date_format="iso")

        result = _stitch_cache(_TICKER, _START, _END, _SOURCE)
        assert result is not None
        assert len(result) == 2

    def test_stitches_two_overlapping_files_covering_range(self, tmp_path, monkeypatch):
        import alpha_tech_tracker.op_momentum_strategy.op_momentum_backtest as m
        monkeypatch.setattr(m, "_CACHE_DIR", tmp_path)
        df1 = _make_df(["2020-11-01 09:35:00", "2021-06-30 09:35:00"])
        df2 = _make_df(["2021-06-15 09:35:00", "2022-12-30 09:35:00"])

        (tmp_path / f"{_SOURCE}_5min_{_TICKER}_2020-11-01_2021-12-31.json").write_text(
            df1.to_json(orient="split", date_format="iso")
        )
        (tmp_path / f"{_SOURCE}_5min_{_TICKER}_2021-11-01_2022-12-31.json").write_text(
            df2.to_json(orient="split", date_format="iso")
        )

        result = _stitch_cache(_TICKER, _START, _END, _SOURCE)
        assert result is not None
        # 4 unique timestamps: df1[0]=2020-11-01, df2[0]=2021-06-15, df1[1]=2021-06-30, df2[1]=2022-12-30
        assert len(result) == 4

    def test_returns_none_when_gap_between_pieces_exceeds_threshold(
        self, tmp_path, monkeypatch
    ):
        import alpha_tech_tracker.op_momentum_strategy.op_momentum_backtest as m
        monkeypatch.setattr(m, "_CACHE_DIR", tmp_path)
        df1 = _make_df(["2021-01-04 09:35:00"])
        df2 = _make_df(["2022-06-01 09:35:00", "2022-12-30 09:35:00"])

        (tmp_path / f"{_SOURCE}_5min_{_TICKER}_2020-11-01_2021-06-30.json").write_text(
            df1.to_json(orient="split", date_format="iso")
        )
        (tmp_path / f"{_SOURCE}_5min_{_TICKER}_2022-05-01_2022-12-31.json").write_text(
            df2.to_json(orient="split", date_format="iso")
        )

        result = _stitch_cache(_TICKER, _START, _END, _SOURCE)
        assert result is None

    def test_returns_none_when_pieces_dont_reach_end_date(self, tmp_path, monkeypatch):
        import alpha_tech_tracker.op_momentum_strategy.op_momentum_backtest as m
        monkeypatch.setattr(m, "_CACHE_DIR", tmp_path)
        df = _make_df(["2021-01-04 09:35:00", "2021-12-30 09:35:00"])
        (tmp_path / f"{_SOURCE}_5min_{_TICKER}_2020-11-01_2021-12-31.json").write_text(
            df.to_json(orient="split", date_format="iso")
        )

        result = _stitch_cache(_TICKER, _START, _END, _SOURCE)
        assert result is None

    def test_ignores_files_for_different_ticker(self, tmp_path, monkeypatch):
        import alpha_tech_tracker.op_momentum_strategy.op_momentum_backtest as m
        monkeypatch.setattr(m, "_CACHE_DIR", tmp_path)
        df = _make_df(["2020-11-01 09:35:00", "2022-12-30 09:35:00"])
        (tmp_path / f"{_SOURCE}_5min_MSFT_2020-11-01_2022-12-31.json").write_text(
            df.to_json(orient="split", date_format="iso")
        )

        result = _stitch_cache(_TICKER, _START, _END, _SOURCE)
        assert result is None

    def test_result_is_sorted_and_deduplicated(self, tmp_path, monkeypatch):
        import alpha_tech_tracker.op_momentum_strategy.op_momentum_backtest as m
        monkeypatch.setattr(m, "_CACHE_DIR", tmp_path)
        df1 = _make_df(["2021-01-04 09:35:00", "2021-06-30 09:35:00"])
        df2 = _make_df(["2021-06-30 09:35:00", "2022-12-30 09:35:00"])

        (tmp_path / f"{_SOURCE}_5min_{_TICKER}_2020-11-01_2021-12-31.json").write_text(
            df1.to_json(orient="split", date_format="iso")
        )
        (tmp_path / f"{_SOURCE}_5min_{_TICKER}_2021-11-01_2022-12-31.json").write_text(
            df2.to_json(orient="split", date_format="iso")
        )

        result = _stitch_cache(_TICKER, _START, _END, _SOURCE)
        assert result is not None
        assert result.index.is_monotonic_increasing
        assert not result.index.duplicated().any()


# ---------------------------------------------------------------------------
# _annotate_doubledown_addon
# ---------------------------------------------------------------------------
#
# dd_bars = doubledown_start_min // 5
# With doubledown_start_min=5 → dd_bars=1.
# addon_bar = post_or.iloc[1]  (NOT iloc[0], which was the old off-by-one bug)
#
# Setup:
#   OR close bar index: 09:45 (3-bar OR: 09:30, 09:35, 09:40 → OR closes at 09:45)
#   post_or.iloc[0] → 09:45 close=50.0  (old wrong entry)
#   post_or.iloc[1] → 09:50 close=55.0  (correct entry after fix)
#
# Winner exits at 09:55 with exit_price=60.0 (BULLISH).
# Rank-2 stopout exits at 09:45 with bars_held=1 (≤ dd_bars=1) — capital freed.


def _make_intraday_bars(date_str, times):
    """One bar per (date, time) pair with distinct Close values for identification."""
    index = [
        ET.localize(datetime.strptime(f"{date_str} {t}", "%Y-%m-%d %H:%M"))
        for t in times
    ]
    close_prices = [float(50 + i * 5) for i in range(len(times))]
    rows = [
        {"Open": 100.0, "High": 101.0, "Low": 99.0, "Close": c, "Volume": 1000}
        for c in close_prices
    ]
    return pd.DataFrame(rows, index=pd.DatetimeIndex(index))


def _make_intraday_bars_ohlc(date_str, bar_specs):
    """bar_specs: list of (time_str, close, high, low)."""
    index = [
        ET.localize(datetime.strptime(f"{date_str} {t}", "%Y-%m-%d %H:%M"))
        for t, _, _, _ in bar_specs
    ]
    rows = [
        {"Open": c, "High": h, "Low": l, "Close": c, "Volume": 1000}
        for _, c, h, l in bar_specs
    ]
    return pd.DataFrame(rows, index=pd.DatetimeIndex(index))


_DD_DATE = date(2025, 1, 2)
_DD_DATE_STR = "2025-01-02"
# OR window: 09:30 start, 3 bars → OR closes at 09:45
# post_or starts at 09:45
# iloc[0]=09:45 (close=50), iloc[1]=09:50 (close=55), iloc[2]=09:55 (close=60)
_DD_TIMES = ["09:45", "09:50", "09:55"]


def _dd_winner_row(exit_price=60.0, bars_held=2):
    return {
        "date": _DD_DATE,
        "window": "M1",
        "rank": 1,
        "ticker": "NVDA",
        "signal": "BULLISH",
        "entry_price": 48.0,
        "exit_price": exit_price,
        "exit_reason": "end_of_day",
        "bars_held": bars_held,
    }


def _dd_stopout_row(bars_held=0):
    return {
        "date": _DD_DATE,
        "window": "M1",
        "rank": 2,
        "ticker": "TSLA",
        "signal": "BULLISH",
        "entry_price": 48.0,
        "exit_price": 45.0,
        "exit_reason": "hard_stop",
        "bars_held": bars_held,
    }


def _dd_bars_by_date():
    df = _make_intraday_bars(_DD_DATE_STR, _DD_TIMES)
    return {"NVDA": {_DD_DATE: df}}


class TestAnnotateDoubledownAddon:
    _WINDOW_OPENING_TIMES = {"M1": datetime.strptime("09:30", "%H:%M").time()}
    _OPENING_BARS_BY_LABEL = {"M1": 3}

    def test_addon_entry_uses_iloc_1_not_iloc_0(self):
        # With doubledown_start_min=5: dd_bars=1 → addon_bar=post_or.iloc[1]
        # post_or.iloc[0] close=50.0, post_or.iloc[1] close=55.0
        rows = [_dd_winner_row(), _dd_stopout_row()]
        _annotate_doubledown_addon(
            rows,
            _dd_bars_by_date(),
            self._WINDOW_OPENING_TIMES,
            self._OPENING_BARS_BY_LABEL,
            doubledown_start_min=5,
        )

        winner = next(r for r in rows if r["rank"] == 1)
        assert "dd_addon_entry" in winner
        assert winner["dd_addon_entry"] == pytest.approx(55.0)

    def test_addon_entry_is_not_or_close_bar(self):
        # The OR-close bar (post_or.iloc[0]) has close=50.0.
        # The fix ensures addon_entry != 50.0.
        rows = [_dd_winner_row(), _dd_stopout_row()]
        _annotate_doubledown_addon(
            rows,
            _dd_bars_by_date(),
            self._WINDOW_OPENING_TIMES,
            self._OPENING_BARS_BY_LABEL,
            doubledown_start_min=5,
        )

        winner = next(r for r in rows if r["rank"] == 1)
        assert winner.get("dd_addon_entry") != pytest.approx(50.0)

    def test_no_addon_when_stopout_exited_after_dd_bars(self):
        # Stopout bars_held=2 > dd_bars=1 → stopout is NOT eligible → no addon.
        rows = [_dd_winner_row(), _dd_stopout_row(bars_held=2)]
        _annotate_doubledown_addon(
            rows,
            _dd_bars_by_date(),
            self._WINDOW_OPENING_TIMES,
            self._OPENING_BARS_BY_LABEL,
            doubledown_start_min=5,
        )

        winner = next(r for r in rows if r["rank"] == 1)
        assert "dd_addon_entry" not in winner

    def test_no_addon_when_winner_exits_before_dd_bar(self):
        # Winner bars_held=0 < dd_bars=1 → winner already exited → no addon.
        rows = [_dd_winner_row(bars_held=0), _dd_stopout_row()]
        _annotate_doubledown_addon(
            rows,
            _dd_bars_by_date(),
            self._WINDOW_OPENING_TIMES,
            self._OPENING_BARS_BY_LABEL,
            doubledown_start_min=5,
        )

        winner = next(r for r in rows if r["rank"] == 1)
        assert "dd_addon_entry" not in winner

    def test_addon_pnl_pct_is_nonnegative(self):
        # BULLISH winner: addon_entry=55.0, exit_price=60.0 → raw_pct=(60-55)/55 > 0.
        rows = [_dd_winner_row(exit_price=60.0), _dd_stopout_row()]
        _annotate_doubledown_addon(
            rows,
            _dd_bars_by_date(),
            self._WINDOW_OPENING_TIMES,
            self._OPENING_BARS_BY_LABEL,
            doubledown_start_min=5,
        )

        winner = next(r for r in rows if r["rank"] == 1)
        assert winner["dd_addon_pnl_pct"] >= 0.0

    def test_freed_ranks_contains_stopout_rank(self):
        rows = [_dd_winner_row(), _dd_stopout_row()]
        _annotate_doubledown_addon(
            rows,
            _dd_bars_by_date(),
            self._WINDOW_OPENING_TIMES,
            self._OPENING_BARS_BY_LABEL,
            doubledown_start_min=5,
        )

        winner = next(r for r in rows if r["rank"] == 1)
        assert winner["dd_freed_ranks"] == [2]

    def test_addon_fires_for_afternoon_a1_window(self):
        # Window opens at 13:15/1-bar → OR closes at 13:20.
        # doubledown_start_min=5 → dd_bars=1 → addon_bar at 13:25 → DD fires.
        afternoon_date = date(2025, 1, 2)
        afternoon_date_str = "2025-01-02"
        bars = _make_intraday_bars(afternoon_date_str, ["13:20", "13:25", "13:30"])
        bars_by_date = {"NVDA": {afternoon_date: bars}}
        winner = {
            "date": afternoon_date, "window": "A1", "rank": 1,
            "ticker": "NVDA", "signal": "BULLISH",
            "entry_price": 48.0, "exit_price": 60.0,
            "exit_reason": "end_of_day", "bars_held": 3,
        }
        stopout = {
            "date": afternoon_date, "window": "A1", "rank": 2,
            "ticker": "TSLA", "signal": "BULLISH",
            "entry_price": 48.0, "exit_price": 45.0,
            "exit_reason": "hard_stop", "bars_held": 0,
        }
        rows = [winner, stopout]
        _annotate_doubledown_addon(
            rows,
            bars_by_date,
            {"A1": datetime.strptime("13:15", "%H:%M").time()},
            {"A1": 1},
            doubledown_start_min=5,
        )

        assert "dd_addon_entry" in winner

    def test_addon_fires_when_dd_bar_is_before_1300(self):
        # Window opens at 12:30/1-bar → OR closes at 12:35.
        # doubledown_start_min=5 → dd_bars=1 → addon_bar at 12:40 (< 13:00) → fires.
        morning_date = date(2025, 1, 2)
        morning_date_str = "2025-01-02"
        bars = _make_intraday_bars(morning_date_str, ["12:35", "12:40", "12:45"])
        bars_by_date = {"NVDA": {morning_date: bars}}
        winner = {
            "date": morning_date, "window": "A1", "rank": 1,
            "ticker": "NVDA", "signal": "BULLISH",
            "entry_price": 48.0, "exit_price": 60.0,
            "exit_reason": "end_of_day", "bars_held": 3,
        }
        stopout = {
            "date": morning_date, "window": "A1", "rank": 2,
            "ticker": "TSLA", "signal": "BULLISH",
            "entry_price": 48.0, "exit_price": 45.0,
            "exit_reason": "hard_stop", "bars_held": 0,
        }
        rows = [winner, stopout]
        _annotate_doubledown_addon(
            rows,
            bars_by_date,
            {"A1": datetime.strptime("12:30", "%H:%M").time()},
            {"A1": 1},
            doubledown_start_min=5,
        )

        assert "dd_addon_entry" in winner

    # -----------------------------------------------------------------------
    # Bar-scan stop-breach tests (added 2026-05-10)
    #
    # Setup (shared across breach tests):
    #   post_or.iloc[0] = 09:45, close=50.0, High=101.0, Low=99.0  (not addon bar)
    #   post_or.iloc[1] = 09:50, close=55.0, High=101.0, Low=99.0  (addon_bar)
    #     → stop_price (BULLISH) = 55.0 − 0.80 × (101−99) = 55.0 − 1.6 = 53.4
    #     → stop_price (BEARISH) = 55.0 + 0.80 × (101−99) = 55.0 + 1.6 = 56.6
    #   post_or.iloc[2] = 09:55                                      (first scanned bar)
    #
    # bars_held=2 → bars_after_addon = post_or.iloc[2:3] (one bar scanned)
    # -----------------------------------------------------------------------

    def test_bullish_stop_not_breached_uses_primary_exit_price(self):
        bars = _make_intraday_bars_ohlc(_DD_DATE_STR, [
            ("09:45", 50.0, 101.0, 99.0),
            ("09:50", 55.0, 101.0, 99.0),  # addon_bar; stop=53.4
            ("09:55", 65.0, 66.0, 54.0),   # Low=54.0 > 53.4 → no breach
        ])
        winner = _dd_winner_row(exit_price=65.0, bars_held=2)
        rows = [winner, _dd_stopout_row()]
        _annotate_doubledown_addon(
            rows, {"NVDA": {_DD_DATE: bars}},
            self._WINDOW_OPENING_TIMES, self._OPENING_BARS_BY_LABEL,
            doubledown_start_min=5,
        )
        assert winner["dd_addon_stop_breached"] is False
        assert winner["dd_addon_effective_exit"] == pytest.approx(65.0)
        assert winner["dd_addon_pnl_pct"] == pytest.approx((65.0 - 55.0) / 55.0)

    def test_bullish_stop_breached_uses_stop_price(self):
        bars = _make_intraday_bars_ohlc(_DD_DATE_STR, [
            ("09:45", 50.0, 101.0, 99.0),
            ("09:50", 55.0, 101.0, 99.0),  # addon_bar; stop=53.4
            ("09:55", 53.5, 54.0, 52.0),   # Low=52.0 < 53.4 → breach
        ])
        winner = _dd_winner_row(exit_price=65.0, bars_held=2)
        rows = [winner, _dd_stopout_row()]
        _annotate_doubledown_addon(
            rows, {"NVDA": {_DD_DATE: bars}},
            self._WINDOW_OPENING_TIMES, self._OPENING_BARS_BY_LABEL,
            doubledown_start_min=5,
        )
        expected_stop = 55.0 - 0.80 * (101.0 - 99.0)  # 53.4
        assert winner["dd_addon_stop_breached"] is True
        assert winner["dd_addon_effective_exit"] == pytest.approx(expected_stop)
        assert winner["dd_addon_pnl_pct"] == pytest.approx((expected_stop - 55.0) / 55.0)

    def test_bearish_stop_not_breached_uses_primary_exit_price(self):
        bars = _make_intraday_bars_ohlc(_DD_DATE_STR, [
            ("09:45", 50.0, 101.0, 99.0),
            ("09:50", 55.0, 101.0, 99.0),  # addon_bar; stop=56.6
            ("09:55", 50.0, 56.0, 49.0),   # High=56.0 < 56.6 → no breach
        ])
        winner = {
            "date": _DD_DATE, "window": "M1", "rank": 1,
            "ticker": "NVDA", "signal": "BEARISH",
            "entry_price": 58.0, "exit_price": 50.0,
            "exit_reason": "end_of_day", "bars_held": 2,
        }
        rows = [winner, _dd_stopout_row()]
        _annotate_doubledown_addon(
            rows, {"NVDA": {_DD_DATE: bars}},
            self._WINDOW_OPENING_TIMES, self._OPENING_BARS_BY_LABEL,
            doubledown_start_min=5,
        )
        assert winner["dd_addon_stop_breached"] is False
        assert winner["dd_addon_effective_exit"] == pytest.approx(50.0)
        assert winner["dd_addon_pnl_pct"] == pytest.approx((55.0 - 50.0) / 55.0)

    def test_bearish_stop_breached_uses_stop_price(self):
        bars = _make_intraday_bars_ohlc(_DD_DATE_STR, [
            ("09:45", 50.0, 101.0, 99.0),
            ("09:50", 55.0, 101.0, 99.0),  # addon_bar; stop=56.6
            ("09:55", 57.0, 57.5, 56.0),   # High=57.5 > 56.6 → breach
        ])
        winner = {
            "date": _DD_DATE, "window": "M1", "rank": 1,
            "ticker": "NVDA", "signal": "BEARISH",
            "entry_price": 58.0, "exit_price": 50.0,
            "exit_reason": "end_of_day", "bars_held": 2,
        }
        rows = [winner, _dd_stopout_row()]
        _annotate_doubledown_addon(
            rows, {"NVDA": {_DD_DATE: bars}},
            self._WINDOW_OPENING_TIMES, self._OPENING_BARS_BY_LABEL,
            doubledown_start_min=5,
        )
        expected_stop = 55.0 + 0.80 * (101.0 - 99.0)  # 56.6
        assert winner["dd_addon_stop_breached"] is True
        assert winner["dd_addon_effective_exit"] == pytest.approx(expected_stop)
        assert winner["dd_addon_pnl_pct"] == pytest.approx((55.0 - expected_stop) / 55.0)

    def test_stop_breach_only_scanned_up_to_bars_held(self):
        # Winner exits at bars_held=2. A breach occurs at post_or.iloc[3] (bars_held=3).
        # That bar is outside the scan window → stop_breached must remain False.
        bars = _make_intraday_bars_ohlc(_DD_DATE_STR, [
            ("09:45", 50.0, 101.0, 99.0),
            ("09:50", 55.0, 101.0, 99.0),  # addon_bar; stop=53.4
            ("09:55", 65.0, 66.0, 54.0),   # Low=54.0 > 53.4 → no breach (scanned)
            ("10:00", 30.0, 31.0, 20.0),   # Low=20.0 < 53.4 → breach, but NOT scanned
        ])
        winner = _dd_winner_row(exit_price=65.0, bars_held=2)
        rows = [winner, _dd_stopout_row()]
        _annotate_doubledown_addon(
            rows, {"NVDA": {_DD_DATE: bars}},
            self._WINDOW_OPENING_TIMES, self._OPENING_BARS_BY_LABEL,
            doubledown_start_min=5,
        )
        assert winner["dd_addon_stop_breached"] is False
        assert winner["dd_addon_effective_exit"] == pytest.approx(65.0)


# ---------------------------------------------------------------------------
# _apply_opportunity_pool
# ---------------------------------------------------------------------------
#
# Window configs used throughout:
#   M1: 09:30 / 3 bars → or_close_min=585, dd_fire_min=590 (with dd_start_min=5)
#   A1: 13:15 / 1 bar  → or_close_min=800, dd_fire_min=805
#   A2: 15:00 / 1 bar  → or_close_min=905, dd_fire_min=910
#
# A row is DD-eligible when it has "dd_freed_ranks" set and not "skipped".

_M1 = {"label": "M1", "opening_start": "09:30", "opening_bars": 3}
_A1 = {"label": "A1", "opening_start": "13:15", "opening_bars": 1}
_A2 = {"label": "A2", "opening_start": "15:00", "opening_bars": 1}
_DD_START_MIN = 5  # → dd_bars = 1


def _opp_row(window, bars_held=3, pnl_pct=0.10, exit_reason="end_of_day", d=_D1):
    return {
        "date": d,
        "window": window,
        "rank": 1,
        "entry_price": 100.0,
        "pnl": 0.0,
        "cap_pnl": 0.0,
        "bars_held": bars_held,
        "exit_reason": exit_reason,
        "dd_freed_ranks": [2],
        "dd_addon_pnl_pct": pnl_pct,
    }


class TestApplyOpportunityPool:
    def test_deploys_pool_on_dd_eligible_winner(self):
        row = _opp_row("M1", pnl_pct=0.10)
        _apply_opportunity_pool([row], [_M1], initial_pool=1_000.0, doubledown_start_min=_DD_START_MIN)

        assert row["opp_deployed"] == pytest.approx(1_000.0)
        assert row["opp_cap_pnl"] == pytest.approx(100.0)
        assert row["opp_returned"] == pytest.approx(1_100.0)

    def test_opp_cap_pnl_folds_into_cap_pnl(self):
        row = _opp_row("M1", pnl_pct=0.10)
        row["cap_pnl"] = 500.0
        _apply_opportunity_pool([row], [_M1], initial_pool=1_000.0, doubledown_start_min=_DD_START_MIN)

        assert row["cap_pnl"] == pytest.approx(600.0)

    def test_no_deployment_without_dd_freed_ranks(self):
        row = {"date": _D1, "window": "M1", "rank": 1, "cap_pnl": 0.0,
               "bars_held": 3, "dd_addon_pnl_pct": 0.10}
        _apply_opportunity_pool([row], [_M1], initial_pool=1_000.0, doubledown_start_min=_DD_START_MIN)

        assert "opp_cap_pnl" not in row

    def test_no_deployment_when_row_is_skipped(self):
        row = _opp_row("M1", pnl_pct=0.10)
        row["skipped"] = True
        _apply_opportunity_pool([row], [_M1], initial_pool=1_000.0, doubledown_start_min=_DD_START_MIN)

        assert "opp_cap_pnl" not in row

    def test_pool_recycles_to_next_window_after_early_exit(self):
        # M1 exits after bars_held=2 (not EOD) → pool_exit_min=600 < A1 dd_fire=805 → A1 deploys
        m1 = _opp_row("M1", bars_held=2, pnl_pct=0.10, exit_reason="trailing_stop")
        a1 = _opp_row("A1", bars_held=3, pnl_pct=0.05, exit_reason="end_of_day")
        _apply_opportunity_pool([m1, a1], [_M1, _A1], initial_pool=1_000.0, doubledown_start_min=_DD_START_MIN)

        assert m1["opp_deployed"] == pytest.approx(1_000.0)
        assert a1["opp_deployed"] == pytest.approx(1_100.0)  # recycled from M1
        assert a1["opp_cap_pnl"] == pytest.approx(55.0)

    def test_pool_locked_when_prior_deployment_still_running(self):
        # M1 exit_reason=end_of_day → pool_exit_min=960 > A1 dd_fire=805 → A1 skipped
        m1 = _opp_row("M1", bars_held=3, pnl_pct=0.10, exit_reason="end_of_day")
        a1 = _opp_row("A1", bars_held=3, pnl_pct=0.05, exit_reason="end_of_day")
        _apply_opportunity_pool([m1, a1], [_M1, _A1], initial_pool=1_000.0, doubledown_start_min=_DD_START_MIN)

        assert "opp_cap_pnl" in m1
        assert "opp_cap_pnl" not in a1

    def test_no_compound_resets_pool_each_day(self):
        d1_row = _opp_row("M1", pnl_pct=0.10, d=_D1)
        d2_row = _opp_row("M1", pnl_pct=0.10, d=_D2)
        _apply_opportunity_pool(
            [d1_row, d2_row], [_M1], initial_pool=1_000.0,
            compound=False, doubledown_start_min=_DD_START_MIN,
        )

        assert d1_row["opp_deployed"] == pytest.approx(1_000.0)
        assert d2_row["opp_deployed"] == pytest.approx(1_000.0)

    def test_compound_day2_deploys_day1_returned_balance(self):
        d1_row = _opp_row("M1", pnl_pct=0.10, d=_D1)
        d2_row = _opp_row("M1", pnl_pct=0.10, d=_D2)
        _apply_opportunity_pool(
            [d1_row, d2_row], [_M1], initial_pool=1_000.0,
            compound=True, doubledown_start_min=_DD_START_MIN,
        )

        assert d1_row["opp_returned"] == pytest.approx(1_100.0)
        assert d2_row["opp_deployed"] == pytest.approx(1_100.0)

    def test_pool_floored_at_zero_after_total_loss(self):
        # Day 1: 100% loss → opp_returned=0 → Day 2 pool=0 → no deployment
        d1_row = _opp_row("M1", pnl_pct=-1.0, d=_D1)
        d2_row = _opp_row("M1", pnl_pct=0.10, d=_D2)
        _apply_opportunity_pool(
            [d1_row, d2_row], [_M1], initial_pool=1_000.0,
            compound=True, doubledown_start_min=_DD_START_MIN,
        )

        assert d1_row["opp_returned"] == pytest.approx(0.0)
        assert "opp_cap_pnl" not in d2_row

    def test_no_op_when_initial_pool_is_zero(self):
        row = _opp_row("M1", pnl_pct=0.10)
        _apply_opportunity_pool([row], [_M1], initial_pool=0.0, doubledown_start_min=_DD_START_MIN)

        assert "opp_cap_pnl" not in row

    def test_loss_deployment_records_negative_opp_cap_pnl(self):
        row = _opp_row("M1", pnl_pct=-0.05)
        _apply_opportunity_pool([row], [_M1], initial_pool=1_000.0, doubledown_start_min=_DD_START_MIN)

        assert row["opp_cap_pnl"] == pytest.approx(-50.0)
        assert row["opp_returned"] == pytest.approx(950.0)

    def test_winner_with_insufficient_bars_held_is_skipped(self):
        # bars_held=0 < dd_bars=1 → winner exited before DD fires → no deployment
        row = _opp_row("M1", bars_held=0, pnl_pct=0.10)
        _apply_opportunity_pool([row], [_M1], initial_pool=1_000.0, doubledown_start_min=_DD_START_MIN)

        assert "opp_cap_pnl" not in row


# ---------------------------------------------------------------------------
# _print_reentry_subrow — sub-leg entry/exit time display
# ---------------------------------------------------------------------------

def _fmt(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _sub_row(
    or_close_min,
    primary_bars,
    ep_key,
    ep,
    pnl_key,
    pnl,
    exit_price_key,
    exit_price,
    exit_reason_key,
    exit_reason,
    entry_idx_key,
    entry_idx,
    bars_held_key,
    bars_held,
):
    return {
        "or_close_min": or_close_min,
        "bars_held": primary_bars,
        ep_key: ep,
        pnl_key: pnl,
        exit_price_key: exit_price,
        exit_reason_key: exit_reason,
        entry_idx_key: entry_idx,
        bars_held_key: bars_held,
    }


class TestPrintReentrySubrowTimes:
    # or_close_min=585 (09:45) for M1 09:30/3-bar window

    def test_bru_entry_time_one_bar_after_primary_exit(self, capsys):
        # Primary holds 0 bars (exits at first bar = 09:50).
        # BRU entry_idx=0: fires on the very first scan bar → entry = 09:55.
        row = _sub_row(
            or_close_min=585, primary_bars=0,
            ep_key="bru_entry_price", ep=100.0,
            pnl_key="bru_pnl", pnl=2.0,
            exit_price_key="bru_exit_price", exit_price=102.0,
            exit_reason_key="bru_exit_reason", exit_reason="trailing_stop_ma20",
            entry_idx_key="bru_entry_idx", entry_idx=0,
            bars_held_key="bru_bars_held", bars_held=0,
        )
        _print_reentry_subrow(
            row, "[BRU]",
            "bru_entry_price", "bru_pnl", "bru_exit_price", "bru_exit_reason",
            "bru_entry_idx", "bru_bars_held",
            multi_window=False, fmt_bar_time=_fmt,
        )
        out = capsys.readouterr().out
        # primary exits at 09:50, BRU entry_idx=0 → entry bar is the one right after → 09:55
        assert "09:55" in out
        # BRU bars_held=0 → exits one bar later at 10:00
        assert "10:00" in out

    def test_bru_entry_delayed_by_entry_idx(self, capsys):
        # Primary holds 2 bars (exits at 10:00). BRU entry_idx=3 (fires 3 bars into scan).
        # sub_entry = 585 + (2 + 3 + 2) * 5 = 585 + 35 = 620 → 10:20
        row = _sub_row(
            or_close_min=585, primary_bars=2,
            ep_key="bru_entry_price", ep=200.0,
            pnl_key="bru_pnl", pnl=-4.0,
            exit_price_key="bru_exit_price", exit_price=196.0,
            exit_reason_key="bru_exit_reason", exit_reason="hard_stop",
            entry_idx_key="bru_entry_idx", entry_idx=3,
            bars_held_key="bru_bars_held", bars_held=1,
        )
        _print_reentry_subrow(
            row, "[BRU]",
            "bru_entry_price", "bru_pnl", "bru_exit_price", "bru_exit_reason",
            "bru_entry_idx", "bru_bars_held",
            multi_window=False, fmt_bar_time=_fmt,
        )
        out = capsys.readouterr().out
        assert "10:20" in out
        # exit: 620 + (1+1)*5 = 630 → 10:30
        assert "10:30" in out

    def test_bre_end_of_day_shows_eod_display_time(self, capsys):
        # BRE that runs to end of day should show _EOD_DISPLAY_TIME (15:50) for exit.
        row = _sub_row(
            or_close_min=585, primary_bars=0,
            ep_key="br_entry_price", ep=150.0,
            pnl_key="br_pnl", pnl=3.0,
            exit_price_key="br_exit_price", exit_price=153.0,
            exit_reason_key="br_exit_reason", exit_reason="end_of_day",
            entry_idx_key="br_entry_idx", entry_idx=0,
            bars_held_key="br_bars_held", bars_held=50,
        )
        _print_reentry_subrow(
            row, "[BRE]",
            "br_entry_price", "br_pnl", "br_exit_price", "br_exit_reason",
            "br_entry_idx", "br_bars_held",
            multi_window=False, fmt_bar_time=_fmt,
        )
        out = capsys.readouterr().out
        assert "15:50" in out

    def test_rev_afternoon_window_entry_time(self, capsys):
        # A2 window 13:15/1-bar: or_close_min = 13*60+15+5 = 800 (13:20).
        # Primary bars_held=0 exits at 13:25. REV entry_idx=1 → entry at 13:35.
        row = _sub_row(
            or_close_min=800, primary_bars=0,
            ep_key="rev_entry_price", ep=190.0,
            pnl_key="rev_pnl", pnl=1.5,
            exit_price_key="rev_exit_price", exit_price=191.5,
            exit_reason_key="rev_exit_reason", exit_reason="trailing_stop_ma20",
            entry_idx_key="rev_entry_idx", entry_idx=1,
            bars_held_key="rev_bars_held", bars_held=2,
        )
        _print_reentry_subrow(
            row, "[REV]",
            "rev_entry_price", "rev_pnl", "rev_exit_price", "rev_exit_reason",
            "rev_entry_idx", "rev_bars_held",
            multi_window=False, fmt_bar_time=_fmt,
        )
        out = capsys.readouterr().out
        # sub_entry = 800 + (0 + 1 + 2) * 5 = 815 → 13:35
        assert "13:35" in out
        # sub_exit = 815 + (2+1)*5 = 830 → 13:50
        assert "13:50" in out

    def test_cancelled_subrow_shows_entry_time_not_exit(self, capsys):
        # Cancelled sub-leg should show the pending entry time but no exit time.
        row = {
            "or_close_min": 585,
            "bars_held": 0,
            "bru_entry_price": 100.0,
            "bru_entry_idx": 0,
            "bru_bars_held": 0,
            "bru_pnl": 0.0,
            "bru_exit_price": 0.0,
            "bru_exit_reason": "",
            "bru_cancelled": True,
        }
        _print_reentry_subrow(
            row, "[BRU]",
            "bru_entry_price", "bru_pnl", "bru_exit_price", "bru_exit_reason",
            "bru_entry_idx", "bru_bars_held",
            multi_window=False, fmt_bar_time=_fmt,
        )
        out = capsys.readouterr().out
        assert "09:55" in out
        assert "cancelled" in out

    def test_missing_entry_price_prints_nothing(self, capsys):
        # Row with no sub-leg entry price → function returns None and prints nothing.
        row = {"or_close_min": 585, "bars_held": 0, "bru_entry_price": 0}
        result = _print_reentry_subrow(
            row, "[BRU]",
            "bru_entry_price", "bru_pnl", "bru_exit_price", "bru_exit_reason",
            "bru_entry_idx", "bru_bars_held",
            multi_window=False, fmt_bar_time=_fmt,
        )
        assert result is None
        assert capsys.readouterr().out == ""


# ---------------------------------------------------------------------------
# DD entry/exit time display (via _print_daily_table)
# ---------------------------------------------------------------------------

def _dd_trade_row(or_close_min, bars_held, exit_reason, dd_fire_min, signal="BULLISH"):
    """Minimal trade row that triggers a [DD] sub-row in _print_daily_table."""
    return {
        "date": _D1,
        "window": "W1",
        "rank": 1,
        "ticker": "TST",
        "signal": signal,
        "score": 1.0,
        "or_close_min": or_close_min,
        "entry_price": 100.0,
        "exit_price": 102.0,
        "pnl": 2.0,
        "exit_reason": exit_reason,
        "bars_held": bars_held,
        "cap_pnl": 20.0,
        "skipped": False,
        "dd_addon_cap_pnl": 5.0,
        "dd_addon_entry": 101.0,
        "dd_addon_effective_exit": 103.0,
        "dd_freed_capital": 4000.0,
        "dd_freed_ranks": [2],
        "dd_fire_min": dd_fire_min,
    }


class TestDDSubrowTimes:
    def test_dd_in_time_matches_dd_fire_min(self, capsys):
        # DD fires at 09:55 (585 + 10 min = 595). Primary exits at 10:25 (bars_held=7).
        row = _dd_trade_row(or_close_min=585, bars_held=7, exit_reason="trailing_stop_ma20", dd_fire_min=595)
        _print_daily_table([row], n=1, multi_window=False)
        out = capsys.readouterr().out
        assert "09:55" in out
        # exit = 585 + (7+1)*5 = 625 → 10:25
        assert "10:25" in out

    def test_dd_out_time_is_eod_display_time_when_end_of_day(self, capsys):
        # DD fires at 10:00; primary holds to EOD — exit display should be 15:50.
        row = _dd_trade_row(or_close_min=585, bars_held=50, exit_reason="end_of_day", dd_fire_min=600)
        _print_daily_table([row], n=1, multi_window=False)
        out = capsys.readouterr().out
        assert "10:00" in out
        assert "15:50" in out

    def test_dd_in_out_aligned_with_primary_columns(self, capsys):
        # Both the primary row and [DD] sub-row must have In/Out values in their output.
        row = _dd_trade_row(or_close_min=800, bars_held=3, exit_reason="hard_stop", dd_fire_min=810)
        _print_daily_table([row], n=1, multi_window=False)
        out = capsys.readouterr().out
        lines = [l for l in out.splitlines() if "[DD]" in l]
        assert len(lines) == 1
        # 13:30 (dd_fire_min=810) and 13:40 (exit = 800+(3+1)*5=820)
        assert "13:30" in lines[0]
        assert "13:40" in lines[0]


# ---------------------------------------------------------------------------
# _compute_rolling_stats
# ---------------------------------------------------------------------------
#
# Verifies the helper slices trade history to [lookback_start, d) (exclusive of d)
# and returns correct stats per ticker.  Uses small in-memory DataFrames — no
# file I/O or bar fetching required.
# ---------------------------------------------------------------------------

_RS_D = date(2024, 6, 1)   # the "today" date (exclusive upper bound)
_RS_LB = date(2024, 5, 1)  # lookback start


def _results_df(rows):
    """Build a minimal primary-results DataFrame from a list of dicts."""
    return pd.DataFrame(rows)


def _win_row(d, ticker="AMD", entry=100.0, pnl=1.0, signal="BULLISH"):
    return {
        "date": d,
        "ticker": ticker,
        "entry_price": entry,
        "pnl": pnl,
        "success": True,
        "signal": signal,
        "midpoint": entry * 0.99,
        "or_range_pct": 0.5,
    }


def _loss_row(d, ticker="AMD", entry=100.0, pnl=-0.5, signal="BULLISH"):
    return {
        "date": d,
        "ticker": ticker,
        "entry_price": entry,
        "pnl": pnl,
        "success": False,
        "signal": signal,
        "midpoint": entry * 0.99,
        "or_range_pct": 0.5,
    }


class TestComputeRollingStats:
    def test_returns_stats_for_each_ticker(self):
        data = {
            "AMD":  _results_df([_win_row(_RS_D - pd.Timedelta(days=5))]),
            "TSLA": _results_df([_loss_row(_RS_D - pd.Timedelta(days=5))]),
        }
        stats = _compute_rolling_stats(["AMD", "TSLA"], _RS_LB, _RS_D, data, ev_trend_days=15)

        assert set(stats.keys()) == {"AMD", "TSLA"}

    def test_excludes_rows_on_or_after_eval_date(self):
        # Row on _RS_D itself must not count — window is [lookback_start, d).
        data = {
            "AMD": _results_df([
                _win_row(_RS_D - pd.Timedelta(days=1)),  # included
                _win_row(_RS_D),                          # excluded (today)
            ]),
        }
        stats = _compute_rolling_stats(["AMD"], _RS_LB, _RS_D, data, ev_trend_days=15)

        assert stats["AMD"]["signals"] == 1

    def test_excludes_rows_before_lookback_start(self):
        # Row before _RS_LB must not count.
        data = {
            "AMD": _results_df([
                _win_row(_RS_LB - pd.Timedelta(days=1)),  # excluded (too old)
                _win_row(_RS_LB),                          # included (on boundary)
            ]),
        }
        stats = _compute_rolling_stats(["AMD"], _RS_LB, _RS_D, data, ev_trend_days=15)

        assert stats["AMD"]["signals"] == 1

    def test_empty_history_returns_zero_ev(self):
        stats = _compute_rolling_stats(["AMD"], _RS_LB, _RS_D, {}, ev_trend_days=15)

        assert stats["AMD"]["ev_trade"] == 0.0
        assert stats["AMD"]["signals"] == 0

    def test_all_wins_produces_positive_ev(self):
        data = {
            "AMD": _results_df([
                _win_row(_RS_D - pd.Timedelta(days=i)) for i in range(1, 6)
            ]),
        }
        stats = _compute_rolling_stats(["AMD"], _RS_LB, _RS_D, data, ev_trend_days=15)

        assert stats["AMD"]["ev_trade"] > 0.0
        assert stats["AMD"]["win_rate"] == pytest.approx(1.0)

    def test_all_losses_produces_negative_ev(self):
        data = {
            "AMD": _results_df([
                _loss_row(_RS_D - pd.Timedelta(days=i)) for i in range(1, 6)
            ]),
        }
        stats = _compute_rolling_stats(["AMD"], _RS_LB, _RS_D, data, ev_trend_days=15)

        assert stats["AMD"]["ev_trade"] < 0.0
        assert stats["AMD"]["win_rate"] == pytest.approx(0.0)

    def test_shorter_lookback_window_excludes_older_trades(self):
        # 5-day lookback vs 30-day lookback: only the last 5 days' trade should differ.
        old_win = _win_row(_RS_D - pd.Timedelta(days=20))
        recent_loss = _loss_row(_RS_D - pd.Timedelta(days=2))
        data = {"AMD": _results_df([old_win, recent_loss])}

        lb_30 = _RS_D - pd.Timedelta(days=30)
        lb_5  = _RS_D - pd.Timedelta(days=5)

        stats_30 = _compute_rolling_stats(["AMD"], lb_30, _RS_D, data, ev_trend_days=15)
        stats_5  = _compute_rolling_stats(["AMD"], lb_5,  _RS_D, data, ev_trend_days=15)

        # 30-day window sees both rows (1 win + 1 loss); 5-day sees only the loss.
        assert stats_30["AMD"]["signals"] == 2
        assert stats_5["AMD"]["signals"] == 1
        assert stats_5["AMD"]["win_rate"] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Dynamic EV gate — pool vote regime classification
#
# Tests the regime-detection logic (bull / neutral / bear) and the percentile
# floor calculation, extracted into pure-function helpers that mirror what the
# daily loop does in run_selector_backtest().
# ---------------------------------------------------------------------------


def _pool_vote(rolling_stats):
    return sum(1 for s in rolling_stats.values() if s["ev_trade"] > 0)


def _dg_ev_floor(rolling_stats, regime, bull_pct, neutral_pct, bear_pct, min_ev=0.0):
    """Replicate the percentile-floor computation from the daily loop."""
    candidate_evs = sorted(
        s["ev_trade"] for s in rolling_stats.values() if s["ev_trade"] > min_ev
    )
    if regime == "bull":
        excl_pct = bull_pct
    elif regime == "bear":
        excl_pct = bear_pct
    else:
        excl_pct = neutral_pct
    if not candidate_evs:
        return min_ev
    cutoff_idx = int(len(candidate_evs) * excl_pct)
    return candidate_evs[cutoff_idx] if cutoff_idx < len(candidate_evs) else candidate_evs[-1]


def _make_rolling_stats(ev_values):
    """Build a rolling_stats dict from a list of EV floats, keyed T0..TN."""
    return {f"T{i}": {"ev_trade": v} for i, v in enumerate(ev_values)}


class TestDynamicEvGatePoolVote:
    def test_pool_vote_counts_only_positive_ev_tickers(self):
        stats = _make_rolling_stats([0.5, 0.3, -0.1, 0.0, 0.8])
        assert _pool_vote(stats) == 3  # 0.5, 0.3, 0.8 > 0

    def test_pool_vote_zero_when_all_negative(self):
        stats = _make_rolling_stats([-0.5, -0.2, -1.0])
        assert _pool_vote(stats) == 0

    def test_bull_regime_when_vote_at_or_above_threshold(self):
        # 10 positive-EV tickers → bull tier (threshold=10)
        stats = _make_rolling_stats([0.1] * 10 + [-0.1] * 4)
        vote = _pool_vote(stats)
        assert vote >= 10

    def test_bear_regime_when_vote_at_or_below_threshold(self):
        # 5 positive-EV tickers → bear tier (threshold=5)
        stats = _make_rolling_stats([0.1] * 5 + [-0.1] * 9)
        vote = _pool_vote(stats)
        assert vote <= 5

    def test_neutral_regime_between_thresholds(self):
        # 7 positive-EV tickers → neutral tier (bull≥10, bear≤5)
        stats = _make_rolling_stats([0.1] * 7 + [-0.1] * 7)
        vote = _pool_vote(stats)
        assert 5 < vote < 10


class TestDynamicEvGatePercentileFloor:
    # Pool: 10 positive-EV candidates with EV values 0.1, 0.2, ..., 1.0
    # sorted: [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]

    def _pool(self):
        ev_vals = [round(0.1 * i, 1) for i in range(1, 11)]   # 0.1 … 1.0
        ev_vals += [-0.5, -0.3]  # two negative-EV tickers (should be ignored)
        return _make_rolling_stats(ev_vals)

    def test_bear_regime_40pct_excludes_bottom_4_of_10(self):
        # cutoff_idx = int(10 * 0.40) = 4 → floor = sorted[4] = 0.5
        floor = _dg_ev_floor(self._pool(), "bear", 0.10, 0.25, 0.40)
        assert floor == pytest.approx(0.5)

    def test_neutral_regime_25pct_excludes_bottom_2_of_10(self):
        # cutoff_idx = int(10 * 0.25) = 2 → floor = sorted[2] = 0.3
        floor = _dg_ev_floor(self._pool(), "neutral", 0.10, 0.25, 0.40)
        assert floor == pytest.approx(0.3)

    def test_bull_regime_10pct_excludes_bottom_1_of_10(self):
        # cutoff_idx = int(10 * 0.10) = 1 → floor = sorted[1] = 0.2
        floor = _dg_ev_floor(self._pool(), "bull", 0.10, 0.25, 0.40)
        assert floor == pytest.approx(0.2)

    def test_negative_ev_tickers_not_counted_in_percentile(self):
        # Floor computed from 10 positive-EV candidates only, not the full 12-ticker pool.
        # If negatives were included, sorted[-] would shift the cutoff index downward.
        floor_with_negatives = _dg_ev_floor(self._pool(), "bear", 0.10, 0.25, 0.40)
        # Pool with only positive EVs (same 10, no negatives)
        pure_pool = _make_rolling_stats([round(0.1 * i, 1) for i in range(1, 11)])
        floor_pure = _dg_ev_floor(pure_pool, "bear", 0.10, 0.25, 0.40)
        assert floor_with_negatives == pytest.approx(floor_pure)

    def test_floor_above_zero_so_gate_is_stricter_than_min_ev(self):
        # The percentile floor should always be > 0 when there are positive-EV candidates,
        # meaning it is strictly tighter than the baseline min_ev=0 gate.
        floor = _dg_ev_floor(self._pool(), "bear", 0.10, 0.25, 0.40)
        assert floor > 0.0

    def test_zero_exclude_pct_admits_all_candidates(self):
        # With 0% exclusion, floor = sorted[0] = 0.1, i.e., all 10 candidates pass.
        floor = _dg_ev_floor(self._pool(), "bull", 0.0, 0.0, 0.0)
        assert floor == pytest.approx(0.1)

    def test_empty_candidate_pool_returns_min_ev(self):
        # All tickers have negative EV → no candidates → floor falls back to min_ev.
        all_negative = _make_rolling_stats([-0.5, -0.3, -0.1])
        floor = _dg_ev_floor(all_negative, "bear", 0.10, 0.25, 0.40)
        assert floor == pytest.approx(0.0)  # default min_ev


# ---------------------------------------------------------------------------
# Adaptive lookback — lookback-day selection by regime
#
# Tests the regime → lookback-days mapping, mirroring what the daily loop
# does in run_selector_backtest() when --adaptive-lookback is active.
# ---------------------------------------------------------------------------


def _al_days(pool_vote, bull_threshold, bear_threshold,
             bull_days, neutral_days, bear_days):
    """Replicate the adaptive-lookback day selection from the daily loop."""
    if pool_vote >= bull_threshold:
        return bull_days
    elif pool_vote <= bear_threshold:
        return bear_days
    return neutral_days


class TestAdaptiveLookbackDaySelection:
    _BULL_T = 10
    _BEAR_T = 5
    _BULL_D = 30
    _NEUTRAL_D = 60
    _BEAR_D = 90

    def _days(self, vote):
        return _al_days(vote, self._BULL_T, self._BEAR_T,
                        self._BULL_D, self._NEUTRAL_D, self._BEAR_D)

    def test_bull_vote_at_threshold_uses_bull_days(self):
        assert self._days(10) == 30

    def test_bull_vote_above_threshold_uses_bull_days(self):
        assert self._days(14) == 30

    def test_bear_vote_at_threshold_uses_bear_days(self):
        assert self._days(5) == 90

    def test_bear_vote_below_threshold_uses_bear_days(self):
        assert self._days(2) == 90

    def test_neutral_vote_uses_neutral_days(self):
        assert self._days(7) == 60

    def test_neutral_boundary_just_above_bear(self):
        assert self._days(6) == 60

    def test_neutral_boundary_just_below_bull(self):
        assert self._days(9) == 60

    def test_bull_lookback_shorter_than_neutral(self):
        assert self._days(12) < self._days(7)

    def test_bear_lookback_longer_than_neutral(self):
        assert self._days(3) > self._days(7)

    def test_shorter_lookback_in_bull_reflects_more_responsive_window(self):
        # The entire point of adaptive lookback: bull = recent signal matters more.
        # Verify the ordering: bull_days < neutral_days < bear_days.
        assert self._days(10) < self._days(7) < self._days(5)


# ---------------------------------------------------------------------------
# _qqq_regime_factor
# ---------------------------------------------------------------------------

class TestQqqRegimeFactor:
    """Tests for the QQQ MA bear-regime intensity tier helper."""

    def test_returns_zero_when_close_above_ma20(self):
        # Neutral regime — QQQ above MA20, no bear boost.
        assert _qqq_regime_factor(close=410.0, ma20=400.0, ma50=380.0,
                                  ma20_slope=2.0, ma50_slope=1.0) == 0.0

    def test_returns_zero_when_close_equals_ma20(self):
        assert _qqq_regime_factor(close=400.0, ma20=400.0, ma50=380.0,
                                  ma20_slope=1.0, ma50_slope=0.5) == 0.0

    def test_returns_0_33_when_below_ma20_above_ma50(self):
        # Mild bear: QQQ dipped below MA20 but still above MA50.
        assert _qqq_regime_factor(close=390.0, ma20=395.0, ma50=380.0,
                                  ma20_slope=-1.0, ma50_slope=0.5) == pytest.approx(0.33)

    def test_returns_0_67_when_below_ma50_mas_not_both_falling(self):
        # Moderate bear: QQQ below MA50 but MA50 slope still positive.
        assert _qqq_regime_factor(close=370.0, ma20=385.0, ma50=375.0,
                                  ma20_slope=-1.0, ma50_slope=0.5) == pytest.approx(0.67)

    def test_returns_1_0_when_below_ma50_and_both_mas_falling(self):
        # Full bear: QQQ below MA50 and both MAs trending down.
        assert _qqq_regime_factor(close=370.0, ma20=385.0, ma50=375.0,
                                  ma20_slope=-2.0, ma50_slope=-1.0) == pytest.approx(1.0)

    def test_full_only_returns_zero_for_mild_bear(self):
        # full_only collapses mild bear (0.33) to 0 — no false signal on brief dips.
        assert _qqq_regime_factor(close=390.0, ma20=395.0, ma50=380.0,
                                  ma20_slope=-1.0, ma50_slope=0.5,
                                  full_only=True) == 0.0

    def test_full_only_returns_zero_for_moderate_bear(self):
        # full_only collapses moderate bear (0.67) to 0 as well.
        assert _qqq_regime_factor(close=370.0, ma20=385.0, ma50=375.0,
                                  ma20_slope=-1.0, ma50_slope=0.5,
                                  full_only=True) == 0.0

    def test_full_only_returns_1_0_for_full_bear(self):
        assert _qqq_regime_factor(close=370.0, ma20=385.0, ma50=375.0,
                                  ma20_slope=-2.0, ma50_slope=-1.0,
                                  full_only=True) == pytest.approx(1.0)

    # --- 5-tier MA200 system ---

    def test_ma200_returns_0_25_when_below_ma20_above_ma50(self):
        # Warning tier: QQQ slipped under MA20 but still above MA50.
        assert _qqq_regime_factor(close=390.0, ma20=395.0, ma50=380.0,
                                  ma20_slope=-1.0, ma50_slope=0.5,
                                  ma200=320.0) == pytest.approx(0.25)

    def test_ma200_returns_0_55_when_below_ma50_above_ma200(self):
        # Acceleration zone: MA50 broken, move accelerating toward MA200.
        assert _qqq_regime_factor(close=370.0, ma20=385.0, ma50=375.0,
                                  ma20_slope=-2.0, ma50_slope=-0.5,
                                  ma200=320.0) == pytest.approx(0.55)

    def test_ma200_returns_0_75_when_below_ma200_mas_not_both_falling(self):
        # Deep bear but MA50 slope not yet negative — could be sluggish recovery.
        assert _qqq_regime_factor(close=310.0, ma20=375.0, ma50=365.0,
                                  ma20_slope=-2.0, ma50_slope=0.1,
                                  ma200=320.0) == pytest.approx(0.75)

    def test_ma200_returns_1_0_when_below_ma200_both_mas_falling(self):
        # True bear: QQQ below MA200 AND both MAs trending down.
        assert _qqq_regime_factor(close=310.0, ma20=375.0, ma50=365.0,
                                  ma20_slope=-3.0, ma50_slope=-1.5,
                                  ma200=320.0) == pytest.approx(1.0)

    def test_ma200_full_only_returns_zero_for_acceleration_zone(self):
        # full_only with MA200: below MA50 but above MA200 — not strict enough, returns 0.
        assert _qqq_regime_factor(close=370.0, ma20=385.0, ma50=375.0,
                                  ma20_slope=-2.0, ma50_slope=-0.5,
                                  full_only=True, ma200=320.0) == 0.0

    def test_ma200_full_only_returns_1_0_only_when_below_ma200_and_both_mas_falling(self):
        assert _qqq_regime_factor(close=310.0, ma20=375.0, ma50=365.0,
                                  ma20_slope=-3.0, ma50_slope=-1.5,
                                  full_only=True, ma200=320.0) == pytest.approx(1.0)

    def test_ma200_full_only_returns_zero_when_below_ma200_but_ma50_slope_positive(self):
        # Below MA200 but recovery starting — MA50 slope not yet negative, not full bear.
        assert _qqq_regime_factor(close=310.0, ma20=375.0, ma50=365.0,
                                  ma20_slope=-1.0, ma50_slope=0.2,
                                  full_only=True, ma200=320.0) == 0.0

    def test_ma200_nan_falls_back_to_4tier(self):
        # When MA200 is NaN (insufficient history), should use 4-tier logic.
        result = _qqq_regime_factor(close=370.0, ma20=385.0, ma50=375.0,
                                    ma20_slope=-2.0, ma50_slope=-1.0,
                                    ma200=float("nan"))
        assert result == pytest.approx(1.0)  # 4-tier full bear


# ---------------------------------------------------------------------------
# _compute_bear_ctp_dates
# ---------------------------------------------------------------------------

def _make_qqq_df(prices):
    """Build a minimal QQQ-like DataFrame with one bar per calendar day."""
    start = datetime(2020, 1, 2, 16, 0, 0, tzinfo=ET)
    idx = pd.DatetimeIndex([start + timedelta(days=i) for i in range(len(prices))])
    return pd.DataFrame({"Close": prices}, index=idx)


class TestComputeBearCtpDates:
    """Tests for _compute_bear_ctp_dates helper."""

    def test_returns_empty_set_for_empty_dataframe(self):
        result = _compute_bear_ctp_dates(
            pd.DataFrame(),
            qqq_regime_full_only=True,
            qqq_regime_ma200=False,
            qqq_regime_slope_days=5,
        )
        assert result == set()

    def test_returns_nonempty_set_in_prolonged_decline(self):
        # 65 days declining: MA50 is non-NaN from day 51; full-bear condition met.
        prices = [1000.0 - i * 5 for i in range(65)]
        df = _make_qqq_df(prices)
        result = _compute_bear_ctp_dates(
            df,
            qqq_regime_full_only=True,
            qqq_regime_ma200=False,
            qqq_regime_slope_days=5,
        )
        assert len(result) > 0

    def test_ma_cross_gate_is_subset_of_base_result(self):
        # In a sustained decline MA20 < MA50 throughout, so gate changes nothing.
        # Result with gate ⊆ result without gate (and equal in this scenario).
        prices = [1000.0 - i * 5 for i in range(65)]
        df = _make_qqq_df(prices)
        base = _compute_bear_ctp_dates(
            df,
            qqq_regime_full_only=True,
            qqq_regime_ma200=False,
            qqq_regime_slope_days=5,
            qqq_regime_bear_ctp_ma_cross=False,
        )
        gated = _compute_bear_ctp_dates(
            df,
            qqq_regime_full_only=True,
            qqq_regime_ma200=False,
            qqq_regime_slope_days=5,
            qqq_regime_bear_ctp_ma_cross=True,
        )
        assert gated.issubset(base)

    def test_ma_cross_gate_excludes_dates_when_ma20_above_ma50(self):
        # Series: 50 flat days then 30 strong rally days.
        # During rally, MA20 > MA50 because recent prices are higher.
        # With gate enabled, rally-phase eval dates should be excluded.
        prices = [100.0] * 50 + [100.0 + i * 10 for i in range(30)]
        df = _make_qqq_df(prices)

        _patch = "alpha_tech_tracker.op_momentum_strategy.op_momentum_selector_backtest._qqq_regime_factor"
        with unittest.mock.patch(_patch, return_value=1.0):
            base = _compute_bear_ctp_dates(
                df,
                qqq_regime_full_only=True,
                qqq_regime_ma200=False,
                qqq_regime_slope_days=5,
                qqq_regime_bear_ctp_ma_cross=False,
            )
            gated = _compute_bear_ctp_dates(
                df,
                qqq_regime_full_only=True,
                qqq_regime_ma200=False,
                qqq_regime_slope_days=5,
                qqq_regime_bear_ctp_ma_cross=True,
            )
        # Gate must exclude at least some rally-phase dates where MA20 > MA50.
        assert len(gated) < len(base)
        assert gated.issubset(base)

    def test_ma_cross_gate_passes_all_dates_when_ma20_below_ma50(self):
        # Use a declining-only series; in a sustained decline MA20 < MA50 always.
        # Gate should filter nothing — result with gate equals result without gate.
        prices = [1000.0 - i * 5 for i in range(65)]
        df = _make_qqq_df(prices)

        _patch = "alpha_tech_tracker.op_momentum_strategy.op_momentum_selector_backtest._qqq_regime_factor"
        with unittest.mock.patch(_patch, return_value=1.0):
            base = _compute_bear_ctp_dates(
                df,
                qqq_regime_full_only=True,
                qqq_regime_ma200=False,
                qqq_regime_slope_days=5,
                qqq_regime_bear_ctp_ma_cross=False,
            )
            gated = _compute_bear_ctp_dates(
                df,
                qqq_regime_full_only=True,
                qqq_regime_ma200=False,
                qqq_regime_slope_days=5,
                qqq_regime_bear_ctp_ma_cross=True,
            )
        assert gated == base

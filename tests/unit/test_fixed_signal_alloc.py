"""
Tests for the fixed-per-signal capital allocation mode.

Covers:
  - _effective_weights: fixed=True skips renormalization; idle capital stays idle
  - _apply_capital_flow: fixed_signal_alloc=True uses fixed slot sizes
  - slot_capital values are correct for 1, 3, and 8 signals against top-8 config
  - full top-N (8/8 signals): fixed and current produce identical results
  - compound mode still works correctly with fixed allocation
  - sequential windows respect fixed slot sizing in each window
"""


from alpha_tech_tracker.op_momentum_strategy.op_momentum_selector_backtest import (
    _apply_capital_flow,
    _effective_weights,
)

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_W1 = {"label": "W1", "opening_start": "09:30", "opening_bars": 3}
_W2 = {"label": "W2", "opening_start": "13:15", "opening_bars": 1}

_EQUAL_8 = [1 / 8] * 8   # equal weights for top-8 config
_CAPITAL = 10_000.0


def _row(window, rank, entry=100.0, pnl=0.0, date="2025-01-02"):
    return {
        "date": date,
        "window": window,
        "rank": rank,
        "entry_price": entry,
        "pnl": pnl,
    }


# ---------------------------------------------------------------------------
# _effective_weights — fixed=True
# ---------------------------------------------------------------------------


class TestEffectiveWeightsFixed:
    def test_fewer_picks_no_renormalization(self):
        result = _effective_weights(_EQUAL_8, n_picks=3, fixed=True)
        assert len(result) == 3
        assert all(abs(w - 1 / 8) < 1e-9 for w in result)

    def test_fewer_picks_weights_do_not_sum_to_one(self):
        result = _effective_weights(_EQUAL_8, n_picks=3, fixed=True)
        assert abs(sum(result) - 1.0) > 0.1

    def test_single_pick_slot_is_one_eighth_not_full(self):
        result = _effective_weights(_EQUAL_8, n_picks=1, fixed=True)
        assert len(result) == 1
        assert abs(result[0] - 1 / 8) < 1e-9

    def test_full_top_n_same_as_current_behavior(self):
        fixed = _effective_weights(_EQUAL_8, n_picks=8, fixed=True)
        current = _effective_weights(_EQUAL_8, n_picks=8, fixed=False)
        assert fixed == current

    def test_zero_picks_returns_original_weights(self):
        result = _effective_weights(_EQUAL_8, n_picks=0, fixed=True)
        assert result == _EQUAL_8


# ---------------------------------------------------------------------------
# _effective_weights — fixed=False (existing behavior must be unchanged)
# ---------------------------------------------------------------------------


class TestEffectiveWeightsCurrentUnchanged:
    def test_fewer_picks_renormalizes_to_sum_one(self):
        result = _effective_weights(_EQUAL_8, n_picks=3, fixed=False)
        assert abs(sum(result) - 1.0) < 1e-9

    def test_single_pick_gets_full_weight(self):
        result = _effective_weights(_EQUAL_8, n_picks=1, fixed=False)
        assert abs(result[0] - 1.0) < 1e-9


# ---------------------------------------------------------------------------
# _apply_capital_flow — fixed_signal_alloc=True, slot sizes
# ---------------------------------------------------------------------------


class TestApplyCapitalFlowFixedSlotSizes:
    def test_single_signal_slot_is_one_eighth_of_capital(self):
        rows = [_row("W1", rank=1, entry=100.0, pnl=0.0)]
        _apply_capital_flow(
            rows, [_W1], _CAPITAL, _EQUAL_8, 8, fixed_signal_alloc=True
        )
        assert abs(rows[0]["slot_capital"] - _CAPITAL / 8) < 1e-6

    def test_three_signals_each_slot_is_one_eighth(self):
        rows = [
            _row("W1", rank=1, entry=100.0, pnl=0.0),
            _row("W1", rank=2, entry=100.0, pnl=0.0),
            _row("W1", rank=3, entry=100.0, pnl=0.0),
        ]
        _apply_capital_flow(
            rows, [_W1], _CAPITAL, _EQUAL_8, 8, fixed_signal_alloc=True
        )
        for row in rows:
            assert abs(row["slot_capital"] - _CAPITAL / 8) < 1e-6

    def test_full_top_n_slots_match_current_behavior(self):
        rows_fixed = [_row("W1", rank=i + 1, entry=100.0, pnl=2.0) for i in range(8)]
        rows_current = [_row("W1", rank=i + 1, entry=100.0, pnl=2.0) for i in range(8)]
        _apply_capital_flow(
            rows_fixed, [_W1], _CAPITAL, _EQUAL_8, 8, fixed_signal_alloc=True
        )
        _apply_capital_flow(
            rows_current, [_W1], _CAPITAL, _EQUAL_8, 8, fixed_signal_alloc=False
        )
        for f, c in zip(rows_fixed, rows_current):
            assert abs(f["slot_capital"] - c["slot_capital"]) < 1e-6


# ---------------------------------------------------------------------------
# _apply_capital_flow — fixed_signal_alloc=True, cap_pnl values
# ---------------------------------------------------------------------------


class TestApplyCapitalFlowFixedCapPnl:
    def test_single_signal_cap_pnl_uses_fixed_slot(self):
        # entry=100, pnl=5 (5% move), slot=$1250 → cap_pnl = 1250/100*5 = 62.50
        rows = [_row("W1", rank=1, entry=100.0, pnl=5.0)]
        _apply_capital_flow(
            rows, [_W1], _CAPITAL, _EQUAL_8, 8, fixed_signal_alloc=True
        )
        expected = (_CAPITAL / 8) / 100.0 * 5.0
        assert abs(rows[0]["cap_pnl"] - expected) < 1e-6

    def test_three_signals_total_cap_pnl_is_three_fixed_slots(self):
        # 3 positions, each entry=100, pnl=10 → each cap_pnl = 1250/100*10 = 125
        rows = [_row("W1", rank=i + 1, entry=100.0, pnl=10.0) for i in range(3)]
        _apply_capital_flow(
            rows, [_W1], _CAPITAL, _EQUAL_8, 8, fixed_signal_alloc=True
        )
        slot = _CAPITAL / 8
        expected_each = slot / 100.0 * 10.0
        for row in rows:
            assert abs(row["cap_pnl"] - expected_each) < 1e-6

    def test_fixed_cap_pnl_lower_than_current_for_few_signals(self):
        # With 1 signal: current gives full $10k slot, fixed gives $1250 slot
        rows_fixed = [_row("W1", rank=1, entry=100.0, pnl=5.0)]
        rows_current = [_row("W1", rank=1, entry=100.0, pnl=5.0)]
        _apply_capital_flow(
            rows_fixed, [_W1], _CAPITAL, _EQUAL_8, 8, fixed_signal_alloc=True
        )
        _apply_capital_flow(
            rows_current, [_W1], _CAPITAL, _EQUAL_8, 8, fixed_signal_alloc=False
        )
        assert rows_fixed[0]["cap_pnl"] < rows_current[0]["cap_pnl"]

    def test_fixed_cap_pnl_equal_to_current_at_full_top_n(self):
        rows_fixed = [_row("W1", rank=i + 1, entry=100.0, pnl=3.0) for i in range(8)]
        rows_current = [_row("W1", rank=i + 1, entry=100.0, pnl=3.0) for i in range(8)]
        _apply_capital_flow(
            rows_fixed, [_W1], _CAPITAL, _EQUAL_8, 8, fixed_signal_alloc=True
        )
        _apply_capital_flow(
            rows_current, [_W1], _CAPITAL, _EQUAL_8, 8, fixed_signal_alloc=False
        )
        for f, c in zip(rows_fixed, rows_current):
            assert abs(f["cap_pnl"] - c["cap_pnl"]) < 1e-6


# ---------------------------------------------------------------------------
# _apply_capital_flow — default (fixed_signal_alloc=False) unchanged
# ---------------------------------------------------------------------------


class TestApplyCapitalFlowDefaultUnchanged:
    def test_single_signal_gets_full_capital_slot(self):
        rows = [_row("W1", rank=1, entry=100.0, pnl=0.0)]
        _apply_capital_flow(
            rows, [_W1], _CAPITAL, _EQUAL_8, 8, fixed_signal_alloc=False
        )
        assert abs(rows[0]["slot_capital"] - _CAPITAL) < 1e-6

    def test_three_signals_renormalized_to_full_capital(self):
        rows = [_row("W1", rank=i + 1, entry=100.0, pnl=0.0) for i in range(3)]
        _apply_capital_flow(
            rows, [_W1], _CAPITAL, _EQUAL_8, 8, fixed_signal_alloc=False
        )
        total_deployed = sum(r["slot_capital"] for r in rows)
        assert abs(total_deployed - _CAPITAL) < 1e-6


# ---------------------------------------------------------------------------
# _apply_capital_flow — compound mode with fixed allocation
# ---------------------------------------------------------------------------


class TestApplyCapitalFlowFixedCompound:
    def test_compound_grows_portfolio_across_days(self):
        rows = [
            _row("W1", rank=1, entry=100.0, pnl=10.0, date="2025-01-02"),
            _row("W1", rank=1, entry=100.0, pnl=10.0, date="2025-01-03"),
        ]
        _apply_capital_flow(
            rows, [_W1], _CAPITAL, _EQUAL_8, 8,
            compound=True, fixed_signal_alloc=True,
        )
        # Day 2 portfolio is larger → slot is proportionally larger
        assert rows[1]["slot_capital"] > rows[0]["slot_capital"]

    def test_no_compound_resets_slot_each_day(self):
        rows = [
            _row("W1", rank=1, entry=100.0, pnl=10.0, date="2025-01-02"),
            _row("W1", rank=1, entry=100.0, pnl=10.0, date="2025-01-03"),
        ]
        _apply_capital_flow(
            rows, [_W1], _CAPITAL, _EQUAL_8, 8,
            compound=False, fixed_signal_alloc=True,
        )
        assert abs(rows[0]["slot_capital"] - rows[1]["slot_capital"]) < 1e-6


# ---------------------------------------------------------------------------
# _apply_capital_flow — sequential windows with fixed allocation
# ---------------------------------------------------------------------------


class TestApplyCapitalFlowFixedSequential:
    def test_sequential_window_slot_uses_fixed_fraction_of_available(self):
        # W1 fires 1 signal (rank-1), W2 fires 1 signal (rank-1)
        # W2 available = initial + W1 cap_pnl; slot = available / 8
        rows = [
            _row("W1", rank=1, entry=100.0, pnl=8.0),   # W1 gains some P&L
            _row("W2", rank=1, entry=100.0, pnl=0.0),
        ]
        _apply_capital_flow(
            rows, [_W1, _W2], _CAPITAL, _EQUAL_8, 8,
            morning_split=[1.0], fixed_signal_alloc=True,
        )
        w1_cap_pnl = rows[0]["cap_pnl"]
        expected_w2_slot = (_CAPITAL + w1_cap_pnl) / 8
        assert abs(rows[1]["slot_capital"] - expected_w2_slot) < 1e-6

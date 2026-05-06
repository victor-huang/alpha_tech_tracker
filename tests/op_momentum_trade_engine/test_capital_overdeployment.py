"""Regression tests for capital over-deployment bugs.

Captures the 2026-05-05 incident where M1 deployed $16,100 against a $10,000 cap
because the position sizer rounded a too-small slot budget up to 1 contract,
and A1 then deployed an additional $7,280 because the sequential window budget
formula assumed M1 had spent only its slot allocation.

Three independent guards are tested:
  1. PositionSizer rejects when the slot budget can't fund a single contract.
  2. _get_window_budget subtracts actual open primary capital from the formula.
  3. _enter_position aborts if the new position would exceed total available capital.
"""

import threading
from unittest.mock import Mock, patch

import pytest

from alpha_tech_tracker.op_momentum_strategy.models import (
    ActivePosition,
    SignalEvent,
    WindowConfig,
)
from alpha_tech_tracker.op_momentum_strategy.position_sizer import (
    InsufficientSlotBudgetError,
    PositionSizer,
)
from alpha_tech_tracker.op_momentum_strategy.trade_engine import OpMomentumTradeEngine

from conftest import _D, _make_alpaca_client, _make_option_quote


_OPTION_CONTRACT_SELECTOR_PATH = (
    "alpha_tech_tracker.op_momentum_strategy.trade_engine"
    ".ITMOptionContractSelector.select"
)
_POSITION_SIZER_PATH = (
    "alpha_tech_tracker.op_momentum_strategy.trade_engine.PositionSizer.compute"
)
_PLACE_ENTRY_PATH = (
    "alpha_tech_tracker.op_momentum_strategy.trade_engine"
    ".OpMomentumTradeEngine._place_entry"
)


def _make_open_position(
    ticker, contracts, entry_fill_price, slot_capital, window_label="M1"
):
    pos = ActivePosition(
        ticker=ticker,
        signal="BULLISH",
        option_symbol=f"{ticker}260508C00100000",
        entry_order_id=f"order-{ticker}",
        contracts=contracts,
        entry_stock_price=_D("100"),
        or_high=_D("105"),
        or_low=_D("95"),
        or_range=_D("10"),
        hard_stop_price=_D("96"),
        fallback_price=_D("96"),
        window_label=window_label,
        slot_capital=_D(str(slot_capital)),
    )
    pos.entry_fill_price = _D(str(entry_fill_price))
    return pos


def _make_signal_event(ticker="SNDK"):
    return SignalEvent(
        ticker=ticker,
        signal="BULLISH",
        entry_price=_D("1335.99"),
        stock_price=_D("1335.99"),
        or_high=_D("1340.72"),
        or_low=_D("1286.13"),
        or_range=_D("54.59"),
        ma50_at_signal=_D("1300.00"),
    )


class TestPositionSizerSlotBudgetCap:
    """Guard #1 — PositionSizer must refuse to size when one contract > slot budget."""

    def test_raises_when_slot_budget_too_small_for_one_contract(self):
        # Reproduces 2026-05-05 SNDK: weight=0.40, window_budget=$10,000 → slot=$4,000.
        # Option mid=$102.35 → 1 contract = $10,235 > $4,000.
        client = _make_alpaca_client()
        client.get_accounts.return_value = {"buying_power": 100000.0}
        client.get_option_quote_by_occ.return_value = _make_option_quote(
            bid=102.30, ask=102.40
        )

        sizer = PositionSizer(client)
        with pytest.raises(InsufficientSlotBudgetError, match="slot budget"):
            sizer.compute(
                "SNDK260508C01260000",
                capital_weight=_D("0.40"),
                window_budget=_D("10000"),
            )

    def test_raises_when_slot_budget_too_small_combined_with_weight(self):
        # Option costs $5,000/contract; weight=0.20 of $10,000 = $2,000 slot.
        client = _make_alpaca_client()
        client.get_accounts.return_value = {"buying_power": 100000.0}
        client.get_option_quote_by_occ.return_value = _make_option_quote(
            bid=49.50, ask=50.50
        )

        sizer = PositionSizer(client)
        with pytest.raises(InsufficientSlotBudgetError, match="slot budget"):
            sizer.compute(
                "AMD260508C00350000",
                capital_weight=_D("0.20"),
                window_budget=_D("10000"),
            )

    def test_account_budget_path_keeps_one_contract_floor(self):
        # No window_budget — engine is sizing from full account; existing buying-power
        # check guards this path. The slot-budget guard must NOT fire here.
        client = _make_alpaca_client()
        client.get_accounts.return_value = {"buying_power": 100000.0}
        client.get_option_quote_by_occ.return_value = _make_option_quote(
            bid=102.30, ask=102.40
        )

        sizer = PositionSizer(client)
        contracts, _ = sizer.compute("SNDK260508C01260000")
        assert contracts >= 1


class TestSequentialWindowBudgetSubtractsOpenCapital:
    """Guard #2 — _get_window_budget must subtract actual open-position cost."""

    def _make_engine(self):
        client = _make_alpaca_client()
        client.get_accounts.return_value = {"buying_power": 100000.0}
        windows = [
            WindowConfig(label="M1", opening_start="09:30", opening_bars=3),
            WindowConfig(
                label="A1", opening_start="10:00", opening_bars=3, is_sequential=True
            ),
        ]
        engine = OpMomentumTradeEngine(
            alpaca_client=client, mock_trade_execution=True, windows=windows
        )
        engine._initial_capital = _D("10000")
        engine._monitor = Mock()
        engine._monitor._lock = threading.Lock()
        engine._monitor._positions = []
        return engine

    def test_subtracts_open_primary_capital_from_initial(self):
        engine = self._make_engine()
        # M1 has one open primary position costing $5,865 (3 COIN puts at $19.55).
        engine._monitor._positions = [
            _make_open_position("COIN", contracts=3, entry_fill_price=19.55,
                                slot_capital=6000),
        ]
        a1_win = next(w for w in engine._windows if w.label == "A1")

        budget = engine._get_window_budget(a1_win)

        # Available = initial $10,000 - open $5,865 = $4,135
        assert budget == _D("10000") - _D("3") * _D("19.55") * _D("100")

    def test_clamps_to_zero_when_overdeployed(self):
        # 2026-05-05 scenario: M1 deployed $16,100 (SNDK $10,235 + COIN $5,865)
        # against $10,000 initial. A1 budget must be $0, NOT $10,000.
        engine = self._make_engine()
        engine._monitor._positions = [
            _make_open_position("SNDK", contracts=1, entry_fill_price=102.35,
                                slot_capital=4000),
            _make_open_position("COIN", contracts=3, entry_fill_price=19.55,
                                slot_capital=6000),
        ]
        a1_win = next(w for w in engine._windows if w.label == "A1")

        budget = engine._get_window_budget(a1_win)

        assert budget == _D("0")

    def test_includes_realized_pnl_in_available_capital(self):
        engine = self._make_engine()
        engine._daily_realized_pnl = _D("2000")
        engine._monitor._positions = [
            _make_open_position("COIN", contracts=3, entry_fill_price=19.55,
                                slot_capital=6000),
        ]
        a1_win = next(w for w in engine._windows if w.label == "A1")

        budget = engine._get_window_budget(a1_win)

        # initial $10,000 + pnl $2,000 - open $5,865 = $6,135
        assert budget == _D("10000") + _D("2000") - _D("5865")

    def test_excludes_closed_positions(self):
        engine = self._make_engine()
        closed = _make_open_position("COIN", contracts=3, entry_fill_price=19.55,
                                     slot_capital=6000)
        closed.is_closed = True
        engine._monitor._positions = [closed]
        a1_win = next(w for w in engine._windows if w.label == "A1")

        budget = engine._get_window_budget(a1_win)

        assert budget == _D("10000")


class TestEnterPositionCapitalCap:
    """Guard #3 — _enter_position must abort if entry would exceed available capital."""

    def _make_engine(self):
        client = _make_alpaca_client()
        engine = OpMomentumTradeEngine(
            alpaca_client=client, mock_trade_execution=True
        )
        engine._initial_capital = _D("10000")
        engine._monitor = Mock()
        engine._monitor._lock = threading.Lock()
        engine._monitor._positions = []
        engine._monitor.add_position = Mock()
        engine._signal_engine = Mock()
        engine._signal_engine.get_latest_bar.return_value = None
        return engine

    def test_aborts_when_new_entry_exceeds_available_capital(self):
        engine = self._make_engine()
        # Existing open position consuming $9,000.
        engine._monitor._positions = [
            _make_open_position("COIN", contracts=3, entry_fill_price=30.00,
                                slot_capital=9000),
        ]
        # New entry would cost 1 × $102 × 100 = $10,200 — only $1,000 available.
        with patch(
            _OPTION_CONTRACT_SELECTOR_PATH, return_value="SNDK260508C01260000"
        ), patch(
            _POSITION_SIZER_PATH, return_value=(1, _D("102.00"))
        ), patch(_PLACE_ENTRY_PATH) as place_entry:
            placed = engine._enter_position(_make_signal_event("SNDK"), rank=0)

        assert placed is False
        place_entry.assert_not_called()

    def test_insufficient_slot_budget_logs_warning_without_stack_trace(self, caplog):
        # Mirrors the live "Insufficient slot budget for CRDO260508P00220000:
        # need $2840.00/contract, slot=$192.00" case — should surface as a clean
        # WARNING line, not as ERROR with a Traceback.
        import logging

        engine = self._make_engine()

        def _raise(*_a, **_kw):
            raise InsufficientSlotBudgetError(
                "Insufficient slot budget for CRDO260508P00220000:"
                " need $2840.00/contract, slot=$192.00"
            )

        with caplog.at_level(logging.WARNING), patch(
            _OPTION_CONTRACT_SELECTOR_PATH, return_value="CRDO260508P00220000"
        ), patch(_POSITION_SIZER_PATH, side_effect=_raise), patch(
            _PLACE_ENTRY_PATH
        ) as place_entry:
            placed = engine._enter_position(_make_signal_event("CRDO"), rank=0)

        assert placed is False
        place_entry.assert_not_called()
        relevant = [
            r for r in caplog.records if "Insufficient slot budget" in r.getMessage()
        ]
        assert relevant, "expected a slot-budget skip log line"
        assert all(r.levelno == logging.WARNING for r in relevant)
        assert all(r.exc_info is None for r in relevant)

    def test_allows_entry_within_available_capital(self):
        engine = self._make_engine()
        # No prior open positions — full $10,000 available.
        with patch(
            _OPTION_CONTRACT_SELECTOR_PATH, return_value="COIN260508P00220000"
        ), patch(
            _POSITION_SIZER_PATH, return_value=(3, _D("19.55"))
        ), patch(
            _PLACE_ENTRY_PATH,
            return_value={"order_id": "sim-1", "simulated_fill_mid": _D("19.55")},
        ) as place_entry:
            placed = engine._enter_position(_make_signal_event("COIN"), rank=0)

        assert placed is True
        place_entry.assert_called_once()


class TestDrainSlotFallback:
    """When an option doesn't fit a slot, advance to the next-ranked candidate
    instead of leaving the slot empty.
    """

    def _make_engine(self):
        from datetime import datetime, timedelta
        import pytz

        client = _make_alpaca_client()
        windows = [
            WindowConfig(
                label="M1", opening_start="09:30", opening_bars=3,
                capital_fraction=1.0,
            ),
        ]
        engine = OpMomentumTradeEngine(
            alpaca_client=client,
            mock_trade_execution=True,
            windows=windows,
            trade_type="options",
            rank_weights=[60, 40],
            top_n=2,
        )
        engine._initial_capital = _D("10000")
        engine._monitor = Mock()
        engine._monitor._lock = threading.Lock()
        engine._monitor._positions = []
        engine._signal_engine = Mock()
        engine._signal_engine.get_latest_bar.return_value = None
        # Drain runs after the deadline; pin it in the past so the loop fires.
        et = pytz.timezone("America/New_York")
        engine._window_state["M1"]["collection_deadline"] = (
            datetime.now(et) - timedelta(seconds=1)
        )
        # Stats picked so the score ordering is BIG > MID > SMALL when each
        # event has identical OR/entry params (avg_win_pct dominates).
        engine._rolling_stats_by_window = {
            "M1": {
                "BIG":   {"ev_trade": 1.0, "win_rate": 0.6, "avg_win_pct": 20.0},
                "MID":   {"ev_trade": 0.8, "win_rate": 0.5, "avg_win_pct": 10.0},
                "SMALL": {"ev_trade": 0.6, "win_rate": 0.5, "avg_win_pct": 5.0},
            },
        }
        engine._rolling_stats = engine._rolling_stats_by_window["M1"]
        return engine

    def _signal(self, ticker, entry):
        return SignalEvent(
            ticker=ticker,
            signal="BULLISH",
            entry_price=_D(str(entry)),
            stock_price=_D(str(entry)),
            or_high=_D(str(entry + 5)),
            or_low=_D(str(entry - 5)),
            or_range=_D("10"),
            ma50_at_signal=_D(str(entry)),
        )

    def test_falls_through_to_next_candidate_when_slot_too_small(self):
        # Score order: BIG > MID > SMALL. Slot 0 weight 60% × $10k = $6,000;
        # BIG's contract is rejected by the slot budget; MID at $3k fits slot
        # 0, SMALL at $2k fits slot 1.
        engine = self._make_engine()
        engine._window_state["M1"]["pending_signals"] = {
            "BIG":   self._signal("BIG", 100),
            "MID":   self._signal("MID", 100),
            "SMALL": self._signal("SMALL", 100),
        }

        def _select(ticker, signal, stock_price):
            return f"{ticker}260508C00010000"

        def _size(symbol, weight, window_budget, **kw):
            if symbol.startswith("BIG"):
                raise InsufficientSlotBudgetError("slot too small for BIG")
            if symbol.startswith("MID"):
                return (1, _D("30.00"))
            return (1, _D("20.00"))

        entered = []

        def _enter(event, rank, **kw):
            entered.append((rank, event.ticker))
            return True

        with patch(_OPTION_CONTRACT_SELECTOR_PATH, side_effect=_select), \
             patch(_POSITION_SIZER_PATH, side_effect=_size), \
             patch.object(engine, "_get_window_budget", return_value=_D("10000")), \
             patch.object(engine, "_enter_position", side_effect=_enter):
            engine._signal_selection_loop_for_window(engine._windows[0])

        assert entered == [(0, "MID"), (1, "SMALL")]

    def test_skips_slot_entirely_when_no_candidate_fits(self):
        engine = self._make_engine()
        engine._window_state["M1"]["pending_signals"] = {
            "BIG": self._signal("BIG", 100),
            "MID": self._signal("MID", 100),
        }

        def _select(ticker, signal, stock_price):
            return f"{ticker}260508C00010000"

        def _size(symbol, weight, window_budget, **kw):
            raise InsufficientSlotBudgetError(f"too small for {symbol}")

        entered = []

        def _enter(event, rank, **kw):
            entered.append((rank, event.ticker))
            return True

        with patch(_OPTION_CONTRACT_SELECTOR_PATH, side_effect=_select), \
             patch(_POSITION_SIZER_PATH, side_effect=_size), \
             patch.object(engine, "_get_window_budget", return_value=_D("10000")), \
             patch.object(engine, "_enter_position", side_effect=_enter):
            engine._signal_selection_loop_for_window(engine._windows[0])

        assert entered == []

    def test_falls_through_when_bankroll_cap_exceeded(self):
        # initial_capital $10k, but $9k already locked in an open position.
        # Slot 0 budget weight is $6k, but bankroll only has $1k free.
        # MID at $3k → exceeds bankroll. SMALL at $0.5k → fits.
        engine = self._make_engine()
        engine._monitor._positions = [
            _make_open_position("LOCK", contracts=3, entry_fill_price=30,
                                slot_capital=9000),
        ]
        engine._window_state["M1"]["pending_signals"] = {
            "MID":   self._signal("MID", 100),
            "SMALL": self._signal("SMALL", 100),
        }

        def _select(ticker, signal, stock_price):
            return f"{ticker}260508C00010000"

        def _size(symbol, weight, window_budget, **kw):
            if symbol.startswith("MID"):
                return (1, _D("30.00"))   # cost $3000 > available $1000
            return (1, _D("5.00"))        # cost $500 fits

        entered = []

        def _enter(event, rank, **kw):
            entered.append((rank, event.ticker))
            return True

        with patch(_OPTION_CONTRACT_SELECTOR_PATH, side_effect=_select), \
             patch(_POSITION_SIZER_PATH, side_effect=_size), \
             patch.object(engine, "_get_window_budget", return_value=_D("10000")), \
             patch.object(engine, "_enter_position", side_effect=_enter):
            engine._signal_selection_loop_for_window(engine._windows[0])

        assert entered == [(0, "SMALL")]

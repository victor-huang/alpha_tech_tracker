from datetime import date
from unittest.mock import MagicMock, patch

from alpha_tech_tracker.op_momentum_strategy.models import WindowConfig
from alpha_tech_tracker.op_momentum_strategy.trade_engine import OpMomentumTradeEngine

from conftest import _D, _make_alpaca_client

_TRADE_ENGINE_MOD = "alpha_tech_tracker.op_momentum_strategy.trade_engine"


def _make_engine(replay_capital=10000.0, windows=None):
    client = _make_alpaca_client()
    kwargs = dict(
        alpaca_client=client,
        mock_trade_execution=True,
        replay_capital=replay_capital,
    )
    if windows is not None:
        kwargs["windows"] = windows
    return OpMomentumTradeEngine(**kwargs)


def _run_replay_patched(engine, replay_date):
    mock_driver = MagicMock()
    mock_driver.last_bar_time = None

    with patch(f"{_TRADE_ENGINE_MOD}.disable_notifications"), \
         patch(f"{_TRADE_ENGINE_MOD}.enable_notifications"), \
         patch(f"{_TRADE_ENGINE_MOD}.set_replay_clock"), \
         patch(f"{_TRADE_ENGINE_MOD}.clear_replay_clock"), \
         patch.object(engine, "_run_window_selectors", return_value={}), \
         patch(f"{_TRADE_ENGINE_MOD}.LiveSignalEngine"), \
         patch(f"{_TRADE_ENGINE_MOD}.PositionMonitor"), \
         patch(f"{_TRADE_ENGINE_MOD}.BarReplayDriver", return_value=mock_driver):
        engine.run_replay(replay_date)


# ---------------------------------------------------------------------------
# TestRunReplayInitialCapital
# ---------------------------------------------------------------------------


class TestRunReplayInitialCapital:
    def test_sets_initial_capital_equal_to_replay_capital_for_full_fraction(self):
        windows = [
            WindowConfig(label="M1", opening_start="09:30", opening_bars=3, capital_fraction=1.0),
            WindowConfig(label="A1", opening_start="13:15", opening_bars=1, is_sequential=True),
        ]
        engine = _make_engine(replay_capital=10000.0, windows=windows)

        _run_replay_patched(engine, date(2026, 3, 17))

        assert engine._initial_capital == _D("10000.0")

    def test_sets_initial_capital_scaled_by_capital_fraction(self):
        windows = [
            WindowConfig(label="M1", opening_start="09:30", opening_bars=3, capital_fraction=0.6),
            WindowConfig(label="A1", opening_start="13:15", opening_bars=1, is_sequential=True),
        ]
        engine = _make_engine(replay_capital=10000.0, windows=windows)

        _run_replay_patched(engine, date(2026, 3, 17))

        assert engine._initial_capital == _D("6000.0")

    def test_uses_first_nonsq_window_capital_fraction_only(self):
        windows = [
            WindowConfig(label="M1", opening_start="09:30", opening_bars=3, capital_fraction=0.4),
            WindowConfig(label="A1", opening_start="13:15", opening_bars=1, is_sequential=True),
            WindowConfig(label="A2", opening_start="15:00", opening_bars=1, is_sequential=True),
        ]
        engine = _make_engine(replay_capital=5000.0, windows=windows)

        _run_replay_patched(engine, date(2026, 3, 17))

        assert engine._initial_capital == _D("2000.0")

    def test_initial_capital_resets_on_each_replay_call(self):
        windows = [
            WindowConfig(label="M1", opening_start="09:30", opening_bars=3, capital_fraction=1.0),
        ]
        engine = _make_engine(replay_capital=10000.0, windows=windows)
        engine._initial_capital = _D("99999")

        _run_replay_patched(engine, date(2026, 3, 17))

        assert engine._initial_capital == _D("10000.0")


# ---------------------------------------------------------------------------
# TestSequentialWindowBudgetGlobalPool
# ---------------------------------------------------------------------------


class TestSequentialWindowBudgetGlobalPool:
    def _setup(self, replay_capital=10000.0, initial_capital=None):
        windows = [
            WindowConfig(label="M1", opening_start="09:30", opening_bars=3),
            WindowConfig(label="A1", opening_start="13:15", opening_bars=1, is_sequential=True),
        ]
        engine = _make_engine(replay_capital=replay_capital, windows=windows)
        engine._window_state["M1"] = {}
        engine._initial_capital = _D(str(initial_capital or replay_capital))
        engine._daily_realized_pnl = _D("0")
        return engine, windows[1]

    def test_returns_initial_capital_when_no_pnl_and_no_open_positions(self):
        engine, a1_win = self._setup()

        with patch.object(engine, "_sum_open_position_cost", return_value=_D("0")):
            budget = engine._get_window_budget(a1_win)

        assert budget == _D("10000")

    def test_adds_realized_pnl_to_budget(self):
        engine, a1_win = self._setup()
        engine._daily_realized_pnl = _D("500")

        with patch.object(engine, "_sum_open_position_cost", return_value=_D("0")):
            budget = engine._get_window_budget(a1_win)

        assert budget == _D("10500")

    def test_deducts_open_position_cost_from_budget(self):
        engine, a1_win = self._setup()

        with patch.object(engine, "_sum_open_position_cost", return_value=_D("3000")):
            budget = engine._get_window_budget(a1_win)

        assert budget == _D("7000")

    def test_combines_pnl_and_open_position_cost(self):
        engine, a1_win = self._setup()
        engine._daily_realized_pnl = _D("200")

        with patch.object(engine, "_sum_open_position_cost", return_value=_D("1500")):
            budget = engine._get_window_budget(a1_win)

        assert budget == _D("8700")

    def test_returns_zero_when_open_cost_exceeds_initial_plus_pnl(self):
        engine, a1_win = self._setup()
        engine._daily_realized_pnl = _D("-500")

        with patch.object(engine, "_sum_open_position_cost", return_value=_D("12000")):
            budget = engine._get_window_budget(a1_win)

        assert budget == _D("0")

    def test_uses_initial_capital_path_not_fallback_when_set(self):
        engine, a1_win = self._setup(replay_capital=10000.0)
        engine._daily_realized_pnl = _D("0")

        with patch.object(engine, "_sum_open_position_cost", return_value=_D("0")), \
             patch.object(engine, "_prior_window_label", return_value="M1"):
            budget = engine._get_window_budget(a1_win)

        # Global pool: initial_capital(10000) + pnl(0) - open(0) = 10000
        # Fallback would return 0 (no window_returned, no deployed)
        assert budget == _D("10000")

import json
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch

import pytz

from alpha_tech_tracker.op_momentum_strategy.models import ActivePosition, _D
from alpha_tech_tracker.op_momentum_strategy import session_state

ET = pytz.timezone("America/New_York")

_MODULE = "alpha_tech_tracker.op_momentum_strategy.session_state"

_SESSION_DATE = date(2026, 4, 11)


def _make_position(**overrides) -> ActivePosition:
    defaults = dict(
        ticker="NVDA",
        signal="BULLISH",
        option_symbol="NVDA260418C00120000",
        entry_order_id="ord-001",
        contracts=2,
        entry_stock_price=_D("120.00"),
        or_high=_D("122.00"),
        or_low=_D("118.00"),
        or_range=_D("4.00"),
        hard_stop_price=_D("117.40"),
        fallback_price=_D("118.80"),
        trade_type="options",
        window_label="M1",
        rank=0,
        window_budget=_D("10000"),
        slot_capital=_D("5000"),
        entry_fill_price=_D("3.50"),
        entry_time=ET.localize(datetime(2026, 4, 11, 9, 46, 0)),
        entry_bar_time=ET.localize(datetime(2026, 4, 11, 9, 45, 0)),
    )
    defaults.update(overrides)
    return ActivePosition(**defaults)


# ---------------------------------------------------------------------------
# TestActivePositionSerialization
# ---------------------------------------------------------------------------


class TestActivePositionSerialization:
    def test_to_dict_converts_decimal_to_str(self):
        pos = _make_position()

        d = pos.to_dict()

        assert d["entry_stock_price"] == "120.00"
        assert d["or_high"] == "122.00"
        assert d["hard_stop_price"] == "117.40"
        assert d["slot_capital"] == "5000"
        assert d["entry_fill_price"] == "3.50"

    def test_to_dict_converts_datetime_to_iso(self):
        pos = _make_position()

        d = pos.to_dict()

        assert isinstance(d["entry_time"], str)
        assert "2026-04-11" in d["entry_time"]
        assert isinstance(d["entry_bar_time"], str)

    def test_to_dict_handles_none_optionals(self):
        pos = _make_position(
            exit_fill_price=None,
            exit_time=None,
            trailing_arm_price=None,
            window_budget=None,
        )

        d = pos.to_dict()

        assert d["exit_fill_price"] is None
        assert d["exit_time"] is None
        assert d["trailing_arm_price"] is None
        assert d["window_budget"] is None

    def test_from_dict_round_trip_preserves_all_fields(self):
        pos = _make_position(
            is_closed=True,
            exit_reason="hard_stop",
            bars_held=3,
            hard_stop_armed=True,
            trailing_arm_reached=False,
            reentry_type=None,
        )

        restored = ActivePosition.from_dict(pos.to_dict())

        assert restored.ticker == pos.ticker
        assert restored.signal == pos.signal
        assert restored.option_symbol == pos.option_symbol
        assert restored.contracts == pos.contracts
        assert restored.entry_stock_price == pos.entry_stock_price
        assert restored.hard_stop_price == pos.hard_stop_price
        assert restored.slot_capital == pos.slot_capital
        assert restored.entry_fill_price == pos.entry_fill_price
        assert restored.is_closed == pos.is_closed
        assert restored.exit_reason == pos.exit_reason
        assert restored.bars_held == pos.bars_held
        assert restored.hard_stop_armed == pos.hard_stop_armed
        assert restored.entry_time == pos.entry_time
        assert restored.entry_bar_time == pos.entry_bar_time
        assert restored.window_label == pos.window_label
        assert restored.rank == pos.rank


# ---------------------------------------------------------------------------
# TestSessionStateSave
# ---------------------------------------------------------------------------


class TestSessionStateSave:
    def test_creates_state_dir_if_missing(self, tmp_path):
        state_dir = tmp_path / "state"
        with patch(f"{_MODULE}.STATE_DIR", state_dir):
            session_state.save([_make_position()], _SESSION_DATE)

        assert state_dir.exists()

    def test_file_named_by_date(self, tmp_path):
        with patch(f"{_MODULE}.STATE_DIR", tmp_path):
            session_state.save([_make_position()], _SESSION_DATE)

        assert (tmp_path / "session_2026-04-11.json").exists()

    def test_write_is_atomic_tmp_then_rename(self, tmp_path):
        written_paths = []
        original_replace = Path.replace

        def spy_replace(self, target):
            written_paths.append((str(self), str(target)))
            return original_replace(self, target)

        with patch(f"{_MODULE}.STATE_DIR", tmp_path), \
             patch.object(Path, "replace", spy_replace):
            session_state.save([_make_position()], _SESSION_DATE)

        assert len(written_paths) == 1
        src, dst = written_paths[0]
        assert ".tmp" in src
        assert "session_2026-04-11.json" in dst

    def test_save_swallows_exception_and_logs(self, tmp_path, caplog):
        with patch(f"{_MODULE}.STATE_DIR", tmp_path), \
             patch.object(Path, "mkdir", side_effect=OSError("disk full")):
            session_state.save([_make_position()], _SESSION_DATE)

        assert "session_state.save failed" in caplog.text


# ---------------------------------------------------------------------------
# TestSessionStateLoad
# ---------------------------------------------------------------------------


class TestSessionStateLoad:
    def test_returns_empty_list_when_no_file(self, tmp_path):
        with patch(f"{_MODULE}.STATE_DIR", tmp_path):
            result = session_state.load(_SESSION_DATE)

        assert result == []

    def test_returns_empty_list_for_wrong_date(self, tmp_path):
        data = {"date": "2026-04-10", "positions": [_make_position().to_dict()]}
        (tmp_path / "session_2026-04-11.json").write_text(json.dumps(data))

        with patch(f"{_MODULE}.STATE_DIR", tmp_path):
            result = session_state.load(_SESSION_DATE)

        assert result == []

    def test_returns_empty_list_on_parse_error(self, tmp_path, caplog):
        (tmp_path / "session_2026-04-11.json").write_text("not json {{{")

        with patch(f"{_MODULE}.STATE_DIR", tmp_path):
            result = session_state.load(_SESSION_DATE)

        assert result == []
        assert "session_state.load failed" in caplog.text

    def test_round_trip_save_and_load(self, tmp_path):
        pos = _make_position()

        with patch(f"{_MODULE}.STATE_DIR", tmp_path):
            session_state.save([pos], _SESSION_DATE)
            restored = session_state.load(_SESSION_DATE)

        assert len(restored) == 1
        assert restored[0].ticker == pos.ticker
        assert restored[0].entry_fill_price == pos.entry_fill_price
        assert restored[0].hard_stop_price == pos.hard_stop_price
        assert restored[0].entry_time == pos.entry_time

    def test_load_returns_all_positions_including_closed(self, tmp_path):
        open_pos = _make_position(is_closed=False)
        closed_pos = _make_position(
            entry_order_id="ord-002",
            is_closed=True,
            exit_reason="hard_stop",
        )

        with patch(f"{_MODULE}.STATE_DIR", tmp_path):
            session_state.save([open_pos, closed_pos], _SESSION_DATE)
            restored = session_state.load(_SESSION_DATE)

        assert len(restored) == 2
        open_ones = [p for p in restored if not p.is_closed]
        closed_ones = [p for p in restored if p.is_closed]
        assert len(open_ones) == 1
        assert len(closed_ones) == 1
        assert closed_ones[0].exit_reason == "hard_stop"

from unittest.mock import Mock

import pytest

from alpha_tech_tracker.op_momentum_strategy.op_momentum_trade_engine import _parse_windows


def _make_args(window=None, morning_split=None):
    args = Mock()
    args.window = window
    args.morning_split = morning_split
    return args


class TestParseWindows:
    def test_returns_none_when_no_window_args(self):
        args = _make_args(window=None)
        result = _parse_windows(args)
        assert result is None

    def test_single_window_defaults_to_first_group_with_full_fraction(self):
        args = _make_args(window=[["M1", "09:30", "3"]])
        result = _parse_windows(args)

        assert len(result) == 1
        assert result[0].label == "M1"
        assert result[0].opening_start == "09:30"
        assert result[0].opening_bars == 3
        assert result[0].capital_fraction == 1.0
        assert result[0].is_sequential is False

    def test_single_window_with_morning_split_100(self):
        args = _make_args(window=[["M1", "09:30", "3"]], morning_split=[100.0])
        result = _parse_windows(args)

        assert result[0].capital_fraction == 1.0
        assert result[0].is_sequential is False

    def test_two_windows_without_morning_split_first_is_first_group_second_is_sequential(self):
        args = _make_args(window=[["M1", "09:30", "3"], ["A1", "13:15", "1"]])
        result = _parse_windows(args)

        assert result[0].is_sequential is False
        assert result[1].is_sequential is True

    def test_two_windows_second_window_has_full_capital_fraction_as_sequential(self):
        args = _make_args(window=[["M1", "09:30", "3"], ["A1", "13:15", "1"]])
        result = _parse_windows(args)

        assert result[1].capital_fraction == 1.0

    def test_two_windows_with_morning_split_sets_correct_fractions(self):
        args = _make_args(
            window=[["M1", "09:30", "3"], ["M2", "09:30", "1"]],
            morning_split=[60.0, 40.0],
        )
        result = _parse_windows(args)

        assert result[0].capital_fraction == pytest.approx(0.6)
        assert result[0].is_sequential is False
        assert result[1].capital_fraction == pytest.approx(0.4)
        assert result[1].is_sequential is False

    def test_three_windows_with_one_split_value_first_is_first_group_rest_sequential(self):
        args = _make_args(
            window=[["M1", "09:30", "3"], ["A1", "13:15", "1"], ["A2", "15:00", "1"]],
            morning_split=[100.0],
        )
        result = _parse_windows(args)

        assert result[0].is_sequential is False
        assert result[1].is_sequential is True
        assert result[2].is_sequential is True

    def test_three_windows_with_one_split_sequential_windows_have_full_fraction(self):
        args = _make_args(
            window=[["M1", "09:30", "3"], ["A1", "13:15", "1"], ["A2", "15:00", "1"]],
            morning_split=[100.0],
        )
        result = _parse_windows(args)

        assert result[1].capital_fraction == 1.0
        assert result[2].capital_fraction == 1.0

    def test_morning_split_exceeding_100_raises_system_exit(self):
        args = _make_args(
            window=[["M1", "09:30", "3"], ["M2", "09:30", "1"]],
            morning_split=[70.0, 40.0],
        )
        with pytest.raises(SystemExit):
            _parse_windows(args)

    def test_more_split_values_than_windows_raises_system_exit(self):
        args = _make_args(
            window=[["M1", "09:30", "3"]],
            morning_split=[50.0, 50.0],
        )
        with pytest.raises(SystemExit):
            _parse_windows(args)

    def test_window_labels_are_preserved(self):
        args = _make_args(
            window=[["M1", "09:30", "3"], ["A1", "13:15", "1"], ["A2", "15:00", "1"]],
            morning_split=[100.0],
        )
        result = _parse_windows(args)

        labels = [w.label for w in result]
        assert labels == ["M1", "A1", "A2"]

    def test_opening_bars_parsed_as_int(self):
        args = _make_args(window=[["M2", "09:30", "1"]])
        result = _parse_windows(args)

        assert isinstance(result[0].opening_bars, int)
        assert result[0].opening_bars == 1

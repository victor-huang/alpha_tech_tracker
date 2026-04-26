import sys
from unittest.mock import Mock

import pytest

from alpha_tech_tracker.op_momentum_strategy.op_momentum_selector import (
    ACTIVELY_TRADE_TICKERS,
    DEFAULT_TICKERS,
)
from alpha_tech_tracker.op_momentum_strategy.op_momentum_trade_engine import (
    _parse_windows,
    parse_args,
)


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


def _resolve_tickers(ticker_set=None, tickers=None):
    """Mirrors the resolution logic in all three entry points."""
    _TICKER_SETS = {"V3": DEFAULT_TICKERS, "AT": ACTIVELY_TRADE_TICKERS}
    return tickers or _TICKER_SETS.get(ticker_set, DEFAULT_TICKERS)


class TestTickerSetResolutionLogic:
    def test_no_ticker_set_returns_default_tickers(self):
        result = _resolve_tickers(ticker_set=None, tickers=None)
        assert result == DEFAULT_TICKERS

    def test_ticker_set_v3_returns_default_tickers(self):
        result = _resolve_tickers(ticker_set="V3", tickers=None)
        assert result == DEFAULT_TICKERS

    def test_ticker_set_at_returns_actively_trade_tickers(self):
        result = _resolve_tickers(ticker_set="AT", tickers=None)
        assert result == ACTIVELY_TRADE_TICKERS

    def test_explicit_tickers_override_ticker_set(self):
        result = _resolve_tickers(ticker_set="AT", tickers=["TSLA", "NVDA"])
        assert result == ["TSLA", "NVDA"]

    def test_explicit_tickers_override_default_when_no_ticker_set(self):
        result = _resolve_tickers(ticker_set=None, tickers=["TSLA"])
        assert result == ["TSLA"]

    def test_at_and_v3_pools_are_distinct(self):
        assert set(ACTIVELY_TRADE_TICKERS) != set(DEFAULT_TICKERS)

    def test_at_pool_contains_nvda_and_tsla(self):
        assert "NVDA" in ACTIVELY_TRADE_TICKERS
        assert "TSLA" in ACTIVELY_TRADE_TICKERS

    def test_v3_pool_does_not_contain_nvda_or_tsla(self):
        assert "NVDA" not in DEFAULT_TICKERS
        assert "TSLA" not in DEFAULT_TICKERS


class TestTradeEngineTickerSetArg:
    def test_ticker_set_at_stored_on_args(self, monkeypatch):
        monkeypatch.setattr(
            sys, "argv", ["engine", "run", "--ticker-set", "AT", "--window", "M1", "09:30", "3"]
        )
        args = parse_args()
        assert args.ticker_set == "AT"

    def test_ticker_set_v3_stored_on_args(self, monkeypatch):
        monkeypatch.setattr(
            sys, "argv", ["engine", "run", "--ticker-set", "V3", "--window", "M1", "09:30", "3"]
        )
        args = parse_args()
        assert args.ticker_set == "V3"

    def test_ticker_set_defaults_to_none_when_not_provided(self, monkeypatch):
        monkeypatch.setattr(
            sys, "argv", ["engine", "run", "--window", "M1", "09:30", "3"]
        )
        args = parse_args()
        assert args.ticker_set is None

    def test_invalid_ticker_set_raises_system_exit(self, monkeypatch):
        monkeypatch.setattr(
            sys, "argv", ["engine", "run", "--ticker-set", "UNKNOWN", "--window", "M1", "09:30", "3"]
        )
        with pytest.raises(SystemExit):
            parse_args()

    def test_ticker_set_and_tickers_can_coexist_on_args(self, monkeypatch):
        monkeypatch.setattr(
            sys,
            "argv",
            ["engine", "run", "--ticker-set", "AT", "--tickers", "TSLA", "--window", "M1", "09:30", "3"],
        )
        args = parse_args()
        assert args.ticker_set == "AT"
        assert args.tickers == ["TSLA"]

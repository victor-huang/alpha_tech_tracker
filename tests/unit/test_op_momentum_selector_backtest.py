from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest
import pytz

from alpha_tech_tracker.op_momentum_strategy.op_momentum_selector_backtest import (
    _apply_capital_flow,
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

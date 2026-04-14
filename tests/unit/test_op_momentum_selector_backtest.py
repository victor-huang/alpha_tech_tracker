from datetime import date, datetime

import pandas as pd
import pytest
import pytz

from alpha_tech_tracker.op_momentum_strategy.op_momentum_selector_backtest import (
    _annotate_doubledown_addon,
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


def _dd_stopout_row(bars_held=1):
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

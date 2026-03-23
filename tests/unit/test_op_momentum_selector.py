from datetime import date, datetime, timedelta
from unittest.mock import patch

import pandas as pd
import pytest
import pytz

from alpha_tech_tracker.op_momentum_strategy.op_momentum_selector import (
    compute_ticker_stats,
    compute_today_signals,
    score_ticker,
    select_top_n,
)


ET = pytz.timezone("America/New_York")

_BACKTEST_PATH = (
    "alpha_tech_tracker.op_momentum_strategy.op_momentum_selector.run_backtest"
)
_FETCH_BARS_PATH = (
    "alpha_tech_tracker.op_momentum_strategy.op_momentum_selector.fetch_bars"
)
_COMPUTE_SIGNALS_PATH = "alpha_tech_tracker.op_momentum_strategy.op_momentum_selector.compute_signals_with_backtest"
_COMPUTE_TODAY_SIGNALS_PATH = (
    "alpha_tech_tracker.op_momentum_strategy.op_momentum_selector.compute_today_signals"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_results_df(rows):
    return pd.DataFrame(rows)


def _win_row(entry=100.0, pnl=2.0, midpoint=99.0):
    return {
        "signal": "BULLISH",
        "entry_price": entry,
        "midpoint": midpoint,
        "pnl": pnl,
        "success": True,
        "date": date(2026, 3, 1),
        "or_high": 101.0,
        "or_low": 97.0,
        "exit_price": entry + pnl,
        "exit_reason": "end_of_day",
        "ma20": 95.0,
        "ma200": 90.0,
        "bars_held": 10,
        "mins_held": 50,
        "max_favorable_move": 2.5,
        "held_to_close": True,
        "total_post_bars": 12,
    }


def _loss_row(entry=100.0, pnl=-1.0):
    return {
        "signal": "BULLISH",
        "entry_price": entry,
        "midpoint": 99.0,
        "pnl": pnl,
        "success": False,
        "date": date(2026, 3, 2),
        "or_high": 101.0,
        "or_low": 97.0,
        "exit_price": entry + pnl,
        "exit_reason": "hard_stop",
        "ma20": 95.0,
        "ma200": 90.0,
        "bars_held": 2,
        "mins_held": 10,
        "max_favorable_move": 0.3,
        "held_to_close": False,
        "total_post_bars": 12,
    }


def _make_bar_df(target_date, closes, highs=None, lows=None):
    n = len(closes)
    if highs is None:
        highs = [c + 1.0 for c in closes]
    if lows is None:
        lows = [c - 1.0 for c in closes]
    timestamps = [
        ET.localize(
            datetime.combine(target_date, datetime.min.time())
            + timedelta(hours=9, minutes=30 + i * 5)
        )
        for i in range(n)
    ]
    return pd.DataFrame(
        {
            "Open": closes,
            "High": highs,
            "Low": lows,
            "Close": closes,
            "Volume": [1000.0] * n,
        },
        index=timestamps,
    )


# ---------------------------------------------------------------------------
# TestComputeTickerStats
# ---------------------------------------------------------------------------


class TestComputeTickerStats:
    def test_empty_dataframe_returns_zero_stats(self):
        stats = compute_ticker_stats(pd.DataFrame())

        assert stats["signals"] == 0
        assert stats["win_rate"] == 0.0
        assert stats["avg_win_pct"] == 0.0
        assert stats["avg_loss_pct"] == 0.0
        assert stats["ev_trade"] == 0.0
        assert stats["avg_entry_vs_mid_pct"] == 0.0

    def test_all_wins_has_zero_avg_loss_and_positive_ev(self):
        df = _make_results_df([_win_row(entry=100.0, pnl=2.0)] * 3)

        stats = compute_ticker_stats(df)

        assert stats["win_rate"] == 1.0
        assert stats["avg_loss_pct"] == 0.0
        assert stats["ev_trade"] > 0

    def test_all_losses_has_zero_avg_win_and_negative_ev(self):
        df = _make_results_df([_loss_row(entry=100.0, pnl=-1.5)] * 3)

        stats = compute_ticker_stats(df)

        assert stats["win_rate"] == 0.0
        assert stats["avg_win_pct"] == 0.0
        assert stats["ev_trade"] < 0

    def test_mixed_wins_and_losses_computes_correct_win_rate(self):
        rows = [_win_row()] * 3 + [_loss_row()] * 1
        df = _make_results_df(rows)

        stats = compute_ticker_stats(df)

        assert stats["signals"] == 4
        assert stats["win_rate"] == pytest.approx(0.75)

    def test_avg_win_pct_uses_pnl_over_entry_price(self):
        df = _make_results_df([_win_row(entry=200.0, pnl=4.0)])

        stats = compute_ticker_stats(df)

        assert stats["avg_win_pct"] == pytest.approx(2.0)

    def test_avg_loss_pct_uses_absolute_pnl_over_entry_price(self):
        df = _make_results_df([_loss_row(entry=200.0, pnl=-3.0)])

        stats = compute_ticker_stats(df)

        assert stats["avg_loss_pct"] == pytest.approx(1.5)

    def test_ev_trade_is_win_rate_times_avg_win_minus_loss_rate_times_avg_loss(self):
        rows = [_win_row(entry=100.0, pnl=2.0)] * 1 + [
            _loss_row(entry=100.0, pnl=-1.0)
        ] * 1
        df = _make_results_df(rows)

        stats = compute_ticker_stats(df)

        expected_ev = 0.5 * 2.0 - 0.5 * 1.0
        assert stats["ev_trade"] == pytest.approx(expected_ev)

    def test_avg_entry_vs_mid_pct_only_from_winning_trades(self):
        win = _win_row(entry=101.0, midpoint=100.0)  # (101-100)/100 * 100 = 1.0%
        loss = _loss_row(entry=98.0)  # should not affect avg_entry_vs_mid
        loss["midpoint"] = 100.0
        df = _make_results_df([win, loss])

        stats = compute_ticker_stats(df)

        assert stats["avg_entry_vs_mid_pct"] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# TestScoreTicker
# ---------------------------------------------------------------------------


class TestScoreTicker:
    def test_returns_zero_when_ev_trade_is_negative(self):
        signal = {"entry_vs_mid_pct": 2.0, "or_range_pct": 1.5}
        stats = {"ev_trade": -0.1, "avg_win_pct": 2.5}

        assert score_ticker(signal, stats) == 0.0

    def test_returns_zero_when_ev_trade_is_exactly_zero(self):
        signal = {"entry_vs_mid_pct": 2.0, "or_range_pct": 1.5}
        stats = {"ev_trade": 0.0, "avg_win_pct": 2.5}

        assert score_ticker(signal, stats) == 0.0

    def test_formula_weights_entry_vs_mid_heaviest(self):
        signal = {"entry_vs_mid_pct": 2.0, "or_range_pct": 1.0}
        stats = {"ev_trade": 1.0, "avg_win_pct": 1.0}

        score = score_ticker(signal, stats)

        expected = 2.0 * 0.50 + 1.0 * 0.30 + 1.0 * 0.20
        assert score == pytest.approx(expected)

    def test_higher_entry_vs_mid_pct_produces_higher_score(self):
        stats = {"ev_trade": 1.0, "avg_win_pct": 2.0}

        score_low = score_ticker({"entry_vs_mid_pct": 0.5, "or_range_pct": 1.0}, stats)
        score_high = score_ticker({"entry_vs_mid_pct": 2.0, "or_range_pct": 1.0}, stats)

        assert score_high > score_low


# ---------------------------------------------------------------------------
# TestComputeTodaySignals
# ---------------------------------------------------------------------------


class TestComputeTodaySignals:
    @patch(_COMPUTE_SIGNALS_PATH)
    def test_returns_signal_dict_for_ticker_with_signal_today(self, mock_compute):
        target = date(2026, 3, 17)
        bar_df = _make_bar_df(target, closes=[100.0] * 6)
        mock_compute.return_value = pd.DataFrame(
            [
                {
                    "date": target,
                    "signal": "BULLISH",
                    "or_high": 102.0,
                    "or_low": 98.0,
                    "midpoint": 100.0,
                    "entry_price": 101.0,
                    "ma20": 95.0,
                    "ma200": 90.0,
                }
            ]
        )

        signals = compute_today_signals(
            ticker_dfs={"SHOP": bar_df},
            opening_bars=3,
            bearish_ma200=False,
            stop_pct=0.15,
            target_date=target,
        )

        assert "SHOP" in signals
        s = signals["SHOP"]
        assert s["signal"] == "BULLISH"
        assert s["entry_price"] == pytest.approx(101.0)
        assert s["midpoint"] == pytest.approx(100.0)
        assert s["or_range"] == pytest.approx(4.0)
        assert s["entry_vs_mid_pct"] == pytest.approx(1.0)

    @patch(_COMPUTE_SIGNALS_PATH)
    def test_excludes_ticker_when_no_signal_on_target_date(self, mock_compute):
        target = date(2026, 3, 17)
        bar_df = _make_bar_df(target, closes=[100.0] * 6)
        mock_compute.return_value = pd.DataFrame(
            [
                {
                    "date": date(2026, 3, 14),
                    "signal": "BULLISH",
                    "or_high": 102.0,
                    "or_low": 98.0,
                    "midpoint": 100.0,
                    "entry_price": 101.0,
                    "ma20": 95.0,
                    "ma200": 90.0,
                }
            ]
        )

        signals = compute_today_signals(
            ticker_dfs={"AMD": bar_df},
            opening_bars=3,
            bearish_ma200=False,
            stop_pct=0.15,
            target_date=target,
        )

        assert "AMD" not in signals

    @patch(_COMPUTE_SIGNALS_PATH)
    def test_excludes_ticker_when_compute_signals_returns_empty(self, mock_compute):
        target = date(2026, 3, 17)
        bar_df = _make_bar_df(target, closes=[100.0] * 6)
        mock_compute.return_value = pd.DataFrame()

        signals = compute_today_signals(
            ticker_dfs={"FANG": bar_df},
            opening_bars=3,
            bearish_ma200=False,
            stop_pct=0.15,
            target_date=target,
        )

        assert "FANG" not in signals

    @patch(_COMPUTE_SIGNALS_PATH)
    def test_skips_empty_bar_dataframe(self, mock_compute):
        target = date(2026, 3, 17)

        signals = compute_today_signals(
            ticker_dfs={"SNDK": pd.DataFrame()},
            opening_bars=3,
            bearish_ma200=False,
            stop_pct=0.15,
            target_date=target,
        )

        mock_compute.assert_not_called()
        assert "SNDK" not in signals

    @patch(_COMPUTE_SIGNALS_PATH)
    def test_or_range_pct_computed_from_range_over_entry(self, mock_compute):
        target = date(2026, 3, 17)
        bar_df = _make_bar_df(target, closes=[100.0] * 6)
        mock_compute.return_value = pd.DataFrame(
            [
                {
                    "date": target,
                    "signal": "BULLISH",
                    "or_high": 104.0,
                    "or_low": 100.0,
                    "midpoint": 102.0,
                    "entry_price": 102.0,
                    "ma20": 95.0,
                    "ma200": 90.0,
                }
            ]
        )

        signals = compute_today_signals(
            ticker_dfs={"APP": bar_df},
            opening_bars=3,
            bearish_ma200=False,
            stop_pct=0.15,
            target_date=target,
        )

        expected_pct = 4.0 / 102.0 * 100
        assert signals["APP"]["or_range_pct"] == pytest.approx(expected_pct)


# ---------------------------------------------------------------------------
# TestSelectTopN
# ---------------------------------------------------------------------------


def _shop_signal():
    return {
        "signal": "BULLISH",
        "or_high": 102.0,
        "or_low": 98.0,
        "or_range": 4.0,
        "midpoint": 100.0,
        "entry_price": 101.5,
        "entry_vs_mid_pct": 1.5,
        "or_range_pct": 3.9,
        "ma20": 95.0,
        "ma50": 93.0,
        "ma200": 90.0,
    }


def _app_signal():
    return {
        "signal": "BULLISH",
        "or_high": 202.0,
        "or_low": 198.0,
        "or_range": 4.0,
        "midpoint": 200.0,
        "entry_price": 201.0,
        "entry_vs_mid_pct": 0.5,
        "or_range_pct": 2.0,
        "ma20": 190.0,
        "ma50": 188.0,
        "ma200": 185.0,
    }


class TestSelectTopN:
    @patch(
        _COMPUTE_TODAY_SIGNALS_PATH,
        return_value={"SHOP": _shop_signal(), "APP": _app_signal()},
    )
    @patch(
        _FETCH_BARS_PATH, return_value={"SHOP": pd.DataFrame(), "APP": pd.DataFrame()}
    )
    @patch(_BACKTEST_PATH)
    def test_returns_top_n_picks_sorted_by_score(self, mock_backtest, _fetch, _signals):
        target = date(2026, 3, 17)
        mock_backtest.return_value = {
            "SHOP": _make_results_df([_win_row()] * 6 + [_loss_row()] * 4),
            "APP": _make_results_df([_win_row()] * 5 + [_loss_row()] * 5),
        }

        result = select_top_n(
            n=2,
            tickers=["SHOP", "APP"],
            lookback_days=60,
            opening_bars=3,
            bearish_ma200=False,
            stop_pct=0.15,
            source="alpaca",
            target_date=target,
        )

        picks = result["picks"]
        assert len(picks) == 2
        assert picks[0]["score"] >= picks[1]["score"]
        assert picks[0]["ticker"] == "SHOP"

    @patch(_COMPUTE_TODAY_SIGNALS_PATH, return_value={})
    @patch(
        _FETCH_BARS_PATH, return_value={"SHOP": pd.DataFrame(), "AMD": pd.DataFrame()}
    )
    @patch(_BACKTEST_PATH)
    def test_tickers_without_signal_go_to_no_signal_list(
        self, mock_backtest, _fetch, _signals
    ):
        target = date(2026, 3, 17)
        mock_backtest.return_value = {
            "SHOP": _make_results_df([_win_row()] * 5),
            "AMD": _make_results_df([_win_row()] * 5),
        }

        result = select_top_n(
            n=3,
            tickers=["SHOP", "AMD"],
            lookback_days=60,
            opening_bars=3,
            bearish_ma200=False,
            stop_pct=0.15,
            source="alpaca",
            target_date=target,
        )

        assert result["picks"] == []
        assert "SHOP" in result["no_signal"]
        assert "AMD" in result["no_signal"]

    @patch(_COMPUTE_TODAY_SIGNALS_PATH)
    @patch(_FETCH_BARS_PATH, return_value={"FANG": pd.DataFrame()})
    @patch(_BACKTEST_PATH)
    def test_tickers_with_negative_ev_go_to_negative_ev_list(
        self, mock_backtest, _fetch, mock_signals
    ):
        target = date(2026, 3, 17)
        mock_backtest.return_value = {
            "FANG": _make_results_df([_loss_row()] * 8 + [_win_row()] * 2),
        }
        mock_signals.return_value = {
            "FANG": {
                "signal": "BULLISH",
                "or_high": 102.0,
                "or_low": 98.0,
                "or_range": 4.0,
                "midpoint": 100.0,
                "entry_price": 101.0,
                "entry_vs_mid_pct": 1.0,
                "or_range_pct": 4.0,
                "ma20": 95.0,
                "ma50": 93.0,
                "ma200": 90.0,
            }
        }

        result = select_top_n(
            n=3,
            tickers=["FANG"],
            lookback_days=60,
            opening_bars=3,
            bearish_ma200=False,
            stop_pct=0.15,
            source="alpaca",
            target_date=target,
        )

        assert result["picks"] == []
        assert "FANG" in result["negative_ev"]

    @patch(_COMPUTE_TODAY_SIGNALS_PATH)
    @patch(_FETCH_BARS_PATH)
    @patch(_BACKTEST_PATH)
    def test_result_capped_at_top_n(self, mock_backtest, mock_fetch, mock_signals):
        target = date(2026, 3, 17)
        tickers = ["SHOP", "APP", "CVNA", "AMD"]
        mock_backtest.return_value = {
            t: _make_results_df([_win_row()] * 6 + [_loss_row()] * 4) for t in tickers
        }
        mock_fetch.return_value = {t: pd.DataFrame() for t in tickers}
        mock_signals.return_value = {
            t: {
                "signal": "BULLISH",
                "or_high": 102.0,
                "or_low": 98.0,
                "or_range": 4.0,
                "midpoint": 100.0,
                "entry_price": 101.0,
                "entry_vs_mid_pct": 1.0,
                "or_range_pct": 4.0,
                "ma20": 95.0,
                "ma50": 93.0,
                "ma200": 90.0,
            }
            for t in tickers
        }

        result = select_top_n(
            n=2,
            tickers=tickers,
            lookback_days=60,
            opening_bars=3,
            bearish_ma200=False,
            stop_pct=0.15,
            source="alpaca",
            target_date=target,
        )

        assert len(result["picks"]) == 2

    @patch(_COMPUTE_TODAY_SIGNALS_PATH)
    @patch(_FETCH_BARS_PATH, return_value={"SHOP": pd.DataFrame()})
    @patch(_BACKTEST_PATH)
    def test_each_pick_contains_required_keys(
        self, mock_backtest, _fetch, mock_signals
    ):
        target = date(2026, 3, 17)
        mock_backtest.return_value = {
            "SHOP": _make_results_df([_win_row()] * 6 + [_loss_row()] * 4),
        }
        mock_signals.return_value = {
            "SHOP": {
                "signal": "BULLISH",
                "or_high": 102.0,
                "or_low": 98.0,
                "or_range": 4.0,
                "midpoint": 100.0,
                "entry_price": 101.0,
                "entry_vs_mid_pct": 1.5,
                "or_range_pct": 3.9,
                "ma20": 95.0,
                "ma50": 93.0,
                "ma200": 90.0,
            }
        }

        result = select_top_n(
            n=3,
            tickers=["SHOP"],
            lookback_days=60,
            opening_bars=3,
            bearish_ma200=False,
            stop_pct=0.15,
            source="alpaca",
            target_date=target,
        )

        pick = result["picks"][0]
        for key in (
            "ticker",
            "signal",
            "score",
            "entry_vs_mid_pct",
            "or_range_pct",
            "ev_trade",
            "win_rate",
            "avg_win_pct",
        ):
            assert key in pick, f"Missing key: {key}"

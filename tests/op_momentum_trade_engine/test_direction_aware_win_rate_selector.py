"""
TDD tests for direction-aware win-rate selector (DEV_PLAN_DIRECTION_AWARE_WINRATE_SELECTOR.md).

Coverage:
  - compute_directional_stats: bull/bear WR and avg_win_pct from signal history
  - direction_score: scoring formula WR * (1 + avg_win_pct * 2)
  - rank_tickers_direction_aware: directional ranking + overall-WR fallback
  - DualSideFloorSuppressor: suppression trigger, recovery, hysteresis
"""
from datetime import date, timedelta

import pandas as pd
import pytest

from alpha_tech_tracker.op_momentum_strategy.direction_aware_selector import (
    DualSideFloorSuppressor,
    compute_directional_stats,
    direction_score,
    rank_tickers_direction_aware,
)


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_signals(rows):
    """
    rows: list of (date_obj, signal_str, success_bool, pnl_float, entry_price_float)
    Returns a DataFrame with the columns expected by compute_directional_stats.
    """
    return pd.DataFrame(rows, columns=["date", "signal", "success", "pnl", "entry_price"])


def _trading_days(start: date, n: int):
    """Generate n consecutive weekday dates starting from start."""
    days = []
    d = start
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    return days


# ── TestComputeDirectionalStats ───────────────────────────────────────────────

class TestComputeDirectionalStats:
    """Rule 1 (90-day lookback) + Rule 2 (min 10 directional trades)."""

    _BASE = date(2025, 1, 2)

    def _recent(self, offset_days=0):
        """A date within the default 90-day lookback window."""
        return self._BASE - timedelta(days=offset_days)

    def test_bull_wr_computed_from_bullish_signals_only(self):
        # 7 BULLISH wins + 3 BULLISH losses = 70%; 4 BEARISH wins + 6 BEARISH losses = 40%
        rows = []
        for i in range(7):
            rows.append((self._recent(i), "BULLISH", True, 50.0, 100.0))
        for i in range(7, 10):
            rows.append((self._recent(i), "BULLISH", False, -40.0, 100.0))
        for i in range(10, 14):
            rows.append((self._recent(i), "BEARISH", True, 50.0, 100.0))
        for i in range(14, 20):
            rows.append((self._recent(i), "BEARISH", False, -40.0, 100.0))

        df = _make_signals(rows)
        result = compute_directional_stats(df, target_date=self._BASE, lookback_days=90)

        assert result["bull"]["wr"] == pytest.approx(7 / 10)
        assert result["bear"]["wr"] == pytest.approx(4 / 10)

    def test_bear_wr_computed_from_bearish_signals_only(self):
        rows = []
        for i in range(10):
            rows.append((self._recent(i), "BULLISH", True, 50.0, 100.0))
        for i in range(10, 18):
            rows.append((self._recent(i), "BEARISH", True, 60.0, 100.0))
        for i in range(18, 20):
            rows.append((self._recent(i), "BEARISH", False, -30.0, 100.0))

        df = _make_signals(rows)
        result = compute_directional_stats(df, target_date=self._BASE, lookback_days=90)

        assert result["bear"]["wr"] == pytest.approx(8 / 10)

    def test_avg_win_pct_is_average_of_winning_pnl_pct(self):
        rows = []
        # 10 bullish wins with pnl = entry_price * 1% → avg_win_pct = 1%
        for i in range(10):
            rows.append((self._recent(i), "BULLISH", True, 1.0, 100.0))

        df = _make_signals(rows)
        result = compute_directional_stats(df, target_date=self._BASE, lookback_days=90)

        assert result["bull"]["avg_win_pct"] == pytest.approx(1.0)

    def test_rolling_window_excludes_signals_outside_lookback(self):
        # 10 bullish wins within window + 5 bullish losses outside (91+ days ago)
        rows = []
        for i in range(10):
            rows.append((self._recent(i), "BULLISH", True, 50.0, 100.0))
        for i in range(92, 97):
            rows.append((self._recent(i), "BULLISH", False, -40.0, 100.0))

        df = _make_signals(rows)
        result = compute_directional_stats(df, target_date=self._BASE, lookback_days=90)

        # Only the 10 wins within the window should count → WR = 100%
        assert result["bull"]["wr"] == pytest.approx(1.0)
        assert result["bull"]["n"] == 10

    def test_no_bullish_history_returns_none_for_bull(self):
        rows = [(self._recent(i), "BEARISH", True, 50.0, 100.0) for i in range(10)]
        df = _make_signals(rows)
        result = compute_directional_stats(df, target_date=self._BASE, lookback_days=90)

        assert result["bull"] is None
        assert result["bear"] is not None

    def test_no_bearish_history_returns_none_for_bear(self):
        rows = [(self._recent(i), "BULLISH", True, 50.0, 100.0) for i in range(10)]
        df = _make_signals(rows)
        result = compute_directional_stats(df, target_date=self._BASE, lookback_days=90)

        assert result["bear"] is None
        assert result["bull"] is not None

    def test_below_min_trades_returns_none_for_that_direction(self):
        # Only 9 bullish trades → below min_trades=10 → bull should be None
        rows = [(self._recent(i), "BULLISH", True, 50.0, 100.0) for i in range(9)]
        rows += [(self._recent(i + 9), "BEARISH", True, 50.0, 100.0) for i in range(10)]
        df = _make_signals(rows)
        result = compute_directional_stats(df, target_date=self._BASE, lookback_days=90, min_trades=10)

        assert result["bull"] is None
        assert result["bear"] is not None

    def test_below_min_trades_returns_none_even_with_large_total(self):
        # 9 bull trades + 11 bear trades = 20 total
        # Bull has < 10 trades → None regardless of total (no proxy fallback)
        # Bear has 11 trades >= 10 → valid direct stats
        rows = []
        for i in range(9):
            rows.append((self._recent(i), "BULLISH", True, 50.0, 100.0))
        for i in range(9, 14):
            rows.append((self._recent(i), "BEARISH", True, 50.0, 100.0))
        for i in range(14, 20):
            rows.append((self._recent(i), "BEARISH", False, -30.0, 100.0))

        df = _make_signals(rows)
        result = compute_directional_stats(df, target_date=self._BASE, lookback_days=90, min_trades=10)

        assert result["bull"] is None
        assert result["bear"] is not None
        assert result["bear"]["is_proxy"] is False
        assert result["bear"]["wr"] == pytest.approx(5 / 11)

    def test_excluded_entirely_when_less_than_20_total_trades(self):
        # Only 15 total trades across both directions → excluded entirely
        rows = []
        for i in range(7):
            rows.append((self._recent(i), "BULLISH", True, 50.0, 100.0))
        for i in range(7, 15):
            rows.append((self._recent(i), "BEARISH", False, -30.0, 100.0))

        df = _make_signals(rows)
        result = compute_directional_stats(df, target_date=self._BASE, lookback_days=90, min_trades=10)

        assert result["bull"] is None
        assert result["bear"] is None

    def test_empty_dataframe_returns_both_none(self):
        df = _make_signals([])
        result = compute_directional_stats(df, target_date=self._BASE, lookback_days=90)

        assert result["bull"] is None
        assert result["bear"] is None


# ── TestDirectionScore ────────────────────────────────────────────────────────

class TestDirectionScore:
    """Rule 3: scoring formula WR * (1 + avg_win_pct * 2)."""

    def test_formula_basic(self):
        # wr=0.70, avg_win_pct=1.0% → 0.70 * (1 + 1.0 * 2) = 0.70 * 3.0 = 2.10
        assert direction_score(0.70, 1.0) == pytest.approx(2.10)

    def test_zero_avg_win_equals_wr(self):
        assert direction_score(0.60, 0.0) == pytest.approx(0.60)

    def test_higher_magnitude_ranks_above_equal_wr(self):
        score_high_mag = direction_score(0.55, 0.80)  # 0.55 * (1 + 1.60) = 1.43
        score_low_mag = direction_score(0.55, 0.10)   # 0.55 * (1 + 0.20) = 0.66
        assert score_high_mag > score_low_mag

    def test_known_example_from_dev_plan(self):
        # TSLA 2021 bearish: WR=64%, avg_win_pct=1.015% → score ≈ 1.94
        score = direction_score(0.64, 1.015)
        assert score == pytest.approx(0.64 * (1 + 1.015 * 2), rel=1e-4)

    def test_known_example_avgo_weak(self):
        # AVGO 2021 bearish: WR=44%, avg_win_pct=0.12% → score ≈ 0.55
        score = direction_score(0.44, 0.12)
        assert score == pytest.approx(0.44 * (1 + 0.12 * 2), rel=1e-4)


# ── TestRankTickersDirectionAware ─────────────────────────────────────────────

class TestRankTickersDirectionAware:
    """Rule 3 (scoring) + Rule 7 (fallback) + Rule 8 (grace period / exclusion)."""

    def _stats(self, bull_wr, bull_avg_win, bear_wr, bear_avg_win, bull_n=15, bear_n=15):
        """Helper: build a {bull: ..., bear: ...} directional stats dict."""
        return {
            "bull": {"wr": bull_wr, "avg_win_pct": bull_avg_win, "n": bull_n, "is_proxy": False},
            "bear": {"wr": bear_wr, "avg_win_pct": bear_avg_win, "n": bear_n, "is_proxy": False},
        }

    def test_long_day_ranks_by_bull_score_descending(self):
        pool = {
            "CRWD": self._stats(0.70, 0.5, 0.50, 0.3),  # bull_score > TSLA
            "TSLA": self._stats(0.40, 0.3, 0.77, 0.8),  # TSLA bull weak, bear strong
        }
        ranked = rank_tickers_direction_aware(pool, direction="LONG")
        assert ranked[0][0] == "CRWD"
        assert ranked[1][0] == "TSLA"

    def test_short_day_ranks_by_bear_score_descending(self):
        pool = {
            "CRWD": self._stats(0.70, 0.5, 0.50, 0.3),
            "TSLA": self._stats(0.40, 0.3, 0.77, 0.8),  # TSLA bear score wins
        }
        ranked = rank_tickers_direction_aware(pool, direction="SHORT")
        assert ranked[0][0] == "TSLA"
        assert ranked[1][0] == "CRWD"

    def test_ticker_with_only_bear_history_excluded_on_long_day(self):
        pool = {
            "DDOG": {"bull": None, "bear": {"wr": 0.72, "avg_win_pct": 0.47, "n": 12, "is_proxy": False}},
            "AMD":  self._stats(0.60, 0.5, 0.50, 0.3),
        }
        ranked = rank_tickers_direction_aware(pool, direction="LONG")
        tickers = [t for t, _ in ranked]
        assert "DDOG" not in tickers
        assert "AMD" in tickers

    def test_ticker_with_only_bull_history_excluded_on_short_day(self):
        pool = {
            "DDOG": {"bull": {"wr": 0.60, "avg_win_pct": 0.4, "n": 11, "is_proxy": False}, "bear": None},
            "AMD":  self._stats(0.55, 0.4, 0.55, 0.4),
        }
        ranked = rank_tickers_direction_aware(pool, direction="SHORT")
        tickers = [t for t, _ in ranked]
        assert "DDOG" not in tickers
        assert "AMD" in tickers

    def test_falls_back_to_overall_wr_when_fewer_than_3_valid(self):
        # Only 2 tickers have direction-specific bull stats; should trigger overall-WR fallback.
        pool = {
            "AMD":  self._stats(0.60, 0.4, 0.50, 0.3),
            "MRVL": self._stats(0.55, 0.3, 0.48, 0.2),
            "TSLA": {"bull": None, "bear": {"wr": 0.77, "avg_win_pct": 0.8, "n": 12, "is_proxy": False}},
            "CRWD": {"bull": None, "bear": {"wr": 0.70, "avg_win_pct": 0.6, "n": 11, "is_proxy": False}},
        }
        overall_wr = {"AMD": 0.58, "MRVL": 0.52, "TSLA": 0.55, "CRWD": 0.60}
        ranked = rank_tickers_direction_aware(
            pool, direction="LONG", min_pool_valid=3, fallback_overall_wr=overall_wr
        )
        # Fallback: should include TSLA and CRWD using overall WR
        tickers = [t for t, _ in ranked]
        assert "TSLA" in tickers
        assert "CRWD" in tickers

    def test_no_fallback_when_3_or_more_valid_long_scores(self):
        pool = {
            "CRWD": self._stats(0.70, 0.5, 0.50, 0.3),
            "TSLA": self._stats(0.40, 0.3, 0.77, 0.8),
            "AMD":  self._stats(0.60, 0.4, 0.50, 0.3),
        }
        # All 3 have valid bull stats → no fallback needed
        ranked = rank_tickers_direction_aware(pool, direction="LONG", min_pool_valid=3)
        assert len(ranked) == 3

    def test_ticker_below_min_trades_excluded_from_ranking(self):
        # compute_directional_stats now returns None when n_dir < min_trades (no proxy).
        # rank_tickers_direction_aware excludes any ticker whose relevant side is None.
        pool = {
            "TSLA": {"bull": None, "bear": {"wr": 0.72, "avg_win_pct": 0.6, "n": 12, "is_proxy": False}},
            "AMD":  self._stats(0.60, 0.5, 0.50, 0.3),
            "MRVL": self._stats(0.55, 0.3, 0.50, 0.3),
            "CRWD": self._stats(0.70, 0.4, 0.50, 0.3),
        }
        ranked = rank_tickers_direction_aware(pool, direction="LONG", min_pool_valid=3)
        tickers = [t for t, _ in ranked]
        # TSLA has no bull stats → excluded; AMD/MRVL/CRWD have bull stats → included
        assert "TSLA" not in tickers
        assert "AMD" in tickers
        assert "CRWD" in tickers


# ── TestDualSideFloorSuppressor ───────────────────────────────────────────────

class TestDualSideFloorSuppressor:
    """Rules 4–6: suppression trigger, recovery, hysteresis."""

    def _days(self, n, start=None):
        """Return n consecutive trading days starting from start."""
        start = start or date(2025, 1, 2)
        return _trading_days(start, n)

    def test_ticker_suppressed_after_45_consecutive_days_both_below_45pct(self):
        sup = DualSideFloorSuppressor()
        days = self._days(50)
        for d in days[:45]:
            sup.update("TSLA", bull_wr=0.40, bear_wr=0.38, trading_date=d)

        assert sup.is_suppressed("TSLA", direction="LONG", as_of=days[44])
        assert sup.is_suppressed("TSLA", direction="SHORT", as_of=days[44])

    def test_ticker_not_suppressed_after_only_44_trading_days(self):
        sup = DualSideFloorSuppressor()
        days = self._days(50)
        for d in days[:44]:
            sup.update("TSLA", bull_wr=0.40, bear_wr=0.38, trading_date=d)

        assert not sup.is_suppressed("TSLA", direction="LONG", as_of=days[43])

    def test_streak_resets_when_either_wr_climbs_above_floor(self):
        sup = DualSideFloorSuppressor()
        days = self._days(60)
        # 30 days both below floor
        for d in days[:30]:
            sup.update("TSLA", bull_wr=0.40, bear_wr=0.38, trading_date=d)
        # Bear WR recovers above 0.45 on day 31 — streak should reset
        sup.update("TSLA", bull_wr=0.40, bear_wr=0.46, trading_date=days[30])
        # 30 more days both below floor (does not reach 45 yet — streak started over)
        for d in days[31:61]:
            sup.update("TSLA", bull_wr=0.40, bear_wr=0.38, trading_date=d)

        # Total = 30 reset days after day 31, so not yet 45 consecutive
        assert not sup.is_suppressed("TSLA", direction="LONG", as_of=days[59])

    def test_bull_recovery_re_enables_long_ranking(self):
        sup = DualSideFloorSuppressor()
        days = self._days(80)

        # Trigger suppression: 45 days both below floor
        for d in days[:45]:
            sup.update("TSLA", bull_wr=0.40, bear_wr=0.38, trading_date=d)
        assert sup.is_suppressed("TSLA", direction="LONG", as_of=days[44])

        # Bull WR recovers above 50% for 20 consecutive days
        for d in days[45:65]:
            sup.update("TSLA", bull_wr=0.52, bear_wr=0.38, trading_date=d)

        assert not sup.is_suppressed("TSLA", direction="LONG", as_of=days[64])
        # Bear still suppressed because it hasn't recovered yet
        assert sup.is_suppressed("TSLA", direction="SHORT", as_of=days[64])

    def test_bear_recovery_re_enables_short_ranking(self):
        sup = DualSideFloorSuppressor()
        days = self._days(80)

        for d in days[:45]:
            sup.update("TSLA", bull_wr=0.40, bear_wr=0.38, trading_date=d)

        for d in days[45:65]:
            sup.update("TSLA", bull_wr=0.40, bear_wr=0.52, trading_date=d)

        assert not sup.is_suppressed("TSLA", direction="SHORT", as_of=days[64])
        assert sup.is_suppressed("TSLA", direction="LONG", as_of=days[64])

    def test_full_recovery_clears_suppression_entirely(self):
        sup = DualSideFloorSuppressor()
        days = self._days(100)

        for d in days[:45]:
            sup.update("TSLA", bull_wr=0.40, bear_wr=0.38, trading_date=d)

        # Both sides recover over 20 days
        for d in days[45:65]:
            sup.update("TSLA", bull_wr=0.52, bear_wr=0.52, trading_date=d)

        assert not sup.is_suppressed("TSLA", direction="LONG", as_of=days[64])
        assert not sup.is_suppressed("TSLA", direction="SHORT", as_of=days[64])

    def test_hysteresis_50pct_recovery_threshold_not_45pct(self):
        sup = DualSideFloorSuppressor()
        days = self._days(80)

        for d in days[:45]:
            sup.update("TSLA", bull_wr=0.40, bear_wr=0.38, trading_date=d)

        # Bull WR at exactly 0.46 (above floor 0.45 but below recovery 0.50)
        # → should not trigger recovery
        for d in days[45:65]:
            sup.update("TSLA", bull_wr=0.46, bear_wr=0.38, trading_date=d)

        assert sup.is_suppressed("TSLA", direction="LONG", as_of=days[64])

    def test_recovery_streak_resets_when_wr_dips_below_50pct(self):
        sup = DualSideFloorSuppressor()
        days = self._days(90)

        for d in days[:45]:
            sup.update("TSLA", bull_wr=0.40, bear_wr=0.38, trading_date=d)

        # 19 days of bull recovery
        for d in days[45:64]:
            sup.update("TSLA", bull_wr=0.52, bear_wr=0.38, trading_date=d)

        # Dips below 0.50 on day 65 → recovery streak resets
        sup.update("TSLA", bull_wr=0.48, bear_wr=0.38, trading_date=days[64])

        # 20 more days of bull recovery
        for d in days[65:85]:
            sup.update("TSLA", bull_wr=0.52, bear_wr=0.38, trading_date=d)

        assert not sup.is_suppressed("TSLA", direction="LONG", as_of=days[84])

    def test_unknown_ticker_is_never_suppressed(self):
        sup = DualSideFloorSuppressor()
        assert not sup.is_suppressed("NVDA", direction="LONG", as_of=date(2025, 1, 2))

    def test_avgo_2020_scenario_not_suppressed_under_single_bad_year(self):
        """
        AVGO 2020 had both WR < 45% but recovered the following year.
        The 45-day continuous streak must not be triggered by a few scattered weak days.
        """
        sup = DualSideFloorSuppressor()
        days = self._days(250)  # ~1 year of trading days

        # Alternate: 40 bad days, then 1 good day — never hits 45 consecutive
        for i, d in enumerate(days[:160]):
            if i % 41 == 40:
                sup.update("AVGO", bull_wr=0.50, bear_wr=0.50, trading_date=d)
            else:
                sup.update("AVGO", bull_wr=0.43, bear_wr=0.36, trading_date=d)

        assert not sup.is_suppressed("AVGO", direction="LONG", as_of=days[159])

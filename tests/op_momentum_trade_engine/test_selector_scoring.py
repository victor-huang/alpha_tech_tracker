from datetime import date, timedelta
from itertools import cycle
from unittest.mock import patch

import pandas as pd

from alpha_tech_tracker.op_momentum_strategy.op_momentum_selector import (
    select_top_n,
    score_ticker,
    passes_dynamic_ev_gate,
    passes_direction_split_ev_gate,
)

ET = __import__("pytz").timezone("America/New_York")

_SELECTOR_MODULE = "alpha_tech_tracker.op_momentum_strategy.op_momentum_selector"

_BASE_STATS = {
    "ev_trade": 0.3, "win_rate": 0.4, "avg_win_pct": 0.6,
    "avg_loss_pct": -0.3, "ev_trend": 0.0,
    "ev_trade_bullish": 0.3, "ev_trade_bearish": 0.0,
    "recent_bear_ev": 0.0,
}

_BASE_SIGNAL = {
    "signal": "BULLISH", "or_high": 105.0, "or_low": 95.0,
    "or_range": 10.0, "midpoint": 100.0, "entry_price": 103.0,
    "entry_vs_mid_pct": 0.5, "or_range_pct": 1.0,
    "or_vol_ratio": 1.0, "ma20": 100.0, "ma50": 98.0, "ma200": 90.0,
}


def _make_fake_backtest(tickers):
    def fake_run_backtest(**kwargs):
        return {t: pd.DataFrame({"date": [date(2025, 12, 1)]}) for t in tickers}
    return fake_run_backtest


def _make_today_signals(tickers, overrides=None):
    result = {t: dict(_BASE_SIGNAL) for t in tickers}
    if overrides:
        for t, vals in overrides.items():
            result[t].update(vals)
    return result


class TestMinPoolVoteGate:
    """min_pool_vote_to_trade: skip day if fewer than N tickers have positive EV."""

    def test_returns_picks_when_pool_vote_above_threshold(self):
        tickers = ["AAA", "BBB", "CCC", "DDD", "EEE"]
        ticker_dfs = {t: pd.DataFrame() for t in tickers}

        with patch(f"{_SELECTOR_MODULE}.run_backtest", side_effect=_make_fake_backtest(tickers)), \
             patch(f"{_SELECTOR_MODULE}.compute_today_signals",
                   return_value=_make_today_signals(tickers)), \
             patch(f"{_SELECTOR_MODULE}.build_bearish_regime_dates", return_value=None), \
             patch(f"{_SELECTOR_MODULE}.compute_ticker_stats",
                   return_value=dict(_BASE_STATS)):

            result = select_top_n(
                n=3, tickers=tickers, lookback_days=60, opening_bars=3,
                bearish_ma200=False, stop_pct=0.15, source="alpaca",
                target_date=date(2025, 12, 2), ticker_dfs=ticker_dfs,
                min_pool_vote_to_trade=4,
            )

        assert len(result["picks"]) > 0

    def test_returns_empty_picks_when_pool_vote_below_threshold(self):
        tickers = ["AAA", "BBB", "CCC", "DDD", "EEE"]
        ticker_dfs = {t: pd.DataFrame() for t in tickers}
        call_count = [0]

        def fake_stats(df, **kwargs):
            call_count[0] += 1
            ev = 0.3 if call_count[0] <= 1 else -0.1
            return {**_BASE_STATS, "ev_trade": ev}

        with patch(f"{_SELECTOR_MODULE}.run_backtest", side_effect=_make_fake_backtest(tickers)), \
             patch(f"{_SELECTOR_MODULE}.compute_today_signals",
                   return_value=_make_today_signals(tickers)), \
             patch(f"{_SELECTOR_MODULE}.build_bearish_regime_dates", return_value=None), \
             patch(f"{_SELECTOR_MODULE}.compute_ticker_stats", side_effect=fake_stats):

            result = select_top_n(
                n=3, tickers=tickers, lookback_days=60, opening_bars=3,
                bearish_ma200=False, stop_pct=0.15, source="alpaca",
                target_date=date(2025, 12, 2), ticker_dfs=ticker_dfs,
                min_pool_vote_to_trade=4,
            )

        assert result["picks"] == []

    def test_min_pool_vote_zero_never_skips(self):
        """Default min_pool_vote_to_trade=0 means no gate is applied."""
        tickers = ["AAA", "BBB"]
        ticker_dfs = {t: pd.DataFrame() for t in tickers}
        call_count = [0]

        def fake_stats(df, **kwargs):
            call_count[0] += 1
            ev = 0.3 if call_count[0] <= 1 else -0.5
            return {**_BASE_STATS, "ev_trade": ev}

        with patch(f"{_SELECTOR_MODULE}.run_backtest", side_effect=_make_fake_backtest(tickers)), \
             patch(f"{_SELECTOR_MODULE}.compute_today_signals",
                   return_value=_make_today_signals(["AAA"])), \
             patch(f"{_SELECTOR_MODULE}.build_bearish_regime_dates", return_value=None), \
             patch(f"{_SELECTOR_MODULE}.compute_ticker_stats", side_effect=fake_stats):

            result = select_top_n(
                n=3, tickers=tickers, lookback_days=60, opening_bars=3,
                bearish_ma200=False, stop_pct=0.15, source="alpaca",
                target_date=date(2025, 12, 2), ticker_dfs=ticker_dfs,
                min_pool_vote_to_trade=0,
            )

        assert len(result["picks"]) == 1  # AAA passes, BBB has negative EV


def _make_multi_day_bars(days: int = 40) -> pd.DataFrame:
    rows = []
    base = date(2025, 10, 1)
    trading_days = [base + timedelta(days=d) for d in range(days * 2)
                    if (base + timedelta(days=d)).weekday() < 5][:days]
    for d in trading_days:
        for bar_i in range(78):
            ts = ET.localize(
                pd.Timestamp(d).to_pydatetime().replace(hour=9, minute=30)
                + timedelta(minutes=bar_i * 5)
            )
            close = 100.0 + bar_i * 0.01
            rows.append({
                "Open": close - 0.5, "High": close + 1.0,
                "Low": close - 1.0, "Close": close, "Volume": 10_000.0,
                "_ts": ts,
            })
    df = pd.DataFrame(rows).set_index("_ts")
    df.index.name = "timestamp"
    return df


class TestNormalizeOrByAdr:
    """normalize_or_by_adr divides or_range_pct by the ticker's prior-day ADR."""

    def test_or_range_pct_is_divided_by_adr(self):
        tickers = ["AAA"]
        ticker_dfs = {"AAA": _make_multi_day_bars()}
        target = date(2025, 11, 14)  # Friday — must be a trading day so ADR dict has an entry
        raw_or_range_pct = 2.0

        scored_sigs = []

        def capture_score(sig, stats, **kwargs):
            scored_sigs.append(dict(sig))
            return score_ticker(sig, stats, **kwargs)

        with patch(f"{_SELECTOR_MODULE}.run_backtest",
                   side_effect=lambda **kw: {"AAA": pd.DataFrame({"date": [target - timedelta(days=1)]})}), \
             patch(f"{_SELECTOR_MODULE}.build_bearish_regime_dates", return_value=None), \
             patch(f"{_SELECTOR_MODULE}.compute_ticker_stats", return_value=dict(_BASE_STATS)), \
             patch(f"{_SELECTOR_MODULE}.compute_today_signals", return_value={
                 "AAA": {**_BASE_SIGNAL, "or_range_pct": raw_or_range_pct},
             }), \
             patch(f"{_SELECTOR_MODULE}.score_ticker", side_effect=capture_score):

            select_top_n(
                n=1, tickers=tickers, lookback_days=30, opening_bars=3,
                bearish_ma200=False, stop_pct=0.15, source="alpaca",
                target_date=target, ticker_dfs=ticker_dfs,
                normalize_or_by_adr=True, adr_days=20,
            )

        assert len(scored_sigs) == 1
        assert scored_sigs[0]["or_range_pct"] < raw_or_range_pct

    def test_normalize_off_leaves_or_range_pct_unchanged(self):
        tickers = ["AAA"]
        ticker_dfs = {"AAA": _make_multi_day_bars()}
        target = date(2025, 11, 14)  # Friday — must be a trading day
        raw_or_range_pct = 2.0

        scored_sigs = []

        def capture_score(sig, stats, **kwargs):
            scored_sigs.append(dict(sig))
            return score_ticker(sig, stats, **kwargs)

        with patch(f"{_SELECTOR_MODULE}.run_backtest",
                   side_effect=lambda **kw: {"AAA": pd.DataFrame({"date": [target - timedelta(days=1)]})}), \
             patch(f"{_SELECTOR_MODULE}.build_bearish_regime_dates", return_value=None), \
             patch(f"{_SELECTOR_MODULE}.compute_ticker_stats", return_value=dict(_BASE_STATS)), \
             patch(f"{_SELECTOR_MODULE}.compute_today_signals", return_value={
                 "AAA": {**_BASE_SIGNAL, "or_range_pct": raw_or_range_pct},
             }), \
             patch(f"{_SELECTOR_MODULE}.score_ticker", side_effect=capture_score):

            select_top_n(
                n=1, tickers=tickers, lookback_days=30, opening_bars=3,
                bearish_ma200=False, stop_pct=0.15, source="alpaca",
                target_date=target, ticker_dfs=ticker_dfs,
                normalize_or_by_adr=False,
            )

        assert len(scored_sigs) == 1
        assert scored_sigs[0]["or_range_pct"] == raw_or_range_pct


class TestScoringWeights:
    """score_entry_weight, score_avg_win_weight, score_win_rate_weight flow through to score_ticker."""

    def test_custom_weights_are_passed_to_score_ticker(self):
        tickers = ["AAA"]
        captured_kwargs = []

        def capture(sig, stats, **kwargs):
            captured_kwargs.append(kwargs)
            return score_ticker(sig, stats, **kwargs)

        with patch(f"{_SELECTOR_MODULE}.run_backtest", side_effect=_make_fake_backtest(tickers)), \
             patch(f"{_SELECTOR_MODULE}.build_bearish_regime_dates", return_value=None), \
             patch(f"{_SELECTOR_MODULE}.compute_ticker_stats", return_value=dict(_BASE_STATS)), \
             patch(f"{_SELECTOR_MODULE}.compute_today_signals",
                   return_value=_make_today_signals(tickers)), \
             patch(f"{_SELECTOR_MODULE}.score_ticker", side_effect=capture):

            select_top_n(
                n=1, tickers=tickers, lookback_days=30, opening_bars=3,
                bearish_ma200=False, stop_pct=0.15, source="alpaca",
                target_date=date(2025, 12, 2), ticker_dfs={t: pd.DataFrame() for t in tickers},
                score_entry_weight=0.40,
                score_avg_win_weight=0.25,
                score_win_rate_weight=0.10,
            )

        assert len(captured_kwargs) == 1
        kw = captured_kwargs[0]
        assert kw["score_entry_weight"] == 0.40
        assert kw["score_avg_win_weight"] == 0.25
        assert kw["score_win_rate_weight"] == 0.10

    def test_default_weights_preserved_when_not_overridden(self):
        tickers = ["AAA"]
        captured_kwargs = []

        def capture(sig, stats, **kwargs):
            captured_kwargs.append(kwargs)
            return score_ticker(sig, stats, **kwargs)

        with patch(f"{_SELECTOR_MODULE}.run_backtest", side_effect=_make_fake_backtest(tickers)), \
             patch(f"{_SELECTOR_MODULE}.build_bearish_regime_dates", return_value=None), \
             patch(f"{_SELECTOR_MODULE}.compute_ticker_stats", return_value=dict(_BASE_STATS)), \
             patch(f"{_SELECTOR_MODULE}.compute_today_signals",
                   return_value=_make_today_signals(tickers)), \
             patch(f"{_SELECTOR_MODULE}.score_ticker", side_effect=capture):

            select_top_n(
                n=1, tickers=tickers, lookback_days=30, opening_bars=3,
                bearish_ma200=False, stop_pct=0.15, source="alpaca",
                target_date=date(2025, 12, 2), ticker_dfs={t: pd.DataFrame() for t in tickers},
            )

        assert len(captured_kwargs) == 1
        kw = captured_kwargs[0]
        assert kw["score_entry_weight"] == 0.50
        assert kw["score_avg_win_weight"] == 0.30
        assert kw["score_win_rate_weight"] == 0.0

    def test_higher_win_rate_weight_boosts_high_wr_ticker(self):
        """Ticker B has same entry_vs_mid but higher win_rate → ranks #1 with large win_rate_weight."""
        tickers = ["A", "B"]
        # cycle so the iterator isn't exhausted by eager default-arg evaluation
        # in rolling_stats.get(ticker, compute_ticker_stats(...))
        stats_iter = cycle([
            {**_BASE_STATS, "win_rate": 0.30},
            {**_BASE_STATS, "win_rate": 0.60},
        ])

        with patch(f"{_SELECTOR_MODULE}.run_backtest", side_effect=_make_fake_backtest(tickers)), \
             patch(f"{_SELECTOR_MODULE}.build_bearish_regime_dates", return_value=None), \
             patch(f"{_SELECTOR_MODULE}.compute_ticker_stats",
                   side_effect=lambda df, **kw: next(stats_iter)), \
             patch(f"{_SELECTOR_MODULE}.compute_today_signals",
                   return_value=_make_today_signals(tickers)):

            result = select_top_n(
                n=2, tickers=tickers, lookback_days=30, opening_bars=3,
                bearish_ma200=False, stop_pct=0.15, source="alpaca",
                target_date=date(2025, 12, 2), ticker_dfs={t: pd.DataFrame() for t in tickers},
                score_entry_weight=0.40,
                score_avg_win_weight=0.20,
                score_win_rate_weight=0.30,
            )

        picks = result["picks"]
        assert len(picks) == 2
        assert picks[0]["ticker"] == "B"


class TestRelStrengthWeight:
    """score_rel_strength_weight injects cross-sectional rel_ma50_dist_pct into score_ticker."""

    def test_rel_strength_daily_context_is_injected(self):
        tickers = ["AAA", "BBB"]
        base = date(2025, 10, 1)
        trading_days = [base + timedelta(days=d) for d in range(120)
                        if (base + timedelta(days=d)).weekday() < 5]
        target = trading_days[-1]

        def make_df(close_level):
            rows = []
            for d in trading_days:
                for bar_i in range(13):
                    ts = ET.localize(
                        pd.Timestamp(d).to_pydatetime().replace(hour=9, minute=30)
                        + timedelta(minutes=bar_i * 5)
                    )
                    rows.append({"Open": close_level, "High": close_level + 0.5,
                                 "Low": close_level - 0.5, "Close": close_level,
                                 "Volume": 10_000.0, "_ts": ts})
            return pd.DataFrame(rows).set_index("_ts")

        ticker_dfs = {"AAA": make_df(110.0), "BBB": make_df(90.0)}
        captured_tickers = []

        def capture(sig, stats, **kwargs):
            captured_tickers.append((sig, kwargs.get("daily_context")))
            return score_ticker(sig, stats, **kwargs)

        with patch(f"{_SELECTOR_MODULE}.run_backtest",
                   side_effect=lambda **kw: {t: pd.DataFrame({"date": [target - timedelta(days=1)]})
                                             for t in tickers}), \
             patch(f"{_SELECTOR_MODULE}.build_bearish_regime_dates", return_value=None), \
             patch(f"{_SELECTOR_MODULE}.compute_ticker_stats", return_value=dict(_BASE_STATS)), \
             patch(f"{_SELECTOR_MODULE}.compute_today_signals",
                   return_value=_make_today_signals(tickers)), \
             patch(f"{_SELECTOR_MODULE}.score_ticker", side_effect=capture):

            select_top_n(
                n=2, tickers=tickers, lookback_days=60, opening_bars=3,
                bearish_ma200=False, stop_pct=0.15, source="alpaca",
                target_date=target, ticker_dfs=ticker_dfs,
                score_rel_strength_weight=0.10,
            )

        assert len(captured_tickers) == 2
        for _sig, ctx in captured_tickers:
            assert ctx is not None
            assert "rel_ma50_dist_pct" in ctx
            assert isinstance(ctx["rel_ma50_dist_pct"], float)


class TestEvTrend:
    """score_ev_trend_weight and ev_trend_days flow through select_top_n."""

    def test_ev_trend_weight_passed_to_score_ticker(self):
        tickers = ["AAA"]
        captured_kwargs = []

        def capture(sig, stats, **kwargs):
            captured_kwargs.append(kwargs)
            return score_ticker(sig, stats, **kwargs)

        with patch(f"{_SELECTOR_MODULE}.run_backtest", side_effect=_make_fake_backtest(tickers)), \
             patch(f"{_SELECTOR_MODULE}.build_bearish_regime_dates", return_value=None), \
             patch(f"{_SELECTOR_MODULE}.compute_ticker_stats", return_value=dict(_BASE_STATS)), \
             patch(f"{_SELECTOR_MODULE}.compute_today_signals",
                   return_value=_make_today_signals(tickers)), \
             patch(f"{_SELECTOR_MODULE}.score_ticker", side_effect=capture):

            select_top_n(
                n=1, tickers=tickers, lookback_days=30, opening_bars=3,
                bearish_ma200=False, stop_pct=0.15, source="alpaca",
                target_date=date(2025, 12, 2), ticker_dfs={t: pd.DataFrame() for t in tickers},
                score_ev_trend_weight=0.15,
            )

        assert len(captured_kwargs) == 1
        assert captured_kwargs[0]["score_ev_trend_weight"] == 0.15

    def test_ev_trend_days_passed_to_compute_ticker_stats(self):
        tickers = ["AAA"]
        captured_recent_days = []

        def fake_stats(df, **kwargs):
            captured_recent_days.append(kwargs.get("recent_days"))
            return dict(_BASE_STATS)

        with patch(f"{_SELECTOR_MODULE}.run_backtest",
                   side_effect=lambda **kw: {"AAA": pd.DataFrame({"date": [date(2025, 12, 1)]})}), \
             patch(f"{_SELECTOR_MODULE}.build_bearish_regime_dates", return_value=None), \
             patch(f"{_SELECTOR_MODULE}.compute_ticker_stats", side_effect=fake_stats), \
             patch(f"{_SELECTOR_MODULE}.compute_today_signals",
                   return_value=_make_today_signals(tickers)):

            select_top_n(
                n=1, tickers=tickers, lookback_days=30, opening_bars=3,
                bearish_ma200=False, stop_pct=0.15, source="alpaca",
                target_date=date(2025, 12, 2), ticker_dfs={t: pd.DataFrame() for t in tickers},
                ev_trend_days=7,
            )

        # First call is from the rolling_stats dict comprehension
        assert captured_recent_days[0] == 7

    def test_ev_trend_default_weight_is_zero(self):
        tickers = ["AAA"]
        captured_kwargs = []

        def capture(sig, stats, **kwargs):
            captured_kwargs.append(kwargs)
            return score_ticker(sig, stats, **kwargs)

        with patch(f"{_SELECTOR_MODULE}.run_backtest", side_effect=_make_fake_backtest(tickers)), \
             patch(f"{_SELECTOR_MODULE}.build_bearish_regime_dates", return_value=None), \
             patch(f"{_SELECTOR_MODULE}.compute_ticker_stats", return_value=dict(_BASE_STATS)), \
             patch(f"{_SELECTOR_MODULE}.compute_today_signals",
                   return_value=_make_today_signals(tickers)), \
             patch(f"{_SELECTOR_MODULE}.score_ticker", side_effect=capture):

            select_top_n(
                n=1, tickers=tickers, lookback_days=30, opening_bars=3,
                bearish_ma200=False, stop_pct=0.15, source="alpaca",
                target_date=date(2025, 12, 2), ticker_dfs={t: pd.DataFrame() for t in tickers},
            )

        assert len(captured_kwargs) == 1
        assert captured_kwargs[0]["score_ev_trend_weight"] == 0.0


def _stats_cycle(evs):
    return cycle([{**_BASE_STATS, "ev_trade": ev} for ev in evs])


class TestPassesDynamicEvGate:
    """passes_dynamic_ev_gate: per-ticker exclusion mirroring the backtest."""

    def test_disabled_gate_passes_everything(self):
        assert passes_dynamic_ev_gate({"ev_trade": -5.0}, None) is True

    def test_percentile_passes_at_or_above_floor(self):
        gate = {"mode": "percentile", "ev_floor": 0.3}
        assert passes_dynamic_ev_gate({"ev_trade": 0.3}, gate) is True

    def test_percentile_excludes_below_floor(self):
        gate = {"mode": "percentile", "ev_floor": 0.3}
        assert passes_dynamic_ev_gate({"ev_trade": 0.29}, gate) is False

    def test_threshold_passes_when_wr_and_wl_meet_floors(self):
        gate = {"mode": "threshold", "min_wr": 0.33, "min_wl": 1.5}
        stats = {"win_rate": 0.4, "avg_win_pct": 0.6, "avg_loss_pct": -0.3}
        assert passes_dynamic_ev_gate(stats, gate) is True

    def test_threshold_excludes_on_low_win_rate(self):
        gate = {"mode": "threshold", "min_wr": 0.33, "min_wl": 1.5}
        stats = {"win_rate": 0.30, "avg_win_pct": 0.6, "avg_loss_pct": -0.3}
        assert passes_dynamic_ev_gate(stats, gate) is False

    def test_threshold_excludes_on_low_win_loss_ratio(self):
        gate = {"mode": "threshold", "min_wr": 0.33, "min_wl": 1.5}
        stats = {"win_rate": 0.4, "avg_win_pct": 0.3, "avg_loss_pct": -0.3}
        assert passes_dynamic_ev_gate(stats, gate) is False


class TestDynamicEvGateInSelector:
    """select_top_n: dynamic EV gate floor derivation and exclusion."""

    def test_percentile_floor_excludes_bottom_tickers(self):
        tickers = ["AAA", "BBB", "CCC", "DDD", "EEE"]
        evs = [0.5, 0.4, 0.3, 0.2, 0.1]

        with patch(f"{_SELECTOR_MODULE}.run_backtest", side_effect=_make_fake_backtest(tickers)), \
             patch(f"{_SELECTOR_MODULE}.build_bearish_regime_dates", return_value=None), \
             patch(f"{_SELECTOR_MODULE}.compute_ticker_stats", side_effect=_stats_cycle(evs)), \
             patch(f"{_SELECTOR_MODULE}.compute_today_signals",
                   return_value=_make_today_signals(tickers)):

            result = select_top_n(
                n=5, tickers=tickers, lookback_days=60, opening_bars=3,
                bearish_ma200=False, stop_pct=0.15, source="alpaca",
                target_date=date(2025, 12, 2),
                ticker_dfs={t: pd.DataFrame() for t in tickers},
                dynamic_ev_gate=True, dg_mode="percentile",
                dg_bull_threshold=100, dg_bear_threshold=0,  # force neutral regime
            )

        # neutral excl 0.25; sorted [0.1,0.2,0.3,0.4,0.5], cutoff=int(5*0.25)=1 → floor=0.2
        assert result["dynamic_ev_gate"] == {"mode": "percentile", "ev_floor": 0.2}
        assert "EEE" in result["negative_ev"]
        picked = {p["ticker"] for p in result["picks"]}
        assert "EEE" not in picked
        assert "AAA" in picked

    def test_threshold_mode_returns_regime_floors(self):
        tickers = ["AAA", "BBB", "CCC"]

        with patch(f"{_SELECTOR_MODULE}.run_backtest", side_effect=_make_fake_backtest(tickers)), \
             patch(f"{_SELECTOR_MODULE}.build_bearish_regime_dates", return_value=None), \
             patch(f"{_SELECTOR_MODULE}.compute_ticker_stats", return_value=dict(_BASE_STATS)), \
             patch(f"{_SELECTOR_MODULE}.compute_today_signals",
                   return_value=_make_today_signals(tickers)):

            result = select_top_n(
                n=3, tickers=tickers, lookback_days=60, opening_bars=3,
                bearish_ma200=False, stop_pct=0.15, source="alpaca",
                target_date=date(2025, 12, 2),
                ticker_dfs={t: pd.DataFrame() for t in tickers},
                dynamic_ev_gate=True, dg_mode="threshold",
                dg_bull_threshold=100, dg_bear_threshold=0,  # force neutral regime
            )

        assert result["dynamic_ev_gate"] == {
            "mode": "threshold", "min_wr": 0.33, "min_wl": 1.5,
        }

    def test_gate_disabled_by_default(self):
        tickers = ["AAA", "BBB"]

        with patch(f"{_SELECTOR_MODULE}.run_backtest", side_effect=_make_fake_backtest(tickers)), \
             patch(f"{_SELECTOR_MODULE}.build_bearish_regime_dates", return_value=None), \
             patch(f"{_SELECTOR_MODULE}.compute_ticker_stats", return_value=dict(_BASE_STATS)), \
             patch(f"{_SELECTOR_MODULE}.compute_today_signals",
                   return_value=_make_today_signals(tickers)):

            result = select_top_n(
                n=2, tickers=tickers, lookback_days=60, opening_bars=3,
                bearish_ma200=False, stop_pct=0.15, source="alpaca",
                target_date=date(2025, 12, 2),
                ticker_dfs={t: pd.DataFrame() for t in tickers},
            )

        assert result["dynamic_ev_gate"] is None


class TestAdaptiveLookback:
    """select_top_n: adaptive lookback extends the backtest range."""

    def _capture_start(self, tickers, **kwargs):
        captured = {}

        def fake_bt(**bt_kwargs):
            captured.update(bt_kwargs)
            return {t: pd.DataFrame({"date": [date(2025, 12, 1)]}) for t in tickers}

        with patch(f"{_SELECTOR_MODULE}.run_backtest", side_effect=fake_bt), \
             patch(f"{_SELECTOR_MODULE}.build_bearish_regime_dates", return_value=None), \
             patch(f"{_SELECTOR_MODULE}.compute_ticker_stats", return_value=dict(_BASE_STATS)), \
             patch(f"{_SELECTOR_MODULE}.compute_today_signals",
                   return_value=_make_today_signals(tickers)):

            select_top_n(
                n=1, tickers=tickers, lookback_days=60, opening_bars=3,
                bearish_ma200=False, stop_pct=0.15, source="alpaca",
                target_date=date(2025, 12, 2),
                ticker_dfs={t: pd.DataFrame() for t in tickers},
                **kwargs,
            )
        return captured

    def test_adaptive_extends_backtest_to_longest_window(self):
        captured = self._capture_start(["AAA"], adaptive_lookback=True, al_bear_days=90)
        assert captured["start_date"] == date(2025, 12, 2) - timedelta(days=90)

    def test_disabled_adaptive_uses_standard_lookback(self):
        captured = self._capture_start(["AAA"], adaptive_lookback=False)
        assert captured["start_date"] == date(2025, 12, 2) - timedelta(days=60)


class TestPassesDirectionSplitEvGate:
    """passes_direction_split_ev_gate: directional EV floor per signal."""

    def test_disabled_gate_passes_everything(self):
        stats = {"ev_trade_bullish": -1.0, "ev_trade_bearish": -1.0}
        assert passes_direction_split_ev_gate(stats, "BULLISH", None) is True

    def test_bullish_uses_bullish_ev(self):
        ds = {"min_ev": 0.0}
        assert passes_direction_split_ev_gate(
            {"ev_trade_bullish": 0.1, "ev_trade_bearish": -0.5}, "BULLISH", ds) is True

    def test_bullish_excluded_when_bullish_ev_below_floor(self):
        ds = {"min_ev": 0.0}
        assert passes_direction_split_ev_gate(
            {"ev_trade_bullish": -0.01, "ev_trade_bearish": 0.5}, "BULLISH", ds) is False

    def test_bearish_uses_bearish_ev(self):
        ds = {"min_ev": 0.0}
        assert passes_direction_split_ev_gate(
            {"ev_trade_bullish": -0.5, "ev_trade_bearish": 0.2}, "BEARISH", ds) is True

    def test_bearish_excluded_when_bearish_ev_below_floor(self):
        ds = {"min_ev": 0.0}
        assert passes_direction_split_ev_gate(
            {"ev_trade_bullish": 0.5, "ev_trade_bearish": -0.1}, "BEARISH", ds) is False


class TestDirectionSplitEvInSelector:
    """select_top_n: direction-split EV gate state + exclusion."""

    def test_bearish_ticker_excluded_when_bearish_ev_negative(self):
        tickers = ["AAA"]
        # Combined EV positive (passes negative-EV gate) but bearish EV negative.
        stats = {
            **_BASE_STATS, "ev_trade": 0.3,
            "ev_trade_bullish": 0.6, "ev_trade_bearish": -0.2,
        }

        with patch(f"{_SELECTOR_MODULE}.run_backtest", side_effect=_make_fake_backtest(tickers)), \
             patch(f"{_SELECTOR_MODULE}.build_bearish_regime_dates", return_value=None), \
             patch(f"{_SELECTOR_MODULE}.compute_ticker_stats", return_value=stats), \
             patch(f"{_SELECTOR_MODULE}.compute_today_signals",
                   return_value=_make_today_signals(tickers, {"AAA": {"signal": "BEARISH"}})):

            result = select_top_n(
                n=1, tickers=tickers, lookback_days=60, opening_bars=3,
                bearish_ma200=False, stop_pct=0.15, source="alpaca",
                target_date=date(2025, 12, 2),
                ticker_dfs={t: pd.DataFrame() for t in tickers},
                direction_split_ev_gate=True,
            )

        assert result["direction_split_ev"] == {"min_ev": 0.0}
        assert "AAA" in result["negative_ev"]
        assert result["picks"] == []

    def test_disabled_by_default(self):
        tickers = ["AAA"]
        with patch(f"{_SELECTOR_MODULE}.run_backtest", side_effect=_make_fake_backtest(tickers)), \
             patch(f"{_SELECTOR_MODULE}.build_bearish_regime_dates", return_value=None), \
             patch(f"{_SELECTOR_MODULE}.compute_ticker_stats", return_value=dict(_BASE_STATS)), \
             patch(f"{_SELECTOR_MODULE}.compute_today_signals",
                   return_value=_make_today_signals(tickers)):

            result = select_top_n(
                n=1, tickers=tickers, lookback_days=60, opening_bars=3,
                bearish_ma200=False, stop_pct=0.15, source="alpaca",
                target_date=date(2025, 12, 2),
                ticker_dfs={t: pd.DataFrame() for t in tickers},
            )

        assert result["direction_split_ev"] is None


class TestContextResolvesWhenDataEndsBeforeTarget:
    """ADR + rel-strength must resolve from the prior trading day when the bar data
    ends the day before target_date (the live/replay case) — not silently disable."""

    def test_adr_resolved_when_target_date_absent_from_bars(self):
        # Bars end Friday; target is the following Monday (no Monday bars present).
        bars = _make_multi_day_bars()
        last_bar_date = bars.index[-1].date()
        target = last_bar_date + timedelta(days=3)  # skip weekend
        ticker_dfs = {"AAA": bars}
        raw_or_range_pct = 2.0
        scored_sigs = []

        def capture_score(sig, stats, **kwargs):
            scored_sigs.append(dict(sig))
            return score_ticker(sig, stats, **kwargs)

        with patch(f"{_SELECTOR_MODULE}.run_backtest",
                   side_effect=lambda **kw: {"AAA": pd.DataFrame({"date": [last_bar_date]})}), \
             patch(f"{_SELECTOR_MODULE}.build_bearish_regime_dates", return_value=None), \
             patch(f"{_SELECTOR_MODULE}.compute_ticker_stats", return_value=dict(_BASE_STATS)), \
             patch(f"{_SELECTOR_MODULE}.compute_today_signals", return_value={
                 "AAA": {**_BASE_SIGNAL, "or_range_pct": raw_or_range_pct},
             }), \
             patch(f"{_SELECTOR_MODULE}.score_ticker", side_effect=capture_score):

            result = select_top_n(
                n=1, tickers=["AAA"], lookback_days=30, opening_bars=3,
                bearish_ma200=False, stop_pct=0.15, source="alpaca",
                target_date=target, ticker_dfs=ticker_dfs,
                normalize_or_by_adr=True, adr_days=20,
            )

        # ADR resolved from the prior trading day -> normalization applied (not skipped).
        assert scored_sigs[0]["or_range_pct"] < raw_or_range_pct
        assert result["scoring_context"]["AAA"]["adr"] is not None

    def test_rel_strength_resolved_when_target_date_absent_from_bars(self):
        # Reproduces the Monday/post-holiday bug: a fixed target_date-1 calendar day
        # would miss the (non-trading) prior day and yield NaN rel-strength. Resolving
        # the prior *trading* day keeps rel-strength populated.
        tickers = ["AAA", "BBB"]
        bars = {t: _make_multi_day_bars() for t in tickers}
        last_bar_date = bars["AAA"].index[-1].date()
        target = last_bar_date + timedelta(days=3)  # skip weekend -> no bar on target

        with patch(f"{_SELECTOR_MODULE}.run_backtest",
                   side_effect=lambda **kw: {t: pd.DataFrame({"date": [last_bar_date]}) for t in tickers}), \
             patch(f"{_SELECTOR_MODULE}.build_bearish_regime_dates", return_value=None), \
             patch(f"{_SELECTOR_MODULE}.compute_ticker_stats", return_value=dict(_BASE_STATS)), \
             patch(f"{_SELECTOR_MODULE}.compute_today_signals",
                   return_value=_make_today_signals(tickers)):

            result = select_top_n(
                n=2, tickers=tickers, lookback_days=30, opening_bars=3,
                bearish_ma200=False, stop_pct=0.15, source="alpaca",
                target_date=target, ticker_dfs=bars,
                score_rel_strength_weight=0.15,
            )

        rel = result["scoring_context"]["AAA"]["rel_ma50_dist_pct"]
        assert rel is not None and not pd.isna(rel)

import numpy as np
import pandas as pd
import pytest

from alpha_tech_tracker.research.uptrend_formation import (
    add_ranks_and_screens,
    checkpoint_days,
    compute_feature_frames,
    excess_vs_vol_peers,
    forward_test,
    market_regime,
    summarize_years,
    winner_timeline,
)


def _days(n, start="2025-01-02"):
    return pd.bdate_range(start, periods=n)


def _panel_row(symbol, checkpoint, tier="Large", **overrides):
    row = {
        "symbol": symbol, "checkpoint": pd.Timestamp(checkpoint), "tier": tier,
        "close": 100.0, "ma50": 90.0, "ma200": 80.0, "ma200_rising": True,
        "off_52w_high": -0.05, "above_52w_low": 0.5, "new_high_10d": False,
        "ret_20d": 0.1, "ret_60d": 0.2, "ret_120d": 0.3, "ret_250d": 0.4,
        "ma50_slope": 0.02, "volume_surge": 1.0, "vol_contraction": 1.0,
        "max_1d_gain_20d": 0.03, "up_day_share_20d": 0.5, "vol_60d": 0.3,
        "fwd_ret": 0.0, "ret_to_end": 0.0,
    }
    row.update(overrides)
    return row


class TestCheckpointDays:

    def test_every_step_trading_days_within_year(self):
        days = pd.bdate_range("2025-12-29", "2026-02-27")

        result = checkpoint_days(days, 2026, 10)

        assert result[0] == pd.Timestamp("2026-01-01")
        assert result[1] == pd.Timestamp("2026-01-15")
        assert all(d.year == 2026 for d in result)


class TestComputeFeatureFrames:

    def test_steady_uptrend_sits_at_its_high_with_rising_averages(self):
        idx = _days(260)
        close = pd.DataFrame({"AAA": np.linspace(10, 36, 260)}, index=idx)

        f = compute_feature_frames(close, close * 1e6)

        last = idx[-1]
        assert f["off_52w_high"].loc[last, "AAA"] == pytest.approx(0.0)
        assert bool(f["ma200_rising"].loc[last, "AAA"])
        assert f["ma50"].loc[last, "AAA"] > f["ma200"].loc[last, "AAA"]
        assert bool(f["new_high_10d"].loc[last, "AAA"])

    def test_returns_use_only_past_closes(self):
        idx = _days(30)
        close = pd.DataFrame({"AAA": [10.0] * 20 + [20.0] * 10}, index=idx)

        f = compute_feature_frames(close, close * 1e6)

        assert f["ret_10d"].loc[idx[19], "AAA"] == pytest.approx(0.0)
        assert f["ret_10d"].loc[idx[29], "AAA"] == pytest.approx(1.0)

    def test_volume_surge_measures_shares_not_dollars(self):
        idx = _days(80)
        close = pd.DataFrame({"AAA": [10.0] * 70 + [20.0] * 10}, index=idx)
        dollar_volume = close * 1000

        f = compute_feature_frames(close, dollar_volume)

        assert f["volume_surge"].loc[idx[-1], "AAA"] == pytest.approx(1.0)


class TestAddRanksAndScreens:

    def test_trend_template_needs_price_above_rising_averages_and_relative_strength(self):
        rows = [_panel_row("LEAD", "2026-03-02", ret_120d=0.9)]
        rows += [_panel_row(f"S{i}", "2026-03-02", ret_120d=0.01 * i) for i in range(9)]
        rows.append(_panel_row("BROKEN", "2026-03-02", ret_120d=0.95, close=85.0))

        panel = add_ranks_and_screens(pd.DataFrame(rows)).set_index("symbol")

        assert panel.loc["LEAD", "trend_template"]
        assert not panel.loc["BROKEN", "trend_template"]
        assert not panel.loc["S0", "trend_template"]

    def test_breakout_needs_new_high_and_volume_surge(self):
        rows = [
            _panel_row("YES", "2026-03-02", new_high_10d=True, volume_surge=2.0),
            _panel_row("QUIET", "2026-03-02", new_high_10d=True, volume_surge=1.1),
        ]

        panel = add_ranks_and_screens(pd.DataFrame(rows)).set_index("symbol")

        assert panel.loc["YES", "breakout"]
        assert not panel.loc["QUIET", "breakout"]

    def test_lower_volatility_contraction_ranks_higher(self):
        rows = [_panel_row("TIGHT", "2026-03-02", vol_contraction=0.5),
                _panel_row("LOOSE", "2026-03-02", vol_contraction=2.0)]

        panel = add_ranks_and_screens(pd.DataFrame(rows)).set_index("symbol")

        assert panel.loc["TIGHT", "vol_contraction_pct"] > panel.loc["LOOSE", "vol_contraction_pct"]

    def test_forward_winner_is_top_5_percent_within_tier(self):
        rows = [_panel_row(f"S{i}", "2026-03-02", fwd_ret=i / 100) for i in range(40)]

        panel = add_ranks_and_screens(pd.DataFrame(rows)).set_index("symbol")

        assert panel["fwd_win"].sum() == 2
        assert panel.loc["S39", "fwd_win"] == 1.0


class TestForwardTest:

    def test_lift_compares_flagged_hit_rate_to_tier_base_rate(self):
        rows = [_panel_row(f"S{i}", "2026-03-02", fwd_ret=i / 100, new_high_10d=(i >= 36), volume_surge=2.0)
                for i in range(40)]
        panel = add_ranks_and_screens(pd.DataFrame(rows))

        result = forward_test(panel)

        breakout = result[(result["rule"] == "breakout") & (result["tier"] == "All")].iloc[0]
        assert breakout["hit_rate"] == pytest.approx(0.5)
        assert breakout["lift"] == pytest.approx(10.0)
        assert breakout["recall"] == pytest.approx(1.0)
        assert breakout["loss_rate"] == pytest.approx(0.0)

    def test_vol_matched_lift_is_one_when_edge_is_only_volatility(self):
        rows = []
        for i in range(40):
            wild = i >= 20
            rows.append(_panel_row(f"S{i}", "2026-03-02", vol_60d=1.0 + i / 100 if wild else 0.2 + i / 1000,
                                   fwd_ret=(i / 100) if wild else 0.0, new_high_10d=wild, volume_surge=2.0))
        panel = add_ranks_and_screens(pd.DataFrame(rows))

        result = forward_test(panel)

        breakout = result[(result["rule"] == "breakout") & (result["tier"] == "All")].iloc[0]
        assert breakout["lift"] == pytest.approx(2.0)
        assert breakout["vol_matched_lift"] == pytest.approx(1.0)


class TestWinnerTimeline:

    def test_gain_ahead_share_after_first_screen_hit(self):
        idx = pd.bdate_range("2025-12-31", periods=4)
        daily_close = pd.DataFrame({"WIN": [10.0, 20.0, 40.0, 40.0]}, index=idx)
        panel = pd.DataFrame([
            _panel_row("WIN", idx[1], close=20.0, trend_template=False, breakout=False, early_momentum=False),
            _panel_row("WIN", idx[2], close=40.0, trend_template=True, breakout=False, early_momentum=True),
        ])
        winners = pd.DataFrame([{"tier": "Large", "rank": 1, "symbol": "WIN"}])

        result = winner_timeline(panel, winners, daily_close, pd.Series({"WIN": 10.0})).iloc[0]

        assert result["ytd_pct"] == pytest.approx(300.0)
        assert result["trend_template_ytd_at_first_pct"] == pytest.approx(300.0)
        assert result["trend_template_gain_ahead_share"] == pytest.approx(0.0)
        assert result["breakout_first"] is None
        assert result["biggest_day_pct"] == pytest.approx(100.0)


class TestMarketRegime:

    def test_above_200_day_average_in_uptrend_only(self):
        idx = _days(400)
        close = pd.Series(np.r_[np.linspace(100, 200, 300), np.linspace(200, 100, 100)], index=idx)

        regime = market_regime(close)

        assert bool(regime.iloc[299])
        assert not bool(regime.iloc[-1])


class TestExcessVsVolPeers:

    def test_flagged_return_measured_against_same_volatility_bucket(self):
        rows = []
        for i in range(10):
            rows.append(_panel_row(f"S{i}", "2026-03-02", ret_60d=1.0 if i == 0 else 0.01 * i, vol_60d=0.5,
                                   fwd_ret=0.21 if i == 0 else 0.0))
        panel = add_ranks_and_screens(pd.DataFrame(rows))
        panel["vol_bucket"] = 0.0
        regime = pd.Series({pd.Timestamp("2026-03-02"): True})

        result = excess_vs_vol_peers(panel, regime).set_index("rule")

        peer_mean = np.log(1.21) / 10
        leader_and_runner_up = ((np.log(1.21) - peer_mean) + (0.0 - peer_mean)) / 2
        assert result.loc["mom60_top10", "flagged"] == 2
        assert result.loc["mom60_top10", "excess"] == pytest.approx(leader_and_runner_up)
        assert bool(result.loc["mom60_top10", "index_above_ma200"])


class TestSummarizeYears:

    def test_combines_forward_tests_and_capture_stats_per_year(self, tmp_path):
        for year in (2024, 2025):
            folder = tmp_path / str(year)
            folder.mkdir()
            pd.DataFrame([{"rule": "early_momentum", "tier": "Large", "flagged_per_checkpoint": 80.0, "hit_rate": 0.12,
                           "loss_rate": 0.1, "lift": 2.4, "vol_matched_lift": 1.3}]).to_csv(folder / "forward_test.csv",
                                                                                           index=False)
            screens = ("trend_template", "breakout", "early_momentum")
            row = {f"{s}_first": "2025-01-02" if s == "trend_template" else None for s in screens}
            row.update({f"{s}_gain_ahead_share": 0.7 for s in screens})
            pd.DataFrame([row]).to_csv(folder / "winner_timeline.csv", index=False)
            pd.DataFrame([{"checkpoint": f"{year}-03-02", "tier": "Large", "excess": 0.01, "flagged": 5,
                           "rule": "mom60_top10", "index_above_ma200": True}]).to_csv(
                folder / "excess_vs_vol_peers.csv", index=False)

        summary = summarize_years(str(tmp_path), [2024, 2025])

        lifts = summary[summary["rule"] == "early_momentum"].set_index("year")["vol_matched_lift"]
        capture = summary[summary["rule"] == "capture:trend_template"].set_index("year")
        assert lifts.to_dict() == {2024: 1.3, 2025: 1.3}
        assert capture.loc[2025, "caught"] == 1
        assert (tmp_path / "summary_2024_2025.csv").exists()
        assert (tmp_path / "excess_by_regime_2024_2025.csv").exists()

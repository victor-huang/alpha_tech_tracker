from datetime import date

import pandas as pd
import pytest
from alpaca.data.enums import DataFeed

from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.ticker_stats_report import (
    clamp_end_for_sip,
    classify_daily_trend,
    latest_sip_date,
    resolve_followthrough_threshold,
)

MARKET_TZ = "America/New_York"


def _et(stamp: str):
    return pd.Timestamp(stamp, tz=MARKET_TZ)


class TestLatestSipDate:
    def test_returns_today_once_extended_hours_have_ended(self):
        assert latest_sip_date(_et("2026-08-21 20:00")) == date(2026, 8, 21)

    def test_returns_today_late_in_the_evening(self):
        assert latest_sip_date(_et("2026-08-21 23:30")) == date(2026, 8, 21)

    def test_returns_yesterday_during_the_session(self):
        assert latest_sip_date(_et("2026-08-21 14:15")) == date(2026, 8, 20)

    def test_returns_yesterday_just_before_extended_hours_end(self):
        assert latest_sip_date(_et("2026-08-21 19:59")) == date(2026, 8, 20)

    def test_returns_yesterday_before_the_open(self):
        assert latest_sip_date(_et("2026-08-21 06:30")) == date(2026, 8, 20)


class TestClampEndForSip:
    def test_leaves_iex_requests_untouched(self):
        assert clamp_end_for_sip(
            date(2026, 8, 21), DataFeed.IEX, _et("2026-08-21 10:00")
        ) == date(2026, 8, 21)

    def test_allows_today_after_extended_hours(self):
        assert clamp_end_for_sip(
            date(2026, 8, 21), DataFeed.SIP, _et("2026-08-21 20:05")
        ) == date(2026, 8, 21)

    def test_pulls_today_back_during_the_session(self):
        assert clamp_end_for_sip(
            date(2026, 8, 21), DataFeed.SIP, _et("2026-08-21 11:00")
        ) == date(2026, 8, 20)

    def test_clamps_a_future_end_date_to_the_latest_available(self):
        assert clamp_end_for_sip(
            date(2026, 12, 31), DataFeed.SIP, _et("2026-08-21 21:00")
        ) == date(2026, 8, 21)

    def test_leaves_a_past_end_date_untouched(self):
        assert clamp_end_for_sip(
            date(2026, 7, 1), DataFeed.SIP, _et("2026-08-21 11:00")
        ) == date(2026, 7, 1)

    def test_uses_the_current_time_when_none_is_given(self, mocker):
        mocker.patch(
            "alpha_tech_tracker.op_momentum_strategy.analysis_scripts."
            "ticker_stats_report.pd.Timestamp.now",
            return_value=_et("2026-08-21 20:30"),
        )

        assert clamp_end_for_sip(date(2026, 8, 25), DataFeed.SIP) == date(2026, 8, 21)


class TestResolveFollowthroughThreshold:
    def test_scales_to_the_adr_when_a_factor_is_given(self):
        threshold, basis = resolve_followthrough_threshold(
            {"avg_range_pct": 8.0}, 0.8, 0.25
        )

        assert (threshold, basis) == (2.0, "0.25xADR")

    def test_falls_back_to_the_flat_bar_without_a_factor(self):
        assert resolve_followthrough_threshold({"avg_range_pct": 8.0}, 0.8, 0) == (
            0.8,
            "flat",
        )

    def test_falls_back_to_the_flat_bar_without_daily_history(self):
        assert resolve_followthrough_threshold(None, 0.8, 0.25) == (0.8, "flat")

    def test_falls_back_when_the_adr_is_zero(self):
        assert resolve_followthrough_threshold({"avg_range_pct": 0.0}, 0.8, 0.25) == (
            0.8,
            "flat",
        )


@pytest.mark.parametrize(
    "stamp,expected",
    [
        ("2026-08-22 21:00", date(2026, 8, 22)),
        ("2026-08-23 12:00", date(2026, 8, 22)),
    ],
)
class TestWeekendBehaviour:
    def test_weekend_dates_resolve_without_special_casing(self, stamp, expected):
        assert latest_sip_date(_et(stamp)) == expected


def _daily(closes):
    return pd.DataFrame(
        {"Close": closes},
        index=pd.date_range("2024-01-01", periods=len(closes), freq="B"),
    )


def _label(closes):
    states = classify_daily_trend(_daily(closes))
    return states[max(states)]["label"]


class TestClassifyDailyTrend:
    def test_steady_advance_is_strong_up(self):
        assert _label([100 + i * 0.5 for i in range(260)]) == "STRONG_UP"

    def test_steady_decline_is_strong_down(self):
        assert _label([300 - i * 0.5 for i in range(260)]) == "STRONG_DOWN"

    def test_advance_then_drop_below_ma50_is_up_pullback(self):
        rising = [100 + i * 0.5 for i in range(260)]
        dip = rising[-1] * 0.80
        assert _label(rising + [dip, dip]) == "UP_PULLBACK"

    def test_decline_then_pop_above_ma50_is_down_bounce(self):
        falling = [300 - i * 0.5 for i in range(260)]
        pop = falling[-1] * 1.30
        assert _label(falling + [pop, pop]) == "DOWN_BOUNCE"

    def test_old_advance_now_flat_above_ma200_is_uptrend(self):
        assert _label([100 + i * 0.5 for i in range(150)] + [175.0] * 110) == "UPTREND"

    def test_old_decline_now_flat_below_ma200_is_downtrend(self):
        assert _label([300 - i * 0.5 for i in range(150)] + [225.0] * 110) == "DOWNTREND"

    def test_conflicting_slopes_are_mixed(self):
        declining = [300 - i * 0.5 for i in range(220)]
        rally = [declining[-1] + i * 1.0 for i in range(1, 21)]
        assert _label(declining + rally) == "MIXED"

    def test_returns_empty_without_enough_history(self):
        assert classify_daily_trend(_daily([100.0] * 50)) == {}

    def test_returns_empty_for_an_empty_frame(self):
        assert classify_daily_trend(pd.DataFrame()) == {}

    def test_reports_distance_from_both_moving_averages(self):
        states = classify_daily_trend(_daily([100 + i * 0.5 for i in range(260)]))
        row = states[max(states)]

        assert row["vs_ma50_pct"] > 0
        assert row["vs_ma200_pct"] > row["vs_ma50_pct"]

    def test_flat_band_widens_with_a_larger_threshold(self):
        gentle = [100 + i * 0.02 for i in range(260)]
        assert classify_daily_trend(_daily(gentle), flat_pct=0.01)[
            max(classify_daily_trend(_daily(gentle), flat_pct=0.01))
        ]["slopes"][20] == "up"
        assert classify_daily_trend(_daily(gentle), flat_pct=5.0)[
            max(classify_daily_trend(_daily(gentle), flat_pct=5.0))
        ]["slopes"][20] == "flat"

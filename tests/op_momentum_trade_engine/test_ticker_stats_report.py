from datetime import date

import pandas as pd
import pytest
from alpaca.data.enums import DataFeed

from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.ticker_stats_report import (
    aggregate_option_volume,
    clamp_end_for_sip,
    classify_daily_trend,
    compute_option_volume_stats,
    compute_week_pin_price,
    fetch_option_volume_stats,
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


class TestComputeWeekPinPrice:
    @pytest.fixture
    def daily(self):
        index = pd.bdate_range("2026-07-01", "2026-09-25").date
        return pd.DataFrame({"Close": range(1, len(index) + 1)}, index=index, dtype=float)

    def test_weekday_pins_on_prior_friday(self, daily):
        _, pin_asof = compute_week_pin_price(daily, date(2026, 9, 23))

        assert pin_asof == date(2026, 9, 18)

    def test_sunday_pins_on_friday_just_closed(self, daily):
        _, pin_asof = compute_week_pin_price(daily, date(2026, 9, 27))

        assert pin_asof == date(2026, 9, 25)

    def test_saturday_pins_on_friday_just_closed(self, daily):
        _, pin_asof = compute_week_pin_price(daily, date(2026, 9, 26))

        assert pin_asof == date(2026, 9, 25)

    def test_pin_is_ma_of_last_n_closes(self, daily):
        pin_price, _ = compute_week_pin_price(daily, date(2026, 9, 27), ma_period=3)

        last_three = daily["Close"].iloc[-3:]
        assert pin_price == pytest.approx(last_three.mean())


def _contract(symbol, expiry, strike, option_type="call"):
    return {"symbol": symbol, "expiration_date": expiry, "strike_price": strike, "option_type": option_type}


class TestAggregateOptionVolume:
    @pytest.fixture
    def chain(self):
        strikes = [float(k) for k in range(90, 111)]
        return [_contract(f"C{int(k)}", "2026-10-16", k) for k in strikes] + \
            [_contract(f"P{int(k)}", "2026-10-16", k, "put") for k in strikes]

    def test_sums_calls_and_puts_separately(self, chain):
        volumes = {"C100": {date(2026, 10, 9): 30}, "P100": {date(2026, 10, 9): 10}}

        result = aggregate_option_volume(chain, volumes, {date(2026, 10, 9): 100.0}, strikes_around=2)

        assert result[date(2026, 10, 9)] == {"call": 30, "put": 10}

    def test_excludes_strikes_outside_the_band(self, chain):
        volumes = {"C103": {date(2026, 10, 9): 50}}

        result = aggregate_option_volume(chain, volumes, {date(2026, 10, 9): 100.0}, strikes_around=2)

        assert result.get(date(2026, 10, 9), {"call": 0})["call"] == 0

    def test_band_follows_each_sessions_own_close(self, chain):
        volumes = {"C105": {date(2026, 10, 8): 40, date(2026, 10, 9): 40}}
        closes = {date(2026, 10, 8): 100.0, date(2026, 10, 9): 105.0}

        result = aggregate_option_volume(chain, volumes, closes, strikes_around=2)

        assert result.get(date(2026, 10, 8), {"call": 0})["call"] == 0
        assert result[date(2026, 10, 9)]["call"] == 40

    def test_counts_same_day_expiry(self, chain):
        volumes = {"C100": {date(2026, 10, 16): 25}}

        result = aggregate_option_volume(chain, volumes, {date(2026, 10, 16): 100.0}, strikes_around=2)

        assert result[date(2026, 10, 16)]["call"] == 25

    def test_excludes_contracts_beyond_max_dte(self, chain):
        volumes = {"C100": {date(2026, 9, 1): 25}}

        result = aggregate_option_volume(chain, volumes, {date(2026, 9, 1): 100.0},
                                         max_dte=30, strikes_around=2)

        assert date(2026, 9, 1) not in result


class TestComputeOptionVolumeStats:
    @staticmethod
    def _series(days, call=100, put=100):
        return {d: {"call": call, "put": put} for d in days}

    def test_ratio_against_prior_sessions_average(self):
        per_session = self._series(pd.bdate_range("2026-09-28", "2026-10-08").date)
        per_session[date(2026, 10, 9)] = {"call": 300, "put": 100}

        stats = compute_option_volume_stats(per_session, date(2026, 10, 9), baseline_sessions=5)

        assert stats["call_ratio"] == pytest.approx(3.0)
        assert stats["put_ratio"] == pytest.approx(1.0)
        assert stats["total_ratio"] == pytest.approx(2.0)

    def test_flags_each_side_at_or_above_spike_multiple(self):
        per_session = self._series(pd.bdate_range("2026-09-28", "2026-10-08").date)
        per_session[date(2026, 10, 9)] = {"call": 300, "put": 100}

        stats = compute_option_volume_stats(per_session, date(2026, 10, 9), spike_mult=2.0)

        assert stats["spike_sides"] == ["total", "call"]

    def test_monthly_expiry_day_left_out_of_baseline(self):
        per_session = self._series(pd.bdate_range("2026-09-14", "2026-09-25").date)
        per_session[date(2026, 9, 18)] = {"call": 10_000, "put": 10_000}

        stats = compute_option_volume_stats(per_session, date(2026, 9, 25), baseline_sessions=10)

        assert stats["total_avg"] == pytest.approx(200)

    def test_marks_a_monthly_expiry_session(self):
        per_session = self._series(pd.bdate_range("2026-09-08", "2026-09-18").date)

        stats = compute_option_volume_stats(per_session, date(2026, 9, 18))

        assert stats["monthly_expiry_session"] is True

    def test_returns_none_with_a_single_session(self):
        assert compute_option_volume_stats(self._series([date(2026, 10, 9)]), date(2026, 10, 9)) is None


class TestFetchOptionVolumeStats:
    @pytest.fixture
    def daily(self):
        index = pd.bdate_range("2026-09-28", "2026-10-09")
        return pd.DataFrame({"Close": [100.0] * len(index)}, index=index)

    @pytest.fixture
    def client(self, mocker):
        client = mocker.Mock()
        client.get_option_contracts_in_window.return_value = [
            _contract(f"C{k}", "2026-10-16", float(k)) for k in range(90, 111)
        ]
        client.get_option_daily_volumes.side_effect = lambda symbols, start, end: {
            symbol: {d: 100 for d in pd.bdate_range(start, end).date} for symbol in symbols
        }
        return client

    def test_fetches_volume_only_for_strikes_inside_the_band(self, client, daily):
        fetch_option_volume_stats(client, "TSLA", daily, date(2026, 10, 9), 5, 45, 2, 2.0)

        symbols = client.get_option_daily_volumes.call_args.args[0]
        assert sorted(symbols) == ["C100", "C101", "C102", "C98", "C99"]

    def test_sums_the_band_for_the_session(self, client, daily):
        stats = fetch_option_volume_stats(client, "TSLA", daily, date(2026, 10, 9), 5, 45, 2, 2.0)

        assert stats["calls"] == 500
        assert stats["total_ratio"] == pytest.approx(1.0)

    def test_returns_error_when_the_client_raises(self, client, daily):
        client.get_option_contracts_in_window.side_effect = RuntimeError("rate limited")

        stats = fetch_option_volume_stats(client, "TSLA", daily, date(2026, 10, 9), 5, 45, 2, 2.0)

        assert stats == {"error": "RuntimeError: rate limited"}

    def test_returns_error_without_daily_bars(self, client):
        stats = fetch_option_volume_stats(
            client, "TSLA", pd.DataFrame(), date(2026, 10, 9), 5, 45, 2, 2.0
        )

        assert stats == {"error": "no daily bars"}

from datetime import date, time

import pandas as pd
import pytest

from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.intraday_leg_timing import (
    best_group,
    bucket_start,
    find_session_legs,
    prior_session_adr,
    summarize_group,
    zone_label,
)

MARKET_TZ = "America/New_York"


def _session(start, ohlc_rows):
    index = pd.date_range(pd.Timestamp(start, tz=MARKET_TZ), periods=len(ohlc_rows), freq="5min")
    return pd.DataFrame(ohlc_rows, columns=["Open", "High", "Low", "Close"], index=index)


def _leg(session=date(2026, 9, 1), direction="up", capture_pct=0.5, retraced=True):
    return {
        "session": session,
        "direction": direction,
        "move_pct": 2.0,
        "move_usd": 2.0,
        "adr_multiple": 0.5,
        "mins_to_peak": 15,
        "mins_to_retrace": 25,
        "retraced": retraced,
        "capture_pct": capture_pct,
    }


class TestFindSessionLegs:
    def test_detects_up_leg_that_runs_until_20pct_retracement(self):
        frame = _session("2026-09-01 10:00", [
            (100.0, 101.0, 100.0, 101.0),
            (101.0, 102.0, 101.0, 102.0),
            (102.0, 104.0, 102.0, 104.0),
            (104.0, 104.5, 103.5, 104.0),
            (104.0, 104.0, 103.0, 103.2),
        ])

        up = [leg for leg in find_session_legs(frame, min_move_pct=1.5) if leg["direction"] == "up"]

        assert len(up) == 1
        assert up[0]["start_price"] == 100.0
        assert up[0]["extreme_price"] == 104.5
        assert up[0]["move_pct"] == pytest.approx(4.5)
        assert up[0]["mins_to_confirm"] == 10
        assert up[0]["mins_to_peak"] == 20
        assert up[0]["mins_to_retrace"] == 25
        assert up[0]["exit_price"] == pytest.approx(103.6)
        assert up[0]["capture_pct"] == pytest.approx((103.6 - 102.0) / 102.0 * 100)

    def test_detects_down_leg_with_prices_signed_back_to_real_values(self):
        frame = _session("2026-09-01 09:30", [
            (100.0, 100.0, 99.0, 99.0),
            (99.0, 99.0, 97.0, 97.0),
            (97.0, 99.0, 97.0, 98.8),
        ])

        down = [leg for leg in find_session_legs(frame, min_move_pct=2.0) if leg["direction"] == "down"]

        assert len(down) == 1
        assert down[0]["extreme_price"] == 97.0
        assert down[0]["entry_price"] == 97.0
        assert down[0]["exit_price"] == pytest.approx(97.6)
        assert down[0]["capture_pct"] == pytest.approx((97.0 - 97.6) / 97.0 * 100)

    def test_ignores_move_that_needs_longer_than_the_impulse_window(self):
        frame = _session("2026-09-01 10:00", [
            (100.0, 100.5, 100.0, 100.5),
            (100.5, 101.0, 100.5, 101.0),
            (101.0, 101.4, 101.0, 101.4),
            (101.4, 103.0, 101.4, 103.0),
        ])

        legs = find_session_legs(frame, min_move_pct=2.5, impulse_bars=3)

        assert [leg for leg in legs if leg["start_price"] == 100.0] == []

    def test_ignores_move_that_gives_back_20pct_before_qualifying(self):
        frame = _session("2026-09-01 10:00", [
            (100.0, 101.0, 100.0, 101.0),
            (101.0, 101.0, 100.5, 100.6),
            (100.6, 102.1, 100.6, 102.1),
        ])

        legs = find_session_legs(frame, min_move_pct=2.0, impulse_bars=3)

        assert [leg for leg in legs if leg["start_price"] == 100.0] == []

    def test_marks_leg_unretraced_when_it_runs_into_the_close(self):
        frame = _session("2026-09-01 15:40", [
            (100.0, 102.0, 100.0, 102.0),
            (102.0, 103.0, 102.0, 103.0),
            (103.0, 104.0, 103.0, 104.0),
        ])

        up = [leg for leg in find_session_legs(frame, min_move_pct=1.5) if leg["direction"] == "up"]

        assert up[0]["retraced"] is False
        assert up[0]["exit_price"] == 104.0

    def test_exit_uses_bar_open_when_price_gaps_through_the_retracement_level(self):
        frame = _session("2026-09-01 10:00", [
            (100.0, 103.0, 100.0, 103.0),
            (101.0, 101.5, 100.8, 101.2),
        ])

        up = [leg for leg in find_session_legs(frame, min_move_pct=2.0) if leg["direction"] == "up"]

        assert up[0]["exit_price"] == 101.0

    def test_resumes_scanning_after_a_leg_ends_so_one_move_counts_once(self):
        frame = _session("2026-09-01 10:00", [
            (100.0, 101.0, 100.0, 101.0),
            (101.0, 102.0, 101.0, 102.0),
            (102.0, 103.0, 102.0, 103.0),
            (103.0, 103.0, 102.0, 102.2),
        ])

        up = [leg for leg in find_session_legs(frame, min_move_pct=1.5) if leg["direction"] == "up"]

        assert len(up) == 1

    def test_close_basis_ignores_a_wick_that_gives_back_20pct(self):
        frame = _session("2026-09-01 10:00", [
            (100.0, 101.0, 100.0, 101.0),
            (101.0, 102.0, 101.0, 102.0),
            (102.0, 102.5, 101.2, 102.4),
            (102.4, 103.0, 102.4, 103.0),
            (103.0, 103.0, 102.0, 102.2),
        ])

        up = [
            leg for leg in find_session_legs(frame, min_move_pct=1.5, close_basis=True)
            if leg["direction"] == "up"
        ]

        assert len(up) == 1
        assert up[0]["extreme_price"] == 103.0
        assert up[0]["mins_to_retrace"] == 25
        assert up[0]["exit_price"] == 102.2

    def test_wick_basis_ends_leg_on_the_bar_whose_low_gives_back_20pct(self):
        frame = _session("2026-09-01 10:00", [
            (100.0, 101.0, 100.0, 101.0),
            (101.0, 102.0, 101.0, 102.0),
            (102.0, 102.5, 101.2, 102.4),
        ])

        up = [leg for leg in find_session_legs(frame, min_move_pct=1.5) if leg["direction"] == "up"]

        assert up[0]["mins_to_retrace"] == 15

    def test_buckets_leg_by_its_start_bar(self):
        frame = _session("2026-09-01 09:55", [
            (100.0, 102.0, 100.0, 102.0),
            (102.0, 102.0, 101.0, 101.0),
        ])

        up = [leg for leg in find_session_legs(frame, min_move_pct=1.5) if leg["direction"] == "up"]

        assert up[0]["bucket"] == time(9, 45)
        assert up[0]["zone"] == "open 30m"


class TestPriorSessionAdr:
    def test_averages_only_sessions_before_the_scored_one(self):
        sessions = [
            (date(2026, 9, 1), _session("2026-09-01 09:30", [(100.0, 102.0, 100.0, 101.0)])),
            (date(2026, 9, 2), _session("2026-09-02 09:30", [(100.0, 104.0, 100.0, 101.0)])),
            (date(2026, 9, 3), _session("2026-09-03 09:30", [(100.0, 150.0, 100.0, 101.0)])),
        ]

        adr = prior_session_adr(sessions, lookback=2)

        assert adr == {date(2026, 9, 3): pytest.approx(3.0)}


class TestBucketStart:
    @pytest.mark.parametrize("clock, bucket_minutes, expected", [
        (time(9, 30), 15, time(9, 30)),
        (time(9, 44), 15, time(9, 30)),
        (time(9, 45), 15, time(9, 45)),
        (time(13, 20), 30, time(13, 0)),
    ])
    def test_floors_to_bucket_anchored_on_open(self, clock, bucket_minutes, expected):
        assert bucket_start(clock, bucket_minutes) == expected


class TestZoneLabel:
    @pytest.mark.parametrize("clock, expected", [
        (time(9, 55), "open 30m"),
        (time(10, 0), "morning"),
        (time(12, 0), "midday"),
        (time(14, 55), "afternoon"),
        (time(15, 50), "power hour"),
    ])
    def test_maps_clock_time_to_zone(self, clock, expected):
        assert zone_label(clock) == expected


class TestSummarizeGroup:
    def test_capture_per_session_divides_by_all_sessions(self):
        legs = [_leg(capture_pct=1.0), _leg(capture_pct=-0.2)]

        summary = summarize_group(legs, session_count=4)

        assert summary["capture_per_session_pct"] == pytest.approx(0.2)

    def test_session_hit_rate_counts_distinct_sessions(self):
        legs = [_leg(session=date(2026, 9, 1)), _leg(session=date(2026, 9, 1)), _leg(session=date(2026, 9, 2))]

        summary = summarize_group(legs, session_count=4)

        assert summary["session_hit_pct"] == pytest.approx(50.0)

    def test_returns_none_without_legs(self):
        assert summarize_group([], session_count=4) is None


class TestBestGroup:
    def test_picks_highest_capture_per_session_among_groups_with_enough_legs(self):
        summary = {
            "open 30m": {"legs": 2, "capture_per_session_pct": 0.9},
            "morning": {"legs": 6, "capture_per_session_pct": 0.3},
            "midday": {"legs": 8, "capture_per_session_pct": 0.1},
        }

        assert best_group(summary, min_legs=5)[0] == "morning"

    def test_returns_none_when_no_group_has_enough_legs(self):
        assert best_group({"morning": {"legs": 1, "capture_per_session_pct": 0.3}}, min_legs=5) == (None, None)

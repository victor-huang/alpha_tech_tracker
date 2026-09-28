from datetime import date, time

import pandas as pd
import pytest

from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.daily_longest_leg import (
    session_longest_legs,
    summarize_kind,
    top_legs_for_day,
)

MARKET_TZ = "America/New_York"


def _session(start, ohlc_rows):
    index = pd.date_range(pd.Timestamp(start, tz=MARKET_TZ), periods=len(ohlc_rows), freq="5min")
    return pd.DataFrame(ohlc_rows, columns=["Open", "High", "Low", "Close"], index=index)


def _closes_session(start, closes, first_open):
    rows, prev = [], first_open
    for close in closes:
        rows.append((prev, max(prev, close), min(prev, close), close))
        prev = close
    return _session(start, rows)


class TestSessionLongestLegsCloseBasis:
    def test_leg_survives_a_pullback_under_the_retrace_limit(self):
        frame = _closes_session("2026-09-01 10:00", [101, 102, 103, 104, 103.2, 105, 106, 104], 100)

        legs = session_longest_legs(frame, adr_pct=5.0, close_basis=True)

        assert legs["up"]["start_price"] == 100
        assert legs["up"]["end_price"] == 106
        assert legs["up"]["duration_mins"] == 35
        assert legs["up"]["max_retrace"] == pytest.approx(0.2)

    def test_pullback_over_the_retrace_limit_splits_the_leg(self):
        frame = _closes_session("2026-09-01 10:00", [102, 104, 102.5, 103, 106, 107], 100)

        legs = session_longest_legs(frame, adr_pct=5.0, close_basis=True)

        assert legs["up"]["start_price"] == 102.5
        assert legs["up"]["end_price"] == 107

    def test_retrace_limit_is_ignored_until_leg_reaches_min_progress(self):
        frame = _closes_session("2026-09-01 10:00", [100.2, 100.05, 102, 103], 100)

        legs = session_longest_legs(frame, adr_pct=5.0, close_basis=True, min_progress_adr=0.1)

        assert legs["up"]["start_price"] == 100
        assert legs["up"]["end_price"] == 103

    def test_finds_down_leg_with_real_prices(self):
        frame = _closes_session("2026-09-01 13:30", [99, 97, 97.5, 95, 96], 100)

        legs = session_longest_legs(frame, adr_pct=5.0, close_basis=True)

        assert legs["down"]["start_price"] == 100
        assert legs["down"]["end_price"] == 95
        assert legs["down"]["move_pct"] == pytest.approx(5.0)
        assert legs["down"]["start_zone"] == "afternoon"

    def test_biggest_is_the_larger_of_up_and_down(self):
        frame = _closes_session("2026-09-01 10:00", [101, 102, 99, 96, 94], 100)

        legs = session_longest_legs(frame, adr_pct=5.0, close_basis=True)

        assert legs["biggest"]["direction"] == "down"

    def test_rank_by_duration_prefers_the_slower_leg_that_clears_min_move(self):
        frame = _closes_session(
            "2026-09-01 10:00", [104, 101, 101.5, 102, 102.5, 103, 103.5], 100
        )

        by_move = session_longest_legs(frame, adr_pct=5.0, close_basis=True)
        by_duration = session_longest_legs(
            frame, adr_pct=5.0, close_basis=True, rank_by="duration", min_move_adr=0.25
        )

        assert by_move["up"]["end_price"] == 104
        assert by_duration["up"]["start_price"] == 101
        assert by_duration["up"]["end_price"] == 103.5
        assert by_duration["up"]["duration_mins"] == 25


class TestSessionLongestLegsWickBasis:
    def test_anchors_up_leg_on_the_start_bar_low(self):
        frame = _session("2026-09-01 09:30", [
            (100.0, 100.5, 99.0, 100.4),
            (100.4, 102.0, 100.3, 101.9),
            (101.9, 103.0, 101.8, 102.9),
        ])

        legs = session_longest_legs(frame, adr_pct=5.0)

        assert legs["up"]["start_price"] == 99.0
        assert legs["up"]["end_price"] == 103.0
        assert legs["up"]["start_bucket"] == time(9, 30)

    def test_wick_through_the_retrace_limit_breaks_the_leg(self):
        frame = _session("2026-09-01 09:30", [
            (100.0, 102.0, 100.0, 102.0),
            (102.0, 102.2, 101.0, 102.1),
            (102.1, 103.0, 102.0, 103.0),
        ])

        legs = session_longest_legs(frame, adr_pct=5.0)

        assert legs["up"]["start_price"] == 100.0
        assert legs["up"]["end_price"] == 102.0


class TestSummarizeKind:
    def _leg(self, start, zone, session=date(2026, 9, 1)):
        stamp = pd.Timestamp(f"2026-09-01 {start}", tz=MARKET_TZ)
        return {
            "session": session, "start_time": stamp, "end_time": stamp + pd.Timedelta(minutes=30),
            "start_zone": zone, "end_zone": zone, "start_bucket": time(stamp.hour, stamp.minute),
            "duration_mins": 30, "move_pct": 2.0, "move_usd": 2.0, "adr_multiple": 0.5,
            "day_range_share": 0.6, "max_retrace": 0.1,
        }

    def test_start_zone_share_is_percent_of_legs(self):
        legs = [self._leg("09:30", "open 30m"), self._leg("09:45", "open 30m"), self._leg("14:00", "afternoon")]

        summary = summarize_kind(legs)

        assert summary["start_zone_share"]["open 30m"] == pytest.approx(200 / 3)
        assert summary["start_zone_share"]["midday"] == 0

    def test_median_start_is_a_clock_time(self):
        legs = [self._leg("09:30", "open 30m"), self._leg("10:00", "morning"), self._leg("14:00", "afternoon")]

        assert summarize_kind(legs)["median_start"] == time(10, 0)

    def test_returns_none_without_legs(self):
        assert summarize_kind([]) is None


class TestTopLegsForDay:
    DAY = date(2026, 9, 25)

    def _leg(self, session, kind="up", move_pct=2.0, move_usd=4.0, adr_multiple=0.5):
        stamp = pd.Timestamp(f"{session} 09:35", tz=MARKET_TZ)
        return {
            "session": session, "kind": kind, "start_time": stamp,
            "end_time": stamp + pd.Timedelta(minutes=40), "duration_mins": 40,
            "start_price": 200.0, "end_price": 204.0, "move_pct": move_pct,
            "move_usd": move_usd, "adr_multiple": adr_multiple,
        }

    def _report(self, legs):
        return {"sessions": len({leg["session"] for leg in legs}), "legs": legs}

    def test_ranks_tickers_by_percent_move_on_the_day(self):
        reports = {
            "AAA": self._report([self._leg(self.DAY, move_pct=1.0)]),
            "BBB": self._report([self._leg(self.DAY, move_pct=3.0)]),
            "CCC": self._report([self._leg(self.DAY, move_pct=2.0)]),
        }

        rows = top_legs_for_day(reports, self.DAY, "up", top_n=2)

        assert [row["ticker"] for row in rows] == ["BBB", "CCC"]

    def test_ranks_by_adr_multiple_when_asked(self):
        reports = {
            "AAA": self._report([self._leg(self.DAY, move_pct=3.0, adr_multiple=0.4)]),
            "BBB": self._report([self._leg(self.DAY, move_pct=1.0, adr_multiple=0.9)]),
        }

        rows = top_legs_for_day(reports, self.DAY, "up", rank_by="adr")

        assert rows[0]["ticker"] == "BBB"

    def test_uses_only_legs_of_the_requested_direction(self):
        reports = {
            "AAA": self._report([
                self._leg(self.DAY, kind="up", move_pct=1.0),
                self._leg(self.DAY, kind="down", move_pct=5.0),
            ]),
        }

        rows = top_legs_for_day(reports, self.DAY, "down")

        assert rows[0]["move_pct"] == 5.0

    def test_average_covers_the_prior_sessions_and_excludes_the_day(self):
        prior_days = [date(2026, 9, d) for d in (18, 21, 22, 23, 24)]
        legs = [self._leg(d, move_pct=1.0, move_usd=2.0) for d in prior_days]
        legs.append(self._leg(self.DAY, move_pct=4.0))
        reports = {"AAA": self._report(legs)}

        row = top_legs_for_day(reports, self.DAY, "up", avg_sessions=5)[0]

        assert row["avg_move_pct"] == pytest.approx(1.0)
        assert row["avg_move_usd"] == pytest.approx(2.0)
        assert row["avg_n"] == 5
        assert row["vs_avg"] == pytest.approx(4.0)

    def test_average_window_counts_sessions_not_legs(self):
        legs = [
            self._leg(date(2026, 9, 22), move_pct=9.0),
            self._leg(date(2026, 9, 23), kind="down"),
            self._leg(date(2026, 9, 24), move_pct=3.0),
            self._leg(self.DAY, move_pct=2.0),
        ]
        reports = {"AAA": self._report(legs)}

        row = top_legs_for_day(reports, self.DAY, "up", avg_sessions=2)[0]

        assert row["avg_move_pct"] == pytest.approx(3.0)
        assert row["avg_n"] == 1

    def test_skips_tickers_without_a_leg_on_the_day(self):
        reports = {
            "AAA": self._report([self._leg(date(2026, 9, 24))]),
            "BBB": self._report([self._leg(self.DAY)]),
        }

        rows = top_legs_for_day(reports, self.DAY, "up")

        assert [row["ticker"] for row in rows] == ["BBB"]

    def test_average_is_none_without_prior_sessions(self):
        reports = {"AAA": self._report([self._leg(self.DAY)])}

        row = top_legs_for_day(reports, self.DAY, "up")[0]

        assert row["avg_move_pct"] is None
        assert row["vs_avg"] is None

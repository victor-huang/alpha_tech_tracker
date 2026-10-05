import json
from datetime import date, datetime

import pandas as pd

from alpha_tech_tracker.op_momentum_strategy.analysis_scripts import earnings_calendar
from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.earnings_calendar import (
    earnings_windows,
    in_earnings_window,
    load_releases,
    parse_release,
    reaction_sessions,
)

MARKET_TZ = "America/New_York"
SESSIONS = [date(2026, 9, 1), date(2026, 9, 2), date(2026, 9, 3), date(2026, 9, 4), date(2026, 9, 8)]


class TestParseRelease:
    def test_parses_hour_and_zone(self):
        assert parse_release("September 1, 2026 at 4 PM EDT") == datetime(2026, 9, 1, 16, 0)

    def test_parses_minutes(self):
        assert parse_release("May 5, 2026 at 8:30 AM EDT") == datetime(2026, 5, 5, 8, 30)

    def test_returns_none_for_unparseable_text(self):
        assert parse_release("-") is None


class TestReactionSessions:
    def test_after_close_release_moves_the_next_session(self):
        assert reaction_sessions([datetime(2026, 9, 1, 16, 0)], SESSIONS) == {date(2026, 9, 2)}

    def test_before_open_release_moves_the_same_session(self):
        assert reaction_sessions([datetime(2026, 9, 3, 7, 0)], SESSIONS) == {date(2026, 9, 3)}

    def test_weekend_release_moves_the_next_session(self):
        assert reaction_sessions([datetime(2026, 9, 5, 16, 0)], SESSIONS) == {date(2026, 9, 8)}

    def test_unknown_time_marks_both_sessions(self):
        assert reaction_sessions([datetime(2026, 9, 2, 0, 0)], SESSIONS) == {date(2026, 9, 2), date(2026, 9, 3)}


class TestEarningsWindows:
    def test_eve_is_the_session_before_the_reaction(self):
        windows = earnings_windows([datetime(2026, 9, 3, 16, 0)], SESSIONS)

        assert windows == {"reaction": {date(2026, 9, 4)}, "eve": {date(2026, 9, 3)}}


class TestInEarningsWindow:
    windows = {"reaction": {date(2026, 9, 2)}, "eve": {date(2026, 9, 1)}}

    def _signal(self, name, stamp):
        return {"signal": name, "time": pd.Timestamp(stamp, tz=MARKET_TZ)}

    def test_overnight_hold_on_the_eve_carries_the_release(self):
        assert in_earnings_window(self._signal("overnight_long", "2026-09-01 15:55"), self.windows)

    def test_overnight_hold_on_the_reaction_session_does_not(self):
        assert not in_earnings_window(self._signal("overnight_long", "2026-09-02 15:55"), self.windows)

    def test_intraday_signal_on_the_reaction_session_does(self):
        assert in_earnings_window(self._signal("drive_long", "2026-09-02 09:30"), self.windows)

    def test_intraday_signal_on_the_eve_does_not(self):
        assert not in_earnings_window(self._signal("drive_long", "2026-09-01 09:30"), self.windows)


class TestLoadReleases:
    def test_uses_a_fresh_cache_without_fetching(self, tmp_path, mocker):
        (tmp_path / "MDB.json").write_text(json.dumps({"fetched": "2026-10-01", "releases": ["2026-09-01T16:00:00"]}))
        fetch = mocker.patch.object(earnings_calendar, "fetch_releases")

        releases = load_releases("MDB", cache_dir=tmp_path, today=date(2026, 10, 5))

        assert releases == [datetime(2026, 9, 1, 16, 0)]
        fetch.assert_not_called()

    def test_refetches_a_stale_cache_and_saves_it(self, tmp_path, mocker):
        (tmp_path / "MDB.json").write_text(json.dumps({"fetched": "2026-09-01", "releases": []}))
        mocker.patch.object(earnings_calendar, "fetch_releases", return_value=[datetime(2026, 9, 1, 16, 0)])

        releases = load_releases("MDB", cache_dir=tmp_path, today=date(2026, 10, 5))

        assert releases == [datetime(2026, 9, 1, 16, 0)]
        assert json.loads((tmp_path / "MDB.json").read_text())["fetched"] == "2026-10-05"

    def test_falls_back_to_the_stale_cache_when_the_fetch_fails(self, tmp_path, mocker):
        (tmp_path / "MDB.json").write_text(json.dumps({"fetched": "2026-09-01", "releases": ["2026-09-01T16:00:00"]}))
        mocker.patch.object(earnings_calendar, "fetch_releases", side_effect=OSError("offline"))

        assert load_releases("MDB", cache_dir=tmp_path, today=date(2026, 10, 5)) == [datetime(2026, 9, 1, 16, 0)]

    def test_returns_nothing_when_the_fetch_fails_without_a_cache(self, tmp_path, mocker):
        mocker.patch.object(earnings_calendar, "fetch_releases", side_effect=OSError("offline"))

        assert load_releases("MDB", cache_dir=tmp_path, today=date(2026, 10, 5)) == []

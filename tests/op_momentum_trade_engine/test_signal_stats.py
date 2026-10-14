from datetime import date, datetime, time, timedelta
from pathlib import Path

import pandas as pd
import pytest
import pytz

from alpha_tech_tracker.op_momentum_strategy import signal_stats as stats_module
from alpha_tech_tracker.op_momentum_strategy.signal_stats import (
    Result,
    drive_long_results,
    overnight_results,
    signal_stats,
    stats_message,
)

ET = pytz.timezone("America/New_York")
MON, TUE, WED = date(2026, 10, 12), date(2026, 10, 13), date(2026, 10, 14)
FIXTURES = Path(__file__).parent / "fixtures"


def _session(day, close=100.0, first_open=None):
    """78 flat 5-min bars at `close`; the first bar opens at `first_open`."""
    index = pd.DatetimeIndex([ET.localize(datetime.combine(day, time(9, 30)) + timedelta(minutes=5 * i))
                              for i in range(78)])
    frame = pd.DataFrame({"open": close, "high": close, "low": close, "close": close}, index=index)
    if first_open is not None:
        frame.iloc[0, frame.columns.get_loc("open")] = first_open
    return frame


def _bars(*sessions):
    return pd.concat(sessions)


def _windows(eves=()):
    return {"reaction": set(), "eve": set(eves)}


class TestOvernightResults:
    def test_buys_the_1555_close_and_sells_the_next_open(self):
        bars = _bars(_session(MON, 100.0), _session(TUE, 102.0, first_open=101.0))

        results = overnight_results("AMD", bars, pd.Series(dtype=float), None, {MON}, mode="always")

        assert results == [Result("AMD", "overnight", MON, pytest.approx(1.0))]

    def test_pending_until_the_next_open(self):
        bars = _session(MON)

        assert overnight_results("AMD", bars, pd.Series(dtype=float), None, {MON}, mode="always") == [
            Result("AMD", "overnight", MON, None)]

    def test_no_entry_is_not_pending(self):
        bars = _session(MON)
        closes = pd.Series([110.0] * 200, index=[MON - timedelta(days=i) for i in range(1, 201)])

        assert overnight_results("AMD", bars, closes, None, {MON}, mode="ma200") == []

    def test_no_hold_on_an_early_close_day(self):
        bars = _bars(_session(MON).iloc[:42], _session(TUE))

        assert overnight_results("AMD", bars, pd.Series(dtype=float), None, {MON}, mode="always") == []

    def test_skips_the_night_into_earnings(self):
        bars = _bars(_session(MON), _session(TUE))

        assert overnight_results("AMD", bars, pd.Series(dtype=float), _windows([MON]), {MON}, mode="always") == []

    def test_skips_when_the_ma200_filter_fails(self):
        bars = _bars(_session(MON, 100.0), _session(TUE))
        closes = pd.Series([110.0] * 200, index=[MON - timedelta(days=i) for i in range(1, 201)])

        assert overnight_results("AMD", bars, closes, None, {MON}, mode="ma200") == []

    def test_holds_when_the_close_is_above_ma200(self):
        bars = _bars(_session(MON, 100.0), _session(TUE))
        closes = pd.Series([90.0] * 200, index=[MON - timedelta(days=i) for i in range(1, 201)])

        assert len(overnight_results("AMD", bars, closes, None, {MON}, mode="ma200")) == 1

    def test_only_the_days_asked(self):
        bars = _bars(_session(MON), _session(TUE), _session(WED))

        results = overnight_results("AMD", bars, pd.Series(dtype=float), None, {TUE}, mode="always")

        assert [r.day for r in results] == [TUE]


class TestDriveLongResults:
    def _signal(self, day, kind="drive_long"):
        return {"signal": kind, "time": ET.localize(datetime.combine(day, time(9, 30))), "risk_reward": {}}

    def test_drive_long_held_to_the_close(self, mocker):
        mocker.patch.object(stats_module, "analyze_bars", return_value={"signals": [self._signal(MON)]})
        run = mocker.patch.object(stats_module.TradeSimulator, "run", return_value={"gross_pct": 1.5})

        results = drive_long_results("AMD", _session(MON), {MON})

        assert results == [Result("AMD", "drive", MON, 1.5)]
        assert run.call_args.args[1] == "eod"

    def test_real_drive_long_stops_at_the_first_bars_low(self):
        frame = pd.read_csv(FIXTURES / "amd_5min_2026-09-16.csv", index_col="time")
        frame.index = pd.to_datetime(frame.index, utc=True).tz_convert(ET)

        results = drive_long_results("AMD", frame, {date(2026, 9, 16)})

        assert results == [Result("AMD", "drive", date(2026, 9, 16), pytest.approx((514.16 - 519.12) / 519.12 * 100,
                                                                                 abs=0.01))]

    def test_ignores_other_signals_and_days(self, mocker):
        mocker.patch.object(stats_module, "analyze_bars", return_value={"signals": [
            self._signal(MON, "drive_short"), self._signal(TUE)]})
        mocker.patch.object(stats_module.TradeSimulator, "run", return_value={"gross_pct": 1.5})

        assert drive_long_results("AMD", _bars(_session(MON), _session(TUE)), {MON}) == []


class TestStatsMessage:
    def _results(self):
        return [Result("AMD", "drive", MON, 2.0), Result("AMD", "drive", TUE, -1.0),
                Result("META", "drive", TUE, 1.0), Result("AMD", "overnight", MON, 0.5),
                Result("META", "overnight", MON, -0.5), Result("AMD", "overnight", TUE, None)]

    def test_pooled_and_by_day(self):
        message = stats_message(self._results(), ["AMD", "META"], ["AMD"], {MON, TUE}, [MON, TUE], "ma200")

        assert message.splitlines() == [
            "signal stats, last 2 sessions (10-12 to 10-13), 2 tickers:",
            "drive long: 2/3 won (67%), avg +0.67%",
            "overnight ma200: 1/2 won (50%), avg +0.00%, 1 pending",
            "monitored (AMD), by day:",
            "10-12 drive long 1/1 won (100%), avg +2.00% | overnight 1/1 won (100%), avg +0.50%",
            "10-13 drive long 0/1 won (0%), avg -1.00% | overnight 1 pending (exit at the next open)"]

    def test_day_without_trades(self):
        message = stats_message([], ["AMD"], ["AMD"], {MON, TUE}, [MON, TUE], "ma200")

        assert "10-12 drive long no trades | overnight no trades" in message

    def test_names_tickers_without_data(self):
        message = stats_message([], ["AMD", "META"], ["AMD"], {MON}, [MON], "ma200", missing=["META"])

        assert message.splitlines()[0] == "signal stats, last 1 session (10-12 to 10-12), 1 ticker:"
        assert message.splitlines()[-1] == "no data: META"

    def test_notes_end_the_message(self):
        message = stats_message([], ["AMD"], ["AMD"], {MON}, [MON], "ma200", notes=["daily closes unavailable"])

        assert message.splitlines()[-1] == "daily closes unavailable"

    def test_no_sessions(self):
        assert stats_message([], ["AMD"], ["AMD"], set(), [], "ma200") == (
            "signal stats: no completed sessions in the history")


class TestSignalStats:
    def test_uses_only_sessions_before_the_start(self, mocker):
        drive = mocker.patch.object(stats_module, "drive_long_results", return_value=[])
        mocker.patch.object(stats_module, "overnight_results", return_value=[])
        bars = {"AMD": _bars(_session(MON), _session(TUE), _session(WED))}

        message = signal_stats(bars, {}, {}, ["AMD"], ["AMD"], WED, sessions=10, days=1)

        assert message.splitlines()[0].startswith("signal stats, last 2 sessions (10-12 to 10-13)")
        assert set(drive.call_args.args[1].index.date) == {MON, TUE}

    def test_window_is_the_last_sessions(self, mocker):
        drive = mocker.patch.object(stats_module, "drive_long_results", return_value=[])
        mocker.patch.object(stats_module, "overnight_results", return_value=[])
        bars = {"AMD": _bars(_session(MON), _session(TUE), _session(WED))}

        signal_stats(bars, {}, {}, ["AMD"], ["AMD"], date(2026, 10, 15), sessions=2, days=1)

        assert drive.call_args.args[2] == {TUE, WED}

    def test_todays_open_ends_the_last_night(self):
        bars = {"AMD": _bars(_session(MON, 100.0), _session(TUE, 100.0, first_open=102.0).iloc[:1])}

        message = signal_stats(bars, {}, {}, ["AMD"], ["AMD"], TUE, days=1, overnight_mode="always")

        assert "10-12 drive long no trades | overnight 1/1 won (100%), avg +2.00%" in message

    def test_reports_stats_tickers_without_bars(self, mocker):
        mocker.patch.object(stats_module, "drive_long_results", return_value=[])
        mocker.patch.object(stats_module, "overnight_results", return_value=[])

        message = signal_stats({"AMD": _session(MON)}, {}, {}, ["AMD", "META"], ["AMD"], TUE)

        assert message.splitlines()[-1] == "no data: META"

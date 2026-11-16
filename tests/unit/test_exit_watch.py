from datetime import date

import pandas as pd
import pytest

from alpha_tech_tracker.research.exit_watch import (
    MARKET_TZ,
    cash_rule_line,
    cash_rule_state,
    completed_days,
    history_start,
    trail_status,
    watch_table,
)

DAYS = pd.bdate_range("2026-11-02", periods=6)


def _close(prices):
    return pd.Series(prices, index=DAYS[:len(prices)])


class TestTrailStatus:
    def test_holds_while_close_stays_within_trail_of_peak(self):
        status = trail_status(_close([100, 120, 100]), DAYS[0], [DAYS[0]], 0.25)

        assert (status["peak"], status["stopped_on"]) == (120, None)

    def test_stops_when_close_falls_trail_below_peak(self):
        status = trail_status(_close([100, 120, 90]), DAYS[0], [DAYS[0]], 0.25)

        assert status["stopped_on"] == DAYS[2].date()

    def test_ignores_closes_before_entry(self):
        status = trail_status(_close([200, 100, 90]), DAYS[1], [DAYS[1]], 0.15)

        assert (status["peak"], status["stopped_on"]) == (100, None)

    def test_peak_resets_when_bought_back_at_a_later_checkpoint(self):
        status = trail_status(_close([100, 80, 70, 75]), DAYS[0], [DAYS[0], DAYS[3]], 0.15)

        assert (status["peak"], status["stopped_on"]) == (75, None)

    def test_stays_stopped_until_the_next_checkpoint(self):
        status = trail_status(_close([100, 80, 120]), DAYS[0], [DAYS[0]], 0.15)

        assert status["stopped_on"] == DAYS[1].date()

    def test_rebuys_at_once_when_the_stop_fires_on_a_checkpoint_day(self):
        status = trail_status(_close([100, 120, 80]), DAYS[0], [DAYS[0], DAYS[2]], 0.25)

        assert (status["peak"], status["stopped_on"]) == (80, None)

    def test_reports_stop_price_from_peak(self):
        status = trail_status(_close([100, 120]), DAYS[0], [DAYS[0]], 0.25)

        assert status["stop_price"] == 90


class TestWatchTable:
    def _lists(self, rows):
        return pd.DataFrame(rows, columns=["list", "symbol", "status", "entry", "exit_rule"])

    def test_skips_dropped_names_and_lists_without_a_trailing_stop(self):
        lists = self._lists([("a", "AAA", "held", DAYS[0], "trail25"), ("a", "BBB", "dropped", DAYS[0], "trail25"),
                             ("b", "CCC", "held", DAYS[0], "none")])
        close = pd.DataFrame({s: [10.0, 11.0] for s in ("AAA", "BBB", "CCC")}, index=DAYS[:2])

        assert watch_table(lists, close, [DAYS[0]])["symbol"].tolist() == ["AAA"]

    def test_marks_stopped_names_to_sell(self):
        lists = self._lists([("a", "AAA", "held", DAYS[0], "trail15")])
        close = pd.DataFrame({"AAA": [10.0, 8.0]}, index=DAYS[:2])

        assert watch_table(lists, close, [DAYS[0]])["action"].tolist() == ["SELL (stopped)"]

    def test_empty_list_gives_empty_table_with_action_column(self):
        lists = self._lists([("a", "AAA", "dropped", DAYS[0], "trail25")])

        table = watch_table(lists, pd.DataFrame({"AAA": [10.0]}, index=DAYS[:1]), [DAYS[0]])

        assert table.empty and "action" in table.columns


class TestHistoryStart:
    def test_reaches_back_before_the_first_trading_day_of_the_entry_year(self):
        assert history_start(date(2026, 10, 19)) < date(2026, 1, 2)


def _now(text):
    return pd.Timestamp(text, tz=MARKET_TZ)


def _bars(days):
    closes = [100.0 + i * 0.1 for i in range(days)]
    timestamps = pd.bdate_range("2024-01-02", periods=days, tz="UTC") + pd.Timedelta(hours=5)
    return pd.DataFrame({"symbol": "QQQ", "timestamp": timestamps, "close": closes, "volume": 1000.0})


class TestCompletedDays:
    INDEX = pd.DatetimeIndex(["2026-11-12", "2026-11-13"])

    def test_drops_todays_bar_before_the_close_is_final(self):
        assert completed_days(self.INDEX, _now("2026-11-13 15:30")).tolist() == [pd.Timestamp("2026-11-12")]

    def test_drops_todays_bar_until_the_sip_delay_has_passed(self):
        assert len(completed_days(self.INDEX, _now("2026-11-13 16:05"))) == 1

    def test_keeps_todays_bar_after_the_close_is_final(self):
        assert len(completed_days(self.INDEX, _now("2026-11-13 16:30"))) == 2

    def test_keeps_an_earlier_days_bar(self):
        assert len(completed_days(self.INDEX, _now("2026-11-14 10:00"))) == 2


class TestCashRuleState:
    def test_replays_the_rule_on_completed_bars(self, mocker):
        mocker.patch("alpha_tech_tracker.research.exit_watch.AlpacaData").return_value.daily_bars.return_value = _bars(5)

        state = cash_rule_state(date(2024, 1, 8), _now("2024-01-08 10:00"))

        assert state.index[-1] == pd.Timestamp("2024-01-05")

    def test_raises_without_qqq_bars(self, mocker):
        mocker.patch("alpha_tech_tracker.research.exit_watch.AlpacaData").return_value.daily_bars.return_value = \
            pd.DataFrame(columns=["symbol", "timestamp", "close", "volume"])

        with pytest.raises(ValueError):
            cash_rule_state(date(2024, 1, 8), _now("2024-01-08 18:00"))


class TestCashRuleLine:
    def test_reports_unavailable_instead_of_raising(self, mocker):
        mocker.patch("alpha_tech_tracker.research.exit_watch.cash_rule_state", side_effect=RuntimeError("bars failed"))

        line = cash_rule_line(date(2024, 1, 8), _now("2024-01-08 18:00"))

        assert line.startswith("market cash rule: UNAVAILABLE (bars failed)")

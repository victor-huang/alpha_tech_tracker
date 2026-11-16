import pandas as pd

from alpha_tech_tracker.research.cash_rule import (
    MIN_STAY,
    cash_rule,
    distribution_days,
    last_event,
    ma_rule,
    status_line,
)


def _path(*segments):
    """Close and volume from (days, daily return, volume) segments; volume "rising" adds 5 a day, "surging" doubles
    every day, a number is constant."""
    closes, volumes, price, vol = [], [], 100.0, 100.0
    for days, ret, volume in segments:
        for _ in range(days):
            price *= 1 + ret
            vol = vol + 5 if volume == "rising" else vol * 2 if volume == "surging" else float(volume)
            closes.append(price)
            volumes.append(vol)
    index = pd.bdate_range("2020-01-01", periods=len(closes))
    return pd.Series(closes, index=index), pd.Series(volumes, index=index)


UPTREND = (260, 0.003, 100)
SELL_OFF = (40, -0.01, "rising")
LONG_SELL_OFF = (80, -0.01, "rising")  # long enough for the 50-day to drop under the 200-day
SHORT_RALLY = (8, 0.035, 100)  # re-enters above the 50-day while it is still under the 200-day
RECOVERY_THEN_DIP = (UPTREND, LONG_SELL_OFF, (200, 0.01, 100), (30, -0.02, 100))


def _first(state, event):
    days = state.index[state["event"] == event]
    return days[0] if len(days) else None


class TestDistributionDays:
    def _days(self, last_return, last_volume, previous_volume=100.0):
        close = pd.Series([100.0] * 21 + [100.0 * (1 + last_return)])
        volume = pd.Series([100.0] * 20 + [previous_volume, last_volume])
        return distribution_days(close, volume)

    def test_flat_close_on_higher_volume_counts(self):
        assert self._days(0.001, 150.0).iloc[-1]

    def test_down_close_on_higher_volume_counts(self):
        assert self._days(-0.02, 150.0).iloc[-1]

    def test_up_close_does_not_count(self):
        assert not self._days(0.01, 150.0).iloc[-1]

    def test_volume_not_above_the_day_before_does_not_count(self):
        assert not self._days(-0.02, 150.0, previous_volume=160.0).iloc[-1]

    def test_volume_not_above_the_20_day_average_does_not_count(self):
        assert not self._days(-0.02, 90.0, previous_volume=80.0).iloc[-1]


class TestMaRule:
    def test_in_cash_below_both_averages(self):
        close, _ = _path(UPTREND, (60, -0.01, 100))

        assert ma_rule(close).iloc[-1]

    def test_invested_above_the_averages(self):
        close, _ = _path(UPTREND)

        assert not ma_rule(close).iloc[-1]


class TestCashRule:
    def test_exits_after_distribution_days_below_both_averages(self):
        close, volume = _path(UPTREND, SELL_OFF)

        state = cash_rule(close, volume)

        assert state["in_cash"].iloc[-1] and _first(state, "exit") is not None

    def test_stays_invested_in_a_sell_off_without_distribution_days(self):
        close, volume = _path(UPTREND, (40, -0.01, 100))

        assert not cash_rule(close, volume)["in_cash"].any()

    def test_re_enters_on_a_close_above_the_50_day(self):
        close, volume = _path(UPTREND, SELL_OFF, (40, 0.02, 100))

        state = cash_rule(close, volume)

        assert _first(state, "re-enter") is not None and not state["in_cash"].iloc[-1]

    def test_waits_the_minimum_stay_before_re_entering(self):
        close, volume = _path(UPTREND, (24, -0.01, "rising"), (1, 0.30, 100), (20, 0.0, 100))

        state = cash_rule(close, volume)

        gap = state.index.get_loc(_first(state, "re-enter")) - state.index.get_loc(_first(state, "exit"))
        assert gap == MIN_STAY

    def test_re_exits_below_the_50_day_without_new_distribution_days(self):
        close, volume = _path(UPTREND, LONG_SELL_OFF, (12, 0.025, 100), (15, -0.02, 100))

        state = cash_rule(close, volume)

        assert _first(state, "re-exit") > _first(state, "re-enter")

    def test_stops_re_exits_once_the_uptrend_is_back(self):
        state = cash_rule(*_path(*RECOVERY_THEN_DIP))

        assert _first(state, "re-exit") is None

    def test_recovery_then_dip_path_closes_below_the_50_day(self):
        state = cash_rule(*_path(*RECOVERY_THEN_DIP))

        assert state["close"].iloc[-1] < state["ma50"].iloc[-1]

    def test_minimum_stay_does_not_delay_a_fresh_distribution_exit(self):
        state = cash_rule(*_path(UPTREND, LONG_SELL_OFF, SHORT_RALLY, (10, -0.02, "surging")))

        exits = state.index[state["event"] == "exit"]
        gap = state.index.get_loc(exits[1]) - state.index.get_loc(_first(state, "re-enter"))
        assert gap < MIN_STAY

    def test_minimum_stay_delays_a_re_exit(self):
        state = cash_rule(*_path(UPTREND, LONG_SELL_OFF, SHORT_RALLY, (12, -0.02, 100)))

        gap = state.index.get_loc(_first(state, "re-exit")) - state.index.get_loc(_first(state, "re-enter"))
        assert gap == MIN_STAY

    def test_never_exits_before_the_200_day_average_exists(self):
        state = cash_rule(*_path((100, 0.003, 100), (40, -0.01, "rising")))

        assert not state["in_cash"].any()

    def test_counts_distribution_days_only_since_the_last_re_entry(self):
        close, volume = _path(UPTREND, SELL_OFF, (25, 0.02, 100))

        state = cash_rule(close, volume)

        assert state.loc[state.index > _first(state, "re-enter"), "dist_count"].max() == 0


class TestLastEvent:
    def test_is_empty_without_any_event(self):
        assert last_event(cash_rule(*_path(UPTREND))) == (None, "")

    def test_returns_the_latest_event(self):
        state = cash_rule(*_path(UPTREND, SELL_OFF, (40, 0.02, 100)))

        assert last_event(state) == (_first(state, "re-enter"), "re-enter")


class TestStatusLine:
    def test_reports_cash_with_the_exit_day(self):
        close, volume = _path(UPTREND, SELL_OFF)
        state = cash_rule(close, volume)

        assert f"CASH since exit on {_first(state, 'exit').date()}" in status_line(state)

    def test_reports_invested_without_any_event(self):
        close, volume = _path(UPTREND)

        assert "INVESTED |" in status_line(cash_rule(close, volume))

    def test_includes_the_previous_rule_for_comparison(self):
        close, volume = _path(UPTREND)

        assert status_line(cash_rule(close, volume)).endswith("previous 50/200-day rule: invested")


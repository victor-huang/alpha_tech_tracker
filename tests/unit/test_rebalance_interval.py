import pandas as pd

from alpha_tech_tracker.research.rebalance_interval import (
    TrendIntervals,
    book_summary,
    combine_years,
    returns_by_year,
    dynamic_schedule,
    fixed_schedule,
    trend_state,
)

CPS = list(pd.bdate_range("2026-01-05", periods=7))


class TestFixedSchedule:
    def test_takes_every_nth_checkpoint(self):
        assert fixed_schedule(CPS, 2, 0) == CPS[0::2]

    def test_offset_still_starts_at_the_first_checkpoint(self):
        assert fixed_schedule(CPS, 3, 1) == [CPS[0], CPS[1], CPS[4]]


class TestDynamicSchedule:
    def test_waits_the_interval_of_the_current_trend(self):
        states = pd.Series(["above_both"] * 5, index=CPS[:5])

        assert dynamic_schedule(states, TrendIntervals(2, 1, 1)) == [CPS[0], CPS[2], CPS[4]]

    def test_rebalances_at_once_when_the_trend_shortens_the_interval(self):
        states = pd.Series(["above_both", "below_200", "below_200"], index=CPS[:3])

        assert dynamic_schedule(states, TrendIntervals(6, 1, 1)) == CPS[:3]


class TestTrendState:
    def _close(self, last):
        days = pd.bdate_range("2025-01-01", periods=260)
        return pd.Series([100.0] * 259 + [last], index=days), days[-1]

    def test_above_both_averages(self):
        close, day = self._close(110.0)

        assert trend_state(close, [day]).iloc[0] == "above_both"

    def test_below_200_day_average(self):
        close, day = self._close(90.0)

        assert trend_state(close, [day]).iloc[0] == "below_200"

    def test_above_200_but_below_50_day_average(self):
        days = pd.bdate_range("2025-01-01", periods=260)
        close = pd.Series([50.0] * 200 + [120.0] * 59 + [110.0], index=days)

        assert trend_state(close, [days[-1]]).iloc[0] == "above_200_only"


class TestCombineYears:
    def _write(self, root, year, returns):
        rows = [{"tier": "Large", "exit": "trail25", "schedule": name, "total_return": r, "turnover": 10.0}
                for name, r in returns.items()]
        (root / str(year)).mkdir()
        pd.DataFrame(rows).to_csv(root / str(year) / "summary.csv", index=False)

    def test_compounds_years_into_total(self, tmp_path):
        self._write(tmp_path, 2024, {"2 weeks": 0.10, "1 month": 0.20})
        self._write(tmp_path, 2025, {"2 weeks": 0.10, "1 month": 0.00})

        table = combine_years(str(tmp_path))

        assert round(table.loc[("Large", "1 month"), "total"], 4) == 0.2

    def test_counts_years_beating_two_weeks(self, tmp_path):
        self._write(tmp_path, 2024, {"2 weeks": 0.10, "1 month": 0.20})
        self._write(tmp_path, 2025, {"2 weeks": 0.10, "1 month": 0.00})

        table = combine_years(str(tmp_path))

        assert table.loc[("Large", "1 month"), "years_beat_2_weeks"] == 1


def _book(rets, starts):
    return pd.DataFrame({"ret": rets, "turnover": 0.5, "exits": 1}, index=pd.to_datetime(starts))


class TestBookSummary:
    def test_measures_worst_drop_from_the_running_peak(self):
        book = _book([0.5, -0.4, 0.1], ["2024-01-02", "2024-07-01", "2025-01-02"])

        summary = book_summary(book, pd.Timestamp("2025-12-31"))

        assert round(summary["max_dd_at_rebalances"], 4) == -0.4

    def test_compounds_total_over_the_years_held(self):
        book = _book([0.21], ["2024-01-01"])

        summary = book_summary(book, pd.Timestamp("2025-12-31"))

        assert (round(summary["total_return"], 4), round(summary["cagr"], 2)) == (0.21, 0.10)


class TestReturnsByYear:
    def test_credits_each_period_to_the_year_it_starts_in(self):
        book = _book([0.1, 0.1, -0.5], ["2024-06-03", "2024-12-16", "2025-01-02"])

        assert returns_by_year(book).round(4).to_dict() == {2024: 0.21, 2025: -0.5}

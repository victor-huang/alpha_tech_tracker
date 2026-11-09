import numpy as np
import pandas as pd
import pytest

from alpha_tech_tracker.research.winner_capture import names_per_year, shuffled_top, winner_capture

DAYS = pd.to_datetime(["2023-12-29", "2024-01-02", "2024-06-03", "2024-12-31"])


def _book(held_by_checkpoint):
    return pd.DataFrame({"held": list(held_by_checkpoint.values())}, index=pd.DatetimeIndex(held_by_checkpoint))


class TestWinnerCapture:

    def _inputs(self):
        close = pd.DataFrame({"WIN": [10.0, 10.0, 40.0, 100.0]}, index=DAYS)
        checkpoints = [DAYS[1], DAYS[2]]
        returns = pd.DataFrame({"WIN": [3.0, 1.5]}, index=checkpoints)
        winners = pd.DataFrame({"year": [2024], "tier": ["Small"], "symbol": ["WIN"], "return_pct": [900.0]})
        return close, returns, winners

    def test_share_of_gain_ahead_and_captured_from_the_first_checkpoint_held(self):
        close, returns, winners = self._inputs()
        book = _book({DAYS[1]: ["X"], DAYS[2]: ["WIN"]})

        row = winner_capture(book, winners, close, returns).iloc[0]

        assert row["held"]
        assert row["first_held"] == DAYS[2]
        assert row["share_ahead"] == pytest.approx(np.log(100 / 40) / np.log(10))
        assert row["share_captured"] == pytest.approx(np.log(2.5) / np.log(10))

    def test_winner_never_held_is_reported_as_missed(self):
        close, returns, winners = self._inputs()
        book = _book({DAYS[1]: ["X"], DAYS[2]: ["Y"]})

        row = winner_capture(book, winners, close, returns).iloc[0]

        assert not row["held"]
        assert np.isnan(row["share_ahead"])


class TestNamesPerYear:

    def test_counts_distinct_symbols_held_in_each_year(self):
        book = _book({DAYS[1]: ["A", "B"], DAYS[2]: ["B", "C"]})

        assert names_per_year(book).loc[2024] == 3


class TestShuffledTop:

    def test_keeps_only_the_top_names_with_permuted_ranks(self):
        ranked = pd.DataFrame({"checkpoint": [DAYS[1]] * 5, "symbol": list("ABCDE"), "rank": [1.0, 2, 3, 4, 5]})

        result = shuffled_top(ranked, np.random.default_rng(0), size=3)

        assert set(result["symbol"]) == {"A", "B", "C"}
        assert sorted(result["rank"]) == [1.0, 2.0, 3.0]

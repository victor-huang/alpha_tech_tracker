import pandas as pd

from alpha_tech_tracker.research.concentration import LISTS, contributions, top_share

CPS = [pd.Timestamp("2026-01-02"), pd.Timestamp("2026-01-16")]


class TestContributions:
    def _returns(self):
        return pd.DataFrame({"A": [0.2, 0.1], "B": [-0.1, 0.0], "C": [0.0, 0.4]}, index=CPS)

    def test_weights_each_holding_by_book_size(self):
        book = pd.DataFrame({"held": [["A", "B"], ["A", "C"]]}, index=CPS)

        out = contributions(book, self._returns())

        assert round(out.loc["A", "contribution"], 4) == 0.15

    def test_counts_periods_held(self):
        book = pd.DataFrame({"held": [["A", "B"], ["A", "C"]]}, index=CPS)

        out = contributions(book, self._returns())

        assert out.loc["A", "periods"] == 2

    def test_sorts_largest_contributor_first(self):
        book = pd.DataFrame({"held": [["A", "B"], ["A", "C"]]}, index=CPS)

        out = contributions(book, self._returns())

        assert out.index.tolist() == ["C", "A", "B"]


class TestTopShare:
    def test_share_of_summed_contribution_from_largest_names(self):
        contrib = pd.DataFrame({"contribution": [0.6, 0.3, 0.1]}, index=["A", "B", "C"])

        assert round(top_share(contrib, k=1), 4) == 0.6


class TestLists:
    def test_large_score_only_has_no_breakout_slots(self):
        assert LISTS["large_score_only"].variant.boost_groups == ()

    def test_small_uses_the_trend_schedule(self):
        assert LISTS["small"].trend_schedule == "uptrend 2w, else 1m"

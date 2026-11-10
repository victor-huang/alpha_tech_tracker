import pandas as pd

from alpha_tech_tracker.research.concentration import (
    LISTS,
    contributions,
    geometric_mean,
    top_share,
    walk_forward_picks,
    walk_forward_summary,
)

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


def _grid():
    rets = {"a": [0.5, -0.1, 0.2], "b": [0.1, 0.3, 0.0], "c": [0.0, 0.0, 0.1]}
    return pd.DataFrame([{"setting": name, "top": 3, "year": 2020 + i, "ret": r}
                         for name, values in rets.items() for i, r in enumerate(values)])


class TestGeometricMean:
    def test_compounds_yearly_returns(self):
        assert round(geometric_mean([1.0, -0.5]), 4) == 0.0


class TestWalkForwardPicks:
    def test_chooses_best_setting_on_earlier_years_only(self):
        picks = walk_forward_picks(_grid(), first_test_year=2021)

        assert picks.set_index("year").loc[2021, "chosen"] == "a"

    def test_records_chosen_setting_test_year_return(self):
        picks = walk_forward_picks(_grid(), first_test_year=2021)

        assert round(picks.set_index("year").loc[2021, "test_ret"], 4) == -0.1

    def test_ranks_chosen_setting_among_all_settings_in_test_year(self):
        picks = walk_forward_picks(_grid(), first_test_year=2021)

        assert picks.set_index("year").loc[2021, "rank"] == 3

    def test_retrains_on_all_earlier_years(self):
        picks = walk_forward_picks(_grid(), first_test_year=2021)

        assert picks.set_index("year").loc[2022, "chosen"] == "b"


class TestWalkForwardSummary:
    def test_fixed_setting_cagr_covers_years_from_start(self):
        grid = _grid()

        out = walk_forward_summary(grid, walk_forward_picks(grid, 2021), "c", from_year=2022)

        assert round(out.loc[0, "fixed"], 4) == 0.1

    def test_hindsight_best_is_best_setting_over_the_period(self):
        grid = _grid()

        out = walk_forward_summary(grid, walk_forward_picks(grid, 2021), "c", from_year=2022)

        assert round(out.loc[0, "hindsight_best"], 4) == 0.2

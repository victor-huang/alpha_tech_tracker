import numpy as np
import pandas as pd
import pytest

from alpha_tech_tracker.research.walk_forward_tuning import add_lookback_returns, settings, walk_forward


def _grid(rows):
    return pd.DataFrame(rows, columns=["tier", "setting", "year", "ret", "captured"])


class TestWalkForward:

    def test_choice_uses_only_years_before_the_test_year(self):
        grid = _grid([
            ("Large", "A", 2020, 0.30, 0.1), ("Large", "B", 2020, 0.10, 0.1),
            ("Large", "A", 2021, -0.50, 0.1), ("Large", "B", 2021, 0.40, 0.1),
        ])

        result = walk_forward(grid, "ret", first_test_year=2021).iloc[0]

        assert result["chosen"] == "A"
        assert result["ret"] == pytest.approx(-0.50)

    def test_book_return_objective_compounds_rather_than_averages(self):
        grid = _grid([
            ("Large", "STEADY", 2020, 0.20, 0), ("Large", "STEADY", 2021, 0.20, 0),
            ("Large", "SWINGY", 2020, 1.00, 0), ("Large", "SWINGY", 2021, -0.55, 0),
            ("Large", "STEADY", 2022, 0.0, 0), ("Large", "SWINGY", 2022, 0.0, 0),
        ])

        result = walk_forward(grid, "ret", first_test_year=2022).iloc[0]

        assert result["chosen"] == "STEADY"


class TestAddLookbackReturns:

    def test_adds_missing_lookbacks_at_each_checkpoint(self):
        days = pd.bdate_range("2024-01-01", periods=100)
        close = pd.DataFrame({"A": np.arange(1.0, 101.0)}, index=days)
        panel = pd.DataFrame({"checkpoint": [days[-1]], "symbol": ["A"], "ret_60d": [0.0]})

        result = add_lookback_returns(panel, close, lookbacks=(60, 90)).iloc[0]

        assert result["ret_90d"] == pytest.approx(100 / 10 - 1)
        assert result["ret_60d"] == 0.0


class TestSettings:

    def test_grid_covers_every_combination(self):
        assert len(settings()) == 5 * 3 * 2 * 2

import numpy as np
import pandas as pd
import pytest

from alpha_tech_tracker.research.winner_progression import block_reason, cell, episodes


def _row(**overrides):
    row = {"close": 100.0, "ma50": 90.0, "ma200": 80.0, "ma200_rising": True, "dilution_10": 0.0, "rank": 3.0}
    row.update(overrides)
    return pd.Series(row)


class TestBlockReason:

    def test_trend_failure_is_reported_before_exclusions(self):
        assert block_reason(_row(close=85.0, dilution_10=1.0), ["dilution_10"], []) == "trend: below ma50"

    def test_exclusion_factor_is_named(self):
        assert block_reason(_row(dilution_10=1.0), ["dilution_10"], []) == "excluded: dilution_10"

    def test_eligible_stock_ranked_outside_the_list(self):
        assert block_reason(_row(rank=27.0), [], []) == "ranked below 15"

    def test_eligible_stock_without_a_score(self):
        assert block_reason(_row(rank=np.nan), [], []) == "no score"


class TestCell:

    def test_held_cell_shows_its_rank(self):
        assert cell(pd.Series({"reason": "held", "rank": 4.0})) == "H4"

    def test_trend_failure_cell(self):
        assert cell(pd.Series({"reason": "trend: ma200 falling", "rank": np.nan})) == "T"


class TestEpisodes:

    def _prog(self, reasons, ytd):
        cps = pd.date_range("2026-01-02", periods=len(reasons), freq="14D")
        return pd.DataFrame({"tier": "Large", "symbol": "WIN", "year_return_pct": 100.0, "checkpoint": cps,
                             "reason": reasons, "rank": [3.0 if r == "held" else 20.0 for r in reasons],
                             "ytd": ytd})

    def test_each_holding_stretch_records_exit_reason_and_return_gap(self):
        prog = self._prog(["ranked below 15", "held", "held", "trend: below ma50", "ranked below 15", "held"],
                          [0.0, 0.1, 0.3, 0.2, 0.25, 0.5])

        result = episodes(prog)

        first, second = result.iloc[0], result.iloc[1]
        assert first["checkpoints_held"] == 2
        assert first["exit_reason"] == "trend: below ma50"
        assert first["gain_while_held"] == pytest.approx(1.2 / 1.1 - 1)
        assert first["checkpoints_until_back"] == 2
        assert second["exit_reason"] == "still held"

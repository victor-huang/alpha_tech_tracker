import numpy as np
import pandas as pd
import pytest

from alpha_tech_tracker.research.selection_filters import (
    Variant,
    drop_funds,
    list_streak,
    performance,
    period_returns,
    rank_variant,
    run_portfolio,
)

CP = [pd.Timestamp("2026-01-02"), pd.Timestamp("2026-01-16"), pd.Timestamp("2026-01-30")]


def _rows(checkpoint, scores, tier="Large", streaks=None):
    streaks = streaks or {}
    return [{"checkpoint": checkpoint, "tier": tier, "symbol": s, "score_in": v, "dollar_volume_20d": 1e8,
             "streak": streaks.get(s, 0)} for s, v in scores.items()]


SCORE_ALL = Variant(lambda p: pd.Series(True, index=p.index), lambda p: p["score_in"])


class TestDropFunds:

    def test_removes_closed_end_funds_but_keeps_their_sponsors(self):
        panel = pd.DataFrame({"symbol": ["BST", "BLK", "NVDA"]})
        names = pd.Series({"BST": "BlackRock Science and Technology Trust", "BLK": "Blackrock, Inc.",
                           "NVDA": "NVIDIA Corporation"})

        result = drop_funds(panel, names)

        assert result["symbol"].tolist() == ["BLK", "NVDA"]


class TestRankVariant:

    def test_ranks_highest_score_first_within_checkpoint_and_tier(self):
        panel = pd.DataFrame(_rows(CP[0], {"A": 1.0, "B": 3.0}) + _rows(CP[0], {"C": 0.5}, tier="Small"))

        ranked = rank_variant(panel, SCORE_ALL, n=1).set_index("symbol")

        assert ranked.loc["B", "rank"] == 1
        assert ranked.loc["A", "rank"] == 2
        assert ranked.loc["C", "rank"] == 1

    def test_persistence_requires_a_top_ranking_at_the_previous_checkpoint(self):
        panel = pd.DataFrame(_rows(CP[0], {"OLD": 3.0, "MID": 2.0, "LOW": 1.0})
                             + _rows(CP[1], {"OLD": 1.0, "LOW": 2.0, "NEW": 9.0}))
        variant = Variant(SCORE_ALL.eligible, SCORE_ALL.score, persist=True)

        ranked = rank_variant(panel, variant, n=1)

        assert ranked["symbol"].tolist() == ["OLD"]
        assert ranked["checkpoint"].tolist() == [CP[1]]

    def test_liquidity_floor_drops_thin_names(self):
        panel = pd.DataFrame(_rows(CP[0], {"THIN": 5.0, "DEEP": 1.0}))
        panel.loc[panel["symbol"] == "THIN", "dollar_volume_20d"] = 1e6
        variant = Variant(SCORE_ALL.eligible, SCORE_ALL.score, liquid=True)

        ranked = rank_variant(panel, variant, n=1)

        assert ranked["symbol"].tolist() == ["DEEP"]


    def test_streak_cap_drops_names_on_the_list_too_long(self):
        panel = pd.DataFrame(_rows(CP[0], {"TIRED": 5.0, "FRESH": 1.0}, streaks={"TIRED": 9, "FRESH": 1}))
        variant = Variant(SCORE_ALL.eligible, SCORE_ALL.score, max_streak=8)

        ranked = rank_variant(panel, variant, n=1)

        assert ranked["symbol"].tolist() == ["FRESH"]

    def test_prefer_promotes_names_with_the_factor_within_the_pool(self):
        panel = pd.DataFrame(_rows(CP[0], {"TOP": 5.0, "STEADY": 4.0, "OUTSIDE": 1.0},
                                   streaks={"TOP": 1, "STEADY": 6, "OUTSIDE": 12}))
        variant = Variant(SCORE_ALL.eligible, SCORE_ALL.score, prefer=("streak",))

        ranked = rank_variant(panel, variant, n=1).set_index("symbol")

        assert ranked.loc["STEADY", "rank"] == 1
        assert ranked.loc["TOP", "rank"] == 2
        assert ranked.loc["OUTSIDE", "rank"] == 3

    def test_hold_on_list_marks_names_still_on_the_list(self):
        panel = pd.DataFrame(_rows(CP[0], {"ON": 1.0, "OFF": 2.0}, streaks={"ON": 3}))
        variant = Variant(SCORE_ALL.eligible, SCORE_ALL.score, hold_on_list=True)

        ranked = rank_variant(panel, variant, n=1).set_index("symbol")

        assert ranked.loc["ON", "keep"]
        assert not ranked.loc["OFF", "keep"]


    def test_exclude_drops_flagged_names_but_keeps_unknown(self):
        panel = pd.DataFrame(_rows(CP[0], {"FADED": 5.0, "CLEAN": 2.0, "UNKNOWN": 1.0}))
        panel["jump_faded_60d"] = [1.0, 0.0, np.nan]
        variant = Variant(SCORE_ALL.eligible, SCORE_ALL.score, exclude=("jump_faded_60d",))

        ranked = rank_variant(panel, variant, n=1)

        assert ranked["symbol"].tolist() == ["CLEAN", "UNKNOWN"]

    def test_require_keeps_only_flagged_names(self):
        panel = pd.DataFrame(_rows(CP[0], {"STRONG": 1.0, "WEAK": 5.0, "UNKNOWN": 3.0}))
        panel["group_top20_120d"] = [1.0, 0.0, np.nan]
        variant = Variant(SCORE_ALL.eligible, SCORE_ALL.score, require=("group_top20_120d",))

        ranked = rank_variant(panel, variant, n=1)

        assert ranked["symbol"].tolist() == ["STRONG"]


class TestListStreak:

    def test_counts_consecutive_checkpoints_and_resets_after_a_gap(self):
        panel = pd.DataFrame({"checkpoint": CP + CP, "symbol": ["A"] * 3 + ["B"] * 3,
                              "flag": [True, True, True, True, False, True]})

        result = list_streak(panel, "flag")

        assert result.tolist() == [1, 2, 3, 1, 0, 1]


class TestPeriodReturns:

    def test_return_runs_to_next_checkpoint_and_last_to_latest_close(self):
        idx = pd.bdate_range("2026-01-02", "2026-02-03")
        close = pd.DataFrame({"A": np.arange(len(idx), dtype=float) + 100}, index=idx)

        result = period_returns(close, CP)

        assert result.loc[CP[0], "A"] == pytest.approx(close.loc[CP[1], "A"] / 100 - 1)
        assert result.loc[CP[2], "A"] == pytest.approx(close["A"].iloc[-1] / close.loc[CP[2], "A"] - 1)


class TestRunPortfolio:

    def _ranked(self):
        return pd.DataFrame([
            {"checkpoint": CP[0], "symbol": "A", "rank": 1}, {"checkpoint": CP[0], "symbol": "B", "rank": 2},
            {"checkpoint": CP[1], "symbol": "B", "rank": 1}, {"checkpoint": CP[1], "symbol": "C", "rank": 2},
            {"checkpoint": CP[1], "symbol": "A", "rank": 3},
        ])

    def _returns(self):
        return pd.DataFrame({"A": [0.10, 0.0, 0.0], "B": [0.0, 0.0, 0.0], "C": [0.0, 0.20, 0.0]}, index=CP)

    def test_holds_top_n_equal_weight(self):
        book = run_portfolio(self._ranked(), self._returns(), pd.Series(True, index=CP), n=1, buffer=1, gate=False,
                             cost=0.0)

        assert book.loc[CP[0], "ret"] == pytest.approx(0.10)
        assert book.loc[CP[1], "ret"] == pytest.approx(0.0)

    def test_buffer_keeps_a_holding_that_slipped_in_rank(self):
        book = run_portfolio(self._ranked(), self._returns(), pd.Series(True, index=CP), n=1, buffer=3, gate=False,
                             cost=0.0)

        assert book.loc[CP[1], "ret"] == pytest.approx(0.0)
        assert book.loc[CP[1], "turnover"] == pytest.approx(0.0)

    def test_keep_flag_holds_a_name_past_the_buffer(self):
        ranked = self._ranked().assign(keep=lambda r: r["symbol"] == "A")

        book = run_portfolio(ranked, self._returns(), pd.Series(True, index=CP), n=1, buffer=1, gate=False, cost=0.0)

        assert book.loc[CP[1], "turnover"] == pytest.approx(0.0)

    def test_gate_moves_to_cash_when_index_below_average(self):
        regime = pd.Series([False, True, True], index=CP)

        book = run_portfolio(self._ranked(), self._returns(), regime, n=1, buffer=1, gate=True, cost=0.0)

        assert book.loc[CP[0], "ret"] == 0.0
        assert book.loc[CP[0], "names"] == 0

    def test_costs_charged_on_traded_weight(self):
        book = run_portfolio(self._ranked(), self._returns(), pd.Series(True, index=CP), n=1, buffer=1, gate=False,
                             cost=0.001)

        assert book.loc[CP[0], "ret"] == pytest.approx(0.10 - 0.001)
        assert book.loc[CP[1], "ret"] == pytest.approx(0.0 - 0.002)


class TestPerformance:

    def test_max_drawdown_from_peak(self):
        ret = pd.Series([0.10, -0.50, 0.20])

        assert performance(ret)["max_dd"] == pytest.approx(-0.5)

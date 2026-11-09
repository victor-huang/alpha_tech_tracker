import numpy as np
import pandas as pd
import pytest

from alpha_tech_tracker.research.ranking_exits import (
    ExitRule,
    daily_data,
    industry_relative,
    residual_momentum,
    run_daily_book,
)
from alpha_tech_tracker.research.selection_filters import period_returns, run_portfolio

DAYS = pd.bdate_range("2024-01-01", periods=400)


def _ranked(rows):
    return pd.DataFrame(rows, columns=["checkpoint", "symbol", "rank"]).assign(tier="Large", keep=False)


class TestResidualMomentum:

    def test_stock_that_only_follows_the_market_scores_below_one_with_its_own_drift(self):
        rng = np.random.default_rng(0)
        market_ret = rng.normal(0.0005, 0.01, len(DAYS))
        noise = rng.normal(0, 0.005, (len(DAYS), 2))
        own_drift = np.array([0.0, 0.003])
        stock_ret = 1.5 * market_ret[:, None] + noise + own_drift
        close = pd.DataFrame(100 * np.exp(np.cumsum(stock_ret, axis=0)), index=DAYS, columns=["BETA", "DRIFT"])
        market = pd.Series(100 * np.exp(np.cumsum(market_ret)), index=DAYS)

        result = residual_momentum(close, market, [DAYS[-1]]).iloc[0]

        assert abs(result["BETA"]) < 2
        assert result["DRIFT"] > 5

    def test_checkpoints_without_a_full_beta_window_are_skipped(self):
        close = pd.DataFrame({"A": np.linspace(10, 20, len(DAYS))}, index=DAYS)
        market = pd.Series(np.linspace(10, 12, len(DAYS)), index=DAYS)

        result = residual_momentum(close, market, [DAYS[100]])

        assert result.empty


class TestIndustryRelative:

    def test_return_above_industry_median_per_unit_of_volatility(self):
        panel = pd.DataFrame({"checkpoint": [DAYS[0]] * 6, "industry": ["Chips"] * 5 + ["Tiny"],
                              "ret_120d": [0.1, 0.2, 0.3, 0.4, 0.9, 0.5], "vol_60d": [0.5] * 6})

        result = industry_relative(panel)

        assert result.iloc[4] == pytest.approx((0.9 - 0.3) / 0.5)
        assert np.isnan(result.iloc[5])


class TestRunDailyBook:

    def _bars(self, prices):
        close = pd.DataFrame(prices, index=DAYS[:len(next(iter(prices.values())))])
        return close, close * 1e6

    def test_without_exit_rules_matches_the_checkpoint_portfolio(self):
        close, dollar_volume = self._bars({"A": np.linspace(10, 14, 21), "B": np.linspace(10, 8, 21)})
        checkpoints = [DAYS[0], DAYS[10]]
        ranked = _ranked([(DAYS[0], "A", 1), (DAYS[0], "B", 2), (DAYS[10], "A", 1)])

        daily = run_daily_book(ranked, daily_data(close, dollar_volume), checkpoints, 2, 2, ExitRule(), 0.001)
        periodic = run_portfolio(ranked, period_returns(close, checkpoints), pd.Series(dtype=bool), 2, 2, False,
                                 0.001)

        assert daily["ret"].values == pytest.approx(periodic["ret"].values)

    def test_trailing_stop_sells_and_holds_cash_until_the_next_checkpoint(self):
        prices = [10.0, 11.0, 12.0, 9.0, 6.0, 6.0]
        close, dollar_volume = self._bars({"A": prices})
        ranked = _ranked([(DAYS[0], "A", 1)])

        book = run_daily_book(ranked, daily_data(close, dollar_volume), [DAYS[0]], 1, 1, ExitRule(trail=0.2), 0.0)

        assert book["ret"].iloc[0] == pytest.approx(9.0 / 10.0 - 1)
        assert book["exits"].iloc[0] == 1

    def test_inverse_volatility_weights_the_calmer_stock_more(self):
        close, dollar_volume = self._bars({"CALM": [10.0, 11.0], "WILD": [10.0, 10.0]})
        ranked = _ranked([(DAYS[0], "CALM", 1), (DAYS[0], "WILD", 2)])
        vol = pd.DataFrame({"CALM": [0.2], "WILD": [0.6]}, index=[DAYS[0]])

        book = run_daily_book(ranked, daily_data(close, dollar_volume), [DAYS[0]], 2, 2,
                              ExitRule(inverse_vol=True), 0.0, vol)

        assert book["ret"].iloc[0] == pytest.approx(0.75 * 0.10)

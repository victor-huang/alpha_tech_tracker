import pandas as pd

from alpha_tech_tracker.research.short_hedge import (
    basket_returns,
    basket_turnover,
    downtrend,
    hedged_returns,
    weakest,
)

CPS = [pd.Timestamp("2026-01-02"), pd.Timestamp("2026-01-16"), pd.Timestamp("2026-01-30")]


class TestDowntrend:
    def test_true_only_when_below_both_averages(self):
        days = pd.bdate_range("2025-01-01", periods=260)
        close = pd.Series(100.0, index=days)
        close.iloc[-1] = 50.0

        on = downtrend(close, [days[-2], days[-1]])

        assert on.tolist() == [False, True]


class TestWeakest:
    def _panel(self):
        return pd.DataFrame({"checkpoint": CPS[0], "tier": "Large", "symbol": ["A", "B", "C", "D"],
                             "ret_180d": [-0.5, -0.3, 0.2, -0.9], "vol_60d": [0.04, 0.04, 0.04, 0.04],
                             "dollar_volume_20d": [5e8, 4e8, 3e8, 1e6]})

    def test_takes_lowest_scores(self):
        out = weakest(self._panel(), n=2, liquid_rank=3)

        assert out["symbol"].tolist() == ["A", "B"]

    def test_skips_illiquid_names(self):
        out = weakest(self._panel(), n=1, liquid_rank=3)

        assert "D" not in out["symbol"].tolist()


class TestBasketReturns:
    def test_equal_weights_the_basket(self):
        basket = pd.DataFrame({"checkpoint": [CPS[0], CPS[0]], "symbol": ["A", "B"]})
        returns = pd.DataFrame({"A": [-0.2], "B": [0.1]}, index=[CPS[0]])

        assert round(basket_returns(basket, returns)[CPS[0]], 4) == -0.05


class TestBasketTurnover:
    def test_full_basket_when_switching_on_and_off(self):
        basket = pd.DataFrame({"checkpoint": [CPS[0], CPS[1]], "symbol": ["A", "A"]})
        on = pd.Series([True, True, False], index=CPS)

        assert basket_turnover(basket, on).tolist() == [1.0, 0.0, 1.0]

    def test_share_of_names_replaced_while_on(self):
        basket = pd.DataFrame({"checkpoint": [CPS[0], CPS[0], CPS[1], CPS[1]], "symbol": ["A", "B", "A", "C"]})
        on = pd.Series([True, True], index=CPS[:2])

        assert basket_turnover(basket, on).tolist() == [1.0, 0.5]


class TestHedgedReturns:
    def test_subtracts_fraction_of_basket_while_on(self):
        book = pd.Series([0.02, 0.02], index=CPS[:2])
        basket = pd.Series([-0.10, -0.10], index=CPS[:2])
        on = pd.Series([True, False], index=CPS[:2])

        out = hedged_returns(book, basket, on, 0.5, cost=0.0, borrow_rate=0.0)

        assert [round(v, 4) for v in out] == [0.07, 0.02]

    def test_charges_borrow_and_trading_costs_while_on(self):
        book = pd.Series([0.0], index=CPS[:1])
        basket = pd.Series([0.0], index=CPS[:1])
        on = pd.Series([True], index=CPS[:1])

        out = hedged_returns(book, basket, on, 1.0, cost=0.001, borrow_rate=0.365)

        assert round(out.iloc[0], 4) == -(0.014 + 0.001)

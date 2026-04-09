from alpha_tech_tracker.op_momentum_strategy.config import (
    MAX_CAPITAL_PERCENTAGE_PER_SYMBOL_IN_WINDOW,
    RANK_WEIGHTS,
)
from alpha_tech_tracker.op_momentum_strategy.position_sizer import PositionSizer

from conftest import _D, _make_alpaca_client, _make_option_quote


def _make_stock_quote(bid, ask):
    return {
        "QuoteResponse": {
            "QuoteData": [{"All": {"bid": bid, "ask": ask, "bid_size": 1, "ask_size": 1, "last": None}}]
        }
    }


class TestPositionSizer:
    def test_computes_contract_count_from_buying_power(self):
        client = _make_alpaca_client()
        client.get_accounts.return_value = {"buying_power": 25000.0}
        client.get_option_quote_by_occ.return_value = _make_option_quote(bid=8.00, ask=9.00)

        sizer = PositionSizer(client)
        contracts, limit_price = sizer.compute("NVDA260328C00730000")

        budget = _D("25000") * MAX_CAPITAL_PERCENTAGE_PER_SYMBOL_IN_WINDOW
        mid = (_D("8.00") + _D("9.00")) / _D("2")
        expected_contracts = max(1, int(budget / (mid * _D("100"))))

        assert contracts == expected_contracts
        assert limit_price == _D("8.50")

    def test_minimum_one_contract_when_budget_is_tiny(self):
        client = _make_alpaca_client()
        client.get_accounts.return_value = {"buying_power": 100.0}
        client.get_option_quote_by_occ.return_value = _make_option_quote(bid=50.00, ask=60.00)

        sizer = PositionSizer(client)
        contracts, _ = sizer.compute("NVDA260328C00730000")

        assert contracts == 1

    def test_returns_one_contract_and_ask_when_mid_is_zero(self):
        client = _make_alpaca_client()
        client.get_accounts.return_value = {"buying_power": 25000.0}
        client.get_option_quote_by_occ.return_value = _make_option_quote(bid=0.0, ask=0.0)

        sizer = PositionSizer(client)
        contracts, limit_price = sizer.compute("OPT")

        assert contracts == 1
        assert limit_price == _D("0")


class TestWindowBudgetSizing:
    def test_window_budget_bypasses_get_accounts(self):
        client = _make_alpaca_client()
        client.get_option_quote_by_occ.return_value = _make_option_quote(bid=8.00, ask=9.00)

        sizer = PositionSizer(client)
        sizer.compute("NVDA260328C00730000", window_budget=_D("20000"))

        client.get_accounts.assert_not_called()

    def test_window_budget_computes_contracts_from_explicit_budget(self):
        client = _make_alpaca_client()
        client.get_option_quote_by_occ.return_value = _make_option_quote(bid=8.00, ask=9.00)

        sizer = PositionSizer(client)
        contracts, limit_price = sizer.compute(
            "NVDA260328C00730000", window_budget=_D("20000")
        )

        budget = _D("20000")
        mid = (_D("8.00") + _D("9.00")) / _D("2")
        expected_contracts = max(1, int(budget / (mid * _D("100"))))

        assert contracts == expected_contracts
        assert limit_price == _D("8.50")

    def test_window_budget_combined_with_capital_weight(self):
        client = _make_alpaca_client()
        client.get_option_quote_by_occ.return_value = _make_option_quote(bid=8.00, ask=9.00)
        weight = _D("0.5")

        sizer = PositionSizer(client)
        contracts, _ = sizer.compute(
            "NVDA260328C00730000", capital_weight=weight, window_budget=_D("20000")
        )

        budget = _D("20000") * weight
        mid = (_D("8.00") + _D("9.00")) / _D("2")
        expected_contracts = max(1, int(budget / (mid * _D("100"))))

        assert contracts == expected_contracts

    def test_none_window_budget_falls_back_to_account_balance(self):
        client = _make_alpaca_client()
        client.get_accounts.return_value = {"buying_power": 30000.0}
        client.get_option_quote_by_occ.return_value = _make_option_quote(bid=8.00, ask=9.00)

        sizer = PositionSizer(client)
        sizer.compute("NVDA260328C00730000", window_budget=None)

        client.get_accounts.assert_called_once()


class TestRankWeightedSizing:
    def test_rank_zero_uses_first_weight(self):
        client = _make_alpaca_client()
        client.get_accounts.return_value = {"buying_power": 25000.0}
        client.get_option_quote_by_occ.return_value = _make_option_quote(bid=8.00, ask=9.00)

        sizer = PositionSizer(client)
        weight = _D(str(RANK_WEIGHTS[0]))
        contracts, _ = sizer.compute("NVDA260328C00730000", capital_weight=weight)

        budget = _D("25000") * MAX_CAPITAL_PERCENTAGE_PER_SYMBOL_IN_WINDOW * weight
        mid = (_D("8.00") + _D("9.00")) / _D("2")
        expected = max(1, int(budget / (mid * _D("100"))))
        assert contracts == expected

    def test_rank_one_uses_second_weight(self):
        client = _make_alpaca_client()
        client.get_accounts.return_value = {"buying_power": 25000.0}
        client.get_option_quote_by_occ.return_value = _make_option_quote(bid=8.00, ask=9.00)

        sizer = PositionSizer(client)
        weight = _D(str(RANK_WEIGHTS[1]))
        contracts, _ = sizer.compute("NVDA260328C00730000", capital_weight=weight)

        budget = _D("25000") * MAX_CAPITAL_PERCENTAGE_PER_SYMBOL_IN_WINDOW * weight
        mid = (_D("8.00") + _D("9.00")) / _D("2")
        expected = max(1, int(budget / (mid * _D("100"))))
        assert contracts == expected


class TestComputeStock:
    def test_computes_share_count_from_budget(self):
        client = _make_alpaca_client()
        client.get_accounts.return_value = {"buying_power": 25000.0}
        client.get_stock_quote.return_value = _make_stock_quote(bid=99.00, ask=101.00)

        sizer = PositionSizer(client)
        shares, limit_price = sizer.compute_stock("NVDA", _D("100"))

        budget = _D("25000") * MAX_CAPITAL_PERCENTAGE_PER_SYMBOL_IN_WINDOW
        mid = (_D("99.00") + _D("101.00")) / _D("2")
        expected_shares = max(1, int(budget / mid))

        assert shares == expected_shares
        assert limit_price == _D("100.00")

    def test_minimum_one_share_when_budget_is_tiny(self):
        client = _make_alpaca_client()
        client.get_accounts.return_value = {"buying_power": 1.0}
        client.get_stock_quote.return_value = _make_stock_quote(bid=500.00, ask=502.00)

        sizer = PositionSizer(client)
        shares, _ = sizer.compute_stock("TSLA", _D("501"))

        assert shares == 1

    def test_returns_one_share_when_quote_and_stock_price_are_zero(self):
        client = _make_alpaca_client()
        client.get_accounts.return_value = {"buying_power": 25000.0}
        client.get_stock_quote.return_value = _make_stock_quote(bid=0.0, ask=0.0)

        sizer = PositionSizer(client)
        shares, limit_price = sizer.compute_stock("NVDA", _D("0"))

        assert shares == 1
        assert limit_price == _D("0")

    def test_falls_back_to_stock_price_when_quote_bid_ask_are_zero(self):
        client = _make_alpaca_client()
        client.get_accounts.return_value = {"buying_power": 25000.0}
        client.get_stock_quote.return_value = _make_stock_quote(bid=0.0, ask=0.0)

        sizer = PositionSizer(client)
        shares, limit_price = sizer.compute_stock("NVDA", _D("100"))

        # bid/ask 0 falls back to stock_price=100, so mid=100
        budget = _D("25000") * MAX_CAPITAL_PERCENTAGE_PER_SYMBOL_IN_WINDOW
        expected_shares = max(1, int(budget / _D("100")))
        assert shares == expected_shares
        assert limit_price == _D("100.00")

    def test_window_budget_bypasses_get_accounts(self):
        client = _make_alpaca_client()
        client.get_stock_quote.return_value = _make_stock_quote(bid=99.00, ask=101.00)

        sizer = PositionSizer(client)
        sizer.compute_stock("NVDA", _D("100"), window_budget=_D("20000"))

        client.get_accounts.assert_not_called()

    def test_window_budget_combined_with_capital_weight(self):
        client = _make_alpaca_client()
        client.get_stock_quote.return_value = _make_stock_quote(bid=99.00, ask=101.00)
        weight = _D("0.5")

        sizer = PositionSizer(client)
        shares, _ = sizer.compute_stock(
            "NVDA", _D("100"), capital_weight=weight, window_budget=_D("20000")
        )

        budget = _D("20000") * weight
        mid = (_D("99.00") + _D("101.00")) / _D("2")
        expected_shares = max(1, int(budget / mid))

        assert shares == expected_shares

    def test_no_options_multiplier_applied(self):
        client = _make_alpaca_client()
        client.get_stock_quote.return_value = _make_stock_quote(bid=99.00, ask=101.00)

        sizer = PositionSizer(client)
        shares_stock, _ = sizer.compute_stock("NVDA", _D("100"), window_budget=_D("20000"))

        budget = _D("20000")
        mid = _D("100.00")
        shares_expected = max(1, int(budget / mid))
        shares_would_be_with_multiplier = max(1, int(budget / (mid * _D("100"))))

        assert shares_stock == shares_expected
        assert shares_stock != shares_would_be_with_multiplier


class TestMockStockPriceCompute:
    # strike $90 call — ITM when stock=$100 (intrinsic=$10)
    _CALL_SYM = "NVDA260328C00090000"
    # strike $110 put — ITM when stock=$100 (intrinsic=$10)
    _PUT_SYM = "NVDA260328P00110000"

    def test_skips_api_quote_when_mock_stock_price_provided(self):
        client = _make_alpaca_client()

        sizer = PositionSizer(client)
        sizer.compute(self._CALL_SYM, window_budget=_D("25000"), mock_stock_price=_D("100"))

        client.get_option_quote_by_occ.assert_not_called()

    def test_call_intrinsic_pricing_from_stock_price(self):
        # stock=$100, strike=$90 call → intrinsic=$10, ×1.20=$12.00
        # budget=$25000 (capital_weight=1, no MAX_CAPITAL_... applied for window_budget)
        # contracts=floor(25000/1200)=20
        client = _make_alpaca_client()

        sizer = PositionSizer(client)
        contracts, limit_price = sizer.compute(
            self._CALL_SYM, window_budget=_D("25000"), mock_stock_price=_D("100")
        )

        assert limit_price == _D("12.00")
        assert contracts == 20

    def test_put_intrinsic_pricing_from_stock_price(self):
        # stock=$100, strike=$110 put → intrinsic=$10, ×1.20=$12.00
        # budget=$25000 (capital_weight=1); contracts=floor(25000/1200)=20
        client = _make_alpaca_client()

        sizer = PositionSizer(client)
        contracts, limit_price = sizer.compute(
            self._PUT_SYM, window_budget=_D("25000"), mock_stock_price=_D("100")
        )

        assert limit_price == _D("12.00")
        assert contracts == 20

    def test_infers_call_type_from_c_in_symbol(self):
        # stock=$95, strike=$90: call intrinsic=$5 → $6.00; if wrongly put: intrinsic=0
        client = _make_alpaca_client()

        sizer = PositionSizer(client)
        _, limit_price = sizer.compute(
            self._CALL_SYM, window_budget=_D("25000"), mock_stock_price=_D("95")
        )

        assert limit_price == _D("6.00")

    def test_infers_put_type_from_p_in_symbol(self):
        # stock=$105, strike=$110: put intrinsic=$5 → $6.00; if wrongly call: intrinsic=0
        client = _make_alpaca_client()

        sizer = PositionSizer(client)
        _, limit_price = sizer.compute(
            self._PUT_SYM, window_budget=_D("25000"), mock_stock_price=_D("105")
        )

        assert limit_price == _D("6.00")

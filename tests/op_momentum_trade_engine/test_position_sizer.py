from alpha_tech_tracker.op_momentum_strategy.config import CAPITAL_PER_SYMBOL, RANK_WEIGHTS
from alpha_tech_tracker.op_momentum_strategy.position_sizer import PositionSizer

from conftest import _D, _make_alpaca_client, _make_option_quote


class TestPositionSizer:
    def test_computes_contract_count_from_buying_power(self):
        client = _make_alpaca_client()
        client.get_accounts.return_value = {"buying_power": 25000.0}
        client._option_data_client.get_option_latest_quote.return_value = {
            "NVDA260328C00730000": _make_option_quote(bid=8.00, ask=9.00)
        }

        sizer = PositionSizer(client)
        contracts, limit_price = sizer.compute("NVDA260328C00730000")

        budget = _D("25000") * CAPITAL_PER_SYMBOL
        mid = (_D("8.00") + _D("9.00")) / _D("2")
        expected_contracts = max(1, int(budget / (mid * _D("100"))))

        assert contracts == expected_contracts
        assert limit_price == _D("8.50")

    def test_minimum_one_contract_when_budget_is_tiny(self):
        client = _make_alpaca_client()
        client.get_accounts.return_value = {"buying_power": 100.0}
        client._option_data_client.get_option_latest_quote.return_value = {
            "NVDA260328C00730000": _make_option_quote(bid=50.00, ask=60.00)
        }

        sizer = PositionSizer(client)
        contracts, _ = sizer.compute("NVDA260328C00730000")

        assert contracts == 1

    def test_returns_one_contract_and_ask_when_mid_is_zero(self):
        client = _make_alpaca_client()
        client.get_accounts.return_value = {"buying_power": 25000.0}
        client._option_data_client.get_option_latest_quote.return_value = {
            "OPT": _make_option_quote(bid=0.0, ask=0.0)
        }

        sizer = PositionSizer(client)
        contracts, limit_price = sizer.compute("OPT")

        assert contracts == 1
        assert limit_price == _D("0")


class TestRankWeightedSizing:
    def test_rank_zero_uses_first_weight(self):
        client = _make_alpaca_client()
        client.get_accounts.return_value = {"buying_power": 25000.0}
        client._option_data_client.get_option_latest_quote.return_value = {
            "NVDA260328C00730000": _make_option_quote(bid=8.00, ask=9.00)
        }

        sizer = PositionSizer(client)
        weight = _D(str(RANK_WEIGHTS[0]))
        contracts, _ = sizer.compute("NVDA260328C00730000", capital_weight=weight)

        budget = _D("25000") * CAPITAL_PER_SYMBOL * weight
        mid = (_D("8.00") + _D("9.00")) / _D("2")
        expected = max(1, int(budget / (mid * _D("100"))))
        assert contracts == expected

    def test_rank_one_uses_second_weight(self):
        client = _make_alpaca_client()
        client.get_accounts.return_value = {"buying_power": 25000.0}
        client._option_data_client.get_option_latest_quote.return_value = {
            "NVDA260328C00730000": _make_option_quote(bid=8.00, ask=9.00)
        }

        sizer = PositionSizer(client)
        weight = _D(str(RANK_WEIGHTS[1]))
        contracts, _ = sizer.compute("NVDA260328C00730000", capital_weight=weight)

        budget = _D("25000") * CAPITAL_PER_SYMBOL * weight
        mid = (_D("8.00") + _D("9.00")) / _D("2")
        expected = max(1, int(budget / (mid * _D("100"))))
        assert contracts == expected

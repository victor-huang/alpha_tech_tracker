from datetime import date
from unittest.mock import patch

import pytest

from alpha_tech_tracker.op_momentum_strategy.contract_selector import (
    OptionContractSelector,
    _next_friday,
    _strike_increment,
)

from conftest import _D, _make_alpaca_client

_NEXT_FRIDAY_PATH = (
    "alpha_tech_tracker.op_momentum_strategy.contract_selector._next_friday"
)


class TestNextFriday:
    def test_monday_returns_same_week_friday(self):
        monday = date(2026, 3, 23)
        assert _next_friday(monday) == date(2026, 3, 27)

    def test_friday_returns_next_week_friday(self):
        friday = date(2026, 3, 27)
        assert _next_friday(friday) == date(2026, 4, 3)

    def test_saturday_returns_next_week_friday(self):
        saturday = date(2026, 3, 28)
        assert _next_friday(saturday) == date(2026, 4, 3)

    def test_thursday_returns_next_day_friday(self):
        thursday = date(2026, 3, 26)
        assert _next_friday(thursday) == date(2026, 3, 27)


class TestStrikeIncrement:
    def test_low_price_stock_uses_one_dollar_increment(self):
        assert _strike_increment(_D("30")) == _D("1")

    def test_mid_price_stock_uses_five_dollar_increment(self):
        assert _strike_increment(_D("100")) == _D("5")
        assert _strike_increment(_D("200")) == _D("5")

    def test_high_price_stock_uses_ten_dollar_increment(self):
        assert _strike_increment(_D("820")) == _D("10")
        assert _strike_increment(_D("500")) == _D("10")

    def test_boundary_at_fifty_uses_five_dollar_increment(self):
        assert _strike_increment(_D("50")) == _D("5")


class TestOptionContractSelector:
    @patch(_NEXT_FRIDAY_PATH, return_value=date(2026, 3, 27))
    def test_bullish_signal_selects_call_with_lower_strike(self, _):
        client = _make_alpaca_client()
        client.get_options_contracts.return_value = [
            {"symbol": "NVDA260328C00730000", "strike_price": 730.0},
            {"symbol": "NVDA260328C00740000", "strike_price": 740.0},
        ]

        selector = OptionContractSelector(client)
        symbol = selector.select("NVDA", "BULLISH", 820.0)

        assert symbol == "NVDA260328C00730000"
        client.get_options_contracts.assert_called_once_with(
            underlying_symbol="NVDA",
            expiration_date=date(2026, 3, 27),
            option_type="call",
            strike_price_gte="656",
            strike_price_lte="984",
            limit=50,
        )

    @patch(_NEXT_FRIDAY_PATH, return_value=date(2026, 3, 27))
    def test_bearish_signal_selects_put_with_higher_strike(self, _):
        client = _make_alpaca_client()
        client.get_options_contracts.return_value = [
            {"symbol": "NVDA260328P00910000", "strike_price": 910.0},
            {"symbol": "NVDA260328P00900000", "strike_price": 900.0},
        ]

        selector = OptionContractSelector(client)
        symbol = selector.select("NVDA", "BEARISH", 820.0)

        assert symbol == "NVDA260328P00900000"

    @patch(_NEXT_FRIDAY_PATH, return_value=date(2026, 3, 27))
    def test_picks_contract_closest_to_target_strike(self, _):
        client = _make_alpaca_client()
        client.get_options_contracts.return_value = [
            {"symbol": "CRWD260328C00085000", "strike_price": 85.0},
            {"symbol": "CRWD260328C00090000", "strike_price": 90.0},
            {"symbol": "CRWD260328C00095000", "strike_price": 95.0},
        ]

        selector = OptionContractSelector(client)
        # stock @ 100 → target call strike = floor(90/5)*5 = 90
        symbol = selector.select("CRWD", "BULLISH", 100.0)

        assert symbol == "CRWD260328C00090000"

    @patch(_NEXT_FRIDAY_PATH, return_value=date(2026, 3, 27))
    def test_raises_when_no_contracts_found(self, _):
        client = _make_alpaca_client()
        client.get_options_contracts.return_value = []

        selector = OptionContractSelector(client)

        with pytest.raises(RuntimeError, match="No call contracts found"):
            selector.select("NVDA", "BULLISH", 820.0)

    @patch(_NEXT_FRIDAY_PATH, return_value=date(2026, 3, 27))
    def test_floating_point_safe_strike_calculation(self, _):
        """100 * 1.10 = 110.000...01 must not round up to 115."""
        client = _make_alpaca_client()
        client.get_options_contracts.return_value = [
            {"symbol": "COIN260328P00110000", "strike_price": 110.0},
        ]

        selector = OptionContractSelector(client)
        symbol = selector.select("COIN", "BEARISH", 100.0)

        call_args = client.get_options_contracts.call_args
        assert call_args.kwargs["strike_price_lte"] == "120"
        assert call_args.kwargs["strike_price_gte"] == "80"
        assert call_args.kwargs["limit"] == 50
        assert symbol == "COIN260328P00110000"

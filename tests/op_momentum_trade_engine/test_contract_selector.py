from datetime import date
from unittest.mock import patch

import pytest

from alpha_tech_tracker.op_momentum_strategy.contract_selector import (
    OptionContractSelector,
    _end_of_next_month,
    _is_nyse_holiday,
    _next_friday,
    _strike_increment,
)

from conftest import _D, _make_alpaca_client

_TODAY_PATH = "alpha_tech_tracker.op_momentum_strategy.contract_selector._today"
_NEXT_FRIDAY_PATH = (
    "alpha_tech_tracker.op_momentum_strategy.contract_selector._next_friday"
)
_IS_NYSE_HOLIDAY_PATH = (
    "alpha_tech_tracker.op_momentum_strategy.contract_selector._is_nyse_holiday"
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


class TestEndOfNextMonth:
    def test_march_returns_end_of_april(self):
        assert _end_of_next_month(date(2026, 3, 23)) == date(2026, 4, 30)

    def test_november_returns_end_of_december(self):
        assert _end_of_next_month(date(2026, 11, 1)) == date(2026, 12, 31)

    def test_december_returns_end_of_january_next_year(self):
        assert _end_of_next_month(date(2026, 12, 1)) == date(2027, 1, 31)

    def test_january_returns_end_of_february(self):
        assert _end_of_next_month(date(2026, 1, 15)) == date(2026, 2, 28)


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


class TestIsNyseHoliday:
    def test_good_friday_is_a_holiday(self):
        assert _is_nyse_holiday(date(2026, 4, 3)) is True

    def test_regular_friday_is_not_a_holiday(self):
        assert _is_nyse_holiday(date(2026, 3, 27)) is False

    def test_christmas_observed_on_friday_is_a_holiday(self):
        assert _is_nyse_holiday(date(2026, 12, 25)) is True


class TestOptionContractSelector:
    @patch(_TODAY_PATH, return_value=date(2026, 3, 23))  # Monday
    @patch(_NEXT_FRIDAY_PATH, return_value=date(2026, 3, 27))
    def test_bullish_signal_selects_call_with_lower_strike(self, _, __):
        client = _make_alpaca_client()
        client.get_options_contracts.return_value = [
            {"symbol": "NVDA260328C00730000", "strike_price": 730.0, "expiration_date": "2026-03-27"},
            {"symbol": "NVDA260328C00740000", "strike_price": 740.0, "expiration_date": "2026-03-27"},
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

    @patch(_TODAY_PATH, return_value=date(2026, 3, 23))  # Monday
    @patch(_NEXT_FRIDAY_PATH, return_value=date(2026, 3, 27))
    def test_bearish_signal_selects_put_with_higher_strike(self, _, __):
        client = _make_alpaca_client()
        client.get_options_contracts.return_value = [
            {"symbol": "NVDA260328P00910000", "strike_price": 910.0, "expiration_date": "2026-03-27"},
            {"symbol": "NVDA260328P00900000", "strike_price": 900.0, "expiration_date": "2026-03-27"},
        ]

        selector = OptionContractSelector(client)
        symbol = selector.select("NVDA", "BEARISH", 820.0)

        assert symbol == "NVDA260328P00900000"

    @patch(_TODAY_PATH, return_value=date(2026, 3, 23))  # Monday
    @patch(_NEXT_FRIDAY_PATH, return_value=date(2026, 3, 27))
    def test_picks_contract_closest_to_target_strike(self, _, __):
        client = _make_alpaca_client()
        client.get_options_contracts.return_value = [
            {"symbol": "CRWD260328C00085000", "strike_price": 85.0, "expiration_date": "2026-03-27"},
            {"symbol": "CRWD260328C00090000", "strike_price": 90.0, "expiration_date": "2026-03-27"},
            {"symbol": "CRWD260328C00095000", "strike_price": 95.0, "expiration_date": "2026-03-27"},
        ]

        selector = OptionContractSelector(client)
        # stock @ 100 → target call strike = floor(90/5)*5 = 90
        symbol = selector.select("CRWD", "BULLISH", 100.0)

        assert symbol == "CRWD260328C00090000"

    @patch(_TODAY_PATH, return_value=date(2026, 3, 27))  # Friday — uses today directly
    def test_friday_uses_todays_expiry_without_calling_next_friday(self, _):
        client = _make_alpaca_client()
        client.get_options_contracts.return_value = [
            {"symbol": "NVDA260327C00730000", "strike_price": 730.0, "expiration_date": "2026-03-27"},
        ]

        selector = OptionContractSelector(client)
        symbol = selector.select("NVDA", "BULLISH", 820.0)

        assert symbol == "NVDA260327C00730000"
        client.get_options_contracts.assert_called_once_with(
            underlying_symbol="NVDA",
            expiration_date=date(2026, 3, 27),
            option_type="call",
            strike_price_gte="656",
            strike_price_lte="984",
            limit=50,
        )

    @patch(_TODAY_PATH, return_value=date(2026, 3, 30))  # Monday before Good Friday
    @patch(_NEXT_FRIDAY_PATH, return_value=date(2026, 4, 3))  # Good Friday
    @patch(_IS_NYSE_HOLIDAY_PATH, return_value=True)
    def test_good_friday_shifts_expiry_to_thursday(self, _, __, ___):
        client = _make_alpaca_client()
        client.get_options_contracts.return_value = [
            {"symbol": "NVDA260402C00730000", "strike_price": 730.0, "expiration_date": "2026-04-02"},
        ]

        selector = OptionContractSelector(client)
        selector.select("NVDA", "BULLISH", 820.0)

        call_args = client.get_options_contracts.call_args
        assert call_args.kwargs["expiration_date"] == date(2026, 4, 2)  # Thursday

    @patch(_TODAY_PATH, return_value=date(2026, 3, 23))  # Monday
    @patch(_NEXT_FRIDAY_PATH, return_value=date(2026, 3, 27))
    def test_raises_when_no_contracts_found_for_weekly_or_monthly(self, _, __):
        client = _make_alpaca_client()
        client.get_options_contracts.return_value = []

        selector = OptionContractSelector(client)

        with pytest.raises(RuntimeError, match="No call contracts found"):
            selector.select("NVDA", "BULLISH", 820.0)

        assert client.get_options_contracts.call_count == 2

    @patch(_TODAY_PATH, return_value=date(2026, 3, 23))  # Monday
    @patch(_NEXT_FRIDAY_PATH, return_value=date(2026, 3, 27))
    def test_falls_back_to_alpaca_date_range_when_weekly_has_no_contracts(self, _, __):
        client = _make_alpaca_client()
        monthly_contract = {
            "symbol": "ISSC260417C00020000",
            "strike_price": 20.0,
            "expiration_date": "2026-04-17",  # 3rd Friday of April
        }
        client.get_options_contracts.side_effect = [[], [monthly_contract]]

        selector = OptionContractSelector(client)
        symbol = selector.select("ISSC", "BULLISH", 21.5)

        assert symbol == "ISSC260417C00020000"
        assert client.get_options_contracts.call_count == 2
        second_call = client.get_options_contracts.call_args_list[1]
        # second call uses date range, not a fixed expiration_date
        assert second_call.kwargs.get("expiration_date") is None
        assert second_call.kwargs["expiration_date_gte"] == date(2026, 3, 23)
        assert second_call.kwargs["expiration_date_lte"] == date(2026, 4, 30)

    @patch(_TODAY_PATH, return_value=date(2026, 3, 23))  # Monday
    @patch(_NEXT_FRIDAY_PATH, return_value=date(2026, 3, 27))
    def test_fallback_picks_earliest_expiry_when_multiple_available(self, _, __):
        client = _make_alpaca_client()
        client.get_options_contracts.side_effect = [
            [],
            [
                {"symbol": "FN260417C00550000", "strike_price": 550.0, "expiration_date": "2026-04-17"},
                {"symbol": "FN260515C00550000", "strike_price": 550.0, "expiration_date": "2026-05-15"},
            ],
        ]

        selector = OptionContractSelector(client)
        symbol = selector.select("FN", "BULLISH", 552.0)

        assert symbol == "FN260417C00550000"

    @patch(_TODAY_PATH, return_value=date(2026, 3, 23))  # Monday
    @patch(_NEXT_FRIDAY_PATH, return_value=date(2026, 3, 27))
    def test_weekly_contracts_found_does_not_call_monthly_fallback(self, _, __):
        client = _make_alpaca_client()
        client.get_options_contracts.return_value = [
            {"symbol": "FN260327C00550000", "strike_price": 550.0, "expiration_date": "2026-03-27"}
        ]

        selector = OptionContractSelector(client)
        selector.select("FN", "BULLISH", 552.0)

        client.get_options_contracts.assert_called_once()

    @patch(_TODAY_PATH, return_value=date(2026, 3, 23))  # Monday
    @patch(_NEXT_FRIDAY_PATH, return_value=date(2026, 3, 27))
    def test_floating_point_safe_strike_calculation(self, _, __):
        """100 * 1.10 = 110.000...01 must not round up to 115."""
        client = _make_alpaca_client()
        client.get_options_contracts.return_value = [
            {"symbol": "COIN260328P00110000", "strike_price": 110.0, "expiration_date": "2026-03-27"},
        ]

        selector = OptionContractSelector(client)
        symbol = selector.select("COIN", "BEARISH", 100.0)

        call_args = client.get_options_contracts.call_args
        assert call_args.kwargs["strike_price_lte"] == "120"
        assert call_args.kwargs["strike_price_gte"] == "80"
        assert call_args.kwargs["limit"] == 50
        assert symbol == "COIN260328P00110000"

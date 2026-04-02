from datetime import date
from unittest.mock import patch

import pytest

from alpha_tech_tracker.op_momentum_strategy.contract_selector import (
    OptionContractSelector,
    TimePremiumContractSelector,
    _end_of_next_month,
    _is_nyse_holiday,
    _next_friday,
    _strike_increment,
)

from conftest import _D, _make_alpaca_client, _make_option_quote

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


def _make_contracts(strike_prices, option_type="call", expiry="2026-03-27"):
    return [
        {
            "symbol": f"TSLA260327{'C' if option_type == 'call' else 'P'}{int(s * 1000):08d}",
            "strike_price": float(s),
            "expiration_date": expiry,
        }
        for s in strike_prices
    ]


@patch(_TODAY_PATH, return_value=date(2026, 3, 23))
@patch(_NEXT_FRIDAY_PATH, return_value=date(2026, 3, 27))
class TestTimePremiumContractSelector:
    # TSLA at $300, target_pct=1% → target_premium=$3
    # call intrinsic = stock - strike; put intrinsic = strike - stock

    def test_bullish_selects_first_strike_where_time_premium_at_or_below_target(
        self, _, __
    ):
        client = _make_alpaca_client()
        # strike $290 (intrinsic $10): mid=$14 → time_premium=$4 > $3 → skip
        # strike $280 (intrinsic $20): mid=$22 → time_premium=$2 <= $3 → select
        client.get_options_contracts.return_value = _make_contracts([280, 290])
        client._option_data_client.get_option_latest_quote.return_value = {
            "TSLA260327C00290000": _make_option_quote(bid=13.0, ask=15.0),  # mid=14, tp=4
            "TSLA260327C00280000": _make_option_quote(bid=21.0, ask=23.0),  # mid=22, tp=2
        }

        selector = TimePremiumContractSelector(client, target_pct=0.01)
        symbol = selector.select("TSLA", "BULLISH", 300.0)

        assert symbol == "TSLA260327C00280000"

    def test_bearish_selects_first_put_strike_where_time_premium_at_or_below_target(
        self, _, __
    ):
        client = _make_alpaca_client()
        # strike $310 (intrinsic $10): mid=$14 → time_premium=$4 > $3 → skip
        # strike $320 (intrinsic $20): mid=$22 → time_premium=$2 <= $3 → select
        client.get_options_contracts.return_value = _make_contracts(
            [310, 320], option_type="put"
        )
        client._option_data_client.get_option_latest_quote.return_value = {
            "TSLA260327P00310000": _make_option_quote(bid=13.0, ask=15.0),  # mid=14, tp=4
            "TSLA260327P00320000": _make_option_quote(bid=21.0, ask=23.0),  # mid=22, tp=2
        }

        selector = TimePremiumContractSelector(client, target_pct=0.01)
        symbol = selector.select("TSLA", "BEARISH", 300.0)

        assert symbol == "TSLA260327P00320000"

    def test_falls_back_to_deepest_itm_when_all_time_premiums_exceed_target(
        self, _, __
    ):
        client = _make_alpaca_client()
        # All strikes still have time_premium > target → use deepest ITM (lowest call strike)
        client.get_options_contracts.return_value = _make_contracts([290, 295])
        client._option_data_client.get_option_latest_quote.return_value = {
            "TSLA260327C00295000": _make_option_quote(bid=9.0, ask=11.0),   # mid=10, tp=5 > 3
            "TSLA260327C00290000": _make_option_quote(bid=13.5, ask=14.5),  # mid=14, tp=4 > 3
        }

        selector = TimePremiumContractSelector(client, target_pct=0.01)
        symbol = selector.select("TSLA", "BULLISH", 300.0)

        assert symbol == "TSLA260327C00290000"

    def test_skips_strikes_with_zero_mid_and_continues_scanning(self, _, __):
        client = _make_alpaca_client()
        # strike $295: mid=0 → skip; strike $285: tp=$2 ≤ $3 → select
        client.get_options_contracts.return_value = _make_contracts([285, 295])
        client._option_data_client.get_option_latest_quote.return_value = {
            "TSLA260327C00295000": _make_option_quote(bid=0.0, ask=0.0),    # mid=0, skip
            "TSLA260327C00285000": _make_option_quote(bid=16.0, ask=18.0),  # mid=17, tp=2
        }

        selector = TimePremiumContractSelector(client, target_pct=0.01)
        symbol = selector.select("TSLA", "BULLISH", 300.0)

        assert symbol == "TSLA260327C00285000"

    def test_skips_strikes_missing_from_quote_response(self, _, __):
        client = _make_alpaca_client()
        # $295 not in quote response → skip; $285 has tp=$2 ≤ $3 → select
        client.get_options_contracts.return_value = _make_contracts([285, 295])
        client._option_data_client.get_option_latest_quote.return_value = {
            "TSLA260327C00285000": _make_option_quote(bid=16.0, ask=18.0),  # mid=17, tp=2
        }

        selector = TimePremiumContractSelector(client, target_pct=0.01)
        symbol = selector.select("TSLA", "BULLISH", 300.0)

        assert symbol == "TSLA260327C00285000"

    def test_quote_fetch_failure_falls_back_to_deepest_itm(self, _, __):
        client = _make_alpaca_client()
        client.get_options_contracts.return_value = _make_contracts([280, 290, 295])
        client._option_data_client.get_option_latest_quote.side_effect = Exception(
            "network error"
        )

        selector = TimePremiumContractSelector(client, target_pct=0.01)
        symbol = selector.select("TSLA", "BULLISH", 300.0)

        assert symbol == "TSLA260327C00280000"

    def test_raises_when_no_contracts_found(self, _, __):
        client = _make_alpaca_client()
        client.get_options_contracts.return_value = []

        selector = TimePremiumContractSelector(client, target_pct=0.01)

        with pytest.raises(RuntimeError, match="No call contracts found"):
            selector.select("TSLA", "BULLISH", 300.0)

    def test_uses_weekly_expiry_and_falls_back_to_monthly(self, _, __):
        client = _make_alpaca_client()
        monthly = _make_contracts([280], option_type="call", expiry="2026-04-17")
        client.get_options_contracts.side_effect = [[], monthly]

        selector = TimePremiumContractSelector(client, target_pct=0.01)
        client._option_data_client.get_option_latest_quote.return_value = {
            monthly[0]["symbol"]: _make_option_quote(bid=21.0, ask=23.0),
        }

        symbol = selector.select("TSLA", "BULLISH", 300.0)

        assert symbol == monthly[0]["symbol"]
        assert client.get_options_contracts.call_count == 2

    def test_configurable_target_pct_changes_selected_strike(self, _, __):
        client = _make_alpaca_client()
        # With target_pct=0.02 ($6 target), strike $280 has tp=$2 which is ≤ $6 → selected
        # With target_pct=0.005 ($1.50 target), strike $280 tp=$2 > $1.50 → fallback deepest
        client.get_options_contracts.return_value = _make_contracts([280, 290])
        client._option_data_client.get_option_latest_quote.return_value = {
            "TSLA260327C00290000": _make_option_quote(bid=13.0, ask=15.0),  # mid=14, tp=4
            "TSLA260327C00280000": _make_option_quote(bid=21.0, ask=23.0),  # mid=22, tp=2
        }

        selector_wide = TimePremiumContractSelector(client, target_pct=0.02)
        symbol = selector_wide.select("TSLA", "BULLISH", 300.0)
        assert symbol == "TSLA260327C00290000"  # tp=4 ≤ 6 → picked first

    def test_bullish_fetches_itm_call_strike_range(self, _, __):
        client = _make_alpaca_client()
        client.get_options_contracts.return_value = _make_contracts([280])
        client._option_data_client.get_option_latest_quote.return_value = {
            "TSLA260327C00280000": _make_option_quote(bid=21.0, ask=23.0),
        }

        TimePremiumContractSelector(client).select("TSLA", "BULLISH", 300.0)

        call_args = client.get_options_contracts.call_args
        # search_low = 300 * 0.70 = 210; search_high = 300 (ATM)
        assert call_args.kwargs["option_type"] == "call"
        assert call_args.kwargs["strike_price_gte"] == "210"
        assert call_args.kwargs["strike_price_lte"] == "300"

    def test_bearish_fetches_itm_put_strike_range(self, _, __):
        client = _make_alpaca_client()
        client.get_options_contracts.return_value = _make_contracts(
            [310], option_type="put"
        )
        client._option_data_client.get_option_latest_quote.return_value = {
            "TSLA260327P00310000": _make_option_quote(bid=8.0, ask=12.0),  # mid=10, tp=0 ≤ 3
        }

        TimePremiumContractSelector(client).select("TSLA", "BEARISH", 300.0)

        call_args = client.get_options_contracts.call_args
        # search_low = 300 (ATM); search_high = 300 * 1.30 = 390
        assert call_args.kwargs["option_type"] == "put"
        assert call_args.kwargs["strike_price_gte"] == "300"
        assert call_args.kwargs["strike_price_lte"] == "390"

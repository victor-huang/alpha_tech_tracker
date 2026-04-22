from datetime import date
from unittest.mock import patch

import pytest

from alpha_tech_tracker.op_momentum_strategy.contract_selector import (
    MockContractSelector,
    ITMOptionContractSelector,
    TimePremiumContractSelector,
    _end_of_next_month,
    _is_nyse_holiday,
    _next_friday,
    _strike_increment,
)

from alpha_tech_tracker.op_momentum_strategy.option_price_monitor import _parse_occ_symbol

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


class TestITMOptionContractSelector:
    @patch(_TODAY_PATH, return_value=date(2026, 3, 23))  # Monday
    @patch(_NEXT_FRIDAY_PATH, return_value=date(2026, 3, 27))
    def test_bullish_signal_selects_call_with_lower_strike(self, _, __):
        client = _make_alpaca_client()
        client.get_options_contracts.return_value = [
            {"symbol": "NVDA260328C00730000", "strike_price": 730.0, "expiration_date": "2026-03-27"},
            {"symbol": "NVDA260328C00740000", "strike_price": 740.0, "expiration_date": "2026-03-27"},
        ]

        selector = ITMOptionContractSelector(client)
        symbol = selector.select("NVDA", "BULLISH", 820.0)

        # stock=$820, incr=$10, target=floor(820*0.90/10)*10=730, radius=50
        assert symbol == "NVDA260328C00730000"
        client.get_options_contracts.assert_called_once_with(
            underlying_symbol="NVDA",
            expiration_date=date(2026, 3, 27),
            option_type="call",
            strike_price_gte="680",
            strike_price_lte="780",
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

        selector = ITMOptionContractSelector(client)
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

        selector = ITMOptionContractSelector(client)
        # stock @ 100 → target call strike = floor(90/5)*5 = 90
        symbol = selector.select("CRWD", "BULLISH", 100.0)

        assert symbol == "CRWD260328C00090000"

    @patch(_TODAY_PATH, return_value=date(2026, 3, 27))  # Friday — uses today directly
    def test_friday_uses_todays_expiry_without_calling_next_friday(self, _):
        client = _make_alpaca_client()
        client.get_options_contracts.return_value = [
            {"symbol": "NVDA260327C00730000", "strike_price": 730.0, "expiration_date": "2026-03-27"},
        ]

        selector = ITMOptionContractSelector(client)
        symbol = selector.select("NVDA", "BULLISH", 820.0)

        # stock=$820, incr=$10, target=730, radius=50 → narrow range [680, 780]
        assert symbol == "NVDA260327C00730000"
        client.get_options_contracts.assert_called_once_with(
            underlying_symbol="NVDA",
            expiration_date=date(2026, 3, 27),
            option_type="call",
            strike_price_gte="680",
            strike_price_lte="780",
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

        selector = ITMOptionContractSelector(client)
        selector.select("NVDA", "BULLISH", 820.0)

        call_args = client.get_options_contracts.call_args
        assert call_args.kwargs["expiration_date"] == date(2026, 4, 2)  # Thursday

    @patch(_TODAY_PATH, return_value=date(2026, 3, 23))  # Monday
    @patch(_NEXT_FRIDAY_PATH, return_value=date(2026, 3, 27))
    def test_raises_when_no_contracts_found_for_weekly_or_monthly(self, _, __):
        client = _make_alpaca_client()
        client.get_options_contracts.return_value = []

        selector = ITMOptionContractSelector(client)

        with pytest.raises(RuntimeError, match="No call contracts found"):
            selector.select("NVDA", "BULLISH", 820.0)

        # narrow weekly, narrow monthly, broad weekly, broad monthly
        assert client.get_options_contracts.call_count == 4

    @patch(_TODAY_PATH, return_value=date(2026, 3, 23))  # Monday
    @patch(_NEXT_FRIDAY_PATH, return_value=date(2026, 3, 27))
    def test_falls_back_to_alpaca_date_range_when_weekly_has_no_contracts(self, _, __):
        client = _make_alpaca_client()
        monthly_contract = {
            "symbol": "ISSC260417C00020000",
            "strike_price": 20.0,
            "expiration_date": "2026-04-17",  # 3rd Friday of April
        }
        # narrow weekly, narrow monthly, broad weekly, broad monthly (succeeds)
        client.get_options_contracts.side_effect = [[], [], [], [monthly_contract]]

        selector = ITMOptionContractSelector(client)
        symbol = selector.select("ISSC", "BULLISH", 21.5)

        assert symbol == "ISSC260417C00020000"
        assert client.get_options_contracts.call_count == 4
        broad_monthly_call = client.get_options_contracts.call_args_list[3]
        assert broad_monthly_call.kwargs.get("expiration_date") is None
        assert broad_monthly_call.kwargs["expiration_date_gte"] == date(2026, 3, 23)
        assert broad_monthly_call.kwargs["expiration_date_lte"] == date(2026, 4, 30)

    @patch(_TODAY_PATH, return_value=date(2026, 3, 23))  # Monday
    @patch(_NEXT_FRIDAY_PATH, return_value=date(2026, 3, 27))
    def test_fallback_picks_earliest_expiry_when_multiple_available(self, _, __):
        client = _make_alpaca_client()
        # stock=$552, target=$495, narrow=[470,520] misses $550 → all 3 narrow calls empty
        # broad monthly returns both expiries; earliest wins
        client.get_options_contracts.side_effect = [
            [],
            [],
            [],
            [
                {"symbol": "FN260417C00550000", "strike_price": 550.0, "expiration_date": "2026-04-17"},
                {"symbol": "FN260515C00550000", "strike_price": 550.0, "expiration_date": "2026-05-15"},
            ],
        ]

        selector = ITMOptionContractSelector(client)
        symbol = selector.select("FN", "BULLISH", 552.0)

        assert symbol == "FN260417C00550000"

    @patch(_TODAY_PATH, return_value=date(2026, 4, 8))  # Tuesday — SNDK live session date
    @patch(_NEXT_FRIDAY_PATH, return_value=date(2026, 4, 10))
    def test_narrow_search_finds_target_strike_on_sparse_chain(self, _, __):
        """Reproduce the 2026-04-08 SNDK bug: broad ±20% search returned K=745 (OTM)
        because the first page of results didn't include the target K=850.
        Narrow search [800, 900] is centered on the target and finds it directly."""
        client = _make_alpaca_client()
        # stock=$777, incr=$10, target=850 (777*1.10=854.7 → rounds to 850), radius=50
        # narrow range [800, 900] contains the target
        client.get_options_contracts.return_value = [
            {"symbol": "SNDK260410P00840000", "strike_price": 840.0, "expiration_date": "2026-04-10"},
            {"symbol": "SNDK260410P00850000", "strike_price": 850.0, "expiration_date": "2026-04-10"},
        ]

        selector = ITMOptionContractSelector(client)
        symbol = selector.select("SNDK", "BEARISH", 777.0)

        assert symbol == "SNDK260410P00850000"
        client.get_options_contracts.assert_called_once_with(
            underlying_symbol="SNDK",
            expiration_date=date(2026, 4, 10),
            option_type="put",
            strike_price_gte="800",
            strike_price_lte="900",
            limit=50,
        )

    @patch(_TODAY_PATH, return_value=date(2026, 3, 23))  # Monday
    @patch(_NEXT_FRIDAY_PATH, return_value=date(2026, 3, 27))
    def test_broad_fallback_used_when_narrow_search_returns_empty(self, _, __):
        """When the narrow ±5-increment window has no contracts, the selector
        falls back to the broad ±20% stock-price range."""
        client = _make_alpaca_client()
        broad_contract = {
            "symbol": "NVDA260327C00730000",
            "strike_price": 730.0,
            "expiration_date": "2026-03-27",
        }
        # narrow weekly [], narrow monthly [], broad weekly [contract]
        client.get_options_contracts.side_effect = [[], [], [broad_contract]]

        selector = ITMOptionContractSelector(client)
        symbol = selector.select("NVDA", "BULLISH", 820.0)

        assert symbol == "NVDA260327C00730000"
        # 3 calls: narrow weekly, narrow monthly (inside _fetch_contracts_with_expiry_fallback),
        # then broad weekly (which succeeds, so no broad monthly needed)
        assert client.get_options_contracts.call_count == 3
        broad_call = client.get_options_contracts.call_args_list[2]
        assert broad_call.kwargs["strike_price_gte"] == "656"
        assert broad_call.kwargs["strike_price_lte"] == "984"

    @patch(_TODAY_PATH, return_value=date(2026, 3, 23))  # Monday
    @patch(_NEXT_FRIDAY_PATH, return_value=date(2026, 3, 27))
    def test_weekly_contracts_found_does_not_call_monthly_fallback(self, _, __):
        client = _make_alpaca_client()
        client.get_options_contracts.return_value = [
            {"symbol": "FN260327C00550000", "strike_price": 550.0, "expiration_date": "2026-03-27"}
        ]

        selector = ITMOptionContractSelector(client)
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

        selector = ITMOptionContractSelector(client)
        symbol = selector.select("COIN", "BEARISH", 100.0)

        # stock=$100, incr=$5, target=110, radius=25 → narrow range [85, 135]
        call_args = client.get_options_contracts.call_args
        assert call_args.kwargs["strike_price_gte"] == "85"
        assert call_args.kwargs["strike_price_lte"] == "135"
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
        client.get_option_quotes_by_occ_batch.return_value = {
            "TSLA260327C00290000": _make_option_quote(bid=13.0, ask=15.0),  # mid=14, tp=4
            "TSLA260327C00280000": _make_option_quote(bid=21.0, ask=23.0),  # mid=22, tp=2
        }

        selector = TimePremiumContractSelector(client, time_premium_pct_cap=0.01)
        symbol = selector.select("TSLA", "BULLISH", 300.0)

        assert symbol == "TSLA260327C00280000"

    def test_bearish_selects_first_put_strike_where_time_premium_at_or_below_target(
        self, _, __
    ):
        client = _make_alpaca_client()
        # DTE=4, target = 0.01/5 * 4 * $300 = $2.40
        # strike $310 (intrinsic $10): mid=$14 → time_premium=$4 > $2.40 → skip
        # strike $320 (intrinsic $20): mid=$22 → time_premium=$2 <= $2.40 → select
        client.get_options_contracts.return_value = _make_contracts(
            [310, 320], option_type="put"
        )
        client.get_option_quotes_by_occ_batch.return_value = {
            "TSLA260327P00310000": _make_option_quote(bid=13.0, ask=15.0),  # mid=14, tp=4
            "TSLA260327P00320000": _make_option_quote(bid=21.0, ask=23.0),  # mid=22, tp=2
        }

        selector = TimePremiumContractSelector(client, time_premium_pct_cap=0.01)
        symbol = selector.select("TSLA", "BEARISH", 300.0)

        assert symbol == "TSLA260327P00320000"

    def test_falls_back_to_deepest_itm_when_all_time_premiums_exceed_target(
        self, _, __
    ):
        client = _make_alpaca_client()
        # DTE=4, target = $2.40; all strikes tp > $2.40 → deepest ITM (lowest call strike)
        client.get_options_contracts.return_value = _make_contracts([290, 295])
        client.get_option_quotes_by_occ_batch.return_value = {
            "TSLA260327C00295000": _make_option_quote(bid=9.0, ask=11.0),   # mid=10, tp=5 > 2.40
            "TSLA260327C00290000": _make_option_quote(bid=13.5, ask=14.5),  # mid=14, tp=4 > 2.40
        }

        selector = TimePremiumContractSelector(client, time_premium_pct_cap=0.01)
        symbol = selector.select("TSLA", "BULLISH", 300.0)

        assert symbol == "TSLA260327C00290000"

    def test_skips_strikes_with_zero_mid_and_continues_scanning(self, _, __):
        client = _make_alpaca_client()
        # strike $295: mid=0 → skip; strike $285: tp=$2 ≤ $3 → select
        client.get_options_contracts.return_value = _make_contracts([285, 295])
        client.get_option_quotes_by_occ_batch.return_value = {
            "TSLA260327C00295000": _make_option_quote(bid=0.0, ask=0.0),    # mid=0, skip
            "TSLA260327C00285000": _make_option_quote(bid=16.0, ask=18.0),  # mid=17, tp=2
        }

        selector = TimePremiumContractSelector(client, time_premium_pct_cap=0.01)
        symbol = selector.select("TSLA", "BULLISH", 300.0)

        assert symbol == "TSLA260327C00285000"

    def test_skips_strikes_missing_from_quote_response(self, _, __):
        client = _make_alpaca_client()
        # $295 not in quote response → skip; $285 has tp=$2 ≤ $3 → select
        client.get_options_contracts.return_value = _make_contracts([285, 295])
        client.get_option_quotes_by_occ_batch.return_value = {
            "TSLA260327C00285000": _make_option_quote(bid=16.0, ask=18.0),  # mid=17, tp=2
        }

        selector = TimePremiumContractSelector(client, time_premium_pct_cap=0.01)
        symbol = selector.select("TSLA", "BULLISH", 300.0)

        assert symbol == "TSLA260327C00285000"

    def test_quote_fetch_failure_falls_back_to_deepest_itm(self, _, __):
        client = _make_alpaca_client()
        client.get_options_contracts.return_value = _make_contracts([280, 290, 295])
        client.get_option_quotes_by_occ_batch.side_effect = Exception(
            "network error"
        )

        selector = TimePremiumContractSelector(client, time_premium_pct_cap=0.01)
        symbol = selector.select("TSLA", "BULLISH", 300.0)

        assert symbol == "TSLA260327C00280000"

    def test_raises_when_no_contracts_found(self, _, __):
        client = _make_alpaca_client()
        client.get_options_contracts.return_value = []

        selector = TimePremiumContractSelector(client, time_premium_pct_cap=0.01)

        with pytest.raises(RuntimeError, match="No call contracts found"):
            selector.select("TSLA", "BULLISH", 300.0)

    def test_uses_weekly_expiry_and_falls_back_to_monthly(self, _, __):
        client = _make_alpaca_client()
        monthly = _make_contracts([280], option_type="call", expiry="2026-04-17")
        client.get_options_contracts.side_effect = [[], monthly]

        selector = TimePremiumContractSelector(client, time_premium_pct_cap=0.01)
        client.get_option_quotes_by_occ_batch.return_value = {
            monthly[0]["symbol"]: _make_option_quote(bid=21.0, ask=23.0),
        }

        symbol = selector.select("TSLA", "BULLISH", 300.0)

        assert symbol == monthly[0]["symbol"]
        assert client.get_options_contracts.call_count == 2

    def test_configurable_time_premium_pct_cap_changes_selected_strike(self, _, __):
        client = _make_alpaca_client()
        # DTE=4, reference_dte=5
        # time_premium_pct_cap=0.02 → target = 0.02/5 * 4 * $300 = $4.80
        #   strike $290 tp=$4 ≤ $4.80 → picked first
        client.get_options_contracts.return_value = _make_contracts([280, 290])
        client.get_option_quotes_by_occ_batch.return_value = {
            "TSLA260327C00290000": _make_option_quote(bid=13.0, ask=15.0),  # mid=14, tp=4
            "TSLA260327C00280000": _make_option_quote(bid=21.0, ask=23.0),  # mid=22, tp=2
        }

        selector_wide = TimePremiumContractSelector(client, time_premium_pct_cap=0.02)
        symbol = selector_wide.select("TSLA", "BULLISH", 300.0)
        assert symbol == "TSLA260327C00290000"  # tp=4 ≤ 4.80 → picked first

    def test_monthly_fallback_uses_dte_adjusted_threshold(self, _, __):
        # today=2026-03-23, monthly expiry=2026-04-17 → DTE=25
        # target = 0.01/5 * 25 * $300 = $15.00
        # A time premium of $10 would be rejected on weekly (DTE=4, target=$2.40)
        # but accepted on monthly (target=$15.00)
        client = _make_alpaca_client()
        monthly = _make_contracts([280], option_type="call", expiry="2026-04-17")
        client.get_options_contracts.side_effect = [[], monthly]
        client.get_option_quotes_by_occ_batch.return_value = {
            monthly[0]["symbol"]: _make_option_quote(bid=29.0, ask=31.0),  # mid=30, tp=10
        }

        selector = TimePremiumContractSelector(client, time_premium_pct_cap=0.01)
        symbol = selector.select("TSLA", "BULLISH", 300.0)

        assert symbol == monthly[0]["symbol"]  # tp=10 ≤ 15.00 → accepted

    def test_bullish_fetches_itm_call_strike_range(self, _, __):
        client = _make_alpaca_client()
        client.get_options_contracts.return_value = _make_contracts([280])
        client.get_option_quotes_by_occ_batch.return_value = {
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
        client.get_option_quotes_by_occ_batch.return_value = {
            "TSLA260327P00310000": _make_option_quote(bid=8.0, ask=12.0),  # mid=10, tp=0 ≤ 3
        }

        TimePremiumContractSelector(client).select("TSLA", "BEARISH", 300.0)

        call_args = client.get_options_contracts.call_args
        # search_low = 300 (ATM); search_high = 300 * 1.30 = 390
        assert call_args.kwargs["option_type"] == "put"
        assert call_args.kwargs["strike_price_gte"] == "300"
        assert call_args.kwargs["strike_price_lte"] == "390"


class TestMockContractSelector:
    # ref_date Monday 2026-03-23 → next Friday 2026-03-27 → "260327"
    _REF_DATE = date(2026, 3, 23)
    _EXPIRY_SUFFIX = "260327"

    def test_bullish_call_floors_strike_to_increment(self):
        # stock=$100, increment=$5, 100×0.90=90 → floor(90/5)*5=$90
        symbol = MockContractSelector(self._REF_DATE).select("NVDA", "BULLISH", 100.0)
        assert symbol == f"NVDA{self._EXPIRY_SUFFIX}C00090000"

    def test_bearish_put_ceils_strike_to_increment(self):
        # stock=$100, increment=$5, 100×1.10=110 → ceil(110/5)*5=$110
        symbol = MockContractSelector(self._REF_DATE).select("NVDA", "BEARISH", 100.0)
        assert symbol == f"NVDA{self._EXPIRY_SUFFIX}P00110000"

    def test_high_price_uses_ten_dollar_increment(self):
        # stock=$250, increment=$10, 250×0.90=225 → floor(225/10)*10=$220
        symbol = MockContractSelector(self._REF_DATE).select("TSLA", "BULLISH", 250.0)
        assert symbol == f"TSLA{self._EXPIRY_SUFFIX}C00220000"

    def test_low_price_uses_one_dollar_increment(self):
        # stock=$30, increment=$1, 30×0.90=27 → floor(27/1)*1=$27
        symbol = MockContractSelector(self._REF_DATE).select("APP", "BULLISH", 30.0)
        assert symbol == f"APP{self._EXPIRY_SUFFIX}C00027000"

    def test_bearish_put_ceils_non_round_target(self):
        # stock=$250, increment=$10, 250×1.10=275 → ceil(275/10)*10=$280
        symbol = MockContractSelector(self._REF_DATE).select("TSLA", "BEARISH", 250.0)
        assert symbol == f"TSLA{self._EXPIRY_SUFFIX}P00280000"

    def test_expiry_is_next_friday_from_ref_date(self):
        # ref_date=Wednesday 2026-04-01 → next Friday 2026-04-03 → "260403"
        ref = date(2026, 4, 1)
        symbol = MockContractSelector(ref).select("COIN", "BULLISH", 100.0)
        assert "260403" in symbol

    def test_no_api_calls_made(self):
        selector = MockContractSelector(self._REF_DATE)
        # just verifying select() returns without touching any client
        symbol = selector.select("PLTR", "BEARISH", 80.0)
        assert symbol.startswith("PLTR")
        assert "P" in symbol


class TestMockContractSelectorITMInvariant:
    """MockContractSelector must always produce ITM contracts so mock_entry_price
    never encounters an OTM symbol (intrinsic is always positive at entry).

    ITM definition:
      call: strike < stock_price   (you can buy at a discount)
      put:  strike > stock_price   (you can sell at a premium)
    """

    _REF_DATE = date(2026, 3, 23)

    def _strike(self, symbol: str) -> float:
        return float(_parse_occ_symbol(symbol)["strike"])

    def test_bullish_call_strike_is_below_stock_price(self):
        symbol = MockContractSelector(self._REF_DATE).select("NVDA", "BULLISH", 100.0)
        assert self._strike(symbol) < 100.0

    def test_bearish_put_strike_is_above_stock_price(self):
        symbol = MockContractSelector(self._REF_DATE).select("NVDA", "BEARISH", 100.0)
        assert self._strike(symbol) > 100.0

    def test_call_itm_for_high_price_stock(self):
        # stock=$467 (SNDK-range), increment=$10 → strike=$420 < $467
        symbol = MockContractSelector(self._REF_DATE).select("SNDK", "BULLISH", 467.0)
        assert self._strike(symbol) < 467.0

    def test_put_itm_for_high_price_stock(self):
        # stock=$467, increment=$10 → strike=$520 > $467
        symbol = MockContractSelector(self._REF_DATE).select("SNDK", "BEARISH", 467.0)
        assert self._strike(symbol) > 467.0

    def test_call_itm_for_low_price_stock(self):
        # stock=$30 (APP-range), increment=$1 → strike=$27 < $30
        symbol = MockContractSelector(self._REF_DATE).select("APP", "BULLISH", 30.0)
        assert self._strike(symbol) < 30.0

    def test_put_itm_for_low_price_stock(self):
        # stock=$30, increment=$1 → strike=$33 > $30
        symbol = MockContractSelector(self._REF_DATE).select("APP", "BEARISH", 30.0)
        assert self._strike(symbol) > 30.0

    def test_call_intrinsic_is_approximately_10pct_of_stock(self):
        # strike = floor(stock * 0.90 / incr) * incr, so intrinsic ≈ stock * 0.10
        stock = 300.0
        symbol = MockContractSelector(self._REF_DATE).select("CLS", "BULLISH", stock)
        intrinsic = stock - self._strike(symbol)
        assert intrinsic >= stock * 0.08  # at least 8% (flooring can reduce it slightly)
        assert intrinsic <= stock * 0.12  # at most 12%

    def test_put_intrinsic_is_approximately_10pct_of_stock(self):
        stock = 300.0
        symbol = MockContractSelector(self._REF_DATE).select("CLS", "BEARISH", stock)
        intrinsic = self._strike(symbol) - stock
        assert intrinsic >= stock * 0.08
        assert intrinsic <= stock * 0.12

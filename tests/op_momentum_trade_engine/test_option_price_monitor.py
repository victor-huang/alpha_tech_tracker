from collections import deque
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import Mock, patch

import pytz

from alpha_tech_tracker.op_momentum_strategy.option_price_monitor import (
    ContractSpec,
    OptionPriceMonitor,
    TradeEngineStrikeSelector,
    _is_third_friday,
    _parse_occ_symbol,
    _quantize_option_price,
)

from conftest import _D, _make_alpaca_client, _make_option_quote

ET = pytz.timezone("America/New_York")

# Symbol with far-future expiry so days_to_expiry is always > 0 in tests
_CALL_SYM = "TSLA990101C00280000"  # strike $280, call, expires 2099-01-01
_PUT_SYM = "TSLA990101P00320000"   # strike $320, put,  expires 2099-01-01

# Symbols with real near-term dates for expiry_type tests
_WEEKLY_CALL = "TSLA260410C00280000"   # 2026-04-10 = 2nd Friday of April (weekly)
_MONTHLY_CALL = "TSLA260417C00280000"  # 2026-04-17 = 3rd Friday of April (monthly)

_DATE_PATH = "alpha_tech_tracker.op_momentum_strategy.option_price_monitor.date"


def _make_monitor(client=None, tickers=None, output_dir="/tmp/test_opm"):
    client = client or _make_alpaca_client()
    selector = Mock()
    selector.select_contracts.return_value = []
    return OptionPriceMonitor(
        client=client,
        tickers=tickers or ["TSLA"],
        output_dir=output_dir,
        contract_selector=selector,
    )


class TestParseOccSymbol:
    def test_parses_call_symbol_components(self):
        with patch(_DATE_PATH) as mock_date:
            mock_date.today.return_value = date(2026, 4, 9)
            mock_date.side_effect = date
            result = _parse_occ_symbol("TSLA260410C00280000")

        assert result["ticker"] == "TSLA"
        assert result["option_type"] == "call"
        assert result["strike"] == Decimal("280")
        assert result["expiry"] == date(2026, 4, 10)
        assert result["expiry_str"] == "2026-04-10"
        assert result["days_to_expiry"] == 1

    def test_parses_put_symbol_components(self):
        with patch(_DATE_PATH) as mock_date:
            mock_date.today.return_value = date(2026, 4, 9)
            mock_date.side_effect = date
            result = _parse_occ_symbol("NVDA260410P00730000")

        assert result["ticker"] == "NVDA"
        assert result["option_type"] == "put"
        assert result["strike"] == Decimal("730")

    def test_strike_divided_by_1000(self):
        with patch(_DATE_PATH) as mock_date:
            mock_date.today.return_value = date(2026, 1, 1)
            mock_date.side_effect = date
            result = _parse_occ_symbol("TSLA260410C00282500")

        assert result["strike"] == Decimal("282.5")

    def test_days_to_expiry_clamped_to_zero_for_expired_symbol(self):
        with patch(_DATE_PATH) as mock_date:
            mock_date.today.return_value = date(2026, 4, 20)
            mock_date.side_effect = date
            result = _parse_occ_symbol("TSLA260410C00280000")

        assert result["days_to_expiry"] == 0

    def test_returns_empty_dict_for_invalid_symbol(self):
        assert _parse_occ_symbol("INVALID") == {}
        assert _parse_occ_symbol("") == {}
        assert _parse_occ_symbol("tsla260410c00280000") == {}  # lowercase


class TestIsThirdFriday:
    def test_third_friday_of_april_2026(self):
        assert _is_third_friday(date(2026, 4, 17)) is True

    def test_second_friday_is_not_third(self):
        assert _is_third_friday(date(2026, 4, 10)) is False

    def test_fourth_friday_is_not_third(self):
        assert _is_third_friday(date(2026, 4, 24)) is False

    def test_non_friday_returns_false(self):
        assert _is_third_friday(date(2026, 4, 16)) is False  # Thursday

    def test_first_friday_of_month_returns_false(self):
        assert _is_third_friday(date(2026, 4, 3)) is False


class TestFetchStats:
    def _run(self, client, spec, stock_price, today=date(2026, 4, 9)):
        monitor = _make_monitor(client=client)
        with patch(_DATE_PATH) as mock_date:
            mock_date.today.return_value = today
            mock_date.side_effect = date
            return monitor._fetch_stats("TSLA", spec, _D(str(stock_price)))

    def test_call_intrinsic_is_stock_minus_strike(self):
        client = _make_alpaca_client()
        client.get_option_quote_by_occ.return_value = _make_option_quote(bid=19.0, ask=21.0)
        spec = ContractSpec(symbol=_WEEKLY_CALL, option_type="call")

        row = self._run(client, spec, stock_price=300.0)

        # strike=$280, stock=$300 → intrinsic=$20
        assert row["intrinsic_value"] == 20.0
        assert row["mid"] == 20.0
        assert row["mid_time_value"] == 0.0

    def test_put_intrinsic_is_strike_minus_stock(self):
        client = _make_alpaca_client()
        client.get_option_quote_by_occ.return_value = _make_option_quote(bid=18.0, ask=22.0)
        spec = ContractSpec(symbol=_MONTHLY_CALL, option_type="put")

        row = self._run(client, spec, stock_price=260.0)

        # symbol is a "put" spec even though OCC says C — intrinsic driven by spec.option_type
        # strike=$280, stock=$260 → intrinsic=$20
        assert row["intrinsic_value"] == 20.0

    def test_spread_pct_computed_correctly(self):
        client = _make_alpaca_client()
        client.get_option_quote_by_occ.return_value = _make_option_quote(bid=18.0, ask=22.0)
        spec = ContractSpec(symbol=_WEEKLY_CALL, option_type="call")

        row = self._run(client, spec, stock_price=300.0)

        # spread=4, mid=20 → spread_pct=20.0%
        assert row["spread_pct"] == 20.0

    def test_spread_pct_is_zero_when_mid_is_zero(self):
        client = _make_alpaca_client()
        client.get_option_quote_by_occ.return_value = _make_option_quote(bid=0.0, ask=0.0)
        spec = ContractSpec(symbol=_WEEKLY_CALL, option_type="call")

        row = self._run(client, spec, stock_price=300.0)

        assert row["spread_pct"] == 0.0

    def test_daily_theta_is_zero_when_already_expired(self):
        client = _make_alpaca_client()
        client.get_option_quote_by_occ.return_value = _make_option_quote(bid=19.0, ask=21.0)
        spec = ContractSpec(symbol=_WEEKLY_CALL, option_type="call")

        # today is after expiry
        row = self._run(client, spec, stock_price=300.0, today=date(2026, 4, 20))

        assert row["daily_theta_approx"] == 0.0

    def test_expiry_type_weekly_for_non_third_friday(self):
        client = _make_alpaca_client()
        client.get_option_quote_by_occ.return_value = _make_option_quote(bid=19.0, ask=21.0)
        spec = ContractSpec(symbol=_WEEKLY_CALL, option_type="call")

        row = self._run(client, spec, stock_price=300.0)

        assert row["expiry_type"] == "weekly"

    def test_expiry_type_monthly_for_third_friday(self):
        client = _make_alpaca_client()
        client.get_option_quote_by_occ.return_value = _make_option_quote(bid=19.0, ask=21.0)
        spec = ContractSpec(symbol=_MONTHLY_CALL, option_type="call")

        row = self._run(client, spec, stock_price=300.0)

        assert row["expiry_type"] == "monthly"

    def test_returns_none_when_quote_fetch_fails(self):
        client = _make_alpaca_client()
        client.get_option_quote_by_occ.side_effect = Exception(
            "network error"
        )
        spec = ContractSpec(symbol=_WEEKLY_CALL, option_type="call")

        row = self._run(client, spec, stock_price=300.0)

        assert row is None

    def test_returns_none_for_unparseable_symbol(self):
        client = _make_alpaca_client()
        client.get_option_quote_by_occ.return_value = _make_option_quote(bid=5.0, ask=6.0)
        spec = ContractSpec(symbol="BADSYM", option_type="call")

        monitor = _make_monitor(client=client)
        row = monitor._fetch_stats("TSLA", spec, _D("300"))

        assert row is None

    def test_row_contains_all_required_csv_fields(self):
        client = _make_alpaca_client()
        client.get_option_quote_by_occ.return_value = _make_option_quote(bid=19.0, ask=21.0)
        spec = ContractSpec(symbol=_WEEKLY_CALL, option_type="call")

        row = self._run(client, spec, stock_price=300.0)

        expected_fields = OptionPriceMonitor._CSV_FIELDS
        for field in expected_fields:
            assert field in row, f"Missing field: {field}"


class TestMedianTimeValue:
    def test_returns_none_when_cache_is_empty(self):
        monitor = _make_monitor()
        assert monitor._median_time_value("SYM") is None

    def test_returns_median_for_odd_number_of_snapshots(self):
        monitor = _make_monitor()
        monitor._cache["SYM"] = deque(
            [{"mid_time_value": 2.0}, {"mid_time_value": 4.0}, {"mid_time_value": 3.0}]
        )
        assert monitor._median_time_value("SYM") == _D("3.0")

    def test_returns_average_of_middle_two_for_even_count(self):
        monitor = _make_monitor()
        monitor._cache["SYM"] = deque(
            [{"mid_time_value": 1.0}, {"mid_time_value": 3.0},
             {"mid_time_value": 5.0}, {"mid_time_value": 7.0}]
        )
        assert monitor._median_time_value("SYM") == _D("4.0")

    def test_returns_single_value_when_only_one_snapshot(self):
        monitor = _make_monitor()
        monitor._cache["SYM"] = deque([{"mid_time_value": 5.5}])
        assert monitor._median_time_value("SYM") == _D("5.5")


class TestGetFairPrice:
    _SYM = _WEEKLY_CALL  # strike=$280, call

    def _monitor_with_quote(self, bid, ask, cache_tv=None):
        client = _make_alpaca_client()
        client.get_option_quote_by_occ.return_value = _make_option_quote(bid=bid, ask=ask)
        monitor = _make_monitor(client=client)
        if cache_tv is not None:
            monitor._cache[self._SYM] = deque(
                [{"mid_time_value": float(cache_tv)}]
            )
        return monitor

    def test_returns_mid_when_spread_is_liquid_and_bid_above_intrinsic(self):
        # strike=$280, stock=$300 → intrinsic=$20; bid=$21 > $20, spread=(22-21)/21.5*100=4.6% ≤ 15%
        monitor = self._monitor_with_quote(bid=21.0, ask=22.0)
        fair = monitor.get_fair_price("TSLA", self._SYM, "call", _D("300"))
        assert fair == _D("21.50")

    def test_uses_intrinsic_plus_cached_median_when_bid_is_stale(self):
        # bid=$18 < intrinsic=$20 (stale) → use intrinsic + cached median_tv=$3 = $23, clamped to ask=$28
        monitor = self._monitor_with_quote(bid=18.0, ask=28.0, cache_tv=_D("3"))
        fair = monitor.get_fair_price("TSLA", self._SYM, "call", _D("300"))
        # intrinsic=$20, median_tv=$3 → fair=$23, within [18, 28]
        assert fair == _D("23.00")

    def test_uses_intrinsic_plus_cached_median_when_spread_is_wide(self):
        # spread=(30-21)/25.5*100=35% > 15% → use cache even if bid > intrinsic
        monitor = self._monitor_with_quote(bid=21.0, ask=30.0, cache_tv=_D("2"))
        fair = monitor.get_fair_price("TSLA", self._SYM, "call", _D("300"))
        # intrinsic=$20, median_tv=$2 → fair=$22
        assert fair == _D("22.00")

    def test_falls_back_to_20_pct_of_spread_when_no_cache(self):
        # No cache: wide spread bid=$21 ask=$30, spread=$9
        # fallback median_tv = 9 * 0.20 = $1.80
        # intrinsic=$20 → fair = 20 + 1.80 = $21.80, within [21, 30]
        monitor = self._monitor_with_quote(bid=21.0, ask=30.0)
        fair = monitor.get_fair_price("TSLA", self._SYM, "call", _D("300"))
        assert fair == _D("21.80")

    def test_clamps_fair_price_to_ask_when_above(self):
        # Wide spread → cache path; intrinsic=$20 + median_tv=$35 = $55 > ask=$50 → clamp to $50
        monitor = self._monitor_with_quote(bid=25.0, ask=50.0, cache_tv=_D("35"))
        fair = monitor.get_fair_price("TSLA", self._SYM, "call", _D("300"))
        assert fair == _D("50.00")

    def test_fair_price_stays_below_bid_when_cache_tv_is_small(self):
        # Wide spread → cache path; intrinsic=$20 + median_tv=$1 = $21
        # bid clamping is intentionally skipped (see get_fair_price comment)
        monitor = self._monitor_with_quote(bid=22.0, ask=35.0, cache_tv=_D("1"))
        fair = monitor.get_fair_price("TSLA", self._SYM, "call", _D("300"))
        assert fair == _D("21.00")

    def test_returns_zero_when_quote_fetch_fails(self):
        client = _make_alpaca_client()
        client.get_option_quote_by_occ.side_effect = Exception(
            "timeout"
        )
        monitor = _make_monitor(client=client)
        fair = monitor.get_fair_price("TSLA", self._SYM, "call", _D("300"))
        assert fair == _D("0")

    def test_returns_mid_when_occ_symbol_cannot_be_parsed(self):
        client = _make_alpaca_client()
        client.get_option_quote_by_occ.return_value = _make_option_quote(bid=5.0, ask=7.0)
        monitor = _make_monitor(client=client)
        fair = monitor.get_fair_price("TSLA", "BADSYM", "call", _D("300"))
        assert fair == _D("6.00")

    def test_returns_zero_mid_when_bid_and_ask_both_zero(self):
        monitor = self._monitor_with_quote(bid=0.0, ask=0.0)
        fair = monitor.get_fair_price("TSLA", self._SYM, "call", _D("300"))
        assert fair == _D("0")


class TestQuantizeOptionPrice:
    """
    All pool tickers are on the CBOE Penny Pilot Program:
      < $3.00  → $0.01 tick
      ≥ $3.00  → $0.05 tick
    """

    def test_price_above_3_rounds_to_5_cent_tick(self):
        assert _quantize_option_price(_D("21.73")) == _D("21.75")

    def test_price_above_3_rounds_down_on_less_than_half(self):
        assert _quantize_option_price(_D("21.72")) == _D("21.70")

    def test_price_above_3_rounds_up_on_half(self):
        assert _quantize_option_price(_D("21.725")) == _D("21.75")

    def test_price_below_3_rounds_to_1_cent_tick(self):
        assert _quantize_option_price(_D("2.634")) == _D("2.63")

    def test_price_below_3_rounds_up(self):
        assert _quantize_option_price(_D("2.615")) == _D("2.62")

    def test_price_exactly_3_uses_5_cent_tick(self):
        assert _quantize_option_price(_D("3.00")) == _D("3.00")

    def test_price_already_on_tick_is_unchanged(self):
        assert _quantize_option_price(_D("15.50")) == _D("15.50")


class TestGetFairPriceQuantization:
    """Verify get_fair_price returns a properly tick-quantized price."""

    _SYM = _WEEKLY_CALL  # strike=$280, call

    def _monitor_with_quote(self, bid, ask, cache_tv=None):
        client = _make_alpaca_client()
        client.get_option_quote_by_occ.return_value = _make_option_quote(bid=bid, ask=ask)
        monitor = _make_monitor(client=client)
        if cache_tv is not None:
            monitor._cache[self._SYM] = deque(
                [{"mid_time_value": float(cache_tv)}]
            )
        return monitor

    def test_liquid_mid_is_rounded_to_5_cent_tick(self):
        # bid=$21.05 ask=$21.75 → mid=$21.40, spread=3.3% liquid
        # intrinsic=stock$300 - strike$280=$20; bid > intrinsic → use mid
        # mid $21.40 → penny pilot ≥$3 → nearest $0.05 = $21.40
        monitor = self._monitor_with_quote(bid=21.05, ask=21.75)
        fair = monitor.get_fair_price("TSLA", self._SYM, "call", _D("300"))
        assert fair == _D("21.40")

    def test_cache_path_result_rounded_to_5_cent_tick(self):
        # Wide spread; intrinsic=$20 + cached_tv=$1.83 = $21.83
        # penny pilot ≥$3 → nearest $0.05 = $21.85
        monitor = self._monitor_with_quote(bid=21.0, ask=35.0, cache_tv=_D("1.83"))
        fair = monitor.get_fair_price("TSLA", self._SYM, "call", _D("300"))
        assert fair == _D("21.85")

    def test_price_below_3_rounded_to_1_cent_tick(self):
        # OTM call: stock=$278, strike=$280 → intrinsic=$0; bid=$0.80, ask=$0.94
        # mid=$0.87, spread=16.1% wide → use 20% of spread fallback
        # median_tv = (0.94-0.80)*0.20 = $0.028 → fair = 0 + 0.028 = $0.028
        # bid clamping is intentionally skipped; $0.028 < $3 → penny pilot tick $0.01 → $0.03
        monitor = self._monitor_with_quote(bid=0.80, ask=0.94)
        fair = monitor.get_fair_price("TSLA", self._SYM, "call", _D("278"))
        assert fair == _D("0.03")


class TestIsMarketHours:
    def _dt(self, hour, minute):
        return ET.localize(datetime(2026, 4, 9, hour, minute))

    def test_returns_true_at_market_open(self):
        monitor = _make_monitor()
        assert monitor._is_market_hours(self._dt(9, 30)) is True

    def test_returns_true_mid_day(self):
        monitor = _make_monitor()
        assert monitor._is_market_hours(self._dt(12, 0)) is True

    def test_returns_false_before_open(self):
        monitor = _make_monitor()
        assert monitor._is_market_hours(self._dt(9, 29)) is False

    def test_returns_false_at_close(self):
        monitor = _make_monitor()
        assert monitor._is_market_hours(self._dt(16, 0)) is False

    def test_returns_false_after_close(self):
        monitor = _make_monitor()
        assert monitor._is_market_hours(self._dt(16, 30)) is False


class TestSnapshotTicker:
    def _stock_quote(self, bid, ask):
        return {
            "QuoteResponse": {
                "QuoteData": [{"All": {"bid": bid, "ask": ask, "bid_size": 1, "ask_size": 1, "last": None}}]
            }
        }

    def test_calls_selector_and_writes_row_for_each_spec(self):
        client = _make_alpaca_client()
        client.get_stock_quote.return_value = self._stock_quote(299.0, 301.0)

        spec = ContractSpec(symbol=_WEEKLY_CALL, option_type="call")
        selector = Mock()
        selector.select_contracts.return_value = [spec]

        client.get_option_quote_by_occ.return_value = _make_option_quote(bid=19.0, ask=21.0)

        monitor = OptionPriceMonitor(
            client=client,
            tickers=["TSLA"],
            output_dir="/tmp/test_opm_snap",
            contract_selector=selector,
        )

        with patch("alpha_tech_tracker.op_momentum_strategy.option_price_monitor.os.makedirs"), \
             patch("builtins.open", create=True) as mock_open, \
             patch(_DATE_PATH) as mock_date:
            mock_date.today.return_value = date(2026, 4, 9)
            mock_date.side_effect = date
            mock_open.return_value.__enter__ = Mock(return_value=Mock())
            mock_open.return_value.__exit__ = Mock(return_value=False)
            monitor._snapshot_ticker("TSLA")

        selector.select_contracts.assert_called_once()
        assert _WEEKLY_CALL in monitor._cache

    def test_skips_spec_when_fetch_stats_returns_none(self):
        client = _make_alpaca_client()
        client.get_stock_quote.return_value = self._stock_quote(299.0, 301.0)
        client.get_option_quote_by_occ.side_effect = Exception(
            "no quote"
        )

        spec = ContractSpec(symbol=_WEEKLY_CALL, option_type="call")
        selector = Mock()
        selector.select_contracts.return_value = [spec]

        monitor = OptionPriceMonitor(
            client=client,
            tickers=["TSLA"],
            output_dir="/tmp/test_opm_snap",
            contract_selector=selector,
        )

        with patch(_DATE_PATH) as mock_date:
            mock_date.today.return_value = date(2026, 4, 9)
            mock_date.side_effect = date
            monitor._snapshot_ticker("TSLA")

        assert _WEEKLY_CALL not in monitor._cache

    def test_uses_mid_of_stock_bid_ask_as_stock_price(self):
        client = _make_alpaca_client()
        client.get_stock_quote.return_value = self._stock_quote(298.0, 302.0)

        selector = Mock()
        selector.select_contracts.return_value = []

        monitor = OptionPriceMonitor(
            client=client,
            tickers=["TSLA"],
            contract_selector=selector,
        )

        with patch(_DATE_PATH) as mock_date:
            mock_date.today.return_value = date(2026, 4, 9)
            mock_date.side_effect = date
            monitor._snapshot_ticker("TSLA")

        call_args = selector.select_contracts.call_args
        assert call_args[0][1] == _D("300.0")  # mid of 298/302


class TestTradeEngineStrikeSelector:
    def test_returns_call_and_put_contract_specs(self):
        client = _make_alpaca_client()
        selector_mock = Mock()
        selector_mock.select.side_effect = [
            "TSLA260410C00280000",  # BULLISH call
            "TSLA260410P00320000",  # BEARISH put
        ]

        with patch(
            "alpha_tech_tracker.op_momentum_strategy.option_price_monitor.TimePremiumContractSelector",
            return_value=selector_mock,
        ):
            tess = TradeEngineStrikeSelector(client)
            specs = tess.select_contracts("TSLA", _D("300"))

        assert len(specs) == 2
        assert specs[0].symbol == "TSLA260410C00280000"
        assert specs[0].option_type == "call"
        assert specs[1].symbol == "TSLA260410P00320000"
        assert specs[1].option_type == "put"

    def test_swallows_exception_and_returns_partial_list(self):
        client = _make_alpaca_client()
        selector_mock = Mock()
        selector_mock.select.side_effect = [
            RuntimeError("no call contracts"),
            "TSLA260410P00320000",
        ]

        with patch(
            "alpha_tech_tracker.op_momentum_strategy.option_price_monitor.TimePremiumContractSelector",
            return_value=selector_mock,
        ):
            tess = TradeEngineStrikeSelector(client)
            specs = tess.select_contracts("TSLA", _D("300"))

        assert len(specs) == 1
        assert specs[0].option_type == "put"

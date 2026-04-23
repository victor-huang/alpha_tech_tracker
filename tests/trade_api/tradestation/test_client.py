import pytest
from datetime import date
from unittest.mock import MagicMock, patch

from alpha_tech_tracker.trade_api.tradestation.client import (
    TradeStationAPIClient,
    APIInvalidArgumentError,
    _occ_to_ts,
    _ts_to_occ,
    _occ_to_ts_order_symbol,
    _ts_search_name_to_occ,
    _parse_ts_date,
    _parse_tick_from_error,
)
from alpha_tech_tracker.trade_api.tradestation.tradestation_api_response import (
    accounts_response,
    balances_response,
    stock_quote_response,
    option_quote_response,
    option_search_response,
    place_order_response,
    orders_open_response,
    orders_filled_response,
    orders_cancelled_response,
    cancel_order_response,
)

_ACCOUNT_KEY = "123456"


def _make_client():
    client = TradeStationAPIClient(
        client_id="test_client_id",
        client_secret="test_client_secret",
        selected_account_key=_ACCOUNT_KEY,
        environment="sim",
    )
    client._session = MagicMock()
    client._user_id = "testuser"
    return client


def _mock_response(data, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = data
    return resp


class TestOccTsSymbolConversion:
    def test_four_char_ticker_padded_to_six(self):
        assert _occ_to_ts("TSLA250420C00240000") == "TSLA  250420C00240000"

    def test_three_char_ticker_padded_to_six(self):
        assert _occ_to_ts("SPY250321C00520000") == "SPY   250321C00520000"

    def test_four_char_ticker_put(self):
        assert _occ_to_ts("AAPL250117P00200000") == "AAPL  250117P00200000"

    def test_ts_to_occ_strips_spaces(self):
        assert _ts_to_occ("TSLA  250420C00240000") == "TSLA250420C00240000"

    def test_ts_to_occ_three_char(self):
        assert _ts_to_occ("SPY   250321C00520000") == "SPY250321C00520000"

    def test_roundtrip(self):
        original = "TSLA250420C00240000"
        assert _ts_to_occ(_occ_to_ts(original)) == original

    def test_invalid_occ_raises(self):
        with pytest.raises(ValueError):
            _occ_to_ts("bad-symbol")


class TestOrderSymbolConversions:
    def test_occ_to_order_symbol_whole_strike(self):
        assert _occ_to_ts_order_symbol("TSLA260417C00390000") == "TSLA 260417C390"

    def test_occ_to_order_symbol_decimal_strike(self):
        assert _occ_to_ts_order_symbol("TSLA260417C00392500") == "TSLA 260417C392.5"

    def test_occ_to_order_symbol_three_char_ticker(self):
        assert _occ_to_ts_order_symbol("SPY260417C00520000") == "SPY 260417C520"

    def test_occ_to_order_symbol_put(self):
        assert _occ_to_ts_order_symbol("TSLA260417P00390000") == "TSLA 260417P390"

    def test_ts_search_name_to_occ_whole_strike(self):
        assert _ts_search_name_to_occ("TSLA 260417C390") == "TSLA260417C00390000"

    def test_ts_search_name_to_occ_decimal_strike(self):
        assert _ts_search_name_to_occ("TSLA 260417C392.5") == "TSLA260417C00392500"

    def test_ts_search_name_to_occ_three_char_ticker(self):
        assert _ts_search_name_to_occ("SPY 260417C520") == "SPY260417C00520000"

    def test_ts_search_name_to_occ_roundtrip(self):
        occ = "TSLA260417C00392500"
        assert _ts_search_name_to_occ(_occ_to_ts_order_symbol(occ)) == occ

    def test_parse_ts_date_epoch_ms(self):
        # /Date(1744848000000)/ corresponds to 2025-04-17 UTC
        assert _parse_ts_date("/Date(1744848000000)/") == "2025-04-17"

    def test_parse_ts_date_iso_string(self):
        assert _parse_ts_date("2025-04-17T00:00:00Z") == "2025-04-17"

    def test_parse_ts_date_date_only(self):
        assert _parse_ts_date("2025-04-17") == "2025-04-17"


class TestGetAccounts:
    def test_returns_normalized_buying_power_cash_equity(self):
        client = _make_client()
        client._session.get.return_value = _mock_response(balances_response)

        result = client.get_accounts()

        assert result["buying_power"] == 50000.00
        assert result["cash"] == 48000.00
        assert result["portfolio_value"] == 52000.00
        assert result["equity"] == 52000.00
        assert result["account_id"] == _ACCOUNT_KEY

    def test_includes_raw_response(self):
        client = _make_client()
        client._session.get.return_value = _mock_response(balances_response)

        result = client.get_accounts()

        assert result["raw_response"] == balances_response["Balances"][0]

    def test_resolves_account_key_when_not_set(self):
        client = _make_client()
        client._account_key = None
        client._session.get.side_effect = [
            _mock_response(accounts_response),
            _mock_response(balances_response),
        ]

        result = client.get_accounts()

        assert client._account_key == _ACCOUNT_KEY
        assert result["buying_power"] == 50000.00

    def test_uses_first_active_account_when_no_key_given(self):
        client = _make_client()
        client._account_key = None
        two_accounts = {
            "Accounts": [
                {"AccountID": "111", "Status": "Closed", "Name": "closed"},
                {"AccountID": "222", "Status": "Active", "Name": "active"},
            ]
        }
        client._session.get.side_effect = [
            _mock_response(two_accounts),
            _mock_response(balances_response),
        ]

        client.get_accounts()

        assert client._account_key == "222"

    def test_get_accounts_uses_v3_balances_url(self):
        client = _make_client()
        client._session.get.return_value = _mock_response(balances_response)

        client.get_accounts()

        url = client._session.get.call_args[0][0]
        assert "/v3/brokerage/accounts/" in url
        assert "balances" in url


class TestGetStockQuote:
    def test_single_symbol_returns_nested_shape(self):
        client = _make_client()
        client._session.get.return_value = _mock_response(stock_quote_response)

        result = client.get_stock_quote("TSLA")

        assert result["QuoteResponse"]["QuoteData"][0]["All"]["bid"] == 245.10
        assert result["QuoteResponse"]["QuoteData"][0]["All"]["ask"] == 245.30

    def test_multiple_symbols_returns_dict_keyed_by_symbol(self):
        client = _make_client()
        two_quotes = [
            {"Symbol": "TSLA", "Bid": 245.10, "Ask": 245.30, "BidSize": 10, "AskSize": 10},
            {"Symbol": "AAPL", "Bid": 182.00, "Ask": 182.20, "BidSize": 5, "AskSize": 5},
        ]
        client._session.get.return_value = _mock_response(two_quotes)

        result = client.get_stock_quote(["TSLA", "AAPL"])

        assert "TSLA" in result
        assert "AAPL" in result
        assert result["AAPL"]["QuoteResponse"]["QuoteData"][0]["All"]["bid"] == 182.00

    def test_comma_joins_multiple_symbols_in_url(self):
        client = _make_client()
        client._session.get.return_value = _mock_response([
            {"Symbol": "TSLA", "Bid": 1.0, "Ask": 2.0},
            {"Symbol": "AAPL", "Bid": 1.0, "Ask": 2.0},
        ])

        client.get_stock_quote(["TSLA", "AAPL"])

        url = client._session.get.call_args[0][0]
        assert "TSLA,AAPL" in url

    def test_feed_kwarg_ignored(self):
        client = _make_client()
        client._session.get.return_value = _mock_response(stock_quote_response)

        result = client.get_stock_quote("TSLA", feed="iex")

        assert result["QuoteResponse"]["QuoteData"][0]["All"]["bid"] == 245.10


class TestGetOptionQuoteByOcc:
    def test_returns_bid_ask_mid(self):
        client = _make_client()
        client._session.get.return_value = _mock_response(option_quote_response)

        result = client.get_option_quote_by_occ("TSLA250420C00240000")

        assert result["bid"] == 10.20
        assert result["ask"] == 10.60
        assert result["mid"] == pytest.approx((10.20 + 10.60) / 2)

    def test_occ_converted_to_display_symbol_in_url(self):
        # v2 quote API requires display format "TSLA 250420C240", not padded OCC.
        client = _make_client()
        client._session.get.return_value = _mock_response(option_quote_response)

        client.get_option_quote_by_occ("TSLA250420C00240000")

        url = client._session.get.call_args[0][0]
        assert "TSLA 250420C240" in url


class TestGetOptionQuotesByOccBatch:
    def test_returns_dict_keyed_by_occ_symbol(self):
        client = _make_client()
        two_quotes = [
            {"Symbol": "TSLA 250420C240", "Bid": 10.20, "Ask": 10.60},
            {"Symbol": "TSLA 250420C245", "Bid": 8.00, "Ask": 8.40},
        ]
        client._session.get.return_value = _mock_response(two_quotes)

        result = client.get_option_quotes_by_occ_batch(
            ["TSLA250420C00240000", "TSLA250420C00245000"]
        )

        assert "TSLA250420C00240000" in result
        assert "TSLA250420C00245000" in result
        assert result["TSLA250420C00240000"]["bid"] == 10.20

    def test_single_http_call_for_batch(self):
        client = _make_client()
        client._session.get.return_value = _mock_response([
            {"Symbol": "TSLA 250420C240", "Bid": 10.20, "Ask": 10.60},
        ])

        client.get_option_quotes_by_occ_batch(
            ["TSLA250420C00240000", "TSLA250420C00245000"]
        )

        assert client._session.get.call_count == 1

    def test_missing_symbol_omitted_from_result(self):
        client = _make_client()
        client._session.get.return_value = _mock_response([
            {"Symbol": "TSLA 250420C240", "Bid": 10.20, "Ask": 10.60},
        ])

        result = client.get_option_quotes_by_occ_batch(
            ["TSLA250420C00240000", "TSLA250420C00245000"]
        )

        assert "TSLA250420C00240000" in result
        assert "TSLA250420C00245000" not in result

    def test_empty_list_returns_empty_dict(self):
        client = _make_client()
        assert client.get_option_quotes_by_occ_batch([]) == {}
        client._session.get.assert_not_called()


class TestGetOptionsContracts:
    def test_with_specific_expiry_returns_normalized_contracts(self):
        client = _make_client()
        client._session.get.return_value = _mock_response(option_search_response)

        contracts = client.get_options_contracts(
            underlying_symbol="TSLA",
            expiration_date=date(2025, 4, 17),
            option_type="call",
        )

        call_contracts = [c for c in contracts if c["option_type"] == "call"]
        assert len(call_contracts) == 2
        assert call_contracts[0]["symbol"] == "TSLA250417C00240000"
        assert call_contracts[0]["expiration_date"] == "2025-04-17"
        assert call_contracts[0]["strike_price"] == 240.0
        assert call_contracts[0]["contract_size"] == 100

    def test_call_filter_excludes_puts(self):
        client = _make_client()
        client._session.get.return_value = _mock_response(option_search_response)

        contracts = client.get_options_contracts(
            underlying_symbol="TSLA",
            option_type="call",
        )

        assert all(c["option_type"] == "call" for c in contracts)

    def test_strike_range_filter_applied(self):
        client = _make_client()
        client._session.get.return_value = _mock_response(option_search_response)

        contracts = client.get_options_contracts(
            underlying_symbol="TSLA",
            strike_price_gte=243,
            strike_price_lte=250,
        )

        strikes = [c["strike_price"] for c in contracts]
        assert 245.0 in strikes
        assert 240.0 not in strikes

    def test_padded_occ_symbol_normalized(self):
        # Fixture uses display name format — _ts_search_name_to_occ parses it correctly.
        client = _make_client()
        display_name_response = [
            {
                "Name": "TSLA 250417C240",
                "ExpirationDate": "/Date(1744848000000)/",
                "OptionType": "Call",
                "StrikePrice": 240.0,
                "Root": "TSLA",
            }
        ]
        client._session.get.return_value = _mock_response(display_name_response)

        contracts = client.get_options_contracts(underlying_symbol="TSLA")

        assert contracts[0]["symbol"] == "TSLA250417C00240000"

    def test_option_type_call_singular_accepted(self):
        # API returns "Call" (not "Calls") — both must be accepted.
        client = _make_client()
        call_response = [
            {
                "Name": "TSLA 250417C240",
                "ExpirationDate": "/Date(1744848000000)/",
                "OptionType": "Call",
                "StrikePrice": 240.0,
                "Root": "TSLA",
            }
        ]
        client._session.get.return_value = _mock_response(call_response)

        contracts = client.get_options_contracts(
            underlying_symbol="TSLA", option_type="call"
        )

        assert len(contracts) == 1
        assert contracts[0]["option_type"] == "call"

    def test_epoch_ms_expiry_date_parsed(self):
        # /Date(1744848000000)/ must parse to 2025-04-17.
        client = _make_client()
        epoch_response = [
            {
                "Name": "TSLA 250417C240",
                "ExpirationDate": "/Date(1744848000000)/",
                "OptionType": "Call",
                "StrikePrice": 240.0,
                "Root": "TSLA",
            }
        ]
        client._session.get.return_value = _mock_response(epoch_response)

        contracts = client.get_options_contracts(underlying_symbol="TSLA")

        assert contracts[0]["expiration_date"] == "2025-04-17"

    def test_date_range_query_includes_date_bounds_in_criteria(self):
        client = _make_client()
        client._session.get.return_value = _mock_response([])

        client.get_options_contracts(
            underlying_symbol="TSLA",
            expiration_date_gte=date(2025, 4, 15),
            expiration_date_lte=date(2025, 4, 30),
        )

        url = client._session.get.call_args[0][0]
        assert "Edl=04-15-2025" in url
        assert "Edh=04-30-2025" in url

    def test_empty_response_returns_empty_list(self):
        client = _make_client()
        client._session.get.return_value = _mock_response([])

        result = client.get_options_contracts(underlying_symbol="TSLA")

        assert result == []


class TestPlaceOptionOrder:
    def test_returns_normalized_order_dict(self):
        client = _make_client()
        client._session.post.return_value = _mock_response(place_order_response)

        result = client.place_option_order(
            symbol="TSLA",
            price=10.50,
            _option_symbol_override="TSLA250420C00240000",
        )

        assert result["order_id"] == "207887821"
        assert result["status"] == "open"
        assert result["limit_price"] == 10.50
        assert result["symbol"] == "TSLA250420C00240000"

    def test_single_post_no_preview(self):
        client = _make_client()
        client._session.post.return_value = _mock_response(place_order_response)

        client.place_option_order(
            symbol="TSLA",
            price=10.50,
            _option_symbol_override="TSLA250420C00240000",
        )

        assert client._session.post.call_count == 1

    def test_display_symbol_sent_in_order_body(self):
        # v3 order endpoint requires display format "TSLA 250420C240", not padded OCC.
        client = _make_client()
        client._session.post.return_value = _mock_response(place_order_response)

        client.place_option_order(
            symbol="TSLA",
            price=10.50,
            _option_symbol_override="TSLA250420C00240000",
        )

        body = client._session.post.call_args[1]["json"]
        assert body["Symbol"] == "TSLA 250420C240"

    def test_buy_open_maps_to_buytoopen(self):
        client = _make_client()
        client._session.post.return_value = _mock_response(place_order_response)

        client.place_option_order(
            symbol="TSLA",
            price=10.50,
            order_action="BUY_OPEN",
            _option_symbol_override="TSLA250420C00240000",
        )

        body = client._session.post.call_args[1]["json"]
        assert body["TradeAction"] == "BUYTOOPEN"

    def test_sell_close_maps_to_selltoclose(self):
        client = _make_client()
        client._session.post.return_value = _mock_response(place_order_response)

        client.place_option_order(
            symbol="TSLA",
            price=10.50,
            order_action="SELL_CLOSE",
            _option_symbol_override="TSLA250420C00240000",
        )

        body = client._session.post.call_args[1]["json"]
        assert body["TradeAction"] == "SELLTOCLOSE"

    def test_asset_type_is_op(self):
        client = _make_client()
        client._session.post.return_value = _mock_response(place_order_response)

        client.place_option_order(
            symbol="TSLA",
            price=10.50,
            _option_symbol_override="TSLA250420C00240000",
        )

        body = client._session.post.call_args[1]["json"]
        assert body["AssetType"] == "OP"

    def test_time_in_force_nested_object(self):
        # v3 requires {"TimeInForce": {"Duration": "DAY"}}, not flat "Duration".
        client = _make_client()
        client._session.post.return_value = _mock_response(place_order_response)

        client.place_option_order(
            symbol="TSLA",
            price=10.50,
            _option_symbol_override="TSLA250420C00240000",
        )

        body = client._session.post.call_args[1]["json"]
        assert body["TimeInForce"] == {"Duration": "DAY"}

    def test_account_id_in_order_body(self):
        # v3 uses "AccountID", not "AccountKey".
        client = _make_client()
        client._session.post.return_value = _mock_response(place_order_response)

        client.place_option_order(
            symbol="TSLA",
            price=10.50,
            _option_symbol_override="TSLA250420C00240000",
        )

        body = client._session.post.call_args[1]["json"]
        assert body["AccountID"] == _ACCOUNT_KEY

    def test_order_id_extracted_from_orders_wrapper(self):
        # v3 response: {"Orders": [{"OrderID": "..."}]} — must unwrap before reading order_id.
        client = _make_client()
        wrapped_response = {"Orders": [{"OrderID": "999888777", "Error": "OK"}]}
        client._session.post.return_value = _mock_response(wrapped_response)

        result = client.place_option_order(
            symbol="TSLA",
            price=10.50,
            _option_symbol_override="TSLA250420C00240000",
        )

        assert result["order_id"] == "999888777"

    def test_uses_v3_orderexecution_url(self):
        client = _make_client()
        client._session.post.return_value = _mock_response(place_order_response)

        client.place_option_order(
            symbol="TSLA",
            price=10.50,
            _option_symbol_override="TSLA250420C00240000",
        )

        url = client._session.post.call_args[0][0]
        assert "/v3/orderexecution/orders" in url

    def test_market_order_omits_limit_price_in_body(self):
        client = _make_client()
        client._session.post.return_value = _mock_response(place_order_response)

        client.place_option_order(
            symbol="TSLA",
            price_type="MARKET",
            _option_symbol_override="TSLA250420C00240000",
        )

        body = client._session.post.call_args[1]["json"]
        assert "LimitPrice" not in body
        assert body["OrderType"] == "Market"

    def test_missing_option_symbol_override_raises(self):
        client = _make_client()

        with pytest.raises(APIInvalidArgumentError):
            client.place_option_order(symbol="TSLA", price=10.50)

    def test_limit_order_missing_price_raises(self):
        client = _make_client()

        with pytest.raises(APIInvalidArgumentError):
            client.place_option_order(
                symbol="TSLA",
                price_type="LIMIT",
                price=None,
                _option_symbol_override="TSLA250420C00240000",
            )

    def test_smart_market_fetches_quote_then_places_limit(self):
        client = _make_client()
        client._session.get.return_value = _mock_response(option_quote_response)
        client._session.post.return_value = _mock_response(place_order_response)

        client.place_option_order(
            symbol="TSLA",
            price_type="SMART_MARKET",
            _option_symbol_override="TSLA250420C00240000",
        )

        assert client._session.get.call_count == 1
        assert client._session.post.call_count == 1
        body = client._session.post.call_args[1]["json"]
        assert body["OrderType"] == "Limit"


class TestParseTickFromError:
    def test_confirmed_production_format(self):
        from decimal import Decimal
        assert _parse_tick_from_error(
            "Price = 41.65000000 not rounded to a valid price increment [ 0.1 ]"
        ) == Decimal("0.1")

    def test_five_cent_tick_in_brackets(self):
        from decimal import Decimal
        assert _parse_tick_from_error(
            "Price = 0.09000000 not rounded to a valid price increment [ 0.05 ]"
        ) == Decimal("0.05")

    def test_increments_of_pattern_fallback(self):
        from decimal import Decimal
        assert _parse_tick_from_error("LimitPrice must be in increments of 0.10") \
            == Decimal("0.10")

    def test_multiple_of_pattern_fallback(self):
        from decimal import Decimal
        assert _parse_tick_from_error("Price must be a multiple of 0.05") \
            == Decimal("0.05")

    def test_no_increment_in_message_returns_none(self):
        assert _parse_tick_from_error("Invalid symbol") is None

    def test_unrelated_number_does_not_match(self):
        assert _parse_tick_from_error("Order rejected for account 12345") is None


class TestPlaceOptionOrderTickRetry:
    def test_price_sent_as_is_without_client_rounding(self):
        client = _make_client()
        client._session.post.return_value = _mock_response(place_order_response)

        client.place_option_order(
            symbol="APP",
            price=75.85,
            order_action="BUY_OPEN",
            _option_symbol_override="APP250417P00520000",
        )

        body = client._session.post.call_args[1]["json"]
        assert body["LimitPrice"] == "75.85"

    def test_reject_reason_exposed_in_normalized_order(self):
        # Tick rejection arrives as RejectReason on the order record (Status=REJ),
        # not as a 400 HTTP error. Verify _normalize_order surfaces it.
        client = _make_client()
        rej_order = {
            "OrderID": "9999",
            "Status": "REJ",
            "LimitPrice": "41.65",
            "RejectReason": "Price = 41.65000000 not rounded to a valid price increment [ 0.1 ]",
            "Legs": [],
        }
        result = client._normalize_order(rej_order)
        assert result["status"] == "canceled"
        assert "0.1" in result["reject_reason"]

    def test_non_tick_400_error_raises(self):
        client = _make_client()
        error_response = _mock_response(
            {"Message": "Account not authorized"}, status_code=400
        )
        client._session.post.return_value = error_response

        with pytest.raises(APIInvalidArgumentError):
            client.place_option_order(
                symbol="TSLA",
                price=75.85,
                order_action="BUY_OPEN",
                _option_symbol_override="TSLA250420C00240000",
            )


class TestPlaceStockOrder:
    def test_returns_normalized_order_dict(self):
        client = _make_client()
        client._session.post.return_value = _mock_response(place_order_response)

        result = client.place_stock_order(
            symbol="TSLA",
            quantity=10,
            side="BUY",
            order_type="LIMIT",
            limit_price=245.00,
        )

        assert result["order_id"] == "207887821"
        assert result["status"] == "open"
        assert result["symbol"] == "TSLA"
        assert result["quantity"] == 10.0
        assert result["limit_price"] == 245.00

    def test_buy_maps_to_buy_trade_action(self):
        client = _make_client()
        client._session.post.return_value = _mock_response(place_order_response)

        client.place_stock_order("TSLA", 10, side="BUY", order_type="MARKET")

        body = client._session.post.call_args[1]["json"]
        assert body["TradeAction"] == "BUY"
        assert body["AssetType"] == "EQ"

    def test_sell_maps_to_sell_trade_action(self):
        client = _make_client()
        client._session.post.return_value = _mock_response(place_order_response)

        client.place_stock_order("TSLA", 10, side="SELL", order_type="MARKET")

        body = client._session.post.call_args[1]["json"]
        assert body["TradeAction"] == "SELL"

    def test_limit_price_included_in_body(self):
        client = _make_client()
        client._session.post.return_value = _mock_response(place_order_response)

        client.place_stock_order("TSLA", 10, order_type="LIMIT", limit_price=245.00)

        body = client._session.post.call_args[1]["json"]
        assert body["LimitPrice"] == "245"
        assert body["OrderType"] == "Limit"

    def test_market_order_omits_limit_price(self):
        client = _make_client()
        client._session.post.return_value = _mock_response(place_order_response)

        client.place_stock_order("TSLA", 10, order_type="MARKET")

        body = client._session.post.call_args[1]["json"]
        assert "LimitPrice" not in body
        assert body["OrderType"] == "Market"

    def test_time_in_force_nested_object(self):
        # v3 requires {"TimeInForce": {"Duration": "DAY"}}, not flat "Duration".
        client = _make_client()
        client._session.post.return_value = _mock_response(place_order_response)

        client.place_stock_order("TSLA", 10, order_type="MARKET")

        body = client._session.post.call_args[1]["json"]
        assert body["TimeInForce"] == {"Duration": "DAY"}

    def test_account_id_in_order_body(self):
        client = _make_client()
        client._session.post.return_value = _mock_response(place_order_response)

        client.place_stock_order("TSLA", 10, order_type="MARKET")

        body = client._session.post.call_args[1]["json"]
        assert body["AccountID"] == _ACCOUNT_KEY

    def test_uses_v3_orderexecution_url(self):
        client = _make_client()
        client._session.post.return_value = _mock_response(place_order_response)

        client.place_stock_order("TSLA", 10, order_type="MARKET")

        url = client._session.post.call_args[0][0]
        assert "/v3/orderexecution/orders" in url

    def test_limit_order_without_price_raises(self):
        client = _make_client()

        with pytest.raises(APIInvalidArgumentError):
            client.place_stock_order("TSLA", 10, order_type="LIMIT")


class TestOrderStatus:
    def test_fll_maps_to_filled(self):
        client = _make_client()
        client._session.get.return_value = _mock_response(orders_filled_response)

        result = client.order_status("207887821")

        assert result["status"] == "filled"
        assert result["order_id"] == "207887821"

    def test_opn_maps_to_open(self):
        client = _make_client()
        client._session.get.return_value = _mock_response(orders_open_response)

        result = client.order_status("207887821")

        assert result["status"] == "open"

    def test_can_maps_to_canceled(self):
        client = _make_client()
        client._session.get.return_value = _mock_response(orders_cancelled_response)

        result = client.order_status("207887821")

        assert result["status"] == "canceled"

    def test_filled_qty_and_avg_price_extracted(self):
        client = _make_client()
        client._session.get.return_value = _mock_response(orders_filled_response)

        result = client.order_status("207887821")

        assert result["filled_qty"] == 1.0
        assert result["filled_avg_price"] == 10.50

    def test_occ_symbol_normalized_in_result(self):
        # Legs[0].Symbol is display format "TSLA 250420C240" — must be converted to OCC.
        client = _make_client()
        client._session.get.return_value = _mock_response(orders_filled_response)

        result = client.order_status("207887821")

        assert result["symbol"] == "TSLA250420C00240000"

    def test_qty_and_filled_qty_from_legs(self):
        # v3 stores QuantityOrdered and ExecQuantity inside Legs[0], not top-level.
        client = _make_client()
        client._session.get.return_value = _mock_response(orders_open_response)

        result = client.order_status("207887821")

        assert result["quantity"] == 1.0
        assert result["filled_qty"] == 0.0

    def test_uses_v3_brokerage_orders_url(self):
        client = _make_client()
        client._session.get.return_value = _mock_response(orders_open_response)

        client.order_status("207887821")

        url = client._session.get.call_args[0][0]
        assert "/v3/brokerage/accounts/" in url
        assert "/orders" in url

    def test_rej_maps_to_canceled(self):
        # REJ status (after-hours rejected orders) must map to "canceled".
        client = _make_client()
        rej_response = {
            "Orders": [
                {
                    "OrderID": "207887821",
                    "Status": "REJ",
                    "LimitPrice": "1.00",
                    "FilledPrice": "0",
                    "OpenedDateTime": "2025-04-20T09:31:00Z",
                    "Legs": [
                        {
                            "Symbol": "TSLA 250420C240",
                            "QuantityOrdered": "1",
                            "ExecQuantity": "0",
                            "BuyOrSell": "Buy",
                        }
                    ],
                }
            ]
        }
        client._session.get.return_value = _mock_response(rej_response)

        result = client.order_status("207887821")

        assert result["status"] == "canceled"

    def test_order_not_found_returns_open(self):
        client = _make_client()
        client._session.get.return_value = _mock_response([])

        result = client.order_status("999999")

        assert result["order_id"] == "999999"
        assert result["status"] == "open"


class TestCancelOrder:
    def test_delete_method_used(self):
        client = _make_client()
        client._session.delete.return_value = _mock_response(cancel_order_response)

        client.cancel_order("207887821")

        assert client._session.delete.called
        url = client._session.delete.call_args[0][0]
        assert "207887821" in url

    def test_cancel_uses_v3_orderexecution_url(self):
        client = _make_client()
        client._session.delete.return_value = _mock_response(cancel_order_response)

        client.cancel_order("207887821")

        url = client._session.delete.call_args[0][0]
        assert "/v3/orderexecution/orders/" in url

    def test_returns_normalized_cancel_dict(self):
        client = _make_client()
        client._session.delete.return_value = _mock_response(cancel_order_response)

        result = client.cancel_order("207887821")

        assert result["order_id"] == "207887821"
        assert result["status"] == "canceled"
        assert "message" in result

    def test_not_an_open_order_400_returns_canceled_gracefully(self):
        # Already-closed orders return 400 "Not an open order." — must not raise.
        client = _make_client()
        client._session.delete.return_value = _mock_response(
            {"Message": "Not an open order."}, status_code=400
        )

        result = client.cancel_order("207887821")

        assert result["status"] == "canceled"
        assert result["order_id"] == "207887821"

    def test_api_error_on_400_raises(self):
        client = _make_client()
        client._session.delete.return_value = _mock_response(
            {"Message": "Order already filled"}, status_code=400
        )

        with pytest.raises(APIInvalidArgumentError):
            client.cancel_order("207887821")


class TestRestoreSession:
    def test_creates_oauth2_session_from_token_dict(self):
        pass

        client = TradeStationAPIClient(
            client_id="key",
            client_secret="secret",
            environment="sim",
        )
        token = {
            "access_token": "acc_tok",
            "refresh_token": "ref_tok",
            "token_type": "Bearer",
            "expires_at": 9999999999.0,
        }

        with patch("alpha_tech_tracker.trade_api.tradestation.client.OAuth2Session") as mock_session_cls, \
             patch("alpha_tech_tracker.op_momentum_strategy.config._save_tradestation_session_tokens"):
            client.restore_session(token)
            mock_session_cls.assert_called_once()
            kwargs = mock_session_cls.call_args[1]
            assert kwargs["auto_refresh_url"] == "https://signin.tradestation.com/oauth/token"
            assert "token_updater" in kwargs

    def test_user_id_stored_from_token(self):
        client = TradeStationAPIClient(
            client_id="key",
            client_secret="secret",
            environment="sim",
        )
        token = {
            "access_token": "acc",
            "refresh_token": "ref",
            "token_type": "Bearer",
            "expires_at": 9999999999.0,
            "userid": "myuser",
        }

        with patch("alpha_tech_tracker.trade_api.tradestation.client.OAuth2Session"), \
             patch("alpha_tech_tracker.op_momentum_strategy.config._save_tradestation_session_tokens"):
            client.restore_session(token)

        assert client._user_id == "myuser"


class TestVerifySession:
    def test_returns_true_on_200(self):
        client = _make_client()
        client._session.get.return_value = _mock_response({"data": "ok"}, status_code=200)

        assert client.verify_session() is True

    def test_returns_false_on_non_200(self):
        client = _make_client()
        client._session.get.return_value = _mock_response({}, status_code=401)

        assert client.verify_session() is False

    def test_returns_false_when_no_session(self):
        client = TradeStationAPIClient(client_id="k", client_secret="s")
        assert client._session is None
        assert client.verify_session() is False

    def test_returns_false_on_exception(self):
        client = _make_client()
        client._session.get.side_effect = ConnectionError("network down")

        assert client.verify_session() is False


class TestAuthorizeSession:
    def test_raises_when_credentials_missing(self):
        client = TradeStationAPIClient(environment="sim")

        with pytest.raises(RuntimeError, match="credentials are missing"):
            client.authorize_session()


# ---------------------------------------------------------------------------
# _build_session — HTTPAdapter connection pool size
# ---------------------------------------------------------------------------

class TestBuildSessionHttpAdapter:
    def test_mounts_http_adapter_on_https_prefix(self):
        from unittest.mock import MagicMock, patch
        from requests.adapters import HTTPAdapter

        client = TradeStationAPIClient(
            client_id="test_id",
            client_secret="test_secret",
            environment="sim",
        )
        token = {"access_token": "tok", "token_type": "Bearer", "expires_at": 9999999999}
        mock_session = MagicMock()

        with patch("alpha_tech_tracker.trade_api.tradestation.client.OAuth2Session", return_value=mock_session), \
             patch("alpha_tech_tracker.op_momentum_strategy.config._save_tradestation_session_tokens"):
            client._build_session(token)

        url_prefix, adapter = mock_session.mount.call_args[0]
        assert url_prefix == "https://"
        assert isinstance(adapter, HTTPAdapter)

    def test_http_adapter_pool_size_is_30(self):
        from unittest.mock import MagicMock, patch

        client = TradeStationAPIClient(
            client_id="test_id",
            client_secret="test_secret",
            environment="sim",
        )
        token = {"access_token": "tok", "token_type": "Bearer", "expires_at": 9999999999}
        mock_session = MagicMock()

        with patch("alpha_tech_tracker.trade_api.tradestation.client.OAuth2Session", return_value=mock_session), \
             patch("alpha_tech_tracker.op_momentum_strategy.config._save_tradestation_session_tokens"), \
             patch("requests.adapters.HTTPAdapter") as mock_adapter_cls:
            client._build_session(token)

        mock_adapter_cls.assert_called_once_with(pool_connections=30, pool_maxsize=30)

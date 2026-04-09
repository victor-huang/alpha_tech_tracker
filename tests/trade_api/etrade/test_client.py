import pytest
from unittest.mock import MagicMock
from datetime import date

from alpha_tech_tracker.trade_api.etrade.client import (
    EtradeAPIClient,
    _parse_occ_symbol,
    _build_occ_symbol,
)
from alpha_tech_tracker.trade_api.etrade.etrade_api_response import (
    account_list,
    option_quote,
    option_order_status,
    order_status_executed_order,
    success_place_option_order,
    option_preview_response,
    success_preview_order,
    success_place_trade_response,
)

_ACCOUNT_ID = "712793764"
_ACCOUNT_ID_KEY = "IgItVLi3690yUCGDu_CGoA"
_OCC_SYMBOL = "TSLA231013C00240000"
_OCC_SYMBOL_NON_INT_STRIKE = "TSLA231013C00247500"


def _make_client():
    client = EtradeAPIClient(
        key_id="test_key",
        client_secret="test_secret",
        selected_account_id=_ACCOUNT_ID,
    )
    client._session = MagicMock()
    return client


def _mock_response(data, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = __import__("json").dumps(data)
    return resp


class TestParseOccSymbol:
    def test_standard_call(self):
        ticker, year, month, day, opt_type, strike = _parse_occ_symbol("TSLA231013C00240000")
        assert ticker == "TSLA"
        assert year == 2023
        assert month == 10
        assert day == 13
        assert opt_type == "CALL"
        assert strike == 240.0

    def test_put_symbol(self):
        _, _, _, _, opt_type, _ = _parse_occ_symbol("NVDA250117P00600000")
        assert opt_type == "PUT"

    def test_non_integer_strike(self):
        _, _, _, _, _, strike = _parse_occ_symbol("TSLA231013C00247500")
        assert strike == 247.5

    def test_invalid_symbol_raises(self):
        with pytest.raises(ValueError):
            _parse_occ_symbol("INVALID")

    def test_multi_char_ticker(self):
        ticker, _, _, _, _, _ = _parse_occ_symbol("SHOP250117C00100000")
        assert ticker == "SHOP"


class TestBuildOccSymbol:
    def test_call_integer_strike(self):
        symbol = _build_occ_symbol("TSLA", 2023, 10, 13, "CALL", 240.0)
        assert symbol == "TSLA231013C00240000"

    def test_put_non_integer_strike(self):
        symbol = _build_occ_symbol("NVDA", 2025, 1, 17, "PUT", 247.5)
        assert symbol == "NVDA250117P00247500"

    def test_roundtrip(self):
        original = "TSLA231013C00240000"
        ticker, year, month, day, opt_type, strike = _parse_occ_symbol(original)
        rebuilt = _build_occ_symbol(ticker, year, month, day, opt_type, strike)
        assert rebuilt == original


class TestGetAccounts:
    def test_returns_buying_power_from_balance_api(self):
        client = _make_client()
        client._account_id_key = _ACCOUNT_ID_KEY

        balance_response = {
            "BalanceResponse": {
                "Computed": {
                    "cashBuyingPower": 50000.0,
                    "cashBalance": 30000.0,
                    "realTimeValues": {"totalAccountValue": 80000.0},
                }
            }
        }
        client._session.get.return_value = _mock_response(balance_response)

        result = client.get_accounts()

        assert result["buying_power"] == 50000.0
        assert result["cash"] == 30000.0
        assert result["portfolio_value"] == 80000.0

    def test_resolves_account_id_key_when_not_cached(self):
        client = _make_client()
        assert client._account_id_key is None

        balance_response = {
            "BalanceResponse": {
                "Computed": {
                    "cashBuyingPower": 1000.0,
                    "cashBalance": 1000.0,
                    "realTimeValues": {"totalAccountValue": 1000.0},
                }
            }
        }
        client._session.get.side_effect = [
            _mock_response(account_list),
            _mock_response(balance_response),
        ]

        result = client.get_accounts()

        assert client._account_id_key == _ACCOUNT_ID_KEY
        assert result["buying_power"] == 1000.0


class TestGetOptionQuoteByOcc:
    def test_returns_bid_ask_mid(self):
        client = _make_client()
        client._session.get.return_value = _mock_response(option_quote)

        result = client.get_option_quote_by_occ(_OCC_SYMBOL)

        assert result["bid"] == 22.8
        assert result["ask"] == 23.55
        assert result["mid"] == pytest.approx((22.8 + 23.55) / 2)

    def test_builds_correct_etrade_key(self):
        client = _make_client()
        client._session.get.return_value = _mock_response(option_quote)

        client.get_option_quote_by_occ("TSLA231013C00240000")

        call_url = client._session.get.call_args[0][0]
        assert "TSLA:2023:10:13:CALL:240" in call_url

    def test_non_integer_strike_key(self):
        client = _make_client()
        client._session.get.return_value = _mock_response(option_quote)

        client.get_option_quote_by_occ(_OCC_SYMBOL_NON_INT_STRIKE)

        call_url = client._session.get.call_args[0][0]
        assert "247.5" in call_url


class TestGetOptionQuotesByOccBatch:
    def test_returns_dict_keyed_by_occ_symbol(self):
        client = _make_client()
        client._session.get.return_value = _mock_response(option_quote)

        symbols = ["TSLA231013C00240000", "TSLA231013C00245000"]
        result = client.get_option_quotes_by_occ_batch(symbols)

        assert set(result.keys()) == set(symbols)
        for q in result.values():
            assert "bid" in q and "ask" in q and "mid" in q

    def test_skips_failed_symbol_and_continues(self):
        client = _make_client()

        def side_effect(url):
            if "240" in url and "245" not in url:
                return _mock_response(option_quote)
            raise Exception("quote unavailable")

        client._session.get.side_effect = side_effect

        result = client.get_option_quotes_by_occ_batch(
            ["TSLA231013C00240000", "TSLA231013C00245000"]
        )

        assert "TSLA231013C00240000" in result
        assert "TSLA231013C00245000" not in result

    def test_empty_list_returns_empty_dict(self):
        client = _make_client()
        assert client.get_option_quotes_by_occ_batch([]) == {}


class TestGetOptionsContracts:
    def _make_chain_response(self, strikes, expiry: date, opt_type="CALL"):
        pairs = []
        for s in strikes:
            occ = _build_occ_symbol(
                "TSLA", expiry.year, expiry.month, expiry.day, opt_type, s
            )
            side_key = "Call" if opt_type == "CALL" else "Put"
            pairs.append(
                {
                    side_key: {
                        "strikePrice": s,
                        "optionType": opt_type,
                        "bid": 5.0,
                        "ask": 5.5,
                        "osiKey": occ,
                    }
                }
            )
        return {
            "OptionChainResponse": {
                "OptionPair": pairs,
                "SelectedED": {
                    "year": expiry.year,
                    "month": expiry.month,
                    "day": expiry.day,
                },
            }
        }

    def test_with_specific_expiry_date(self):
        client = _make_client()
        expiry = date(2025, 4, 17)
        chain = self._make_chain_response([240, 245, 250], expiry)
        client._session.get.return_value = _mock_response(chain)

        contracts = client.get_options_contracts(
            underlying_symbol="TSLA",
            expiration_date=expiry,
            option_type="call",
        )

        assert len(contracts) == 3
        assert all(c["expiration_date"] == "2025-04-17" for c in contracts)
        assert contracts[0]["symbol"] == "TSLA250417C00240000"

    def test_strike_range_filter(self):
        client = _make_client()
        expiry = date(2025, 4, 17)
        chain = self._make_chain_response([230, 240, 250, 260], expiry)
        client._session.get.return_value = _mock_response(chain)

        contracts = client.get_options_contracts(
            underlying_symbol="TSLA",
            expiration_date=expiry,
            option_type="call",
            strike_price_gte=235,
            strike_price_lte=255,
        )

        strikes = [c["strike_price"] for c in contracts]
        assert 240.0 in strikes and 250.0 in strikes
        assert 230.0 not in strikes and 260.0 not in strikes

    def test_range_query_uses_earliest_available_expiry(self):
        client = _make_client()
        expiry_dates_response = {
            "OptionExpireDateResponse": {
                "ExpirationDate": [
                    {"year": 2025, "month": 4, "day": 17, "expiryType": "WEEKLY"},
                    {"year": 2025, "month": 4, "day": 25, "expiryType": "MONTHLY"},
                ]
            }
        }
        chain = self._make_chain_response([240], date(2025, 4, 17))
        client._session.get.side_effect = [
            _mock_response(expiry_dates_response),
            _mock_response(chain),
        ]

        contracts = client.get_options_contracts(
            underlying_symbol="TSLA",
            option_type="call",
            expiration_date_gte=date(2025, 4, 15),
            expiration_date_lte=date(2025, 4, 30),
        )

        assert len(contracts) == 1
        assert contracts[0]["expiration_date"] == "2025-04-17"

    def test_range_query_returns_empty_when_no_dates_in_range(self):
        client = _make_client()
        expiry_dates_response = {
            "OptionExpireDateResponse": {
                "ExpirationDate": [
                    {"year": 2025, "month": 5, "day": 1, "expiryType": "MONTHLY"},
                ]
            }
        }
        client._session.get.return_value = _mock_response(expiry_dates_response)

        contracts = client.get_options_contracts(
            underlying_symbol="TSLA",
            option_type="call",
            expiration_date_gte=date(2025, 4, 1),
            expiration_date_lte=date(2025, 4, 30),
        )

        assert contracts == []


class TestPlaceOptionOrder:
    def _setup_preview_and_place(self, client):
        client._session.post.side_effect = [
            _mock_response(option_preview_response),
            _mock_response(success_place_option_order),
        ]

    def test_returns_normalized_order_dict(self):
        client = _make_client()
        self._setup_preview_and_place(client)

        result = client.place_option_order(
            symbol="TSLA",
            price=10.0,
            price_type="LIMIT",
            option_type="CALL",
            order_action="BUY_OPEN",
            quantity=1,
            _option_symbol_override=_OCC_SYMBOL,
        )

        assert result["order_id"] == "12881"
        assert result["status"] == "open"
        assert result["limit_price"] == 10.0

    def test_calls_preview_before_place(self):
        client = _make_client()
        self._setup_preview_and_place(client)

        client.place_option_order(
            symbol="TSLA",
            price=10.0,
            _option_symbol_override=_OCC_SYMBOL,
        )

        assert client._session.post.call_count == 2
        preview_url = client._session.post.call_args_list[0][0][0]
        place_url = client._session.post.call_args_list[1][0][0]
        assert "preview" in preview_url
        assert "place" in place_url

    def test_occ_override_extracts_correct_components(self):
        client = _make_client()
        self._setup_preview_and_place(client)

        client.place_option_order(
            symbol="TSLA",
            price=10.0,
            _option_symbol_override="TSLA231013C00240000",
        )

        preview_payload = client._session.post.call_args_list[0][1]["json"]
        instrument = (
            preview_payload["PreviewOrderRequest"]["Order"][0]["Instrument"][0]
        )
        product = instrument["Product"]
        assert product["symbol"] == "TSLA"
        assert product["expiryYear"] == 2023
        assert product["expiryMonth"] == 10
        assert product["expiryDay"] == 13
        assert product["callPut"] == "CALL"
        assert product["strikePrice"] == 240

    def test_market_order_price_type(self):
        client = _make_client()
        self._setup_preview_and_place(client)

        client.place_option_order(
            symbol="TSLA",
            price_type="MARKET",
            order_action="SELL_CLOSE",
            _option_symbol_override=_OCC_SYMBOL,
        )

        preview_payload = client._session.post.call_args_list[0][1]["json"]
        assert (
            preview_payload["PreviewOrderRequest"]["Order"][0]["priceType"] == "MARKET"
        )

    def test_missing_option_key_raises(self):
        client = _make_client()
        with pytest.raises(Exception):
            client.place_option_order(symbol="TSLA", price=10.0)


class TestOrderStatus:
    def test_executed_maps_to_filled(self):
        client = _make_client()
        client._session.get.return_value = _mock_response(order_status_executed_order)

        result = client.order_status("12937")

        assert result["status"] == "filled"
        assert result["order_id"] == "12937"

    def test_open_maps_to_open(self):
        client = _make_client()
        client._session.get.return_value = _mock_response(option_order_status)

        result = client.order_status("12881")

        assert result["status"] == "open"

    def test_cancelled_maps_to_canceled(self):
        client = _make_client()
        cancelled_response = {
            "OrdersResponse": {
                "Order": [
                    {
                        "orderId": 999,
                        "orderType": "OPTN",
                        "OrderDetail": [
                            {
                                "status": "CANCELLED",
                                "limitPrice": 5.0,
                                "Instrument": [{"filledQuantity": 0.0}],
                            }
                        ],
                    }
                ]
            }
        }
        client._session.get.return_value = _mock_response(cancelled_response)

        result = client.order_status("999")

        assert result["status"] == "canceled"

    def test_filled_qty_and_avg_price_extracted(self):
        client = _make_client()
        client._session.get.return_value = _mock_response(order_status_executed_order)

        result = client.order_status("12937")

        assert result["filled_qty"] == 1.0
        assert result["filled_avg_price"] == 19.25


class TestCancelOrder:
    def test_returns_normalized_cancel_dict(self):
        client = _make_client()
        client._session.put.return_value = _mock_response({"CancelOrderResponse": {}})

        result = client.cancel_order("12881")

        assert result["order_id"] == "12881"
        assert result["status"] == "canceled"

    def test_sends_numeric_order_id_in_payload(self):
        client = _make_client()
        client._session.put.return_value = _mock_response({"CancelOrderResponse": {}})

        client.cancel_order("12881")

        payload = client._session.put.call_args[1]["json"]
        assert payload["CancelOrderRequest"]["orderId"] == 12881


class TestPlaceStockOrder:
    def _setup_preview_and_place(self, client):
        client._session.post.side_effect = [
            _mock_response(success_preview_order),
            _mock_response(success_place_trade_response),
        ]

    def test_returns_normalized_order_dict(self):
        client = _make_client()
        self._setup_preview_and_place(client)

        result = client.place_stock_order(
            symbol="TSLA",
            quantity=10,
            side="BUY",
            order_type="LIMIT",
            limit_price=169.0,
        )

        assert result["order_id"] == "12856"
        assert result["status"] == "open"
        assert result["symbol"] == "TSLA"
        assert result["quantity"] == 10.0

    def test_calls_preview_before_place(self):
        client = _make_client()
        self._setup_preview_and_place(client)

        client.place_stock_order("TSLA", 10, "BUY", "LIMIT", 169.0)

        assert client._session.post.call_count == 2
        preview_url = client._session.post.call_args_list[0][0][0]
        place_url = client._session.post.call_args_list[1][0][0]
        assert "preview" in preview_url
        assert "place" in place_url

    def test_limit_price_in_preview_payload(self):
        client = _make_client()
        self._setup_preview_and_place(client)

        client.place_stock_order("TSLA", 10, "BUY", "LIMIT", 169.0)

        preview_payload = client._session.post.call_args_list[0][1]["json"]
        assert preview_payload["PreviewOrderRequest"]["Order"][0]["limitPrice"] == 169.0

    def test_missing_limit_price_for_limit_order_raises(self):
        client = _make_client()
        with pytest.raises(Exception):
            client.place_stock_order("TSLA", 10, order_type="LIMIT")

    def test_market_order_sends_market_price_type(self):
        client = _make_client()
        self._setup_preview_and_place(client)

        client.place_stock_order("TSLA", 10, "SELL", "MARKET")

        preview_payload = client._session.post.call_args_list[0][1]["json"]
        assert preview_payload["PreviewOrderRequest"]["Order"][0]["priceType"] == "MARKET"


@pytest.mark.etrade
@pytest.mark.credentials
@pytest.mark.integration
def test_get_stock_quote_integration():
    client = EtradeAPIClient(selected_account_id=None, is_sandbox_enabled=True)
    client.authorize_session()
    result = client.get_stock_quote("TSLA")
    assert result["QuoteResponse"] is not None


@pytest.mark.etrade
@pytest.mark.credentials
@pytest.mark.integration
def test_get_accounts_integration():
    client = EtradeAPIClient(is_sandbox_enabled=True)
    client.authorize_session()
    result = client.get_accounts()
    assert "buying_power" in result

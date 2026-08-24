from datetime import date

import pytest

from alpha_tech_tracker.trade_api.alpaca_client.client import (
    AlpacaAPIClient,
    ClientError,
    main_monthly_expiry,
)


class TestMainMonthlyExpiry:
    def test_returns_third_friday_of_current_month_when_still_ahead(self):
        assert main_monthly_expiry(date(2026, 8, 1)) == date(2026, 8, 21)

    def test_returns_third_friday_when_reference_is_expiry_day(self):
        assert main_monthly_expiry(date(2026, 8, 21)) == date(2026, 8, 21)

    def test_rolls_to_next_month_after_third_friday_passed(self):
        assert main_monthly_expiry(date(2026, 8, 22)) == date(2026, 9, 18)

    def test_rolls_across_year_boundary_in_december(self):
        assert main_monthly_expiry(date(2026, 12, 25)) == date(2027, 1, 15)


def _contract(strike, option_type, open_interest, oi_date="2026-08-20"):
    return {
        "symbol": f"AAPL260918{option_type[0].upper()}{int(strike * 1000):08d}",
        "underlying_symbol": "AAPL",
        "expiration_date": "2026-09-18",
        "strike_price": strike,
        "option_type": option_type,
        "contract_size": "100",
        "open_interest": open_interest,
        "open_interest_date": oi_date,
    }


def _chain(strikes):
    return [
        _contract(strike, option_type, open_interest)
        for strike, calls, puts in strikes
        for option_type, open_interest in (("call", calls), ("put", puts))
    ]


@pytest.fixture
def client(mocker):
    mocker.patch(
        "alpha_tech_tracker.trade_api.alpaca_client.client.TradingClient"
    )
    mocker.patch(
        "alpha_tech_tracker.trade_api.alpaca_client.client.StockHistoricalDataClient"
    )
    mocker.patch(
        "alpha_tech_tracker.trade_api.alpaca_client.client.OptionHistoricalDataClient"
    )
    return AlpacaAPIClient(api_key="key", secret_key="secret")


class TestGetOptionsOpenInterest:
    def test_aggregates_calls_and_puts_across_selected_strikes(self, client, mocker):
        mocker.patch.object(
            client,
            "get_options_contracts",
            return_value=_chain([(100.0, 10, 1), (105.0, 20, 2), (110.0, 30, 3)]),
        )

        result = client.get_options_open_interest(
            "AAPL", expiration_date=date(2026, 9, 18), reference_price=105.0
        )

        assert result["call_open_interest"] == 60
        assert result["put_open_interest"] == 6
        assert result["total_open_interest"] == 66

    def test_picks_strike_nearest_to_reference_price_as_atm(self, client, mocker):
        mocker.patch.object(
            client,
            "get_options_contracts",
            return_value=_chain([(100.0, 1, 1), (105.0, 1, 1), (110.0, 1, 1)]),
        )

        result = client.get_options_open_interest(
            "AAPL", expiration_date=date(2026, 9, 18), reference_price=106.4
        )

        assert result["atm_strike"] == 105.0

    def test_limits_strikes_to_requested_band_around_atm(self, client, mocker):
        mocker.patch.object(
            client,
            "get_options_contracts",
            return_value=_chain([(float(strike), 1, 1) for strike in range(90, 121, 5)]),
        )

        result = client.get_options_open_interest(
            "AAPL",
            expiration_date=date(2026, 9, 18),
            reference_price=105.0,
            strikes_around_atm=1,
        )

        assert [row["strike_price"] for row in result["by_strike"]] == [100.0, 105.0, 110.0]

    def test_includes_whole_chain_when_band_is_none(self, client, mocker):
        mocker.patch.object(
            client,
            "get_options_contracts",
            return_value=_chain([(float(strike), 1, 1) for strike in range(90, 121, 5)]),
        )

        result = client.get_options_open_interest(
            "AAPL",
            expiration_date=date(2026, 9, 18),
            reference_price=105.0,
            strikes_around_atm=None,
        )

        assert result["strike_count"] == 7

    def test_defaults_expiration_to_main_monthly_expiry(self, client, mocker):
        fetch = mocker.patch.object(
            client, "get_options_contracts", return_value=_chain([(100.0, 1, 1)])
        )
        mocker.patch(
            "alpha_tech_tracker.trade_api.alpaca_client.client.main_monthly_expiry",
            return_value=date(2026, 9, 18),
        )

        client.get_options_open_interest("AAPL", reference_price=100.0)

        assert fetch.call_args.kwargs["expiration_date"] == date(2026, 9, 18)

    def test_derives_reference_price_from_quote_mid_when_not_given(self, client, mocker):
        mocker.patch.object(
            client,
            "get_options_contracts",
            return_value=_chain([(100.0, 1, 1), (105.0, 1, 1)]),
        )
        mocker.patch.object(client, "get_stock_quote", return_value={})
        mocker.patch.object(client, "_extract_bid_ask", return_value=(104.0, 106.0))

        result = client.get_options_open_interest("AAPL")

        assert result["reference_price"] == 105.0

    def test_computes_put_call_ratio(self, client, mocker):
        mocker.patch.object(
            client, "get_options_contracts", return_value=_chain([(100.0, 40, 10)])
        )

        result = client.get_options_open_interest("AAPL", reference_price=100.0)

        assert result["put_call_ratio"] == 0.25

    def test_computes_call_put_ratio(self, client, mocker):
        mocker.patch.object(
            client, "get_options_contracts", return_value=_chain([(100.0, 40, 10)])
        )

        result = client.get_options_open_interest("AAPL", reference_price=100.0)

        assert result["call_put_ratio"] == 4.0

    def test_call_put_ratio_is_none_without_put_open_interest(self, client, mocker):
        mocker.patch.object(
            client, "get_options_contracts", return_value=_chain([(100.0, 40, 0)])
        )

        result = client.get_options_open_interest("AAPL", reference_price=100.0)

        assert result["call_put_ratio"] is None

    def test_put_call_ratio_is_none_without_call_open_interest(self, client, mocker):
        mocker.patch.object(
            client, "get_options_contracts", return_value=_chain([(100.0, 0, 10)])
        )

        result = client.get_options_open_interest("AAPL", reference_price=100.0)

        assert result["put_call_ratio"] is None

    def test_treats_missing_open_interest_as_zero(self, client, mocker):
        mocker.patch.object(
            client,
            "get_options_contracts",
            return_value=[_contract(100.0, "call", None), _contract(100.0, "put", 5)],
        )

        result = client.get_options_open_interest("AAPL", reference_price=100.0)

        assert result["call_open_interest"] == 0

    def test_reports_latest_open_interest_date(self, client, mocker):
        mocker.patch.object(
            client,
            "get_options_contracts",
            return_value=[
                _contract(100.0, "call", 5, oi_date="2026-08-19"),
                _contract(100.0, "put", 5, oi_date="2026-08-20"),
            ],
        )

        result = client.get_options_open_interest("AAPL", reference_price=100.0)

        assert result["open_interest_date"] == "2026-08-20"

    def test_raises_when_no_contracts_returned(self, client, mocker):
        mocker.patch.object(client, "get_options_contracts", return_value=[])

        with pytest.raises(ClientError):
            client.get_options_open_interest("AAPL", reference_price=100.0)

    def test_requests_all_pages_of_the_chain(self, client, mocker):
        fetch = mocker.patch.object(
            client, "get_options_contracts", return_value=_chain([(100.0, 1, 1)])
        )

        client.get_options_open_interest("AAPL", reference_price=100.0)

        assert fetch.call_args.kwargs["fetch_all_pages"] is True


class TestGetOptionsContracts:
    def test_exposes_open_interest_fields(self, client, mocker):
        contract = mocker.MagicMock(
            symbol="AAPL260918C00300000",
            underlying_symbol="AAPL",
            expiration_date=date(2026, 9, 18),
            strike_price=300.0,
            size="100",
            open_interest="27400",
            open_interest_date=date(2026, 8, 20),
        )
        client._trading_client.get_option_contracts.return_value = mocker.MagicMock(
            option_contracts=[contract], next_page_token=None
        )

        result = client.get_options_contracts("AAPL")

        assert result[0]["open_interest"] == 27400
        assert result[0]["open_interest_date"] == "2026-08-20"

    def test_returns_none_open_interest_when_broker_omits_it(self, client, mocker):
        contract = mocker.MagicMock(
            symbol="AAPL260918C00300000",
            underlying_symbol="AAPL",
            expiration_date=date(2026, 9, 18),
            strike_price=300.0,
            size="100",
            open_interest=None,
            open_interest_date=None,
        )
        client._trading_client.get_option_contracts.return_value = mocker.MagicMock(
            option_contracts=[contract], next_page_token=None
        )

        result = client.get_options_contracts("AAPL")

        assert result[0]["open_interest"] is None

    def test_follows_next_page_token_when_fetching_all_pages(self, client, mocker):
        def make_contract(symbol):
            return mocker.MagicMock(
                symbol=symbol,
                underlying_symbol="AAPL",
                expiration_date=date(2026, 9, 18),
                strike_price=300.0,
                size="100",
                open_interest="1",
                open_interest_date=date(2026, 8, 20),
            )

        client._trading_client.get_option_contracts.side_effect = [
            mocker.MagicMock(
                option_contracts=[make_contract("A")], next_page_token="token-2"
            ),
            mocker.MagicMock(option_contracts=[make_contract("B")], next_page_token=None),
        ]

        result = client.get_options_contracts("AAPL", fetch_all_pages=True)

        assert [row["symbol"] for row in result] == ["A", "B"]

    def test_stops_after_first_page_by_default(self, client, mocker):
        contract = mocker.MagicMock(
            symbol="A",
            underlying_symbol="AAPL",
            expiration_date=date(2026, 9, 18),
            strike_price=300.0,
            size="100",
            open_interest="1",
            open_interest_date=date(2026, 8, 20),
        )
        client._trading_client.get_option_contracts.return_value = mocker.MagicMock(
            option_contracts=[contract], next_page_token="token-2"
        )

        client.get_options_contracts("AAPL")

        assert client._trading_client.get_option_contracts.call_count == 1

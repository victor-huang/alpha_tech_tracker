import pytest

from alpha_tech_tracker.trade_api.alpaca_client.client import AlpacaAPIClient


@pytest.mark.alpaca
@pytest.mark.credentials
def test_get_accounts():
    client = AlpacaAPIClient(is_paper_trading=True)
    account_info = client.get_accounts()

    assert account_info is not None
    assert "account_id" in account_info
    assert "buying_power" in account_info
    assert "portfolio_value" in account_info


@pytest.mark.alpaca
@pytest.mark.credentials
def test_get_stock_quote():
    client = AlpacaAPIClient(is_paper_trading=True)
    quote_response = client.get_stock_quote("TSLA")

    assert quote_response["QuoteResponse"] is not None
    assert quote_response["QuoteResponse"]["QuoteData"] is not None
    assert "bid" in quote_response["QuoteResponse"]["QuoteData"][0]["All"]
    assert "ask" in quote_response["QuoteResponse"]["QuoteData"][0]["All"]


@pytest.mark.alpaca
@pytest.mark.credentials
def test_get_multiple_stock_quotes():
    client = AlpacaAPIClient(is_paper_trading=True)
    quotes = client.get_stock_quote(["TSLA", "AAPL"])

    assert "TSLA" in quotes
    assert "AAPL" in quotes
    assert quotes["TSLA"]["QuoteResponse"] is not None
    assert quotes["AAPL"]["QuoteResponse"] is not None


@pytest.mark.alpaca
@pytest.mark.credentials
def test_get_option_quote():
    client = AlpacaAPIClient(is_paper_trading=True)

    try:
        contracts = client.get_options_contracts(
            underlying_symbol="TSLA", option_type="call", limit=1
        )

        if len(contracts) == 0:
            pytest.skip("No option contracts available")

        expiration = contracts[0]["expiration_date"]
        strike = contracts[0]["strike_price"]
        option_key = f"{expiration} s{strike}"

        quote_response = client.get_option_quote(
            symbol="TSLA", option_key=option_key, option_type="CALL"
        )

        assert quote_response["QuoteResponse"] is not None
        assert quote_response["QuoteResponse"]["QuoteData"] is not None
        assert "bid" in quote_response["QuoteResponse"]["QuoteData"][0]["All"]
        assert "ask" in quote_response["QuoteResponse"]["QuoteData"][0]["All"]
    except Exception as e:
        if "400" in str(e) or "subscription" in str(e).lower():
            pytest.skip(
                f"Options data not available (may require subscription): {str(e)}"
            )
        raise


@pytest.mark.alpaca
@pytest.mark.credentials
def test_get_price_from_quote():
    client = AlpacaAPIClient(is_paper_trading=True)
    quote = client.get_stock_quote("TSLA")
    price_info = client.get_price_from_quote(quote)

    assert "bid" in price_info
    assert "ask" in price_info
    assert "mid" in price_info
    assert "s-mid" in price_info
    assert price_info["bid"] < price_info["ask"]


@pytest.mark.alpaca
@pytest.mark.credentials
def test_get_options_contracts():
    client = AlpacaAPIClient(is_paper_trading=True)
    contracts = client.get_options_contracts(
        underlying_symbol="TSLA", option_type="call", limit=5
    )

    assert contracts is not None
    assert len(contracts) > 0
    assert "symbol" in contracts[0]
    assert "underlying_symbol" in contracts[0]
    assert "strike_price" in contracts[0]
    assert contracts[0]["underlying_symbol"] == "TSLA"


@pytest.mark.alpaca
@pytest.mark.credentials
def test_place_stock_order():
    client = AlpacaAPIClient(is_paper_trading=True)

    order = client.place_stock_order(
        symbol="TSLA", quantity=1, side="BUY", order_type="LIMIT", limit_price=1.00
    )

    assert order is not None
    assert "order_id" in order
    assert order["symbol"] == "TSLA"
    assert order["quantity"] == 1
    assert order["side"] == "buy"

    client.cancel_order(order["order_id"])


@pytest.mark.alpaca
@pytest.mark.credentials
def test_place_option_order():
    client = AlpacaAPIClient(is_paper_trading=True)

    try:
        contracts = client.get_options_contracts(
            underlying_symbol="TSLA", option_type="call", limit=1
        )

        if len(contracts) == 0:
            pytest.skip("No option contracts available")

        contract_symbol = contracts[0]["symbol"]
        expiration = contracts[0]["expiration_date"]
        strike = contracts[0]["strike_price"]

        option_key = f"{expiration} s{strike}"

        order = client.place_option_order(
            symbol="TSLA",
            option_key=option_key,
            price=0.10,
            option_type="CALL",
            order_action="BUY_OPEN",
            quantity=1,
        )

        assert order is not None
        assert "order_id" in order
        assert order["quantity"] == 1

        client.cancel_order(order["order_id"])
    except Exception as e:
        if "not found" in str(e).lower() or "42210000" in str(e):
            pytest.skip(f"Options trading not available in paper account: {str(e)}")
        raise


@pytest.mark.alpaca
@pytest.mark.credentials
def test_order_status():
    client = AlpacaAPIClient(is_paper_trading=True)

    order = client.place_stock_order(
        symbol="TSLA", quantity=1, side="BUY", order_type="LIMIT", limit_price=1.00
    )

    order_id = order["order_id"]
    status = client.order_status(order_id)

    assert status is not None
    assert status["order_id"] == order_id
    assert "status" in status
    assert status["symbol"] == "TSLA"

    client.cancel_order(order_id)


@pytest.mark.alpaca
@pytest.mark.credentials
def test_cancel_order():
    client = AlpacaAPIClient(is_paper_trading=True)

    order = client.place_stock_order(
        symbol="TSLA", quantity=1, side="BUY", order_type="LIMIT", limit_price=1.00
    )

    order_id = order["order_id"]
    cancel_result = client.cancel_order(order_id)

    assert cancel_result is not None
    assert cancel_result["order_id"] == order_id
    assert cancel_result["status"] == "cancelled"

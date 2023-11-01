from alpha_tech_tracker.trade_api.etrade.client import EtradeAPIClient


# integration test
def test_get_stock_quote():
    account_id = None
    client = EtradeAPIClient(selected_account_id=account_id)
    client.authorize_session()
    quote_response = client.get_stock_quote("TSLA")

    assert quote_response["QuoteResponse"] != None
    assert "TSLA" in str(quote_response["QuoteResponse"])

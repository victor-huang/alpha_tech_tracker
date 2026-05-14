from datetime import date
from unittest.mock import MagicMock, call

from alpha_tech_tracker.op_momentum_strategy.fetch_ts_orders import _fetch_all_orders

_BASE_URL = "https://api.tradestation.com/v3"
_ACCOUNT = "12345"
_HISTORICAL_URL = f"{_BASE_URL}/brokerage/accounts/{_ACCOUNT}/historicalorders"
_ORDERS_URL = f"{_BASE_URL}/brokerage/accounts/{_ACCOUNT}/orders"


def _make_client(*responses):
    client = MagicMock()
    client._get_account_key.return_value = _ACCOUNT
    client._v3_base_url = _BASE_URL
    client._session.get.side_effect = list(responses)
    return client


def _resp(status_code, data):
    r = MagicMock()
    r.status_code = status_code
    r.json.return_value = data
    return r


class TestFetchAllOrders:

    def test_returns_historical_orders_when_available(self):
        orders = [{"OrderID": "1"}, {"OrderID": "2"}]
        client = _make_client(_resp(200, {"Orders": orders}))

        result = _fetch_all_orders(client, date(2026, 5, 12))

        assert result == orders
        assert client._session.get.call_count == 1
        assert client._session.get.call_args[0][0] == _HISTORICAL_URL

    def test_falls_back_to_orders_on_404(self):
        orders = [{"OrderID": "3"}]
        client = _make_client(
            _resp(404, {}),
            _resp(200, {"Orders": orders}),
        )

        result = _fetch_all_orders(client, date(2026, 5, 13))

        assert result == orders
        assert client._session.get.call_count == 2
        assert client._session.get.call_args_list[1][0][0] == _ORDERS_URL

    def test_falls_back_to_orders_when_historical_returns_empty_dict(self):
        orders = [{"OrderID": "4"}]
        client = _make_client(
            _resp(200, {"Orders": []}),
            _resp(200, {"Orders": orders}),
        )

        result = _fetch_all_orders(client, date(2026, 5, 13))

        assert result == orders
        assert client._session.get.call_count == 2
        assert client._session.get.call_args_list[1][0][0] == _ORDERS_URL

    def test_falls_back_to_orders_when_historical_returns_bare_empty_list(self):
        orders = [{"OrderID": "5"}]
        client = _make_client(
            _resp(200, []),
            _resp(200, {"Orders": orders}),
        )

        result = _fetch_all_orders(client, date(2026, 5, 13))

        assert result == orders
        assert client._session.get.call_count == 2
        assert client._session.get.call_args_list[1][0][0] == _ORDERS_URL

    def test_does_not_call_orders_when_historical_returns_results(self):
        orders = [{"OrderID": "6"}]
        client = _make_client(_resp(200, {"Orders": orders}))

        _fetch_all_orders(client, date(2026, 5, 13))

        assert client._session.get.call_count == 1

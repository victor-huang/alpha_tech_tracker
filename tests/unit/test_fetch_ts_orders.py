from datetime import date, datetime, timezone
from unittest.mock import MagicMock, call

from alpha_tech_tracker.op_momentum_strategy.fetch_ts_orders import (
    _fetch_all_orders,
    _parse_quotes_from_log,
)

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


_SYM = "CRDO260605C00190000"
_ORDER_ID = "ord-001"
_FILL_TIME = datetime(2026, 6, 4, 17, 22, 48, tzinfo=timezone.utc)


def _make_record(fill_time=_FILL_TIME, symbol=_SYM, order_id=_ORDER_ID):
    return {"symbol": symbol, "fill_time": fill_time, "order_id": order_id}


def _log_line(ts, step, side, symbol, bid, ask, mid, fair):
    return (
        f"{ts} INFO module — FILL_ESC loop step{step} {side} {symbol}: "
        f"bid={bid} ask={ask} mid={mid} fair={fair} → limit at {mid}\n"
    )


def _floor_line(ts, step, side, symbol, bid, fair):
    return (
        f"{ts} WARNING module — FILL_ESC step{step} {side} {symbol}: "
        f"bid={bid} is below fair_price={fair} — flooring at fair_price\n"
    )


class TestParseQuotesFromLog:

    def test_step1_fill_returns_correct_quote_and_step(self, tmp_path):
        log = tmp_path / "trade.log"
        log.write_text(
            _log_line("2026-06-04 17:22:30", 1, "SELL_CLOSE", _SYM, 31.1, 32.7, 31.9, 32.5)
        )

        result = _parse_quotes_from_log(str(log), [_make_record()])

        assert result[_ORDER_ID]["opt_log_step"] == 1
        assert result[_ORDER_ID]["opt_log_bid"] == 31.1
        assert result[_ORDER_ID]["opt_log_ask"] == 32.7
        assert result[_ORDER_ID]["opt_log_mid"] == 31.9
        assert result[_ORDER_ID]["opt_log_fair"] == 32.5

    def test_step2_fill_returns_step_2(self, tmp_path):
        log = tmp_path / "trade.log"
        log.write_text(
            _log_line("2026-06-04 17:22:20", 1, "SELL_CLOSE", _SYM, 31.1, 32.7, 31.9, 32.5)
            + _log_line("2026-06-04 17:22:30", 2, "SELL_CLOSE", _SYM, 31.0, 32.6, 31.8, 32.1)
        )

        result = _parse_quotes_from_log(str(log), [_make_record()])

        assert result[_ORDER_ID]["opt_log_step"] == 2
        assert result[_ORDER_ID]["opt_log_bid"] == 31.0

    def test_step3_floor_patches_step_to_3(self, tmp_path):
        log = tmp_path / "trade.log"
        log.write_text(
            _log_line("2026-06-04 17:22:30", 1, "SELL_CLOSE", _SYM, 31.1, 32.7, 31.9, 32.5)
            + _floor_line("2026-06-04 17:22:40", 3, "SELL_CLOSE", _SYM, 31.2, 32.6)
        )

        result = _parse_quotes_from_log(str(log), [_make_record()])

        assert result[_ORDER_ID]["opt_log_step"] == 3
        assert result[_ORDER_ID]["opt_log_bid"] == 31.1
        assert result[_ORDER_ID]["opt_log_ask"] == 32.7

    def test_step3_floor_on_retry_uses_most_recent_quote(self, tmp_path):
        # First attempt: step1 → step3 floor → MISS (no fill)
        # Retry: step1 → step2 → step3 floor → filled at 17:22:48
        log = tmp_path / "trade.log"
        log.write_text(
            _log_line("2026-06-04 17:21:09", 1, "SELL_CLOSE", _SYM, 31.1, 32.7, 31.9, 32.5)
            + _floor_line("2026-06-04 17:21:19", 3, "SELL_CLOSE", _SYM, 31.2, 32.6)
            + _log_line("2026-06-04 17:22:22", 1, "SELL_CLOSE", _SYM, 31.3, 34.0, 32.65, 31.9)
            + _log_line("2026-06-04 17:22:33", 2, "SELL_CLOSE", _SYM, 31.1, 32.7, 31.9, 32.1)
            + _floor_line("2026-06-04 17:22:41", 3, "SELL_CLOSE", _SYM, 31.1, 32.1)
        )

        result = _parse_quotes_from_log(str(log), [_make_record()])

        # Most recent entry (retry step2 line) patched to step3
        assert result[_ORDER_ID]["opt_log_step"] == 3
        assert result[_ORDER_ID]["opt_log_bid"] == 31.1
        assert result[_ORDER_ID]["opt_log_ask"] == 32.7
        assert result[_ORDER_ID]["opt_log_mid"] == 31.9
        assert result[_ORDER_ID]["opt_log_fair"] == 32.1

    def test_step3_floor_without_prior_quote_is_ignored(self, tmp_path):
        log = tmp_path / "trade.log"
        log.write_text(
            _floor_line("2026-06-04 17:22:40", 3, "SELL_CLOSE", _SYM, 31.2, 32.6)
        )

        result = _parse_quotes_from_log(str(log), [_make_record()])

        assert result == {}

    def test_no_matching_lines_returns_empty(self, tmp_path):
        log = tmp_path / "trade.log"
        log.write_text("2026-06-04 17:22:30 INFO module — unrelated log line\n")

        result = _parse_quotes_from_log(str(log), [_make_record()])

        assert result == {}

    def test_fill_outside_5min_window_not_matched(self, tmp_path):
        log = tmp_path / "trade.log"
        # Log entry is 6 minutes before fill — outside the 300s lookback
        log.write_text(
            _log_line("2026-06-04 17:16:40", 1, "SELL_CLOSE", _SYM, 31.1, 32.7, 31.9, 32.5)
        )

        result = _parse_quotes_from_log(str(log), [_make_record()])

        assert result == {}

    def test_buy_open_entry_matched(self, tmp_path):
        log = tmp_path / "trade.log"
        fill_time = datetime(2026, 6, 4, 17, 6, 12, tzinfo=timezone.utc)
        log.write_text(
            _log_line("2026-06-04 17:06:10", 1, "BUY_OPEN", _SYM, 33.2, 37.2, 35.2, 35.3)
        )

        result = _parse_quotes_from_log(str(log), [_make_record(fill_time=fill_time)])

        assert result[_ORDER_ID]["opt_log_step"] == 1
        assert result[_ORDER_ID]["opt_log_spread_pct"] == round((37.2 - 33.2) / 35.2 * 100, 2)

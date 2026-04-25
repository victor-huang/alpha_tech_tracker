import functools
import logging
import os
import random
import string

from alpaca.trading.client import TradingClient
from alpaca.data.historical import StockHistoricalDataClient, OptionHistoricalDataClient
from alpaca.trading.requests import (
    MarketOrderRequest,
    LimitOrderRequest,
    GetOptionContractsRequest,
)
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.data.enums import DataFeed
from alpaca.data.requests import StockLatestQuoteRequest, OptionLatestQuoteRequest, OptionLatestTradeRequest

from alpha_tech_tracker.trade_api.execution_client import ExecutionClient, InsufficientFundsError

logger = logging.getLogger("trade_api.alpaca")


class APIError(Exception):
    def __init__(self, code, message):
        self.code = code
        self.message = message
        super().__init__(message)


class APIInvalidArgumentError(APIError):
    pass


class ClientError(Exception):
    pass


class AlpacaAPIClient(ExecutionClient):
    def __init__(
        self,
        api_key=None,
        secret_key=None,
        is_paper_trading=True,
        selected_account_id=None,
    ):
        self._api_key = api_key or os.environ.get("ALPACA_API_KEY")
        self._secret_key = secret_key or os.environ.get("ALPACA_SECRET_KEY")
        self._is_paper_trading = is_paper_trading
        self._selected_account_id = selected_account_id

        self._trading_client = TradingClient(
            self._api_key, self._secret_key, paper=is_paper_trading
        )
        self._stock_data_client = StockHistoricalDataClient(
            self._api_key, self._secret_key
        )
        self._option_data_client = OptionHistoricalDataClient(
            self._api_key, self._secret_key
        )
        self._apply_request_timeout(timeout=30)

    def _apply_request_timeout(self, timeout: int):
        """Patch every SDK client's requests.Session to enforce a hard timeout.

        alpaca-py passes no timeout to requests, so a hung API server will block
        a thread forever. This wraps Session.request on each internal client so
        that every HTTP call raises requests.exceptions.Timeout after `timeout`
        seconds rather than hanging indefinitely.
        """
        for sdk_client in (
            self._trading_client,
            self._stock_data_client,
            self._option_data_client,
        ):
            session = getattr(sdk_client, "_session", None)
            if session is None:
                continue
            original_request = session.request
            session.request = functools.partial(
                lambda orig, *a, **kw: orig(*a, **{**kw, "timeout": kw.get("timeout", timeout)}),
                original_request,
            )

    def _generate_order_id(self, length=8):
        chars = string.ascii_letters + string.digits
        return "".join(random.choice(chars) for _ in range(length))

    def _parse_option_key(self, option_key):
        expiry_year, expiry_month, remaining = option_key.split("-")
        expiry_day, strike_price = remaining.split()
        strike_price = strike_price[1:]

        return [expiry_year, expiry_month, expiry_day, strike_price]

    def _build_option_symbol(self, symbol, option_key, option_type="CALL"):
        expiry_year, expiry_month, expiry_day, strike_price = self._parse_option_key(
            option_key
        )

        option_type_code = "C" if option_type == "CALL" else "P"
        strike_price_formatted = f"{float(strike_price):09.3f}".replace(".", "")

        option_symbol = (
            f"{symbol}{expiry_year[2:]}{expiry_month}{expiry_day}"
            f"{option_type_code}{strike_price_formatted}"
        )

        return option_symbol

    def round_nearest(self, x, smallest_unit):
        return round(x / smallest_unit) * smallest_unit

    def get_accounts(self):
        account = self._trading_client.get_account()
        return {
            "account_id": account.account_number,
            "account_type": account.account_blocked,
            "cash": float(account.cash),
            "buying_power": float(account.buying_power),
            "portfolio_value": float(account.portfolio_value),
            "equity": float(account.equity),
            "raw_response": account,
        }

    def get_stock_quote(self, symbols, feed: DataFeed = DataFeed.IEX):
        if isinstance(symbols, str):
            symbols = [symbols]

        request_params = StockLatestQuoteRequest(symbol_or_symbols=symbols, feed=feed)
        quotes = self._stock_data_client.get_stock_latest_quote(request_params)

        formatted_quotes = {}
        for symbol, quote_data in quotes.items():
            formatted_quotes[symbol] = {
                "QuoteResponse": {
                    "QuoteData": [
                        {
                            "All": {
                                "bid": float(quote_data.bid_price),
                                "ask": float(quote_data.ask_price),
                                "bid_size": quote_data.bid_size,
                                "ask_size": quote_data.ask_size,
                                "last": None,
                            }
                        }
                    ]
                }
            }

        if len(symbols) == 1:
            return formatted_quotes[symbols[0]]

        return formatted_quotes

    def get_option_quote(self, symbol, option_key, option_type="CALL"):
        option_symbol = self._build_option_symbol(symbol, option_key, option_type)

        request_params = OptionLatestQuoteRequest(symbol_or_symbols=[option_symbol])
        quotes = self._option_data_client.get_option_latest_quote(request_params)

        quote_data = quotes[option_symbol]
        formatted_quote = {
            "QuoteResponse": {
                "QuoteData": [
                    {
                        "All": {
                            "bid": float(quote_data.bid_price),
                            "ask": float(quote_data.ask_price),
                            "bid_size": quote_data.bid_size,
                            "ask_size": quote_data.ask_size,
                        }
                    }
                ]
            }
        }

        return formatted_quote

    def get_option_quote_by_occ(self, occ_symbol: str) -> dict:
        request_params = OptionLatestQuoteRequest(symbol_or_symbols=[occ_symbol])
        quotes = self._option_data_client.get_option_latest_quote(request_params)
        q = quotes[occ_symbol]
        bid = float(q.bid_price)
        ask = float(q.ask_price)
        mid = (bid + ask) / 2
        return {"bid": bid, "ask": ask, "mid": mid}

    def get_option_latest_trade_by_occ(self, occ_symbol: str):
        request_params = OptionLatestTradeRequest(symbol_or_symbols=[occ_symbol])
        trades = self._option_data_client.get_option_latest_trade(request_params)
        t = trades.get(occ_symbol)
        if t is None:
            return None
        return {"price": float(t.price), "timestamp": t.timestamp}

    def get_option_quotes_by_occ_batch(self, occ_symbols: list) -> dict:
        request_params = OptionLatestQuoteRequest(symbol_or_symbols=occ_symbols)
        quotes = self._option_data_client.get_option_latest_quote(request_params)
        result = {}
        for sym, q in quotes.items():
            bid = float(q.bid_price)
            ask = float(q.ask_price)
            mid = (bid + ask) / 2
            result[sym] = {"bid": bid, "ask": ask, "mid": mid}
        return result

    def get_price_from_quote(
        self, quote, percentage_deviate_from_mid_point=-0.1, smallest_unit=0.05
    ):
        decimal_place = 2
        bid = quote["QuoteResponse"]["QuoteData"][0]["All"]["bid"]
        ask = quote["QuoteResponse"]["QuoteData"][0]["All"]["ask"]
        mid_price_diff = (ask - bid) / 2
        mid_price = bid + mid_price_diff

        selected_price = self.round_nearest(
            bid + mid_price_diff * (1 + percentage_deviate_from_mid_point),
            smallest_unit,
        )
        selected_price = round(selected_price, decimal_place)

        print(
            f"Price, Bid: {bid}, Ask: {ask}, Mid: {mid_price}, SMid: {selected_price}"
        )

        return {
            "bid": bid,
            "ask": ask,
            "mid": mid_price,
            "s-mid": selected_price,
        }

    def get_options_contracts(
        self,
        underlying_symbol,
        expiration_date=None,
        expiration_date_gte=None,
        expiration_date_lte=None,
        option_type=None,
        strike_price_gte=None,
        strike_price_lte=None,
        limit=100,
    ):
        request = GetOptionContractsRequest(
            underlying_symbols=[underlying_symbol],
            expiration_date=expiration_date,
            expiration_date_gte=expiration_date_gte,
            expiration_date_lte=expiration_date_lte,
            type=option_type,
            strike_price_gte=strike_price_gte,
            strike_price_lte=strike_price_lte,
            limit=limit,
        )
        response = self._trading_client.get_option_contracts(request)
        contracts = (
            response.option_contracts
            if hasattr(response, "option_contracts")
            else response
        )

        return [
            {
                "symbol": contract.symbol,
                "underlying_symbol": contract.underlying_symbol,
                "expiration_date": str(contract.expiration_date),
                "strike_price": float(contract.strike_price),
                "option_type": contract.type,
                "contract_size": contract.size,
            }
            for contract in contracts
        ]

    def place_stock_order(
        self,
        symbol,
        quantity,
        side="BUY",
        order_type="MARKET",
        limit_price=None,
        time_in_force="DAY",
    ):
        order_side = OrderSide.BUY if side.upper() == "BUY" else OrderSide.SELL
        tif = getattr(TimeInForce, time_in_force.upper())

        if order_type.upper() == "MARKET":
            order_data = MarketOrderRequest(
                symbol=symbol,
                qty=quantity,
                side=order_side,
                time_in_force=tif,
            )
        elif order_type.upper() == "LIMIT":
            if limit_price is None:
                raise APIInvalidArgumentError(
                    code="MISSING_LIMIT_PRICE",
                    message="limit_price is required for LIMIT orders",
                )
            order_data = LimitOrderRequest(
                symbol=symbol,
                qty=quantity,
                side=order_side,
                time_in_force=tif,
                limit_price=limit_price,
            )
        else:
            raise APIInvalidArgumentError(
                code="INVALID_ORDER_TYPE",
                message=f"Unsupported order type: {order_type}",
            )

        try:
            order = self._trading_client.submit_order(order_data=order_data)
        except Exception as exc:
            if "40310000" in str(exc):
                raise InsufficientFundsError(str(exc)) from exc
            raise

        return {
            "order_id": str(order.id),
            "client_order_id": order.client_order_id,
            "symbol": order.symbol,
            "quantity": float(order.qty),
            "filled_qty": float(order.filled_qty) if order.filled_qty else 0,
            "side": order.side.value,
            "type": order.type.value,
            "status": order.status.value,
            "limit_price": float(order.limit_price) if order.limit_price else None,
            "filled_avg_price": (
                float(order.filled_avg_price) if order.filled_avg_price else None
            ),
            "submitted_at": order.submitted_at,
            "raw_response": order,
        }

    def place_option_order(
        self,
        symbol,
        option_key=None,
        price=None,
        order_id=None,
        preview_order=None,
        price_type="LIMIT",
        option_type="CALL",
        order_action="BUY_OPEN",
        quantity=1,
        _option_symbol_override=None,
    ):
        if _option_symbol_override:
            option_symbol = _option_symbol_override
        else:
            option_symbol = self._build_option_symbol(symbol, option_key, option_type)

        side_mapping = {
            "BUY_OPEN": "BUY",
            "BUY_CLOSE": "BUY",
            "SELL_OPEN": "SELL",
            "SELL_CLOSE": "SELL",
        }
        side = side_mapping.get(order_action, "BUY")

        if price_type.upper() == "SMART_MARKET":
            quote = self.get_option_quote(symbol, option_key, option_type=option_type)
            price_info = self.get_price_from_quote(quote)
            price = price_info["s-mid"]
            price_type = "LIMIT"

        order_side = OrderSide.BUY if side == "BUY" else OrderSide.SELL

        if price_type.upper() == "MARKET":
            order_data = MarketOrderRequest(
                symbol=option_symbol,
                qty=quantity,
                side=order_side,
                time_in_force=TimeInForce.DAY,
            )
        elif price_type.upper() == "LIMIT":
            if price is None:
                raise APIInvalidArgumentError(
                    code="MISSING_LIMIT_PRICE",
                    message="price is required for LIMIT orders",
                )
            order_data = LimitOrderRequest(
                symbol=option_symbol,
                qty=quantity,
                side=order_side,
                time_in_force=TimeInForce.DAY,
                limit_price=price,
            )
        else:
            raise APIInvalidArgumentError(
                code="INVALID_PRICE_TYPE",
                message=f"Unsupported price type: {price_type}",
            )

        try:
            order = self._trading_client.submit_order(order_data=order_data)
        except Exception as exc:
            if "40310000" in str(exc):
                raise InsufficientFundsError(str(exc)) from exc
            raise

        return {
            "order_id": str(order.id),
            "client_order_id": order.client_order_id,
            "symbol": order.symbol,
            "quantity": float(order.qty),
            "filled_qty": float(order.filled_qty) if order.filled_qty else 0,
            "side": order.side.value,
            "type": order.type.value,
            "status": order.status.value,
            "limit_price": float(order.limit_price) if order.limit_price else None,
            "filled_avg_price": (
                float(order.filled_avg_price) if order.filled_avg_price else None
            ),
            "submitted_at": order.submitted_at,
            "raw_response": order,
        }

    def get_open_positions(self) -> dict:
        positions = self._trading_client.get_all_positions()
        return {p.symbol: {"qty": float(p.qty or 0)} for p in positions}

    def get_filled_orders(self, symbol: str, limit: int = 5) -> list:
        from alpaca.trading.requests import GetOrdersRequest
        from alpaca.trading.enums import QueryOrderStatus
        request = GetOrdersRequest(symbols=[symbol], status=QueryOrderStatus.CLOSED, limit=limit)
        orders = self._trading_client.get_orders(request)
        result = []
        for o in orders:
            if o.filled_avg_price is None:
                continue
            result.append({
                "order_id": str(o.id),
                "filled_avg_price": float(o.filled_avg_price),
                "filled_qty": float(o.filled_qty) if o.filled_qty else 0.0,
                "side": o.side.value,
                "filled_at": o.filled_at,
            })
        return result

    def cancel_order(self, order_id):
        try:
            self._trading_client.cancel_order_by_id(order_id)
            return {
                "order_id": order_id,
                "status": "cancelled",
                "message": "Order cancelled successfully",
            }
        except Exception as e:
            logger.error(f"Failed to cancel order {order_id}: {e}")
            raise APIError(code="CANCEL_FAILED", message=str(e))

    def order_status(self, order_id):
        order = self._trading_client.get_order_by_id(order_id)

        return {
            "order_id": str(order.id),
            "client_order_id": order.client_order_id,
            "symbol": order.symbol,
            "quantity": float(order.qty),
            "filled_qty": float(order.filled_qty) if order.filled_qty else 0,
            "side": order.side.value,
            "type": order.type.value,
            "status": order.status.value,
            "limit_price": float(order.limit_price) if order.limit_price else None,
            "stop_price": float(order.stop_price) if order.stop_price else None,
            "filled_avg_price": (
                float(order.filled_avg_price) if order.filled_avg_price else None
            ),
            "submitted_at": order.submitted_at,
            "filled_at": order.filled_at,
            "canceled_at": order.canceled_at,
            "expired_at": order.expired_at,
            "raw_response": order,
        }


"""
Example client init
"""
#  client = AlpacaAPIClient(is_paper_trading=True)


"""
Get account information
"""
#  account_info = client.get_accounts()
#  print(account_info)


"""
Get stock quote
"""
#  quote = client.get_stock_quote("TSLA")
#  print(quote)


"""
Place stock order
"""
#  order = client.place_stock_order(
#      symbol="TSLA",
#      quantity=1,
#      side="BUY",
#      order_type="LIMIT",
#      limit_price=250.00
#  )
#  print(order)


"""
Get option contracts
"""
#  contracts = client.get_options_contracts(
#      underlying_symbol="TSLA",
#      option_type="call",
#      limit=10
#  )
#  print(contracts)


"""
Get option quote
"""
#  quote = client.get_option_quote(
#      symbol="TSLA",
#      option_key="2024-10-20 s240",
#      option_type="CALL"
#  )
#  print(quote)


"""
Place option order
"""
#  order = client.place_option_order(
#      symbol="TSLA",
#      option_key="2024-10-20 s240",
#      price=1.50,
#      option_type="CALL",
#      order_action="BUY_OPEN",
#      quantity=1
#  )
#  print(order)


"""
Check order status
"""
#  status = client.order_status(order_id="<order_id>")
#  print(status)


"""
Cancel order
"""
#  result = client.cancel_order(order_id="<order_id>")
#  print(result)

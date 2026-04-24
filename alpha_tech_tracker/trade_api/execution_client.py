from abc import ABC, abstractmethod
from typing import Optional


class InsufficientFundsError(Exception):
    """Raised by ExecutionClient implementations when the broker rejects an order
    due to insufficient buying power, account balance, or position-level quantity
    constraints (e.g. short-sale locate limits).

    order_executor catches this to abort fill escalation immediately — retrying
    the same order will never resolve an account-level funding constraint.
    """


class ExecutionClient(ABC):
    """
    Abstract interface for broker execution: account management, quotes, and order
    placement. Strategies depend only on this type. Alpaca, ETrade, and IBKR each
    provide a concrete subclass.

    Option symbols are always OCC format (e.g. "TSLA250420C00240000") at this
    interface boundary. Each concrete adapter converts to broker-native format
    internally.
    """

    @abstractmethod
    def get_accounts(self) -> dict:
        """
        Return account state.
        Required keys: buying_power (float), portfolio_value (float),
                       cash (float), account_id (str).
        """

    @abstractmethod
    def get_stock_quote(self, symbols) -> dict:
        """
        Return latest bid/ask for one or more stock symbols.
        Single symbol: returns nested dict:
          {"QuoteResponse": {"QuoteData": [{"All": {"bid": ..., "ask": ...}}]}}
        Multiple symbols: dict keyed by symbol, same inner shape.
        """

    @abstractmethod
    def get_option_quote_by_occ(self, occ_symbol: str) -> dict:
        """
        Return latest bid/ask for a single option by its OCC symbol.
        Returns: {"bid": float, "ask": float, "mid": float}
        Raises on error (caller decides fallback).
        """

    @abstractmethod
    def get_option_quotes_by_occ_batch(self, occ_symbols: list) -> dict:
        """
        Return latest bid/ask for multiple options in one call.
        Returns: {occ_symbol: {"bid": float, "ask": float, "mid": float}}
        Missing symbols are omitted from the result.
        """

    @abstractmethod
    def get_option_latest_trade_by_occ(self, occ_symbol: str) -> Optional[dict]:
        """
        Return the most recent trade for a single option by its OCC symbol.
        Returns: {"price": float, "timestamp": datetime} or None if unavailable.
        Raises on network/API error (caller decides fallback).
        """

    @abstractmethod
    def get_options_contracts(
        self,
        underlying_symbol: str,
        expiration_date=None,
        expiration_date_gte=None,
        expiration_date_lte=None,
        option_type=None,
        strike_price_gte=None,
        strike_price_lte=None,
        limit: int = 100,
    ) -> list:
        """
        Return available option contracts matching the filters.
        Each item: {symbol, underlying_symbol, expiration_date, strike_price,
                    option_type, contract_size}
        """

    @abstractmethod
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
    ) -> dict:
        """
        Place an option order.
        _option_symbol_override: pre-built OCC symbol; when provided, symbol/option_key
                                 are ignored.
        order_action: "BUY_OPEN" | "BUY_CLOSE" | "SELL_OPEN" | "SELL_CLOSE"
        price_type:   "LIMIT" | "MARKET"
        Returns: {order_id, status, filled_qty, filled_avg_price, limit_price, ...}
        """

    @abstractmethod
    def place_stock_order(
        self,
        symbol: str,
        quantity: int,
        side: str,
        order_type: str,
        limit_price: float = None,
        time_in_force: str = "DAY",
    ) -> dict:
        """
        Place a stock order.
        side: "BUY" | "SELL"
        order_type: "LIMIT" | "MARKET"
        Returns: {order_id, status, filled_qty, filled_avg_price, ...}
        """

    @abstractmethod
    def order_status(self, order_id: str) -> dict:
        """
        Return current order state.
        Required keys: order_id, status, filled_qty, filled_avg_price.
        status values: "filled" | "partially_filled" | "open" | "canceled" | "expired"
        """

    @abstractmethod
    def cancel_order(self, order_id: str) -> dict:
        """
        Cancel a pending order.
        Returns: {order_id, status: "cancelled", message}
        """

    @abstractmethod
    def get_open_positions(self) -> dict:
        """
        Return all currently open positions keyed by symbol.
        Options use OCC format (e.g. "NVDA260418C00120000").
        Stocks use the ticker symbol (e.g. "MU").
        Each value: {"qty": float}
        Returns empty dict on error.
        """

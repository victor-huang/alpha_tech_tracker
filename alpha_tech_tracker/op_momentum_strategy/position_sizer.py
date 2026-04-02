import logging
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from alpaca.data.requests import OptionLatestQuoteRequest

from alpha_tech_tracker.trade_api.alpaca_client.client import AlpacaAPIClient

from .config import ACCOUNT_BUDGET, CAPITAL_PER_SYMBOL
from .models import _D, _stock_bid_ask

logger = logging.getLogger(__name__)


class PositionSizer:
    """Computes contract quantity based on available buying power."""

    def __init__(self, alpaca_client: AlpacaAPIClient):
        self._client = alpaca_client

    def compute(
        self,
        option_symbol: str,
        capital_weight: Decimal = _D("1"),
        window_budget: Optional[Decimal] = None,
    ) -> tuple:
        if window_budget is not None:
            budget = window_budget * CAPITAL_PER_SYMBOL * capital_weight
        else:
            account = self._client.get_accounts()
            buying_power = _D(account.get("buying_power", ACCOUNT_BUDGET))
            budget = buying_power * CAPITAL_PER_SYMBOL * capital_weight

        quote_resp = self._client._option_data_client.get_option_latest_quote(
            OptionLatestQuoteRequest(symbol_or_symbols=[option_symbol])
        )
        quote = quote_resp[option_symbol]
        bid = _D(quote.bid_price)
        ask = _D(quote.ask_price)
        mid = (bid + ask) / _D("2")

        if mid <= _D("0"):
            logger.warning(
                "Mid price is zero for %s, defaulting to 1 contract", option_symbol
            )
            return 1, ask

        contracts = max(1, int(budget / (mid * _D("100"))))
        limit_price = mid.quantize(_D("0.01"), rounding=ROUND_HALF_UP)
        budget_source = "window_budget" if window_budget is not None else "account"
        logger.info(
            "%s: budget=%s (weight=%.2f, source=%s) mid=%s → %d contracts (cost=%s)",
            option_symbol,
            budget,
            float(capital_weight),
            budget_source,
            mid,
            contracts,
            contracts * mid * _D("100"),
        )
        return contracts, limit_price

    def compute_stock(
        self,
        ticker: str,
        stock_price: Decimal,
        capital_weight: Decimal = _D("1"),
        window_budget: Optional[Decimal] = None,
    ) -> tuple:
        if window_budget is not None:
            budget = window_budget * CAPITAL_PER_SYMBOL * capital_weight
        else:
            account = self._client.get_accounts()
            buying_power = _D(account.get("buying_power", ACCOUNT_BUDGET))
            budget = buying_power * CAPITAL_PER_SYMBOL * capital_weight

        raw_quote = self._client.get_stock_quote(ticker)
        bid_f, ask_f = _stock_bid_ask(raw_quote)
        bid = _D(str(bid_f)) if bid_f else _D(str(stock_price))
        ask = _D(str(ask_f)) if ask_f else _D(str(stock_price))
        mid = (bid + ask) / _D("2")
        limit_price = mid.quantize(_D("0.01"), rounding=ROUND_HALF_UP)

        if mid <= _D("0"):
            logger.warning("Mid price is zero for %s, defaulting to 1 share", ticker)
            return 1, ask

        shares = max(1, int(budget / mid))
        budget_source = "window_budget" if window_budget is not None else "account"
        logger.info(
            "%s stock: budget=%s (weight=%.2f, source=%s) mid=%s → %d shares (cost=%s)",
            ticker,
            budget,
            float(capital_weight),
            budget_source,
            mid,
            shares,
            shares * mid,
        )
        return shares, limit_price

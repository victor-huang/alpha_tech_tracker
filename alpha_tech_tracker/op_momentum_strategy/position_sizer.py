import logging
from decimal import ROUND_HALF_UP, Decimal

from alpaca.data.requests import OptionLatestQuoteRequest

from alpha_tech_tracker.trade_api.alpaca_client.client import AlpacaAPIClient

from .config import ACCOUNT_BUDGET, CAPITAL_PER_SYMBOL
from .models import _D

logger = logging.getLogger(__name__)


class PositionSizer:
    """Computes contract quantity based on available buying power."""

    def __init__(self, alpaca_client: AlpacaAPIClient):
        self._client = alpaca_client

    def compute(self, option_symbol: str, capital_weight: Decimal = _D("1")) -> tuple:
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
        logger.info(
            "%s: budget=%s (weight=%.2f) mid=%s → %d contracts (cost=%s)",
            option_symbol,
            budget,
            float(capital_weight),
            mid,
            contracts,
            contracts * mid * _D("100"),
        )
        return contracts, limit_price

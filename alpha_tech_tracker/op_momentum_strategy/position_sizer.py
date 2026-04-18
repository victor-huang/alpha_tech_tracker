import logging
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from alpha_tech_tracker.trade_api.execution_client import ExecutionClient

from .config import ACCOUNT_BUDGET, MAX_CAPITAL_PERCENTAGE_PER_SYMBOL_IN_WINDOW
from .models import _D

logger = logging.getLogger(__name__)


class PositionSizer:
    """Computes contract quantity based on available buying power."""

    def __init__(self, alpaca_client: ExecutionClient):
        self._client = alpaca_client

    def compute(
        self,
        option_symbol: str,
        capital_weight: Decimal = _D("1"),
        window_budget: Optional[Decimal] = None,
        mock_stock_price: Optional[Decimal] = None,
    ) -> tuple:
        account_buying_power = None

        if window_budget is not None:
            budget = window_budget * capital_weight
        else:
            account = self._client.get_accounts()
            account_buying_power = _D(str(account.get("buying_power", ACCOUNT_BUDGET)))
            budget = account_buying_power * MAX_CAPITAL_PERCENTAGE_PER_SYMBOL_IN_WINDOW * capital_weight

        ask = _D("0")
        if mock_stock_price is not None:
            from .mock_option_pricer import mock_entry_price
            mid = mock_entry_price(mock_stock_price, option_symbol)
        else:
            q = self._client.get_option_quote_by_occ(option_symbol)
            bid = _D(str(q["bid"]))
            ask = _D(str(q["ask"]))
            mid = _D(str(q["mid"]))

        if mid <= _D("0"):
            logger.warning(
                "Mid price is zero for %s, defaulting to 1 contract", option_symbol
            )
            return 1, ask

        contracts = max(1, int(budget / (mid * _D("100"))))
        limit_price = mid.quantize(_D("0.01"), rounding=ROUND_HALF_UP)

        if mock_stock_price is None:
            if account_buying_power is None:
                try:
                    account = self._client.get_accounts()
                    account_buying_power = _D(str(account.get("buying_power", 0)))
                except Exception:
                    logger.warning(
                        "Could not fetch buying power for %s — skipping cap check",
                        option_symbol,
                    )
            if account_buying_power is not None:
                cost_per_contract = limit_price * _D("100")
                max_by_bp = int(account_buying_power / cost_per_contract) if cost_per_contract > 0 else 0
                if max_by_bp == 0:
                    raise RuntimeError(
                        "Insufficient buying power for %s: need $%.2f/contract, have $%.2f"
                        % (option_symbol, float(cost_per_contract), float(account_buying_power))
                    )
                if max_by_bp < contracts:
                    logger.warning(
                        "%s: buying power cap: %d → %d contracts "
                        "(buying_power=%s, cost_per_contract=%s)",
                        option_symbol,
                        contracts,
                        max_by_bp,
                        account_buying_power,
                        cost_per_contract,
                    )
                    contracts = max_by_bp

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
        mock: bool = False,
    ) -> tuple:
        account_buying_power = None

        if window_budget is not None:
            budget = window_budget * capital_weight
        else:
            account = self._client.get_accounts()
            account_buying_power = _D(str(account.get("buying_power", ACCOUNT_BUDGET)))
            budget = account_buying_power * MAX_CAPITAL_PERCENTAGE_PER_SYMBOL_IN_WINDOW * capital_weight

        mid = _D(str(stock_price))
        limit_price = mid.quantize(_D("0.01"), rounding=ROUND_HALF_UP)

        if mid <= _D("0"):
            logger.warning("Mid price is zero for %s, defaulting to 1 share", ticker)
            return 1, limit_price

        shares = max(1, int(budget / mid))

        if not mock:
            if account_buying_power is None:
                try:
                    account = self._client.get_accounts()
                    account_buying_power = _D(str(account.get("buying_power", 0)))
                except Exception:
                    logger.warning(
                        "Could not fetch buying power for %s stock — skipping cap check",
                        ticker,
                    )
            if account_buying_power is not None and limit_price > 0:
                max_by_bp = int(account_buying_power / limit_price)
                if max_by_bp == 0:
                    raise RuntimeError(
                        "Insufficient buying power for %s stock: need $%.2f/share, have $%.2f"
                        % (ticker, float(limit_price), float(account_buying_power))
                    )
                if max_by_bp < shares:
                    logger.warning(
                        "%s stock: buying power cap: %d → %d shares "
                        "(buying_power=%s, price_per_share=%s)",
                        ticker,
                        shares,
                        max_by_bp,
                        account_buying_power,
                        limit_price,
                    )
                    shares = max_by_bp

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

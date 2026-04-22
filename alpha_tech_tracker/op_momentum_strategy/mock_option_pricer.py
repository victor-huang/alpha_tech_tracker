import logging
from decimal import Decimal

from .models import _D
from .option_price_monitor import _parse_occ_symbol, _quantize_option_price

logger = logging.getLogger(__name__)

_TIME_PREMIUM_RATIO = _D("0.20")  # 20% of intrinsic added as time premium
_TIME_DECAY = _D("1")              # no time decay applied (time premium fully retained at exit)


def _intrinsic(stock_price: Decimal, strike: Decimal, option_type: str) -> Decimal:
    if option_type == "call":
        return max(_D("0"), stock_price - strike)
    return max(_D("0"), strike - stock_price)


def mock_entry_price(
    stock_price: Decimal,
    option_symbol: str,
    option_type: str = "",
    time_premium_ratio: Decimal = _TIME_PREMIUM_RATIO,
) -> Decimal:
    """
    Estimate option entry price for mock/replay execution.

    Assumes the contract is deep ITM (as always produced by MockContractSelector:
    ~10% ITM call/put), so intrinsic is always positive.

    Formula:
        intrinsic = max(0, stock - strike)   # call
                  = max(0, strike - stock)   # put
        price     = intrinsic * (1 + time_premium_ratio)

    Example: stock=$100, strike=$90 call → intrinsic=$10, time_premium=$2, price=$12

    Note: option_type is derived from the OCC symbol (C/P character) and overrides
    any caller-supplied value, preventing misclassification for tickers whose names
    contain the letter C (e.g. COIN, CVNA).
    """
    parsed = _parse_occ_symbol(option_symbol)
    if not parsed:
        logger.warning("mock_entry_price: could not parse OCC symbol %s", option_symbol)
        return _D("0")

    iv = _intrinsic(stock_price, parsed["strike"], parsed["option_type"])
    if iv <= _D("0"):
        logger.error(
            "mock_entry_price: OTM contract at entry — stock=%s strike=%s %s %s; "
            "MockContractSelector should always produce ITM contracts",
            stock_price, parsed["strike"], parsed["option_type"], option_symbol,
        )
        return _D("0")

    price = iv * (1 + time_premium_ratio)
    result = _quantize_option_price(price)
    logger.debug(
        "mock_entry_price %s: stock=%s strike=%s intrinsic=%s → %s",
        option_symbol, stock_price, parsed["strike"], iv, result,
    )
    return result


def mock_exit_price(
    exit_stock_price: Decimal,
    option_symbol: str,
    option_type: str = "",
    entry_price: Decimal = _D("0"),
    entry_stock_price: Decimal = _D("0"),
    time_decay: Decimal = _TIME_DECAY,
) -> Decimal:
    """
    Estimate option exit price for mock/replay execution.

    Formula:
        exit_intrinsic    = max(0, exit_stock - strike)      # call
        entry_intrinsic   = max(0, entry_stock - strike)     # call
        entry_time_prem   = entry_price - entry_intrinsic
        exit_time_prem    = entry_time_prem * time_decay     # slight decay
        exit_price        = exit_intrinsic + exit_time_prem

    Example: entry stock=$100 → price=$12; exit stock=$102 → intrinsic=$12,
             time_prem decays $2×0.95=$1.90, exit=$13.90 (between $13-$14).

    Note: option_type is derived from the OCC symbol (C/P character) — see mock_entry_price.
    """
    parsed = _parse_occ_symbol(option_symbol)
    if not parsed:
        logger.warning("mock_exit_price: could not parse OCC symbol %s", option_symbol)
        return entry_price

    strike = parsed["strike"]
    option_type_from_symbol = parsed["option_type"]
    entry_iv = _intrinsic(entry_stock_price, strike, option_type_from_symbol)
    exit_iv = _intrinsic(exit_stock_price, strike, option_type_from_symbol)

    entry_time_prem = max(_D("0"), entry_price - entry_iv)
    exit_time_prem = entry_time_prem * time_decay

    price = exit_iv + exit_time_prem
    result = _quantize_option_price(max(_D("0.01"), price))
    logger.debug(
        "mock_exit_price %s: entry_stock=%s exit_stock=%s entry_iv=%s exit_iv=%s "
        "entry_tp=%s exit_tp=%s → %s",
        option_symbol, entry_stock_price, exit_stock_price,
        entry_iv, exit_iv, entry_time_prem, exit_time_prem, result,
    )
    return result

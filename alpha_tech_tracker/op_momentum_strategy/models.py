from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Optional


def _D(x) -> Decimal:
    return Decimal(str(x))


@dataclass
class SignalEvent:
    ticker: str
    signal: str
    entry_price: Decimal
    stock_price: Decimal
    or_high: Decimal
    or_low: Decimal
    or_range: Decimal
    ma50_at_signal: Decimal


@dataclass
class _FiveMinBar:
    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class ActivePosition:
    ticker: str
    signal: str
    option_symbol: str
    entry_order_id: str
    contracts: int
    entry_stock_price: Decimal
    or_high: Decimal
    or_low: Decimal
    or_range: Decimal
    hard_stop_price: Decimal
    fallback_price: Decimal
    hard_stop_armed: bool = False
    is_closed: bool = False
    exit_reason: str = ""
    entry_time: Optional[datetime] = None
    exit_time: Optional[datetime] = None
    simulated_entry_mid: Optional[Decimal] = None
    simulated_exit_mid: Optional[Decimal] = None
    exit_order_id: Optional[str] = None
    entry_fill_price: Optional[Decimal] = None
    exit_fill_price: Optional[Decimal] = None

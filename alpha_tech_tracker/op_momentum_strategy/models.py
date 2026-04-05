from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Optional


def _D(x) -> Decimal:
    return Decimal(str(x))


def _stock_bid_ask(quote: dict) -> tuple:
    """Extract (bid, ask) floats from AlpacaAPIClient.get_stock_quote() response."""
    all_data = quote["QuoteResponse"]["QuoteData"][0]["All"]
    return float(all_data["bid"]), float(all_data["ask"])


@dataclass
class WindowConfig:
    """Configuration for one intraday trading window."""

    label: str  # "M1", "A1", "A2"
    opening_start: str  # "09:30", "13:15", "15:00" ET
    opening_bars: int  # number of 5-min bars in the opening range
    capital_fraction: float = 1.0  # fraction of account buying power (first-group only)
    is_sequential: bool = False  # True for windows after the first group


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
    signal_bar_time: Optional[object] = None  # bar timestamp at signal fire time


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
    trade_type: str = "options"
    shares: int = 0
    hard_stop_armed: bool = False
    is_closed: bool = False
    exit_reason: str = ""
    entry_bar_time: Optional[datetime] = None
    entry_time: Optional[datetime] = None
    exit_time: Optional[datetime] = None
    simulated_entry_mid: Optional[Decimal] = None
    simulated_exit_mid: Optional[Decimal] = None
    exit_order_id: Optional[str] = None
    entry_fill_price: Optional[Decimal] = None
    exit_fill_price: Optional[Decimal] = None
    bars_held: int = 0
    trailing_arm_price: Optional[Decimal] = None
    window_label: str = "W1"
    rank: int = 0
    window_budget: Optional[Decimal] = None
    slot_capital: Optional[Decimal] = None


@dataclass
class ReentryWatcher:
    """
    Watches a closed primary position for a second-leg re-entry or reversal trigger.

    Created by PositionMonitor when a primary trade stops out within max_bars.
    Fires when the trigger price level is crossed on a subsequent bar.
    """
    ticker: str
    reentry_type: str        # "reversal" | "bearish_reentry" | "bullish_reentry"
    primary_signal: str      # "BEARISH" or "BULLISH"
    or_high: Decimal
    or_low: Decimal
    or_range: Decimal
    midpoint: Decimal
    window_label: str
    rank: int
    window_budget: Optional[Decimal]
    primary_exit_bar_time: Optional[datetime] = None

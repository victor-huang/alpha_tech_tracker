from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Optional


def _D(x) -> Decimal:
    return Decimal(str(x))


def _stock_bid_ask(quote: dict) -> tuple:
    """Extract (bid, ask) floats from AlpacaAPIClient.get_stock_quote() response.

    ask=0 is a WebSocket staleness artifact. Fall back to bid so callers compute
    mid = bid rather than mid = bid/2.
    """
    all_data = quote["QuoteResponse"]["QuoteData"][0]["All"]
    bid = float(all_data["bid"])
    ask = float(all_data["ask"])
    if ask == 0:
        ask = bid
    return bid, ask


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
    trailing_arm_reached: bool = False
    reentry_type: Optional[str] = None
    window_label: str = "W1"
    rank: int = 0
    window_budget: Optional[Decimal] = None
    slot_capital: Optional[Decimal] = None
    last_evaluated_bar_time: Optional[datetime] = None
    is_doubledown_addon: bool = False
    close_order_failed: bool = False
    close_order_reconciled: bool = False
    close_retry_count: int = 0
    reconcile_pending_count: int = 0
    closed_contracts: int = 0
    close_alert_sent: bool = False
    use_ma_fast: bool = False
    max_favorable_move: Decimal = Decimal("0")
    timed_exit_minutes: Optional[int] = None
    disable_ma_stop: bool = False

    def to_dict(self) -> dict:
        def _ser_dec(v):
            return str(v) if v is not None else None

        def _ser_dt(v):
            return v.isoformat() if v is not None else None

        return {
            "ticker": self.ticker,
            "signal": self.signal,
            "option_symbol": self.option_symbol,
            "entry_order_id": self.entry_order_id,
            "contracts": self.contracts,
            "entry_stock_price": str(self.entry_stock_price),
            "or_high": str(self.or_high),
            "or_low": str(self.or_low),
            "or_range": str(self.or_range),
            "hard_stop_price": str(self.hard_stop_price),
            "fallback_price": str(self.fallback_price),
            "trade_type": self.trade_type,
            "shares": self.shares,
            "hard_stop_armed": self.hard_stop_armed,
            "is_closed": self.is_closed,
            "exit_reason": self.exit_reason,
            "entry_bar_time": _ser_dt(self.entry_bar_time),
            "entry_time": _ser_dt(self.entry_time),
            "exit_time": _ser_dt(self.exit_time),
            "simulated_entry_mid": _ser_dec(self.simulated_entry_mid),
            "simulated_exit_mid": _ser_dec(self.simulated_exit_mid),
            "exit_order_id": self.exit_order_id,
            "entry_fill_price": _ser_dec(self.entry_fill_price),
            "exit_fill_price": _ser_dec(self.exit_fill_price),
            "bars_held": self.bars_held,
            "trailing_arm_price": _ser_dec(self.trailing_arm_price),
            "trailing_arm_reached": self.trailing_arm_reached,
            "reentry_type": self.reentry_type,
            "window_label": self.window_label,
            "rank": self.rank,
            "window_budget": _ser_dec(self.window_budget),
            "slot_capital": _ser_dec(self.slot_capital),
            "last_evaluated_bar_time": _ser_dt(self.last_evaluated_bar_time),
            "is_doubledown_addon": self.is_doubledown_addon,
            "use_ma_fast": self.use_ma_fast,
            "max_favorable_move": _ser_dec(self.max_favorable_move),
            "timed_exit_minutes": self.timed_exit_minutes,
            "disable_ma_stop": self.disable_ma_stop,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ActivePosition":
        def _dec(v):
            return _D(v) if v is not None else None

        def _dt(v):
            return datetime.fromisoformat(v) if v is not None else None

        return cls(
            ticker=d["ticker"],
            signal=d["signal"],
            option_symbol=d["option_symbol"],
            entry_order_id=d["entry_order_id"],
            contracts=d["contracts"],
            entry_stock_price=_D(d["entry_stock_price"]),
            or_high=_D(d["or_high"]),
            or_low=_D(d["or_low"]),
            or_range=_D(d["or_range"]),
            hard_stop_price=_D(d["hard_stop_price"]),
            fallback_price=_D(d["fallback_price"]),
            trade_type=d.get("trade_type", "options"),
            shares=d.get("shares", 0),
            hard_stop_armed=d.get("hard_stop_armed", False),
            is_closed=d.get("is_closed", False),
            exit_reason=d.get("exit_reason", ""),
            entry_bar_time=_dt(d.get("entry_bar_time")),
            entry_time=_dt(d.get("entry_time")),
            exit_time=_dt(d.get("exit_time")),
            simulated_entry_mid=_dec(d.get("simulated_entry_mid")),
            simulated_exit_mid=_dec(d.get("simulated_exit_mid")),
            exit_order_id=d.get("exit_order_id"),
            entry_fill_price=_dec(d.get("entry_fill_price")),
            exit_fill_price=_dec(d.get("exit_fill_price")),
            bars_held=d.get("bars_held", 0),
            trailing_arm_price=_dec(d.get("trailing_arm_price")),
            trailing_arm_reached=d.get("trailing_arm_reached", False),
            reentry_type=d.get("reentry_type"),
            window_label=d.get("window_label", "W1"),
            rank=d.get("rank", 0),
            window_budget=_dec(d.get("window_budget")),
            slot_capital=_dec(d.get("slot_capital")),
            last_evaluated_bar_time=_dt(d.get("last_evaluated_bar_time")),
            is_doubledown_addon=d.get("is_doubledown_addon", False),
            use_ma_fast=d.get("use_ma_fast", False),
            max_favorable_move=_dec(d.get("max_favorable_move")) or Decimal("0"),
            timed_exit_minutes=d.get("timed_exit_minutes", None),
            disable_ma_stop=d.get("disable_ma_stop", False),
        )


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

"""What the strategy wants done: the monitor turns an intent into an alert, the trade engine into an order."""

import logging
from dataclasses import dataclass
from typing import Any, Optional

ENTER = "enter"
EXIT = "exit"
MOVE_STOP = "move_stop"
SKIP = "skip"
INFO = "info"
SYSTEM = "system"
KINDS = (ENTER, EXIT, MOVE_STOP, SKIP, INFO, SYSTEM)

# how an executor fills the order
BAR_CLOSE = "bar_close"
STOP = "stop"
TARGET = "target"
MOC = "moc"
MOO = "moo"
LIMIT = "limit"
ORDERS = (BAR_CLOSE, STOP, TARGET, MOC, MOO, LIMIT, None)

# a LiveTrade exit outcome -> the order that filled it
EXIT_ORDERS = {"stop": STOP, "target": TARGET, "giveback": BAR_CLOSE}


@dataclass
class Intent:
    """`action` is the alert word (BUY, SHORT, SELL, COVER, SOLD, COVERED, RAISE STOP, LOWER STOP, SHORT LIMIT,
    SHORTED, SKIP); `message` the exact alert text; `trade` the LiveTrade it concerns, if any."""

    kind: str
    message: str
    action: Optional[str] = None
    trade: Any = None
    ticker: Optional[str] = None
    setup: Optional[str] = None
    price: Optional[float] = None
    order: Optional[str] = None
    notify: bool = True
    level: int = logging.WARNING

    def __post_init__(self):
        if self.kind not in KINDS:
            raise ValueError(f"unknown intent kind {self.kind!r}")
        if self.order not in ORDERS:
            raise ValueError(f"unknown order {self.order!r}")

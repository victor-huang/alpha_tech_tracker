import logging
import threading
import time
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP
from typing import Callable, Optional

import pandas as pd
import pytz

from alpha_tech_tracker.trade_api.execution_client import ExecutionClient

from .config import (
    ARMED_MA20_EXIT,
    MAX_LOSS_PCT,
    TRAILING_MA,
    _notify,
    _fmt_option,
)
from .models import ActivePosition, ReentryWatcher, _D, _stock_bid_ask
from .order_executor import place_option_order_in_tranches, place_stock_order
from .replay import _now_et, is_replay_mode

# Imported lazily to avoid circular imports — OptionPriceMonitor imports from contract_selector
# which imports from config which imports from op_momentum_selector.
_OptionPriceMonitor = None


def _get_option_price_monitor_type():
    global _OptionPriceMonitor
    if _OptionPriceMonitor is None:
        from .option_price_monitor import OptionPriceMonitor
        _OptionPriceMonitor = OptionPriceMonitor
    return _OptionPriceMonitor

logger = logging.getLogger(__name__)


def _emit_raw(line: str):
    """Write a line directly to stream handlers in the logger hierarchy, bypassing
    the log formatter so summary tables are not cluttered with timestamps/level/module."""
    lg: Optional[logging.Logger] = logging.getLogger(__name__)
    visited: set = set()
    while lg is not None:
        for handler in lg.handlers:
            if id(handler) in visited:
                continue
            visited.add(id(handler))
            if hasattr(handler, "stream"):
                handler.acquire()
                try:
                    handler.stream.write(line + "\n")
                    handler.stream.flush()
                finally:
                    handler.release()
        if not lg.propagate:
            break
        lg = lg.parent

ET = pytz.timezone("America/New_York")

_QUICK_EXIT_MAX_SECONDS = 360  # positions held < 6 min trigger entry-price-first sell
_QUICK_EXIT_STOCK_TOLERANCE_PCT = _D("0.003")  # stock must be within 0.3% of entry price


def _quick_exit_entry_price(
    pos: ActivePosition,
    current_stock_price=None,
) -> "Optional[float]":
    """
    Return pos.entry_fill_price (as float) when the position qualifies for a
    quick-exit: try selling at the entry fill price first to avoid locking in a
    loss on a position that never had time to develop.

    Both conditions must hold:
      1. Position has been held less than _QUICK_EXIT_MAX_SECONDS (5 min).
      2. current_stock_price is within _QUICK_EXIT_STOCK_TOLERANCE_PCT (0.5%) of
         pos.entry_stock_price — if the stock has already moved away, the option
         market value is no longer near entry_fill_price and step 0 would waste
         20 seconds on a limit that won't fill.

    Returns None if any condition fails, entry_time is unknown, or
    entry_fill_price was not recorded.
    """
    if pos.entry_fill_price is None or pos.entry_time is None:
        return None
    elapsed = (_now_et() - pos.entry_time).total_seconds()
    if elapsed >= _QUICK_EXIT_MAX_SECONDS:
        return None
    if current_stock_price is not None:
        diff_pct = abs(current_stock_price - pos.entry_stock_price) / pos.entry_stock_price
        if diff_pct > _QUICK_EXIT_STOCK_TOLERANCE_PCT:
            return None
    return float(pos.entry_fill_price)


class PositionMonitor:
    """Monitors open option positions and exits on stop conditions."""

    def __init__(
        self,
        alpaca_client: ExecutionClient,
        signal_engine,
        mock_trade_execution: bool = False,
        trailing_ma: str = TRAILING_MA,
        max_loss_pct: Optional[float] = MAX_LOSS_PCT,
        armed_ma20_exit: bool = ARMED_MA20_EXIT,
        option_price_monitor=None,
        enable_reversal: bool = False,
        reversal_max_bars: int = 3,
        enable_bearish_reentry: bool = False,
        bearish_reentry_max_bars: int = 3,
        enable_bullish_reentry: bool = False,
        bullish_reentry_max_bars: int = 5,
        re_entry_callback=None,
        initial_capital: Optional[float] = None,
        close_callback: Optional[Callable] = None,
        exit_retry_callback: Optional[Callable] = None,
        alpaca_feed=None,
        count_flat_bars_in_held: bool = False,
    ):
        self._client = alpaca_client
        self._signal_engine = signal_engine
        self._mock_trade_execution = mock_trade_execution
        self._trailing_ma = trailing_ma
        self._max_loss_pct = max_loss_pct
        self._armed_ma20_exit = armed_ma20_exit
        self._option_price_monitor = option_price_monitor
        self._enable_reversal = enable_reversal
        self._reversal_max_bars = reversal_max_bars
        self._enable_bearish_reentry = enable_bearish_reentry
        self._bearish_reentry_max_bars = bearish_reentry_max_bars
        self._enable_bullish_reentry = enable_bullish_reentry
        self._bullish_reentry_max_bars = bullish_reentry_max_bars
        self._re_entry_callback = re_entry_callback
        self._initial_capital = initial_capital
        self._close_callback = close_callback
        self._exit_retry_callback = exit_retry_callback
        self._alpaca_feed = alpaca_feed
        self._count_flat_bars_in_held = count_flat_bars_in_held
        self._positions: list = []
        self._reentry_watchers: list = []
        self._lock = threading.Lock()
        self._stop_event = threading.Event()

    def add_position(self, position: ActivePosition):
        with self._lock:
            self._positions.append(position)
            logger.info(
                "Tracking position: %s %s opt=%s contracts=%d",
                position.ticker,
                position.signal,
                position.option_symbol,
                position.contracts,
            )

    def get_all_positions(self) -> list:
        """Return a thread-safe snapshot of all positions (open and closed)."""
        with self._lock:
            return list(self._positions)

    def on_bar(self, ticker: str):
        latest = self._signal_engine.get_latest_bar(ticker)
        if latest is None:
            return

        bar_time = latest.name
        close = _D(latest["Close"])
        high = _D(latest["High"])
        low = _D(latest["Low"])
        bar_open = _D(latest["Open"])
        bar_volume = latest.get("Volume", 0) or 0
        ma20 = latest.get("MA20")
        ma20_val = _D(ma20) if ma20 is not None and not pd.isna(ma20) else None
        ma50 = latest.get("MA50")
        ma50_val = _D(ma50) if ma50 is not None and not pd.isna(ma50) else None

        to_close = []
        with self._lock:
            for pos in self._positions:
                if pos.ticker != ticker or pos.is_closed:
                    continue
                if pos.entry_bar_time is not None and bar_time == pos.entry_bar_time:
                    continue
                close_intent = self._evaluate_stop(pos, close, high, low, bar_open, ma20_val, ma50_val, bar_time, bar_volume)
                if close_intent is not None:
                    reason, override = close_intent
                    pos.is_closed = True
                    pos.exit_reason = reason
                    pos.exit_time = _now_et()
                    self._maybe_create_reentry_watcher(pos, reason)
                    to_close.append((pos, reason, override))

            fired_watchers = self._collect_fired_watchers(ticker, close, bar_time)

        # Execute close operations outside the lock so sequential window drains
        # are not blocked in _get_window_budget() during slow API calls.
        for pos, reason, override in to_close:
            if pos.trade_type == "stock":
                self._close_stock_position(pos, reason, exit_stock_price_override=override)
            else:
                self._close_option_position(pos, reason, exit_stock_price_override=override)
            if self._close_callback:
                self._close_callback(pos)

        # Retry any positions whose close order failed on a previous bar.
        # _close_callback is NOT re-invoked — capital was already returned on first close.
        retry_failed = []
        with self._lock:
            for pos in self._positions:
                if pos.ticker == ticker and pos.is_closed and pos.close_order_failed:
                    retry_failed.append(pos)
        _MAX_CLOSE_RETRIES = 3
        for pos in retry_failed:
            if pos.close_order_reconciled:
                continue
            if pos.close_retry_count >= _MAX_CLOSE_RETRIES:
                if not pos.close_alert_sent:
                    pos.close_alert_sent = True
                    logger.warning(
                        "CLOSE RETRY LIMIT reached for %s %s — manual intervention required",
                        pos.ticker, pos.signal,
                    )
                    _notify(
                        f"CLOSE FAILED {pos.ticker} {pos.signal} — {_MAX_CLOSE_RETRIES} retries exhausted, close manually"
                    )
                continue
            pos.close_retry_count += 1
            logger.warning(
                "Retrying failed close order for %s %s reason=%s (attempt %d/%d)",
                pos.ticker,
                pos.signal,
                pos.exit_reason,
                pos.close_retry_count,
                _MAX_CLOSE_RETRIES,
            )
            if pos.trade_type == "stock":
                self._close_stock_position(pos, pos.exit_reason)
            else:
                self._close_option_position(pos, pos.exit_reason)
            if (
                self._exit_retry_callback
                and not pos.close_order_failed
                and pos.exit_fill_price is not None
            ):
                self._exit_retry_callback(pos)

        # Invoke re-entry callbacks outside the lock to avoid deadlock with add_position.
        # In replay mode call synchronously so the position exists for the next bar.
        for w in fired_watchers:
            logger.info(
                "Re-entry trigger fired [%s] %s close=%.2f",
                w.reentry_type,
                w.ticker,
                float(close),
            )
            if self._re_entry_callback:
                if is_replay_mode():
                    self._re_entry_callback(w, close)
                else:
                    threading.Thread(
                        target=self._re_entry_callback,
                        args=(w, close),
                        daemon=True,
                    ).start()

    def _trailing_armed(self, pos: ActivePosition, close) -> bool:
        """
        Returns True when the trailing MA stop is allowed to fire.

        Primary positions (trailing_arm_price=None) use the existing behaviour:
        the MA trailing stop is always eligible once armed via hard_stop_armed.
        Re-entry positions gate the trailing stop behind a price threshold
        (entry ± or_range) to match the backtest arming condition.

        Once armed, the flag latches — matching the backtest's persistent
        bru_trailing_armed boolean that stays True once set.
        """
        if pos.trailing_arm_price is None:
            return True
        if not pos.trailing_arm_reached:
            if pos.signal == "BULLISH":
                pos.trailing_arm_reached = close >= pos.trailing_arm_price
            else:
                pos.trailing_arm_reached = close <= pos.trailing_arm_price
        return pos.trailing_arm_reached

    def _evaluate_stop(
        self,
        pos: ActivePosition,
        close,
        high,
        low,
        bar_open,
        ma20: Optional[object],
        ma50: Optional[object],
        bar_time=None,
        bar_volume=0,
    ):
        exit_reason = None

        if self._max_loss_pct is not None:
            entry = pos.entry_stock_price
            loss_pct = (
                (entry - close) / entry
                if pos.signal == "BULLISH"
                else (close - entry) / entry
            )
            if loss_pct >= _D(str(self._max_loss_pct)):
                return ("max_loss", None)

        trailing_armed = self._trailing_armed(pos, close)

        if pos.signal == "BULLISH":
            if not pos.hard_stop_armed and close > pos.hard_stop_price:
                pos.hard_stop_armed = True
            if pos.hard_stop_armed and self._armed_ma20_exit:
                if ma20 is not None:
                    if close < ma20:
                        exit_reason = "trailing_stop_ma20"
                elif close <= pos.hard_stop_price:
                    exit_reason = "hard_stop"
            elif pos.hard_stop_armed and close <= pos.hard_stop_price:
                exit_reason = "hard_stop"
            elif not pos.hard_stop_armed and close <= pos.fallback_price:
                exit_reason = "fallback_20pct"
            elif (
                trailing_armed
                and self._trailing_ma in ("ma20", "both")
                and ma20 is not None
                and ma20 > pos.hard_stop_price
                and close < ma20
            ):
                exit_reason = "trailing_stop_ma20"
            elif (
                trailing_armed
                and self._trailing_ma in ("ma50", "both")
                and ma50 is not None
                and ma50 > pos.hard_stop_price
                and close < ma50
            ):
                exit_reason = "trailing_stop_ma50"
        else:
            if not pos.hard_stop_armed and close < pos.hard_stop_price:
                pos.hard_stop_armed = True
            if pos.hard_stop_armed and self._armed_ma20_exit:
                if ma20 is not None:
                    if close > ma20:
                        exit_reason = "trailing_stop_ma20"
                elif close >= pos.hard_stop_price:
                    exit_reason = "hard_stop"
            elif pos.hard_stop_armed and close >= pos.hard_stop_price:
                exit_reason = "hard_stop"
            elif not pos.hard_stop_armed and close >= pos.fallback_price:
                exit_reason = "fallback_20pct"
            elif (
                trailing_armed
                and self._trailing_ma in ("ma20", "both")
                and ma20 is not None
                and ma20 < pos.or_low
                and close > ma20
            ):
                exit_reason = "trailing_stop_ma20"
            elif (
                trailing_armed
                and self._trailing_ma in ("ma50", "both")
                and ma50 is not None
                and ma50 < pos.or_low
                and close > ma50
            ):
                exit_reason = "trailing_stop_ma50"

        if exit_reason:
            override = None
            if exit_reason == "hard_stop":
                if pos.signal == "BULLISH":
                    override = pos.hard_stop_price if high >= pos.hard_stop_price else bar_open
                else:
                    override = pos.hard_stop_price if low <= pos.hard_stop_price else bar_open
            elif exit_reason == "fallback_20pct":
                if pos.signal == "BEARISH":
                    override = pos.fallback_price if low <= pos.fallback_price else bar_open
                elif high >= pos.fallback_price:
                    override = pos.fallback_price
            return (exit_reason, override)
        else:
            if bar_time is not None and bar_time == pos.last_evaluated_bar_time:
                return None  # same bar repeated poll — don't double-count
            pos.last_evaluated_bar_time = bar_time
            if self._count_flat_bars_in_held or bar_volume > 0:
                pos.bars_held += 1
            return None

    def _maybe_create_reentry_watcher(self, pos: ActivePosition, reason: str):
        if reason not in ("hard_stop", "fallback_20pct"):
            return
        # Don't cascade: re-entry positions (trailing_arm_price set) don't spawn further watchers.
        # Backtest only allows one level of re-entry per primary trade.
        if pos.trailing_arm_price is not None:
            return

        midpoint = (_D(str(pos.or_high)) + _D(str(pos.or_low))) / _D("2")

        # Reversal and BRE are created simultaneously when both are eligible.
        # Both watchers compete on subsequent bars; whichever trigger fires first wins.
        # _collect_fired_watchers enforces reversal priority if both fire on the same bar,
        # and removes all sibling watchers for the ticker once one fires.
        # This matches the backtest's behaviour: it scans for the reversal trigger
        # exhaustively and falls through to BRE only if the reversal never fires —
        # equivalent to "first chronological trigger wins, reversal breaks ties."
        if (
            self._enable_reversal
            and pos.signal == "BEARISH"
            and pos.bars_held <= self._reversal_max_bars
            and not pos.is_doubledown_addon
        ):
            self._reentry_watchers.append(
                ReentryWatcher(
                    ticker=pos.ticker,
                    reentry_type="reversal",
                    primary_signal="BEARISH",
                    or_high=pos.or_high,
                    or_low=pos.or_low,
                    or_range=pos.or_range,
                    midpoint=midpoint,
                    window_label=pos.window_label,
                    rank=pos.rank,
                    window_budget=pos.window_budget,
                    primary_exit_bar_time=pos.exit_time,
                )
            )
            logger.info(
                "Reversal watcher created for %s (bars_held=%d)", pos.ticker, pos.bars_held
            )

        if (
            self._enable_bearish_reentry
            and pos.signal == "BEARISH"
            and pos.bars_held <= self._bearish_reentry_max_bars
            and not pos.is_doubledown_addon
        ):
            self._reentry_watchers.append(
                ReentryWatcher(
                    ticker=pos.ticker,
                    reentry_type="bearish_reentry",
                    primary_signal="BEARISH",
                    or_high=pos.or_high,
                    or_low=pos.or_low,
                    or_range=pos.or_range,
                    midpoint=midpoint,
                    window_label=pos.window_label,
                    rank=pos.rank,
                    window_budget=pos.window_budget,
                    primary_exit_bar_time=pos.exit_time,
                )
            )
            logger.info(
                "Bearish re-entry watcher created for %s (bars_held=%d)",
                pos.ticker,
                pos.bars_held,
            )

        if (
            self._enable_bullish_reentry
            and pos.signal == "BULLISH"
            and pos.bars_held <= self._bullish_reentry_max_bars
            and not pos.is_doubledown_addon
        ):
            self._reentry_watchers.append(
                ReentryWatcher(
                    ticker=pos.ticker,
                    reentry_type="bullish_reentry",
                    primary_signal="BULLISH",
                    or_high=pos.or_high,
                    or_low=pos.or_low,
                    or_range=pos.or_range,
                    midpoint=midpoint,
                    window_label=pos.window_label,
                    rank=pos.rank,
                    window_budget=pos.window_budget,
                    primary_exit_bar_time=pos.exit_time,
                )
            )
            logger.info(
                "Bullish re-entry watcher created for %s (bars_held=%d)",
                pos.ticker,
                pos.bars_held,
            )

    def _collect_fired_watchers(self, ticker: str, close, bar_time) -> list:
        """Collect and remove watchers that trigger on this bar. Called under self._lock.

        When reversal and BRE both fire on the same bar, only the reversal is returned
        (matching backtest priority). Once any watcher fires, all remaining watchers for
        the same ticker are also removed to prevent a sibling from firing on a later bar.
        """
        if not self._reentry_watchers:
            return []

        fired = []
        for w in self._reentry_watchers:
            if w.ticker != ticker:
                continue
            if w.primary_exit_bar_time is not None and bar_time == w.primary_exit_bar_time:
                continue
            if w.reentry_type in ("reversal", "bullish_reentry"):
                triggered = close > w.or_high
            else:
                triggered = close < w.or_low
            if triggered:
                fired.append(w)

        if not fired:
            return fired

        # Reversal takes priority when it fires on the same bar as BRE.
        reversal_fired = [w for w in fired if w.reentry_type == "reversal"]
        if reversal_fired and len(fired) > 1:
            fired = reversal_fired

        # Remove watchers that share the same ticker AND primary_exit_bar_time as the
        # fired watcher(s).  Only true siblings (same exit) are cleaned up — watchers
        # from a different exit on the same ticker (e.g. an M1 BRE that outlives an A1
        # reversal) are kept so they can fire later.
        fired_exit_times = {w.primary_exit_bar_time for w in fired}
        self._reentry_watchers = [
            w for w in self._reentry_watchers
            if not (w.ticker == ticker and w.primary_exit_bar_time in fired_exit_times)
        ]

        return fired

    def _close_position(self, pos: ActivePosition, reason: str, exit_stock_price_override=None):
        pos.is_closed = True
        pos.exit_reason = reason
        pos.exit_time = _now_et()
        self._maybe_create_reentry_watcher(pos, reason)

        if pos.trade_type == "stock":
            self._close_stock_position(pos, reason, exit_stock_price_override=exit_stock_price_override)
        else:
            self._close_option_position(pos, reason, exit_stock_price_override=exit_stock_price_override)

        if self._close_callback:
            self._close_callback(pos)

    def _close_stock_position(self, pos: ActivePosition, reason: str, exit_stock_price_override=None):
        logger.info(
            "EXIT %s %s reason=%s shares=%d",
            pos.ticker,
            pos.signal,
            reason,
            pos.shares,
        )

        mid = None
        if exit_stock_price_override is not None:
            mid = exit_stock_price_override
        elif is_replay_mode():
            latest_bar = self._signal_engine.get_latest_bar(pos.ticker)
            if latest_bar is not None:
                mid = _D(str(latest_bar["Close"]))
        else:
            try:
                raw_quote = self._client.get_stock_quote(
                    pos.ticker,
                    **({"feed": self._alpaca_feed} if self._alpaca_feed is not None else {})
                )
                bid_f, ask_f = _stock_bid_ask(raw_quote)
                bid = _D(str(bid_f))
                ask = _D(str(ask_f))
                mid = (bid + ask) / _D("2")
                logger.info(
                    "EXIT STOCK QUOTE %s: bid=%s ask=%s mid=%s",
                    pos.ticker,
                    bid,
                    ask,
                    mid.quantize(_D("0.01"), rounding=ROUND_HALF_UP),
                )
            except Exception:
                logger.exception("Could not fetch exit stock quote for %s", pos.ticker)

        if not self._mock_trade_execution and not is_replay_mode():
            try:
                open_positions = self._client.get_open_positions()
                broker_entry = open_positions.get(pos.ticker)
                if broker_entry is None:
                    logger.warning(
                        "PRE-CLOSE SYNC %s [stock]: not found at broker — already fully closed manually",
                        pos.ticker,
                    )
                    pos.close_order_failed = False
                    _notify(
                        f"MANUAL CLOSE DETECTED {pos.ticker} x{pos.shares} shares"
                        f" — position already closed at broker, skipping order"
                    )
                    return
                broker_qty = int(abs(broker_entry["qty"]))
                if broker_qty < pos.shares:
                    logger.warning(
                        "PRE-CLOSE SYNC %s [stock]: broker qty=%d < engine qty=%d"
                        " — adjusting (partial manual close detected)",
                        pos.ticker, broker_qty, pos.shares,
                    )
                    _notify(
                        f"PARTIAL MANUAL CLOSE {pos.ticker}:"
                        f" engine={pos.shares} broker={broker_qty} shares"
                        f" — selling remaining {broker_qty} shares"
                    )
                    pos.shares = broker_qty
            except Exception:
                logger.warning(
                    "PRE-CLOSE SYNC: broker qty check failed for %s [stock]"
                    " — proceeding with engine qty=%d",
                    pos.ticker, pos.shares, exc_info=True,
                )

        is_short = pos.signal == "BEARISH"
        close_order_action = "BUY_COVER" if is_short else "SELL_CLOSE"
        close_side = "BUY" if is_short else "SELL"
        close_label = "BUY TO COVER" if is_short else "SELL"

        mid_str = f" @ ~${float(mid):.2f}" if mid is not None else ""
        prefix = "[SIMULATE] " if self._mock_trade_execution else ""
        _notify(f"{prefix}{close_label} {pos.ticker} x{pos.shares} shares{mid_str} reason={reason}")

        if self._mock_trade_execution:
            sim_mid = (
                mid.quantize(_D("0.01"), rounding=ROUND_HALF_UP)
                if mid is not None
                else _D("0")
            )
            pos.simulated_exit_mid = sim_mid
            logger.info(
                "SIMULATE %s %s shares=%d simulated_fill=%.2f (no order placed)",
                close_order_action,
                pos.ticker,
                pos.shares,
                sim_mid,
            )
            return

        try:
            if reason == "end_of_day":
                logger.info(
                    "EOD %s stock market order: %s %d shares",
                    close_order_action,
                    pos.ticker,
                    pos.shares,
                )
                order = self._client.place_stock_order(
                    symbol=pos.ticker,
                    quantity=pos.shares,
                    side=close_side,
                    order_type="MARKET",
                )
            else:
                logger.info(
                    "Placing %s stock with fill escalation: %s %d shares",
                    close_order_action,
                    pos.ticker,
                    pos.shares,
                )
                latest_bar = self._signal_engine.get_latest_bar(pos.ticker)
                exit_signal_price = (
                    float(latest_bar["Close"]) if latest_bar is not None else None
                )
                order = place_stock_order(
                    client=self._client,
                    ticker=pos.ticker,
                    shares=pos.shares,
                    order_action=close_order_action,
                    feed=self._alpaca_feed,
                    signal_price=exit_signal_price,
                )
            pos.exit_order_id = order.get("order_id")
            pos.close_order_failed = False
            logger.info("Stock close order placed: %s", pos.exit_order_id)
            self._poll_exit_fill_price(pos)
        except Exception:
            logger.exception("Failed to place stock close order for %s", pos.ticker)
            pos.close_order_failed = True
            _notify(f"CLOSE FAILED {pos.ticker} x{pos.shares} shares reason={reason} — close manually")

    def _close_option_position(self, pos: ActivePosition, reason: str, exit_stock_price_override=None):
        logger.info(
            "EXIT %s %s reason=%s opt=%s contracts=%d",
            pos.ticker,
            pos.signal,
            reason,
            pos.option_symbol,
            pos.contracts,
        )
        mid = None
        option_type_lower = "call" if pos.signal == "BULLISH" else "put"
        if self._option_price_monitor and not self._mock_trade_execution:
            try:
                try:
                    kwargs = {"feed": self._alpaca_feed} if self._alpaca_feed is not None else {}
                    raw_quote = self._client.get_stock_quote(pos.ticker, **kwargs)
                    bid_f, ask_f = _stock_bid_ask(raw_quote)
                    stock_price = (_D(str(bid_f)) + _D(str(ask_f))) / _D("2")
                except Exception:
                    current_bar = self._signal_engine.get_latest_bar(pos.ticker)
                    stock_price = _D(str(current_bar["Close"])) if current_bar is not None else pos.entry_stock_price
                mid = self._option_price_monitor.get_fair_price(
                    pos.ticker, pos.option_symbol, option_type_lower, stock_price
                )
                logger.info("EXIT FAIR PRICE %s: %s (from OptionPriceMonitor)", pos.option_symbol, mid)
            except Exception:
                logger.warning("get_fair_price failed for %s at exit, falling back to quote mid", pos.option_symbol)
                mid = None

        if mid is None:
            if self._mock_trade_execution:
                from .mock_option_pricer import mock_exit_price, _TIME_DECAY
                current_bar = self._signal_engine.get_latest_bar(pos.ticker)
                if current_bar is not None and pos.simulated_entry_mid:
                    if exit_stock_price_override is not None:
                        exit_stock_price = exit_stock_price_override
                    else:
                        exit_stock_price = _D(str(current_bar["Close"]))
                    time_decay = _D("1") if pos.bars_held < 12 else _TIME_DECAY
                    mid = mock_exit_price(
                        exit_stock_price=exit_stock_price,
                        option_symbol=pos.option_symbol,
                        option_type=option_type_lower,
                        entry_price=pos.simulated_entry_mid,
                        entry_stock_price=_D(str(pos.entry_stock_price)),
                        time_decay=time_decay,
                    )
                    logger.info("MOCK EXIT PRICE %s: %s", pos.option_symbol, mid)
            else:
                try:
                    q = self._client.get_option_quote_by_occ(pos.option_symbol)
                    bid = _D(str(q["bid"]))
                    ask = _D(str(q["ask"]))
                    mid = _D(str(q["mid"]))
                    logger.info(
                        "EXIT QUOTE %s: bid=%s ask=%s mid=%s",
                        pos.option_symbol,
                        bid,
                        ask,
                        mid.quantize(_D("0.01"), rounding=ROUND_HALF_UP),
                    )
                except Exception:
                    logger.exception(
                        "Could not fetch exit quote for %s, using market order",
                        pos.option_symbol,
                    )

        if not self._mock_trade_execution and not is_replay_mode():
            try:
                open_positions = self._client.get_open_positions()
                broker_entry = open_positions.get(pos.option_symbol)
                if broker_entry is None:
                    # Broker may lag a few seconds after a fill before the position
                    # appears in the positions API. Retry once before concluding the
                    # position was manually closed.
                    logger.warning(
                        "PRE-CLOSE SYNC %s: not found at broker on first check"
                        " — retrying in 3s (broker positions API may lag after fill)",
                        pos.option_symbol,
                    )
                    time.sleep(3)
                    open_positions = self._client.get_open_positions()
                    broker_entry = open_positions.get(pos.option_symbol)
                if broker_entry is None:
                    logger.warning(
                        "PRE-CLOSE SYNC %s: not found at broker after retry — already fully closed manually",
                        pos.option_symbol,
                    )
                    fill_est = self._fetch_manual_close_fill_price(pos)
                    if fill_est is not None:
                        pos.exit_fill_price = fill_est
                    pos.close_order_failed = False
                    _notify(
                        f"MANUAL CLOSE DETECTED {_fmt_option(pos.option_symbol)} x{pos.contracts}"
                        f" — position already closed at broker, skipping order"
                    )
                    return
                broker_qty = int(broker_entry["qty"])
                if broker_qty < pos.contracts:
                    logger.warning(
                        "PRE-CLOSE SYNC %s: broker qty=%d < engine qty=%d"
                        " — adjusting (partial manual close detected)",
                        pos.option_symbol, broker_qty, pos.contracts,
                    )
                    _notify(
                        f"PARTIAL MANUAL CLOSE {_fmt_option(pos.option_symbol)}:"
                        f" engine={pos.contracts} broker={broker_qty}"
                        f" — selling remaining {broker_qty} contracts"
                    )
                    pos.contracts = broker_qty
            except Exception:
                logger.warning(
                    "PRE-CLOSE SYNC: broker qty check failed for %s"
                    " — proceeding with engine qty=%d",
                    pos.option_symbol, pos.contracts, exc_info=True,
                )

        mid_str = f" @ ~${float(mid):.2f}" if mid is not None else ""
        prefix = "[SIMULATE] " if self._mock_trade_execution else ""
        _notify(f"{prefix}SELL {_fmt_option(pos.option_symbol)} x{pos.contracts}{mid_str} reason={reason}")

        if self._mock_trade_execution:
            sim_mid = (
                mid.quantize(_D("0.01"), rounding=ROUND_HALF_UP)
                if mid is not None
                else _D("0")
            )
            pos.simulated_exit_mid = sim_mid
            logger.info(
                "SIMULATE SELL_CLOSE %s contracts=%d simulated_fill=%.2f (no order placed)",
                pos.option_symbol,
                pos.contracts,
                sim_mid,
            )
            return

        try:
            option_type = "CALL" if pos.signal == "BULLISH" else "PUT"

            opm = self._option_price_monitor
            se = self._signal_engine
            _esc_client = self._client
            _esc_feed = self._alpaca_feed
            if opm is not None:
                def _exit_fair_price_fn(
                    _ticker=pos.ticker,
                    _symbol=pos.option_symbol,
                    _otype=option_type_lower,
                    _entry_stock=pos.entry_stock_price,
                ):
                    try:
                        kwargs = {"feed": _esc_feed} if _esc_feed is not None else {}
                        raw_quote = _esc_client.get_stock_quote(_ticker, **kwargs)
                        bid_f, ask_f = _stock_bid_ask(raw_quote)
                        stock_price = (_D(str(bid_f)) + _D(str(ask_f))) / _D("2")
                    except Exception:
                        bar = se.get_latest_bar(_ticker) if se else None
                        stock_price = _D(str(bar["Close"])) if bar is not None else _D(str(_entry_stock))
                    return opm.get_fair_price(_ticker, _symbol, _otype, stock_price)
            else:
                _exit_fair_price_fn = None

            if reason == "end_of_day":
                logger.info(
                    "EOD SELL_CLOSE with fill escalation: %s %d contracts",
                    pos.option_symbol,
                    pos.contracts,
                )
                quick_exit_fill_price = None
            else:
                latest_bar = self._signal_engine.get_latest_bar(pos.ticker)
                current_stock_price = (
                    _D(str(latest_bar["Close"])) if latest_bar is not None else None
                )
                quick_exit_fill_price = _quick_exit_entry_price(
                    pos, current_stock_price=current_stock_price
                )
                if quick_exit_fill_price is not None:
                    logger.info(
                        "Placing SELL_CLOSE quick-exit: %s %d contracts"
                        " (held < %ds, stock within %.1f%% of entry, will try entry_fill_price first)",
                        pos.option_symbol,
                        pos.contracts,
                        _QUICK_EXIT_MAX_SECONDS,
                        float(_QUICK_EXIT_STOCK_TOLERANCE_PCT * 100),
                    )
                else:
                    logger.info(
                        "Placing SELL_CLOSE with fill escalation: %s %d contracts",
                        pos.option_symbol,
                        pos.contracts,
                    )
            original_contracts = pos.contracts
            pos.closed_contracts = pos.contracts
            last_order, filled = place_option_order_in_tranches(
                client=self._client,
                ticker=pos.ticker,
                option_symbol=pos.option_symbol,
                option_type=option_type,
                contracts=pos.contracts,
                order_action="SELL_CLOSE",
                entry_fill_price=quick_exit_fill_price,
                get_fair_price_fn=_exit_fair_price_fn,
                feed=self._alpaca_feed,
            )
            pos.contracts -= filled
            pos.exit_order_id = last_order.get("order_id")
            if pos.contracts > 0:
                pos.close_order_failed = True
                if filled > 0:
                    _notify(
                        f"CLOSE PARTIAL {pos.option_symbol}:"
                        f" {filled}/{original_contracts} contracts closed,"
                        f" {pos.contracts} still open reason={reason} — retry pending"
                    )
                else:
                    _notify(
                        f"CLOSE MISSED {pos.option_symbol} x{original_contracts}"
                        f" reason={reason} — manual close required"
                    )
            else:
                pos.close_order_failed = False
                logger.info("Close order placed: %s", pos.exit_order_id)
                self._poll_exit_fill_price(pos)
        except Exception:
            logger.exception("Failed to place close order for %s", pos.option_symbol)
            pos.close_order_failed = True
            _notify(f"CLOSE FAILED {pos.option_symbol} x{pos.contracts} reason={reason} — close manually")

    def close_all(self, reason: str = "end_of_day"):
        to_close = []
        with self._lock:
            for pos in self._positions:
                if not pos.is_closed:
                    pos.is_closed = True
                    pos.exit_reason = reason
                    pos.exit_time = _now_et()
                    to_close.append(pos)
            self._reentry_watchers.clear()
        for pos in to_close:
            if pos.trade_type == "stock":
                self._close_stock_position(pos, reason)
            else:
                self._close_option_position(pos, reason)
            if self._close_callback:
                self._close_callback(pos)

        stuck = []
        with self._lock:
            for pos in self._positions:
                if pos.is_closed and pos.close_order_failed:
                    stuck.append(pos)
        for pos in stuck:
            logger.warning(
                "EOD sweep: force-closing stuck position %s %s (prior close order failed)",
                pos.ticker, pos.signal,
            )
            _notify(
                f"EOD force-close: {pos.ticker} {pos.signal} — prior close order had failed, placing market order now"
            )
            if pos.trade_type == "stock":
                self._close_stock_position(pos, "end_of_day")
            else:
                self._close_option_position(pos, "end_of_day")

    def start_reconciliation_thread(self):
        """Start the background thread that reconciles stuck positions against the broker.

        Only meaningful in live (non-mock, non-replay) mode. Safe to call multiple times —
        a second call is a no-op if the thread is already running.
        """
        t = threading.Thread(
            target=self._reconciliation_loop,
            daemon=True,
            name="stuck-position-reconciler",
        )
        t.start()
        logger.info("Stuck-position reconciliation thread started (interval=5 min)")

    def stop(self):
        """Signal the reconciliation thread to exit on its next wakeup."""
        self._stop_event.set()

    def _reconciliation_loop(self):
        """Wake every 5 minutes and reconcile positions against the broker."""
        _INTERVAL_SECONDS = 300
        while not self._stop_event.wait(timeout=_INTERVAL_SECONDS):
            if is_replay_mode():
                continue
            try:
                self._sync_open_position_qtys()
            except Exception:
                logger.exception("Reconciliation qty-sync error")
            try:
                self._reconcile_stuck_positions()
            except Exception:
                logger.exception("Reconciliation loop error")

    def _sync_open_position_qtys(self):
        """Compare broker qty against engine's tracked qty for all open (not yet closed) positions.

        Detects partial manual closes that happened outside the engine and updates
        pos.contracts / pos.shares so the next exit sells the correct remaining quantity.
        Only reduces qty — never increases — since the engine can't gain contracts externally.
        """
        with self._lock:
            open_pos = [p for p in self._positions if not p.is_closed]
        if not open_pos:
            return

        try:
            open_positions = self._client.get_open_positions()
        except Exception:
            logger.warning("Could not fetch open positions for qty sync", exc_info=True)
            return

        for pos in open_pos:
            lookup_symbol = pos.option_symbol if pos.trade_type != "stock" else pos.ticker
            broker_entry = open_positions.get(lookup_symbol)
            if broker_entry is None:
                continue

            if pos.trade_type == "stock":
                broker_qty = int(abs(broker_entry["qty"]))
                engine_qty = pos.shares
            else:
                broker_qty = int(broker_entry["qty"])
                engine_qty = pos.contracts

            if broker_qty < engine_qty:
                logger.warning(
                    "QTY SYNC %s: broker qty=%d < engine qty=%d"
                    " — updating to broker qty (partial manual close detected)",
                    lookup_symbol, broker_qty, engine_qty,
                )
                _notify(
                    f"QTY SYNC {lookup_symbol}: engine={engine_qty}"
                    f" broker={broker_qty} — updated to broker qty"
                )
                with self._lock:
                    if pos.trade_type == "stock":
                        pos.shares = broker_qty
                    else:
                        pos.contracts = broker_qty

    def _reconcile_stuck_positions(self):
        """Check broker open positions and resolve any stuck (close_order_failed) positions.

        For each position marked close_order_failed, queries the broker to see whether
        the position is still open. If the broker shows it as closed (manually closed by
        the user), sets exit_fill_price from the current option mid (best estimate),
        clears close_order_failed, and fires exit_retry_callback so _on_exit_fill_corrected
        updates daily P&L.
        """
        with self._lock:
            stuck = [
                p for p in self._positions
                if p.is_closed and p.close_order_failed
            ]
        if not stuck:
            return

        logger.info("Reconciling %d stuck position(s) against broker", len(stuck))
        try:
            open_positions = self._client.get_open_positions()
        except Exception:
            logger.warning("Could not fetch open positions for reconciliation", exc_info=True)
            return

        for pos in stuck:
            lookup_symbol = pos.option_symbol if pos.trade_type != "stock" else pos.ticker
            if lookup_symbol in open_positions:
                continue

            # Position is no longer open at the broker — manually closed.
            fill_price = self._fetch_manual_close_fill_price(pos)
            with self._lock:
                if fill_price is not None:
                    pos.exit_fill_price = fill_price
                pos.close_order_failed = False
                pos.close_order_reconciled = True

            if fill_price is not None:
                msg = (
                    f"RECONCILED {pos.option_symbol} x{pos.contracts}"
                    f" — manually closed at broker, exit price ${float(fill_price):.2f}"
                )
            else:
                msg = (
                    f"RECONCILED {pos.option_symbol} x{pos.contracts}"
                    f" — manually closed at broker, exit price unknown"
                )
            logger.info(msg)
            _notify(msg)

            if self._exit_retry_callback and pos.exit_fill_price is not None:
                self._exit_retry_callback(pos)

    def _fetch_option_mid(self, option_symbol: str) -> Optional[object]:
        try:
            q = self._client.get_option_quote_by_occ(option_symbol)
            return _D(str(q["mid"]))
        except Exception:
            return None

    def _fetch_manual_close_fill_price(self, pos: ActivePosition) -> Optional[object]:
        """Return the actual fill price of a manually placed close order.

        Queries order history for the most recent filled sell (or buy-to-cover for stocks)
        on the position's instrument that was submitted after the engine's entry time.
        Falls back to the current option mid when no matching order is found.
        """
        symbol = pos.option_symbol if pos.trade_type != "stock" else pos.ticker
        close_side = "buy" if (pos.trade_type == "stock" and pos.signal == "BEARISH") else "sell"
        try:
            filled_orders = self._client.get_filled_orders(symbol, limit=10)
            for order in filled_orders:
                if order["side"] != close_side:
                    continue
                if pos.entry_time is not None and order.get("filled_at") is not None:
                    filled_at = order["filled_at"]
                    if hasattr(filled_at, "tzinfo") and filled_at.tzinfo is None:
                        filled_at = ET.localize(filled_at)
                    if filled_at <= pos.entry_time:
                        continue
                price = _D(str(order["filled_avg_price"]))
                logger.info(
                    "MANUAL CLOSE FILL %s: found filled %s order %s @ %s (filled_at=%s)",
                    symbol, close_side, order["order_id"], price, order.get("filled_at"),
                )
                return price
        except Exception:
            logger.warning("Could not fetch order history for %s", symbol, exc_info=True)

        return self._fetch_option_mid(symbol) if pos.trade_type != "stock" else None

    def _poll_exit_fill_price(self, pos: ActivePosition, max_attempts: int = 3, interval: float = 5.0):
        """Poll order status after placing an exit order to set pos.exit_fill_price.

        Called synchronously before _close_callback fires so that sequential window
        capital recycling uses the real exit fill price rather than returning slot_capital
        with cap_pnl=0.  Limit orders that were confirmed filled by place_stock_order's
        _is_filled check typically succeed on attempt 1 (no extra delay).  Market
        orders may need 1-2 polls (filled_avg_price=None on the first response).
        """
        if not pos.exit_order_id:
            return
        for attempt in range(1, max_attempts + 1):
            try:
                status = self._client.order_status(pos.exit_order_id)
            except Exception:
                logger.warning(
                    "order_status call failed for %s (attempt %d)", pos.exit_order_id, attempt,
                )
                if attempt < max_attempts:
                    time.sleep(interval)
                continue

            order_status_val = status.get("status", "")
            fill_price_raw = status.get("filled_avg_price")

            if order_status_val in ("canceled", "cancelled", "rejected"):
                logger.warning(
                    "FILL_MISS exit order %s was %s with no fill — %s may still be "
                    "open at broker; manual intervention required",
                    pos.exit_order_id, order_status_val, pos.ticker,
                )
                return

            if fill_price_raw is None or fill_price_raw == 0:
                if attempt < max_attempts:
                    time.sleep(interval)
                continue

            try:
                pos.exit_fill_price = _D(str(fill_price_raw))
                logger.info(
                    "Exit fill confirmed: order=%s fill=%.4f (attempt %d)",
                    pos.exit_order_id, float(pos.exit_fill_price), attempt,
                )
                return
            except Exception:
                logger.warning(
                    "Invalid fill price %r for order %s — skipping poll",
                    fill_price_raw, pos.exit_order_id,
                )
                return

        logger.warning(
            "Exit fill price not confirmed after %d attempts for %s — "
            "capital returned at cost basis",
            max_attempts, pos.exit_order_id,
        )

    def _refresh_fill_prices(self, positions: list):
        for p in positions:
            if p.entry_fill_price is None and p.entry_order_id:
                try:
                    s = self._client.order_status(p.entry_order_id)
                    if s.get("filled_avg_price") is not None:
                        p.entry_fill_price = _D(str(s["filled_avg_price"]))
                except Exception:
                    pass
            if p.is_closed and p.exit_fill_price is None and p.exit_order_id:
                try:
                    s = self._client.order_status(p.exit_order_id)
                    filled_price = s.get("filled_avg_price")
                    order_status_val = s.get("status", "")
                    if (filled_price is not None
                            and filled_price != 0
                            and order_status_val not in ("canceled", "cancelled", "rejected")):
                        p.exit_fill_price = _D(str(filled_price))
                except Exception:
                    pass

    def print_status(self):
        now = datetime.now(ET)
        with self._lock:
            open_pos = [p for p in self._positions if not p.is_closed]
            closed_pos = [p for p in self._positions if p.is_closed]

        has_sim = any(p.simulated_entry_mid is not None for p in self._positions)

        if not has_sim:
            self._refresh_fill_prices(open_pos + closed_pos)

        def _fmt(dt: Optional[datetime]) -> str:
            return dt.strftime("%H:%M") if dt else "—"

        def _pnl(entry, exit_, signal, pos) -> Optional[object]:
            if entry is None or exit_ is None:
                return None
            if pos.trade_type == "stock" and pos.signal == "BEARISH":
                raw = entry - exit_
            else:
                raw = exit_ - entry
            if pos.trade_type == "stock":
                return raw * _D(pos.shares)
            return raw * _D(pos.contracts) * _D("100")

        def _pnl_str(pnl) -> str:
            if pnl is None:
                return ""
            sign = "+" if pnl >= 0 else ""
            return f"  {sign}${pnl:.2f}"

        bar = "━" * 82
        sep = "─" * 80
        lines = [
            "",
            bar,
            f"  POSITION STATUS  {now.strftime('%H:%M ET')}  |  "
            f"open={len(open_pos)}  closed={len(closed_pos)}",
            bar,
        ]

        if open_pos:
            lines.append("  OPEN POSITIONS")
            lines.append(f"  {sep}")
            for p in open_pos:
                if has_sim:
                    entry_price = p.simulated_entry_mid
                    current_mid = p.simulated_entry_mid
                else:
                    entry_price = p.entry_fill_price
                    if p.trade_type == "stock":
                        try:
                            raw_quote = self._client.get_stock_quote(
                                p.ticker,
                                **({"feed": self._alpaca_feed} if self._alpaca_feed is not None else {})
                            )
                            bid_f, ask_f = _stock_bid_ask(raw_quote)
                            current_mid = _D(str((bid_f + ask_f) / 2))
                        except Exception:
                            current_mid = None
                    else:
                        current_mid = self._fetch_option_mid(p.option_symbol)
                unrealized = _pnl(entry_price, current_mid, p.signal, p)
                entry_str = f"  entry=${entry_price:.2f}" if entry_price else ""
                unreal_str = (
                    f"  unreal={_pnl_str(unrealized).strip()}"
                    if unrealized is not None
                    else ""
                )
                if p.trade_type == "stock":
                    qty_str = f"x{p.shares}sh"
                    sym_str = f"{p.ticker} [stock]"
                else:
                    qty_str = f"x{p.contracts}"
                    sym_str = p.option_symbol
                lines.append(
                    f"  {p.ticker:<7} {p.signal:<9} {sym_str:<26} "
                    f"{qty_str}  in={_fmt(p.entry_time)}{entry_str}{unreal_str}"
                )
        else:
            lines.append("  No open positions")

        if closed_pos:
            lines.append("")
            lines.append("  CLOSED POSITIONS")
            lines.append(f"  {sep}")
            total_pnl = _D("0")
            for p in closed_pos:
                if has_sim:
                    entry_price = p.simulated_entry_mid
                    exit_price = p.simulated_exit_mid
                else:
                    entry_price = p.entry_fill_price
                    exit_price = p.exit_fill_price
                pnl = _pnl(entry_price, exit_price, p.signal, p)
                if pnl is not None:
                    total_pnl += pnl
                if p.trade_type == "stock":
                    qty_str = f"x{p.shares}sh"
                    sym_str = f"{p.ticker} [stock]"
                else:
                    qty_str = f"x{p.contracts}"
                    sym_str = p.option_symbol
                lines.append(
                    f"  {p.ticker:<7} {p.signal:<9} {sym_str:<26} "
                    f"{qty_str}  {_fmt(p.entry_time)}→{_fmt(p.exit_time)}"
                    f"  {p.exit_reason}{_pnl_str(pnl)}"
                )
            any_pnl = any(
                _pnl(
                    p.simulated_entry_mid if has_sim else p.entry_fill_price,
                    p.simulated_exit_mid if has_sim else p.exit_fill_price,
                    p.signal,
                    p,
                )
                is not None
                for p in closed_pos
            )
            if any_pnl:
                sign = "+" if total_pnl >= 0 else ""
                lines.append(f"  {sep}")
                lines.append(f"  Running P&L: {sign}${total_pnl:.2f}")

        lines.append(f"{bar}\n")
        logger.info("\n".join(lines))

    def print_summary(self):
        has_sim = any(pos.simulated_entry_mid is not None for pos in self._positions)
        if not has_sim:
            self._refresh_fill_prices(self._positions)

        def _fmt_time(dt: Optional[datetime]) -> str:
            return dt.strftime("%H:%M") if dt else "—"

        def _effective_contracts(pos) -> int:
            return pos.closed_contracts if pos.closed_contracts > 0 else pos.contracts

        def _position_pnl(pos, entry_price, exit_price):
            if entry_price is None or exit_price is None:
                return None
            if pos.trade_type == "stock" and pos.signal == "BEARISH":
                raw = entry_price - exit_price
            else:
                raw = exit_price - entry_price
            if pos.trade_type == "stock":
                return raw * _D(pos.shares)
            return raw * _D(_effective_contracts(pos)) * _D("100")

        def _position_cost(pos, entry_price):
            if entry_price is None:
                return None
            if pos.trade_type == "stock":
                return entry_price * _D(pos.shares)
            return entry_price * _D(_effective_contracts(pos)) * _D("100")

        def _print_totals(positions, get_entry, get_exit, emit, width):
            total_pnl = _D("0")
            total_cost = _D("0")
            total_cap_pnl = _D("0")
            has_any = False
            has_cap = False
            for pos in positions:
                entry = get_entry(pos)
                exit_ = get_exit(pos)
                pnl = _position_pnl(pos, entry, exit_)
                cost = _position_cost(pos, entry)
                if pnl is not None and cost is not None and cost > 0:
                    total_pnl += pnl
                    total_cost += cost
                    has_any = True
                    if pos.slot_capital is not None and entry is not None and entry > 0:
                        if pos.trade_type == "stock" and pos.signal == "BEARISH":
                            raw = entry - exit_
                        else:
                            raw = exit_ - entry
                        if pos.trade_type == "stock":
                            total_cap_pnl += pos.slot_capital / entry * raw
                        else:
                            total_cap_pnl += _D(_effective_contracts(pos)) * _D("100") * raw
                        has_cap = True
            if not has_any:
                return
            pct = float(total_pnl / total_cost * 100) if total_cost > 0 else 0.0
            sign = "+" if total_pnl >= 0 else ""
            pct_sign = "+" if pct >= 0 else ""
            summary = f"  Daily P&L: {sign}${total_pnl:.2f}  ({pct_sign}{pct:.2f}%  on  ${total_cost:.0f} deployed)"
            if has_cap and self._initial_capital:
                cap_pct = float(total_cap_pnl / _D(str(self._initial_capital)) * 100)
                cap_sign = "+" if total_cap_pnl >= 0 else "-"
                cap_pct_sign = "+" if cap_pct >= 0 else ""
                summary += (
                    f"  │  cap: {cap_sign}${abs(float(total_cap_pnl)):.2f}"
                    f" ({cap_pct_sign}{cap_pct:.2f}%) - with fractional shares"
                )
            emit(f"  {'─' * (width - 2)}")
            emit(summary)

        def _trade_label(pos) -> str:
            if pos.is_doubledown_addon:
                return "[Doubledown]"
            if pos.reentry_type is None:
                return f"[{pos.signal.capitalize()}]"
            if pos.reentry_type == "reversal":
                return "[Reversal Trade]"
            if pos.reentry_type == "bearish_reentry":
                return "[Bearish Cont.]"
            if pos.reentry_type == "bullish_reentry":
                return "[Bullish Cont.]"
            return f"[{pos.signal.capitalize()}]"

        lines = []

        def _emit(line=""):
            lines.append(line)

        if has_sim:
            width = 132
            _emit("=" * width)
            _emit("  DAILY TRADE SUMMARY  [SIMULATE MODE]")
            _emit("=" * width)
            _emit(
                f"  {'Ticker':<7} {'Signal':<16} {'Instrument':<26} {'Qty':>6}"
                f"  {'Entry':>5} {'Exit':>5}  {'EntryMid':>9} {'ExitMid':>9} {'P&L':>10}  {'%P&L':>7}  Exit Reason"
            )
            _emit(f"  {'─' * 130}")
            for pos in self._positions:
                entry_mid = pos.simulated_entry_mid
                exit_mid = pos.simulated_exit_mid
                pnl = _position_pnl(pos, entry_mid, exit_mid)
                if pnl is not None:
                    pnl_str = f"+${abs(pnl):.2f}" if pnl >= 0 else f"-${abs(pnl):.2f}"
                    entry_str = f"${entry_mid:.2f}"
                    exit_str = f"${exit_mid:.2f}"
                    if pos.trade_type == "stock" and pos.signal == "BEARISH":
                        pnl_per_share = entry_mid - exit_mid
                    else:
                        pnl_per_share = exit_mid - entry_mid
                    if entry_mid and entry_mid > 0:
                        pnl_pct = float(pnl_per_share / entry_mid * 100)
                        pnl_pct_str = f"+{pnl_pct:.2f}%" if pnl_pct >= 0 else f"{pnl_pct:.2f}%"
                    else:
                        pnl_pct_str = "—"
                else:
                    pnl_str = entry_str = exit_str = pnl_pct_str = "—"
                if pos.trade_type == "stock":
                    sym_str = f"{pos.ticker} [stock]"
                    qty_str = f"{pos.shares}sh"
                else:
                    sym_str = pos.option_symbol
                    qty_str = str(_effective_contracts(pos))
                exit_display_time = (
                    pos.exit_time + timedelta(minutes=5)
                    if pos.exit_time is not None and pos.exit_reason != "end_of_day"
                    else pos.exit_time
                )
                _emit(
                    f"  {pos.ticker:<7} {_trade_label(pos):<16} {sym_str:<26} "
                    f"{qty_str:>6}"
                    f"  {_fmt_time(pos.entry_time):>5} {_fmt_time(exit_display_time):>5}"
                    f"  {entry_str:>9} {exit_str:>9} {pnl_str:>10}  {pnl_pct_str:>7}"
                    f"  {pos.exit_reason or 'open'}"
                )
            _print_totals(
                self._positions,
                lambda p: p.simulated_entry_mid,
                lambda p: p.simulated_exit_mid,
                _emit,
                width,
            )
            _emit("=" * width)
        else:
            width = 132
            _emit("=" * width)
            _emit("  DAILY TRADE SUMMARY")
            _emit("=" * width)
            _emit(
                f"  {'Ticker':<7} {'Signal':<16} {'Instrument':<26} {'Qty':>6}"
                f"  {'Entry':>5} {'Exit':>5}  {'EntryFill':>9} {'ExitFill':>8} {'P&L':>10}  {'%P&L':>7}  Exit Reason"
            )
            _emit(f"  {'─' * 130}")
            for pos in self._positions:
                entry_fill = pos.entry_fill_price
                exit_fill = pos.exit_fill_price
                pnl = _position_pnl(pos, entry_fill, exit_fill)
                if pnl is not None:
                    pnl_str = f"+${abs(pnl):.2f}" if pnl >= 0 else f"-${abs(pnl):.2f}"
                    entry_str = f"${entry_fill:.2f}"
                    exit_str = f"${exit_fill:.2f}"
                    if pos.trade_type == "stock" and pos.signal == "BEARISH":
                        pnl_per_unit = entry_fill - exit_fill
                    else:
                        pnl_per_unit = exit_fill - entry_fill
                    if entry_fill and entry_fill > 0:
                        pnl_pct = float(pnl_per_unit / entry_fill * 100)
                        pnl_pct_str = f"+{pnl_pct:.2f}%" if pnl_pct >= 0 else f"{pnl_pct:.2f}%"
                    else:
                        pnl_pct_str = "—"
                else:
                    pnl_str = entry_str = exit_str = pnl_pct_str = "—"
                if pos.trade_type == "stock":
                    sym_str = f"{pos.ticker} [stock]"
                    qty_str = f"{pos.shares}sh"
                else:
                    sym_str = pos.option_symbol
                    qty_str = str(_effective_contracts(pos))
                _emit(
                    f"  {pos.ticker:<7} {_trade_label(pos):<16} {sym_str:<26} "
                    f"{qty_str:>6}"
                    f"  {_fmt_time(pos.entry_time):>5} {_fmt_time(pos.exit_time):>5}"
                    f"  {entry_str:>9} {exit_str:>8} {pnl_str:>10}  {pnl_pct_str:>7}"
                    f"  {pos.exit_reason or 'open'}"
                )
            _print_totals(
                self._positions,
                lambda p: p.entry_fill_price,
                lambda p: p.exit_fill_price,
                _emit,
                width,
            )
            _emit("=" * width)

        for line in lines:
            _emit_raw(line)

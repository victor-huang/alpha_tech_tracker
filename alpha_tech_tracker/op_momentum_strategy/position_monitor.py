import logging
import threading
from datetime import datetime
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
from .order_executor import _place_with_fill_escalation, place_stock_order
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

ET = pytz.timezone("America/New_York")

_QUICK_EXIT_MAX_SECONDS = 480  # positions held < 8 min trigger entry-price-first sell


def _quick_exit_entry_price(pos: ActivePosition) -> "Optional[float]":
    """
    Return pos.entry_fill_price (as float) when the position was opened recently
    and qualifies for a quick-exit: try selling at the entry fill price first so
    we avoid locking in a loss on a position that never had time to develop.

    Returns None if the position has been held too long, entry_time is unknown,
    or entry_fill_price was not recorded.
    """
    if pos.entry_fill_price is None or pos.entry_time is None:
        return None
    elapsed = (_now_et() - pos.entry_time).total_seconds()
    if elapsed < _QUICK_EXIT_MAX_SECONDS:
        return float(pos.entry_fill_price)
    return None


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
        self._positions: list = []
        self._reentry_watchers: list = []
        self._lock = threading.Lock()

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
        ma20 = latest.get("MA20")
        ma20_val = _D(ma20) if ma20 is not None and not pd.isna(ma20) else None
        ma50 = latest.get("MA50")
        ma50_val = _D(ma50) if ma50 is not None and not pd.isna(ma50) else None

        with self._lock:
            for pos in self._positions:
                if pos.ticker != ticker or pos.is_closed:
                    continue
                if pos.entry_bar_time is not None and bar_time == pos.entry_bar_time:
                    continue
                self._evaluate_stop(pos, close, high, ma20_val, ma50_val, bar_time)

            fired_watchers = self._collect_fired_watchers(ticker, close, bar_time)

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
        ma20: Optional[object],
        ma50: Optional[object],
        bar_time=None,
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
                self._close_position(pos, "max_loss")
                return

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
                override = pos.hard_stop_price
            elif exit_reason == "fallback_20pct":
                if pos.signal == "BEARISH":
                    override = pos.fallback_price
                elif high >= pos.fallback_price:
                    # Bar traded at/above fallback level before closing below it;
                    # exit at fallback_price to match backtest stop-order simulation.
                    override = pos.fallback_price
            self._close_position(pos, exit_reason, exit_stock_price_override=override)
        else:
            if bar_time is not None and bar_time == pos.last_evaluated_bar_time:
                return  # same bar repeated poll — don't double-count
            pos.last_evaluated_bar_time = bar_time
            pos.bars_held += 1

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
                raw_quote = self._client.get_stock_quote(pos.ticker)
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

        mid_str = f" @ ~${float(mid):.2f}" if mid is not None else ""
        prefix = "[SIMULATE] " if self._mock_trade_execution else ""
        _notify(f"{prefix}SELL {pos.ticker} x{pos.shares} shares{mid_str} reason={reason}")

        if self._mock_trade_execution:
            sim_mid = (
                mid.quantize(_D("0.01"), rounding=ROUND_HALF_UP)
                if mid is not None
                else _D("0")
            )
            pos.simulated_exit_mid = sim_mid
            logger.info(
                "SIMULATE SELL_CLOSE %s shares=%d simulated_fill=%.2f (no order placed)",
                pos.ticker,
                pos.shares,
                sim_mid,
            )
            return

        try:
            if reason == "end_of_day":
                logger.info(
                    "EOD SELL_CLOSE stock market order: %s %d shares",
                    pos.ticker,
                    pos.shares,
                )
                order = self._client.place_stock_order(
                    symbol=pos.ticker,
                    quantity=pos.shares,
                    side="SELL",
                    order_type="MARKET",
                )
            else:
                logger.info(
                    "Placing SELL_CLOSE stock with fill escalation: %s %d shares",
                    pos.ticker,
                    pos.shares,
                )
                order = place_stock_order(
                    client=self._client,
                    ticker=pos.ticker,
                    shares=pos.shares,
                    order_action="SELL_CLOSE",
                )
            pos.exit_order_id = order.get("order_id")
            logger.info("Stock close order placed: %s", pos.exit_order_id)
        except Exception:
            logger.exception("Failed to place stock close order for %s", pos.ticker)

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
            if reason == "end_of_day":
                logger.info(
                    "EOD SELL_CLOSE market order: %s %d contracts",
                    pos.option_symbol,
                    pos.contracts,
                )
                order = self._client.place_option_order(
                    symbol=pos.ticker,
                    option_key=None,
                    price_type="MARKET",
                    option_type=option_type,
                    order_action="SELL_CLOSE",
                    quantity=pos.contracts,
                    _option_symbol_override=pos.option_symbol,
                )
            else:
                quick_exit_fill_price = _quick_exit_entry_price(pos)
                if quick_exit_fill_price is not None:
                    logger.info(
                        "Placing SELL_CLOSE quick-exit: %s %d contracts"
                        " (held < %ds, will try entry_fill_price first)",
                        pos.option_symbol,
                        pos.contracts,
                        _QUICK_EXIT_MAX_SECONDS,
                    )
                else:
                    logger.info(
                        "Placing SELL_CLOSE with fill escalation: %s %d contracts",
                        pos.option_symbol,
                        pos.contracts,
                    )
                opm = self._option_price_monitor
                se = self._signal_engine
                if opm is not None:
                    def _exit_fair_price_fn(
                        _ticker=pos.ticker,
                        _symbol=pos.option_symbol,
                        _otype=option_type_lower,
                        _entry_stock=pos.entry_stock_price,
                    ):
                        bar = se.get_latest_bar(_ticker) if se else None
                        stock_price = _D(str(bar["Close"])) if bar is not None else _D(str(_entry_stock))
                        return opm.get_fair_price(_ticker, _symbol, _otype, stock_price)
                else:
                    _exit_fair_price_fn = None
                order = _place_with_fill_escalation(
                    client=self._client,
                    ticker=pos.ticker,
                    option_symbol=pos.option_symbol,
                    option_type=option_type,
                    contracts=pos.contracts,
                    order_action="SELL_CLOSE",
                    entry_fill_price=quick_exit_fill_price,
                    get_fair_price_fn=_exit_fair_price_fn,
                )
            pos.exit_order_id = order.get("order_id")
            logger.info("Close order placed: %s", pos.exit_order_id)
        except Exception:
            logger.exception("Failed to place close order for %s", pos.option_symbol)

    def close_all(self, reason: str = "end_of_day"):
        with self._lock:
            open_positions = [p for p in self._positions if not p.is_closed]
            self._reentry_watchers.clear()
        for pos in open_positions:
            with self._lock:
                if not pos.is_closed:
                    self._close_position(pos, reason)

    def _fetch_option_mid(self, option_symbol: str) -> Optional[object]:
        try:
            q = self._client.get_option_quote_by_occ(option_symbol)
            return _D(str(q["mid"]))
        except Exception:
            return None

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
                    if s.get("filled_avg_price") is not None:
                        p.exit_fill_price = _D(str(s["filled_avg_price"]))
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
        print(f"\n{bar}")
        print(
            f"  POSITION STATUS  {now.strftime('%H:%M ET')}  |  "
            f"open={len(open_pos)}  closed={len(closed_pos)}"
        )
        print(bar)

        if open_pos:
            print("  OPEN POSITIONS")
            print(f"  {sep}")
            for p in open_pos:
                if has_sim:
                    entry_price = p.simulated_entry_mid
                    current_mid = p.simulated_entry_mid
                else:
                    entry_price = p.entry_fill_price
                    if p.trade_type == "stock":
                        try:
                            raw_quote = self._client.get_stock_quote(p.ticker)
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
                print(
                    f"  {p.ticker:<7} {p.signal:<9} {sym_str:<26} "
                    f"{qty_str}  in={_fmt(p.entry_time)}{entry_str}{unreal_str}"
                )
        else:
            print("  No open positions")

        if closed_pos:
            print(f"\n  CLOSED POSITIONS")
            print(f"  {sep}")
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
                print(
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
                print(f"  {sep}")
                print(f"  Running P&L: {sign}${total_pnl:.2f}")

        print(f"{bar}\n")

    def print_summary(self):
        has_sim = any(pos.simulated_entry_mid is not None for pos in self._positions)
        if not has_sim:
            self._refresh_fill_prices(self._positions)

        def _fmt_time(dt: Optional[datetime]) -> str:
            return dt.strftime("%H:%M") if dt else "—"

        def _position_pnl(pos, entry_price, exit_price):
            if entry_price is None or exit_price is None:
                return None
            if pos.trade_type == "stock" and pos.signal == "BEARISH":
                raw = entry_price - exit_price
            else:
                raw = exit_price - entry_price
            if pos.trade_type == "stock":
                return raw * _D(pos.shares)
            return raw * _D(pos.contracts) * _D("100")

        def _position_cost(pos, entry_price):
            if entry_price is None:
                return None
            if pos.trade_type == "stock":
                return entry_price * _D(pos.shares)
            return entry_price * _D(pos.contracts) * _D("100")

        def _print_totals(positions, get_entry, get_exit, width):
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
                            total_cap_pnl += _D(pos.contracts) * _D("100") * raw
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
                    f" ({cap_pct_sign}{cap_pct:.2f}%)"
                )
            print(f"  {'─' * (width - 2)}")
            print(summary)

        def _trade_label(pos) -> str:
            if pos.reentry_type is None:
                return f"[{pos.signal.capitalize()}]"
            if pos.reentry_type == "reversal":
                return "[Reversal Trade]"
            if pos.reentry_type == "bearish_reentry":
                return "[Bearish Cont.]"
            if pos.reentry_type == "bullish_reentry":
                return "[Bullish Cont.]"
            return f"[{pos.signal.capitalize()}]"

        if has_sim:
            width = 132
            print(f"\n{'=' * width}")
            print("  DAILY TRADE SUMMARY  [SIMULATE MODE]")
            print(f"{'=' * width}")
            print(
                f"  {'Ticker':<7} {'Signal':<16} {'Instrument':<26} {'Qty':>6}"
                f"  {'Entry':>5} {'Exit':>5}  {'EntryMid':>9} {'ExitMid':>9} {'P&L':>10}  {'%P&L':>7}  Exit Reason"
            )
            print(f"  {'─' * 130}")
            for pos in self._positions:
                entry_mid = pos.simulated_entry_mid
                exit_mid = pos.simulated_exit_mid
                pnl = _position_pnl(pos, entry_mid, exit_mid)
                if pnl is not None:
                    pnl_str = f"+${pnl:.2f}" if pnl >= 0 else f"-${abs(pnl):.2f}"
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
                    qty_str = str(pos.contracts)
                print(
                    f"  {pos.ticker:<7} {_trade_label(pos):<16} {sym_str:<26} "
                    f"{qty_str:>6}"
                    f"  {_fmt_time(pos.entry_time):>5} {_fmt_time(pos.exit_time):>5}"
                    f"  {entry_str:>9} {exit_str:>9} {pnl_str:>10}  {pnl_pct_str:>7}"
                    f"  {pos.exit_reason or 'open'}"
                )
            _print_totals(
                self._positions,
                lambda p: p.simulated_entry_mid,
                lambda p: p.simulated_exit_mid,
                width,
            )
            print(f"{'=' * width}\n")
        else:
            width = 132
            print(f"\n{'=' * width}")
            print("  DAILY TRADE SUMMARY")
            print(f"{'=' * width}")
            print(
                f"  {'Ticker':<7} {'Signal':<16} {'Instrument':<26} {'Qty':>6}"
                f"  {'Entry':>5} {'Exit':>5}  {'EntryFill':>9} {'ExitFill':>8} {'P&L':>10}  {'%P&L':>7}  Exit Reason"
            )
            print(f"  {'─' * 130}")
            for pos in self._positions:
                entry_fill = pos.entry_fill_price
                exit_fill = pos.exit_fill_price
                pnl = _position_pnl(pos, entry_fill, exit_fill)
                if pnl is not None:
                    pnl_str = f"+${pnl:.2f}" if pnl >= 0 else f"-${abs(pnl):.2f}"
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
                    qty_str = str(pos.contracts)
                print(
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
                width,
            )
            print(f"{'=' * width}\n")

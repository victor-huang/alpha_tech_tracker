import logging
import threading
from datetime import datetime
from decimal import ROUND_HALF_UP
from typing import Optional

import pandas as pd
import pytz

from alpaca.data.requests import OptionLatestQuoteRequest

from alpha_tech_tracker.trade_api.alpaca_client.client import AlpacaAPIClient

from .config import (
    ARMED_MA20_EXIT,
    MAX_LOSS_PCT,
    TRAILING_MA,
    _notify,
    _fmt_option,
)
from .models import ActivePosition, ReentryWatcher, _D, _stock_bid_ask
from .order_executor import _place_with_fill_escalation, place_stock_order

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


class PositionMonitor:
    """Monitors open option positions and exits on stop conditions."""

    def __init__(
        self,
        alpaca_client: AlpacaAPIClient,
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

    def on_bar(self, ticker: str):
        latest = self._signal_engine.get_latest_bar(ticker)
        if latest is None:
            return

        bar_time = latest.name
        close = _D(latest["Close"])
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
                self._evaluate_stop(pos, close, ma20_val, ma50_val)

            self._check_reentry_watchers(ticker, close, bar_time)

    def _trailing_armed(self, pos: ActivePosition, close) -> bool:
        """
        Returns True when the trailing MA stop is allowed to fire.

        Primary positions (trailing_arm_price=None) use the existing behaviour:
        the MA trailing stop is always eligible once armed via hard_stop_armed.
        Re-entry positions gate the trailing stop behind a price threshold
        (entry ± or_range) to match the backtest arming condition.
        """
        if pos.trailing_arm_price is None:
            return True
        if pos.signal == "BULLISH":
            return close >= pos.trailing_arm_price
        return close <= pos.trailing_arm_price

    def _evaluate_stop(
        self,
        pos: ActivePosition,
        close,
        ma20: Optional[object],
        ma50: Optional[object],
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
            self._close_position(pos, exit_reason)
        else:
            pos.bars_held += 1

    def _maybe_create_reentry_watcher(self, pos: ActivePosition, reason: str):
        if reason not in ("hard_stop", "fallback_20pct"):
            return

        midpoint = (_D(str(pos.or_high)) + _D(str(pos.or_low))) / _D("2")

        # Reversal takes priority over bearish re-entry for the same closed position.
        if (
            self._enable_reversal
            and pos.signal == "BEARISH"
            and pos.bars_held <= self._reversal_max_bars
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
                    primary_exit_bar_time=pos.entry_bar_time,
                )
            )
            logger.info(
                "Reversal watcher created for %s (bars_held=%d)", pos.ticker, pos.bars_held
            )
            return  # reversal and bearish re-entry are mutually exclusive

        if (
            self._enable_bearish_reentry
            and pos.signal == "BEARISH"
            and pos.bars_held <= self._bearish_reentry_max_bars
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
                    primary_exit_bar_time=pos.entry_bar_time,
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
                    primary_exit_bar_time=pos.entry_bar_time,
                )
            )
            logger.info(
                "Bullish re-entry watcher created for %s (bars_held=%d)",
                pos.ticker,
                pos.bars_held,
            )

    def _check_reentry_watchers(self, ticker: str, close, bar_time):
        if not self._reentry_watchers:
            return

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

        for w in fired:
            self._reentry_watchers.remove(w)
            logger.info(
                "Re-entry trigger fired [%s] %s close=%.2f",
                w.reentry_type,
                w.ticker,
                float(close),
            )
            if self._re_entry_callback:
                threading.Thread(
                    target=self._re_entry_callback,
                    args=(w, close),
                    daemon=True,
                ).start()

    def _close_position(self, pos: ActivePosition, reason: str):
        pos.is_closed = True
        pos.exit_reason = reason
        pos.exit_time = datetime.now(ET)
        self._maybe_create_reentry_watcher(pos, reason)

        if pos.trade_type == "stock":
            self._close_stock_position(pos, reason)
        else:
            self._close_option_position(pos, reason)

    def _close_stock_position(self, pos: ActivePosition, reason: str):
        logger.info(
            "EXIT %s %s reason=%s shares=%d",
            pos.ticker,
            pos.signal,
            reason,
            pos.shares,
        )
        mid = None
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

        if self._mock_trade_execution:
            sim_mid = (
                mid.quantize(_D("0.01"), rounding=ROUND_HALF_UP)
                if mid is not None
                else _D("0")
            )
            pos.simulated_exit_mid = sim_mid
            _notify(
                f"[SIMULATE] SELL {pos.ticker} x{pos.shares} shares reason={reason} @ ~{sim_mid}"
            )
            logger.info(
                "SIMULATE SELL_CLOSE %s shares=%d simulated_fill=%.2f (no order placed)",
                pos.ticker,
                pos.shares,
                sim_mid,
            )
            return

        try:
            logger.info(
                "Placing SELL_CLOSE stock with fill escalation: %s %d shares",
                pos.ticker,
                pos.shares,
            )
            _notify(f"SELL {pos.ticker} x{pos.shares} shares reason={reason}")
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

    def _close_option_position(self, pos: ActivePosition, reason: str):
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
        if self._option_price_monitor:
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
            try:
                quote_resp = self._client._option_data_client.get_option_latest_quote(
                    OptionLatestQuoteRequest(symbol_or_symbols=[pos.option_symbol])
                )
                quote = quote_resp[pos.option_symbol]
                bid = _D(quote.bid_price)
                ask = _D(quote.ask_price)
                mid = (bid + ask) / _D("2")
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

        if self._mock_trade_execution:
            sim_mid = (
                mid.quantize(_D("0.01"), rounding=ROUND_HALF_UP)
                if mid is not None
                else _D("0")
            )
            pos.simulated_exit_mid = sim_mid
            _notify(
                f"[SIMULATE] SELL {_fmt_option(pos.option_symbol)} x{pos.contracts} reason={reason} @ ~{sim_mid}"
            )
            logger.info(
                "SIMULATE SELL_CLOSE %s contracts=%d simulated_fill=%.2f (no order placed)",
                pos.option_symbol,
                pos.contracts,
                sim_mid,
            )
            return

        try:
            option_type = "CALL" if pos.signal == "BULLISH" else "PUT"
            logger.info(
                "Placing SELL_CLOSE with fill escalation: %s %d contracts",
                pos.option_symbol,
                pos.contracts,
            )
            _notify(
                f"SELL {_fmt_option(pos.option_symbol)} x{pos.contracts} reason={reason} closing {pos.ticker}"
            )
            order = _place_with_fill_escalation(
                client=self._client,
                ticker=pos.ticker,
                option_symbol=pos.option_symbol,
                option_type=option_type,
                contracts=pos.contracts,
                order_action="SELL_CLOSE",
            )
            pos.exit_order_id = order.get("order_id")
            logger.info("Close order placed: %s", pos.exit_order_id)
        except Exception:
            logger.exception("Failed to place close order for %s", pos.option_symbol)

    def close_all(self, reason: str = "end_of_day"):
        with self._lock:
            for pos in self._positions:
                if not pos.is_closed:
                    self._close_position(pos, reason)
            self._reentry_watchers.clear()

    def _fetch_option_mid(self, option_symbol: str) -> Optional[object]:
        try:
            resp = self._client._option_data_client.get_option_latest_quote(
                OptionLatestQuoteRequest(symbol_or_symbols=[option_symbol])
            )
            q = resp[option_symbol]
            return (_D(q.bid_price) + _D(q.ask_price)) / _D("2")
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

        def _fmt_time(dt: Optional[datetime]) -> str:
            return dt.strftime("%H:%M") if dt else "—"

        if has_sim:
            width = 114
            print(f"\n{'=' * width}")
            print("  DAILY TRADE SUMMARY  [SIMULATE MODE]")
            print(f"{'=' * width}")
            print(
                f"  {'Ticker':<7} {'Signal':<9} {'Instrument':<26} {'Qty':>6}"
                f"  {'Entry':>5} {'Exit':>5}  {'EntryMid':>9} {'ExitMid':>9} {'P&L':>10}  Exit Reason"
            )
            print(f"  {'─' * 112}")
            for pos in self._positions:
                entry_mid = pos.simulated_entry_mid
                exit_mid = pos.simulated_exit_mid
                if entry_mid is not None and exit_mid is not None:
                    raw_pnl = exit_mid - entry_mid
                    if pos.trade_type == "stock":
                        pnl_total = raw_pnl * _D(pos.shares)
                    else:
                        pnl_total = raw_pnl * _D(pos.contracts) * _D("100")
                    pnl_str = (
                        f"+${pnl_total:.2f}"
                        if pnl_total >= 0
                        else f"-${abs(pnl_total):.2f}"
                    )
                    entry_str = f"${entry_mid:.2f}"
                    exit_str = f"${exit_mid:.2f}"
                else:
                    pnl_str = entry_str = exit_str = "—"
                if pos.trade_type == "stock":
                    sym_str = f"{pos.ticker} [stock]"
                    qty_str = f"{pos.shares}sh"
                else:
                    sym_str = pos.option_symbol
                    qty_str = str(pos.contracts)
                print(
                    f"  {pos.ticker:<7} {pos.signal:<9} {sym_str:<26} "
                    f"{qty_str:>6}"
                    f"  {_fmt_time(pos.entry_time):>5} {_fmt_time(pos.exit_time):>5}"
                    f"  {entry_str:>9} {exit_str:>9} {pnl_str:>10}"
                    f"  {pos.exit_reason or 'open'}"
                )
            print(f"{'=' * width}\n")
        else:
            width = 86
            print(f"\n{'=' * width}")
            print("  DAILY TRADE SUMMARY")
            print(f"{'=' * width}")
            print(
                f"  {'Ticker':<7} {'Signal':<9} {'Instrument':<26} {'Qty':>6}"
                f"  {'Entry':>5} {'Exit':>5}  Exit Reason"
            )
            print(f"  {'─' * 84}")
            for pos in self._positions:
                if pos.trade_type == "stock":
                    sym_str = f"{pos.ticker} [stock]"
                    qty_str = f"{pos.shares}sh"
                else:
                    sym_str = pos.option_symbol
                    qty_str = str(pos.contracts)
                print(
                    f"  {pos.ticker:<7} {pos.signal:<9} {sym_str:<26} "
                    f"{qty_str:>6}"
                    f"  {_fmt_time(pos.entry_time):>5} {_fmt_time(pos.exit_time):>5}"
                    f"  {pos.exit_reason or 'open'}"
                )
            print(f"{'=' * width}\n")

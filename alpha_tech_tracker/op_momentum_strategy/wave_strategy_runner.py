"""Trades the wave setup strategy (the monitor's signals) with stock orders, intraday only.

The strategy (`wave_strategy.strategy.WaveSetupStrategy`, `intraday_only=True`) decides; this runner turns its intents
into positions: a fixed per-trade size (balance / slots), skip when every slot is taken or the free balance is short,
orders through `order_executor.place_stock_order`, closes through `PositionMonitor._close_position` (no OR exit rules:
the strategy's exit intents drive every close). Mock execution fills at the strategy's own prices (signal bar close,
stop, target, close), so a mock day matches the monitor's alert CSV one to one. The strategy keeps its reference
prices in live mode too; broker fills are recorded on the positions only.

Not reachable from the trade engine CLI yet (step B2 of dev/active/WAVE_STRATEGY_TRADE_ENGINE_PLAN.md).
"""

import csv
import json
import logging
import os
import threading
import time as time_module
from decimal import Decimal
from pathlib import Path

import pandas as pd

from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.earnings_calendar import load_releases
from alpha_tech_tracker.op_momentum_strategy.cli.daemon import _LOG_DIR
from alpha_tech_tracker.op_momentum_strategy.config import _notify
from alpha_tech_tracker.op_momentum_strategy.models import ActivePosition, _D
from alpha_tech_tracker.op_momentum_strategy.order_executor import place_stock_order
from alpha_tech_tracker.op_momentum_strategy.position_monitor import PositionMonitor
from alpha_tech_tracker.op_momentum_strategy.position_sizer import InsufficientSlotBudgetError, PositionSizer
from alpha_tech_tracker.op_momentum_strategy.short_setups import DEFAULT_SHORT_SETUPS
from alpha_tech_tracker.op_momentum_strategy.wave_strategy.feed import BarFeed
from alpha_tech_tracker.op_momentum_strategy.wave_strategy.intents import (
    BAR_CLOSE,
    ENTER,
    EXIT,
    MOC,
    MOO,
    MOVE_STOP,
    STOP,
    SYSTEM,
    TARGET,
)
from alpha_tech_tracker.op_momentum_strategy.wave_strategy.session import (
    BAR_MINUTES,
    PRE_OPEN_ALERT,
    _now_et,
    is_trading_day,
)
from alpha_tech_tracker.op_momentum_strategy.wave_strategy.strategy import DEFAULT_CLOSE_DECISION_BAR, WaveSetupStrategy
from alpha_tech_tracker.op_momentum_strategy.wave_strategy.trades import InlineExecutor

logger = logging.getLogger(__name__)

DEFAULT_STATE = Path(_LOG_DIR) / "wave_strategy_engine_state.json"
DEFAULT_BALANCE = 20000
DEFAULT_SLOTS = 10
WINDOW_LABEL = "WAVE"
EXIT_REASONS = {STOP: "wave_stop", TARGET: "wave_target", BAR_CLOSE: "wave_giveback", MOC: "wave_close"}
END_OF_DAY = "end_of_day"
TRADE_COLUMNS = ["time", "ticker", "setup", "action", "price", "shares", "order", "pnl"]


def trade_key(trade):
    return f"{trade.ticker}|{trade.setup}|{trade.entry_time.isoformat()}"


class _LatestBars:
    """The latest-bar lookup PositionMonitor expects from a signal engine, served from the strategy's bars."""

    def __init__(self, strategy):
        self._strategy = strategy

    def get_latest_bar(self, ticker):
        bars = self._strategy.bars.get(ticker)
        if bars is None or bars.empty:
            return None
        row = bars.iloc[-1]
        return pd.Series({"Open": row["open"], "High": row["high"], "Low": row["low"], "Close": row["close"]},
                         name=bars.index[-1])


class WaveStrategyRunner:
    def __init__(self, setups_by_ticker, market_data_client, execution_client=None, mock=True,
                 balance=DEFAULT_BALANCE, slots=DEFAULT_SLOTS, state_file=DEFAULT_STATE, trades_dir=_LOG_DIR,
                 executor=None, notify=_notify, now=_now_et, releases_loader=load_releases, daily_closes_loader=None,
                 trend_daily_loader=None, evaluate_fn=None, close_decision_bar=DEFAULT_CLOSE_DECISION_BAR,
                 short_setups=DEFAULT_SHORT_SETUPS, short_gate="qqq-ma50", short_tickers=None, drive_trail=False,
                 drive_reentry=False, trend_filters=()):
        if not mock and execution_client is None:
            raise ValueError("live execution needs an execution client")
        self.mock = mock
        self.client = execution_client
        self.balance = _D(str(balance))
        self.slots = int(slots)
        self.per_trade = self.balance / self.slots
        self.state_file = Path(state_file)
        self.trades_dir = Path(trades_dir)
        self.executor = executor or InlineExecutor()
        self.notify = notify
        self.now = now
        self.lock = threading.RLock()
        if daily_closes_loader is None or trend_daily_loader is None:
            from alpha_tech_tracker.op_momentum_strategy.wave_setup_monitor import _load_daily_bars, _load_daily_closes
            daily_closes_loader = daily_closes_loader or _load_daily_closes
            trend_daily_loader = trend_daily_loader or _load_daily_bars
        self.strategy = WaveSetupStrategy(
            setups_by_ticker, sink=self._on_intent, executor=self.executor, lock=self.lock, persist=self._save_state,
            evaluate_fn=evaluate_fn, now=now, releases_loader=releases_loader, daily_closes_loader=daily_closes_loader,
            trend_daily_loader=trend_daily_loader, close_decision_bar=close_decision_bar, short_setups=short_setups,
            short_gate=short_gate, short_tickers=short_tickers, drive_trail=drive_trail, drive_reentry=drive_reentry,
            trend_filters=trend_filters, intraday_only=True)
        self.feed = BarFeed(market_data_client, on_bar=self._on_bar, on_backfill=self._merge_backfill,
                            alert=self._system_alert, now=now, lock=self.lock)
        self.positions = {}
        self.position_monitor = PositionMonitor(execution_client, _LatestBars(self.strategy),
                                                mock_trade_execution=mock)
        self.sizer = PositionSizer(execution_client)
        self.done = {"pre_open": False, "close": False}

    # --- lifecycle -------------------------------------------------------

    def prepare(self):
        now = self.now()
        tickers = self.strategy.tickers
        self.strategy.start_session(now.date(), self.feed.session_bars(tickers, now))
        self._load_state()
        self.strategy.prepare()
        self.strategy.catch_up()
        self.feed.start_session(self.strategy.session, tickers, self.strategy.close_time, now)
        self._save_state()

    def tick(self):
        now = self.now()
        with self.lock:
            self.feed.flush_due(now)
            if self.feed.backfill is not None:
                self.feed.run_backfill(now)
            if not self.done["pre_open"] and now.time() >= PRE_OPEN_ALERT:
                self.done["pre_open"] = True
                self.strategy.on_pre_open()
            if not self.done["close"] and now.time() >= self.strategy.close_alert_at and (
                    now.time() >= self.strategy.close_alert_latest
                    or self.strategy.all_have_bar(self.strategy.close_decision_bar)):
                self.done["close"] = True
                self.strategy.on_close_decision()
        self.feed.watchdog(now)

    def finish(self, session_over=True):
        """End of session: anything still open is closed at its last close. A stop before the session ends (restart,
        SIGTERM, crash) only saves the state, so the next process picks the open positions up again."""
        with self.lock:
            if not session_over:
                logger.warning("Stopped before the end of the session; %d open positions kept for the restart",
                               len(self.open_positions()))
                self._save_state()
                return
            self.strategy.close_leftovers()
            for pos in self.open_positions():
                last = self.strategy.last_close(pos.ticker)
                price = last if last is not None else pos.entry_stock_price
                self._close(pos, END_OF_DAY, price, "SELL" if pos.signal == "BULLISH" else "COVER", MOC)
            try:
                self._session_summary()
            finally:
                self._save_state()

    def run(self, poll_seconds=1.0):
        today = self.now().date()
        if not is_trading_day(today):
            logger.info("Market closed today (%s); nothing to trade", today)
            return
        self.prepare()
        self.feed.start_stream()
        mode = "mock" if self.mock else "live"
        self._system_alert(f"wave engine started for {today} ({mode}): {len(self.strategy.tickers)} tickers, "
                           f"${self.balance:,.0f} in {self.slots} slots of ${self.per_trade:,.0f}", logging.INFO)
        session_over = False
        try:
            while self.now().time() < self.strategy.session_end:
                self.tick()
                time_module.sleep(poll_seconds)
            session_over = True
        finally:
            self.finish(session_over)
            self.feed.stop()
            self.executor.shutdown(wait=False)

    # --- bars ------------------------------------------------------------

    def _on_bar(self, ticker, bar):
        if not self.strategy.add_bar(ticker, bar):
            return
        logger.info("5-min %-6s %s O=%.2f H=%.2f L=%.2f C=%.2f (%d min)", ticker, f"{bar['time']:%H:%M}",
                    bar["open"], bar["high"], bar["low"], bar["close"], bar.get("minutes", BAR_MINUTES))
        self.strategy.on_bar_exits(ticker, bar)
        self.strategy.on_bar_shorts(ticker, bar)
        if self.strategy.takes_entries(bar["time"]):
            self.strategy.submit_evaluations(ticker, bar["time"])
        self._save_state()

    def _merge_backfill(self, gap_start, fetched):
        if fetched is None:
            return
        bars = self.strategy.bars
        for ticker, frame in fetched.items():
            missing = frame[~frame.index.isin(bars[ticker].index)]
            if not missing.empty:
                bars[ticker] = pd.concat([bars[ticker], missing]).sort_index()
                self.strategy.rebuild_drive_trail(ticker)
                logger.info("%s: backfilled %d bars from %s", ticker, len(missing), f"{gap_start:%H:%M}")
        self._save_state()

    def wait_pending(self):
        self.strategy.wait_pending()

    # --- intents ---------------------------------------------------------

    def _on_intent(self, intent):
        if intent.kind == SYSTEM:
            self._system_alert(intent.message, intent.level)
        elif intent.kind == ENTER:
            self._enter(intent)
        elif intent.kind == EXIT:
            self._exit(intent)
        elif intent.kind == MOVE_STOP:
            pos = self.positions.get(trade_key(intent.trade))
            if pos is not None and not pos.is_closed:
                pos.hard_stop_price = _D(str(intent.price))
                logger.info("WAVE %s", intent.message)
        else:
            logger.info("WAVE %s", intent.message)

    def open_positions(self):
        return [pos for pos in self.positions.values() if not pos.is_closed]

    def _enter(self, intent):
        trade = intent.trade
        if intent.order in (MOC, MOO) or trade.overnight:
            logger.info("WAVE not traded (overnight): %s", intent.message)
            return
        open_positions = self.open_positions()
        open_cost = sum((pos.entry_stock_price * pos.shares for pos in open_positions), Decimal("0"))
        if len(open_positions) >= self.slots:
            return self._skip(intent, f"all {self.slots} slots in use")
        if self.balance - open_cost < self.per_trade:
            return self._skip(intent, f"free balance ${self.balance - open_cost:,.0f} < ${self.per_trade:,.0f}")
        price = _D(str(intent.price))
        try:
            shares, _ = self.sizer.compute_stock(trade.ticker, price, window_budget=self.per_trade, mock=self.mock)
        except InsufficientSlotBudgetError as error:
            return self._skip(intent, str(error))
        long = trade.side == 1
        action = "BUY_OPEN" if long else "SELL_SHORT"
        order_id, fill = f"mock-{trade_key(trade)}", price
        if not self.mock:
            try:
                order = place_stock_order(self.client, trade.ticker, shares, action, signal_price=float(price))
            except Exception:
                logger.exception("WAVE %s order failed for %s", action, trade.ticker)
                self._system_alert(f"ENTRY FAILED {trade.ticker} | {trade.setup} | {action} x{shares}")
                return
            order_id = order.get("order_id")
            if order.get("filled_avg_price"):
                fill = _D(str(order["filled_avg_price"]))
        pos = ActivePosition(
            ticker=trade.ticker, signal="BULLISH" if long else "BEARISH", option_symbol="", entry_order_id=order_id,
            contracts=0, entry_stock_price=fill, or_high=fill, or_low=fill, or_range=_D("0"),
            hard_stop_price=_D(str(trade.stop)) if trade.stop is not None else _D("0"), fallback_price=_D("0"),
            trade_type="stock", shares=int(shares), entry_bar_time=trade.entry_time, entry_time=self.now(),
            window_label=WINDOW_LABEL, slot_capital=self.per_trade,
            simulated_entry_mid=fill if self.mock else None, entry_fill_price=None if self.mock else fill)
        self.position_monitor.add_position(pos)
        self.positions[trade_key(trade)] = pos
        self._record(trade.ticker, trade.setup, intent.action, fill, pos.shares, intent.order)
        self._notify(f"{'[SIMULATE] ' if self.mock else ''}{intent.action} {trade.ticker} x{pos.shares} "
                     f"@ {fill:.2f} | {trade.setup}")

    def _exit(self, intent):
        pos = self.positions.get(trade_key(intent.trade))
        if pos is None or pos.is_closed:
            logger.info("WAVE no open position for: %s", intent.message)
            return
        self._close(pos, EXIT_REASONS.get(intent.order, "wave_exit"), intent.price, intent.action, intent.order,
                    setup=intent.trade.setup)

    def _close(self, pos, reason, price, action, order, setup=None):
        override = _D(str(price)) if price is not None else None
        self.position_monitor._close_position(pos, reason, exit_stock_price_override=override)
        pos.exit_time = self.now()
        if self.mock and override is not None:
            pos.simulated_exit_mid = override  # PositionMonitor rounds its simulated fill to the cent
        exit_price = pos.simulated_exit_mid if self.mock else (pos.exit_fill_price or override)
        self._record(pos.ticker, setup or self._setup_of(pos), action, exit_price, pos.shares, order,
                     pnl=self._pnl(pos, exit_price))

    def _setup_of(self, pos):
        return next((key.split("|")[1] for key, p in self.positions.items() if p is pos), "")

    @staticmethod
    def _pnl(pos, exit_price):
        if exit_price is None:
            return None
        side = 1 if pos.signal == "BULLISH" else -1
        return (_D(str(exit_price)) - pos.entry_stock_price) * pos.shares * side

    def _skip(self, intent, why):
        logger.info("WAVE skipped (%s): %s", why, intent.message)

    # --- output ----------------------------------------------------------

    def _record(self, ticker, setup, action, price, shares, order, pnl=None):
        path = self.trades_dir / f"wave_strategy_engine_trades_{self.strategy.session}.csv"
        is_new = not path.exists()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", newline="") as handle:
            writer = csv.writer(handle)
            if is_new:
                writer.writerow(TRADE_COLUMNS)
            writer.writerow([self.now().isoformat(timespec="seconds"), ticker, setup, action,
                             "" if price is None else f"{float(price):.4f}", shares, order or "",
                             "" if pnl is None else f"{float(pnl):.2f}"])

    def _session_summary(self):
        session = self.strategy.session
        closed = [p for p in self.positions.values() if p.is_closed and p.exit_time is not None
                  and p.exit_time.date() == session]
        if not closed:
            return
        total = sum((self._pnl(p, p.simulated_exit_mid if self.mock else p.exit_fill_price) or Decimal("0")
                     for p in closed), Decimal("0"))
        self._notify(f"{session} wave engine: {len(closed)} trades closed, ${total:+,.2f}")

    def _system_alert(self, message, level=logging.WARNING):
        logger.log(level, "SYSTEM %s", message)
        self._notify(message)

    def _notify(self, message):
        try:
            self.notify(f"[wave engine] {message}")
        except Exception:
            logger.exception("Notification failed")

    # --- state -----------------------------------------------------------

    def _load_state(self):
        if not self.state_file.exists():
            return
        try:
            state = json.loads(self.state_file.read_text())
        except (OSError, ValueError):
            logger.warning("Unreadable state file %s; starting fresh", self.state_file)
            return
        positions = {key: ActivePosition.from_dict(d) for key, d in state.get("positions", {}).items()}
        if not self.strategy.restore(state):
            left = [p for p in positions.values() if not p.is_closed]
            if left:
                self._system_alert("positions from an earlier session are still open in the state file, check the "
                                   "broker: " + ", ".join(f"{p.ticker} x{p.shares}" for p in left))
            return
        self.done.update(state.get("done", {}))
        self.positions = positions
        for pos in positions.values():
            self.position_monitor.add_position(pos)

    def _save_state(self):
        with self.lock:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            state = self.strategy.state()
            state["done"] = self.done
            state["positions"] = {key: pos.to_dict() for key, pos in self.positions.items()}
            temp = self.state_file.with_name(f"{self.state_file.name}.{os.getpid()}.{threading.get_ident()}.tmp")
            temp.write_text(json.dumps(state, indent=1, default=str))
            temp.replace(self.state_file)

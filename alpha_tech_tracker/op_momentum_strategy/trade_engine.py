import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Optional

import pytz

from alpha_tech_tracker.op_momentum_strategy.op_momentum_backtest import fetch_bars
from alpha_tech_tracker.op_momentum_strategy.op_momentum_selector import (
    ROLLING_LOOKBACK_DAYS,
    _safe_bars_end,
    score_ticker,
    select_top_n,
)
from alpha_tech_tracker.trade_api.alpaca_client.client import AlpacaAPIClient

from .config import (
    ARMED_MA20_EXIT,
    BEARISH_MA200,
    EOD_EXIT_TIME,
    MAX_ACTIVE_SYMBOLS,
    MAX_LOSS_PCT,
    OPENING_BARS,
    OPENING_START_TIME,
    RANK_WEIGHTED_SIZING,
    RANK_WEIGHTS,
    REGIME_FILTER,
    REGIME_MA,
    SIGNAL_BUFFER_MINUTES,
    STOP_PCT,
    TICKERS,
    TRAILING_MA,
    _notify,
    _fmt_option,
    disable_notifications,
    enable_notifications,
    ACCOUNT_BUDGET,
)
from .bar_recorder import BarRecorder
from .contract_selector import TimePremiumContractSelector
from .models import ActivePosition, ReentryWatcher, SignalEvent, WindowConfig, _D
from .option_price_monitor import OptionPriceMonitor
from .order_executor import _place_with_fill_escalation, place_stock_order
from .position_monitor import PositionMonitor
from .position_sizer import PositionSizer
from .replay import BarReplayDriver, _now_et, is_replay_mode, set_replay_clock, clear_replay_clock
from .signal_engine import LiveSignalEngine

logger = logging.getLogger(__name__)

ET = pytz.timezone("America/New_York")


class TickerSelector:
    """
    Selects the top N tickers using the momentum selector's composite scoring.

    If called before the opening range closes, falls back to the previous trading
    day so the engine still gets a ranked list to watch.
    """

    def __init__(
        self,
        tickers: list,
        top_n: int,
        stop_pct: float = float(STOP_PCT),
        opening_start_time: str = OPENING_START_TIME,
        opening_bars: int = OPENING_BARS,
        lookback_days: int = ROLLING_LOOKBACK_DAYS,
        regime_filter: bool = False,
        regime_ma: int = 8,
    ):
        self._tickers = tickers
        self._top_n = top_n
        self._stop_pct = stop_pct
        self._opening_start_time = opening_start_time
        self._opening_bars = opening_bars
        self._lookback_days = lookback_days
        self._regime_filter = regime_filter
        self._regime_ma = regime_ma
        self.rolling_stats: dict = {}

    def select(self) -> list:
        today = _now_et().date()

        fetch_start = today - timedelta(days=max(self._lookback_days, 30) + 5)
        ticker_dfs = fetch_bars(
            self._tickers,
            fetch_start,
            _safe_bars_end(today),
            source="alpaca",
            allow_intraday=True,
        )

        result = select_top_n(
            n=self._top_n,
            tickers=self._tickers,
            lookback_days=self._lookback_days,
            opening_bars=self._opening_bars,
            bearish_ma200=BEARISH_MA200,
            stop_pct=self._stop_pct,
            source="alpaca",
            target_date=today,
            ticker_dfs=ticker_dfs,
            opening_start_time=self._opening_start_time,
            regime_filter=self._regime_filter,
            regime_ma=self._regime_ma,
        )
        self.rolling_stats = result.get("rolling_stats", {})

        picks = result["picks"]

        if not picks:
            prev_day = today - timedelta(days=1)
            while prev_day.weekday() >= 5:
                prev_day -= timedelta(days=1)
            logger.info(
                "No picks for today (%s) — falling back to %s for pre-market selection",
                today,
                prev_day,
            )
            result = select_top_n(
                n=self._top_n,
                tickers=self._tickers,
                lookback_days=self._lookback_days,
                opening_bars=self._opening_bars,
                bearish_ma200=BEARISH_MA200,
                stop_pct=self._stop_pct,
                source="alpaca",
                target_date=prev_day,
                ticker_dfs=ticker_dfs,
                opening_start_time=self._opening_start_time,
                regime_filter=self._regime_filter,
                regime_ma=self._regime_ma,
            )
            self.rolling_stats = result.get("rolling_stats", {})
            picks = result["picks"]

        selected = [p["ticker"] for p in picks]
        logger.info(
            "Selector picks: %s | no_signal: %s | negative_ev: %s",
            [{p["ticker"]: f"score={p['score']} ev={p['ev_trade']}%"} for p in picks],
            result.get("no_signal", []),
            result.get("negative_ev", []),
        )
        return selected


class OpMomentumTradeEngine:
    """
    Main orchestrator for the opening-range momentum options strategy.

    Supports one or more intraday trading windows via the `windows` parameter.
    When omitted, runs in single-window mode using `opening_start_time` (backward-compatible).

    Daily flow (multi-window):
      1. Select top tickers by composite score (using first window's OR params).
      2. Start a single LiveSignalEngine watching all windows on one stream.
      3. Per-window: after OR closes, rank buffered signals, enter up to MAX_ACTIVE_SYMBOLS.
         - First-group windows: budget = account_buying_power × capital_fraction
         - Sequential windows: PositionSizer reads live account balance at signal time
      4. Single PositionMonitor tracks all positions; exits on stop or EOD.
    """

    def __init__(
        self,
        alpaca_client: AlpacaAPIClient,
        is_paper: bool = True,
        stop_pct: float = float(STOP_PCT),
        mock_trade_execution: bool = False,
        opening_start_time: str = OPENING_START_TIME,
        trailing_ma: str = TRAILING_MA,
        max_loss_pct: Optional[float] = MAX_LOSS_PCT,
        armed_ma20_exit: bool = ARMED_MA20_EXIT,
        regime_filter: bool = REGIME_FILTER,
        regime_ma: int = REGIME_MA,
        rank_weighted_sizing: bool = RANK_WEIGHTED_SIZING,
        top_n: int = MAX_ACTIVE_SYMBOLS,
        lookback_days: int = ROLLING_LOOKBACK_DAYS,
        windows: Optional[list] = None,
        trade_type: str = "options",
        option_price_monitor: Optional[OptionPriceMonitor] = None,
        time_premium_pct_cap: float = 0.01,
        enable_reversal: bool = False,
        reversal_max_bars: int = 3,
        enable_bearish_reentry: bool = False,
        bearish_reentry_max_bars: int = 3,
        enable_bullish_reentry: bool = False,
        bullish_reentry_max_bars: int = 5,
        replay_capital: Optional[float] = None,
        or_bar_lookback: int = 3,
    ):
        self._client = alpaca_client
        self._api_key = alpaca_client._api_key
        self._secret_key = alpaca_client._secret_key
        self._stop_pct = _D(str(stop_pct))
        self._mock_trade_execution = mock_trade_execution
        self._trailing_ma = trailing_ma
        self._max_loss_pct = max_loss_pct
        self._armed_ma20_exit = armed_ma20_exit
        self._regime_filter = regime_filter
        self._regime_ma = regime_ma
        self._rank_weighted_sizing = rank_weighted_sizing
        self._top_n = top_n
        self._lookback_days = lookback_days
        self._trade_type = trade_type
        self._option_price_monitor = option_price_monitor
        self._time_premium_pct_cap = time_premium_pct_cap
        self._enable_reversal = enable_reversal
        self._reversal_max_bars = reversal_max_bars
        self._enable_bearish_reentry = enable_bearish_reentry
        self._bearish_reentry_max_bars = bearish_reentry_max_bars
        self._enable_bullish_reentry = enable_bullish_reentry
        self._bullish_reentry_max_bars = bullish_reentry_max_bars
        self._replay_capital = replay_capital
        self._or_bar_lookback = or_bar_lookback
        self._monitor: PositionMonitor = None
        self._signal_engine: LiveSignalEngine = None
        self._signal_lock = threading.Lock()
        # Accumulated capital returned per window label as positions close.
        self._window_returned: dict = {}
        self._returned_lock = threading.Lock()
        # Total primary slot_capital deployed per window (tracks undeployed capital).
        self._window_primary_deployed: dict = {}
        self._rolling_stats: dict = {}
        # Per-window rolling stats: {label: {ticker: stats_dict}}
        # Falls back to _rolling_stats when label not present (e.g. single-window or tests).
        self._rolling_stats_by_window: dict = {}
        # Per-window state: {label: {pending_signals, collection_deadline, open_position_count, capital_fraction}}
        self._window_state: dict = {}

        if windows:
            self._windows = windows
        else:
            self._windows = [
                WindowConfig(
                    label="W1",
                    opening_start=opening_start_time,
                    opening_bars=OPENING_BARS,
                    capital_fraction=1.0,
                    is_sequential=False,
                )
            ]

        # Pre-initialize window state so per-window methods are callable before run()
        today = _now_et().date()
        for win in self._windows:
            opening_start_t = datetime.strptime(win.opening_start, "%H:%M").time()
            or_open = ET.localize(datetime.combine(today, opening_start_t))
            or_close = or_open + timedelta(minutes=win.opening_bars * 5)
            deadline = or_close + timedelta(minutes=SIGNAL_BUFFER_MINUTES)
            self._window_state[win.label] = {
                "pending_signals": {},
                "collection_deadline": deadline,
                "open_position_count": 0,
                "capital_fraction": win.capital_fraction,
            }

    def _enter_position(
        self,
        event: SignalEvent,
        rank: int = 0,
        window_label: str = "W1",
        window_budget: Optional[_D] = None,
        hard_stop_override: Optional[_D] = None,
        trailing_arm_price: Optional[_D] = None,
        initial_hard_stop_armed: bool = False,
    ):
        logger.info(
            "Entering position [%s]: %s %s @ %.2f (rank=%d)",
            window_label,
            event.ticker,
            event.signal,
            float(event.stock_price),
            rank,
        )
        if self._rank_weighted_sizing and rank < len(RANK_WEIGHTS):
            capital_weight = _D(str(RANK_WEIGHTS[rank]))
        else:
            capital_weight = _D("1")

        if hard_stop_override is not None:
            bull_hard_stop = hard_stop_override
            bear_hard_stop = hard_stop_override
        else:
            bull_hard_stop = event.or_high - self._stop_pct * event.or_range
            bear_hard_stop = event.or_low + self._stop_pct * event.or_range
        bull_fallback = event.or_high - _D("0.20") * event.or_range
        bear_fallback = event.or_low + _D("0.20") * event.or_range

        if event.signal_bar_time is not None:
            entry_bar_time = event.signal_bar_time
        else:
            latest_bar = self._signal_engine.get_latest_bar(event.ticker)
            entry_bar_time = latest_bar.name if latest_bar is not None else None

        if self._trade_type == "stock":
            self._enter_stock_position(
                event=event,
                rank=rank,
                window_label=window_label,
                window_budget=window_budget,
                capital_weight=capital_weight,
                bull_hard_stop=bull_hard_stop,
                bear_hard_stop=bear_hard_stop,
                bull_fallback=bull_fallback,
                bear_fallback=bear_fallback,
                entry_bar_time=entry_bar_time,
                trailing_arm_price=trailing_arm_price,
                initial_hard_stop_armed=initial_hard_stop_armed,
            )
        else:
            self._enter_option_position(
                event=event,
                rank=rank,
                window_label=window_label,
                window_budget=window_budget,
                capital_weight=capital_weight,
                bull_hard_stop=bull_hard_stop,
                bear_hard_stop=bear_hard_stop,
                bull_fallback=bull_fallback,
                bear_fallback=bear_fallback,
                entry_bar_time=entry_bar_time,
                trailing_arm_price=trailing_arm_price,
                initial_hard_stop_armed=initial_hard_stop_armed,
            )

    def _enter_stock_position(
        self,
        event: SignalEvent,
        rank: int,
        window_label: str,
        window_budget,
        capital_weight,
        bull_hard_stop,
        bear_hard_stop,
        bull_fallback,
        bear_fallback,
        entry_bar_time,
        trailing_arm_price=None,
        initial_hard_stop_armed: bool = False,
    ):
        try:
            sizer = PositionSizer(self._client)
            shares, limit_price = sizer.compute_stock(
                event.ticker, event.stock_price, capital_weight, window_budget
            )
        except Exception:
            logger.exception("Could not size stock position for %s", event.ticker)
            with self._signal_lock:
                self._window_state[window_label]["open_position_count"] -= 1
            return

        try:
            if self._mock_trade_execution:
                sim_mid = event.stock_price if is_replay_mode() else limit_price
                logger.info(
                    "SIMULATE BUY_OPEN stock %s shares=%d simulated_fill=%.2f (no order placed)",
                    event.ticker,
                    shares,
                    sim_mid,
                )
                order = {
                    "order_id": f"sim-stock-{event.ticker}",
                    "status": "simulated",
                    "simulated_fill_mid": sim_mid,
                }
            else:
                logger.info(
                    "Placing BUY_OPEN stock with fill escalation: %s %d shares",
                    event.ticker,
                    shares,
                )
                order = place_stock_order(
                    client=self._client,
                    ticker=event.ticker,
                    shares=shares,
                    order_action="BUY_OPEN",
                )
        except Exception:
            logger.exception("Failed to place stock entry order for %s", event.ticker)
            with self._signal_lock:
                self._window_state[window_label]["open_position_count"] -= 1
            return

        sim_entry_mid = (
            order.get("simulated_fill_mid") if self._mock_trade_execution else None
        )
        if window_budget is not None:
            if self._rank_weighted_sizing and rank < len(RANK_WEIGHTS):
                slot_weight = _D(str(RANK_WEIGHTS[rank]))
            else:
                slot_weight = _D("1") / _D(str(self._top_n))
            slot_capital = window_budget * slot_weight
        else:
            slot_capital = None

        # Track primary slot capital deployed per window so undeployed capital
        # can be forwarded to the next sequential window.
        is_reentry = trailing_arm_price is not None
        if not is_reentry and slot_capital is not None:
            with self._returned_lock:
                if window_label not in self._window_primary_deployed:
                    self._window_primary_deployed[window_label] = _D("0")
                self._window_primary_deployed[window_label] += slot_capital

        pos = ActivePosition(
            ticker=event.ticker,
            signal=event.signal,
            option_symbol="",
            entry_order_id=order.get("order_id", ""),
            contracts=0,
            entry_stock_price=event.entry_price,
            or_high=event.or_high,
            or_low=event.or_low,
            or_range=event.or_range,
            hard_stop_price=(
                bull_hard_stop if event.signal == "BULLISH" else bear_hard_stop
            ),
            fallback_price=(
                bull_fallback if event.signal == "BULLISH" else bear_fallback
            ),
            trade_type="stock",
            shares=shares,
            hard_stop_armed=initial_hard_stop_armed,
            entry_bar_time=entry_bar_time,
            entry_time=_now_et(),
            simulated_entry_mid=sim_entry_mid,
            trailing_arm_price=trailing_arm_price,
            window_label=window_label,
            rank=rank,
            window_budget=window_budget,
            slot_capital=slot_capital,
        )
        self._monitor.add_position(pos)

        prefix = "[SIMULATE] " if self._mock_trade_execution else ""
        entry_mid_str = f" @ ~{pos.simulated_entry_mid}" if pos.simulated_entry_mid else ""
        _notify(
            f"{prefix}BUY {event.ticker} x{shares} shares{entry_mid_str}"
            f" | R{rank + 1} | stop ${pos.hard_stop_price:.2f}"
        )

    def _enter_option_position(
        self,
        event: SignalEvent,
        rank: int,
        window_label: str,
        window_budget,
        capital_weight,
        bull_hard_stop,
        bear_hard_stop,
        bull_fallback,
        bear_fallback,
        entry_bar_time,
        trailing_arm_price=None,
        initial_hard_stop_armed: bool = False,
    ):
        try:
            selector = TimePremiumContractSelector(
                self._client, time_premium_pct_cap=self._time_premium_pct_cap
            )
            option_symbol = selector.select(
                event.ticker, event.signal, event.stock_price
            )
        except Exception:
            logger.exception("Could not select option contract for %s", event.ticker)
            with self._signal_lock:
                self._window_state[window_label]["open_position_count"] -= 1
            return

        try:
            sizer = PositionSizer(self._client)
            contracts, limit_price = sizer.compute(
                option_symbol, capital_weight, window_budget
            )
        except Exception:
            logger.exception("Could not size position for %s", option_symbol)
            with self._signal_lock:
                self._window_state[window_label]["open_position_count"] -= 1
            return

        try:
            order = self._place_entry(
                ticker=event.ticker,
                signal=event.signal,
                option_symbol=option_symbol,
                contracts=contracts,
                limit_price=limit_price,
            )
        except Exception:
            logger.exception("Failed to place entry order for %s", option_symbol)
            with self._signal_lock:
                self._window_state[window_label]["open_position_count"] -= 1
            return

        sim_entry_mid = (
            order.get("simulated_fill_mid") if self._mock_trade_execution else None
        )

        pos = ActivePosition(
            ticker=event.ticker,
            signal=event.signal,
            option_symbol=option_symbol,
            entry_order_id=order.get("order_id", ""),
            contracts=contracts,
            entry_stock_price=event.entry_price,
            or_high=event.or_high,
            or_low=event.or_low,
            or_range=event.or_range,
            hard_stop_price=(
                bull_hard_stop if event.signal == "BULLISH" else bear_hard_stop
            ),
            fallback_price=(
                bull_fallback if event.signal == "BULLISH" else bear_fallback
            ),
            trade_type="options",
            hard_stop_armed=initial_hard_stop_armed,
            entry_bar_time=entry_bar_time,
            entry_time=_now_et(),
            simulated_entry_mid=sim_entry_mid,
            trailing_arm_price=trailing_arm_price,
            window_label=window_label,
            rank=rank,
            window_budget=window_budget,
        )
        self._monitor.add_position(pos)

        prefix = "[SIMULATE] " if self._mock_trade_execution else ""
        entry_mid_str = f" @ ~{pos.simulated_entry_mid}" if pos.simulated_entry_mid else ""
        _notify(
            f"{prefix}BUY {_fmt_option(option_symbol)} x{contracts}{entry_mid_str}"
            f" | R{rank + 1} | stop ${pos.hard_stop_price:.2f}"
        )

    def _enter_reentry(self, watcher: ReentryWatcher, trigger_price: _D):
        reentry_signal = "BEARISH" if watcher.reentry_type == "bearish_reentry" else "BULLISH"
        trailing_arm = (
            trigger_price + watcher.or_range
            if reentry_signal == "BULLISH"
            else trigger_price - watcher.or_range
        )
        event = SignalEvent(
            ticker=watcher.ticker,
            signal=reentry_signal,
            entry_price=trigger_price,
            stock_price=trigger_price,
            or_high=watcher.or_high,
            or_low=watcher.or_low,
            or_range=watcher.or_range,
            ma50_at_signal=trigger_price,
        )
        logger.info(
            "Re-entry [%s] %s %s trigger=%.2f hard_stop=%.2f trailing_arm=%.2f",
            watcher.reentry_type,
            watcher.ticker,
            reentry_signal,
            float(trigger_price),
            float(watcher.midpoint),
            float(trailing_arm),
        )
        self._enter_position(
            event,
            rank=watcher.rank,
            window_label=watcher.window_label,
            window_budget=watcher.window_budget,
            hard_stop_override=watcher.midpoint,
            trailing_arm_price=trailing_arm,
            initial_hard_stop_armed=True,
        )

    def _prior_window_label(self, win: WindowConfig) -> Optional[str]:
        for i, w in enumerate(self._windows):
            if w.label == win.label and i > 0:
                return self._windows[i - 1].label
        return None

    def _on_position_closed(self, pos: ActivePosition):
        """Accumulate capital returned by a closed position into _window_returned.

        Re-entry positions (trailing_arm_price set) share a capital slot with their
        primary trade — they don't deploy fresh capital. Only their net P&L is added
        to _window_returned so the sequential window budget matches the backtest's
        capital flow model (available = initial_capital + prior_window_cap_pnl).
        """
        if pos.slot_capital is None:
            return
        entry = pos.simulated_entry_mid if pos.simulated_entry_mid is not None else pos.entry_stock_price
        exit_ = pos.simulated_exit_mid if pos.simulated_exit_mid is not None else pos.exit_fill_price
        if entry and entry > 0 and exit_:
            if pos.trade_type == "stock" and pos.signal == "BEARISH":
                raw = entry - exit_
            else:
                raw = exit_ - entry
            cap_pnl = pos.slot_capital / entry * raw
        else:
            cap_pnl = _D("0")

        is_reentry = pos.trailing_arm_price is not None
        if is_reentry:
            # Re-entry reuses the primary slot's capital; add only the net P&L.
            returned = cap_pnl
        else:
            returned = pos.slot_capital + cap_pnl

        with self._returned_lock:
            if pos.window_label not in self._window_returned:
                self._window_returned[pos.window_label] = _D("0")
            self._window_returned[pos.window_label] += returned
            total = self._window_returned[pos.window_label]
        logger.info(
            "Capital returned [%s] %s (reentry=%s): slot=%.2f cap_pnl=%.2f returned=%.2f window_total=%.2f",
            pos.window_label,
            pos.ticker,
            is_reentry,
            float(pos.slot_capital),
            float(cap_pnl),
            float(returned),
            float(total),
        )

    def _get_window_budget(self, win: WindowConfig) -> Optional[_D]:
        """Return window budget based on available capital.

        First-group windows: buying_power × capital_fraction (or replay_capital in replay mode).
        Sequential windows: capital returned from prior window's closed positions, plus
        slot_capital of still-open prior window positions (estimated at cost). Falls back
        to replay_capital or account balance if the prior window had no positions.
        """
        if not win.is_sequential:
            if self._replay_capital is not None:
                capital = _D(str(self._replay_capital))
                return capital * _D(str(win.capital_fraction))
            try:
                account = self._client.get_accounts()
                buying_power = _D(account.get("buying_power", ACCOUNT_BUDGET))
                return buying_power * _D(str(win.capital_fraction))
            except Exception:
                logger.exception(
                    "Could not fetch account balance for window [%s]", win.label
                )
                return None

        # Sequential window: sum returned capital from prior window
        prior_label = self._prior_window_label(win)
        if prior_label is None:
            logger.warning("No prior window found for sequential [%s]", win.label)
            if self._replay_capital is not None:
                return _D(str(self._replay_capital))
            return None

        # Capital already returned from closed prior-window positions
        with self._returned_lock:
            prior_returned = self._window_returned.get(prior_label, _D("0"))
            prior_deployed = self._window_primary_deployed.get(prior_label, _D("0"))

        # Add slot_capital for still-open primary positions in the prior window.
        # Re-entries (trailing_arm_price set) share the primary's capital slot; exclude them.
        open_primary_capital = _D("0")
        if self._monitor is not None:
            with self._monitor._lock:
                for pos in self._monitor._positions:
                    if (
                        pos.window_label == prior_label
                        and not pos.is_closed
                        and pos.trailing_arm_price is None
                        and pos.slot_capital is not None
                    ):
                        open_primary_capital += pos.slot_capital
        prior_returned += open_primary_capital

        # Add undeployed capital: slots in the prior window that had no signal.
        # prior_deployed tracks the sum of slot_capital for all primary positions
        # (open + closed). Any budget not deployed flows forward to this window.
        prior_budget = self._window_state.get(prior_label, {}).get("budget")
        if prior_budget is not None and prior_deployed < prior_budget:
            undeployed = prior_budget - prior_deployed
            prior_returned += undeployed
            logger.debug(
                "Sequential window [%s]: adding undeployed %.2f from [%s]"
                " (budget=%.2f deployed=%.2f)",
                win.label,
                float(undeployed),
                prior_label,
                float(prior_budget),
                float(prior_deployed),
            )

        if prior_returned > 0:
            logger.info(
                "Sequential window [%s] budget from prior [%s]: %.2f",
                win.label,
                prior_label,
                float(prior_returned),
            )
            return prior_returned

        # Fallback: prior window had no positions
        logger.info(
            "Sequential window [%s]: no prior [%s] capital, using fallback",
            win.label,
            prior_label,
        )
        if self._replay_capital is not None:
            return _D(str(self._replay_capital))
        try:
            account = self._client.get_accounts()
            buying_power = _D(account.get("buying_power", ACCOUNT_BUDGET))
            return buying_power
        except Exception:
            logger.exception(
                "Could not fetch account balance for sequential window [%s]", win.label
            )
            return None

    def _on_signal_for_window(self, window_label: str, event: SignalEvent):
        now = _now_et()
        state = self._window_state[window_label]
        with self._signal_lock:
            if now <= state["collection_deadline"]:
                # In replay mode the clock is pinned to bar timestamps and the
                # collection deadline equals the OR-close bar timestamp exactly.
                # Buffering signals at now == deadline (<=) ensures they are
                # ranked by the drain rather than jumping the queue at rank=0.
                # In live mode now == deadline is essentially impossible
                # (millisecond clock vs 5-min bar grid), so this is safe.
                if self._signal_engine is not None:
                    latest_bar = self._signal_engine.get_latest_bar(event.ticker)
                    event.signal_bar_time = latest_bar.name if latest_bar is not None else None
                state["pending_signals"][event.ticker] = event
                logger.info(
                    "Buffered signal [%s]: %s %s",
                    window_label,
                    event.ticker,
                    event.signal,
                )
                return
            if state["open_position_count"] >= self._top_n:
                logger.info(
                    "Max positions reached [%s] (%d), skipping %s",
                    window_label,
                    self._top_n,
                    event.ticker,
                )
                return
            state["open_position_count"] += 1

        win = next(w for w in self._windows if w.label == window_label)
        window_budget = self._get_window_budget(win)
        self._enter_position(
            event, rank=0, window_label=window_label, window_budget=window_budget
        )

    def _drain_pending_signals_for_window(self, win: WindowConfig):
        """Rank and enter all buffered signals for the given window. Safe to call from any thread."""
        label = win.label
        state = self._window_state[label]

        with self._signal_lock:
            pending = dict(state["pending_signals"])
            state["pending_signals"].clear()

        if not pending:
            logger.info(
                "Signal collection window [%s] closed: no signals buffered", label
            )
            return

        logger.info(
            "Signal collection window [%s] closed: ranking %d buffered signal(s)",
            label,
            len(pending),
        )

        window_rolling_stats = self._rolling_stats_by_window.get(label, self._rolling_stats)
        scored = []
        for ticker, event in pending.items():
            stats = window_rolling_stats.get(ticker, {})
            if stats.get("ev_trade", 0) <= 0:
                logger.info(
                    "Skipping %s [%s]: ev_trade=%.3f <= 0",
                    ticker,
                    label,
                    stats.get("ev_trade", 0),
                )
                continue
            midpoint = (event.or_high + event.or_low) / _D("2")
            entry_vs_mid_pct = (
                float(abs(event.entry_price - midpoint) / midpoint * 100)
                if midpoint != 0
                else 0.0
            )
            or_range_pct = (
                float(event.or_range / event.entry_price * 100)
                if event.entry_price != 0
                else 0.0
            )
            sig_dict = {
                "entry_vs_mid_pct": entry_vs_mid_pct,
                "or_range_pct": or_range_pct,
            }
            score = score_ticker(sig_dict, stats)
            scored.append((score, ticker, event))
            logger.info(
                "Ranked %s [%s]: score=%.3f ev_trade=%.3f",
                ticker,
                label,
                score,
                stats.get("ev_trade", 0),
            )

        scored.sort(key=lambda x: x[0], reverse=True)

        window_budget = self._get_window_budget(win)
        # Store budget so sequential windows can compute undeployed capital.
        if window_budget is not None:
            self._window_state[label]["budget"] = window_budget
        for rank, (score, ticker, event) in enumerate(scored):
            with self._signal_lock:
                if state["open_position_count"] >= self._top_n:
                    logger.info("Max positions reached [%s], stopping selection", label)
                    break
                state["open_position_count"] += 1
            logger.info(
                "Selecting %s from buffer [%s] (score=%.3f rank=%d)",
                ticker,
                label,
                score,
                rank,
            )
            self._enter_position(
                event, rank=rank, window_label=label, window_budget=window_budget
            )

    def _signal_selection_loop_for_window(self, win: WindowConfig):
        label = win.label
        state = self._window_state[label]
        deadline = state["collection_deadline"]
        logger.info(
            "Signal collection window [%s] open until %s ET",
            label,
            deadline.strftime("%H:%M:%S"),
        )
        while _now_et() < deadline:
            time.sleep(0.5)
        self._drain_pending_signals_for_window(win)

    def _place_entry(
        self,
        ticker: str,
        signal: str,
        option_symbol: str,
        contracts: int,
        limit_price,
    ) -> dict:
        from decimal import ROUND_HALF_UP
        from alpaca.data.requests import OptionLatestQuoteRequest

        option_type = "CALL" if signal == "BULLISH" else "PUT"
        option_type_lower = option_type.lower()

        entry_mid = limit_price
        if self._option_price_monitor:
            try:
                latest_bar = self._signal_engine.get_latest_bar(ticker)
                stock_price = _D(str(latest_bar["Close"])) if latest_bar is not None else limit_price
                entry_mid = self._option_price_monitor.get_fair_price(
                    ticker, option_symbol, option_type_lower, stock_price
                )
                logger.info(
                    "ENTRY FAIR PRICE %s: %s (from OptionPriceMonitor)", option_symbol, entry_mid
                )
            except Exception:
                logger.warning(
                    "get_fair_price failed for %s, falling back to quote mid", option_symbol
                )

        if entry_mid == limit_price:
            try:
                quote_resp = self._client._option_data_client.get_option_latest_quote(
                    OptionLatestQuoteRequest(symbol_or_symbols=[option_symbol])
                )
                quote = quote_resp[option_symbol]
                bid = _D(quote.bid_price)
                ask = _D(quote.ask_price)
                entry_mid = (bid + ask) / _D("2")
                logger.info(
                    "ENTRY QUOTE %s: bid=%s ask=%s mid=%s",
                    option_symbol,
                    bid,
                    ask,
                    entry_mid.quantize(_D("0.01"), rounding=ROUND_HALF_UP),
                )
            except Exception:
                logger.warning(
                    "Could not fetch entry quote for %s, using sizer mid", option_symbol
                )

        if self._mock_trade_execution:
            sim_mid = entry_mid.quantize(_D("0.01"), rounding=ROUND_HALF_UP)
            logger.info(
                "SIMULATE BUY_OPEN %s %s contracts=%d simulated_fill=%.2f (no order placed)",
                option_symbol,
                option_type,
                contracts,
                sim_mid,
            )
            return {
                "order_id": f"sim-{option_symbol}",
                "status": "simulated",
                "simulated_fill_mid": sim_mid,
            }

        logger.info(
            "Placing BUY_OPEN with fill escalation: %s %s %d",
            option_symbol,
            option_type,
            contracts,
        )
        return _place_with_fill_escalation(
            client=self._client,
            ticker=ticker,
            option_symbol=option_symbol,
            option_type=option_type,
            contracts=contracts,
            order_action="BUY_OPEN",
        )

    def _monitor_loop(self, active_tickers: list):
        eod_h, eod_m = [int(x) for x in EOD_EXIT_TIME.split(":")]
        last_status_print = _now_et()
        while True:
            now = _now_et()
            if now.hour > eod_h or (now.hour == eod_h and now.minute >= eod_m):
                logger.info("EOD: force-closing all positions")
                self._monitor.close_all(reason="end_of_day")
                break

            for ticker in active_tickers:
                self._monitor.on_bar(ticker)

            if (now - last_status_print).total_seconds() >= 300:
                self._monitor.print_status()
                last_status_print = now

            time.sleep(30)

    def run(self, tickers_override: list = None):
        api_key = self._api_key
        secret_key = self._secret_key

        all_tickers = tickers_override or TICKERS
        first_window = self._windows[0]

        self._window_returned = {}
        self._window_primary_deployed = {}
        self._rolling_stats_by_window = {}
        seen_configs: dict = {}
        pre_market_picks: list = []
        for i, win in enumerate(self._windows):
            config_key = (win.opening_start, win.opening_bars)
            if config_key in seen_configs:
                self._rolling_stats_by_window[win.label] = seen_configs[config_key]
                continue
            win_selector = TickerSelector(
                tickers=all_tickers,
                top_n=self._top_n,
                stop_pct=float(self._stop_pct),
                opening_start_time=win.opening_start,
                opening_bars=win.opening_bars,
                lookback_days=self._lookback_days,
                regime_filter=self._regime_filter,
                regime_ma=self._regime_ma,
            )
            win_picks = win_selector.select()
            if i == 0:
                pre_market_picks = win_picks
            self._rolling_stats_by_window[win.label] = win_selector.rolling_stats
            seen_configs[config_key] = win_selector.rolling_stats
        self._rolling_stats = self._rolling_stats_by_window.get(first_window.label, {})
        print(f"\nPre-market top picks: {pre_market_picks}")
        print(f"Subscribing all {len(all_tickers)} tickers to live stream...")
        if len(self._windows) > 1:
            labels = [
                f"[{w.label}] {w.opening_start}/{w.opening_bars}bar"
                for w in self._windows
            ]
            print(f"Windows: {', '.join(labels)}")

        today = _now_et().date()

        # Build per-window state and signal engine window configs
        engine_windows = []
        for win in self._windows:
            opening_start_t = datetime.strptime(win.opening_start, "%H:%M").time()
            or_open_et = ET.localize(datetime.combine(today, opening_start_t))
            or_close_et = or_open_et + timedelta(minutes=win.opening_bars * 5)
            deadline = or_close_et + timedelta(minutes=SIGNAL_BUFFER_MINUTES)

            label = win.label
            self._window_state[label] = {
                "pending_signals": {},
                "collection_deadline": deadline,
                "open_position_count": 0,
                "capital_fraction": win.capital_fraction,
            }
            logger.info(
                "Window [%s] %s/%dbar — collection deadline %s ET",
                label,
                win.opening_start,
                win.opening_bars,
                deadline.strftime("%H:%M:%S"),
            )

            engine_windows.append(
                {
                    "label": label,
                    "opening_start": win.opening_start,
                    "opening_bars": win.opening_bars,
                    "on_signal": lambda event, lbl=label: self._on_signal_for_window(
                        lbl, event
                    ),
                }
            )

        bar_recorder = BarRecorder()
        self._signal_engine = LiveSignalEngine(
            tickers=all_tickers,
            api_key=api_key,
            secret_key=secret_key,
            bearish_ma200=BEARISH_MA200,
            regime_filter=self._regime_filter,
            regime_ma=self._regime_ma,
            windows=engine_windows,
            bar_recorder=bar_recorder,
            or_bar_lookback=self._or_bar_lookback,
        )
        try:
            account = self._client.get_accounts()
            initial_capital = float(account.get("buying_power", ACCOUNT_BUDGET))
        except Exception:
            initial_capital = float(ACCOUNT_BUDGET)

        self._monitor = PositionMonitor(
            self._client,
            self._signal_engine,
            mock_trade_execution=self._mock_trade_execution,
            trailing_ma=self._trailing_ma,
            max_loss_pct=self._max_loss_pct,
            armed_ma20_exit=self._armed_ma20_exit,
            option_price_monitor=self._option_price_monitor,
            enable_reversal=self._enable_reversal,
            reversal_max_bars=self._reversal_max_bars,
            enable_bearish_reentry=self._enable_bearish_reentry,
            bearish_reentry_max_bars=self._bearish_reentry_max_bars,
            enable_bullish_reentry=self._enable_bullish_reentry,
            bullish_reentry_max_bars=self._bullish_reentry_max_bars,
            re_entry_callback=self._enter_reentry,
            initial_capital=initial_capital,
            close_callback=self._on_position_closed,
        )

        if self._option_price_monitor:
            self._option_price_monitor.start()

        self._signal_engine.start()

        for win in self._windows:
            t = threading.Thread(
                target=self._signal_selection_loop_for_window,
                args=(win,),
                daemon=True,
            )
            t.start()

        monitor_thread = threading.Thread(
            target=self._monitor_loop, args=(all_tickers,), daemon=True
        )
        monitor_thread.start()
        monitor_thread.join()

        self._signal_engine.stop()
        if self._option_price_monitor:
            self._option_price_monitor.stop()
        bar_recorder.close()
        self._monitor.print_summary()

    def run_replay(self, replay_date, tickers_override: list = None):
        """
        Run a full trading session against historical bar data for `replay_date`.

        Feeds cached 5-min bars through the identical signal → entry → monitor →
        exit pipeline used in live mode.  Always uses mock_trade_execution=True
        regardless of how the engine was constructed.
        """
        from datetime import time as _time

        disable_notifications()

        # Pin the clock to replay_date 9:30 so TickerSelector and window-state
        # initialisation both use the correct date.
        replay_open = ET.localize(datetime.combine(replay_date, _time(9, 30)))
        set_replay_clock(lambda: replay_open)

        all_tickers = tickers_override or TICKERS
        first_window = self._windows[0]

        self._window_returned = {}
        self._window_primary_deployed = {}
        self._rolling_stats_by_window = {}
        seen_configs: dict = {}
        pre_market_picks: list = []
        for i, win in enumerate(self._windows):
            config_key = (win.opening_start, win.opening_bars)
            if config_key in seen_configs:
                self._rolling_stats_by_window[win.label] = seen_configs[config_key]
                continue
            win_selector = TickerSelector(
                tickers=all_tickers,
                top_n=self._top_n,
                stop_pct=float(self._stop_pct),
                opening_start_time=win.opening_start,
                opening_bars=win.opening_bars,
                lookback_days=self._lookback_days,
                regime_filter=self._regime_filter,
                regime_ma=self._regime_ma,
            )
            win_picks = win_selector.select()
            if i == 0:
                pre_market_picks = win_picks
            self._rolling_stats_by_window[win.label] = win_selector.rolling_stats
            seen_configs[config_key] = win_selector.rolling_stats
        self._rolling_stats = self._rolling_stats_by_window.get(first_window.label, {})
        print(f"\nReplay {replay_date} — pre-market picks: {pre_market_picks}")

        # Build per-window states with replay_date deadlines.
        # Use or_close as the deadline (no buffer) so that the drain fires at the
        # very first post-OR bar, matching the backtest's bar-by-bar evaluation order.
        engine_windows = []
        for win in self._windows:
            opening_start_t = datetime.strptime(win.opening_start, "%H:%M").time()
            or_open_et = ET.localize(datetime.combine(replay_date, opening_start_t))
            or_close_et = or_open_et + timedelta(minutes=win.opening_bars * 5)
            deadline = or_close_et
            label = win.label
            self._window_state[label] = {
                "pending_signals": {},
                "collection_deadline": deadline,
                "open_position_count": 0,
                "capital_fraction": win.capital_fraction,
            }
            engine_windows.append(
                {
                    "label": label,
                    "opening_start": win.opening_start,
                    "opening_bars": win.opening_bars,
                    "on_signal": lambda event, lbl=label: self._on_signal_for_window(
                        lbl, event
                    ),
                }
            )

        self._signal_engine = LiveSignalEngine(
            tickers=all_tickers,
            api_key=self._api_key,
            secret_key=self._secret_key,
            bearish_ma200=BEARISH_MA200,
            regime_filter=self._regime_filter,
            regime_ma=self._regime_ma,
            windows=engine_windows,
            or_bar_lookback=self._or_bar_lookback,
        )
        self._signal_engine.start_replay(replay_date)

        initial_capital = self._replay_capital or float(ACCOUNT_BUDGET)

        self._monitor = PositionMonitor(
            self._client,
            self._signal_engine,
            mock_trade_execution=True,
            trailing_ma=self._trailing_ma,
            max_loss_pct=self._max_loss_pct,
            armed_ma20_exit=self._armed_ma20_exit,
            enable_reversal=self._enable_reversal,
            reversal_max_bars=self._reversal_max_bars,
            enable_bearish_reentry=self._enable_bearish_reentry,
            bearish_reentry_max_bars=self._bearish_reentry_max_bars,
            enable_bullish_reentry=self._enable_bullish_reentry,
            bullish_reentry_max_bars=self._bullish_reentry_max_bars,
            re_entry_callback=self._enter_reentry,
            initial_capital=initial_capital,
            close_callback=self._on_position_closed,
        )

        # In replay mode signals are drained synchronously in _on_bar (no background threads)
        # so that _drain_pending_signals_for_window runs while the replay clock is active.
        _drained_windows = set()

        def _on_bar(ticker):
            # Drain before monitor so newly-entered positions are evaluated
            # at the same bar that triggers the drain (matching backtest order).
            for win in self._windows:
                lbl = win.label
                if lbl not in _drained_windows:
                    deadline = self._window_state[lbl]["collection_deadline"]
                    if _now_et() >= deadline:
                        _drained_windows.add(lbl)
                        self._drain_pending_signals_for_window(win)
            self._monitor.on_bar(ticker)

        driver = BarReplayDriver(
            tickers=all_tickers,
            replay_date=replay_date,
            signal_engine=self._signal_engine,
            on_bar_injected=_on_bar,
        )
        driver.run()

        # BarReplayDriver.run() clears the replay clock internally.  Re-pin it to the
        # last bar's timestamp so close_all() records the correct exit time and uses
        # bar prices (not wall-clock time / live API quotes) for EOD-closed positions.
        if driver.last_bar_time is not None:
            set_replay_clock(lambda ts=driver.last_bar_time: ts)
        self._monitor.close_all(reason="end_of_day")
        clear_replay_clock()
        enable_notifications()
        self._monitor.print_summary()

import hashlib
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import pytz

from alpaca.data.enums import DataFeed

from alpha_tech_tracker.op_momentum_strategy.op_momentum_backtest import fetch_bars
from alpha_tech_tracker.op_momentum_strategy.op_momentum_selector import (
    ROLLING_LOOKBACK_DAYS,
    _safe_bars_end,
    score_ticker,
    select_top_n,
)
from alpha_tech_tracker.trade_api.execution_client import ExecutionClient

from .config import (
    ACCOUNT_BUDGET,
    ARMED_MA20_EXIT,
    BEARISH_MA200,
    DAILY_MAX_LOSS_USD,
    EOD_EXIT_TIME,
    WS_RECONNECT_TIMEOUT_SECONDS,
    MAX_ACTIVE_SYMBOLS,
    MAX_LOSS_PCT,
    OPENING_BARS,
    OPENING_START_TIME,
    REGIME_FILTER,
    REGIME_MA,
    SESSION_END_TIME,
    SIGNAL_BUFFER_MINUTES,
    STOP_PCT,
    TICKERS,
    TRAILING_MA,
    _notify,
    _fmt_option,
    disable_notifications,
    enable_notifications,
)
from .bar_recorder import BarRecorder
from .contract_selector import MockContractSelector, ITMOptionContractSelector, _is_nyse_holiday
from .models import ActivePosition, ReentryWatcher, SignalEvent, WindowConfig, _D
from .option_price_monitor import OptionPriceMonitor
from .order_executor import _place_with_fill_escalation, place_stock_order
from .position_monitor import PositionMonitor
from .position_sizer import PositionSizer
from .replay import BarReplayDriver, LiveBarsSource, _now_et, is_replay_mode, set_replay_clock, clear_replay_clock
from .session_state import save as _save_session, load as _load_session
from .signal_engine import LiveSignalEngine

logger = logging.getLogger(__name__)

_PREMARKET_WAIT_TIME = "09:20"  # ET — wake up this early before session open


def _next_trading_day(d: date) -> date:
    """Return the nearest future weekday that is not a NYSE holiday."""
    candidate = d + timedelta(days=1)
    while candidate.weekday() >= 5 or _is_nyse_holiday(candidate):
        candidate += timedelta(days=1)
    return candidate


def _trading_days_in_range(start: date, end: date) -> list:
    """Return all weekdays that are not NYSE holidays between start and end (inclusive)."""
    days = []
    d = start
    while d <= end:
        if d.weekday() < 5 and not _is_nyse_holiday(d):
            days.append(d)
        d += timedelta(days=1)
    return days

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
        alpaca_feed: DataFeed = DataFeed.SIP,
    ):
        self._tickers = tickers
        self._top_n = top_n
        self._stop_pct = stop_pct
        self._opening_start_time = opening_start_time
        self._opening_bars = opening_bars
        self._lookback_days = lookback_days
        self._regime_filter = regime_filter
        self._regime_ma = regime_ma
        self._alpaca_feed = alpaca_feed
        self.rolling_stats: dict = {}

    def _selector_cache_path(self, target_date: date) -> Path:
        tickers_hash = hashlib.md5(",".join(sorted(self._tickers)).encode()).hexdigest()[:8]
        cache_dir = Path(__file__).parent.parent.parent / "market_data" / "cache"
        fname = (
            f"selector_{target_date}"
            f"_{self._opening_start_time.replace(':', '')}"
            f"_{self._opening_bars}bar"
            f"_lk{self._lookback_days}"
            f"_reg{int(self._regime_filter)}{self._regime_ma}"
            f"_stop{self._stop_pct}"
            f"_{tickers_hash}.json"
        )
        return cache_dir / fname

    def fetch_bars(self) -> dict:
        """Fetch and return bar data without running the selector. Can be passed to select()."""
        today = _now_et().date()
        fetch_start = today - timedelta(days=max(self._lookback_days, 30) + 5)
        if is_replay_mode():
            bars_end = today - timedelta(days=1)
            return fetch_bars(
                self._tickers,
                fetch_start,
                bars_end,
                source="alpaca",
                feed=self._alpaca_feed,
            )
        return fetch_bars(
            self._tickers,
            fetch_start,
            _safe_bars_end(today),
            source="alpaca",
            allow_intraday=True,
            feed=self._alpaca_feed,
        )

    def select(self, ticker_dfs: dict = None) -> list:
        today = _now_et().date()
        if ticker_dfs is None:
            ticker_dfs = self.fetch_bars()

        if is_replay_mode():
            # In replay mode, recompute selector scores fresh using the replay
            # date as target_date so the 60-day lookback matches the backtest.
            logger.info("Replay mode: computing fresh selector scores for %s (%s/%dbar)", today, self._opening_start_time, self._opening_bars)
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
            picks = result["picks"]
        else:
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
                picks = result["picks"]

        self.rolling_stats = result.get("rolling_stats", {})
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
        alpaca_client: ExecutionClient,
        is_paper: bool = True,
        stop_pct: float = float(STOP_PCT),
        mock_trade_execution: bool = False,
        opening_start_time: str = OPENING_START_TIME,
        trailing_ma: str = TRAILING_MA,
        max_loss_pct: Optional[float] = MAX_LOSS_PCT,
        daily_max_loss_usd: Optional[float] = DAILY_MAX_LOSS_USD,
        armed_ma20_exit: bool = ARMED_MA20_EXIT,
        regime_filter: bool = REGIME_FILTER,
        regime_ma: int = REGIME_MA,
        rank_weights: Optional[list] = None,
        top_n: int = MAX_ACTIVE_SYMBOLS,
        lookback_days: int = ROLLING_LOOKBACK_DAYS,
        windows: Optional[list] = None,
        trade_type: str = "options",
        option_price_monitor: Optional[OptionPriceMonitor] = None,
        contract_selector=None,
        enable_reversal: bool = False,
        reversal_max_bars: int = 3,
        enable_bearish_reentry: bool = False,
        bearish_reentry_max_bars: int = 3,
        enable_bullish_reentry: bool = False,
        bullish_reentry_max_bars: int = 5,
        replay_capital: Optional[float] = None,
        or_bar_lookback: int = 3,
        ws_reconnect_timeout: int = WS_RECONNECT_TIMEOUT_SECONDS,
        alpaca_feed: DataFeed = DataFeed.SIP,
        enable_doubledown: bool = False,
        doubledown_start_min: int = 5,
    ):
        self._client = alpaca_client
        self._api_key = alpaca_client._api_key
        self._secret_key = alpaca_client._secret_key
        self._stop_pct = _D(str(stop_pct))
        self._mock_trade_execution = mock_trade_execution
        self._trailing_ma = trailing_ma
        self._max_loss_pct = max_loss_pct
        self._daily_max_loss_usd = _D(str(daily_max_loss_usd)) if daily_max_loss_usd is not None else None
        self._daily_realized_pnl = _D("0")
        self._pnl_lock = threading.Lock()
        self._armed_ma20_exit = armed_ma20_exit
        self._regime_filter = regime_filter
        self._regime_ma = regime_ma
        if rank_weights:
            total = sum(rank_weights)
            self._rank_weights = [_D(str(w / total)) for w in rank_weights]
        else:
            self._rank_weights = None
        self._top_n = top_n
        self._lookback_days = lookback_days
        self._trade_type = trade_type
        self._option_price_monitor = option_price_monitor
        self._contract_selector = contract_selector if contract_selector is not None else ITMOptionContractSelector(alpaca_client)
        self._enable_reversal = enable_reversal
        self._reversal_max_bars = reversal_max_bars
        self._enable_bearish_reentry = enable_bearish_reentry
        self._bearish_reentry_max_bars = bearish_reentry_max_bars
        self._enable_bullish_reentry = enable_bullish_reentry
        self._bullish_reentry_max_bars = bullish_reentry_max_bars
        self._replay_capital = replay_capital
        self._or_bar_lookback = or_bar_lookback
        self._ws_reconnect_timeout = ws_reconnect_timeout
        self._alpaca_feed = alpaca_feed
        self._enable_doubledown = enable_doubledown
        self._doubledown_start_min = doubledown_start_min
        self._dd_timers: dict = {}
        self._dd_fired: set = set()
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
        reentry_type: Optional[str] = None,
        capital_weight_override: Optional[_D] = None,
    ):
        logger.info(
            "Entering position [%s]: %s %s @ %.2f (rank=%d%s)",
            window_label,
            event.ticker,
            event.signal,
            float(event.stock_price),
            rank,
            " [DD add-on]" if reentry_type == "doubledown" else "",
        )
        if capital_weight_override is not None:
            capital_weight = capital_weight_override
        elif self._rank_weights and rank < len(self._rank_weights):
            capital_weight = self._rank_weights[rank]
        else:
            capital_weight = _D("1") / _D(str(self._top_n))

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
                reentry_type=reentry_type,
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
                reentry_type=reentry_type,
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
        reentry_type: Optional[str] = None,
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

        hard_stop = bull_hard_stop if event.signal == "BULLISH" else bear_hard_stop
        prefix = "[SIMULATE] " if self._mock_trade_execution else ""
        action_label = "BUY" if event.signal == "BULLISH" else "SELL SHORT"
        _notify(
            f"{prefix}{action_label} {event.ticker} x{shares} shares"
            f" @ ~${float(limit_price):.2f}"
            f" | R{rank + 1} | stop ${hard_stop:.2f}"
        )

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
                    signal_price=float(event.stock_price),
                    feed=self._alpaca_feed,
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
            slot_capital = window_budget * capital_weight
        else:
            slot_capital = None

        # Track primary slot capital deployed per window so undeployed capital
        # can be forwarded to the next sequential window.
        # DD add-ons deploy recycled capital, not original window budget — exclude them.
        is_reentry = trailing_arm_price is not None or reentry_type == "doubledown"
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
            hard_stop_price=hard_stop,
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
            reentry_type=reentry_type,
            window_label=window_label,
            rank=rank,
            window_budget=window_budget,
            slot_capital=slot_capital,
            is_doubledown_addon=(reentry_type == "doubledown"),
        )
        if not self._mock_trade_execution:
            pos.entry_fill_price = self._poll_entry_fill(order.get("order_id", ""))
        self._monitor.add_position(pos)
        self._flush_session_state()

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
        reentry_type: Optional[str] = None,
    ):
        try:
            if is_replay_mode():
                ref_date = getattr(self._signal_engine, "_session_date", None)
                selector = MockContractSelector(ref_date or date.today())
            else:
                selector = self._contract_selector
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
            mock_stock_price = event.entry_price if self._mock_trade_execution else None
            contracts, limit_price = sizer.compute(
                option_symbol, capital_weight, window_budget,
                mock_stock_price=mock_stock_price,
            )
        except Exception:
            logger.exception("Could not size position for %s", option_symbol)
            with self._signal_lock:
                self._window_state[window_label]["open_position_count"] -= 1
            return

        hard_stop = bull_hard_stop if event.signal == "BULLISH" else bear_hard_stop
        prefix = "[SIMULATE] " if self._mock_trade_execution else ""
        _notify(
            f"{prefix}BUY {_fmt_option(option_symbol)} x{contracts}"
            f" @ ~${float(limit_price):.2f}"
            f" | R{rank + 1} | stop ${hard_stop:.2f}"
        )

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

        if window_budget is not None:
            slot_capital = window_budget * capital_weight
        else:
            slot_capital = None

        # DD add-ons deploy recycled capital, not original window budget — exclude them.
        is_reentry = trailing_arm_price is not None or reentry_type == "doubledown"
        if not is_reentry and slot_capital is not None:
            with self._returned_lock:
                if window_label not in self._window_primary_deployed:
                    self._window_primary_deployed[window_label] = _D("0")
                self._window_primary_deployed[window_label] += slot_capital

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
            hard_stop_price=hard_stop,
            fallback_price=(
                bull_fallback if event.signal == "BULLISH" else bear_fallback
            ),
            trade_type="options",
            hard_stop_armed=initial_hard_stop_armed,
            entry_bar_time=entry_bar_time,
            entry_time=_now_et(),
            simulated_entry_mid=sim_entry_mid,
            trailing_arm_price=trailing_arm_price,
            reentry_type=reentry_type,
            window_label=window_label,
            rank=rank,
            window_budget=window_budget,
            slot_capital=slot_capital,
            is_doubledown_addon=(reentry_type == "doubledown"),
        )
        if not self._mock_trade_execution:
            pos.entry_fill_price = self._poll_entry_fill(order.get("order_id", ""))
        self._monitor.add_position(pos)
        self._flush_session_state()

    def _poll_entry_fill(self, order_id: str, retries: int = 3, delay: float = 5.0) -> Optional[_D]:
        """Poll broker for entry fill price after a live order is placed.

        Called once per entry (live mode only) so that entry_fill_price is
        available from the very first monitoring bar, enabling quick-exit
        protection on positions held under 8 minutes.

        Returns the fill price as Decimal, or None if unavailable after all retries.
        """
        for attempt in range(retries):
            try:
                status = self._client.order_status(order_id)
                fill = status.get("filled_avg_price")
                if fill is not None:
                    logger.info(
                        "Entry fill confirmed %s: %.4f (attempt %d)",
                        order_id,
                        float(fill),
                        attempt + 1,
                    )
                    return _D(str(fill))
            except Exception:
                logger.warning(
                    "Could not fetch entry fill for %s (attempt %d/%d)",
                    order_id,
                    attempt + 1,
                    retries,
                )
            time.sleep(delay)
        logger.warning(
            "Entry fill unavailable after %d attempts for %s — quick-exit disabled for this position",
            retries,
            order_id,
        )
        return None

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
            reentry_type=watcher.reentry_type,
        )

    def _prior_window_label(self, win: WindowConfig) -> Optional[str]:
        for i, w in enumerate(self._windows):
            if w.label == win.label and i > 0:
                return self._windows[i - 1].label
        return None

    def _compute_position_returned_capital(self, pos) -> _D:
        """Return the capital actually returned from a closed position (principal + P&L)."""
        if pos.slot_capital is None:
            return _D("0")
        entry = pos.simulated_entry_mid or pos.entry_stock_price
        exit_ = pos.simulated_exit_mid or pos.exit_fill_price
        if not entry or entry <= 0 or not exit_:
            return pos.slot_capital
        if pos.trade_type == "stock":
            raw = (exit_ - entry) if pos.signal == "BULLISH" else (entry - exit_)
            return pos.slot_capital + pos.slot_capital / entry * raw
        else:
            raw = (exit_ - entry) if pos.signal == "BULLISH" else (entry - exit_)
            return pos.slot_capital + _D(pos.contracts) * _D("100") * raw

    def _schedule_dd_check_for_window(self, win: WindowConfig):
        """Start a timer to fire _check_doubledown_for_window at OR close + doubledown_start_min.

        Skipped in replay mode (the replay _on_bar loop handles DD inline).
        Skipped when the computed check time falls at or after EOD.
        """
        if not self._enable_doubledown or win.label in self._dd_fired:
            return
        if is_replay_mode():
            return
        today = _now_et().date()
        opening_start_t = datetime.strptime(win.opening_start, "%H:%M").time()
        or_open = ET.localize(datetime.combine(today, opening_start_t))
        or_close = or_open + timedelta(minutes=win.opening_bars * 5)
        dd_check_time = or_close + timedelta(minutes=self._doubledown_start_min)
        eod_dt = ET.localize(
            datetime.combine(today, datetime.strptime(EOD_EXIT_TIME, "%H:%M").time())
        )
        if dd_check_time >= eod_dt:
            logger.info(
                "DD [%s]: check time %s is at/after EOD (%s), skipping",
                win.label,
                dd_check_time.strftime("%H:%M"),
                EOD_EXIT_TIME,
            )
            return
        delay = (dd_check_time - _now_et()).total_seconds()
        if delay <= 0:
            logger.info("DD [%s]: check time already passed, skipping", win.label)
            return
        t = threading.Timer(delay, self._check_doubledown_for_window, args=(win,))
        t.daemon = True
        t.start()
        self._dd_timers[win.label] = t
        logger.info(
            "DD [%s]: check scheduled at %s ET (+%d min from OR close)",
            win.label,
            dd_check_time.strftime("%H:%M"),
            self._doubledown_start_min,
        )

    def _check_doubledown_for_window(self, win: WindowConfig):
        """Fire the double-down add-on if one or more co-picks stopped out and a survivor remains.

        Fires once per window per day. Freed capital from eligible stopouts is
        deployed 100% into the highest-ranked survivor as a break-even-stopped add-on.
        """
        label = win.label
        if label in self._dd_fired:
            return
        self._dd_fired.add(label)

        with self._monitor._lock:
            all_positions = list(self._monitor._positions)

        # All primary (non-re-entry, non-DD) positions in this window
        window_primary = [
            p for p in all_positions
            if p.window_label == label
            and p.trailing_arm_price is None
            and not p.is_doubledown_addon
        ]

        survivors = [p for p in window_primary if not p.is_closed]
        if not survivors:
            logger.info("DD [%s]: no survivors at check time, skipping", label)
            return

        # Ranks that have an open re-entry — their slot capital is already redeployed
        open_reentry_ranks = {
            p.rank for p in all_positions
            if p.window_label == label
            and not p.is_closed
            and p.trailing_arm_price is not None
        }

        stopouts = [
            p for p in window_primary
            if p.is_closed
            and p.exit_reason in ("hard_stop", "fallback_20pct")
            and p.rank not in open_reentry_ranks
        ]
        if not stopouts:
            logger.info("DD [%s]: no eligible stopouts at check time, skipping", label)
            return

        freed_capital = _D("0")
        freed_ranks = []
        for p in stopouts:
            freed_capital += self._compute_position_returned_capital(p)
            freed_ranks.append(p.rank)

        if freed_capital <= 0:
            logger.info("DD [%s]: freed capital is zero, skipping", label)
            return

        winner = min(survivors, key=lambda p: p.rank)

        latest_bar = self._signal_engine.get_latest_bar(winner.ticker)
        if latest_bar is None:
            logger.warning(
                "DD [%s]: no bar available for %s, skipping", label, winner.ticker
            )
            return
        dd_entry_price = _D(str(latest_bar["Close"]))

        logger.info(
            "DD [%s] firing: winner=%s freed=%.2f from ranks %s entry=%.2f",
            label,
            winner.ticker,
            float(freed_capital),
            freed_ranks,
            float(dd_entry_price),
        )
        _notify(
            f"[DD] [{label}] ADD-ON {winner.ticker}"
            f" freed=${float(freed_capital):.0f} from rank(s) {freed_ranks}"
            f" @ ~${float(dd_entry_price):.2f} (break-even stop)"
        )

        # Subtract freed capital from _window_returned to prevent double-counting
        # with sequential window budgets. The capital is being re-deployed, not free.
        with self._returned_lock:
            current = self._window_returned.get(label, _D("0"))
            self._window_returned[label] = max(_D("0"), current - freed_capital)

        event = SignalEvent(
            ticker=winner.ticker,
            signal=winner.signal,
            entry_price=dd_entry_price,
            stock_price=dd_entry_price,
            or_high=winner.or_high,
            or_low=winner.or_low,
            or_range=winner.or_range,
            ma50_at_signal=dd_entry_price,
            signal_bar_time=getattr(latest_bar, "name", None),
        )

        with self._signal_lock:
            self._window_state[label]["open_position_count"] += 1

        self._enter_position(
            event,
            rank=winner.rank,
            window_label=label,
            window_budget=freed_capital,
            hard_stop_override=dd_entry_price,
            initial_hard_stop_armed=True,
            reentry_type="doubledown",
            capital_weight_override=_D("1"),
        )

    def _rebuild_window_returned(self, positions: list) -> None:
        """Accumulate returned capital from a list of positions into _window_returned.

        Side-effect-free with respect to logging — used both by _on_position_closed
        (single live position) and _recover_session (batch of closed checkpoint positions).
        """
        for pos in positions:
            if pos.slot_capital is None:
                continue
            entry = (
                pos.simulated_entry_mid
                if pos.simulated_entry_mid is not None
                else pos.entry_stock_price
            )
            exit_ = (
                pos.simulated_exit_mid
                if pos.simulated_exit_mid is not None
                else pos.exit_fill_price
            )
            if entry and entry > 0 and exit_:
                if pos.trade_type == "stock" and pos.signal == "BEARISH":
                    raw = entry - exit_
                else:
                    raw = exit_ - entry
                if pos.trade_type == "stock":
                    cap_pnl = pos.slot_capital / entry * raw
                else:
                    cap_pnl = _D(pos.contracts) * _D("100") * raw
            else:
                cap_pnl = _D("0")

            is_reentry = pos.trailing_arm_price is not None
            returned = cap_pnl if is_reentry else pos.slot_capital + cap_pnl
            with self._returned_lock:
                self._window_returned.setdefault(pos.window_label, _D("0"))
                self._window_returned[pos.window_label] += returned
            with self._pnl_lock:
                self._daily_realized_pnl += cap_pnl

    def _is_circuit_breaker_tripped(self) -> bool:
        """Return True when daily realized losses exceed the configured threshold."""
        if self._daily_max_loss_usd is None:
            return False
        with self._pnl_lock:
            return self._daily_realized_pnl <= -self._daily_max_loss_usd

    def _on_position_closed(self, pos: ActivePosition):
        """Accumulate capital returned by a closed position into _window_returned.

        Re-entry positions (trailing_arm_price set) share a capital slot with their
        primary trade — they don't deploy fresh capital. Only their net P&L is added
        to _window_returned so the sequential window budget matches the backtest's
        capital flow model (available = initial_capital + prior_window_cap_pnl).
        """
        if pos.slot_capital is None:
            return

        self._rebuild_window_returned([pos])

        # Recompute totals for logging only.
        entry = (
            pos.simulated_entry_mid
            if pos.simulated_entry_mid is not None
            else pos.entry_stock_price
        )
        exit_ = (
            pos.simulated_exit_mid
            if pos.simulated_exit_mid is not None
            else pos.exit_fill_price
        )
        if entry and entry > 0 and exit_:
            if pos.trade_type == "stock" and pos.signal == "BEARISH":
                raw = entry - exit_
            else:
                raw = exit_ - entry
            cap_pnl = (
                pos.slot_capital / entry * raw
                if pos.trade_type == "stock"
                else _D(pos.contracts) * _D("100") * raw
            )
        else:
            cap_pnl = _D("0")

        is_reentry = pos.trailing_arm_price is not None
        returned = cap_pnl if is_reentry else pos.slot_capital + cap_pnl

        with self._returned_lock:
            total = self._window_returned.get(pos.window_label, _D("0"))
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
        self._flush_session_state()

    def _flush_session_state(self) -> None:
        """Checkpoint all positions to disk. Skipped in mock/replay mode."""
        if self._mock_trade_execution:
            return
        try:
            _save_session(self._monitor.get_all_positions(), _now_et().date())
        except Exception:
            logger.exception("Failed to flush session state")

    def _recover_session(self, session_date: date) -> list:
        """Load today's checkpoint and broker-verify each saved open position.

        Skipped in mock/replay mode. Rebuilds _window_returned from closed
        positions so afternoon-window budgets are correct after a restart.
        Returns the list of verified open ActivePosition objects to re-add to
        the monitor.
        """
        if self._mock_trade_execution:
            return []

        all_saved = _load_session(session_date)
        if not all_saved:
            return []

        self._rebuild_window_returned([p for p in all_saved if p.is_closed])

        verified = []
        for pos in [p for p in all_saved if not p.is_closed]:
            try:
                status = self._client.order_status(pos.entry_order_id)
                if status.get("status") in ("filled", "partially_filled"):
                    if pos.entry_fill_price is None:
                        fill = status.get("filled_avg_price")
                        if fill is not None:
                            pos.entry_fill_price = _D(str(fill))
                    verified.append(pos)
                    logger.warning(
                        "RECOVERED position %s %s (order %s)",
                        pos.ticker,
                        pos.option_symbol or "stock",
                        pos.entry_order_id,
                    )
                else:
                    logger.warning(
                        "Skipping saved position %s — broker order status: %s",
                        pos.ticker,
                        status.get("status"),
                    )
            except Exception:
                logger.exception(
                    "Could not verify order %s for %s — skipping",
                    pos.entry_order_id,
                    pos.ticker,
                )

        return verified

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
            if self._is_circuit_breaker_tripped():
                logger.warning(
                    "Daily max-loss circuit breaker tripped [%s], skipping %s",
                    window_label,
                    event.ticker,
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
            if self._is_circuit_breaker_tripped():
                logger.warning(
                    "Daily max-loss circuit breaker tripped, stopping drain [%s]", label
                )
                break
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

        self._schedule_dd_check_for_window(win)

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

        option_type = "CALL" if signal == "BULLISH" else "PUT"
        option_type_lower = option_type.lower()

        entry_mid = limit_price
        if self._option_price_monitor and not self._mock_trade_execution:
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
            if self._mock_trade_execution:
                from .mock_option_pricer import mock_entry_price
                latest_bar = self._signal_engine.get_latest_bar(ticker)
                if latest_bar is not None:
                    stock_price = _D(str(latest_bar["Close"]))
                    entry_mid = mock_entry_price(stock_price, option_symbol, option_type_lower)
                    logger.info("MOCK ENTRY PRICE %s: %s", option_symbol, entry_mid)
            else:
                try:
                    q = self._client.get_option_quote_by_occ(option_symbol)
                    bid = _D(str(q["bid"]))
                    ask = _D(str(q["ask"]))
                    entry_mid = _D(str(q["mid"]))
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
        opm = self._option_price_monitor
        se = self._signal_engine
        option_type_lower = option_type.lower()
        def _entry_fair_price_fn():
            bar = se.get_latest_bar(ticker) if se else None
            stock_price = _D(str(bar["Close"])) if bar is not None else None
            return opm.get_fair_price(ticker, option_symbol, option_type_lower, stock_price)
        return _place_with_fill_escalation(
            client=self._client,
            ticker=ticker,
            option_symbol=option_symbol,
            option_type=option_type,
            contracts=contracts,
            order_action="BUY_OPEN",
            get_fair_price_fn=_entry_fair_price_fn if opm else None,
            feed=self._alpaca_feed,
        )

    def _check_ws_health(self, now) -> None:
        """Reconnect the WebSocket stream if no bar has been received for too long.

        Uses _stream_started_at as the baseline when no bar has ever arrived so
        the watchdog doesn't fire the instant the engine starts up.
        """
        engine = self._signal_engine
        if engine is None:
            return
        last = engine._last_bar_received_at or engine._stream_started_at
        if last is None:
            return
        elapsed = (now - last).total_seconds()
        if elapsed > self._ws_reconnect_timeout:
            logger.warning(
                "WebSocket watchdog: no bar received for %.0fs (threshold %ds) — reconnecting",
                elapsed,
                self._ws_reconnect_timeout,
            )
            try:
                engine.reconnect()
            except Exception:
                logger.exception("WebSocket reconnect failed")

    def _monitor_loop(self, active_tickers: list, session_date: date = None):
        eod_h, eod_m = [int(x) for x in EOD_EXIT_TIME.split(":")]
        end_h, end_m = [int(x) for x in SESSION_END_TIME.split(":")]
        last_status_print = _now_et()
        eod_triggered = False
        while True:
            now = _now_et()

            if not eod_triggered and (session_date is None or now.date() >= session_date) and (
                now.hour > eod_h or (now.hour == eod_h and now.minute >= eod_m)
            ):
                logger.info("EOD: force-closing all positions")
                self._monitor.close_all(reason="end_of_day")
                eod_triggered = True

            if eod_triggered:
                if now.hour > end_h or (now.hour == end_h and now.minute >= end_m):
                    logger.info("Session end: all fills confirmed, shutting down")
                    break
                self._monitor._refresh_fill_prices(self._monitor._positions)
                time.sleep(30)
                continue

            self._check_ws_health(now)

            for ticker in active_tickers:
                self._monitor.on_bar(ticker)

            if (now - last_status_print).total_seconds() >= 300:
                self._monitor.print_status()
                last_status_print = now

            time.sleep(30)

    def _run_window_selectors(self, all_tickers: list) -> list:
        """
        Fetch bars once, then score all unique window configs in parallel.
        Returns the pre-market picks for the first window.
        """
        # Deduplicate windows by (opening_start, opening_bars).
        unique_selectors = {}   # config_key -> TickerSelector
        first_config_key = None
        for win in self._windows:
            config_key = (win.opening_start, win.opening_bars)
            if config_key not in unique_selectors:
                unique_selectors[config_key] = TickerSelector(
                    tickers=all_tickers,
                    top_n=self._top_n,
                    stop_pct=float(self._stop_pct),
                    opening_start_time=win.opening_start,
                    opening_bars=win.opening_bars,
                    lookback_days=self._lookback_days,
                    regime_filter=self._regime_filter,
                    regime_ma=self._regime_ma,
                    alpaca_feed=self._alpaca_feed,
                )
                if first_config_key is None:
                    first_config_key = config_key

        # Fetch bar data once; all windows share the same date range.
        shared_ticker_dfs = unique_selectors[first_config_key].fetch_bars()

        # Score unique window configs in parallel.
        config_picks = {}
        if len(unique_selectors) > 1:
            with ThreadPoolExecutor(max_workers=len(unique_selectors)) as executor:
                future_to_key = {
                    executor.submit(sel.select, shared_ticker_dfs): key
                    for key, sel in unique_selectors.items()
                }
                for fut, key in [(f, future_to_key[f]) for f in future_to_key]:
                    config_picks[key] = fut.result()
        else:
            for key, sel in unique_selectors.items():
                config_picks[key] = sel.select(shared_ticker_dfs)

        # Map rolling stats back to each window label (including duplicates).
        for win in self._windows:
            config_key = (win.opening_start, win.opening_bars)
            self._rolling_stats_by_window[win.label] = unique_selectors[config_key].rolling_stats

        first_win = self._windows[0]
        return config_picks[(first_win.opening_start, first_win.opening_bars)]

    def run(self, tickers_override: list = None):
        today = _now_et().date()
        if not self._mock_trade_execution:
            if today.weekday() == 5:
                logger.warning("Today is Saturday (%s) — market is closed, exiting", today)
                return
            if _is_nyse_holiday(today):
                logger.warning("Today is a NYSE holiday (%s) — market is closed, exiting", today)
                return

        # Determine the trading session date. If started on Sunday or after market
        # close on a weekday, advance to the next trading day and sleep until
        # pre-market rather than exiting.
        now_et = _now_et()
        end_h, end_m = [int(x) for x in SESSION_END_TIME.split(":")]
        after_close = now_et.hour > end_h or (now_et.hour == end_h and now_et.minute >= end_m)
        if today.weekday() == 6 or after_close:
            session_date = _next_trading_day(today)
        else:
            session_date = today

        if session_date != today:
            premarket_dt = ET.localize(
                datetime.combine(session_date, datetime.strptime(_PREMARKET_WAIT_TIME, "%H:%M").time())
            )
            logger.info(
                "Engine started early — next session %s, sleeping until %s ET",
                session_date,
                premarket_dt.strftime("%Y-%m-%d %H:%M"),
            )
            last_log = _now_et()
            while _now_et() < premarket_dt:
                time.sleep(60)
                if (_now_et() - last_log).total_seconds() >= 3600:
                    remaining = premarket_dt - _now_et()
                    hours = int(remaining.total_seconds() // 3600)
                    minutes = int((remaining.total_seconds() % 3600) // 60)
                    logger.info("Waiting for session %s — ~%dh %dm remaining", session_date, hours, minutes)
                    last_log = _now_et()
            logger.info("Pre-market reached — starting session %s", session_date)

        api_key = self._api_key
        secret_key = self._secret_key

        logger.info("Alpaca data feed: %s", self._alpaca_feed.value.upper())
        all_tickers = tickers_override or TICKERS
        first_window = self._windows[0]

        self._window_returned = {}
        self._window_primary_deployed = {}
        self._rolling_stats_by_window = {}
        self._daily_realized_pnl = _D("0")
        self._dd_timers = {}
        self._dd_fired = set()
        pre_market_picks = self._run_window_selectors(all_tickers)
        self._rolling_stats = self._rolling_stats_by_window.get(first_window.label, {})
        logger.info("Pre-market top picks: %s", pre_market_picks)
        logger.info("Subscribing all %d tickers to live stream", len(all_tickers))
        if len(self._windows) > 1:
            labels = [
                f"[{w.label}] {w.opening_start}/{w.opening_bars}bar"
                for w in self._windows
            ]
            logger.info("Windows: %s", ", ".join(labels))

        # Build per-window state and signal engine window configs
        engine_windows = []
        for win in self._windows:
            opening_start_t = datetime.strptime(win.opening_start, "%H:%M").time()
            or_open_et = ET.localize(datetime.combine(session_date, opening_start_t))
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

        bar_recorder = BarRecorder(feed=self._alpaca_feed.value)
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
            alpaca_feed=self._alpaca_feed,
        )
        try:
            account = self._client.get_accounts()
            initial_capital = float(account.get("buying_power", ACCOUNT_BUDGET))
        except Exception:
            initial_capital = float(ACCOUNT_BUDGET)
        if self._replay_capital is not None:
            initial_capital = self._replay_capital

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
            alpaca_feed=self._alpaca_feed,
        )

        if self._option_price_monitor:
            self._option_price_monitor.start()

        recovered = self._recover_session(session_date)
        for pos in recovered:
            self._monitor.add_position(pos)
            label = pos.window_label
            if label in self._window_state:
                self._window_state[label]["open_position_count"] += 1
            if pos.trailing_arm_price is None and pos.slot_capital is not None:
                if label not in self._window_primary_deployed:
                    self._window_primary_deployed[label] = _D("0")
                self._window_primary_deployed[label] += pos.slot_capital

        self._signal_engine.start()

        for win in self._windows:
            t = threading.Thread(
                target=self._signal_selection_loop_for_window,
                args=(win,),
                daemon=True,
            )
            t.start()

        monitor_thread = threading.Thread(
            target=self._monitor_loop, args=(all_tickers, session_date), daemon=True
        )
        monitor_thread.start()
        monitor_thread.join()

        self._signal_engine.stop()
        if self._option_price_monitor:
            self._option_price_monitor.stop()
        bar_recorder.close()
        self._monitor.print_summary()

    def run_replay(
        self,
        replay_date,
        tickers_override: list = None,
        bars_source: "LiveBarsSource | None" = None,
        replay_exit_time: str = "15:55",
    ):
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

        logger.info("Alpaca data feed: %s", self._alpaca_feed.value.upper())
        all_tickers = tickers_override or TICKERS
        first_window = self._windows[0]

        self._window_returned = {}
        self._window_primary_deployed = {}
        self._rolling_stats_by_window = {}
        self._daily_realized_pnl = _D("0")
        self._dd_timers = {}
        self._dd_fired = set()
        pre_market_picks = self._run_window_selectors(all_tickers)
        self._rolling_stats = self._rolling_stats_by_window.get(first_window.label, {})
        logger.info("Replay %s — pre-market picks: %s", replay_date, pre_market_picks)

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
            alpaca_feed=self._alpaca_feed,
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
            alpaca_feed=self._alpaca_feed,
        )

        # In replay mode signals are drained synchronously in _on_bar (no background threads)
        # so that _drain_pending_signals_for_window runs while the replay clock is active.
        _drained_windows = set()

        # Pre-compute the DD check time for each window (OR close + doubledown_start_min).
        _dd_check_times = {}
        if self._enable_doubledown:
            for win in self._windows:
                opening_start_t = datetime.strptime(win.opening_start, "%H:%M").time()
                or_open_et = ET.localize(datetime.combine(replay_date, opening_start_t))
                or_close_et = or_open_et + timedelta(minutes=win.opening_bars * 5)
                _dd_check_times[win.label] = or_close_et + timedelta(
                    minutes=self._doubledown_start_min
                )
        _dd_checked_windows = set()

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
            # DD check fires after the window has been drained (positions entered).
            if self._enable_doubledown:
                for win in self._windows:
                    lbl = win.label
                    if (lbl in _drained_windows
                            and lbl not in _dd_checked_windows
                            and _now_et() >= _dd_check_times[lbl]):
                        _dd_checked_windows.add(lbl)
                        self._check_doubledown_for_window(win)
            self._monitor.on_bar(ticker)

        driver = BarReplayDriver(
            tickers=all_tickers,
            replay_date=replay_date,
            signal_engine=self._signal_engine,
            on_bar_injected=_on_bar,
            bars_source=bars_source,
            exit_time=replay_exit_time,
            feed=self._alpaca_feed.value,
        )
        driver.run()

        # BarReplayDriver.run() clears the replay clock internally.  Re-pin it to the
        # last bar's timestamp so close_all() records the correct exit time and uses
        # bar prices (not wall-clock time / live API quotes) for EOD-closed positions.
        # When the last bar is the EOD bar (15:55), advance the clock by 5 minutes so
        # close_all() records 16:00 (the bar's close time) rather than its open time.
        if driver.last_bar_time is not None:
            eod_h, eod_m = [int(x) for x in EOD_EXIT_TIME.split(":")]
            if driver.last_bar_time.time() >= _time(eod_h, eod_m):
                close_ts = driver.last_bar_time + timedelta(minutes=5)
            else:
                close_ts = driver.last_bar_time
            set_replay_clock(lambda ts=close_ts: ts)
        self._monitor.close_all(reason="end_of_day")
        clear_replay_clock()
        enable_notifications()
        self._monitor.print_summary()

    def run_replay_range(
        self,
        start_date: date,
        end_date: date,
        tickers_override: list = None,
        bars_source: "LiveBarsSource | None" = None,
        replay_exit_time: str = "15:55",
        compound: bool = False,
    ):
        """
        Run replay for every trading day in [start_date, end_date].

        Each day runs the full signal → entry → monitor → EOD-close pipeline via
        run_replay().  With compound=True the ending capital from each day becomes
        the starting capital for the next day.  With compound=False (default) the
        starting capital resets to self._replay_capital each day — equivalent to
        comparing daily edge in isolation.
        """
        days = _trading_days_in_range(start_date, end_date)
        if not days:
            logger.info("No trading days found in %s – %s", start_date, end_date)
            return

        original_capital = self._replay_capital
        initial = float(original_capital) if original_capital is not None else float(ACCOUNT_BUDGET)
        running_capital = initial
        daily_results = []  # [(date, cap_pnl)]

        for i, day in enumerate(days):
            logger.info("─" * 70)
            logger.info(
                "REPLAY %d/%d — %s  (starting capital: $%.2f)",
                i + 1, len(days), day, running_capital,
            )
            if compound:
                self._replay_capital = running_capital

            self.run_replay(
                day,
                tickers_override=tickers_override,
                bars_source=bars_source,
                replay_exit_time=replay_exit_time,
            )

            day_pnl = float(self._daily_realized_pnl)
            daily_results.append((day, day_pnl))
            running_capital += day_pnl

        self._replay_capital = original_capital

        total_pnl = sum(p for _, p in daily_results)
        wins = sum(1 for _, p in daily_results if p > 0)
        losses = len(daily_results) - wins
        logger.info("═" * 70)
        logger.info(
            "RANGE REPLAY COMPLETE: %s – %s  |  %d trading days  |  %d W / %d L  (%.0f%% WR)",
            start_date, end_date, len(days), wins, losses,
            wins / len(days) * 100,
        )
        logger.info("Total cap P&L: %+.2f", total_pnl)
        if compound:
            logger.info(
                "Compound return: %+.2f%%  ($%.2f → $%.2f)",
                total_pnl / initial * 100, initial, initial + total_pnl,
            )
        else:
            avg_pct = (total_pnl / len(days) / initial * 100) if initial else 0.0
            logger.info(
                "No-compound total: %+.2f  |  avg per day: %+.2f%%",
                total_pnl, avg_pct,
            )
        logger.info("═" * 70)

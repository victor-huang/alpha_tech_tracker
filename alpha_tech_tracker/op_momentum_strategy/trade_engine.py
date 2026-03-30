import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Optional

import pytz

from alpha_tech_tracker.op_momentum_strategy.op_momentum_backtest import fetch_bars
from alpha_tech_tracker.op_momentum_strategy.op_momentum_selector import (
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
    ROLLING_LOOKBACK_DAYS,
    SIGNAL_BUFFER_MINUTES,
    STOP_PCT,
    TICKERS,
    TRAILING_MA,
    _notify,
    ACCOUNT_BUDGET,
)
from .contract_selector import OptionContractSelector
from .models import ActivePosition, SignalEvent, WindowConfig, _D
from .order_executor import _place_with_fill_escalation
from .position_monitor import PositionMonitor
from .position_sizer import PositionSizer
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
    ):
        self._tickers = tickers
        self._top_n = top_n
        self._stop_pct = stop_pct
        self._opening_start_time = opening_start_time
        self.rolling_stats: dict = {}

    def select(self) -> list:
        today = datetime.now(ET).date()

        fetch_start = today - timedelta(days=max(ROLLING_LOOKBACK_DAYS, 30) + 5)
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
            lookback_days=ROLLING_LOOKBACK_DAYS,
            opening_bars=OPENING_BARS,
            bearish_ma200=BEARISH_MA200,
            stop_pct=self._stop_pct,
            source="alpaca",
            target_date=today,
            ticker_dfs=ticker_dfs,
            opening_start_time=self._opening_start_time,
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
                lookback_days=ROLLING_LOOKBACK_DAYS,
                opening_bars=OPENING_BARS,
                bearish_ma200=BEARISH_MA200,
                stop_pct=self._stop_pct,
                source="alpaca",
                target_date=prev_day,
                ticker_dfs=ticker_dfs,
                opening_start_time=self._opening_start_time,
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
        windows: Optional[list] = None,
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
        self._monitor: PositionMonitor = None
        self._signal_engine: LiveSignalEngine = None
        self._signal_lock = threading.Lock()
        self._rolling_stats: dict = {}
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
        today = datetime.now(ET).date()
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
    ):
        logger.info(
            "Entering position [%s]: %s %s @ %.2f (rank=%d)",
            window_label,
            event.ticker,
            event.signal,
            float(event.stock_price),
            rank,
        )
        try:
            selector = OptionContractSelector(self._client)
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
            if self._rank_weighted_sizing and rank < len(RANK_WEIGHTS):
                capital_weight = _D(str(RANK_WEIGHTS[rank]))
            else:
                capital_weight = _D("1")
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

        bull_hard_stop = event.or_high - self._stop_pct * event.or_range
        bear_hard_stop = event.or_low + self._stop_pct * event.or_range
        bull_fallback = event.or_high - _D("0.20") * event.or_range
        bear_fallback = event.or_low + _D("0.20") * event.or_range

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
            entry_time=datetime.now(ET),
            simulated_entry_mid=sim_entry_mid,
        )
        self._monitor.add_position(pos)

    def _get_window_budget(self, win: WindowConfig) -> Optional[_D]:
        """Return explicit window_budget for first-group windows; None for sequential."""
        if win.is_sequential:
            return None
        try:
            account = self._client.get_accounts()
            buying_power = _D(account.get("buying_power", ACCOUNT_BUDGET))
            return buying_power * _D(str(win.capital_fraction))
        except Exception:
            logger.exception(
                "Could not fetch account balance for window budget [%s]", win.label
            )
            return None

    def _on_signal_for_window(self, window_label: str, event: SignalEvent):
        now = datetime.now(ET)
        state = self._window_state[window_label]
        with self._signal_lock:
            if now < state["collection_deadline"]:
                state["pending_signals"][event.ticker] = event
                logger.info(
                    "Buffered signal [%s]: %s %s",
                    window_label,
                    event.ticker,
                    event.signal,
                )
                return
            if state["open_position_count"] >= MAX_ACTIVE_SYMBOLS:
                logger.info(
                    "Max positions reached [%s] (%d), skipping %s",
                    window_label,
                    MAX_ACTIVE_SYMBOLS,
                    event.ticker,
                )
                return
            state["open_position_count"] += 1

        win = next(w for w in self._windows if w.label == window_label)
        window_budget = self._get_window_budget(win)
        self._enter_position(
            event, rank=0, window_label=window_label, window_budget=window_budget
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
        while datetime.now(ET) < deadline:
            time.sleep(0.5)

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

        scored = []
        for ticker, event in pending.items():
            stats = self._rolling_stats.get(ticker, {})
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
        for rank, (score, ticker, event) in enumerate(scored):
            with self._signal_lock:
                if state["open_position_count"] >= MAX_ACTIVE_SYMBOLS:
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

        entry_mid = limit_price
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
            _notify(
                f"[SIMULATE] BUY {option_type} {option_symbol} x{contracts} @ ~{sim_mid}"
            )
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
        _notify(f"BUY {option_type} {option_symbol} x{contracts} entering {ticker}")
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
        last_status_print = datetime.now(ET)
        while True:
            now = datetime.now(ET)
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

        ticker_selector = TickerSelector(
            tickers=all_tickers,
            top_n=MAX_ACTIVE_SYMBOLS,
            stop_pct=float(self._stop_pct),
            opening_start_time=first_window.opening_start,
        )
        pre_market_picks = ticker_selector.select()
        self._rolling_stats = ticker_selector.rolling_stats
        print(f"\nPre-market top picks: {pre_market_picks}")
        print(f"Subscribing all {len(all_tickers)} tickers to live stream...")
        if len(self._windows) > 1:
            labels = [
                f"[{w.label}] {w.opening_start}/{w.opening_bars}bar"
                for w in self._windows
            ]
            print(f"Windows: {', '.join(labels)}")

        today = datetime.now(ET).date()

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

        self._signal_engine = LiveSignalEngine(
            tickers=all_tickers,
            api_key=api_key,
            secret_key=secret_key,
            bearish_ma200=BEARISH_MA200,
            regime_filter=self._regime_filter,
            regime_ma=self._regime_ma,
            windows=engine_windows,
        )
        self._monitor = PositionMonitor(
            self._client,
            self._signal_engine,
            mock_trade_execution=self._mock_trade_execution,
            trailing_ma=self._trailing_ma,
            max_loss_pct=self._max_loss_pct,
            armed_ma20_exit=self._armed_ma20_exit,
        )

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
        self._monitor.print_summary()

import argparse
import logging
import logging.handlers
import os
import signal
import sys
import time
from datetime import date

from alpaca.data.enums import DataFeed

from .config import (
    ARMED_MA20_EXIT,
    DAILY_MAX_LOSS_USD,
    MAX_LOSS_PCT,
    WS_RECONNECT_TIMEOUT_SECONDS,
    OPENING_BARS,
    OPENING_START_TIME,
    RANK_WEIGHTS,
    REGIME_FILTER,
    REGIME_MA,
    STOP_PCT,
    TRAILING_MA,
    _CONFIG_FILE,
    _load_config,
    build_execution_client,
    disable_notifications,
)
from .models import WindowConfig
from .op_momentum_selector import (
    ACTIVELY_TRADE_TICKERS,
    DEFAULT_TICKERS,
    ROLLING_LOOKBACK_DAYS as _DEFAULT_LOOKBACK_DAYS,
)
from .contract_selector import ITMOptionContractSelector, TimePremiumContractSelector
from .option_price_monitor import OptionPriceMonitor, TradeEngineStrikeSelector
from .trade_engine import OpMomentumTradeEngine

# re-export remaining config constants for backward compatibility
from .config import (  # noqa: F401
    ACCOUNT_BUDGET,
    BEARISH_MA200,
    EOD_EXIT_TIME,
    MA_WARMUP_DAYS,
    MAX_ACTIVE_SYMBOLS,
    OPENING_BARS,
    ROLLING_LOOKBACK_DAYS,
    SIGNAL_BUFFER_MINUTES,
    STRIKE_CALL_OFFSET,
    STRIKE_PUT_OFFSET,
    TICKERS,
)

logger = logging.getLogger(__name__)

_LOG_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "logs")
_PID_FILE = os.path.join(_LOG_DIR, "op_momentum.pid")


def _dated_log_file() -> str:
    """Return a log file path stamped with today's date, e.g. logs/op_momentum_2026-04-01.log."""
    return os.path.join(_LOG_DIR, f"op_momentum_{date.today()}.log")


def _make_log_handler(log_file: str) -> logging.handlers.TimedRotatingFileHandler:
    """Return a handler that rotates the log file at midnight and keeps 30 days."""
    handler = logging.handlers.TimedRotatingFileHandler(
        log_file, when="midnight", backupCount=30, encoding="utf-8"
    )
    # Rename rotated files: op_momentum_2026-04-01.log.2026-04-02 → op_momentum_2026-04-02.log
    import re
    handler.namer = lambda name: re.sub(r'(op_momentum)_[\d-]+(\.log)\.(\d{4}-\d{2}-\d{2})$',
                                        r'\1_\3\2', name)
    return handler


def _write_pid(pid_file: str):
    with open(pid_file, "w") as f:
        f.write(str(os.getpid()))


def _read_pid(pid_file: str):
    try:
        with open(pid_file) as f:
            return int(f.read().strip())
    except (FileNotFoundError, ValueError):
        return None


def _remove_pid(pid_file: str):
    try:
        os.remove(pid_file)
    except FileNotFoundError:
        pass


def _is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def _daemonize(log_file: str):
    """Double-fork to detach from terminal and run as a background daemon."""
    pid = os.fork()
    if pid > 0:
        sys.exit(0)

    os.setsid()

    pid = os.fork()
    if pid > 0:
        sys.exit(0)

    sys.stdout.flush()
    sys.stderr.flush()

    with open(os.devnull) as dev_null:
        os.dup2(dev_null.fileno(), sys.stdin.fileno())

    log_fd = open(log_file, "a")
    os.dup2(log_fd.fileno(), sys.stdout.fileno())
    os.dup2(log_fd.fileno(), sys.stderr.fileno())
    log_fd.close()


def _daemon_stop(pid_file: str, log_file: str):
    pid = _read_pid(pid_file)
    if pid is None or not _is_running(pid):
        print("Daemon is not running.")
        _remove_pid(pid_file)
        return

    print(f"Stopping daemon (PID {pid})...")
    os.kill(pid, signal.SIGTERM)

    for _ in range(20):
        time.sleep(0.5)
        if not _is_running(pid):
            break
    else:
        os.kill(pid, signal.SIGKILL)
        print(f"Daemon (PID {pid}) force-killed.")
        _remove_pid(pid_file)
        return

    _remove_pid(pid_file)
    print(f"Daemon stopped (PID {pid}).")


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


def parse_args():
    parser = argparse.ArgumentParser(description="OpMomentum live trade engine")
    parser.add_argument(
        "action",
        choices=["run", "start", "stop", "status", "restart"],
        help="run: foreground | start: daemon | stop | status | restart",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        default=False,
        help="Use live trading account (default: paper trading)",
    )
    parser.add_argument(
        "--mock-trade-execution",
        action="store_true",
        default=False,
        help="Simulate order fills at mid bid/ask — no real orders placed",
    )
    parser.add_argument(
        "--no-notify",
        action="store_true",
        default=False,
        dest="no_notify",
        help="Suppress all SMS and Telegram notifications for this session",
    )
    parser.add_argument(
        "--force-run",
        action="store_true",
        default=False,
        help="Bypass the market-hours gate and run immediately regardless of day/time. "
             "For off-hours integration testing only.",
    )
    parser.add_argument(
        "--tickers",
        nargs="+",
        default=None,
        help="Override ticker universe, e.g. --tickers NVDA CRWD",
    )
    parser.add_argument(
        "--ticker-set",
        choices=["V3", "AT"],
        default=None,
        help="Named ticker set: V3 (default pool) or AT (ACTIVELY_TRADE_TICKERS)",
    )
    parser.add_argument(
        "--stop-pct",
        type=float,
        default=float(STOP_PCT),
        help=f"Hard stop as fraction of OR range (default: {float(STOP_PCT)})",
    )
    parser.add_argument(
        "--trailing-ma",
        type=str,
        default=TRAILING_MA,
        choices=["ma20", "ma50", "both"],
        help="Trailing MA stop: ma20, ma50, or both (default: ma20)",
    )
    parser.add_argument(
        "--max-loss-pct",
        type=float,
        default=MAX_LOSS_PCT,
        help="Per-trade max loss as a fraction of entry stock price (e.g. 0.02 = 2%%). Default: disabled.",
    )
    parser.add_argument(
        "--daily-max-loss",
        type=float,
        default=DAILY_MAX_LOSS_USD,
        help="Daily max-loss circuit breaker in dollars (e.g. 500). No new entries once realized P&L drops below -N. Default: disabled.",
    )
    parser.add_argument(
        "--ws-reconnect-timeout",
        type=int,
        default=WS_RECONNECT_TIMEOUT_SECONDS,
        help=f"Seconds without a bar before the WebSocket stream is reconnected (default: {WS_RECONNECT_TIMEOUT_SECONDS}).",
    )
    parser.add_argument(
        "--armed-ma20-exit",
        action="store_true",
        default=ARMED_MA20_EXIT,
        help="Once hard stop is armed, use MA20 as trailing exit instead of hard_stop_price. Default: off.",
    )
    parser.add_argument(
        "--regime-filter",
        action="store_true",
        default=REGIME_FILTER,
        help="Suppress BULLISH signals on days when QQQ is below its N-day MA. Default: off.",
    )
    parser.add_argument(
        "--regime-ma",
        type=int,
        default=REGIME_MA,
        help=f"N-day MA period for QQQ regime filter (default: {REGIME_MA}).",
    )
    parser.add_argument(
        "--rank-weighted-sizing",
        type=int,
        nargs="+",
        default=None,
        metavar="W",
        dest="rank_weighted_sizing",
        help=(
            "Weight position size by rank. Pass weights as integers, e.g. "
            "--rank-weighted-sizing 60 40 or --rank-weighted-sizing 50 25 25. "
            f"Defaults to equal sizing when omitted. Legacy default: {RANK_WEIGHTS}."
        ),
    )
    parser.add_argument(
        "--opening-start",
        type=str,
        default=OPENING_START_TIME,
        help=f"Opening window start time HH:MM ET, single-window mode only (default: {OPENING_START_TIME})",
    )
    parser.add_argument(
        "--window",
        action="append",
        nargs=3,
        metavar=("LABEL", "START", "BARS"),
        default=None,
        help="Define a named trading window: LABEL START BARS (e.g. --window M1 09:30 3). "
        "Repeat to add multiple windows. Overrides --opening-start when specified.",
    )
    parser.add_argument(
        "--morning-split",
        nargs="+",
        type=float,
        default=None,
        help="Capital split %% for the first (simultaneous) group of windows, e.g. --morning-split 100. "
        "Number of values determines first-group size; remaining windows are sequential "
        "(each reads live account balance at signal time). Default: 100%% for first window.",
    )
    parser.add_argument(
        "--pid-file",
        type=str,
        default=_PID_FILE,
        help=f"PID file path (default: {_PID_FILE})",
    )
    parser.add_argument(
        "--log-file",
        type=str,
        default=None,
        help="Log file path (default: logs/op_momentum_YYYY-MM-DD.log)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    parser.add_argument(
        "--trade-type",
        type=str,
        default=None,
        choices=["options", "stock"],
        help="Trade type: options (live default) or stock (replay default)",
    )
    parser.add_argument(
        "--option-selector",
        type=str,
        default="standard",
        choices=["standard", "time-premium"],
        help="Option contract selector for live trading: "
        "'standard' uses ITMOptionContractSelector (fixed ±20%% ITM strike offset, default); "
        "'time-premium' uses TimePremiumContractSelector (shallowest ITM within DTE-adjusted time premium cap).",
    )
    parser.add_argument(
        "--time-premium-pct-cap",
        type=float,
        default=0.01,
        help="Max time premium as a fraction of stock price per reference DTE "
        "(default: 0.01 = 1%%). Only used when --option-selector time-premium is set. "
        "Threshold scales with DTE: 1%% / 5-day ref * actual DTE.",
    )
    parser.add_argument(
        "--collect-option-prices",
        action="store_true",
        default=False,
        help="Enable background option price collection and fair-price advisor. "
        "Writes 5-min snapshots to market_data/options_price_data/ and uses "
        "intrinsic value + cached time premium to compute entry/exit limit prices.",
    )
    parser.add_argument(
        "--record-tradestation-feed",
        action="store_true",
        default=False,
        dest="record_tradestation_feed",
        help="Record TradeStation 1-min and 5-min bar streams in parallel with the "
        "Alpaca feed. Writes CSVs to live_trade_market_data/{date}/tradestation_{ticker}_{timeframe}.csv. "
        "Requires valid TradeStation session tokens in config.json.",
    )
    parser.add_argument(
        "--option-price-interval",
        type=int,
        default=300,
        help="Snapshot interval in seconds for option price collection (default: 300)",
    )
    parser.add_argument(
        "--reversal",
        action="store_true",
        default=False,
        help="Enable reversal trade: if BEARISH primary stops out within N bars and "
        "price later crosses above OR high, enter BULLISH with midpoint as hard stop. Default: off.",
    )
    parser.add_argument(
        "--reversal-max-bars",
        type=int,
        default=3,
        dest="reversal_max_bars",
        help="Max bars_held for primary BEARISH trade to be eligible for reversal (default: 3).",
    )
    parser.add_argument(
        "--bearish-reentry",
        action="store_true",
        default=False,
        dest="bearish_reentry",
        help="Enable bearish re-entry: if BEARISH primary stops out within N bars and "
        "price later closes below OR low, re-enter short with midpoint as hard stop. Default: off.",
    )
    parser.add_argument(
        "--bearish-reentry-max-bars",
        type=int,
        default=3,
        dest="bearish_reentry_max_bars",
        help="Max bars_held for primary BEARISH trade to be eligible for bearish re-entry (default: 3).",
    )
    parser.add_argument(
        "--bullish-reentry",
        action="store_true",
        default=False,
        dest="bullish_reentry",
        help="Enable bullish re-entry: if BULLISH primary stops out within N bars and "
        "price later closes above OR high, re-enter long with midpoint as hard stop. Default: off.",
    )
    parser.add_argument(
        "--bullish-reentry-max-bars",
        type=int,
        default=5,
        dest="bullish_reentry_max_bars",
        help="Max bars_held for primary BULLISH trade to be eligible for bullish re-entry (default: 5).",
    )
    parser.add_argument(
        "--doubledown",
        action="store_true",
        default=False,
        help=(
            "Enable double-down add-on leg: when a co-pick stops out early, "
            "its freed capital is redeployed into the surviving position at a "
            "break-even hard stop. Fires once per window at OR close + doubledown-start."
        ),
    )
    parser.add_argument(
        "--doubledown-start",
        type=int,
        default=5,
        dest="doubledown_start_min",
        metavar="MINUTES",
        help=(
            "Minutes after OR close to fire the double-down check and enter the "
            "add-on leg. Must be a multiple of 5. Default: 5."
        ),
    )
    parser.add_argument(
        "--capital",
        type=float,
        default=None,
        dest="capital",
        help=(
            "Starting capital for cap P&L simulation in replay mode (e.g. 10000). "
            "Used as window budget for all windows so per-trade cap P&L matches the "
            "selector backtest. Has no effect in live mode."
        ),
    )
    parser.add_argument(
        "--replay-date",
        type=str,
        default=None,
        dest="replay_date",
        help="Replay a single historical session (YYYY-MM-DD). Feeds cached 5-min bars through "
        "the live engine instead of a live WebSocket stream. Implies mock-trade-execution.",
    )
    parser.add_argument(
        "--replay-start",
        type=str,
        default=None,
        dest="replay_start",
        help="Start date for a multi-day replay range (YYYY-MM-DD). Must be paired with --replay-end.",
    )
    parser.add_argument(
        "--replay-end",
        type=str,
        default=None,
        dest="replay_end",
        help="End date for a multi-day replay range (YYYY-MM-DD). Must be paired with --replay-start.",
    )
    parser.add_argument(
        "--compound",
        action="store_true",
        default=False,
        dest="compound",
        help="In range replay mode, carry ending capital forward day-to-day instead of resetting each day.",
    )
    parser.add_argument(
        "--live-data-dir",
        type=str,
        default=None,
        dest="live_data_dir",
        help=(
            "Directory of recorded live-session bar CSVs. When combined with "
            "--replay-date or --replay-start/--replay-end, feeds real intraday data instead of "
            "Alpaca historical cache. Expects {dir}/{date}/{feed}_{ticker}_5min.csv (CsvLiveBarsSource format)."
        ),
    )
    parser.add_argument(
        "--live-data-feed",
        choices=["iex", "sip", "tradestation"],
        default=None,
        dest="live_data_feed",
        help=(
            "Feed prefix used to locate CSV files under --live-data-dir "
            "(e.g. 'tradestation' → tradestation_{ticker}_5min.csv). "
            "Defaults to the value of --feed when not set."
        ),
    )
    parser.add_argument(
        "--full-day",
        action="store_true",
        default=False,
        dest="full_day",
        help=(
            "Replay the full market session including the 15:55 bar; close_all "
            "records exits at 16:00. By default replay exits at 15:55 so the "
            "EOD close does not interfere when adding afternoon windows. Use "
            "--full-day when replaying a complete session to market close."
        ),
    )
    parser.add_argument(
        "--top",
        type=int,
        default=MAX_ACTIVE_SYMBOLS,
        dest="top",
        help=f"Number of top-ranked tickers to trade per window (default: {MAX_ACTIVE_SYMBOLS}).",
    )
    parser.add_argument(
        "--lookback",
        type=int,
        default=_DEFAULT_LOOKBACK_DAYS,
        dest="lookback",
        help=f"Rolling lookback window in days for pre-market ticker scoring (default: {_DEFAULT_LOOKBACK_DAYS}).",
    )
    parser.add_argument(
        "--min-ev",
        type=float,
        default=0.0,
        dest="min_ev",
        help="Skip ticker if rolling ev_trade < threshold (default: 0.0, matches backtest behavior).",
    )
    parser.add_argument(
        "--feed",
        choices=["sip", "iex"],
        default="sip",
        help="Alpaca data feed: 'sip' (consolidated, default) or 'iex' (free tier).",
    )
    parser.add_argument(
        "--score-feed",
        choices=["sip", "iex"],
        default=None,
        dest="score_feed",
        help=(
            "Alpaca feed used for the 60-day selector lookback (scoring). "
            "Defaults to --feed when not set. "
            "Useful for replay: --feed iex --score-feed sip runs intraday bars from "
            "IEX while scoring tickers against the SIP 60-day history."
        ),
    )
    parser.add_argument(
        "--market-data-source",
        choices=["alpaca", "tradestation"],
        default="alpaca",
        dest="market_data_source",
        help="Market data source for live bar streaming and warmup (default: alpaca). "
        "'tradestation' requires valid TradeStation session tokens in config.json.",
    )
    parser.add_argument(
        "--execution-broker",
        choices=["alpaca", "tradestation", "etrade"],
        default=None,
        dest="execution_broker",
        help="Execution broker for order placement (default: value from config.json, "
        "fallback alpaca). Overrides 'execution_broker' in config.json when set.",
    )
    parser.add_argument(
        "--reset-session",
        action="store_true",
        default=False,
        dest="reset_session",
        help="Delete today's session checkpoint before starting, ignoring any saved positions "
        "and capital state from prior runs today. Use this to restart the engine fresh "
        "after manually closing positions or when the prior session state is corrupt.",
    )
    args = parser.parse_args()
    if args.rank_weighted_sizing and len(args.rank_weighted_sizing) != args.top:
        parser.error(
            f"--rank-weighted-sizing requires exactly --top weights "
            f"(got {len(args.rank_weighted_sizing)} weights, --top {args.top})"
        )
    return args


def _parse_windows(args) -> list:
    """Parse --window and --morning-split into a list of WindowConfig objects."""
    if not args.window:
        return None

    raw_windows = [
        {"label": w[0], "opening_start": w[1], "opening_bars": int(w[2])}
        for w in args.window
    ]
    n_windows = len(raw_windows)

    if args.morning_split:
        raw_split = args.morning_split
        total_pct = sum(raw_split)
        if total_pct > 100.0 + 1e-6:
            raise SystemExit(
                f"--morning-split values sum to {total_pct:.1f}%% which exceeds 100%%."
            )
        if len(raw_split) > n_windows:
            raise SystemExit(
                f"--morning-split has {len(raw_split)} values but only {n_windows} window(s) defined."
            )
        fractions = [v / 100.0 for v in raw_split]
        n_first = len(fractions)
    else:
        fractions = [1.0]
        n_first = 1

    windows = []
    for i, w in enumerate(raw_windows):
        if i < n_first:
            windows.append(
                WindowConfig(
                    label=w["label"],
                    opening_start=w["opening_start"],
                    opening_bars=w["opening_bars"],
                    capital_fraction=fractions[i],
                    is_sequential=False,
                )
            )
        else:
            windows.append(
                WindowConfig(
                    label=w["label"],
                    opening_start=w["opening_start"],
                    opening_bars=w["opening_bars"],
                    capital_fraction=1.0,
                    is_sequential=True,
                )
            )
    return windows


def _resolve_is_paper(args) -> bool:
    """Return True unless --live is set. --live is the sole control for paper vs live account."""
    return not getattr(args, "live", False)


def _build_market_data_client(args):
    """Return a MarketDataClient based on --market-data-source, or None for default Alpaca."""
    if getattr(args, "market_data_source", "alpaca") == "tradestation":
        from alpha_tech_tracker.op_momentum_strategy.config import (
            _load_config,
            _TRADESTATION_SESSION_TOKENS,
            TRADESTATION_ENVIRONMENT,
        )
        from alpha_tech_tracker.trade_api.tradestation.client import TradeStationAPIClient
        from alpha_tech_tracker.trade_api.tradestation.market_data_client import (
            TradeStationMarketDataClient,
        )
        _load_config()
        ts_client = TradeStationAPIClient(environment=TRADESTATION_ENVIRONMENT)
        ts_client.restore_session(_TRADESTATION_SESSION_TOKENS)
        if not ts_client.verify_session():
            raise RuntimeError(
                "TradeStation session invalid — run tradestation_auth.py first"
            )
        logger.info("Market data source: TradeStation (env=%s)", TRADESTATION_ENVIRONMENT)
        return TradeStationMarketDataClient(ts_client)
    return None  # caller defaults to AlpacaMarketDataClient


def _build_option_price_monitor(args, client, tickers, contract_selector):
    if not args.collect_option_prices:
        return None
    if not getattr(args, "live", False):
        logger.warning(
            "--collect-option-prices requires --live; option contract lookups will "
            "fail with 401 on the paper account (paper account lacks options approval)"
        )
    return OptionPriceMonitor(
        client=client,
        tickers=tickers or TICKERS,
        interval_seconds=args.option_price_interval,
        contract_selector=TradeEngineStrikeSelector(contract_selector),
        feed=DataFeed.IEX if args.feed == "iex" else DataFeed.SIP,
    )


def _build_contract_selector(args, client):
    if args.option_selector == "time-premium":
        return TimePremiumContractSelector(
            client, time_premium_pct_cap=args.time_premium_pct_cap
        )
    return ITMOptionContractSelector(client)


if __name__ == "__main__":
    args = parse_args()
    _TICKER_SETS = {"V3": DEFAULT_TICKERS, "AT": ACTIVELY_TRADE_TICKERS}
    args.tickers = args.tickers or _TICKER_SETS.get(args.ticker_set)
    _load_config()

    if args.no_notify:
        disable_notifications()

    log_file = args.log_file or _dated_log_file()
    os.makedirs(os.path.dirname(os.path.abspath(log_file)), exist_ok=True)

    windows = _parse_windows(args)

    if args.action == "run":
        _fmt = logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s — %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        _root = logging.getLogger()
        _root.setLevel(getattr(logging, args.log_level))
        _root.handlers.clear()
        _sh = logging.StreamHandler()
        _sh.setFormatter(_fmt)
        _root.addHandler(_sh)
        _fh = _make_log_handler(log_file)
        _fh.setFormatter(_fmt)
        _root.addHandler(_fh)
        for _noisy in ("urllib3", "requests", "requests_oauthlib", "oauthlib", "websockets"):
            logging.getLogger(_noisy).setLevel(logging.WARNING)
        is_replay = bool(args.replay_date) or bool(args.replay_start and args.replay_end)
        mock_trade_execution = args.mock_trade_execution or is_replay
        if args.trade_type is None:
            args.trade_type = "stock" if is_replay else "options"
        is_paper = _resolve_is_paper(args)
        # In mock/replay mode use Alpaca — avoids TradeStation OAuth port conflict
        # when running many parallel replays that would all fight over port 8080.
        effective_broker = "alpaca" if mock_trade_execution else args.execution_broker
        client = build_execution_client(is_paper=is_paper, broker=effective_broker)
        # In replay mode, pass None so OpMomentumTradeEngine uses MockContractSelector
        # (which builds synthetic ITM symbols without API calls using the session date).
        contract_selector = None if is_replay else _build_contract_selector(args, client)
        engine = OpMomentumTradeEngine(
            alpaca_client=client,
            is_paper=is_paper,
            stop_pct=args.stop_pct,
            mock_trade_execution=mock_trade_execution,
            opening_start_time=args.opening_start,
            trailing_ma=args.trailing_ma,
            max_loss_pct=args.max_loss_pct,
            daily_max_loss_usd=args.daily_max_loss,
            armed_ma20_exit=args.armed_ma20_exit,
            regime_filter=args.regime_filter,
            regime_ma=args.regime_ma,
            rank_weights=args.rank_weighted_sizing,
            windows=windows,
            trade_type=args.trade_type,
            contract_selector=contract_selector,
            option_price_monitor=_build_option_price_monitor(args, client, args.tickers, contract_selector),
            enable_reversal=args.reversal,
            reversal_max_bars=args.reversal_max_bars,
            enable_bearish_reentry=args.bearish_reentry,
            bearish_reentry_max_bars=args.bearish_reentry_max_bars,
            enable_bullish_reentry=args.bullish_reentry,
            bullish_reentry_max_bars=args.bullish_reentry_max_bars,
            top_n=args.top,
            lookback_days=args.lookback,
            min_ev=args.min_ev,
            replay_capital=args.capital,
            ws_reconnect_timeout=args.ws_reconnect_timeout,
            alpaca_feed=DataFeed.IEX if args.feed == "iex" else DataFeed.SIP,
            score_feed=DataFeed.IEX if args.score_feed == "iex" else DataFeed.SIP if args.score_feed == "sip" else None,
            enable_doubledown=args.doubledown,
            doubledown_start_min=args.doubledown_start_min,
            record_tradestation_feed=args.record_tradestation_feed,
            market_data_client=_build_market_data_client(args),
            force_run=args.force_run,
            reset_session=args.reset_session,
        )
        if args.replay_date:
            from datetime import date as _date
            from .replay import CsvLiveBarsSource
            from .config import EOD_EXIT_TIME
            replay_date = _date.fromisoformat(args.replay_date)
            csv_feed = args.live_data_feed or args.feed
            bars_source = CsvLiveBarsSource(args.live_data_dir, feed=csv_feed) if args.live_data_dir else None
            engine.run_replay(
                replay_date,
                tickers_override=args.tickers,
                bars_source=bars_source,
                replay_exit_time="16:05" if args.full_day else EOD_EXIT_TIME,
            )
        elif args.replay_start and args.replay_end:
            from datetime import date as _date
            from .replay import CsvLiveBarsSource
            from .config import EOD_EXIT_TIME
            start_date = _date.fromisoformat(args.replay_start)
            end_date = _date.fromisoformat(args.replay_end)
            csv_feed = args.live_data_feed or args.feed
            bars_source = CsvLiveBarsSource(args.live_data_dir, feed=csv_feed) if args.live_data_dir else None
            engine.run_replay_range(
                start_date,
                end_date,
                tickers_override=args.tickers,
                bars_source=bars_source,
                replay_exit_time="16:05" if args.full_day else EOD_EXIT_TIME,
                compound=args.compound,
            )
        else:
            engine.run(tickers_override=args.tickers)
        sys.exit(0)

    if args.action == "status":
        pid = _read_pid(args.pid_file)
        if pid and _is_running(pid):
            print(f"Daemon running (PID {pid}) — log: {log_file}")
        else:
            print("Daemon is not running.")
        sys.exit(0)

    if args.action == "stop":
        _daemon_stop(args.pid_file, log_file)
        sys.exit(0)

    if args.action == "restart":
        _daemon_stop(args.pid_file, log_file)

    # start / restart — check not already running
    existing_pid = _read_pid(args.pid_file)
    if existing_pid and _is_running(existing_pid):
        print(
            f"Daemon already running (PID {existing_pid}). Use 'restart' or 'stop' first."
        )
        sys.exit(1)

    print(f"Starting daemon — logs: {log_file}")
    _daemonize(log_file)

    # --- daemon process only beyond this point ---
    _write_pid(args.pid_file)

    _fmt = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    _root = logging.getLogger()
    _root.setLevel(getattr(logging, args.log_level))
    _root.handlers.clear()
    _fh = _make_log_handler(log_file)
    _fh.setFormatter(_fmt)
    _root.addHandler(_fh)
    for _noisy in ("urllib3", "requests", "requests_oauthlib", "oauthlib", "websockets"):
        logging.getLogger(_noisy).setLevel(logging.WARNING)
    logger.info(
        "Daemon started — api_key_set=%s config_file=%s",
        bool(os.environ.get("ALPACA_API_KEY")),
        _CONFIG_FILE,
    )

    try:
        is_paper = _resolve_is_paper(args)
        client = build_execution_client(is_paper=is_paper, broker=args.execution_broker)
        contract_selector = _build_contract_selector(args, client)
        engine = OpMomentumTradeEngine(
            alpaca_client=client,
            is_paper=is_paper,
            stop_pct=args.stop_pct,
            mock_trade_execution=args.mock_trade_execution,
            opening_start_time=args.opening_start,
            trailing_ma=args.trailing_ma,
            max_loss_pct=args.max_loss_pct,
            daily_max_loss_usd=args.daily_max_loss,
            armed_ma20_exit=args.armed_ma20_exit,
            regime_filter=args.regime_filter,
            regime_ma=args.regime_ma,
            rank_weights=args.rank_weighted_sizing,
            windows=windows,
            trade_type=args.trade_type,
            contract_selector=contract_selector,
            option_price_monitor=_build_option_price_monitor(args, client, args.tickers, contract_selector),
            enable_reversal=args.reversal,
            reversal_max_bars=args.reversal_max_bars,
            enable_bearish_reentry=args.bearish_reentry,
            bearish_reentry_max_bars=args.bearish_reentry_max_bars,
            enable_bullish_reentry=args.bullish_reentry,
            bullish_reentry_max_bars=args.bullish_reentry_max_bars,
            top_n=args.top,
            lookback_days=args.lookback,
            min_ev=args.min_ev,
            replay_capital=args.capital,
            ws_reconnect_timeout=args.ws_reconnect_timeout,
            alpaca_feed=DataFeed.IEX if args.feed == "iex" else DataFeed.SIP,
            score_feed=DataFeed.IEX if args.score_feed == "iex" else DataFeed.SIP if args.score_feed == "sip" else None,
            enable_doubledown=args.doubledown,
            doubledown_start_min=args.doubledown_start_min,
            record_tradestation_feed=args.record_tradestation_feed,
            market_data_client=_build_market_data_client(args),
            force_run=args.force_run,
            reset_session=args.reset_session,
        )
        engine.run(tickers_override=args.tickers)
    finally:
        _remove_pid(args.pid_file)

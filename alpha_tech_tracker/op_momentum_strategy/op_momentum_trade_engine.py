import argparse
import logging
import logging.handlers
import os
import signal
import sys
import time
from datetime import date

from alpha_tech_tracker.trade_api.alpaca_client.client import AlpacaAPIClient

from .config import (
    ARMED_MA20_EXIT,
    MAX_LOSS_PCT,
    OPENING_BARS,
    OPENING_START_TIME,
    RANK_WEIGHTED_SIZING,
    RANK_WEIGHTS,
    REGIME_FILTER,
    REGIME_MA,
    STOP_PCT,
    TRAILING_MA,
    _CONFIG_FILE,
    _load_config,
)
from .models import WindowConfig
from .op_momentum_selector import ROLLING_LOOKBACK_DAYS as _DEFAULT_LOOKBACK_DAYS
from .contract_selector import OptionContractSelector, TimePremiumContractSelector
from .option_price_monitor import OptionPriceMonitor
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

_PID_FILE = os.path.expanduser("~/.op_momentum_daemon.pid")
_LOG_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "logs")


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
        "--tickers",
        nargs="+",
        default=None,
        help="Override ticker universe, e.g. --tickers NVDA CRWD",
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
        action="store_true",
        default=RANK_WEIGHTED_SIZING,
        help=f"Weight position size by ticker rank using {RANK_WEIGHTS} (default: off).",
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
        default="options",
        choices=["options", "stock"],
        help="Trade type: options (default) or stock",
    )
    parser.add_argument(
        "--option-selector",
        type=str,
        default="standard",
        choices=["standard", "time-premium"],
        help="Option contract selector for live trading: "
        "'standard' uses OptionContractSelector (fixed ±20%% ITM strike offset, default); "
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
        help="Replay a historical session (YYYY-MM-DD). Feeds cached 5-min bars through "
        "the live engine instead of a live WebSocket stream. Implies mock-trade-execution.",
    )
    parser.add_argument(
        "--live-data-dir",
        type=str,
        default=None,
        dest="live_data_dir",
        help=(
            "Directory of recorded live-session bar CSVs. When combined with "
            "--replay-date, feeds real intraday data instead of Alpaca historical "
            "cache. Expects {dir}/{date}/{ticker}_5min.csv (CsvLiveBarsSource format)."
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
    return parser.parse_args()


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


def _build_option_price_monitor(args, client, tickers):
    if not args.collect_option_prices:
        return None
    return OptionPriceMonitor(
        client=client,
        tickers=tickers or TICKERS,
        interval_seconds=args.option_price_interval,
    )


def _build_contract_selector(args, client):
    if args.option_selector == "time-premium":
        return TimePremiumContractSelector(
            client, time_premium_pct_cap=args.time_premium_pct_cap
        )
    return OptionContractSelector(client)


if __name__ == "__main__":
    args = parse_args()
    _load_config()

    log_file = args.log_file or _dated_log_file()
    os.makedirs(os.path.dirname(os.path.abspath(log_file)), exist_ok=True)

    windows = _parse_windows(args)

    if args.action == "run":
        logging.basicConfig(
            level=getattr(logging, args.log_level),
            format="%(asctime)s %(levelname)s %(name)s — %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
            handlers=[logging.StreamHandler(), _make_log_handler(log_file)],
        )
        is_paper = not (args.live or args.mock_trade_execution)
        client = AlpacaAPIClient(is_paper_trading=is_paper)
        engine = OpMomentumTradeEngine(
            alpaca_client=client,
            is_paper=is_paper,
            stop_pct=args.stop_pct,
            mock_trade_execution=args.mock_trade_execution,
            opening_start_time=args.opening_start,
            trailing_ma=args.trailing_ma,
            max_loss_pct=args.max_loss_pct,
            armed_ma20_exit=args.armed_ma20_exit,
            regime_filter=args.regime_filter,
            regime_ma=args.regime_ma,
            rank_weighted_sizing=args.rank_weighted_sizing,
            windows=windows,
            trade_type=args.trade_type,
            option_price_monitor=_build_option_price_monitor(args, client, args.tickers),
            contract_selector=_build_contract_selector(args, client),
            enable_reversal=args.reversal,
            reversal_max_bars=args.reversal_max_bars,
            enable_bearish_reentry=args.bearish_reentry,
            bearish_reentry_max_bars=args.bearish_reentry_max_bars,
            enable_bullish_reentry=args.bullish_reentry,
            bullish_reentry_max_bars=args.bullish_reentry_max_bars,
            top_n=args.top,
            lookback_days=args.lookback,
            replay_capital=args.capital,
        )
        if args.replay_date:
            from datetime import date as _date
            from .replay import CsvLiveBarsSource
            replay_date = _date.fromisoformat(args.replay_date)
            bars_source = CsvLiveBarsSource(args.live_data_dir) if args.live_data_dir else None
            engine.run_replay(
                replay_date,
                tickers_override=args.tickers,
                bars_source=bars_source,
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

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[_make_log_handler(log_file)],
    )
    logger.info(
        "Daemon started — api_key_set=%s config_file=%s",
        bool(os.environ.get("ALPACA_API_KEY")),
        _CONFIG_FILE,
    )

    try:
        is_paper = not (args.live or args.mock_trade_execution)
        client = AlpacaAPIClient(is_paper_trading=is_paper)
        engine = OpMomentumTradeEngine(
            alpaca_client=client,
            is_paper=is_paper,
            stop_pct=args.stop_pct,
            mock_trade_execution=args.mock_trade_execution,
            opening_start_time=args.opening_start,
            trailing_ma=args.trailing_ma,
            max_loss_pct=args.max_loss_pct,
            armed_ma20_exit=args.armed_ma20_exit,
            regime_filter=args.regime_filter,
            regime_ma=args.regime_ma,
            rank_weighted_sizing=args.rank_weighted_sizing,
            windows=windows,
            trade_type=args.trade_type,
            option_price_monitor=_build_option_price_monitor(args, client, args.tickers),
            contract_selector=_build_contract_selector(args, client),
            enable_reversal=args.reversal,
            reversal_max_bars=args.reversal_max_bars,
            enable_bearish_reentry=args.bearish_reentry,
            bearish_reentry_max_bars=args.bearish_reentry_max_bars,
            enable_bullish_reentry=args.bullish_reentry,
            bullish_reentry_max_bars=args.bullish_reentry_max_bars,
            top_n=args.top,
            lookback_days=args.lookback,
            replay_capital=args.capital,
        )
        engine.run(tickers_override=args.tickers)
    finally:
        _remove_pid(args.pid_file)

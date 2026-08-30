"""OpMomentum live trade engine — CLI entry point.

The implementation lives in the `cli` package; this module wires the pieces
together for `python -m ...op_momentum_trade_engine {run,start,stop,status,restart}`
and re-exports the names other modules and tests import from here.
"""
import logging
import os
import sys

from .cli import (  # noqa: F401  — re-exported for backward compatibility
    _LOG_DIR,
    _PID_FILE,
    _build_contract_selector,
    _build_market_data_client,
    _build_option_price_monitor,
    _build_sip_quote_client,
    _daemon_stop,
    _daemonize,
    _dated_log_file,
    _is_running,
    _make_log_handler,
    _parse_windows,
    _read_pid,
    _remove_pid,
    _resolve_is_paper,
    _warn_replay_feed_mismatch,
    _write_pid,
    build_engine,
    parse_args,
)
from .config import _CONFIG_FILE, _load_config, build_execution_client, disable_notifications
from .op_momentum_selector import ACTIVELY_TRADE_TICKERS, DEFAULT_TICKERS
from .trade_engine import OpMomentumTradeEngine  # noqa: F401

# re-export remaining config constants for backward compatibility
from .config import (  # noqa: F401
    ACCOUNT_BUDGET,
    BEARISH_MA200,
    EOD_EXIT_TIME,
    MA_WARMUP_DAYS,
    MAX_ACTIVE_SYMBOLS,
    OPENING_BARS,
    ROLLING_LOOKBACK_DAYS,
    BAR_AGG_GRACE_SECONDS,
    SIGNAL_BUFFER_SECONDS,
    STRIKE_CALL_OFFSET,
    STRIKE_PUT_OFFSET,
    TICKERS,
)

logger = logging.getLogger(__name__)

_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s — %(message)s"
_LOG_DATEFMT = "%Y-%m-%d %H:%M:%S"
_NOISY_LOGGERS = ("urllib3", "requests", "requests_oauthlib", "oauthlib", "websockets")


def _configure_logging(log_file: str, log_level: str, to_stream: bool):
    """Install the root log handlers. `to_stream` adds terminal output (foreground run)."""
    fmt = logging.Formatter(_LOG_FORMAT, datefmt=_LOG_DATEFMT)
    root = logging.getLogger()
    root.setLevel(getattr(logging, log_level))
    root.handlers.clear()
    if to_stream:
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        root.addHandler(sh)
    fh = _make_log_handler(log_file)
    fh.setFormatter(fmt)
    root.addHandler(fh)
    for noisy in _NOISY_LOGGERS:
        logging.getLogger(noisy).setLevel(logging.WARNING)


def _run_foreground(args, windows, log_file):
    _configure_logging(log_file, args.log_level, to_stream=True)
    is_replay = bool(args.replay_date) or bool(args.replay_start and args.replay_end)
    mock_trade_execution = args.mock_trade_execution or is_replay
    if args.trade_type is None:
        args.trade_type = "stock" if is_replay else "options"
    is_paper = _resolve_is_paper(args)
    # In mock/replay mode use Alpaca — avoids TradeStation OAuth port conflict
    # when running many parallel replays that would all fight over port 8080.
    effective_broker = "alpaca" if mock_trade_execution else args.execution_broker
    sip_quote_client = None if mock_trade_execution else _build_sip_quote_client(args)
    client = build_execution_client(
        is_paper=is_paper, broker=effective_broker, sip_quote_client=sip_quote_client
    )
    # In replay mode, pass None so OpMomentumTradeEngine uses MockContractSelector
    # (which builds synthetic ITM symbols without API calls using the session date).
    contract_selector = None if is_replay else _build_contract_selector(args, client)
    engine = build_engine(
        args,
        client=client,
        is_paper=is_paper,
        mock_trade_execution=mock_trade_execution,
        contract_selector=contract_selector,
        windows=windows,
    )
    if args.replay_date or (args.replay_start and args.replay_end):
        _warn_replay_feed_mismatch(args)

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


def _run_daemon(args, windows, log_file):
    """Daemonize, then run the engine. Does not return in the parent process."""
    print(f"Starting daemon — logs: {log_file}")
    _daemonize(log_file)

    # --- daemon process only beyond this point ---
    _write_pid(args.pid_file)

    _configure_logging(log_file, args.log_level, to_stream=False)
    logger.info(
        "Daemon started — api_key_set=%s config_file=%s",
        bool(os.environ.get("ALPACA_API_KEY")),
        _CONFIG_FILE,
    )

    try:
        is_paper = _resolve_is_paper(args)
        sip_quote_client = _build_sip_quote_client(args)
        client = build_execution_client(
            is_paper=is_paper, broker=args.execution_broker, sip_quote_client=sip_quote_client
        )
        contract_selector = _build_contract_selector(args, client)
        engine = build_engine(
            args,
            client=client,
            is_paper=is_paper,
            mock_trade_execution=args.mock_trade_execution,
            contract_selector=contract_selector,
            windows=windows,
        )
        engine.run(tickers_override=args.tickers)
    finally:
        _remove_pid(args.pid_file)


def main():
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
        _run_foreground(args, windows, log_file)
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

    _run_daemon(args, windows, log_file)


if __name__ == "__main__":
    main()

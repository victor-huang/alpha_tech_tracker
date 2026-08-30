"""CLI layer for the OpMomentum trade engine.

Split out of the former single-file op_momentum_trade_engine.py:

  args.py            argparse definition (`parse_args`)
  windows.py         `_parse_windows`, `_resolve_is_paper`
  clients.py         market-data / quote / contract-selector construction
  daemon.py          daemonize, PID file, log rotation
  engine_builder.py  the single `build_engine(args, ...)` call site
"""
from .args import parse_args
from .clients import (
    _build_contract_selector,
    _build_market_data_client,
    _build_option_price_monitor,
    _build_sip_quote_client,
    _warn_replay_feed_mismatch,
)
from .daemon import (
    _LOG_DIR,
    _PID_FILE,
    _daemon_stop,
    _daemonize,
    _dated_log_file,
    _is_running,
    _make_log_handler,
    _read_pid,
    _remove_pid,
    _write_pid,
)
from .engine_builder import build_engine
from .windows import _parse_windows, _resolve_is_paper

__all__ = [
    "parse_args",
    "build_engine",
    "_parse_windows",
    "_resolve_is_paper",
    "_build_contract_selector",
    "_build_market_data_client",
    "_build_option_price_monitor",
    "_build_sip_quote_client",
    "_warn_replay_feed_mismatch",
    "_dated_log_file",
    "_make_log_handler",
    "_daemonize",
    "_daemon_stop",
    "_read_pid",
    "_write_pid",
    "_remove_pid",
    "_is_running",
    "_LOG_DIR",
    "_PID_FILE",
]

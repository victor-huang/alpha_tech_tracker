import argparse
import json
import logging
import logging.handlers
import os
import signal
import socket
import sys
import threading
import time
from datetime import date, datetime, timezone

from alpha_tech_tracker.trade_api.tradestation.bar_stream import TradeStationBarStream

logger = logging.getLogger(__name__)

_LOG_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "logs")
_PID_FILE = os.path.join(_LOG_DIR, "bar_broadcaster.pid")
_DEFAULT_SOCKET_PATH = "/tmp/ts_bar_feed.sock"
_HEARTBEAT_INTERVAL = 30  # seconds


# ---------------------------------------------------------------------------
# Daemon helpers (mirror op_momentum_trade_engine.py pattern)
# ---------------------------------------------------------------------------

def _dated_log_file() -> str:
    return os.path.join(_LOG_DIR, f"bar_broadcaster_{date.today()}.log")


def _setup_logging(log_file, log_level: str):
    level = getattr(logging, log_level.upper(), logging.INFO)
    handlers = []
    if log_file:
        import re
        file_handler = logging.handlers.TimedRotatingFileHandler(
            log_file, when="midnight", backupCount=30, encoding="utf-8"
        )
        file_handler.namer = lambda name: re.sub(
            r'(bar_broadcaster)_[\d-]+(\.log)\.(\d{4}-\d{2}-\d{2})$',
            r'\1_\3\2',
            name,
        )
        handlers.append(file_handler)
    else:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=level, handlers=handlers,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")


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
    """Double-fork to detach from terminal."""
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


def _daemon_stop():
    pid = _read_pid(_PID_FILE)
    if pid is None or not _is_running(pid):
        print("Broadcaster is not running.")
        _remove_pid(_PID_FILE)
        return
    print(f"Stopping broadcaster (PID {pid})...")
    os.kill(pid, signal.SIGTERM)
    for _ in range(20):
        time.sleep(0.5)
        if not _is_running(pid):
            break
    else:
        os.kill(pid, signal.SIGKILL)
        print(f"Broadcaster (PID {pid}) force-killed.")
        _remove_pid(_PID_FILE)
        return
    _remove_pid(_PID_FILE)
    print(f"Broadcaster stopped (PID {pid}).")


# ---------------------------------------------------------------------------
# BarBroadcaster
# ---------------------------------------------------------------------------

class BarBroadcaster:
    """
    Holds a single TradeStationBarStream and fans out closed 1-min bars to all
    connected Unix domain socket clients as newline-delimited JSON.

    Message types:
      {"type": "bar", "symbol": ..., "timestamp": ..., "open": ..., ...}
      {"type": "heartbeat", "ts": ...}
    """

    def __init__(self, ts_client, tickers: list, socket_path: str = _DEFAULT_SOCKET_PATH):
        self._ts_client = ts_client
        self._tickers = tickers
        self._socket_path = socket_path
        self._clients: list = []
        self._clients_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._server_sock = None
        self._stream: TradeStationBarStream = None

    def _bar_to_line(self, bar) -> str:
        return json.dumps({
            "type": "bar",
            "symbol": bar.symbol,
            "timestamp": bar.timestamp.isoformat(),
            "open": bar.open,
            "high": bar.high,
            "low": bar.low,
            "close": bar.close,
            "volume": bar.volume,
        }) + "\n"

    def _heartbeat_line(self) -> str:
        return json.dumps({
            "type": "heartbeat",
            "ts": datetime.now(tz=timezone.utc).isoformat(),
        }) + "\n"

    def _broadcast(self, line: str):
        encoded = line.encode()
        dead = []
        with self._clients_lock:
            clients = list(self._clients)
        for sock in clients:
            try:
                sock.sendall(encoded)
            except OSError:
                dead.append(sock)
        if dead:
            with self._clients_lock:
                for sock in dead:
                    try:
                        sock.close()
                    except OSError:
                        pass
                    if sock in self._clients:
                        self._clients.remove(sock)
            logger.info("Removed %d disconnected client(s)", len(dead))

    def _on_bar(self, bar):
        logger.debug("Bar: %s %s close=%.2f", bar.symbol, bar.timestamp, bar.close)
        self._broadcast(self._bar_to_line(bar))

    def _accept_loop(self):
        while not self._stop_event.is_set():
            self._server_sock.settimeout(1.0)
            try:
                client_sock, _ = self._server_sock.accept()
            except socket.timeout:
                continue
            except OSError:
                if not self._stop_event.is_set():
                    logger.exception("Accept loop error")
                break
            with self._clients_lock:
                self._clients.append(client_sock)
            logger.info(
                "Client connected — %d client(s) active", len(self._clients)
            )

    def _heartbeat_loop(self):
        while not self._stop_event.wait(_HEARTBEAT_INTERVAL):
            self._broadcast(self._heartbeat_line())
            with self._clients_lock:
                count = len(self._clients)
            logger.debug("Heartbeat sent to %d client(s)", count)

    def start(self):
        os.makedirs(_LOG_DIR, exist_ok=True)
        try:
            os.unlink(self._socket_path)
        except FileNotFoundError:
            pass

        self._server_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server_sock.bind(self._socket_path)
        self._server_sock.listen(10)
        logger.info(
            "Bar broadcaster listening on %s for %d tickers: %s",
            self._socket_path,
            len(self._tickers),
            self._tickers,
        )

        threading.Thread(
            target=self._accept_loop,
            name="broadcaster-accept",
            daemon=True,
        ).start()
        threading.Thread(
            target=self._heartbeat_loop,
            name="broadcaster-heartbeat",
            daemon=True,
        ).start()

        self._stream = TradeStationBarStream(
            self._ts_client, interval=1, unit="Minute", barsback=5
        )
        self._stream.subscribe_bars(self._on_bar, *self._tickers)
        self._stream.run()  # blocks until stop() sets the stream's stop_event

    def stop(self):
        logger.info("Stopping broadcaster")
        self._stop_event.set()
        if self._stream:
            self._stream.stop()
        with self._clients_lock:
            for sock in self._clients:
                try:
                    sock.close()
                except OSError:
                    pass
            self._clients.clear()
        if self._server_sock:
            try:
                self._server_sock.close()
            except OSError:
                pass
        try:
            os.unlink(self._socket_path)
        except FileNotFoundError:
            pass


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_broadcaster(args) -> BarBroadcaster:
    from alpha_tech_tracker.op_momentum_strategy.config import (
        _load_config,
        _TRADESTATION_SESSION_TOKENS,
        TRADESTATION_ENVIRONMENT,
    )
    from alpha_tech_tracker.trade_api.tradestation.client import TradeStationAPIClient

    _load_config()
    ts_client = TradeStationAPIClient(environment=TRADESTATION_ENVIRONMENT)
    ts_client.restore_session(_TRADESTATION_SESSION_TOKENS)
    if not ts_client.verify_session():
        raise RuntimeError(
            "TradeStation session invalid — run tradestation_auth.py first"
        )
    socket_path = getattr(args, "socket_path", _DEFAULT_SOCKET_PATH) or _DEFAULT_SOCKET_PATH
    return BarBroadcaster(ts_client, args.tickers, socket_path=socket_path)


def _run_foreground(args):
    _setup_logging(log_file=None, log_level=args.log_level)
    broadcaster = _build_broadcaster(args)

    def _on_signal(sig, frame):
        broadcaster.stop()

    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)
    broadcaster.start()


def _run_daemon(args):
    log_file = _dated_log_file()
    _daemonize(log_file)
    _write_pid(_PID_FILE)
    _setup_logging(log_file=log_file, log_level=args.log_level)
    broadcaster = _build_broadcaster(args)

    def _on_signal(sig, frame):
        broadcaster.stop()
        _remove_pid(_PID_FILE)

    signal.signal(signal.SIGTERM, _on_signal)
    broadcaster.start()
    _remove_pid(_PID_FILE)


def _parse_args():
    parser = argparse.ArgumentParser(description="Bar broadcaster — fans out TS bars over Unix socket")
    parser.add_argument(
        "action",
        choices=["run", "start", "stop", "status", "restart"],
        help="run: foreground | start: daemon | stop | status | restart",
    )
    parser.add_argument(
        "--tickers",
        nargs="+",
        default=[
            "SNDK", "APP", "SHOP", "CVNA", "AMD", "META",
            "EXPE", "RH", "FN", "MU", "CRDO",
            "PLTR", "COIN", "CLS", "MSTR", "CRWV", "MRVL",
        ],
        help="Tickers to stream (default: V3 pool)",
    )
    parser.add_argument(
        "--socket-path",
        default=_DEFAULT_SOCKET_PATH,
        dest="socket_path",
        help=f"Unix domain socket path (default: {_DEFAULT_SOCKET_PATH})",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        dest="log_level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    return parser.parse_args()


def main():
    args = _parse_args()

    if args.action == "run":
        _run_foreground(args)

    elif args.action == "start":
        pid = _read_pid(_PID_FILE)
        if pid and _is_running(pid):
            print(f"Broadcaster already running (PID {pid}).")
            sys.exit(1)
        _run_daemon(args)

    elif args.action == "stop":
        _daemon_stop()

    elif args.action == "status":
        pid = _read_pid(_PID_FILE)
        if pid and _is_running(pid):
            print(f"Running (PID {pid})")
        else:
            print("Not running")

    elif args.action == "restart":
        _daemon_stop()
        time.sleep(1)
        _run_daemon(args)


if __name__ == "__main__":
    main()

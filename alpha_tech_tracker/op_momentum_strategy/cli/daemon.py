"""Daemon lifecycle and log rotation for the OpMomentum trade engine CLI.

Extracted verbatim from op_momentum_trade_engine.py — no behavior changes.
_LOG_DIR is resolved relative to the package root so it keeps pointing at
<repo>/logs regardless of which module holds this code.
"""
import logging
import logging.handlers
import os
import signal
import sys
import time
from datetime import date

logger = logging.getLogger(__name__)

# Three levels up from op_momentum_strategy/cli/ is the repo root, the same
# directory the pre-split module reached with two levels from op_momentum_strategy/.
# normpath collapses the traversal so the stored value is a clean absolute path.
_LOG_DIR = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "logs")
)
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

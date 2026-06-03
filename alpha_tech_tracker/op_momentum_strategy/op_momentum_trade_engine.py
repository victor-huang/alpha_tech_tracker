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
    TRAILING_MA_SWITCH,
    TRAILING_MA_SWITCH_FACTOR,
    TRAILING_MA_SWITCH_PERIOD,
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
    BAR_AGG_GRACE_SECONDS,
    SIGNAL_BUFFER_SECONDS,
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
        "--trailing-ma-switch",
        choices=["none", "after-arm", "after-target"],
        default=TRAILING_MA_SWITCH,
        dest="trailing_ma_switch",
        help="Upgrade trailing stop to a faster MA once a profit threshold is reached. "
        "after-arm: upgrade when favorable move >= 1x OR range. "
        "after-target: upgrade at factor x OR range (see --trailing-ma-switch-factor). "
        f"Default: {TRAILING_MA_SWITCH}.",
    )
    parser.add_argument(
        "--trailing-ma-switch-period",
        type=int,
        default=TRAILING_MA_SWITCH_PERIOD,
        dest="trailing_ma_switch_period",
        help=f"Period of the fast MA used after the switch threshold is hit (default: {TRAILING_MA_SWITCH_PERIOD}).",
    )
    parser.add_argument(
        "--trailing-ma-switch-factor",
        type=float,
        default=TRAILING_MA_SWITCH_FACTOR,
        dest="trailing_ma_switch_factor",
        help=f"OR-range multiplier for --trailing-ma-switch after-target (default: {TRAILING_MA_SWITCH_FACTOR}).",
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
        "--enable-regime-engine",
        action="store_true",
        default=False,
        help=(
            "Enable MASTER_REGIME_SUMMARY pattern-based regime engine. "
            "Instantiates RegimeEngine; direction filter applied to all signals. "
            "Unrelated to --regime-filter (QQQ MA). Default: off."
        ),
    )
    parser.add_argument(
        "--regime-hold",
        action="store_true",
        default=False,
        help="Apply regime hold window as timed exit. Requires --enable-regime-engine. Default: off.",
    )
    parser.add_argument(
        "--disable-ma-stops-for-regime-hold-only",
        action="store_true",
        default=False,
        dest="disable_ma_stops_for_regime_hold",
        help=(
            "Disable trailing MA stop (MA20/MA50) when --regime-hold is active. "
            "Hard stop always remains armed. Requires --regime-hold. Default: off."
        ),
    )
    parser.add_argument(
        "--selector",
        choices=["score-rank", "win-rate"],
        default="score-rank",
        dest="selector",
        help=(
            "Ticker selector algorithm. "
            "'score-rank' (default): composite score from 60-day rolling backtest. "
            "'win-rate': rank by historical EOD win rate; LONG=top-N, SHORT=bottom-N. "
            "Pair with --enable-regime-engine for direction-aware win-rate selection."
        ),
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
        "--ma-momentum-gate",
        action="store_true",
        default=False,
        dest="ma_momentum_gate",
        help=(
            "Suppress signals where the OR range does not overlap both MA20 and MA50 "
            "in the signal direction (BULLISH: or_high >= MA20 and MA50; "
            "BEARISH: or_low <= MA20 and MA50). Default: off."
        ),
    )
    parser.add_argument(
        "--normalize-or-by-adr",
        action="store_true",
        default=False,
        dest="normalize_or_by_adr",
        help=(
            "Normalize each ticker's OR range pct by its prior 20-day ADR before "
            "scoring. Levels the playing field between high/low volatility tickers. "
            "Default: off."
        ),
    )
    parser.add_argument(
        "--score-entry-weight",
        type=float,
        default=0.50,
        dest="score_entry_weight",
        help="Scoring weight for entry_vs_mid_pct (default: 0.50).",
    )
    parser.add_argument(
        "--score-avg-win-weight",
        type=float,
        default=0.30,
        dest="score_avg_win_weight",
        help="Scoring weight for historical avg_win_pct (default: 0.30).",
    )
    parser.add_argument(
        "--score-win-rate-weight",
        type=float,
        default=0.0,
        dest="score_win_rate_weight",
        help="Scoring weight for rolling win_rate (default: 0.0).",
    )
    parser.add_argument(
        "--score-rel-strength-weight",
        type=float,
        default=0.0,
        dest="score_rel_strength_weight",
        help=(
            "Scoring weight for cross-sectional relative MA50 strength vs pool mean. "
            "Direction-aware: rewards BULLISH outperformers and BEARISH underperformers. "
            "Default: 0.0."
        ),
    )
    parser.add_argument(
        "--min-pool-vote",
        type=int,
        default=0,
        dest="min_pool_vote_to_trade",
        help=(
            "Skip day if fewer than N tickers in the pool have positive rolling EV. "
            "Default: 0 (off)."
        ),
    )
    parser.add_argument(
        "--score-ev-trend-weight",
        type=float,
        default=0.0,
        dest="score_ev_trend_weight",
        help="Scoring weight for ev_trend (recent EV minus full-window EV). Default: 0.0 (off).",
    )
    parser.add_argument(
        "--ev-trend-days",
        type=int,
        default=15,
        dest="ev_trend_days",
        help="Calendar days for the recent EV window used in ev_trend computation. Default: 15.",
    )
    parser.add_argument(
        "--qqq-or-weight",
        type=float,
        default=0.0,
        dest="qqq_or_weight",
        help=(
            "Score bonus/penalty based on QQQ opening-range direction: "
            "BULLISH signals are boosted when QQQ OR is positive, penalised when negative (and vice-versa). "
            "Default: 0.0 (off)."
        ),
    )
    parser.add_argument(
        "--dynamic-ev-gate",
        action="store_true",
        default=False,
        dest="dynamic_ev_gate",
        help=(
            "Apply regime-adaptive EV filter based on daily pool vote (default: off). "
            "Mode 'percentile' (default): exclude bottom N%% of pool by EV. "
            "Mode 'threshold': fixed WR/W-L floors per regime tier. "
            "Pass this to match the backtest, which defaults it ON."
        ),
    )
    parser.add_argument(
        "--dg-mode",
        type=str,
        default="percentile",
        choices=["percentile", "threshold"],
        dest="dg_mode",
        help="Gate mode for --dynamic-ev-gate. Default: percentile.",
    )
    parser.add_argument("--dg-bull-threshold", type=int, default=10, dest="dg_bull_threshold",
                        help="Pool vote at/above which bull-regime thresholds apply. Default: 10.")
    parser.add_argument("--dg-bear-threshold", type=int, default=5, dest="dg_bear_threshold",
                        help="Pool vote at/below which bear-regime thresholds apply. Default: 5.")
    parser.add_argument("--dg-bull-exclude-pct", type=float, default=0.10, dest="dg_bull_exclude_pct",
                        help="[percentile] Bottom fraction of pool excluded in bull regime. Default: 0.10.")
    parser.add_argument("--dg-neutral-exclude-pct", type=float, default=0.25, dest="dg_neutral_exclude_pct",
                        help="[percentile] Bottom fraction excluded in neutral regime. Default: 0.25.")
    parser.add_argument("--dg-bear-exclude-pct", type=float, default=0.40, dest="dg_bear_exclude_pct",
                        help="[percentile] Bottom fraction excluded in bear regime. Default: 0.40.")
    parser.add_argument("--dg-bull-min-wr", type=float, default=0.30, dest="dg_bull_min_wr",
                        help="[threshold] Minimum win rate in bull regime. Default: 0.30.")
    parser.add_argument("--dg-neutral-min-wr", type=float, default=0.33, dest="dg_neutral_min_wr",
                        help="[threshold] Minimum win rate in neutral regime. Default: 0.33.")
    parser.add_argument("--dg-bear-min-wr", type=float, default=0.38, dest="dg_bear_min_wr",
                        help="[threshold] Minimum win rate in bear regime. Default: 0.38.")
    parser.add_argument("--dg-bull-min-wl", type=float, default=1.3, dest="dg_bull_min_wl",
                        help="[threshold] Minimum W/L ratio in bull regime. Default: 1.3.")
    parser.add_argument("--dg-neutral-min-wl", type=float, default=1.5, dest="dg_neutral_min_wl",
                        help="[threshold] Minimum W/L ratio in neutral regime. Default: 1.5.")
    parser.add_argument("--dg-bear-min-wl", type=float, default=1.8, dest="dg_bear_min_wl",
                        help="[threshold] Minimum W/L ratio in bear regime. Default: 1.8.")
    parser.add_argument(
        "--adaptive-lookback",
        action="store_true",
        default=False,
        dest="adaptive_lookback",
        help=(
            "Shorten the rolling lookback in bull regimes and lengthen it in bear regimes, "
            "using the same pool-vote signal as --dynamic-ev-gate (default: off). "
            "Pass this to match the backtest, which defaults it ON."
        ),
    )
    parser.add_argument("--al-bull-threshold", type=int, default=10, dest="al_bull_threshold",
                        help="Pool vote for bull regime in adaptive lookback. Default: 10.")
    parser.add_argument("--al-bear-threshold", type=int, default=5, dest="al_bear_threshold",
                        help="Pool vote for bear regime in adaptive lookback. Default: 5.")
    parser.add_argument("--al-bull-days", type=int, default=20, dest="al_bull_days",
                        help="Lookback days in bull regime. Default: 20.")
    parser.add_argument("--al-neutral-days", type=int, default=60, dest="al_neutral_days",
                        help="Lookback days in neutral regime. Default: 60.")
    parser.add_argument("--al-bear-days", type=int, default=90, dest="al_bear_days",
                        help="Lookback days in bear regime. Default: 90.")
    parser.add_argument(
        "--direction-split-ev",
        action="store_true",
        default=False,
        dest="direction_split_ev_gate",
        help=(
            "Gate on direction-specific EV: a BULLISH signal requires ev_trade_bullish "
            ">= floor; a BEARISH signal requires ev_trade_bearish >= floor (regime floors "
            "via --ds-*-min-ev). Default: off. Pass this to match the backtest, which "
            "defaults it ON. Regime tiers reuse --dg-bull-threshold / --dg-bear-threshold."
        ),
    )
    parser.add_argument("--ds-bull-min-ev", type=float, default=0.0, dest="ds_bull_min_ev",
                        help="Min directional EV in bull regime. Default: 0.0.")
    parser.add_argument("--ds-neutral-min-ev", type=float, default=0.0, dest="ds_neutral_min_ev",
                        help="Min directional EV in neutral regime. Default: 0.0.")
    parser.add_argument("--ds-bear-min-ev", type=float, default=0.0, dest="ds_bear_min_ev",
                        help="Min directional EV in bear regime. Default: 0.0.")
    parser.add_argument(
        "--min-score",
        type=float,
        default=0.0,
        dest="min_score",
        help=(
            "Skip a pick if its composite score (after QQQ-OR adjustment) is below this "
            "floor. Matches the backtest, which drops score < min_score by default. "
            "Default: 0.0 (drops negative-score, low-conviction picks). Set very negative "
            "to disable."
        ),
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
        choices=["alpaca", "tradestation", "local_ts_broadcast"],
        default=None,
        dest="market_data_source",
        help=(
            "Market data source for live bar streaming and warmup (default: alpaca). "
            "'tradestation' — direct TS HTTP stream, requires valid TS session tokens. "
            "'local_ts_broadcast' — receive bars from a running bar_broadcaster daemon "
            "over a Unix domain socket; requires bar_broadcaster.py to be started first. "
            "Can also be set via 'market_data_source' in config.json."
        ),
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
    parser.add_argument(
        "--no-reentry-after-next-window-returned",
        action="store_false",
        default=True,
        dest="reentry_after_next_window_returned",
        help=(
            "Disable BRU/REV re-entries from window N after window N+1 has fully returned "
            "its capital. Default (on): re-entries are allowed once window N+1 has no open "
            "positions, using the current available budget. Pass this flag to match strict "
            "backtest behavior (permanently block once window N+1 has ever opened)."
        ),
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


def _build_sip_quote_client(args):
    """Return a TradeStation SIP client for parallel quote comparison when feed=IEX, or None.

    Skips if the TS session file is missing or expired — the Alpaca client
    will use its own IEX quote in that case.
    """
    if getattr(args, "feed", None) != "iex":
        return None
    from alpha_tech_tracker.op_momentum_strategy.config import (
        _TRADESTATION_SESSION_TOKENS,
        TRADESTATION_ENVIRONMENT,
    )
    if not _TRADESTATION_SESSION_TOKENS.get("access_token"):
        logger.debug("IEX feed: no TS session tokens found, skipping quote fallback")
        return None
    try:
        from alpha_tech_tracker.trade_api.tradestation.client import TradeStationAPIClient
        ts_client = TradeStationAPIClient(environment=TRADESTATION_ENVIRONMENT)
        ts_client.restore_session(_TRADESTATION_SESSION_TOKENS)
        if not ts_client.verify_session():
            logger.warning("IEX feed: TS session expired — SIP quote client disabled, run tradestation_auth.py to enable")
            return None
        logger.info("IEX feed: TradeStation SIP quote client enabled")
        return ts_client
    except Exception:
        logger.warning("IEX feed: failed to init TS SIP quote client — proceeding without it", exc_info=True)
        return None


def _build_market_data_client(args):
    """Return a MarketDataClient based on --market-data-source, or None for default Alpaca.

    Resolution order: CLI flag → config.json 'market_data_source' → 'alpaca'.
    """
    from alpha_tech_tracker.op_momentum_strategy.config import (
        _load_config,
        MARKET_DATA_SOURCE,
        TS_BROADCAST_SOCKET_PATH,
        _TRADESTATION_SESSION_TOKENS,
        TRADESTATION_ENVIRONMENT,
    )
    _load_config()
    source = getattr(args, "market_data_source", None) or MARKET_DATA_SOURCE

    if source == "tradestation":
        from alpha_tech_tracker.trade_api.tradestation.client import TradeStationAPIClient
        from alpha_tech_tracker.trade_api.tradestation.market_data_client import (
            TradeStationMarketDataClient,
        )
        ts_client = TradeStationAPIClient(environment=TRADESTATION_ENVIRONMENT)
        ts_client.restore_session(_TRADESTATION_SESSION_TOKENS)
        if not ts_client.verify_session():
            raise RuntimeError(
                "TradeStation session invalid — run tradestation_auth.py first"
            )
        logger.info("Market data source: TradeStation (env=%s)", TRADESTATION_ENVIRONMENT)
        return TradeStationMarketDataClient(ts_client)

    if source == "local_ts_broadcast":
        from alpha_tech_tracker.trade_api.tradestation.client import TradeStationAPIClient
        from alpha_tech_tracker.trade_api.local_ts_broadcast.market_data_client import (
            LocalTSBroadcastMarketDataClient,
        )
        ts_client = TradeStationAPIClient(environment=TRADESTATION_ENVIRONMENT)
        ts_client.restore_session(_TRADESTATION_SESSION_TOKENS)
        logger.info("Market data source: local_ts_broadcast (socket=%s)", TS_BROADCAST_SOCKET_PATH)
        return LocalTSBroadcastMarketDataClient(ts_client, socket_path=TS_BROADCAST_SOCKET_PATH)

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


def _warn_replay_feed_mismatch(args):
    """Warn when --live-data-feed is set but --market-data-source isn't.

    --live-data-feed only swaps the *intraday* OR bars (read from recorded CSVs).
    Signal-engine warmup (90-day MA history) and ticker-selector scoring (60-day
    rolling stats) still come from Alpaca SIP unless --market-data-source is also
    set. Mixing TS intraday with Alpaca warmup/scoring routinely produces
    different picks than the live engine that recorded the CSVs.
    """
    if not args.live_data_dir or not args.live_data_feed:
        return
    if args.live_data_feed != "tradestation":
        return
    if getattr(args, "market_data_source", None) == "tradestation":
        return
    logger.warning(
        "Replay flag mismatch: --live-data-feed tradestation feeds OR bars from "
        "TS recordings, but --market-data-source is not set so signal-engine "
        "warmup and selector scoring fall back to Alpaca SIP. Picks may diverge "
        "from the live TS engine. Add --market-data-source tradestation to match."
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
        sip_quote_client = None if mock_trade_execution else _build_sip_quote_client(args)
        client = build_execution_client(is_paper=is_paper, broker=effective_broker, sip_quote_client=sip_quote_client)
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
            reentry_after_next_window_returned=args.reentry_after_next_window_returned,
            trailing_ma_switch=args.trailing_ma_switch,
            trailing_ma_switch_factor=args.trailing_ma_switch_factor,
            trailing_ma_switch_period=args.trailing_ma_switch_period,
            ma_momentum_gate=args.ma_momentum_gate,
            score_entry_weight=args.score_entry_weight,
            score_avg_win_weight=args.score_avg_win_weight,
            score_win_rate_weight=args.score_win_rate_weight,
            score_rel_strength_weight=args.score_rel_strength_weight,
            score_ev_trend_weight=args.score_ev_trend_weight,
            normalize_or_by_adr=args.normalize_or_by_adr,
            min_pool_vote_to_trade=args.min_pool_vote_to_trade,
            ev_trend_days=args.ev_trend_days,
            qqq_or_weight=args.qqq_or_weight,
            dynamic_ev_gate=args.dynamic_ev_gate,
            dg_mode=args.dg_mode,
            dg_bull_threshold=args.dg_bull_threshold,
            dg_bear_threshold=args.dg_bear_threshold,
            dg_bull_exclude_pct=args.dg_bull_exclude_pct,
            dg_neutral_exclude_pct=args.dg_neutral_exclude_pct,
            dg_bear_exclude_pct=args.dg_bear_exclude_pct,
            dg_bull_min_wr=args.dg_bull_min_wr,
            dg_neutral_min_wr=args.dg_neutral_min_wr,
            dg_bear_min_wr=args.dg_bear_min_wr,
            dg_bull_min_wl=args.dg_bull_min_wl,
            dg_neutral_min_wl=args.dg_neutral_min_wl,
            dg_bear_min_wl=args.dg_bear_min_wl,
            adaptive_lookback=args.adaptive_lookback,
            al_bull_threshold=args.al_bull_threshold,
            al_bear_threshold=args.al_bear_threshold,
            al_bull_days=args.al_bull_days,
            al_neutral_days=args.al_neutral_days,
            al_bear_days=args.al_bear_days,
            direction_split_ev_gate=args.direction_split_ev_gate,
            ds_bull_min_ev=args.ds_bull_min_ev,
            ds_neutral_min_ev=args.ds_neutral_min_ev,
            ds_bear_min_ev=args.ds_bear_min_ev,
            min_score=args.min_score,
            enable_regime_engine=args.enable_regime_engine,
            regime_hold=args.regime_hold,
            disable_ma_stops_for_regime_hold=args.disable_ma_stops_for_regime_hold,
            selector_type=args.selector,
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
        sip_quote_client = _build_sip_quote_client(args)
        client = build_execution_client(is_paper=is_paper, broker=args.execution_broker, sip_quote_client=sip_quote_client)
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
            reentry_after_next_window_returned=args.reentry_after_next_window_returned,
            trailing_ma_switch=args.trailing_ma_switch,
            trailing_ma_switch_factor=args.trailing_ma_switch_factor,
            trailing_ma_switch_period=args.trailing_ma_switch_period,
            ma_momentum_gate=args.ma_momentum_gate,
            score_entry_weight=args.score_entry_weight,
            score_avg_win_weight=args.score_avg_win_weight,
            score_win_rate_weight=args.score_win_rate_weight,
            score_rel_strength_weight=args.score_rel_strength_weight,
            score_ev_trend_weight=args.score_ev_trend_weight,
            normalize_or_by_adr=args.normalize_or_by_adr,
            min_pool_vote_to_trade=args.min_pool_vote_to_trade,
            ev_trend_days=args.ev_trend_days,
            qqq_or_weight=args.qqq_or_weight,
            dynamic_ev_gate=args.dynamic_ev_gate,
            dg_mode=args.dg_mode,
            dg_bull_threshold=args.dg_bull_threshold,
            dg_bear_threshold=args.dg_bear_threshold,
            dg_bull_exclude_pct=args.dg_bull_exclude_pct,
            dg_neutral_exclude_pct=args.dg_neutral_exclude_pct,
            dg_bear_exclude_pct=args.dg_bear_exclude_pct,
            dg_bull_min_wr=args.dg_bull_min_wr,
            dg_neutral_min_wr=args.dg_neutral_min_wr,
            dg_bear_min_wr=args.dg_bear_min_wr,
            dg_bull_min_wl=args.dg_bull_min_wl,
            dg_neutral_min_wl=args.dg_neutral_min_wl,
            dg_bear_min_wl=args.dg_bear_min_wl,
            adaptive_lookback=args.adaptive_lookback,
            al_bull_threshold=args.al_bull_threshold,
            al_bear_threshold=args.al_bear_threshold,
            al_bull_days=args.al_bull_days,
            al_neutral_days=args.al_neutral_days,
            al_bear_days=args.al_bear_days,
            direction_split_ev_gate=args.direction_split_ev_gate,
            ds_bull_min_ev=args.ds_bull_min_ev,
            ds_neutral_min_ev=args.ds_neutral_min_ev,
            ds_bear_min_ev=args.ds_bear_min_ev,
            min_score=args.min_score,
            enable_regime_engine=args.enable_regime_engine,
            regime_hold=args.regime_hold,
            disable_ma_stops_for_regime_hold=args.disable_ma_stops_for_regime_hold,
            selector_type=args.selector,
        )
        engine.run(tickers_override=args.tickers)
    finally:
        _remove_pid(args.pid_file)

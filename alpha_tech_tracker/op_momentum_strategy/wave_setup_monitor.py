"""Wave setup monitor: live buy/sell alerts for each ticker's top wave_risk_reward setups.

Alerts only, no orders. For every ticker in the config the monitor watches the setups listed
for it (normally the top 3 from a setup report), and sends Telegram/SMS alerts (config._notify)
plus a CSV log:

  BUY / SHORT  when a setup fires on a closed 5-min bar: entry (the bar's close), stop, target
               and how the trade exits. Place the stop as an order; the monitor only checks
               stops on closed 5-min bars.
  SELL / COVER when the stop, the target or the give-back trail is hit, using the backtest's
               exit rules (wave_risk_reward_backtest.TradeSimulator) per setup: box and bounce
               = target, drive = held to the close, pullback = target then trail.
  15:50        SELL/COVER at the close (MOC) for every open intraday trade, and BUY at the close
               (MOC) for the overnight hold when its filter passes. The night into an earnings
               release is skipped. Sent once every ticker's 15:45 bar is in (about 15:50, 15:51
               at the latest), so the decision uses the 15:45 bar's close. That meets the Nasdaq
               MOC cutoff (15:55) but not NYSE's (15:50): `--close-decision-bar 15:40` decides on
               the 15:40 bar and alerts about 15:45 instead.
  09:25        SELL at the open (MOO, before the 09:28 cutoff) for overnight holds.

Signals come from `wave_risk_reward.analyze_bars` with each setup's options (wave_risk_reward_scan
SETUP_RUNS), re-run on a window of the last WARMUP_SESSIONS sessions whose start is fixed for the
day, so a signal does not move as the day goes on. Entries from the close decision bar on are
not alerted (no time left before the close alert).

Market data uses the trade engine's switch (`--market-data-source alpaca|tradestation|
local_ts_broadcast`): history warms up from 5-min bars, then streamed 1-min bars are combined
into 5-min bars (emitted when the period's fifth minute arrives, or FLUSH_GRACE_SECONDS after
the period ends). The first period after a (re)start is refetched whole.

State (alerted signals, open trades, overnight holds) is kept in a JSON file so a restart does
not repeat alerts and the next morning knows what to sell. The process runs one session and
exits at SESSION_END; schedule `start` each trading morning (e.g. 09:00 ET).

  # 1. Config: each ticker's top 3 setups from a setup report
  python -m alpha_tech_tracker.op_momentum_strategy.wave_setup_monitor config \\
    --report alpha_tech_tracker/op_momentum_strategy/backtest_result/wave_setups/2026-07-06_2026-10-05 \\
    --tickers AMD META GOOGL AMAT SHOP SPOT

  # 2. Run in the foreground, or as a daemon (start / status / stop / restart)
  python -m alpha_tech_tracker.op_momentum_strategy.wave_setup_monitor run
  python -m alpha_tech_tracker.op_momentum_strategy.wave_setup_monitor start --market-data-source tradestation
"""

import argparse
import csv
import json
import logging
import logging.handlers
import os
import signal as signal_module
import sys
import threading
import time as time_module
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
import pytz
from alpaca.data.enums import DataFeed

from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.earnings_calendar import (
    earnings_windows,
    in_earnings_window,
    load_releases,
)
from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.wave_risk_reward import (
    LONG_SIGNALS,
    add_moving_averages,
    analyze_bars,
    overnight_filter_ok,
    overnight_needs_history,
    params_from_args,
    regular_hours,
)
from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.wave_risk_reward_backtest import (
    DEFAULT_GIVEBACK,
    DEFAULT_GIVEBACK_ARM_R,
    parse_args as parse_backtest_args,
    signal_group,
)
from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.wave_risk_reward_scan import BOX_GROUPS, SETUP_RUNS
from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.wave_risk_reward_setup_report import (
    REPORT_EXITS,
    top_setups_by_ticker,
)
from alpha_tech_tracker.op_momentum_strategy.cli.clients import _build_market_data_client
from alpha_tech_tracker.op_momentum_strategy.cli.daemon import (
    _LOG_DIR,
    _daemon_stop,
    _daemonize,
    _is_running,
    _read_pid,
    _remove_pid,
    _write_pid,
)
from alpha_tech_tracker.op_momentum_strategy.config import _load_config, _notify, disable_notifications
from alpha_tech_tracker.op_momentum_strategy.contract_selector import _is_nyse_holiday, _prior_trading_day
from alpha_tech_tracker.op_momentum_strategy.op_momentum_backtest import fetch_daily_bars

logger = logging.getLogger(__name__)

ET = pytz.timezone("America/New_York")
DEFAULT_CONFIG = Path(_LOG_DIR) / "wave_setup_monitor_config.json"
DEFAULT_STATE = Path(_LOG_DIR) / "wave_setup_monitor_state.json"
PID_FILE = os.path.join(_LOG_DIR, "wave_setup_monitor.pid")
WARMUP_SESSIONS = 10
WARMUP_CALENDAR_DAYS = 20
DAILY_HISTORY_DAYS = 420
MARKET_OPEN = time(9, 30)
PRE_OPEN_ALERT = time(9, 25)
DEFAULT_CLOSE_DECISION_BAR = time(15, 45)
LAST_BAR = time(15, 55)
SESSION_END = time(16, 5)
FLUSH_GRACE_SECONDS = 20
STREAM_TIMEOUT_SECONDS = 120
DELAYED_DATA_MINUTES = 16  # Alpaca plans without real-time SIP only serve SIP history older than 15 min
BAR_MINUTES = 5
EXIT_TEXT = {
    "target": "exit at the target or the stop",
    "target-trail": "stop until the target, then trail (32% give-back)",
    "giveback": "stop, then trail once up 0.25R (32% give-back)",
    "eod": "hold to the close (stop only)",
}


def _now_et():
    return datetime.now(ET)


# ---------------------------------------------------------------------------
# Setups and config
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SetupSpec:
    name: str
    exit_mode: str
    params: object
    groups: Optional[frozenset]

    @property
    def overnight(self):
        return self.exit_mode == "next open"


def build_setup_spec(name):
    """The analyze_bars options, signal groups and fixed exit for a setup-report setup name."""
    if name not in REPORT_EXITS:
        raise ValueError(f"unknown setup {name!r}; choose from {', '.join(REPORT_EXITS)}")
    box_labels = set(BOX_GROUPS.values())
    run = "box signals" if name in box_labels else name
    groups = frozenset(g for g, label in BOX_GROUPS.items() if label == name) if name in box_labels else None
    params = params_from_args(parse_backtest_args(["--start", "2000-01-01"] + SETUP_RUNS[run]))
    return SetupSpec(name, REPORT_EXITS[name], params, groups)


def generate_config(report_dir, tickers, top_n=3):
    """Monitor config from a setup report folder: each ticker's top setups by fixed-exit total."""
    report_dir = Path(report_dir)
    with (report_dir / "trades.csv").open() as handle:
        ranked = top_setups_by_ticker(csv.DictReader(handle), top_n)
    missing = [t for t in tickers if t not in ranked]
    if missing:
        raise ValueError(f"{', '.join(missing)} not in {report_dir}; run the setup report for them first")
    empty = [t for t in tickers if not ranked[t]]
    if empty:
        logger.warning("No setup made money for %s in %s; they are left out", ", ".join(empty), report_dir)
    return {
        "generated": date.today().isoformat(),
        "source": str(report_dir),
        "top_n": top_n,
        "tickers": {t: [{"setup": s, "report_total_pct": round(total, 2)} for s, total in ranked[t]]
                    for t in tickers if ranked[t]},
    }


def load_config(path):
    """{ticker: [SetupSpec]} from a monitor config file."""
    config = json.loads(Path(path).read_text())
    return {ticker: [build_setup_spec(entry["setup"] if isinstance(entry, dict) else entry) for entry in setups]
            for ticker, setups in config["tickers"].items()}


# ---------------------------------------------------------------------------
# 1-min -> 5-min bars
# ---------------------------------------------------------------------------

def period_start(timestamp):
    return timestamp.replace(second=0, microsecond=0) - timedelta(minutes=timestamp.minute % BAR_MINUTES)


class FiveMinAggregator:
    """Combines 1-min bars into 5-min bars and hands each finished one to `on_bar(ticker, bar)`.

    A period is finished when its fifth minute arrives, when a later minute arrives, or
    FLUSH_GRACE_SECONDS after it ends (flush_due). `bar` is a dict: time (period start), open,
    high, low, close, minutes (1-min bars it was built from).
    """

    def __init__(self, on_bar):
        self._on_bar = on_bar
        self._buffers = {}

    def add(self, ticker, timestamp, open_, high, low, close):
        start = period_start(timestamp)
        buffer = self._buffers.get(ticker)
        if buffer and buffer["time"] != start:
            if start < buffer["time"]:
                return
            self._emit(ticker)
            buffer = None
        if buffer is None:
            buffer = self._buffers[ticker] = {"time": start, "open": open_, "high": high, "low": low,
                                              "close": close, "minutes": 0}
        buffer["high"] = max(buffer["high"], high)
        buffer["low"] = min(buffer["low"], low)
        buffer["close"] = close
        buffer["minutes"] += 1
        if timestamp.minute % BAR_MINUTES == BAR_MINUTES - 1:
            self._emit(ticker)

    def flush_due(self, now):
        for ticker in [t for t, b in self._buffers.items()
                       if b["time"] + timedelta(minutes=BAR_MINUTES, seconds=FLUSH_GRACE_SECONDS) <= now]:
            self._emit(ticker)

    def _emit(self, ticker):
        bar = self._buffers.pop(ticker, None)
        if bar:
            self._on_bar(ticker, bar)


# ---------------------------------------------------------------------------
# Live trades: the backtest's exit rules, one bar at a time
# ---------------------------------------------------------------------------

class LiveTrade:
    """One alerted trade, exited by the rules of wave_risk_reward_backtest.TradeSimulator.run."""

    FIELDS = ("ticker", "setup", "signal", "exit_mode", "entry_time", "side", "entry", "stop", "target", "risk",
              "peak", "target_reached", "status", "last_bar", "exit_time", "exit_price", "outcome")

    def __init__(self, **fields):
        for name in self.FIELDS:
            setattr(self, name, fields.get(name))
        self.peak = self.entry if self.peak is None else self.peak
        self.target_reached = bool(self.target_reached)
        self.status = self.status or "open"

    @property
    def overnight(self):
        return self.exit_mode == "next open"

    def on_bar(self, bar, giveback=DEFAULT_GIVEBACK, arm_r=DEFAULT_GIVEBACK_ARM_R):
        """Apply one closed 5-min bar; returns the outcome when the trade exits on it, else None."""
        self.last_bar = bar["time"]
        if self.status != "open":
            return None
        side, entry, stop, target = self.side, self.entry, self.stop, self.target
        if (bar["low"] <= stop) if side == 1 else (bar["high"] >= stop):
            fill = min(bar["open"], stop) if side == 1 else max(bar["open"], stop)
            return self._close(bar["time"], fill, "stop")
        hit_target = (bar["high"] >= target) if side == 1 else (bar["low"] <= target)
        if self.exit_mode == "target" and hit_target:
            return self._close(bar["time"], target, "target")
        self.target_reached = bool(self.target_reached or hit_target)
        self.peak = max(self.peak, bar["close"]) if side == 1 else min(self.peak, bar["close"])
        if self.exit_mode == "giveback" or (self.exit_mode == "target-trail" and self.target_reached):
            move = (self.peak - entry) * side
            if move >= arm_r * self.risk and (self.peak - bar["close"]) * side >= giveback * move:
                return self._close(bar["time"], bar["close"], "giveback")
        return None

    def close_at(self, when, price, outcome):
        return self._close(when, price, outcome)

    def _close(self, when, price, outcome):
        self.status, self.exit_time, self.exit_price, self.outcome = "closed", when, float(price), outcome
        return outcome

    def pnl_pct(self, price=None):
        price = self.exit_price if price is None else price
        return self.side * (price - self.entry) / self.entry * 100

    def to_dict(self):
        out = {}
        for name in self.FIELDS:
            value = getattr(self, name)
            if isinstance(value, datetime):
                value = value.isoformat()
            elif hasattr(value, "item"):
                value = value.item()
            out[name] = value
        return out

    @classmethod
    def from_dict(cls, data):
        fields = dict(data)
        for name in ("entry_time", "last_bar", "exit_time"):
            if fields.get(name):
                fields[name] = pd.Timestamp(fields[name]).tz_convert(ET)
        return cls(**fields)


# ---------------------------------------------------------------------------
# Signal evaluation (runs in worker processes)
# ---------------------------------------------------------------------------

def evaluate_setup(job):
    """Signals of one setup that fired on `bar_time`, from analyze_bars over the day's window."""
    ticker, spec, frame, windows, bar_time = job
    result = analyze_bars(frame, spec.params, windows)
    fired = []
    for sig in result["signals"]:
        if sig["time"] != bar_time or not sig["risk_reward"]:
            continue
        if spec.groups is not None and signal_group(sig) not in spec.groups:
            continue
        rr = sig["risk_reward"]
        fired.append({"ticker": ticker, "setup": spec.name, "signal": sig["signal"], "time": sig["time"],
                      "price": float(sig["price"]), "stop": rr["stop"], "target": rr["target"], "risk": rr["risk"],
                      "rr": rr.get("rr")})
    return fired


class InlineExecutor:
    """Runs jobs in the calling thread (tests, or --workers 0)."""

    def submit(self, fn, *args):
        from concurrent.futures import Future

        future = Future()
        try:
            future.set_result(fn(*args))
        except Exception as error:  # surfaced through the future like a pool would
            future.set_exception(error)
        return future

    def shutdown(self, wait=True):
        pass


# ---------------------------------------------------------------------------
# The monitor
# ---------------------------------------------------------------------------

class WaveSetupMonitor:
    def __init__(self, setups_by_ticker, market_data_client, state_file=DEFAULT_STATE, alerts_dir=_LOG_DIR,
                 executor=None, notify=_notify, now=_now_et, releases_loader=load_releases,
                 daily_closes_loader=None, close_decision_bar=DEFAULT_CLOSE_DECISION_BAR):
        self.setups = setups_by_ticker
        self.tickers = list(setups_by_ticker)
        self.client = market_data_client
        self.state_file = Path(state_file)
        self.alerts_dir = Path(alerts_dir)
        self.executor = executor or InlineExecutor()
        self.notify = notify
        self.now = now
        self.releases_loader = releases_loader
        self.daily_closes_loader = daily_closes_loader or _load_daily_closes
        self.close_decision_bar = close_decision_bar
        decision_end = datetime.combine(date.today(), close_decision_bar) + timedelta(minutes=BAR_MINUTES)
        self.close_alert_at = decision_end.time()
        self.close_alert_latest = (decision_end + timedelta(minutes=1)).time()
        self.lock = threading.RLock()
        self.aggregator = FiveMinAggregator(self._on_five_min_bar)
        self.bars = {}
        self.window_start = {}
        self.windows = {}
        self.daily_closes = {}
        self.trades = []
        self.alerted = set()
        self.session = None
        self.done = {"pre_open": False, "close": False}
        self.stream_started_at = None
        self.last_minute_at = None
        self.refetch_before = None
        self.pending = []
        self.backfill = None

    # --- lifecycle -------------------------------------------------------

    def prepare(self):
        """Warm up history, earnings windows and daily closes, restore state, catch up open trades."""
        now = self.now()
        self.session = now.date()
        history = self._warmup(now)
        for ticker in self.tickers:
            frame = history.get(ticker)
            bars = regular_hours(frame) if frame is not None and not frame.empty else _empty_bars()
            bars = bars[bars.index + timedelta(minutes=BAR_MINUTES) <= now]
            self.bars[ticker] = bars
            prior = sorted(d for d in set(bars.index.date) if d < self.session)
            first = prior[-WARMUP_SESSIONS] if len(prior) >= WARMUP_SESSIONS else (prior[0] if prior else self.session)
            self.window_start[ticker] = ET.localize(datetime.combine(first, time(0, 0)))
            sessions = prior + [self.session]
            self.windows[ticker] = earnings_windows(self.releases_loader(ticker), sessions)
        needs_daily = sorted({t for t, specs in self.setups.items()
                              for s in specs if s.overnight and overnight_needs_history(s.params.overnight_hold)})
        if needs_daily:
            self.daily_closes = self.daily_closes_loader(needs_daily, self.session)
        self._load_state()
        self._catch_up_trades()
        self.refetch_before = period_start(now) + timedelta(minutes=BAR_MINUTES)
        self._save_state()

    def _warmup(self, now):
        """History up to now; before the open, up to the previous session's close (no recent data needed).

        If the feed refuses recent data (delayed SIP plans), warm up to DELAYED_DATA_MINUTES ago and
        backfill the gap once it can be queried (tick).
        """
        if now.time() < MARKET_OPEN:
            end = ET.localize(datetime.combine(_prior_trading_day(now.date()), time(16, 0)))
        else:
            end = now
        start = end - timedelta(days=WARMUP_CALENDAR_DAYS)
        try:
            return self.client.warmup(self.tickers, start, end)
        except Exception as error:
            if "recent" not in str(error).lower():
                raise
            delayed_end = now - timedelta(minutes=DELAYED_DATA_MINUTES)
            logger.warning("Feed refuses recent data (%s); warming up to %s and backfilling the rest later",
                           error, f"{delayed_end:%H:%M}")
            self.backfill = (delayed_end, now)
            return self.client.warmup(self.tickers, start, delayed_end)

    def _run_backfill(self, now):
        """Insert the bars skipped at a delayed-feed start; they update history only (no alerts)."""
        gap_start, gap_end = self.backfill
        if now < gap_end + timedelta(minutes=DELAYED_DATA_MINUTES):
            return
        self.backfill = None
        try:
            fetched = self.client.fetch_bars(self.tickers, gap_start, gap_end)
        except Exception:
            logger.warning("Backfill of %s-%s failed", f"{gap_start:%H:%M}", f"{gap_end:%H:%M}", exc_info=True)
            return
        for ticker in self.tickers:
            frame = fetched.get(ticker)
            if frame is None or frame.empty:
                continue
            missing = regular_hours(frame)
            missing = missing[~missing.index.isin(self.bars[ticker].index)]
            if not missing.empty:
                self.bars[ticker] = pd.concat([self.bars[ticker], missing]).sort_index()
                logger.info("%s: backfilled %d bars from %s", ticker, len(missing), f"{gap_start:%H:%M}")
        self._save_state()

    def start_stream(self):
        self.client.subscribe_bars(self.on_minute_bar, *self.tickers)
        self.client.start()
        self.stream_started_at = self.now()

    def tick(self):
        """Periodic work: flush late 5-min bars, scheduled alerts, stream watchdog."""
        now = self.now()
        with self.lock:
            self.aggregator.flush_due(now)
            if self.backfill is not None:
                self._run_backfill(now)
            if not self.done["pre_open"] and now.time() >= PRE_OPEN_ALERT:
                self.done["pre_open"] = True
                self._pre_open_alerts()
            if not self.done["close"] and now.time() >= self.close_alert_at and (
                    now.time() >= self.close_alert_latest or self._all_have_bar(self.close_decision_bar)):
                self.done["close"] = True
                self._close_alerts()
        self._watchdog(now)

    def finish(self):
        """End of session: close anything still open at the last close, summarize, save."""
        with self.lock:
            for trade in self.trades:
                if trade.overnight and trade.status == "pending":
                    last = self._last_close(trade.ticker)
                    if last is not None:
                        trade.entry, trade.peak, trade.status = last, last, "open"
                elif not trade.overnight and trade.status in ("open", "closing"):
                    last = self._last_close(trade.ticker)
                    if last is not None:
                        trade.close_at(self.bars[trade.ticker].index[-1], last, "close")
            self._session_summary()
            self._save_state()

    def run(self, poll_seconds=1.0):
        today = self.now().date()
        if today.weekday() >= 5 or _is_nyse_holiday(today):
            logger.info("Market closed today (%s); nothing to monitor", today)
            return
        self.prepare()
        self.start_stream()
        logger.info("Monitoring %s", ", ".join(f"{t}: {[s.name for s in self.setups[t]]}" for t in self.tickers))
        try:
            while self.now().time() < SESSION_END:
                self.tick()
                time_module.sleep(poll_seconds)
        finally:
            self.finish()
            self.client.stop()
            self.executor.shutdown(wait=False)

    # --- bars ------------------------------------------------------------

    def on_minute_bar(self, bar):
        ticker = bar.symbol
        if ticker not in self.setups:
            return
        timestamp = bar.timestamp.astimezone(ET)
        if timestamp.date() != self.session or not (MARKET_OPEN <= timestamp.time() < time(16, 0)):
            return
        with self.lock:
            self.last_minute_at = self.now()
            self.aggregator.add(ticker, timestamp, float(bar.open), float(bar.high), float(bar.low), float(bar.close))

    def _on_five_min_bar(self, ticker, bar):
        with self.lock:
            self._handle_five_min_bar(ticker, bar)

    def _handle_five_min_bar(self, ticker, bar):
        if self.refetch_before is not None and bar["time"] < self.refetch_before:
            bar = self._refetch_bar(ticker, bar)
        frame = self.bars[ticker]
        if bar["time"] in frame.index:
            return
        self.bars[ticker] = pd.concat([frame, pd.DataFrame(
            [[bar["open"], bar["high"], bar["low"], bar["close"]]],
            columns=["open", "high", "low", "close"], index=pd.DatetimeIndex([bar["time"]]))])
        logger.info("5-min %-6s %s O=%.2f H=%.2f L=%.2f C=%.2f (%d min)", ticker, f"{bar['time']:%H:%M}",
                    bar["open"], bar["high"], bar["low"], bar["close"], bar.get("minutes", BAR_MINUTES))
        self._update_trades(ticker, bar)
        if bar["time"].time() < self.close_decision_bar:
            self._submit_evaluations(ticker, bar["time"])
        self._save_state()

    def _refetch_bar(self, ticker, partial):
        """The first period after a (re)start only has the minutes streamed since; fetch it whole."""
        try:
            fetched = self.client.fetch_bars([ticker], partial["time"], partial["time"] + timedelta(minutes=BAR_MINUTES))
            frame = fetched.get(ticker)
            if frame is not None and not frame.empty:
                row = regular_hours(frame).loc[partial["time"]]
                return {"time": partial["time"], "open": float(row["open"]), "high": float(row["high"]),
                        "low": float(row["low"]), "close": float(row["close"]), "minutes": BAR_MINUTES}
        except Exception:
            logger.warning("%s: refetch of the %s bar failed; using the streamed minutes", ticker,
                           f"{partial['time']:%H:%M}", exc_info=True)
        return partial

    # --- signals ---------------------------------------------------------

    def _submit_evaluations(self, ticker, bar_time):
        frame = add_moving_averages(self.bars[ticker])
        frame = frame[frame.index >= self.window_start[ticker]]
        for spec in self.setups[ticker]:
            if spec.overnight:
                continue
            future = self.executor.submit(evaluate_setup, (ticker, spec, frame, self.windows[ticker], bar_time))
            self.pending = [f for f in self.pending if not f.done()] + [future]
            future.add_done_callback(self._on_evaluated)

    def wait_pending(self):
        """Block until every submitted evaluation has been handled (replays and tests)."""
        from concurrent.futures import wait

        pending, self.pending = self.pending, []
        wait(pending)
        for future in pending:
            future.result()

    def _on_evaluated(self, future):
        try:
            fired = future.result()
        except Exception:
            logger.exception("Setup evaluation failed")
            return
        with self.lock:
            for sig in fired:
                key = f"{sig['ticker']}|{sig['setup']}|{sig['time'].isoformat()}"
                if key in self.alerted:
                    continue
                self.alerted.add(key)
                self._open_trade(sig)
            self._save_state()

    def _open_trade(self, sig):
        spec = next(s for s in self.setups[sig["ticker"]] if s.name == sig["setup"])
        side = 1 if sig["signal"] in LONG_SIGNALS else -1
        trade = LiveTrade(ticker=sig["ticker"], setup=sig["setup"], signal=sig["signal"], exit_mode=spec.exit_mode,
                          entry_time=sig["time"], side=side, entry=sig["price"], stop=sig["stop"],
                          target=sig["target"], risk=sig["risk"], last_bar=sig["time"])
        self.trades.append(trade)
        action = "BUY" if side == 1 else "SHORT"
        target_text = "" if spec.exit_mode == "eod" else f", target {trade.target:.2f}"
        self._alert(trade, action, trade.entry,
                    f"{action} {trade.ticker} | {trade.setup} | ~{trade.entry:.2f} ({sig['time']:%H:%M} bar close) | "
                    f"stop {trade.stop:.2f}{target_text} | {EXIT_TEXT[spec.exit_mode]}")

    # --- exits -----------------------------------------------------------

    def _update_trades(self, ticker, bar):
        for trade in self.trades:
            if trade.ticker != ticker or trade.status in ("closed",) or bar["time"] <= trade.last_bar:
                continue
            if trade.overnight:
                if trade.status == "pending" and bar["time"].time() == LAST_BAR:
                    trade.entry, trade.peak, trade.status, trade.last_bar = bar["close"], bar["close"], "open", bar["time"]
                elif trade.status == "open" and trade.entry_time.date() < bar["time"].date():
                    trade.close_at(bar["time"], bar["open"], "next open")
                    self._alert(trade, "SOLD", trade.exit_price,
                                f"SOLD {ticker} | overnight hold | open {trade.exit_price:.2f} | "
                                f"{trade.pnl_pct():+.2f}% from {trade.entry:.2f}", notify=False)
                continue
            if trade.status == "closing":
                trade.last_bar = bar["time"]
                if bar["time"].time() == LAST_BAR:
                    trade.close_at(bar["time"], bar["close"], "close")
                continue
            outcome = trade.on_bar(bar)
            if outcome:
                action = "SELL" if trade.side == 1 else "COVER"
                self._alert(trade, action, trade.exit_price,
                            f"{action} {ticker} | {trade.setup} | {outcome} hit on the {bar['time']:%H:%M} bar "
                            f"@ {trade.exit_price:.2f} | {trade.pnl_pct():+.2f}%")
            elif bar["time"].time() == LAST_BAR:
                trade.close_at(bar["time"], bar["close"], "close")

    def _close_alerts(self):
        """15:50: close every open intraday trade at the close, decide the overnight holds."""
        for trade in self.trades:
            if trade.overnight or trade.status != "open":
                continue
            trade.status = "closing"
            last = self._last_close(trade.ticker)
            action = "SELL" if trade.side == 1 else "COVER"
            pnl = f" | {trade.pnl_pct(last):+.2f}% at {last:.2f}" if last is not None else ""
            self._alert(trade, action, last, f"{action} {trade.ticker} | {trade.setup} | at the close (MOC){pnl}")
        for ticker, specs in self.setups.items():
            for spec in (s for s in specs if s.overnight):
                self._overnight_entry(ticker, spec)

    def _overnight_entry(self, ticker, spec):
        last = self._last_close(ticker)
        bar_time = self.bars[ticker].index[-1] if not self.bars[ticker].empty else None
        if last is None or bar_time is None or bar_time.date() != self.session:
            logger.warning("%s: no bars today; overnight hold skipped", ticker)
            return
        key = f"{ticker}|{spec.name}|{self.session.isoformat()}"
        if key in self.alerted:
            return
        probe = {"signal": "overnight_long", "time": bar_time}
        if spec.params.overnight_skip_earnings and in_earnings_window(probe, self.windows[ticker]):
            self.alerted.add(key)
            self._alert(None, "SKIP", last, f"SKIP {ticker} | {spec.name} | earnings release before the next open",
                        ticker=ticker, setup=spec.name)
            return
        closes = self.daily_closes.get(ticker, [])
        if not overnight_filter_ok(spec.params.overnight_hold, closes + [last]):
            logger.info("%s: %s filter not met at %.2f", ticker, spec.name, last)
            return
        self.alerted.add(key)
        trade = LiveTrade(ticker=ticker, setup=spec.name, signal="overnight_long", exit_mode="next open",
                          entry_time=bar_time, side=1, entry=last, stop=None, target=None, risk=None,
                          status="pending", last_bar=bar_time)
        self.trades.append(trade)
        self._alert(trade, "BUY", last, f"BUY {ticker} | {spec.name} | at the close (MOC), ref {last:.2f} "
                                        f"({bar_time:%H:%M} bar) | sell at the next open")

    def _pre_open_alerts(self):
        for trade in self.trades:
            if trade.overnight and trade.status == "open" and trade.entry_time.date() < self.session:
                self._alert(trade, "SELL", None, f"SELL {trade.ticker} | {trade.setup} | at the open (MOO before "
                                                 f"09:28), bought {trade.entry:.2f} on {trade.entry_time:%m-%d}")

    def _catch_up_trades(self):
        """Replay today's warm-up bars through trades restored from the state file."""
        for ticker in self.tickers:
            for stamp, row in self.bars[ticker].iterrows():
                if stamp.date() != self.session:
                    continue
                self._update_trades(ticker, {"time": stamp, "open": float(row["open"]), "high": float(row["high"]),
                                             "low": float(row["low"]), "close": float(row["close"])})

    # --- helpers ---------------------------------------------------------

    def _all_have_bar(self, bar_time):
        return all(not frame.empty and frame.index[-1].date() == self.session and frame.index[-1].time() >= bar_time
                   for frame in self.bars.values())

    def _last_close(self, ticker):
        frame = self.bars.get(ticker)
        if frame is None or frame.empty or frame.index[-1].date() != self.session:
            return None
        return float(frame["close"].iloc[-1])

    def _watchdog(self, now):
        if not (MARKET_OPEN <= now.time() < time(16, 0)) or self.stream_started_at is None:
            return
        last = self.last_minute_at or max(self.stream_started_at, ET.localize(datetime.combine(now.date(), MARKET_OPEN)))
        if (now - last).total_seconds() > STREAM_TIMEOUT_SECONDS:
            logger.warning("No 1-min bar for %.0fs; reconnecting the stream", (now - last).total_seconds())
            self.last_minute_at = now
            try:
                self.client.reconnect()
            except Exception:
                logger.exception("Stream reconnect failed")

    def _alert(self, trade, action, price, message, notify=True, ticker=None, setup=None):
        now = self.now()
        logger.info("ALERT %s", message)
        if notify:
            try:
                self.notify(f"[wave] {message}")
            except Exception:
                logger.exception("Notification failed")
        path = self.alerts_dir / f"wave_setup_alerts_{self.session}.csv"
        is_new = not path.exists()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", newline="") as handle:
            writer = csv.writer(handle)
            if is_new:
                writer.writerow(["time", "ticker", "setup", "action", "price", "stop", "target", "message"])
            writer.writerow([now.isoformat(timespec="seconds"), trade.ticker if trade else ticker,
                             trade.setup if trade else setup, action, "" if price is None else round(price, 4),
                             "" if not trade or trade.stop is None else round(trade.stop, 4),
                             "" if not trade or trade.target is None else round(trade.target, 4), message])

    def _session_summary(self):
        closed = [t for t in self.trades if t.status == "closed" and t.exit_time is not None
                  and t.exit_time.date() == self.session and t.exit_price is not None]
        holding = [t for t in self.trades if t.overnight and t.status == "open"]
        if not closed and not holding:
            return
        lines = [f"{t.ticker} {t.setup} {t.outcome} {t.pnl_pct():+.2f}%" for t in closed]
        lines += [f"{t.ticker} {t.setup} holding overnight from {t.entry:.2f}" for t in holding]
        total = sum(t.pnl_pct() for t in closed)
        self.notify(f"[wave] {self.session} summary: {len(closed)} closed, {total:+.2f}% summed\n" + "\n".join(lines))

    # --- state -----------------------------------------------------------

    def _load_state(self):
        if not self.state_file.exists():
            return
        try:
            state = json.loads(self.state_file.read_text())
        except (OSError, ValueError):
            logger.warning("Unreadable state file %s; starting fresh", self.state_file)
            return
        same_session = state.get("session") == self.session.isoformat()
        trades = [LiveTrade.from_dict(d) for d in state.get("trades", [])]
        if same_session:
            self.trades = trades
            self.alerted = set(state.get("alerted", []))
            self.done.update(state.get("done", {}))
        else:
            self.trades = [t for t in trades if t.overnight and t.status in ("open", "pending")
                           and t.ticker in self.setups]
            for trade in self.trades:
                trade.status = "open"

    def _save_state(self):
        with self.lock:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            keep = [t for t in self.trades
                    if t.status != "closed" or (t.exit_time and t.exit_time.date() == self.session)]
            temp = self.state_file.with_name(f"{self.state_file.name}.{os.getpid()}.{threading.get_ident()}.tmp")
            temp.write_text(json.dumps({"session": self.session.isoformat(), "alerted": sorted(self.alerted),
                                        "done": self.done, "trades": [t.to_dict() for t in keep]}, indent=1))
            temp.replace(self.state_file)


def _empty_bars():
    return pd.DataFrame(columns=["open", "high", "low", "close"], index=pd.DatetimeIndex([], tz=ET), dtype=float)


def _load_daily_closes(tickers, session):
    """Split-adjusted daily closes before `session`, for the overnight moving-average filters."""
    daily = fetch_daily_bars(tickers, session - timedelta(days=DAILY_HISTORY_DAYS), session - timedelta(days=1))
    out = {}
    for ticker in tickers:
        frame = daily.get(ticker)
        if frame is None or frame.empty:
            out[ticker] = []
            continue
        column = "Close" if "Close" in frame.columns else "close"
        out[ticker] = [float(c) for d, c in frame[column].items() if pd.Timestamp(d).date() < session]
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _configure_logging(log_file, level, to_stream):
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s — %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    root = logging.getLogger()
    root.setLevel(getattr(logging, level))
    root.handlers.clear()
    if to_stream:
        stream = logging.StreamHandler()
        stream.setFormatter(fmt)
        root.addHandler(stream)
    handler = logging.handlers.TimedRotatingFileHandler(log_file, when="midnight", backupCount=30, encoding="utf-8")
    handler.setFormatter(fmt)
    root.addHandler(handler)
    for noisy in ("urllib3", "requests", "websockets", "yfinance"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def build_market_data_client(args):
    client = _build_market_data_client(args)
    if client is not None:
        return client
    from alpha_tech_tracker.trade_api.alpaca_client.market_data_client import AlpacaMarketDataClient

    feed = DataFeed.SIP if args.feed == "sip" else DataFeed.IEX
    logger.info("Market data source: Alpaca (%s)", args.feed)
    return AlpacaMarketDataClient(os.environ.get("ALPACA_API_KEY"), os.environ.get("ALPACA_SECRET_KEY"), feed)


def _run_monitor(args):
    setups = load_config(args.config)
    executor = InlineExecutor() if args.workers == 0 else ProcessPoolExecutor(max_workers=args.workers)
    monitor = WaveSetupMonitor(setups, build_market_data_client(args), state_file=args.state_file, executor=executor,
                               close_decision_bar=datetime.strptime(args.close_decision_bar, "%H:%M").time())

    def _stop(signum, frame):
        raise KeyboardInterrupt

    signal_module.signal(signal_module.SIGTERM, _stop)
    try:
        monitor.run()
    except KeyboardInterrupt:
        logger.info("Stopped")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action", choices=["config", "run", "start", "stop", "status", "restart"])
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help=f"Monitor config (default: {DEFAULT_CONFIG})")
    parser.add_argument("--report", help="config: setup report folder with trades.csv")
    parser.add_argument("--tickers", nargs="+", help="config: tickers to monitor (default: every ticker in the report)")
    parser.add_argument("--top", type=int, default=3, help="config: setups per ticker (default: 3)")
    parser.add_argument("--market-data-source", choices=["alpaca", "tradestation", "local_ts_broadcast"],
                        help="Market data provider (default: config.json market_data_source, else alpaca)")
    parser.add_argument("--feed", default="sip", choices=["sip", "iex"], help="Alpaca feed (default: sip)")
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1),
                        help="Processes evaluating setups (0 = in the main process)")
    parser.add_argument("--close-decision-bar", default=f"{DEFAULT_CLOSE_DECISION_BAR:%H:%M}", choices=["15:40", "15:45"],
                        help="Bar whose close decides the close/overnight alerts: 15:45 alerts about 15:50 (Nasdaq "
                             "MOC cutoff 15:55), 15:40 about 15:45 (NYSE MOC cutoff 15:50) (default: 15:45)")
    parser.add_argument("--state-file", default=str(DEFAULT_STATE))
    parser.add_argument("--pid-file", default=PID_FILE)
    parser.add_argument("--log-file", help="Default: logs/wave_setup_monitor_<date>.log")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    parser.add_argument("--no-notify", action="store_true", help="Log and write the CSV only, no Telegram/SMS")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    os.makedirs(_LOG_DIR, exist_ok=True)
    log_file = args.log_file or os.path.join(_LOG_DIR, f"wave_setup_monitor_{date.today()}.log")

    if args.action == "config":
        if not args.report:
            sys.exit("config needs --report <setup report folder>")
        tickers = args.tickers
        if not tickers:
            with (Path(args.report) / "trades.csv").open() as handle:
                tickers = list(dict.fromkeys(row["ticker"] for row in csv.DictReader(handle)))
        config = generate_config(args.report, tickers, args.top)
        Path(args.config).parent.mkdir(parents=True, exist_ok=True)
        Path(args.config).write_text(json.dumps(config, indent=1))
        for ticker, setups in config["tickers"].items():
            print(f"{ticker:6} " + ", ".join(f"{s['setup']} ({s['report_total_pct']:+.2f}%)" for s in setups))
        print(f"config written to {args.config}")
        return

    _load_config()
    if args.no_notify:
        disable_notifications()

    if args.action == "run":
        _configure_logging(log_file, args.log_level, to_stream=True)
        _run_monitor(args)
        return
    if args.action == "status":
        pid = _read_pid(args.pid_file)
        print(f"Monitor running (PID {pid}) — log: {log_file}" if pid and _is_running(pid) else "Monitor is not running.")
        return
    if args.action in ("stop", "restart"):
        _daemon_stop(args.pid_file, log_file)
        if args.action == "stop":
            return
    pid = _read_pid(args.pid_file)
    if pid and _is_running(pid):
        sys.exit(f"Monitor already running (PID {pid}). Use 'restart' or 'stop' first.")
    load_config(args.config)
    print(f"Starting monitor daemon — logs: {log_file}")
    _daemonize(log_file)
    _write_pid(args.pid_file)
    try:
        _configure_logging(log_file, args.log_level, to_stream=False)
        _run_monitor(args)
    finally:
        _remove_pid(args.pid_file)


if __name__ == "__main__":
    main()

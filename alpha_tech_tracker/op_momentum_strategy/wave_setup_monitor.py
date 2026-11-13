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
  SHORT / SHORT LIMIT / SHORTED / LOWER STOP / COVER
               down-market shorts (short_setups), only on sessions the gate allows (`--short-gate`, default
               QQQ's previous close below its 50-day MA; the start-up alert says whether they are on):
               drive (a red first bar shorted at 09:35, stop its high, one re-entry below that high after a
               stop-out, covered at the close) and overnight (short the close, cover at the next open) by
               default; retest (a sell limit at the retest of the last confirmed rally high, trailing stop) is
               opt-in, it did not hold up out of sample. On `--short-tickers`, default the config's tickers
               (QQQ is the gate and trend benchmark, not traded); `--short-setups` picks them, `--no-short-setups` turns them off. `--short-gate
               qqq-ma50-down10` / `qqq-ma200` and `--overnight-short-gate` (default: the short gate) are opt-in
               gates (Finding 41). On sessions the overnight short is on, the long overnight holds are skipped;
               a configured `drive short` is not alerted twice.
  RAISE STOP / BUY (re-entry)
               opt-in drive long options: `--drive-trail` raises an open drive long's stop to each new
               confirmed dip low (wave setting 7 bars / 38.2% / 1.5); `--drive-reentry` buys once after a
               drive long stop-out when a bar closes back above the stop-out level (before 15:00), stop the
               low since the stop-out, held to the close (Findings 32, 35, 36).
  TREND FILTERS
               opt-in (`--trend-filters`, off by default; Finding 40), decided at start-up on the
               daily bars before the session, listed in one start-up alert: `pullback` (pullback long / C1 only
               while the ticker's 10-session high is above the 10 before; mixed across years), `overnight`
               (overnight holds only while QQQ is above its 200-day MA and up over 10 sessions; SKIP at the
               close otherwise; the best of the tested rules over 2020, 2022, 2025 and 2026).
  Start-up    drive long and overnight hold win rates: the last 10 sessions pooled over the stats
               tickers (`--stats-tickers`), and day by day for the last 3 sessions over the monitored
               tickers (signal_stats). `--no-signal-stats` turns it off.
  LOW? / HIGH? information only, no trade: a reversal candle (piercing / dark cloud, push, long tail
               confirmed by the next bar) on a bar near the low of a down wave or the high of an up wave
               (reversal_watch), up to the bar before the last. `--reversal-patterns` picks the patterns,
               `--no-reversal-alerts` turns them off.

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
exits 5 minutes after the close; schedule `start` each trading morning (e.g. 09:00 ET). Early-close
days (13:00) move the close alerts with the close and skip the overnight hold, like the backtest.
A data outage of 5 minutes is notified once, and its bars are backfilled when the data returns.

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
import subprocess
import sys
import threading
import time as time_module
from concurrent.futures import ProcessPoolExecutor
from datetime import date, datetime, time, timedelta
from pathlib import Path

import pandas as pd
from alpaca.data.enums import DataFeed

from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.earnings_calendar import earnings_windows, load_releases
from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.wave_risk_reward import analyze_bars, regular_hours
from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.wave_risk_reward_setup_report import TYPE_CHOICES
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
from alpha_tech_tracker.op_momentum_strategy.op_momentum_backtest import fetch_daily_bars
from alpha_tech_tracker.op_momentum_strategy.reversal_watch import (
    PATTERNS as REVERSAL_PATTERNS,
    ReversalWatch,
    reversal_message,
)
from alpha_tech_tracker.op_momentum_strategy.short_setups import (  # noqa: F401 (re-exported; tests patch TurnTracker)
    DEFAULT_SHORT_SETUPS,
    GATE_TICKER,
    GATES as SHORT_GATES,
    SHORT_SETUPS,
    TurnTracker,
)
from alpha_tech_tracker.op_momentum_strategy.trend_filters import TREND_FILTERS
from alpha_tech_tracker.op_momentum_strategy.signal_stats import (
    DEFAULT_STATS_DAYS,
    DEFAULT_STATS_OVERNIGHT,
    DEFAULT_STATS_SESSIONS,
    DEFAULT_STATS_TICKERS,
    signal_stats,
)
from alpha_tech_tracker.op_momentum_strategy.wave_strategy.intents import SYSTEM
from alpha_tech_tracker.op_momentum_strategy.wave_strategy.feed import (  # noqa: F401 (re-exported)
    DELAYED_DATA_MINUTES,
    OUTAGE_ALERT_SECONDS,
    STREAM_TIMEOUT_SECONDS,
    WARMUP_CALENDAR_DAYS,
    BarFeed,
)
from alpha_tech_tracker.op_momentum_strategy.wave_strategy.bars import (  # noqa: F401 (re-exported)
    FLUSH_GRACE_SECONDS,
    FiveMinAggregator,
)
from alpha_tech_tracker.op_momentum_strategy.wave_strategy.session import (  # noqa: F401 (re-exported)
    AFTER_CLOSE_MINUTES,
    BAR_MINUTES,
    EARLY_CLOSE,
    ET,
    MARKET_OPEN,
    PRE_OPEN_ALERT,
    REGULAR_CLOSE,
    _now_et,
    is_trading_day,
    period_start,
    previous_trading_day,
    session_close,
)
from alpha_tech_tracker.op_momentum_strategy.wave_strategy.specs import (  # noqa: F401 (re-exported)
    DEFAULT_REFRESH_ROOT,
    EXIT_TEXT,
    SetupSpec,
    build_setup_spec,
    generate_config,
    load_config,
    refresh_report,
)
from alpha_tech_tracker.op_momentum_strategy.wave_strategy.strategy import (  # noqa: F401 (re-exported)
    CONFIG_DRIVE_SHORT,
    DEFAULT_CLOSE_DECISION_BAR,
    DRIVE_LONG,
    DRIVE_REENTRY,
    DRIVE_REENTRY_LATEST,
    DRIVE_TRAIL_SETTING,
    OVERNIGHT_MIN_DAILY_CLOSES,
    RETEST_CANCEL,
    WARMUP_SESSIONS,
    WaveSetupStrategy,
)
from alpha_tech_tracker.op_momentum_strategy.wave_strategy.trades import (  # noqa: F401 (re-exported)
    InlineExecutor,
    LiveTrade,
    fired_signals,
)

logger = logging.getLogger(__name__)

DEFAULT_CONFIG = Path(_LOG_DIR) / "wave_setup_monitor_config.json"
DEFAULT_STATE = Path(_LOG_DIR) / "wave_setup_monitor_state.json"
PID_FILE = os.path.join(_LOG_DIR, "wave_setup_monitor.pid")
MODULE = "alpha_tech_tracker.op_momentum_strategy.wave_setup_monitor"
REFRESH_LOOKBACK_SESSIONS = 63
DAILY_HISTORY_DAYS = 420


def evaluate_setup(job):
    """Signals of one setup that fired on `bar_time`, from analyze_bars over the day's window.

    Runs in the process pool. Looks up `analyze_bars` in this module so tests can patch it here;
    the trade engine uses wave_strategy.trades.evaluate_setup.
    """
    ticker, spec, frame, windows, bar_time = job
    return fired_signals(ticker, spec, analyze_bars(frame, spec.params, windows)["signals"], bar_time)


def _evaluate_fn():
    """The evaluation function the strategy submits, looked up here at call time so patches on this module apply."""
    return evaluate_setup


def _forward(name, owner="strategy"):
    return property(lambda self: getattr(getattr(self, owner), name),
                    lambda self, value: setattr(getattr(self, owner), name, value))


# ---------------------------------------------------------------------------
# The monitor
# ---------------------------------------------------------------------------

class WaveSetupMonitor:
    def __init__(self, setups_by_ticker, market_data_client, state_file=DEFAULT_STATE, alerts_dir=_LOG_DIR,
                 executor=None, notify=_notify, now=_now_et, releases_loader=load_releases,
                 daily_closes_loader=None, close_decision_bar=DEFAULT_CLOSE_DECISION_BAR,
                 reversal_patterns=REVERSAL_PATTERNS, stats_tickers=DEFAULT_STATS_TICKERS,
                 stats_daily_loader=None, short_setups=DEFAULT_SHORT_SETUPS, short_gate="qqq-ma50", short_tickers=None,
                 extra_tickers=(), drive_trail=False, drive_reentry=False, trend_filters=(), trend_daily_loader=None,
                 overnight_short_gate=None):
        self.state_file = Path(state_file)
        self.alerts_dir = Path(alerts_dir)
        self.executor = executor or InlineExecutor()
        self.notify = notify
        self.now = now
        self.releases_loader = releases_loader
        self.reversal_patterns = tuple(reversal_patterns)
        self.reversal_watches = {}
        self.reversal_paused = False
        self.stats_tickers = tuple(stats_tickers)
        self.stats_daily_loader = stats_daily_loader or _load_daily_close_series
        # streamed only for the short setups or an open overnight trade: no reversal alerts, not in the signal stats
        self.extra_tickers = set(extra_tickers)
        self.lock = threading.RLock()
        self.strategy = WaveSetupStrategy(
            setups_by_ticker, sink=self._on_intent, executor=self.executor, lock=self.lock, persist=self._save_state,
            evaluate_fn=_evaluate_fn, now=now, releases_loader=releases_loader,
            daily_closes_loader=daily_closes_loader or _load_daily_closes,
            trend_daily_loader=trend_daily_loader or _load_daily_bars, close_decision_bar=close_decision_bar,
            short_setups=short_setups, short_gate=short_gate, short_tickers=short_tickers,
            overnight_short_gate=overnight_short_gate, drive_trail=drive_trail, drive_reentry=drive_reentry,
            trend_filters=trend_filters)
        self.feed = BarFeed(market_data_client, on_bar=self._handle_five_min_bar, on_backfill=self._merge_backfill,
                            alert=self._system_alert, now=now, lock=self.lock)
        self.done = {"pre_open": False, "close": False}

    # strategy state, read and set through the monitor (callers and tests predate the split)
    setups = _forward("setups")
    tickers = _forward("tickers")
    bars = _forward("bars")
    window_start = _forward("window_start")
    windows = _forward("windows")
    daily_closes = _forward("daily_closes")
    trades = _forward("trades")
    alerted = _forward("alerted")
    session = _forward("session")
    pending = _forward("pending")
    short_setups = _forward("short_setups")
    short_gate = _forward("short_gate")
    short_tickers = _forward("short_tickers")
    shorts_on = _forward("shorts_on")
    short_gate_text = _forward("short_gate_text")
    overnight_short_gate = _forward("overnight_short_gate")
    overnight_short_on = _forward("overnight_short_on")
    overnight_short_text = _forward("overnight_short_text")
    short_watches = _forward("short_watches")
    short_adr = _forward("short_adr")
    drive_trail = _forward("drive_trail")
    drive_reentry = _forward("drive_reentry")
    drive_trackers = _forward("drive_trackers")
    trend_filters = _forward("trend_filters")
    trend_blocked = _forward("trend_blocked")
    daily_closes_loader = _forward("daily_closes_loader")
    trend_daily_loader = _forward("trend_daily_loader")
    close_time = _forward("close_time")
    half_day = _forward("half_day")
    close_decision_bar = _forward("close_decision_bar")
    last_bar = _forward("last_bar")
    close_alert_at = _forward("close_alert_at")
    close_alert_latest = _forward("close_alert_latest")
    session_end = _forward("session_end")
    # market data state, read and set through the monitor the same way
    client = _forward("client", "feed")
    client_lock = _forward("client_lock", "feed")
    aggregator = _forward("aggregator", "feed")
    stream_started_at = _forward("stream_started_at", "feed")
    last_minute_at = _forward("last_minute_at", "feed")
    refetch_before = _forward("refetch_before", "feed")
    backfill = _forward("backfill", "feed")
    last_reconnect_at = _forward("last_reconnect_at", "feed")
    outage_from = _forward("outage_from", "feed")

    # --- lifecycle -------------------------------------------------------

    def prepare(self):
        """Warm up history, earnings windows and daily closes, restore state, catch up open trades."""
        now = self.now()
        bars_by_ticker = self.feed.session_bars(self.tickers, now)
        self.strategy.start_session(now.date(), bars_by_ticker)
        for ticker in self.tickers:
            self._rebuild_reversal_watch(ticker)
        self._load_state()
        self.strategy.prepare()
        self.strategy.catch_up()
        self.feed.start_session(self.session, self.tickers, self.close_time, now)
        self._save_state()

    def _run_backfill(self, now):
        self.feed.run_backfill(now)

    def _merge_backfill(self, gap_start, fetched):
        """Insert the bars of a delayed-feed start or an outage; they update history only (no alerts)."""
        if fetched is None:
            if self.reversal_watches:
                self.reversal_paused = True
                logger.warning("Reversal alerts paused for the session: their waves miss the gap's bars")
            return
        for ticker, frame in fetched.items():
            missing = frame[~frame.index.isin(self.bars[ticker].index)]
            if not missing.empty:
                self.bars[ticker] = pd.concat([self.bars[ticker], missing]).sort_index()
                self._rebuild_reversal_watch(ticker)
                self.strategy.rebuild_drive_trail(ticker)
                logger.info("%s: backfilled %d bars from %s", ticker, len(missing), f"{gap_start:%H:%M}")
        self._save_state()

    def start_stream(self):
        self.feed.start_stream()

    def _history(self, method, tickers, start, end):
        return self.feed.history(method, tickers, start, end)

    def send_signal_stats(self):
        """Start-up alert, once per session: recent drive long / overnight win rates (signal_stats).

        Errors are logged, not raised.
        """
        if self.done.get("signal_stats"):
            return
        try:
            message = self._signal_stats_message()
        except Exception:
            logger.exception("Signal stats failed")
            return
        logger.info("SIGNAL STATS\n%s", message)
        try:
            self.notify(f"[wave] {message}")
        except Exception:
            logger.exception("Notification failed")
        with self.lock:
            self.done["signal_stats"] = True
            self._save_state()

    def _signal_stats_message(self):
        previous = previous_trading_day(self.session)
        end = ET.localize(datetime.combine(previous, session_close(previous)))
        bars = dict(self.bars)
        for ticker in (t for t in self.stats_tickers if t not in bars):
            try:
                frame = self._history("warmup", [ticker], end - timedelta(days=WARMUP_CALENDAR_DAYS), end).get(ticker)
            except Exception:
                logger.warning("%s: signal stats history unavailable", ticker, exc_info=True)
                continue
            if frame is not None and not frame.empty:
                bars[ticker] = regular_hours(frame)
        notes = []
        try:
            daily = self.stats_daily_loader(list(bars), self.session)
        except Exception:
            logger.warning("Daily closes unavailable for the signal stats", exc_info=True)
            daily = {}
            notes.append(f"overnight {DEFAULT_STATS_OVERNIGHT}: daily closes unavailable, no holds counted")
        windows = {}
        for ticker, frame in bars.items():
            try:
                sessions = sorted(set(frame.index.date) | {self.session})
                windows[ticker] = earnings_windows(self.releases_loader(ticker), sessions)
            except Exception:
                logger.warning("%s: earnings calendar unavailable; its overnight stats include earnings nights",
                               ticker, exc_info=True)
        monitored = [t for t in self.tickers if t not in self.extra_tickers]
        future = self.executor.submit(signal_stats, bars, daily, windows, self.stats_tickers, monitored,
                                      self.session, DEFAULT_STATS_SESSIONS, DEFAULT_STATS_DAYS,
                                      DEFAULT_STATS_OVERNIGHT, notes)
        return future.result()

    def tick(self):
        """Periodic work: flush late 5-min bars, scheduled alerts, stream watchdog."""
        now = self.now()
        with self.lock:
            self.feed.flush_due(now)
            if self.backfill is not None:
                self._run_backfill(now)
            if not self.done["pre_open"] and now.time() >= PRE_OPEN_ALERT:
                self.done["pre_open"] = True
                self.strategy.on_pre_open()
            if not self.done["close"] and now.time() >= self.close_alert_at and (
                    now.time() >= self.close_alert_latest or self.strategy.all_have_bar(self.close_decision_bar)):
                self.done["close"] = True
                self.strategy.on_close_decision()
        self.feed.watchdog(now)

    def finish(self):
        """End of session: close anything still open at the last close, summarize, save."""
        with self.lock:
            self.strategy.close_leftovers()
            try:
                self._session_summary()
            finally:
                self._save_state()

    def run(self, poll_seconds=1.0):
        today = self.now().date()
        if not is_trading_day(today):
            logger.info("Market closed today (%s); nothing to monitor", today)
            return
        self.prepare()
        self.start_stream()
        if self.stats_tickers:
            threading.Thread(target=self.send_signal_stats, name="signal-stats", daemon=True).start()
        self._system_alert(f"monitor started for {today}: {len(self.tickers)} tickers ({', '.join(self.tickers)})"
                           + (f"; early close at {self.close_time:%H:%M}" if self.half_day else ""), level=logging.INFO)
        logger.info("Monitoring %s", ", ".join(f"{t}: {[s.name for s in self.setups[t]]}" for t in self.tickers))
        if self.short_setups and self.short_tickers:
            separate = self.overnight_short_gate != self.short_gate and "overnight" in self.short_setups
            self._system_alert(f"{self.short_gate_text} ({', '.join(self.short_setups)} on "
                               f"{', '.join(self.short_tickers)})"
                               + (f" | {self.overnight_short_text}" if separate else ""), level=logging.INFO)
        try:
            while self.now().time() < self.session_end:
                self.tick()
                time_module.sleep(poll_seconds)
        finally:
            self.finish()
            self.feed.stop()
            self.executor.shutdown(wait=False)

    # --- bars ------------------------------------------------------------

    def on_minute_bar(self, bar):
        self.feed.on_minute_bar(bar)

    def _on_five_min_bar(self, ticker, bar):
        self.feed.on_five_min_bar(ticker, bar)

    def _handle_five_min_bar(self, ticker, bar):
        if not self.strategy.add_bar(ticker, bar):
            return
        logger.info("5-min %-6s %s O=%.2f H=%.2f L=%.2f C=%.2f (%d min)", ticker, f"{bar['time']:%H:%M}",
                    bar["open"], bar["high"], bar["low"], bar["close"], bar.get("minutes", BAR_MINUTES))
        self.strategy.on_bar_exits(ticker, bar)
        self._check_reversals(ticker, bar)
        self.strategy.on_bar_shorts(ticker, bar)
        if self.strategy.takes_entries(bar["time"]):
            self._submit_evaluations(ticker, bar["time"])
        self._save_state()

    def _submit_evaluations(self, ticker, bar_time):
        self.strategy.submit_evaluations(ticker, bar_time)

    def _update_trades(self, ticker, bar):
        self.strategy._update_trades(ticker, bar)

    def wait_pending(self):
        """Block until every submitted evaluation has been handled (replays and tests)."""
        self.strategy.wait_pending()

    # --- signals ---------------------------------------------------------

    def _rebuild_reversal_watch(self, ticker):
        """A fresh watch from the ticker's bars, so it knows the current wave; the replay alerts nothing."""
        if not self.reversal_patterns or ticker in self.extra_tickers:
            return
        try:
            self.reversal_watches[ticker] = ReversalWatch.from_bars(ticker, self.bars[ticker].sort_index(),
                                                                    self.reversal_patterns)
        except Exception:
            self.reversal_watches.pop(ticker, None)
            logger.exception("%s: reversal watch rebuild failed; no reversal alerts for it", ticker)

    def _check_reversals(self, ticker, bar):
        """Reversal alerts for a new bar; never in the way of the setups (errors are logged, not raised)."""
        watch = self.reversal_watches.get(ticker)
        if watch is None:
            return
        if watch.last_time is not None and bar["time"] <= watch.last_time:
            self._rebuild_reversal_watch(ticker)
            return
        try:
            fired = [s for s in watch.update(bar["time"], bar) if s.key not in self.alerted]
        except Exception:
            logger.exception("%s: reversal check failed on the %s bar; rebuilding its watch", ticker,
                             f"{bar['time']:%H:%M}")
            self._rebuild_reversal_watch(ticker)
            return
        # until a delayed-feed gap is backfilled the watch's waves miss bars
        if self.backfill is not None or self.reversal_paused or bar["time"].time() >= self.last_bar:
            return
        for side in ("bottom", "top"):
            signals = [s for s in fired if s.side == side]
            if not signals:
                continue
            self.alerted.update(s.key for s in signals)
            self._alert(None, "LOW?" if side == "bottom" else "HIGH?", signals[0].price, reversal_message(signals),
                        ticker=ticker, setup="reversal " + " + ".join(s.pattern for s in signals))

    def _on_intent(self, intent):
        """The strategy's decisions become alerts here; the trade engine's sink turns them into orders."""
        if intent.kind == SYSTEM:
            self._system_alert(intent.message, level=intent.level)
            return
        self._alert(intent.trade, intent.action, intent.price, intent.message, notify=intent.notify,
                    ticker=intent.ticker, setup=intent.setup)

    def _system_alert(self, message, level=logging.WARNING):
        logger.log(level, "SYSTEM %s", message)
        try:
            self.notify(f"[wave] {message}")
        except Exception:
            logger.exception("Notification failed")

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
        try:
            self.notify(f"[wave] {self.session} summary: {len(closed)} closed, {total:+.2f}% summed\n" + "\n".join(lines))
        except Exception:
            logger.exception("Summary notification failed")

    # --- state -----------------------------------------------------------

    def _load_state(self):
        if not self.state_file.exists():
            return
        try:
            state = json.loads(self.state_file.read_text())
        except (OSError, ValueError):
            logger.warning("Unreadable state file %s; starting fresh", self.state_file)
            return
        if self.strategy.restore(state):
            self.done.update(state.get("done", {}))

    def _save_state(self):
        with self.lock:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            state = self.strategy.state()
            temp = self.state_file.with_name(f"{self.state_file.name}.{os.getpid()}.{threading.get_ident()}.tmp")
            temp.write_text(json.dumps({"session": state["session"], "alerted": state["alerted"], "done": self.done,
                                        "trades": state["trades"]}, indent=1))
            temp.replace(self.state_file)


def _load_daily_close_series(tickers, session):
    """Split-adjusted daily closes before `session` as {ticker: Series by date}, for the start-up signal stats."""
    daily = fetch_daily_bars(tickers, session - timedelta(days=DAILY_HISTORY_DAYS), session - timedelta(days=1))
    out = {}
    for ticker in tickers:
        frame = daily.get(ticker)
        if frame is None or frame.empty:
            out[ticker] = pd.Series(dtype=float)
            continue
        column = "Close" if "Close" in frame.columns else "close"
        closes = pd.Series([float(c) for c in frame[column]], index=[pd.Timestamp(d).date() for d in frame.index])
        out[ticker] = closes[[d < session for d in closes.index]]
    return out


def _load_daily_bars(tickers, session):
    """Split-adjusted daily highs and closes before `session` as {ticker: DataFrame by date}, for the trend filters."""
    daily = fetch_daily_bars(tickers, session - timedelta(days=DAILY_HISTORY_DAYS), session - timedelta(days=1))
    out = {}
    for ticker in tickers:
        frame = daily.get(ticker)
        if frame is None or frame.empty:
            out[ticker] = pd.DataFrame(columns=["high", "close"], dtype=float)
            continue
        columns = {c.lower(): c for c in frame.columns}
        dates = [pd.Timestamp(d).date() for d in frame.index]
        bars = pd.DataFrame({"high": [float(v) for v in frame[columns["high"]]],
                             "close": [float(v) for v in frame[columns["close"]]]}, index=dates)
        out[ticker] = bars[[d < session for d in bars.index]]
    return out


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


def open_overnight_tickers(state_file):
    """Tickers with an overnight trade still open or pending in the state file (they must be streamed to exit)."""
    try:
        state = json.loads(Path(state_file).read_text())
    except (OSError, ValueError):
        return []
    return sorted({t["ticker"] for t in state.get("trades", [])
                   if t.get("exit_mode") == "next open" and t.get("status") in ("open", "pending")})


def _run_monitor(args):
    setups = load_config(args.config)
    configured = set(setups)
    short_setups = [] if args.no_short_setups or args.short_gate == "off" else args.short_setups
    short_tickers = args.short_tickers or list(setups)
    for ticker in (short_tickers if short_setups else []) + open_overnight_tickers(args.state_file):
        setups.setdefault(ticker, [])
    executor = InlineExecutor() if args.workers == 0 else ProcessPoolExecutor(max_workers=args.workers)
    monitor = WaveSetupMonitor(setups, build_market_data_client(args), state_file=args.state_file, executor=executor,
                               close_decision_bar=datetime.strptime(args.close_decision_bar, "%H:%M").time(),
                               reversal_patterns=[] if args.no_reversal_alerts else args.reversal_patterns,
                               stats_tickers=[] if args.no_signal_stats else args.stats_tickers,
                               short_setups=short_setups, short_gate=args.short_gate,
                               overnight_short_gate=args.overnight_short_gate,
                               short_tickers=short_tickers if short_setups else [],
                               extra_tickers=set(setups) - configured,
                               drive_trail=args.drive_trail, drive_reentry=args.drive_reentry,
                               trend_filters=args.trend_filters)

    def _stop(signum, frame):
        raise KeyboardInterrupt

    signal_module.signal(signal_module.SIGTERM, _stop)
    try:
        monitor.run()
    except KeyboardInterrupt:
        logger.info("Stopped")


def _start_detached(argv, log_file):
    """macOS: a forked child crashes once it touches system frameworks (fork safety), so start a
    fresh `run` process in its own session instead of double-forking."""
    child_args = list(sys.argv[1:] if argv is None else argv)
    child_args[child_args.index("start" if "start" in child_args else "restart")] = "run"
    child_args += ["--detached", "--log-file", log_file]
    with open(log_file, "a") as log, open(os.devnull) as dev_null:
        process = subprocess.Popen([sys.executable, "-m", MODULE] + child_args, stdin=dev_null, stdout=log,
                                   stderr=log, start_new_session=True, cwd=os.getcwd())
    print(f"Monitor started (PID {process.pid})")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action", choices=["config", "run", "start", "stop", "status", "restart"])
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help=f"Monitor config (default: {DEFAULT_CONFIG})")
    parser.add_argument("--report", help="config: setup report folder with trades.csv")
    parser.add_argument("--tickers", nargs="+", help="config: tickers to monitor (default: every ticker in the report)")
    parser.add_argument("--top", type=int, default=3, help="config: setups per ticker (default: 3)")
    parser.add_argument("--types", nargs="+", choices=TYPE_CHOICES,
                        help="config: only these setup types; the recommended set is `long overnight` (Finding 18)")
    parser.add_argument("--min-trades", type=int, default=1, help="config: trades a setup needs (recommended: 3)")
    parser.add_argument("--lookback-sessions", type=int,
                        help=f"config: rank on the report's last N sessions (with --refresh: {REFRESH_LOOKBACK_SESSIONS})")
    parser.add_argument("--refresh", action="store_true",
                        help="config: first run the setup report for --tickers over the trailing window ending today")
    parser.add_argument("--market-data-source", choices=["alpaca", "tradestation", "local_ts_broadcast"],
                        help="Market data provider (default: config.json market_data_source, else alpaca)")
    parser.add_argument("--feed", default="sip", choices=["sip", "iex"], help="Alpaca feed (default: sip)")
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1),
                        help="Processes evaluating setups (0 = in the main process)")
    parser.add_argument("--close-decision-bar", default=f"{DEFAULT_CLOSE_DECISION_BAR:%H:%M}", choices=["15:40", "15:45"],
                        help="Bar whose close decides the close/overnight alerts: 15:45 alerts about 15:50 (Nasdaq "
                             "MOC cutoff 15:55), 15:40 about 15:45 (NYSE MOC cutoff 15:50) (default: 15:45)")
    parser.add_argument("--reversal-patterns", nargs="+", choices=REVERSAL_PATTERNS, default=list(REVERSAL_PATTERNS),
                        help="Reversal candles alerted (information only) near wave lows/highs (default: all: "
                             "piercing = piercing / dark cloud, push, long_tail = long tail confirmed by the next bar)")
    parser.add_argument("--no-reversal-alerts", action="store_true", help="No reversal candle alerts")
    parser.add_argument("--drive-trail", action="store_true",
                        help="Raise an open drive long's stop to each new confirmed dip low (RAISE STOP alerts)")
    parser.add_argument("--drive-reentry", action="store_true",
                        help="After a drive long stop-out, BUY once when a bar closes back above the stop-out level "
                             "(before 15:00), stop the low since the stop-out, held to the close")
    parser.add_argument("--short-setups", nargs="+", choices=SHORT_SETUPS, default=list(DEFAULT_SHORT_SETUPS),
                        help="Down-market shorts alerted on gated sessions (default: drive overnight; retest is "
                             "opt-in, it did not hold up out of sample)")
    parser.add_argument("--no-short-setups", action="store_true", help="No short setups")
    parser.add_argument("--short-gate", choices=SHORT_GATES, default="qqq-ma50",
                        help="When shorts are on: qqq-ma50 = QQQ's previous close below its 50-day MA (default); "
                             "qqq-ma50-down10 = below it and down over 10 sessions; qqq-ma200 = below its 200-day MA; "
                             "always; off")
    parser.add_argument("--overnight-short-gate", choices=SHORT_GATES,
                        help="Gate for the overnight short alone (default: --short-gate); qqq-ma200 was its best "
                             "over 2020-2026 (Finding 41)")
    parser.add_argument("--short-tickers", nargs="+", help="Tickers for the short setups (default: the config's "
                                                           "tickers; QQQ is not traded)")
    parser.add_argument("--trend-filters", nargs="+", choices=TREND_FILTERS, default=[],
                        help="Opt-in daily trend filters (default: none; Finding 40): overnight = overnight holds "
                             "only while QQQ is above its 200-day MA and up over 10 sessions; pullback = pullback "
                             "longs only on a higher 10-session high (mixed across years)")
    parser.add_argument("--stats-tickers", nargs="+", default=list(DEFAULT_STATS_TICKERS),
                        help="Tickers pooled in the start-up drive long / overnight win rates (default: the 21 "
                             "setup-tape tickers)")
    parser.add_argument("--no-signal-stats", action="store_true", help="No start-up signal stats alert")
    parser.add_argument("--state-file", default=str(DEFAULT_STATE))
    parser.add_argument("--pid-file", default=PID_FILE)
    parser.add_argument("--log-file", help="Default: logs/wave_setup_monitor_<date>.log")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    parser.add_argument("--no-notify", action="store_true", help="Log and write the CSV only, no Telegram/SMS")
    parser.add_argument("--detached", action="store_true", help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    os.makedirs(_LOG_DIR, exist_ok=True)
    log_file = args.log_file or os.path.join(_LOG_DIR, f"wave_setup_monitor_{date.today()}.log")

    if args.action == "config":
        if args.refresh:
            if not args.tickers:
                sys.exit("config --refresh needs --tickers")
            args.report = str(refresh_report(args.tickers, args.lookback_sessions or REFRESH_LOOKBACK_SESSIONS,
                                             max(1, args.workers)))
        if not args.report:
            sys.exit("config needs --report <setup report folder> (or --refresh --tickers ...)")
        tickers = args.tickers
        if not tickers:
            with (Path(args.report) / "trades.csv").open() as handle:
                tickers = list(dict.fromkeys(row["ticker"] for row in csv.DictReader(handle)))
        lookback = args.lookback_sessions or (REFRESH_LOOKBACK_SESSIONS if args.refresh else None)
        config = generate_config(args.report, tickers, args.top, args.types, args.min_trades, lookback)
        Path(args.config).parent.mkdir(parents=True, exist_ok=True)
        Path(args.config).write_text(json.dumps(config, indent=1))
        for ticker, setups in config["tickers"].items():
            print(f"{ticker:6} " + ", ".join(f"{s['setup']} ({s['report_total_pct']:+.2f}%)" for s in setups))
        print(f"config written to {args.config} (window {config['window']}, types {config['types']})")
        return

    _load_config()
    if args.no_notify:
        disable_notifications()

    if args.action == "run":
        pid = _read_pid(args.pid_file)
        if pid and pid != os.getpid() and _is_running(pid):
            sys.exit(f"Monitor already running (PID {pid}). Use 'stop' first.")
        _write_pid(args.pid_file)
        try:
            _configure_logging(log_file, args.log_level, to_stream=not args.detached)
            _run_monitor(args)
        finally:
            _remove_pid(args.pid_file)
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
    print(f"Starting monitor daemon — logs: {log_file}", flush=True)
    if sys.platform == "darwin":
        _start_detached(argv, log_file)
        return
    _daemonize(log_file)
    _write_pid(args.pid_file)
    try:
        _configure_logging(log_file, args.log_level, to_stream=False)
        _run_monitor(args)
    finally:
        _remove_pid(args.pid_file)


if __name__ == "__main__":
    main()

"""The wave setup strategy's trading core: entries, exits, stops, gates and filters, with no network or file I/O.

Every decision is pushed to `sink(intent)` as an `Intent` (wave_strategy.intents): the wave setup monitor turns it
into an alert, the trade engine into an order. Setup evaluations run on `executor` (a process pool in prod) and
report back on its callback thread, so they are pushed too, under `lock`. The caller owns the bars feed, the
schedule and the state file: it appends each closed 5-min bar (`add_bar`), then calls `on_bar_exits` and
`on_bar_entries`, `on_pre_open` at 09:25, `on_close_decision` at the close decision, and saves `state()`.
"""

import logging
import threading
from datetime import date, datetime, time, timedelta

import pandas as pd

from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.earnings_calendar import (
    earnings_windows,
    in_earnings_window,
    load_releases,
)
from alpha_tech_tracker.op_momentum_strategy.analysis_scripts.wave_risk_reward import (
    LONG_SIGNALS,
    add_moving_averages,
    overnight_filter_ok,
    overnight_needs_history,
)
from alpha_tech_tracker.op_momentum_strategy.short_setups import (
    DEFAULT_SHORT_SETUPS,
    GATE_TICKER,
    REENTRY_LATEST,
    RETEST_WINDOW,
    SETUP_NAMES as SHORT_NAMES,
    RetestShort,
    TurnTracker,
    gate_status,
    next_session_adr,
)
from alpha_tech_tracker.op_momentum_strategy.trend_filters import (
    MARKET_TICKER as TREND_MARKET_TICKER,
    PULLBACK_SETUPS,
    market_trend,
    overnight_rule,
    pullback_rule,
    ticker_trend,
)
from alpha_tech_tracker.op_momentum_strategy.wave_strategy.intents import (
    BAR_CLOSE,
    ENTER,
    EXIT,
    EXIT_ORDERS,
    INFO,
    LIMIT,
    MOC,
    MOO,
    MOVE_STOP,
    SKIP,
    STOP,
    SYSTEM,
    Intent,
)
from alpha_tech_tracker.op_momentum_strategy.wave_strategy.session import (
    AFTER_CLOSE_MINUTES,
    BAR_MINUTES,
    ET,
    MARKET_OPEN,
    REGULAR_CLOSE,
    _now_et,
    session_close,
)
from alpha_tech_tracker.op_momentum_strategy.wave_strategy.specs import EXIT_TEXT
from alpha_tech_tracker.op_momentum_strategy.wave_strategy.trades import InlineExecutor, LiveTrade, evaluate_setup

logger = logging.getLogger(__name__)

WARMUP_SESSIONS = 10
DEFAULT_CLOSE_DECISION_BAR = time(15, 45)
OVERNIGHT_MIN_DAILY_CLOSES = 200
RETEST_CANCEL = f"{RETEST_WINDOW[1]:%H:%M}"
CONFIG_DRIVE_SHORT = "drive short"
DRIVE_LONG = "drive long"
DRIVE_REENTRY = "drive long re-entry"
DRIVE_TRAIL_SETTING = (7, 0.382, 1.5)  # wave setting the drive-trail was chosen with (ticker-tuning doc, Finding 32)
DRIVE_REENTRY_LATEST = time(15, 0)


def _no_daily_data(tickers, session):
    return {}


def _no_op():
    pass


class WaveSetupStrategy:
    """`setups_by_ticker` is {ticker: [SetupSpec]}; tickers with no setups are watched for the shorts or an open
    overnight trade. `evaluate_fn` returns the function setup evaluations run (called each time, so a caller can
    swap it); `persist` is called after asynchronous changes (evaluations) so the caller can save `state()`.
    `intraday_only` (the trade engine) never enters an overnight hold or overnight short."""

    def __init__(self, setups_by_ticker, sink, executor=None, lock=None, persist=None, evaluate_fn=None, now=_now_et,
                 releases_loader=load_releases, daily_closes_loader=None, trend_daily_loader=None,
                 close_decision_bar=DEFAULT_CLOSE_DECISION_BAR, short_setups=DEFAULT_SHORT_SETUPS,
                 short_gate="qqq-ma50", short_tickers=None, overnight_short_gate=None, drive_trail=False,
                 drive_reentry=False, trend_filters=(), intraday_only=False):
        self.setups = setups_by_ticker
        self.tickers = list(setups_by_ticker)
        self.sink = sink
        self.executor = executor or InlineExecutor()
        self.lock = lock or threading.RLock()
        self.persist = persist or _no_op
        self.evaluate_fn = evaluate_fn or (lambda: evaluate_setup)
        self.now = now
        self.releases_loader = releases_loader
        self.daily_closes_loader = daily_closes_loader or _no_daily_data
        self.trend_daily_loader = trend_daily_loader or _no_daily_data
        self.intraday_only = intraday_only
        self.short_setups = tuple(short_setups)
        self.short_gate = short_gate
        self.short_tickers = [t for t in (short_tickers if short_tickers is not None else self.tickers) if t in self.setups]
        self.shorts_on = False
        self.short_gate_text = ""
        self.overnight_short_gate = overnight_short_gate or short_gate
        self.overnight_short_on = False
        self.overnight_short_text = ""
        self.short_watches = {}
        self.short_adr = {}
        self.drive_trail = drive_trail
        self.drive_reentry = drive_reentry
        self.drive_trackers = {}
        self.trend_filters = tuple(trend_filters)
        self.trend_blocked = {}
        self.decision_lead = datetime.combine(date.today(), REGULAR_CLOSE) - datetime.combine(date.today(),
                                                                                                close_decision_bar)
        self._set_session_times(_now_et().date())
        self.bars = {}
        self.window_start = {}
        self.windows = {}
        self.daily_closes = {}
        self.trades = []
        self.alerted = set()
        self.session = None
        self.pending = []

    # --- lifecycle -------------------------------------------------------

    def start_session(self, session, bars_by_ticker):
        """Today's session times, each ticker's bars so far with its signal and earnings windows, and the daily
        closes the overnight filters need. Call `restore` next (if there is saved state), then `prepare`."""
        self.session = session
        self._set_session_times(session)
        for ticker in self.tickers:
            bars = bars_by_ticker[ticker]
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
            short = [t for t in needs_daily if len(self.daily_closes.get(t, [])) < OVERNIGHT_MIN_DAILY_CLOSES]
            if short:
                self.sink(Intent(SYSTEM, f"overnight moving-average filter has too little daily history for "
                                         f"{', '.join(short)}; their filtered overnight holds will not fire today"))

    def restore(self, state):
        """Trades and alerted keys from a saved `state()`; returns True when it is today's session. From an earlier
        session only the open (or pending) overnight trades carry over, as open."""
        same_session = state.get("session") == self.session.isoformat()
        trades = [LiveTrade.from_dict(d) for d in state.get("trades", [])]
        if same_session:
            self.trades = trades
            self.alerted = set(state.get("alerted", []))
        else:
            self.trades = [t for t in trades if t.overnight and t.status in ("open", "pending")
                           and t.ticker in self.setups]
            for trade in self.trades:
                trade.status = "open"
        return same_session

    def state(self):
        """{"session", "alerted", "trades"}: today's trades and the trades still open."""
        keep = [t for t in self.trades if t.status != "closed" or (t.exit_time and t.exit_time.date() == self.session)]
        return {"session": self.session.isoformat(), "alerted": sorted(self.alerted),
                "trades": [t.to_dict() for t in keep]}

    def prepare(self):
        """Today's short gate, trend filters and drive-trail turns, from the bars and state loaded so far."""
        self._prepare_shorts()
        self._prepare_trend_filters()
        self._prepare_drive_trail(through_today=False)

    def catch_up(self):
        """Replay today's warm-up bars through the restored trades (a restart during the session)."""
        self._catch_up_trades()

    def close_leftovers(self):
        """End of session: close anything intraday still open at the last close; enter pending overnight holds."""
        for trade in self.trades:
            if trade.overnight and trade.status == "pending":
                last = self._last_close(trade.ticker)
                if last is not None:
                    trade.entry, trade.peak, trade.status = last, last, "open"
            elif not trade.overnight and trade.status in ("open", "closing"):
                last = self._last_close(trade.ticker)
                if last is not None:
                    trade.close_at(self.bars[trade.ticker].index[-1], last, "close")

    # --- bars ------------------------------------------------------------

    def add_bar(self, ticker, bar):
        """Append a closed 5-min bar; False when the ticker already has a bar at that time."""
        frame = self.bars[ticker]
        if bar["time"] in frame.index:
            return False
        self.bars[ticker] = pd.concat([frame, pd.DataFrame(
            [[bar["open"], bar["high"], bar["low"], bar["close"]]],
            columns=["open", "high", "low", "close"], index=pd.DatetimeIndex([bar["time"]]))])
        return True

    def on_bar_exits(self, ticker, bar):
        """Stops, targets and trails of the open trades, then the drive long options (trail, re-entry)."""
        self._update_trades(ticker, bar)
        self._drive_long_options(ticker, bar)

    def on_bar_shorts(self, ticker, bar):
        self._check_shorts(ticker, bar)

    def takes_entries(self, bar_time):
        """Setup entries stop at the close decision bar (no time left before the close)."""
        return bar_time.time() < self.close_decision_bar

    def submit_evaluations(self, ticker, bar_time):
        self._submit_evaluations(ticker, bar_time)

    def on_bar_entries(self, ticker, bar):
        """The shorts, then the setup evaluations (their entries arrive asynchronously through the sink)."""
        self.on_bar_shorts(ticker, bar)
        if self.takes_entries(bar["time"]):
            self.submit_evaluations(ticker, bar["time"])

    def rebuild_drive_trail(self, ticker):
        self._rebuild_drive_trail(ticker)

    # --- scheduled decisions ----------------------------------------------

    def on_pre_open(self):
        """09:25: sell (cover) the overnight trades at the open."""
        self._pre_open_alerts()

    def on_close_decision(self):
        """Close every open intraday trade at the close; enter the overnight holds unless `intraday_only`."""
        self._close_alerts()

    def all_have_bar(self, bar_time):
        return self._all_have_bar(bar_time)

    def last_close(self, ticker):
        return self._last_close(ticker)

    # --- internals ---------------------------------------------------------

    def _set_session_times(self, day):
        """Close-relative times for the day: the decision bar, the last bar, the close alert, the end."""
        close = datetime.combine(day, session_close(day))
        self.close_time = close.time()
        self.half_day = self.close_time < REGULAR_CLOSE
        self.close_decision_bar = (close - self.decision_lead).time()
        self.last_bar = (close - timedelta(minutes=BAR_MINUTES)).time()
        self.close_alert_at = (close - self.decision_lead + timedelta(minutes=BAR_MINUTES)).time()
        self.close_alert_latest = (close - self.decision_lead + timedelta(minutes=BAR_MINUTES + 1)).time()
        self.session_end = (close + timedelta(minutes=AFTER_CLOSE_MINUTES)).time()


    # --- drive long options ---------------------------------------------------

    def _drive_tickers(self):
        return [t for t, specs in self.setups.items() if any(spec.name == DRIVE_LONG for spec in specs)]

    def _prepare_drive_trail(self, tickers=None, through_today=True):
        """Rebuild drive long tickers' wave turns from the previous session (and today's bars, `through_today`)."""
        if not self.drive_trail:
            return
        for ticker in tickers or self._drive_tickers():
            if ticker not in self._drive_tickers():
                continue
            tracker = TurnTracker(*DRIVE_TRAIL_SETTING)
            bars = self.bars[ticker].sort_index()
            previous = [d for d in sorted(set(bars.index.date)) if d < self.session][-1:]
            replay = bars[bars.index.date >= (previous[0] if previous else self.session)]
            if not through_today:
                replay = replay[replay.index.date < self.session]
            for stamp, row in replay.iterrows():
                tracker.turn(stamp, {k: float(row[k]) for k in ("open", "high", "low", "close")})
            tracker.last_time = replay.index[-1] if not replay.empty else None
            self.drive_trackers[ticker] = tracker

    def _rebuild_drive_trail(self, ticker):
        """Rebuild a ticker's turns after a backfill or an out-of-order bar, and raise open drive longs' stops to dips
        confirmed after their entry that the live path missed (one alert per trade; affects later bars only)."""
        if not self.drive_trail or ticker not in self._drive_tickers():
            return
        self._prepare_drive_trail([ticker], through_today=False)
        tracker = self.drive_trackers[ticker]
        raised = {}
        for stamp, row in self.bars[ticker].sort_index().iterrows():
            if stamp.date() != self.session:
                continue
            tracker.last_time = stamp
            turn = tracker.turn(stamp, {k: float(row[k]) for k in ("open", "high", "low", "close")})
            if turn and turn[0] == "up":
                for trade in self._open_drive_longs(ticker):
                    if trade.entry_time < stamp and turn[1] > trade.stop:
                        trade.stop = raised[id(trade)] = turn[1]
        self._alert_raised(ticker, raised, "caught up after a data gap")

    def _open_drive_longs(self, ticker):
        return [t for t in self.trades if t.ticker == ticker and t.setup in (DRIVE_LONG, DRIVE_REENTRY) and t.side == 1
                and t.status == "open" and t.stop is not None]

    def _alert_raised(self, ticker, raised, why):
        for trade in self._open_drive_longs(ticker):
            if id(trade) in raised:
                self.sink(Intent(MOVE_STOP, f"RAISE STOP {ticker} | {trade.setup} | stop {trade.stop:.2f} "
                                            f"({why})",
                                 "RAISE STOP", trade, ticker, trade.setup, trade.stop))

    def _drive_long_options(self, ticker, bar):
        """After the bar's stop checks: raise open drive longs' stops to a newly confirmed dip low (`--drive-trail`),
        and buy once back above a drive long's stop-out level (`--drive-reentry`)."""
        if bar["time"].date() != self.session:
            return
        try:
            if self.drive_trail:
                self._trail_drive_long(ticker, bar)
            if self.drive_reentry:
                self._reenter_drive_long(ticker, bar)
        except Exception:
            logger.exception("%s: drive long option failed on the %s bar", ticker, f"{bar['time']:%H:%M}")

    def _trail_drive_long(self, ticker, bar, alert=True):
        """Raise open drive longs' stops when this bar confirms a higher dip; returns {id(trade): new stop}."""
        tracker = self.drive_trackers.get(ticker)
        if tracker is None:
            return {}
        if tracker.last_time is not None and bar["time"] <= tracker.last_time:
            self._rebuild_drive_trail(ticker)
            return {}
        tracker.last_time = bar["time"]
        turn = tracker.turn(bar["time"], bar)
        if not turn or turn[0] != "up":
            return {}
        raised = {}
        for trade in self._open_drive_longs(ticker):
            if turn[1] > trade.stop:
                trade.stop = raised[id(trade)] = turn[1]
                if alert:
                    self.sink(Intent(MOVE_STOP, f"RAISE STOP {ticker} | {trade.setup} | stop {turn[1]:.2f} "
                                                "(new higher dip low)",
                                     "RAISE STOP", trade, ticker, trade.setup, turn[1]))
        return raised

    def _reenter_drive_long(self, ticker, bar):
        stamp = bar["time"]
        key = f"{ticker}|{DRIVE_REENTRY}|{self.session.isoformat()}"
        stopped = next((t for t in self.trades if t.ticker == ticker and t.setup == DRIVE_LONG and t.side == 1
                        and t.outcome == "stop" and t.entry_time.date() == self.session), None)
        if (stopped is None or key in self.alerted or stamp <= stopped.exit_time
                or stamp.time() >= DRIVE_REENTRY_LATEST or stamp.time() >= self.close_decision_bar):
            return
        level = stopped.stop
        if not bar["close"] > level:
            return
        frame = self.bars[ticker]
        low_since = float(frame[(frame.index >= stopped.exit_time) & (frame.index <= stamp)]["low"].min())
        self.alerted.add(key)
        trade = LiveTrade(ticker=ticker, setup=DRIVE_REENTRY, signal="drive_long_reentry", exit_mode="eod",
                          entry_time=stamp, side=1, entry=bar["close"], stop=low_since, target=None,
                          risk=bar["close"] - low_since, last_bar=stamp)
        self.trades.append(trade)
        self.sink(Intent(ENTER, f"BUY {ticker} | {DRIVE_REENTRY} | ~{trade.entry:.2f} ({stamp:%H:%M} bar close), "
                                f"back above the stop-out level {level:.2f} | stop {low_since:.2f} | hold to the "
                                "close",
                         "BUY", trade, ticker, DRIVE_REENTRY, trade.entry, BAR_CLOSE))

    # --- down-market shorts --------------------------------------------------

    def _prepare_shorts(self):
        """Decide today's gate, and rebuild each short ticker's retest watch from the bars so far (no alerts)."""
        if not self.short_setups or not self.short_tickers:
            return
        try:
            closes = self.daily_closes_loader([GATE_TICKER], self.session).get(GATE_TICKER, [])
            self.shorts_on, self.short_gate_text = gate_status(self.short_gate, closes)
            self.overnight_short_on, self.overnight_short_text = gate_status(self.overnight_short_gate, closes,
                                                                             "overnight short")
        except Exception:
            logger.exception("Short gate failed; short setups off today")
            self.shorts_on, self.short_gate_text = False, "short setups off: the gate's daily closes are unavailable"
            self.overnight_short_on, self.overnight_short_text = False, "overnight short off: no daily closes"
        logger.info(self.short_gate_text)
        if self.overnight_short_gate != self.short_gate and "overnight" in self.short_setups:
            logger.info(self.overnight_short_text)
        if "retest" not in self.short_setups:
            return
        for ticker in self.short_tickers:
            bars = self.bars[ticker]
            self.short_adr[ticker] = next_session_adr(bars, self.session)
            watch = RetestShort(ticker)
            previous = [d for d in sorted(set(bars.index.date)) if d < self.session][-1:]
            for stamp, row in bars[bars.index.date >= (previous[0] if previous else self.session)].iterrows():
                bar = {k: float(row[k]) for k in ("open", "high", "low", "close")}
                adr = self.short_adr[ticker] if stamp.date() == self.session else None
                watch.update(stamp, bar, adr, in_position=True)
            watch.entries = sum(1 for t in self.trades if t.ticker == ticker and t.setup == SHORT_NAMES["retest"]
                                and t.entry_time.date() == self.session)
            self.short_watches[ticker] = watch

    # --- trend filters ---------------------------------------------------------

    def _prepare_trend_filters(self):
        """Block today's filtered setups per ticker (`trend_blocked`: {ticker: {setup: reason}}) and alert the list."""
        self.trend_blocked = {}
        if not self.trend_filters:
            return
        overnight = {s.name for specs in self.setups.values() for s in specs if s.overnight}
        wanted = {}
        if "pullback" in self.trend_filters:
            for ticker, specs in self.setups.items():
                wanted.setdefault(ticker, set()).update(s.name for s in specs if s.name in PULLBACK_SETUPS)
        if "overnight" in self.trend_filters:
            for ticker, specs in self.setups.items():
                wanted.setdefault(ticker, set()).update(s.name for s in specs if s.name in overnight)
        wanted = {t: names for t, names in wanted.items() if names}
        if not wanted:
            return
        try:
            daily = self.trend_daily_loader(sorted(set(wanted) | {TREND_MARKET_TICKER}), self.session)
        except Exception:
            logger.exception("Trend filter daily bars failed")
            daily = {}
        qqq = daily.get(TREND_MARKET_TICKER)
        market = market_trend(qqq).iloc[-1] if qqq is not None and not qqq.empty else None
        lines = []
        night_ok, night_text = overnight_rule(market)
        if "overnight" in self.trend_filters:
            lines.append(f"overnight holds {'on' if night_ok else 'off'}: {night_text}")
        for ticker in sorted(wanted):
            frame = daily.get(ticker)
            trend = ticker_trend(frame).iloc[-1] if frame is not None and not frame.empty else None
            for name in sorted(wanted[ticker]):
                ok, reason = pullback_rule(trend) if name in PULLBACK_SETUPS else (night_ok, night_text)
                if not ok:
                    self.trend_blocked.setdefault(ticker, {})[name] = reason
        for ticker, blocked in sorted(self.trend_blocked.items()):
            parts = [f"{name} ({reason})" for name, reason in sorted(blocked.items()) if name not in overnight]
            if parts:
                lines.append(f"{ticker} off: {', '.join(parts)}")
        self.sink(Intent(SYSTEM, "trend filters | " + " | ".join(lines or ["every filtered setup is on"]),
                         level=logging.INFO))

    def _trend_blocked(self, ticker, setup):
        return setup in self.trend_blocked.get(ticker, {})

    def _open_short(self, ticker, setup, signal, bar_time, entry, stop, message, action="SHORT", order=BAR_CLOSE):
        trade = LiveTrade(ticker=ticker, setup=setup, signal=signal, exit_mode="eod", entry_time=bar_time, side=-1,
                          entry=entry, stop=stop, target=None, risk=None if stop is None else stop - entry,
                          last_bar=bar_time)
        self.trades.append(trade)
        self.sink(Intent(ENTER, message, action, trade, ticker, setup, entry, order))
        return trade

    def _check_shorts(self, ticker, bar):
        if not self.shorts_on or ticker not in self.short_tickers or bar["time"].date() != self.session:
            return
        try:
            if "drive" in self.short_setups:
                self._drive_short(ticker, bar)
            if "retest" in self.short_setups:
                self._retest_short(ticker, bar)
        except Exception:
            logger.exception("%s: short check failed on the %s bar", ticker, f"{bar['time']:%H:%M}")

    def _drive_short(self, ticker, bar):
        stamp, session = bar["time"], self.session.isoformat()
        name, reentry_name = SHORT_NAMES["drive"], SHORT_NAMES["drive re-entry"]
        drives = {name, CONFIG_DRIVE_SHORT}
        if stamp.time() == MARKET_OPEN:
            key = f"{ticker}|{name}|{session}"
            # a configured "drive short" setup alerts the same trade; its stop-out still gets the re-entry
            has_config_drive = any(spec.name == CONFIG_DRIVE_SHORT for spec in self.setups.get(ticker, []))
            if bar["close"] < bar["open"] and key not in self.alerted and not has_config_drive:
                self.alerted.add(key)
                self._open_short(ticker, name, "drive_short", stamp, bar["close"], bar["high"],
                                 f"SHORT {ticker} | {name} | ~{bar['close']:.2f} (09:30 bar close) | stop {bar['high']:.2f}"
                                 f" | cover at the close")
            return
        key = f"{ticker}|{reentry_name}|{session}"
        stopped = next((t for t in self.trades if t.ticker == ticker and t.setup in drives and t.side == -1
                        and t.outcome == "stop" and t.entry_time.date() == self.session), None)
        if (stopped is None or key in self.alerted or stamp <= stopped.exit_time or stamp.time() >= REENTRY_LATEST
                or stamp.time() >= self.close_decision_bar):
            return
        level = stopped.stop
        if bar["close"] < level:
            self.alerted.add(key)
            self._open_short(ticker, reentry_name, "drive_short_reentry", stamp, bar["close"], None,
                             f"SHORT {ticker} | {reentry_name} | ~{bar['close']:.2f} ({stamp:%H:%M} bar close), back "
                             f"below the stop-out level {level:.2f} | no stop | cover at the close")

    def _retest_short(self, ticker, bar):
        watch = self.short_watches.get(ticker)
        if watch is None:
            return
        stamp, name = bar["time"], SHORT_NAMES["retest"]
        mine = [t for t in self.trades if t.ticker == ticker and t.setup == name and t.entry_time.date() == self.session]
        open_trade = next((t for t in mine if t.status == "open"), None)
        had_position = open_trade is not None or any(t.exit_time == stamp for t in mine)
        last = stamp.time() >= self.last_bar or stamp.time() >= self.close_decision_bar
        for event in watch.update(stamp, bar, self.short_adr.get(ticker), had_position, last):
            if event["kind"] == "trail" and open_trade is not None and event["peak"] < open_trade.stop:
                open_trade.stop = event["peak"]
                self.sink(Intent(MOVE_STOP, f"LOWER STOP {ticker} | {name} | stop {event['peak']:.2f} (new lower "
                                            "rally high)",
                                 "LOWER STOP", open_trade, ticker, name, event["peak"]))
            elif event["kind"] == "entry":
                key = f"{ticker}|{name}|{stamp.isoformat()}"
                if key in self.alerted:
                    continue
                self.alerted.add(key)
                trade = self._open_short(ticker, name, "retest_short", stamp, event["fill"], event["stop"],
                                         f"SHORTED {ticker} | {name} | limit filled ~{event['fill']:.2f} ({stamp:%H:%M}"
                                         f" bar) | stop {event['stop']:.2f} | cover at the close",
                                         action="SHORT", order=LIMIT)
                if event["stopped"]:
                    trade.close_at(stamp, event["stop"], "stop")
                    self.sink(Intent(EXIT, f"COVER {ticker} | {name} | stop hit on the fill bar @ "
                                           f"{trade.exit_price:.2f} | {trade.pnl_pct():+.2f}%",
                                     "COVER", trade, ticker, name, trade.exit_price, STOP))
            elif event["kind"] == "arm":
                self.sink(Intent(INFO, f"SHORT LIMIT {ticker} | {name} | sell limit {event['level']:.2f} from "
                                       f"the next bar | stop {event['stop']:.2f} once filled | cancel at "
                                       f"{RETEST_CANCEL} or when replaced",
                                 "SHORT LIMIT", None, ticker, name, event["level"], LIMIT))

    def _overnight_short_entry(self, ticker):
        name = SHORT_NAMES["overnight"]
        last = self._last_close(ticker)
        bar_time = self.bars[ticker].index[-1] if not self.bars[ticker].empty else None
        key = f"{ticker}|{name}|{self.session.isoformat()}"
        if last is None or bar_time is None or bar_time.date() != self.session or key in self.alerted:
            return
        self.alerted.add(key)
        if in_earnings_window({"signal": "overnight_long", "time": bar_time}, self.windows[ticker]):
            self.sink(Intent(SKIP, f"SKIP {ticker} | {name} | earnings release before the next open",
                             "SKIP", None, ticker, name, last))
            return
        trade = LiveTrade(ticker=ticker, setup=name, signal="overnight_short", exit_mode="next open",
                          entry_time=bar_time, side=-1, entry=last, stop=None, target=None, risk=None,
                          status="pending", last_bar=bar_time)
        self.trades.append(trade)
        self.sink(Intent(ENTER, f"SHORT {ticker} | {name} | at the close (MOC), ref {last:.2f} "
                                f"({bar_time:%H:%M} bar) | cover at the next open",
                         "SHORT", trade, ticker, name, last, MOC))

    def _submit_evaluations(self, ticker, bar_time):
        frame = add_moving_averages(self.bars[ticker])
        frame = frame[frame.index >= self.window_start[ticker]]
        for spec in self.setups[ticker]:
            if spec.overnight or self._trend_blocked(ticker, spec.name):
                continue
            future = self.executor.submit(self.evaluate_fn(), (ticker, spec, frame, self.windows[ticker], bar_time))
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
            self.persist()

    def _open_trade(self, sig):
        spec = next(s for s in self.setups[sig["ticker"]] if s.name == sig["setup"])
        side = 1 if sig["signal"] in LONG_SIGNALS else -1
        trade = LiveTrade(ticker=sig["ticker"], setup=sig["setup"], signal=sig["signal"], exit_mode=spec.exit_mode,
                          entry_time=sig["time"], side=side, entry=sig["price"], stop=sig["stop"],
                          target=sig["target"], risk=sig["risk"], last_bar=sig["time"])
        self.trades.append(trade)
        action = "BUY" if side == 1 else "SHORT"
        target_text = "" if spec.exit_mode == "eod" else f", target {trade.target:.2f}"
        self.sink(Intent(ENTER, f"{action} {trade.ticker} | {trade.setup} | ~{trade.entry:.2f} "
                                f"({sig['time']:%H:%M} bar close) | stop {trade.stop:.2f}{target_text} | "
                                f"{EXIT_TEXT[spec.exit_mode]}",
                         action, trade, trade.ticker, trade.setup, trade.entry, BAR_CLOSE))

    # --- exits -----------------------------------------------------------

    def _update_trades(self, ticker, bar):
        for trade in self.trades:
            if trade.ticker != ticker or trade.status in ("closed",) or bar["time"] <= trade.last_bar:
                continue
            if trade.overnight:
                if trade.status == "pending" and bar["time"].time() == self.last_bar:
                    trade.entry, trade.peak, trade.status, trade.last_bar = bar["close"], bar["close"], "open", bar["time"]
                elif trade.status == "open" and trade.entry_time.date() < bar["time"].date():
                    outcome = "next open" if bar["time"].time() == MARKET_OPEN else "late open"
                    if outcome == "late open":
                        logger.warning("%s: first bar today is %s, not the open; overnight exit priced there",
                                       ticker, f"{bar['time']:%H:%M}")
                    trade.close_at(bar["time"], bar["open"], outcome)
                    done = "SOLD" if trade.side == 1 else "COVERED"
                    self.sink(Intent(EXIT, f"{done} {ticker} | {trade.setup} | open {trade.exit_price:.2f} | "
                                           f"{trade.pnl_pct():+.2f}% from {trade.entry:.2f}",
                                     done, trade, ticker, trade.setup, trade.exit_price, MOO, notify=False))
                continue
            if trade.status == "closing":
                trade.last_bar = bar["time"]
                if bar["time"].time() == self.last_bar:
                    trade.close_at(bar["time"], bar["close"], "close")
                continue
            outcome = trade.on_bar(bar)
            if outcome:
                action = "SELL" if trade.side == 1 else "COVER"
                self.sink(Intent(EXIT, f"{action} {ticker} | {trade.setup} | {outcome} hit on the "
                                       f"{bar['time']:%H:%M} bar @ {trade.exit_price:.2f} | "
                                       f"{trade.pnl_pct():+.2f}%",
                                 action, trade, ticker, trade.setup, trade.exit_price, EXIT_ORDERS[outcome]))
            elif bar["time"].time() == self.last_bar:
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
            self.sink(Intent(EXIT, f"{action} {trade.ticker} | {trade.setup} | at the close (MOC){pnl}",
                             action, trade, trade.ticker, trade.setup, last, MOC))
        if self.intraday_only:
            return
        for ticker, specs in self.setups.items():
            for spec in (s for s in specs if s.overnight):
                if self.half_day:
                    logger.info("%s: %s skipped on an early-close day (the backtest skips them)", ticker, spec.name)
                    continue
                if self._trend_blocked(ticker, spec.name):
                    self._skip_trend_filtered(ticker, spec)
                    continue
                if self._overnight_short_on():
                    self._skip_overnight_hold(ticker, spec)
                    continue
                self._overnight_entry(ticker, spec)
        if self._overnight_short_on():
            for ticker in self.short_tickers:
                if self.half_day:
                    logger.info("%s: short overnight skipped on an early-close day", ticker)
                    continue
                self._overnight_short_entry(ticker)

    def _overnight_short_on(self):
        separate = self.overnight_short_gate != self.short_gate
        return "overnight" in self.short_setups and (self.overnight_short_on if separate else self.shorts_on)

    def _skip_overnight_hold(self, ticker, spec):
        """On a session the overnight short is on, long overnight holds are skipped, so the monitor never alerts BUY
        and SHORT at the same close. With the overnight short off (`--short-setups drive`) the holds stay on."""
        key = f"{ticker}|{spec.name}|{self.session.isoformat()}"
        if key in self.alerted:
            return
        self.alerted.add(key)
        self.sink(Intent(SKIP, f"SKIP {ticker} | {spec.name} | the overnight short is on today "
                               f"({self.overnight_short_text})",
                         "SKIP", None, ticker, spec.name, self._last_close(ticker)))

    def _skip_trend_filtered(self, ticker, spec):
        key = f"{ticker}|{spec.name}|{self.session.isoformat()}"
        if key in self.alerted:
            return
        self.alerted.add(key)
        self.sink(Intent(SKIP, f"SKIP {ticker} | {spec.name} | trend filter: "
                               f"{self.trend_blocked[ticker][spec.name]}",
                         "SKIP", None, ticker, spec.name, self._last_close(ticker)))

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
            self.sink(Intent(SKIP, f"SKIP {ticker} | {spec.name} | earnings release before the next open",
                             "SKIP", None, ticker, spec.name, last))
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
        self.sink(Intent(ENTER, f"BUY {ticker} | {spec.name} | at the close (MOC), ref {last:.2f} "
                                f"({bar_time:%H:%M} bar) | sell at the next open",
                         "BUY", trade, ticker, spec.name, last, MOC))

    def _pre_open_alerts(self):
        before_open = self.now().time() < MARKET_OPEN
        for trade in self.trades:
            if trade.overnight and trade.status == "open" and trade.entry_time.date() < self.session:
                when = "at the open (MOO before 09:28)" if before_open else "now (monitor started after the open)"
                action, verb = ("SELL", "bought") if trade.side == 1 else ("COVER", "shorted")
                self.sink(Intent(EXIT, f"{action} {trade.ticker} | {trade.setup} | {when}, "
                                       f"{verb} {trade.entry:.2f} on {trade.entry_time:%m-%d}",
                                 action, trade, trade.ticker, trade.setup, None, MOO))

    def _catch_up_trades(self):
        """Replay today's warm-up bars through trades restored from the state file: each bar's stop checks, then
        (`--drive-trail`) its raise, as live; one RAISE STOP alert per drive long whose stop moved."""
        for ticker in self.tickers:
            raised = {}
            for stamp, row in self.bars[ticker].iterrows():
                if stamp.date() != self.session:
                    continue
                bar = {"time": stamp, "open": float(row["open"]), "high": float(row["high"]), "low": float(row["low"]),
                       "close": float(row["close"])}
                self._update_trades(ticker, bar)
                if self.drive_trail:
                    raised.update(self._trail_drive_long(ticker, bar, alert=False))
            if raised:
                self._alert_raised(ticker, raised, "caught up after a restart")

    # --- helpers ---------------------------------------------------------

    def _all_have_bar(self, bar_time):
        return all(not frame.empty and frame.index[-1].date() == self.session and frame.index[-1].time() >= bar_time
                   for frame in self.bars.values())

    def _last_close(self, ticker):
        frame = self.bars.get(ticker)
        if frame is None or frame.empty or frame.index[-1].date() != self.session:
            return None
        return float(frame["close"].iloc[-1])


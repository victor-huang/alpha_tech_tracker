"""Replay past sessions through the real wave setup monitor, offline, to prove a refactor changed nothing.

The monitor's own `run()` loop is driven on a fake clock (`time.sleep` advances it), with each cached 5-min
bar streamed as five 1-min bars carrying the bar's OHLC (the aggregator rebuilds the same bar), so the
stream callback, the 5-min aggregation, the scheduled alerts and the state file all run as in prod. The
state file carries over from session to session (overnight holds, next-morning exits); `--restart-at`
stops the monitor mid-session like a SIGTERM and starts a fresh one on the same state file.

Outputs per run folder: the alert CSVs (`wave_setup_alerts_<date>.csv`), `notifications.txt` (every
Telegram text with the fake time) and `state_<date>.json` (the state file after each session).

Setup evaluations (analyze_bars, ~0.75 s each, 12 per 5-min bar for 6 tickers) are cached on disk keyed by a
hash of their exact inputs (`--cache`, default market_data/cache/wave_monitor_replay/): a refactor that
changes what the monitor evaluates misses the cache and is evaluated again, so the cache cannot hide a
regression. `warm` fills it in parallel for the jobs a fresh 09:00 start of each session will submit.

  # 1. Bundle the data once (5-min bars, daily bars, earnings dates); needs Alpaca credentials
  python -m alpha_tech_tracker.op_momentum_strategy.analysis_scripts.wave_monitor_replay fetch \\
    --config alpha_tech_tracker/op_momentum_strategy/monitor_configs/2026-11-09_prod.json \\
    --start 2026-11-02 --end 2026-11-11 --bundle <dir>/bundle

  # 2. Fill the evaluation cache in parallel (optional; misses are evaluated during the run)
  python -m alpha_tech_tracker.op_momentum_strategy.analysis_scripts.wave_monitor_replay warm \
    --bundle <dir>/bundle --workers 8

  # 3. Replay with the monitor's flags (everything after `--` is passed to the monitor's parser)
  python -m alpha_tech_tracker.op_momentum_strategy.analysis_scripts.wave_monitor_replay run \\
    --bundle <dir>/bundle --out <dir>/prod -- --short-setups drive --short-gate qqq-ma50-down10 \\
    --trend-filters overnight

  # 4. Compare two runs file by file
  python -m alpha_tech_tracker.op_momentum_strategy.analysis_scripts.wave_monitor_replay compare <dir_a> <dir_b>
"""

import argparse
import filecmp
import hashlib
import json
import logging
import os
import pickle
import shutil
import sys
import time as time_module
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import date, datetime, time, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pandas as pd

from alpha_tech_tracker.op_momentum_strategy import wave_setup_monitor as wsm

logger = logging.getLogger(__name__)

ET = wsm.ET
DEFAULT_START_TIME = time(9, 0)
POLL_SECONDS = 30
MINUTE_BAR_DELAY_SECONDS = 2
DAILY_HISTORY_DAYS = wsm.DAILY_HISTORY_DAYS
WARMUP_CALENDAR_DAYS = wsm.WARMUP_CALENDAR_DAYS
DEFAULT_CACHE = Path(__file__).resolve().parents[3] / "market_data" / "cache" / "wave_monitor_replay"


class _Restart(KeyboardInterrupt):
    """Raised from the fake sleep to stop the monitor the way SIGTERM does (run() finishes and saves state)."""


# ---------------------------------------------------------------------------
# Bundle: the data a replay needs, saved once so replays are offline and repeatable
# ---------------------------------------------------------------------------

class Bundle:
    def __init__(self, bars, daily, releases):
        self.bars = bars
        self.daily = daily
        self.releases = releases

    @classmethod
    def load(cls, folder):
        folder = Path(folder)
        bars = {}
        for path in sorted((folder / "bars_5min").glob("*.json")):
            frame = pd.read_json(path, orient="split")
            frame.index = pd.to_datetime(frame.index, utc=True).tz_convert(ET)
            bars[path.stem] = frame
        daily = {}
        for path in sorted((folder / "daily").glob("*.json")):
            frame = pd.read_json(path, orient="split")
            frame.index = [pd.Timestamp(d).date() for d in frame.index]
            daily[path.stem] = frame
        raw = json.loads((folder / "releases.json").read_text())
        releases = {t: [datetime.fromisoformat(s) for s in stamps] for t, stamps in raw.items()}
        return cls(bars, daily, releases)

    def save(self, folder):
        folder = Path(folder)
        for name in ("bars_5min", "daily"):
            (folder / name).mkdir(parents=True, exist_ok=True)
        for ticker, frame in self.bars.items():
            frame.to_json(folder / "bars_5min" / f"{ticker}.json", orient="split", date_format="iso")
        for ticker, frame in self.daily.items():
            out = frame.copy()
            out.index = [d.isoformat() for d in out.index]
            out.to_json(folder / "daily" / f"{ticker}.json", orient="split")
        releases = {t: [s.isoformat() for s in stamps] for t, stamps in self.releases.items()}
        (folder / "releases.json").write_text(json.dumps(releases, indent=1, sort_keys=True))

    def releases_loader(self, ticker):
        return list(self.releases.get(ticker, []))

    def daily_closes_loader(self, tickers, session):
        return {t: [float(c) for d, c in self.daily[t]["close"].items() if d < session] if t in self.daily else []
                for t in tickers}

    def trend_daily_loader(self, tickers, session):
        out = {}
        for ticker in tickers:
            frame = self.daily.get(ticker)
            if frame is None:
                out[ticker] = pd.DataFrame(columns=["high", "close"], dtype=float)
                continue
            out[ticker] = frame.loc[[d < session for d in frame.index], ["high", "close"]].astype(float)
        return out

    def stats_daily_loader(self, tickers, session):
        return {t: self.daily[t]["close"][[d < session for d in self.daily[t].index]].astype(float)
                for t in tickers if t in self.daily}

    def session_bars(self, ticker, session):
        frame = self.bars.get(ticker)
        if frame is None:
            return frame
        return wsm.regular_hours(frame[frame.index.date == session])


def fetch_bundle(tickers, sessions, folder):
    from alpha_tech_tracker.op_momentum_strategy.op_momentum_backtest import fetch_bars, fetch_daily_bars

    first, last = sessions[0], sessions[-1]
    intraday = fetch_bars(tickers, first - timedelta(days=WARMUP_CALENDAR_DAYS + 1), last, allow_intraday=True)
    bars = {t: wsm.regular_hours(frame.sort_index()) for t, frame in intraday.items() if frame is not None}
    daily_raw = fetch_daily_bars(tickers, first - timedelta(days=DAILY_HISTORY_DAYS), last - timedelta(days=1))
    daily = {}
    for ticker, frame in daily_raw.items():
        columns = {c.lower(): c for c in frame.columns}
        daily[ticker] = pd.DataFrame({"high": [float(v) for v in frame[columns["high"]]],
                                      "close": [float(v) for v in frame[columns["close"]]]},
                                     index=[pd.Timestamp(d).date() for d in frame.index])
    releases = {t: wsm.load_releases(t) for t in tickers}
    bundle = Bundle(bars, daily, releases)
    bundle.save(folder)
    for ticker in tickers:
        have = sorted(set(bars[ticker].index.date)) if ticker in bars else []
        missing = [s for s in sessions if s not in have]
        print(f"{ticker:6} {len(bars.get(ticker, [])):6d} bars, {len(daily.get(ticker, [])):4d} daily"
              + (f"; MISSING sessions {', '.join(map(str, missing))}" if missing else ""))
    return bundle


# ---------------------------------------------------------------------------
# Evaluation cache
# ---------------------------------------------------------------------------

def _canonical(value):
    if isinstance(value, dict):
        return {str(k): _canonical(v) for k, v in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, (set, frozenset, list, tuple)):
        items = [_canonical(v) for v in value]
        return sorted(items, key=str) if isinstance(value, (set, frozenset)) else items
    return str(value)


def job_key(job):
    """Hash of everything an evaluate_setup job depends on."""
    ticker, spec, frame, windows, bar_time = job
    digest = hashlib.sha1()
    digest.update(json.dumps([ticker, repr(spec), _canonical(windows), bar_time.isoformat(),
                              list(map(str, frame.columns))]).encode())
    digest.update(pd.util.hash_pandas_object(frame, index=True).values.tobytes())
    return digest.hexdigest()


class EvaluationCache:
    def __init__(self, folder):
        self.folder = Path(folder)
        self.hits = 0
        self.misses = 0

    def _path(self, key):
        return self.folder / key[:2] / f"{key}.pkl"

    def get(self, key):
        try:
            return pickle.loads(self._path(key).read_bytes())
        except (OSError, pickle.UnpicklingError, EOFError):
            return None

    def put(self, key, fired):
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        temp.write_bytes(pickle.dumps(fired))
        temp.replace(path)

    def wrap(self, evaluate):
        def cached(job):
            key = job_key(job)
            fired = self.get(key)
            if fired is not None:
                self.hits += 1
                return fired
            self.misses += 1
            fired = evaluate(job)
            self.put(key, fired)
            return fired

        return cached


def predicted_jobs(bundle, setups, session):
    """The evaluate_setup jobs a monitor started at 09:00 on `session` submits, per (ticker, spec)."""
    previous = wsm.previous_trading_day(session)
    end = ET.localize(datetime.combine(previous, wsm.session_close(previous)))
    start = end - timedelta(days=WARMUP_CALENDAR_DAYS)
    for ticker, specs in setups.items():
        frame = bundle.bars.get(ticker)
        if frame is None:
            continue
        history = frame[(frame.index >= start) & (frame.index < end)]
        prior = sorted(d for d in set(history.index.date) if d < session)
        first = prior[-wsm.WARMUP_SESSIONS] if len(prior) >= wsm.WARMUP_SESSIONS else (prior[0] if prior else session)
        window_start = ET.localize(datetime.combine(first, time(0, 0)))
        windows = wsm.earnings_windows(bundle.releases_loader(ticker), prior + [session])
        today = bundle.session_bars(ticker, session)
        for spec in (s for s in specs if not s.overnight):
            yield ticker, spec, history, today, window_start, windows


def _warm_one(cache_dir, ticker, spec, history, today, window_start, windows, close_decision_bar):
    cache = EvaluationCache(cache_dir)
    bars = history
    for stamp, row in today.iterrows():
        bars = pd.concat([bars, pd.DataFrame([[float(row[c]) for c in ("open", "high", "low", "close")]],
                                             columns=["open", "high", "low", "close"],
                                             index=pd.DatetimeIndex([stamp]))])
        if stamp.time() >= close_decision_bar:
            continue
        frame = wsm.add_moving_averages(bars)
        job = (ticker, spec, frame[frame.index >= window_start], windows, stamp)
        key = job_key(job)
        if cache.get(key) is None:
            cache.put(key, wsm.evaluate_setup(job))
    return ticker, spec.name


def warm_cache(bundle, setups, sessions, cache_dir, workers, close_decision_bar=wsm.DEFAULT_CLOSE_DECISION_BAR):
    tasks = [task for session in sessions for task in predicted_jobs(bundle, setups, session)]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_warm_one, str(cache_dir), *task, close_decision_bar) for task in tasks]
        for done, future in enumerate(as_completed(futures), 1):
            future.result()
            print(f"warmed {done}/{len(futures)}", end="\r", flush=True)
    print()


# ---------------------------------------------------------------------------
# Fake clock and market data client
# ---------------------------------------------------------------------------

class FakeClock:
    def __init__(self, start):
        self.current = start

    def __call__(self):
        return self.current


class ReplayClient:
    """The market data client the monitor sees: history from the bundle, a stream fed by the replay."""

    def __init__(self, bundle):
        self.bundle = bundle
        self.callback = None
        self.tickers = []
        self.history_calls = []

    def warmup(self, tickers, start, end):
        self.history_calls.append(("warmup", tuple(tickers), start, end))
        return self._slice(tickers, start, end)

    def fetch_bars(self, tickers, start, end):
        self.history_calls.append(("fetch_bars", tuple(tickers), start, end))
        return self._slice(tickers, start, end)

    def _slice(self, tickers, start, end):
        out = {}
        for ticker in tickers:
            frame = self.bundle.bars.get(ticker)
            if frame is not None:
                out[ticker] = frame[(frame.index >= start) & (frame.index < end)]
        return out

    def subscribe_bars(self, callback, *tickers):
        self.callback = callback
        self.tickers = list(tickers)

    def start(self):
        pass

    def stop(self):
        pass

    def reconnect(self):
        pass


class SessionReplay:
    """One monitor process: from `start` until the monitor's own loop ends (or `stop_at`)."""

    def __init__(self, bundle, session, clock, client, stop_at=None):
        self.bundle = bundle
        self.session = session
        self.clock = clock
        self.client = client
        self.stop_at = stop_at
        self.minute_bars = self._minute_bars()
        self.next_index = 0

    def _minute_bars(self):
        events = []
        for ticker, frame in self.bundle.bars.items():
            bars = self.bundle.session_bars(ticker, self.session)
            for stamp, row in bars.iterrows():
                for minute in range(wsm.BAR_MINUTES):
                    at = stamp + timedelta(minutes=minute)
                    events.append((at, ticker, row))
        events.sort(key=lambda event: (event[0], event[1]))
        return events

    def sleep(self, seconds):
        target = self.clock.current + timedelta(seconds=POLL_SECONDS)
        if self.stop_at is not None and target >= self.stop_at:
            self.clock.current = self.stop_at
            raise _Restart()
        while self.next_index < len(self.minute_bars):
            at, ticker, row = self.minute_bars[self.next_index]
            delivered = at + timedelta(minutes=1, seconds=MINUTE_BAR_DELAY_SECONDS)
            if delivered > target:
                break
            self.next_index += 1
            if self.client.callback is None or ticker not in self.client.tickers:
                continue
            self.clock.current = max(self.clock.current, delivered)
            self.client.callback(SimpleNamespace(symbol=ticker, timestamp=at, open=float(row["open"]),
                                                 high=float(row["high"]), low=float(row["low"]),
                                                 close=float(row["close"])))
        self.clock.current = target


# ---------------------------------------------------------------------------
# Replay
# ---------------------------------------------------------------------------

def build_monitor(args, bundle, clock, client, out_dir, notify):
    """The monitor exactly as `wave_setup_monitor._run_monitor` builds it, with the replay's I/O."""
    setups = wsm.load_config(args.config)
    configured = set(setups)
    short_setups = [] if args.no_short_setups or args.short_gate == "off" else args.short_setups
    short_tickers = args.short_tickers or list(setups)
    for ticker in (short_tickers if short_setups else []) + wsm.open_overnight_tickers(args.state_file):
        setups.setdefault(ticker, [])
    return wsm.WaveSetupMonitor(
        setups, client, state_file=args.state_file, alerts_dir=out_dir, executor=wsm.InlineExecutor(),
        notify=notify, now=clock, releases_loader=bundle.releases_loader,
        daily_closes_loader=bundle.daily_closes_loader,
        close_decision_bar=datetime.strptime(args.close_decision_bar, "%H:%M").time(),
        reversal_patterns=[] if args.no_reversal_alerts else args.reversal_patterns,
        stats_tickers=[], stats_daily_loader=bundle.stats_daily_loader,
        short_setups=short_setups, short_gate=args.short_gate, overnight_short_gate=args.overnight_short_gate,
        short_tickers=short_tickers if short_setups else [], extra_tickers=set(setups) - configured,
        drive_trail=args.drive_trail, drive_reentry=args.drive_reentry, trend_filters=args.trend_filters,
        trend_daily_loader=bundle.trend_daily_loader)


def run_replay(bundle, sessions, monitor_argv, out_dir, restarts=(), start_time=DEFAULT_START_TIME, cache=None):
    """Replay `sessions` in order through fresh monitors sharing one state file; returns the output folder."""
    out_dir = Path(out_dir)
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    state_file = out_dir / "work" / "state.json"
    args = wsm.parse_args(["run", "--state-file", str(state_file), "--workers", "0"] + list(monitor_argv))
    notifications = []
    restarts = sorted(restarts)
    for session in sessions:
        starts = [ET.localize(datetime.combine(session, start_time))]
        starts += [r for r in restarts if r.date() == session]
        for index, start in enumerate(starts):
            stop_at = starts[index + 1] if index + 1 < len(starts) else None
            _run_process(args, bundle, session, start, stop_at, out_dir, notifications, cache)
        shutil.copyfile(state_file, out_dir / f"state_{session}.json")
    (out_dir / "notifications.txt").write_text("".join(f"{at} {message}\n" for at, message in notifications))
    shutil.rmtree(out_dir / "work")
    return out_dir


def _run_process(args, bundle, session, start, stop_at, out_dir, notifications, cache):
    clock = FakeClock(start)
    client = ReplayClient(bundle)
    replay = SessionReplay(bundle, session, clock, client, stop_at)

    def notify(message):
        notifications.append((clock.current.isoformat(timespec="seconds"), message))

    monitor = build_monitor(args, bundle, clock, client, out_dir, notify)
    notify(f"[replay] process start {start:%Y-%m-%d %H:%M}")
    evaluate = cache.wrap(wsm.evaluate_setup) if cache is not None else wsm.evaluate_setup
    with mock.patch.object(time_module, "sleep", replay.sleep), \
         mock.patch.object(wsm, "evaluate_setup", evaluate):
        try:
            monitor.run(poll_seconds=POLL_SECONDS)
        except _Restart:
            notify(f"[replay] process stop {clock.current:%Y-%m-%d %H:%M}")


def compare_runs(left, right):
    """Byte-compare every file of two run folders; returns the list of differences (empty when identical)."""
    left, right = Path(left), Path(right)
    names = sorted({p.name for p in left.iterdir()} | {p.name for p in right.iterdir()})
    problems = []
    for name in names:
        a, b = left / name, right / name
        if not a.exists() or not b.exists():
            problems.append(f"{name}: only in {left if a.exists() else right}")
        elif not filecmp.cmp(a, b, shallow=False):
            problems.append(f"{name}: differs")
    return problems


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def trading_days(start, end):
    days, day = [], start
    while day <= end:
        if wsm.is_trading_day(day):
            days.append(day)
        day += timedelta(days=1)
    return days


def parse_args(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    monitor_argv = []
    if "--" in argv:
        split = argv.index("--")
        argv, monitor_argv = argv[:split], argv[split + 1:]
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="action", required=True)
    fetch = sub.add_parser("fetch", help="Download the bars a replay needs into a bundle folder")
    fetch.add_argument("--config", required=True, help="Monitor config whose tickers are bundled")
    fetch.add_argument("--extra-tickers", nargs="*", default=[wsm.GATE_TICKER],
                       help="Also bundled (default: QQQ, the short gate and trend benchmark)")
    fetch.add_argument("--start", required=True, type=date.fromisoformat)
    fetch.add_argument("--end", required=True, type=date.fromisoformat)
    fetch.add_argument("--bundle", required=True)
    warm = sub.add_parser("warm", help="Fill the evaluation cache in parallel")
    warm.add_argument("--bundle", required=True)
    warm.add_argument("--cache", default=str(DEFAULT_CACHE))
    warm.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    run = sub.add_parser("run", help="Replay the bundle's sessions through the monitor")
    run.add_argument("--bundle", required=True)
    run.add_argument("--cache", default=str(DEFAULT_CACHE), help="Evaluation cache folder ('off' to disable)")
    run.add_argument("--out", required=True)
    run.add_argument("--start", type=date.fromisoformat, help="First session (default: the bundle's sessions.json)")
    run.add_argument("--end", type=date.fromisoformat)
    run.add_argument("--restart-at", nargs="*", default=[],
                     help="Stop and restart the monitor at these ET times (YYYY-MM-DDTHH:MM)")
    compare = sub.add_parser("compare", help="Byte-compare two replay output folders")
    compare.add_argument("left")
    compare.add_argument("right")
    args = parser.parse_args(argv)
    args.monitor_argv = monitor_argv
    return args


def main(argv=None):
    args = parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s — %(message)s")
    if args.action == "fetch":
        tickers = list(dict.fromkeys(list(wsm.load_config(args.config)) + args.extra_tickers))
        sessions = trading_days(args.start, args.end)
        Path(args.bundle).mkdir(parents=True, exist_ok=True)
        shutil.copyfile(args.config, Path(args.bundle) / "config.json")
        (Path(args.bundle) / "sessions.json").write_text(json.dumps([s.isoformat() for s in sessions]))
        fetch_bundle(tickers, sessions, args.bundle)
        return
    if args.action == "compare":
        problems = compare_runs(args.left, args.right)
        print("\n".join(problems) if problems else "identical")
        sys.exit(1 if problems else 0)
    bundle_dir = Path(args.bundle)
    sessions = [date.fromisoformat(s) for s in json.loads((bundle_dir / "sessions.json").read_text())]
    if args.action == "warm":
        warm_cache(Bundle.load(bundle_dir), wsm.load_config(bundle_dir / "config.json"), sessions, args.cache,
                   args.workers)
        return
    sessions = [s for s in sessions if (args.start is None or s >= args.start) and (args.end is None or s <= args.end)]
    monitor_argv = args.monitor_argv
    if "--config" not in monitor_argv:
        monitor_argv = ["--config", str(bundle_dir / "config.json")] + monitor_argv
    restarts = [ET.localize(datetime.fromisoformat(r)) for r in args.restart_at]
    cache = None if args.cache == "off" else EvaluationCache(args.cache)
    out = run_replay(Bundle.load(bundle_dir), sessions, monitor_argv, args.out, restarts, cache=cache)
    alerts = sum(max(0, len(p.read_text().splitlines()) - 1) for p in out.glob("wave_setup_alerts_*.csv"))
    cached = f"; evaluation cache {cache.hits} hits, {cache.misses} misses" if cache is not None else ""
    print(f"{len(sessions)} sessions replayed, {alerts} alert rows -> {out}{cached}")


if __name__ == "__main__":
    main()

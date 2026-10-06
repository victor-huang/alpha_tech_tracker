"""Earnings calendar: release times per ticker and the sessions that react to them.

Release times come from Yahoo Finance's earnings calendar page (through yfinance's session, parsed
with BeautifulSoup) and are cached per ticker in market_data/cache/earnings/<TICKER>.json for
CACHE_MAX_AGE_DAYS. Times shown in another US zone are converted to Eastern.

A release before the open moves that session; a release at or after noon moves the next
session (it lands after the close). Yahoo shows 12 AM when the time is not known, so both the
release day and the next session count as reaction sessions. The eve is the last session before
the release reaches the market: an overnight hold entered at the eve's close carries the release
gap. Eves are found from the release time itself, so a release after today's close marks today
even though the reacting session is not in the bars yet.
"""

import json
import os
import re
from datetime import date, datetime, time, timedelta
from pathlib import Path

import pandas as pd
import yfinance as yf
from bs4 import BeautifulSoup

CACHE_DIR = Path(__file__).resolve().parents[3] / "market_data" / "cache" / "earnings"
CACHE_MAX_AGE_DAYS = 7
STALE_CALENDAR_DAYS = 183
CALENDAR_URL = "https://finance.yahoo.com/calendar/earnings?symbol={ticker}&offset=0&size=100"
UNKNOWN_TIME = time(0, 0)
AFTER_CLOSE_FROM = time(12, 0)
MARKET_OPEN = time(9, 30)
HOURS_BEHIND_EASTERN = {"EST": 0, "EDT": 0, "ET": 0, "CST": 1, "CDT": 1, "CT": 1,
                        "MST": 2, "MDT": 2, "MT": 2, "PST": 3, "PDT": 3, "PT": 3}
DATE_PATTERN = re.compile(
    r"^(?P<day>\w+ \d{1,2}, \d{4})(?: at (?P<time>\d{1,2}(?::\d{2})? [AP]M)(?: (?P<zone>[A-Z]{2,4}))?)?"
)


class EarningsCalendarError(Exception):
    pass


def parse_release(text):
    """'September 1, 2026 at 4 PM EDT' -> naive Eastern datetime; None when unparseable."""
    match = DATE_PATTERN.match(text.strip())
    if not match:
        return None
    day = datetime.strptime(match.group("day"), "%B %d, %Y")
    clock = match.group("time")
    if not clock:
        return day
    clock_format = "%I:%M %p" if ":" in clock else "%I %p"
    released = datetime.combine(day.date(), datetime.strptime(clock, clock_format).time())
    zone = match.group("zone")
    if released.time() == UNKNOWN_TIME or zone is None:
        return released
    if zone not in HOURS_BEHIND_EASTERN:
        print(f"earnings calendar: unknown time zone {zone!r} in {text!r}; read as Eastern")
        return released
    return released + timedelta(hours=HOURS_BEHIND_EASTERN[zone])


def fetch_releases(ticker):
    """Release datetimes (naive Eastern) for the ticker, past and scheduled, from Yahoo.

    Raises EarningsCalendarError when the page has no earnings table, so a blocked or changed
    page is not mistaken for a ticker without releases.
    """
    response = yf.Ticker(ticker)._data.cache_get(CALENDAR_URL.format(ticker=ticker))
    table = BeautifulSoup(response.text, "html.parser").find("table")
    if table is None:
        raise EarningsCalendarError(f"no earnings table on the Yahoo page (HTTP {response.status_code})")
    header = [cell.get_text(strip=True) for cell in table.find("tr").find_all(["th", "td"])]
    if "Earnings Date" not in header:
        raise EarningsCalendarError(f"unexpected earnings table columns {header}")
    column = header.index("Earnings Date")
    releases = []
    for row in table.find_all("tr")[1:]:
        cells = [cell.get_text(strip=True) for cell in row.find_all("td")]
        released = parse_release(cells[column]) if len(cells) > column else None
        if released:
            releases.append(released)
    return sorted(set(releases))


def _read_cache(path):
    """(fetched date, releases) from the cache file, or None when missing or unreadable."""
    try:
        cached = json.loads(path.read_text())
        return date.fromisoformat(cached["fetched"]), [datetime.fromisoformat(s) for s in cached["releases"]]
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _write_cache(path, today, releases):
    """Write through a per-process temp file and rename, so parallel workers never read half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    temp.write_text(json.dumps({"fetched": today.isoformat(),
                                "releases": [stamp.isoformat() for stamp in releases]}, indent=1))
    temp.replace(path)


def load_releases(ticker, cache_dir=CACHE_DIR, today=None):
    """Cached release datetimes; refetched when the cache is older than CACHE_MAX_AGE_DAYS."""
    today = today or date.today()
    path = Path(cache_dir) / f"{ticker.upper()}.json"
    cached = _read_cache(path)
    if cached and today - cached[0] <= timedelta(days=CACHE_MAX_AGE_DAYS):
        return cached[1]
    try:
        releases = fetch_releases(ticker)
    except Exception as error:  # a calendar outage must not stop a backtest
        if cached:
            print(f"{ticker}: earnings calendar refresh failed ({error}); using the copy from {cached[0]}")
            return cached[1]
        print(f"{ticker}: earnings calendar unavailable ({error}); no earnings filter applied")
        return []
    if not any(today - timedelta(days=STALE_CALENDAR_DAYS) <= r.date() <= today for r in releases):
        print(f"{ticker}: no earnings release in the last {STALE_CALENDAR_DAYS} days on Yahoo; check the calendar")
    _write_cache(path, today, releases)
    return releases


def _eve(sessions, last_known, day, include_day):
    """Last session before `day` (or on it, with include_day), when nothing can trade in between.

    Days after the last session in the data are unknown: a weekday among them could be a session,
    so the eve only counts when the days in between are all weekends.
    """
    candidates = [s for s in sessions if s <= day] if include_day else [s for s in sessions if s < day]
    if not candidates:
        return None
    eve = candidates[-1]
    gap_end = day if include_day else day - timedelta(days=1)
    gap = [eve + timedelta(days=n) for n in range(1, (gap_end - eve).days + 1)]
    if any(d > last_known and d.weekday() < 5 for d in gap):
        return None
    return eve


def earnings_windows(releases, sessions):
    """{"reaction": sessions that react to a release, "eve": the session before each release lands}."""
    sessions = sorted(sessions)
    if not sessions:
        return {"reaction": set(), "eve": set()}
    last_known = sessions[-1]
    reacting, eves = set(), set()
    for released in releases:
        day, clock = released.date(), released.time()
        on_or_after = [s for s in sessions if s >= day]
        after = [s for s in sessions if s > day]
        if clock == UNKNOWN_TIME:
            reacting.update(on_or_after[:1] + after[:1])
            eve_options = (False, True)
        elif clock >= AFTER_CLOSE_FROM:
            reacting.update(after[:1])
            eve_options = (True,)
        else:
            reacting.update(on_or_after[:1])
            eve_options = (False,)
        for include_day in eve_options:
            eve = _eve(sessions, last_known, day, include_day)
            if eve is not None:
                eves.add(eve)
    return {"reaction": reacting, "eve": eves}


def reaction_sessions(releases, sessions):
    """Sessions whose price reacts to a release, from the trading sessions given."""
    return earnings_windows(releases, sessions)["reaction"]


def in_earnings_window(signal, windows):
    """True when the signal's trade carries an earnings reaction: an overnight hold entered on an
    eve session, or an intraday trade on a reaction session."""
    session = signal["time"].date()
    if signal["signal"] == "overnight_long":
        return session in windows["eve"]
    return session in windows["reaction"]


def ticker_earnings_windows(ticker, bars):
    """earnings_windows for a ticker over the sessions in its bars (lowercase OHLC, Eastern index)."""
    sessions = sorted(set(pd.DatetimeIndex(bars.index).date))
    return earnings_windows(load_releases(ticker), sessions)

"""Earnings calendar: release times per ticker and the sessions that react to them.

Release times come from Yahoo Finance's earnings calendar page (through yfinance's session, parsed
with BeautifulSoup) and are cached per ticker in market_data/cache/earnings/<TICKER>.json for
CACHE_MAX_AGE_DAYS.

A release before the open moves that session; a release at or after noon moves the next
session (it lands after the close). Yahoo shows 12 AM when the time is not known, so both the
release day and the next session count as reaction sessions. The session before a reaction
session is its eve: an overnight hold entered at the eve's close carries the release gap.
"""

import json
import re
from datetime import date, datetime, time, timedelta
from pathlib import Path

import pandas as pd
import yfinance as yf
from bs4 import BeautifulSoup

CACHE_DIR = Path(__file__).resolve().parents[3] / "market_data" / "cache" / "earnings"
CACHE_MAX_AGE_DAYS = 7
CALENDAR_URL = "https://finance.yahoo.com/calendar/earnings?symbol={ticker}&offset=0&size=100"
MARKET_TZ = "America/New_York"
UNKNOWN_TIME = time(0, 0)
AFTER_CLOSE_FROM = time(12, 0)
MARKET_OPEN = time(9, 30)
DATE_PATTERN = re.compile(r"^(?P<day>\w+ \d{1,2}, \d{4})(?: at (?P<time>\d{1,2}(?::\d{2})? [AP]M))?")


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
    return datetime.combine(day.date(), datetime.strptime(clock, clock_format).time())


def fetch_releases(ticker):
    """Release datetimes (naive Eastern) for the ticker, past and scheduled, from Yahoo."""
    response = yf.Ticker(ticker)._data.cache_get(CALENDAR_URL.format(ticker=ticker))
    table = BeautifulSoup(response.text, "html.parser").find("table")
    if table is None:
        return []
    header = [cell.get_text(strip=True) for cell in table.find("tr").find_all(["th", "td"])]
    column = header.index("Earnings Date")
    releases = []
    for row in table.find_all("tr")[1:]:
        cells = [cell.get_text(strip=True) for cell in row.find_all("td")]
        released = parse_release(cells[column]) if len(cells) > column else None
        if released:
            releases.append(released)
    return sorted(set(releases))


def load_releases(ticker, cache_dir=CACHE_DIR, today=None):
    """Cached release datetimes; refetched when the cache is older than CACHE_MAX_AGE_DAYS."""
    today = today or date.today()
    path = Path(cache_dir) / f"{ticker.upper()}.json"
    if path.exists():
        cached = json.loads(path.read_text())
        if today - date.fromisoformat(cached["fetched"]) <= timedelta(days=CACHE_MAX_AGE_DAYS):
            return [datetime.fromisoformat(stamp) for stamp in cached["releases"]]
    try:
        releases = fetch_releases(ticker)
    except Exception as error:  # a calendar outage must not stop a backtest
        if path.exists():
            print(f"{ticker}: earnings calendar refresh failed ({error}); using the cached copy")
            return [datetime.fromisoformat(stamp) for stamp in json.loads(path.read_text())["releases"]]
        print(f"{ticker}: earnings calendar unavailable ({error}); no earnings filter applied")
        return []
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"fetched": today.isoformat(),
                                "releases": [stamp.isoformat() for stamp in releases]}, indent=1))
    return releases


def reaction_sessions(releases, sessions):
    """Sessions whose price reacts to a release, from the sorted trading sessions given."""
    sessions = sorted(sessions)
    reacting = set()
    for released in releases:
        day, clock = released.date(), released.time()
        on_or_after = [s for s in sessions if s >= day]
        after = [s for s in sessions if s > day]
        if clock == UNKNOWN_TIME:
            reacting.update(on_or_after[:1] + after[:1])
        elif clock < MARKET_OPEN:
            reacting.update(on_or_after[:1])
        elif clock >= AFTER_CLOSE_FROM:
            reacting.update(after[:1])
        else:
            reacting.update(on_or_after[:1])
    return reacting


def earnings_windows(releases, sessions):
    """{"reaction": sessions that react to a release, "eve": the session before each of them}."""
    sessions = sorted(sessions)
    reacting = reaction_sessions(releases, sessions)
    eves = {sessions[i - 1] for i, s in enumerate(sessions) if s in reacting and i > 0}
    return {"reaction": reacting, "eve": eves}


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

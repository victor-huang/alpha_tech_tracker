---
title: 'TradeStation Live Bar Stream Integration'
slug: 'tradestation-live-bar-stream'
created: '2026-04-15'
updated: '2026-04-16'
status: 'in-progress'
stepsCompleted: [1]
tech_stack: ['python3.8', 'requests_oauthlib', 'requests', 'threading']
files_to_modify:
  - alpha_tech_tracker/trade_api/tradestation/client.py
files_to_create:
  - alpha_tech_tracker/trade_api/tradestation/bar_stream.py
  - alpha_tech_tracker/trade_api/tradestation/ts_stream_driver.py
  - tests/trade_api/tradestation/test_bar_stream.py
---

# Tech-Spec: TradeStation Live Bar Stream Integration

**Created:** 2026-04-15  
**Updated:** 2026-04-16

## Overview

### Problem Statement

The live trade engine streams 1-min bar data exclusively via Alpaca's WebSocket. The
Alpaca account only has IEX feed access (regional, ~60-70% of NBBO volume), which can
produce sparse bars for some tickers. A funded TradeStation account with SIP feed enabled
is available and provides full consolidated NBBO data at no extra cost.

### Approach (Phase 1 — Components Only)

Build and validate the TradeStation data components in isolation before wiring them into
the live trade engine. Phase 1 deliverables:

1. `get_historical_bars()` on `TradeStationAPIClient` — fetch 1-min or 5-min OHLCV bars
   for a date/time range
2. `_TSBar` dataclass — normalized bar object with the same attribute interface as Alpaca
   bar objects (`symbol`, `timestamp`, `open`, `high`, `low`, `close`, `volume`)
3. `TradeStationBarStream` — streams 1-min bars for multiple tickers via HTTP chunked
   streaming; one connection per ticker, each in a daemon thread
4. `ts_stream_driver.py` — runnable driver script that streams all default tickers and
   validates historical bar fetches; no dependency on the trade engine

Live trade engine integration (signal_engine, trade_engine, CLI flags) is deferred to
Phase 2.

### Scope

**In Scope (Phase 1):**
- `get_historical_bars()` on `TradeStationAPIClient`
- `_TSBar` dataclass and `TradeStationBarStream` class in `bar_stream.py`
- `ts_stream_driver.py` standalone driver script
- Unit tests in `tests/trade_api/tradestation/test_bar_stream.py`

**Out of Scope (Phase 2 — deferred):**
- `LiveSignalEngine` integration (`_on_one_min_bar` refactor, `data_source` branching)
- `OpMomentumTradeEngine` + `TickerSelector` threading
- `--data-source` CLI flag
- `DATA_SOURCE` constant in `config.py`
- OR catchup via TradeStation historical bars (inside signal_engine)

---

## API Reference (confirmed via live testing 2026-04-16)

### Bar Stream — `GET /v3/marketdata/stream/barcharts/{symbol}`

- **One symbol per connection** — max 1 symbol per request (confirmed `"The max symbols
  that can be requested is 1."` for comma-separated URLs)
- **17 tickers → 17 threads**, each blocking on `iter_lines()`; all I/O-bound, no GIL issue
- Heartbeat every 5 seconds: `{"Heartbeat": N, "Timestamp": "..."}`
- Bar frames have no `Symbol` field — implied by URL; must be passed in from the thread closure

**Bar frame fields (confirmed):**
```json
{
  "Open": "391.78",
  "High": "392.12",
  "Low": "391.7",
  "Close": "392.1",
  "TotalVolume": "679854",
  "TimeStamp": "2026-04-15T20:00:00Z",
  "Epoch": 1776283200000,
  "BarStatus": "Closed",
  "IsRealtime": false,
  "IsEndOfHistory": true,
  "TotalTicks": 6662,
  "DownTicks": 3408, "DownVolume": 326914,
  "UpTicks": 3254, "UpVolume": 352940,
  "UnchangedTicks": 0, "UnchangedVolume": 0,
  "OpenInterest": "0"
}
```

**Processing rule:** only call the bar callback when `BarStatus == "Closed"`. Ignore
`BarStatus == "Open"` (partial, forming bar) and heartbeat frames.

**`IsRealtime` flag:** `false` means the stream is replaying today's earlier bars first
(useful for engines starting mid-session). `true` means live data. Process all bars
regardless — the trade engine's session/timestamp guards will filter stale bars.

### Historical Bars — `GET /v3/marketdata/barcharts/{symbol}`

**Confirmed correct parameter names: `firstdate` / `lastdate`** (not `startDate`/`endDate`
— those are silently ignored and return only the last bar).

**`firstdate` is exclusive.** Bars are timestamped at their close time. The bar whose
close timestamp equals `firstdate` is excluded. To include the bar that opens at
`target_time`, pass `firstdate = target_time - 1 minute`.

| Params | Confirmed result |
|---|---|
| `interval=1, unit=Minute, firstdate, lastdate` | 1-min bars in range |
| `interval=5, unit=Minute, firstdate, lastdate` | 5-min bars in range |
| `interval=1, unit=Daily, firstdate, lastdate` | Daily bars |
| `interval=1, unit=Minute, barsback=N` | Last N bars (no date needed) |

**Response shape:**
```json
{
  "Bars": [
    {
      "Open": "366.75", "High": "366.84", "Low": "362.5", "Close": "364.37",
      "TotalVolume": "974501",
      "TimeStamp": "2026-04-15T13:31:00Z",
      "Epoch": 1776259860000,
      "BarStatus": "Closed",
      "IsRealtime": false,
      "IsEndOfHistory": false
    },
    ...
  ]
}
```

---

## Implementation Plan

### Task 1 — `_v3_base_url` on `TradeStationAPIClient` ✅ DONE

Already added in the v2→v3 migration commit. `client._v3_base_url` is set in `__init__`.

---

### Task 2 — Add `get_historical_bars()` to `TradeStationAPIClient`

**File:** `alpha_tech_tracker/trade_api/tradestation/client.py`

Add below `get_stock_quote`. Lazy-import `_TSBar` to avoid circular import:

```python
def get_historical_bars(
    self,
    symbol: str,
    start_dt,
    end_dt,
    interval: int = 1,
    unit: str = "Minute",
) -> list:
    """Fetch historical bars from TradeStation v3 /marketdata/barcharts/{symbol}.

    Returns a list of _TSBar objects ordered oldest-first.

    Args:
        symbol:   Ticker symbol (e.g. "TSLA")
        start_dt: tz-aware datetime — first bar open time to include.
                  Internally shifted back 1 minute because the API's firstdate
                  param is exclusive (bars timestamped at close time).
        end_dt:   tz-aware datetime — last bar close time to include.
        interval: Bar width (default 1 for 1-min bars; use 5 for 5-min bars).
        unit:     "Minute" (default) or "Daily".
    """
    from datetime import timedelta
    from alpha_tech_tracker.trade_api.tradestation.bar_stream import _TSBar

    # firstdate is exclusive: shift back one interval so the bar opening at
    # start_dt (closing at start_dt + interval) is included in the response.
    effective_start = start_dt - timedelta(minutes=interval)

    params = {
        "interval": interval,
        "unit": unit,
        "firstdate": effective_start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "lastdate": end_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sessiontemplate": "Default",
    }
    url = self._v3_base_url + f"/marketdata/barcharts/{symbol}"
    response = self._session.get(url, params=params)
    data = self._parse(response)
    bars_raw = data.get("Bars", []) if isinstance(data, dict) else []
    return [
        _TSBar.from_ts_dict(b, symbol)
        for b in bars_raw
        if b.get("Open")
    ]
```

---

### Task 3 — Create `bar_stream.py`

**File (new):** `alpha_tech_tracker/trade_api/tradestation/bar_stream.py`

```python
import json
import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_STREAM_URL = "https://api.tradestation.com/v3/marketdata/stream/barcharts/{symbol}"
_SIM_STREAM_URL = "https://sim-api.tradestation.com/v3/marketdata/stream/barcharts/{symbol}"


@dataclass
class _TSBar:
    symbol: str
    timestamp: datetime   # UTC-aware
    open: float
    high: float
    low: float
    close: float
    volume: float

    @classmethod
    def from_ts_dict(cls, d: dict, symbol: str) -> "_TSBar":
        """Parse a TradeStation bar dict (stream or historical) into a _TSBar."""
        raw_ts = d.get("TimeStamp") or d.get("Epoch")
        if isinstance(raw_ts, (int, float)):
            # Epoch is in milliseconds
            ts = datetime.fromtimestamp(raw_ts / 1000, tz=timezone.utc)
        else:
            ts = datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
        return cls(
            symbol=symbol,
            timestamp=ts,
            open=float(d["Open"]),
            high=float(d["High"]),
            low=float(d["Low"]),
            close=float(d["Close"]),
            volume=float(d.get("TotalVolume", 0)),
        )


class TradeStationBarStream:
    """
    Streams 1-min bars for multiple tickers via TradeStation's HTTP chunked
    streaming endpoint. One persistent connection per ticker, each in a
    daemon thread.

    Usage:
        stream = TradeStationBarStream(ts_client)
        stream.subscribe_bars(on_bar, "TSLA", "META", ...)
        stream.run()          # blocks; each thread reconnects on error
        # or:
        stream.start_async()  # starts threads and returns immediately
        ...
        stream.stop()
    """

    def __init__(self, ts_client, interval: int = 1, unit: str = "Minute"):
        self._session = ts_client._session
        self._environment = ts_client._environment
        self._interval = interval
        self._unit = unit
        self._tickers: list = []
        self._callback = None
        self._stop_event = threading.Event()
        self._threads: list = []

    def _stream_url(self, symbol: str) -> str:
        if self._environment == "sim":
            return _SIM_STREAM_URL.format(symbol=symbol)
        return _STREAM_URL.format(symbol=symbol)

    def subscribe_bars(self, callback, *tickers):
        self._callback = callback
        self._tickers = list(tickers)

    def _stream_ticker(self, symbol: str):
        url = self._stream_url(symbol)
        params = {"interval": self._interval, "unit": self._unit}
        while not self._stop_event.is_set():
            try:
                logger.info("TS stream: connecting [%s]", symbol)
                resp = self._session.get(
                    url, params=params, stream=True, timeout=30
                )
                resp.raise_for_status()
                for raw_line in resp.iter_lines():
                    if self._stop_event.is_set():
                        break
                    if not raw_line:
                        continue
                    try:
                        frame = json.loads(raw_line)
                    except (ValueError, TypeError):
                        continue
                    if "Heartbeat" in frame:
                        continue
                    if frame.get("BarStatus") != "Closed":
                        continue
                    try:
                        bar = _TSBar.from_ts_dict(frame, symbol)
                    except (KeyError, ValueError):
                        logger.warning(
                            "TS stream: malformed bar [%s]: %s", symbol, frame
                        )
                        continue
                    if self._callback:
                        self._callback(bar)
            except Exception:
                if not self._stop_event.is_set():
                    logger.exception(
                        "TS stream: error [%s] — reconnecting in 5s", symbol
                    )
                    self._stop_event.wait(5)

    def start_async(self):
        """Start one daemon thread per ticker and return immediately."""
        self._stop_event.clear()
        self._threads = []
        for ticker in self._tickers:
            t = threading.Thread(
                target=self._stream_ticker,
                args=(ticker,),
                name=f"ts-stream-{ticker}",
                daemon=True,
            )
            t.start()
            self._threads.append(t)

    def run(self):
        """Start threads and block until all finish (or stop() is called)."""
        self.start_async()
        for t in self._threads:
            t.join()

    def stop(self):
        self._stop_event.set()
```

---

### Task 4 — Create `ts_stream_driver.py`

**File (new):** `alpha_tech_tracker/trade_api/tradestation/ts_stream_driver.py`

Runnable script that:
1. Loads TradeStation auth from `config.json`
2. Fetches 1-min and 5-min historical bars for a few tickers and prints a summary
3. Starts streaming all `DEFAULT_TICKERS` and prints each closed bar as it arrives
4. Runs until Ctrl-C

```python
"""
Driver script to validate TradeStation bar stream and historical bar fetch.

Usage:
    PYTHONPATH=/path/to/repo python -m \
        alpha_tech_tracker.trade_api.tradestation.ts_stream_driver

Requires config.json with valid tradestation_session tokens.
Run tradestation_auth.py first if needed.
"""

import logging
import signal
import sys
import time
from datetime import datetime, timezone, timedelta

from alpha_tech_tracker.op_momentum_strategy.config import (
    _load_config,
    _TRADESTATION_SESSION_TOKENS,
    TRADESTATION_ENVIRONMENT,
)
from alpha_tech_tracker.op_momentum_strategy.op_momentum_selector import DEFAULT_TICKERS
from alpha_tech_tracker.trade_api.tradestation.client import TradeStationAPIClient
from alpha_tech_tracker.trade_api.tradestation.bar_stream import TradeStationBarStream

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger("ts_stream_driver")


def _build_client() -> TradeStationAPIClient:
    _load_config()
    client = TradeStationAPIClient(environment=TRADESTATION_ENVIRONMENT)
    client.restore_session(_TRADESTATION_SESSION_TOKENS)
    if not client.verify_session():
        logger.error("TradeStation session invalid — run tradestation_auth.py first")
        sys.exit(1)
    return client


def test_historical_bars(client: TradeStationAPIClient):
    """Fetch 1-min and 5-min bars for a few tickers and print a summary."""
    logger.info("=" * 60)
    logger.info("HISTORICAL BAR FETCH TEST")
    logger.info("=" * 60)

    now_utc = datetime.now(tz=timezone.utc)
    # Use yesterday's session: 13:30–16:00 UTC (09:30–12:00 ET)
    yesterday = (now_utc - timedelta(days=1)).replace(
        hour=13, minute=30, second=0, microsecond=0
    )
    end_utc = yesterday.replace(hour=16, minute=0)

    test_tickers = DEFAULT_TICKERS[:3]

    for ticker in test_tickers:
        for interval, label in [(1, "1-min"), (5, "5-min")]:
            bars = client.get_historical_bars(
                ticker, yesterday, end_utc, interval=interval
            )
            if not bars:
                logger.warning("%s %s: no bars returned", ticker, label)
                continue
            logger.info(
                "%s %s: %d bars  first=%s  last=%s  close=%.2f",
                ticker,
                label,
                len(bars),
                bars[0].timestamp.strftime("%H:%M"),
                bars[-1].timestamp.strftime("%H:%M"),
                bars[-1].close,
            )

    logger.info("")


def test_streaming(client: TradeStationAPIClient):
    """Stream 1-min bars for all default tickers, print each closed bar."""
    logger.info("=" * 60)
    logger.info("LIVE BAR STREAM TEST — tickers: %s", DEFAULT_TICKERS)
    logger.info("Press Ctrl-C to stop")
    logger.info("=" * 60)

    bar_counts: dict = {t: 0 for t in DEFAULT_TICKERS}

    def on_bar(bar):
        bar_counts[bar.symbol] = bar_counts.get(bar.symbol, 0) + 1
        logger.info(
            "BAR  %-6s  %s  O=%-8s H=%-8s L=%-8s C=%-8s  vol=%s  realtime=%s",
            bar.symbol,
            bar.timestamp.strftime("%H:%M"),
            f"{bar.open:.2f}",
            f"{bar.high:.2f}",
            f"{bar.low:.2f}",
            f"{bar.close:.2f}",
            int(bar.volume),
            "?" ,  # IsRealtime not exposed on _TSBar; visible in raw log
        )

    stream = TradeStationBarStream(client)
    stream.subscribe_bars(on_bar, *DEFAULT_TICKERS)

    def _shutdown(sig, frame):
        logger.info("Stopping stream...")
        stream.stop()
        logger.info("Bar counts: %s", dict(sorted(bar_counts.items())))
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    stream.run()


if __name__ == "__main__":
    client = _build_client()
    test_historical_bars(client)
    test_streaming(client)
```

---

### Task 5 — Unit tests for `bar_stream.py`

**File (new):** `tests/trade_api/tradestation/test_bar_stream.py`

Cover the acceptance criteria below. Use `mocker.patch` throughout — no real HTTP calls.

#### `TestTSBar`

| Test | Behavior |
|---|---|
| `test_from_ts_dict_iso_timestamp` | ISO `TimeStamp` string parsed to UTC-aware datetime |
| `test_from_ts_dict_epoch_ms` | `Epoch` integer (ms) parsed correctly |
| `test_from_ts_dict_numeric_fields` | `Open/High/Low/Close/TotalVolume` coerced to float |
| `test_from_ts_dict_symbol_stored` | `symbol` arg stored on bar |
| `test_from_ts_dict_missing_volume_defaults_zero` | missing `TotalVolume` → `volume=0.0` |

#### `TestGetHistoricalBars`

| Test | Behavior |
|---|---|
| `test_returns_list_of_ts_bars` | parses `Bars` list into `_TSBar` objects |
| `test_firstdate_shifted_back_one_interval` | `firstdate` in request is `start_dt - 1 min` |
| `test_firstdate_shifted_by_interval_for_5min` | `firstdate` shifted back 5 min for 5-min bars |
| `test_correct_url_used` | URL is `v3/marketdata/barcharts/{symbol}` |
| `test_bars_without_open_skipped` | frames missing `Open` are excluded |
| `test_empty_response_returns_empty_list` | `{"Bars": []}` → `[]` |

#### `TestTradeStationBarStream`

| Test | Behavior |
|---|---|
| `test_closed_bar_triggers_callback` | frame with `BarStatus: "Closed"` → callback called |
| `test_open_bar_does_not_trigger_callback` | `BarStatus: "Open"` → callback not called |
| `test_heartbeat_skipped` | `{"Heartbeat": 1}` frame → callback not called |
| `test_empty_line_skipped` | empty bytes line → no crash, callback not called |
| `test_malformed_json_skipped` | non-JSON bytes → no crash |
| `test_callback_receives_ts_bar` | callback arg is `_TSBar` with correct fields |
| `test_stop_event_exits_loop` | `stop()` sets event; thread exits cleanly |
| `test_one_thread_per_ticker` | `subscribe_bars(cb, "TSLA", "META")` → 2 threads started |
| `test_uses_sim_url_for_sim_environment` | `environment="sim"` → sim base URL in request |

---

## Acceptance Criteria

**AC1 — `_TSBar.from_ts_dict` parses ISO timestamp**
```
Given {"TimeStamp": "2026-04-15T13:31:00Z", "Open": "366.75", ...}
When _TSBar.from_ts_dict(d, "TSLA")
Then bar.timestamp == datetime(2026, 4, 15, 13, 31, tzinfo=timezone.utc)
And bar.open == 366.75, bar.symbol == "TSLA"
```

**AC2 — `_TSBar.from_ts_dict` parses Epoch (ms)**
```
Given {"Epoch": 1776259860000, "Open": "366.75", ...}  (no TimeStamp)
When _TSBar.from_ts_dict(d, "TSLA")
Then bar.timestamp == datetime(2026, 4, 15, 13, 31, tzinfo=timezone.utc)
```

**AC3 — `get_historical_bars` shifts firstdate back by interval**
```
Given start_dt = 2026-04-15T13:30:00Z, interval=1
When get_historical_bars("TSLA", start_dt, end_dt, interval=1)
Then the firstdate param sent to the API is "2026-04-15T13:29:00Z"
```

**AC4 — `get_historical_bars` shifts by interval for 5-min bars**
```
Given start_dt = 2026-04-15T13:30:00Z, interval=5
When get_historical_bars("TSLA", start_dt, end_dt, interval=5)
Then the firstdate param sent to the API is "2026-04-15T13:25:00Z"
```

**AC5 — Stream: only closed bars trigger callback**
```
Given mocked iter_lines returning:
  b'{"Open":"100","High":"101","Low":"99","Close":"100.5","TotalVolume":"500","TimeStamp":"2026-01-01T14:30:00Z","BarStatus":"Closed"}'
  b'{"Open":"100","High":"101","Low":"99","Close":"100.5","TotalVolume":"500","TimeStamp":"2026-01-01T14:31:00Z","BarStatus":"Open"}'
  b'{"Heartbeat":1,"Timestamp":"2026-01-01T14:31:05Z"}'
When stream runs for ticker "TSLA"
Then callback called exactly once (for the Closed bar only)
```

**AC6 — Stream: stop() terminates cleanly**
```
Given a running stream with stop_event not set
When stop() is called
Then stop_event is set and _stream_ticker loop exits without error
```

**AC7 — Driver: historical bars run without error**
```
Given valid TradeStation session in config.json
When ts_stream_driver.test_historical_bars(client) is called
Then 1-min and 5-min bars are fetched for the first 3 DEFAULT_TICKERS
And each result has len > 0 and bars[0].timestamp < bars[-1].timestamp
```

**AC8 — Driver: stream starts for all DEFAULT_TICKERS**
```
Given valid TradeStation session
When ts_stream_driver.test_streaming(client) starts
Then 17 daemon threads named ts-stream-{ticker} are created
And first bar for each ticker is logged within 2 minutes of market open
```

---

## Notes

- **No circular import**: `get_historical_bars` lazy-imports `_TSBar` from `bar_stream.py`
  to avoid a circular dependency between `client.py` and `bar_stream.py`.
- **Token refresh during streaming**: `OAuth2Session` auto-refreshes via `auto_refresh_url`.
  If refresh fails mid-stream the connection may drop with 401 — the `_stream_ticker`
  reconnect loop handles this (catches all exceptions, waits 5s, reconnects).
- **`IsRealtime` on stream start**: the stream replays today's history first
  (`IsRealtime: false`), then transitions to live data. All bars are delivered to the
  callback regardless — useful for mid-day engine starts.
- **Thread naming**: threads are named `ts-stream-{ticker}` — visible in `threading.enumerate()`
  for debugging.

---

## Phase 2 — Live Engine Integration (deferred)

Once Phase 1 components are validated, Phase 2 will add:

1. Extract `_on_one_min_bar` sync method from `LiveSignalEngine._handle_bar`
2. Branch `start()` / `reconnect()` on `data_source` param
3. `_fetch_catchup_bars_tradestation()` for OR catchup
4. Thread `data_source` + `ts_client` through `OpMomentumTradeEngine` + `TickerSelector`
5. `--data-source alpaca|tradestation` CLI flag
6. `DATA_SOURCE = "alpaca"` constant in `config.py`

**OR catchup note (from API testing):** `_fetch_catchup_bars_tradestation` must call
`get_historical_bars(ticker, or_start, or_end, interval=5)`. The 1-minute `firstdate`
back-shift is already handled inside `get_historical_bars` — callers pass the true OR
start time unchanged.

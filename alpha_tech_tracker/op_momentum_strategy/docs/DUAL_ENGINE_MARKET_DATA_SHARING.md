# Dual-Engine Market Data Sharing

Plan for running two trade engine processes in separate folders — one trading stock,
one trading options — both receiving the same TradeStation bar stream.

---

## Problem Statement

The current architecture assumes one `OpMomentumTradeEngine` process per host. Each
process instantiates its own `TradeStationMarketDataClient`, which opens one persistent
HTTP chunked connection per ticker (one daemon thread per ticker in
`TradeStationBarStream._stream_ticker`). Running two engines naively doubles the
connection count and introduces an OAuth token refresh race.

---

## Two Options

### Option A — Independent Streams Per Process

Each engine runs its own `TradeStationMarketDataClient` independently. The only code
change needed is a file lock around `_save_tradestation_session_tokens` so concurrent
auto-refreshes don't corrupt the shared token file.

```
[Stock engine process]              [Options engine process]
TradeStationBarStream               TradeStationBarStream
(17 HTTP threads)                   (17 HTTP threads)
     |                                     |
  shared token file ── file lock ── shared token file
```

**Pros**
- Minimal code change (one file lock)
- Each engine is fully self-contained
- Independent restarts — one crash doesn't affect the other

**Cons**
- 2× HTTP connections to TS per ticker (34 threads for 17 tickers)
- Token file contention under refresh storms (mitigated by lock, but not eliminated)

---

### Option B — Bar Broadcaster via Unix Domain Socket (Selected)

A thin feeder process holds the single `TradeStationBarStream` and fans bars out to
both engines over a Unix domain socket. Each engine uses a new
`LocalTSBroadcastMarketDataClient` that connects to the socket instead of opening
its own TS stream.

```
[bar_broadcaster process]
  TradeStationBarStream (17 HTTP threads, sole TS session owner)
         |
  Unix domain socket server  /tmp/ts_bar_feed.sock
         |  (newline-delimited JSON, fan-out to all connected clients)
    ┌────┴────────────────────────┐
    ▼                             ▼
[stock engine]            [options engine]
LocalTSBroadcast          LocalTSBroadcast
MarketDataClient          MarketDataClient
(socket client)           (socket client)
      |                         |
LiveSignalEngine          LiveSignalEngine
      |                         |
 stock trades             options trades
```

`LocalTSBroadcastMarketDataClient` implements the existing `MarketDataClient` ABC:

- `subscribe_bars(callback, *tickers)` — stores callback + ticker filter
- `start()` — connects to Unix socket, spawns reader thread
- `warmup()` / `fetch_bars()` — call TS REST API directly (historical, no conflict)
- `reconnect()` / `stop()` — disconnect and reconnect to the socket

No changes needed to `signal_engine.py`, `trade_engine.py`, or `position_monitor.py`.
The new client plugs in via the existing `--market-data-source` CLI flag.

**Pros**
- Single TS connection regardless of how many engines run
- No token refresh race (feeder is sole session owner)
- Zero external dependencies — Unix socket is built into the OS
- Sub-millisecond fan-out latency (acceptable for 5-min bar strategy)
- Can migrate to Redis later by swapping only the transport layer

**Cons**
- Feeder process is a new component to monitor and restart on crash
- Engines cannot receive bars if the feeder is down (no independent fallback)

---

## Decision

**Implement Option B with a Unix domain socket.** Redis can be substituted later
by swapping the transport in `BarBroadcaster` and `LocalTSBroadcastMarketDataClient`
without touching any engine code.

---

## Implementation Plan

### Files to Create

| File | Purpose |
|---|---|
| `alpha_tech_tracker/op_momentum_strategy/bar_broadcaster.py` | Feeder process: TS stream → Unix socket server |
| `alpha_tech_tracker/trade_api/local_ts_broadcast/market_data_client.py` | `LocalTSBroadcastMarketDataClient` — socket client implementing `MarketDataClient` ABC |
| `alpha_tech_tracker/trade_api/local_ts_broadcast/__init__.py` | Package init |
| `tests/op_momentum_trade_engine/test_bar_broadcaster.py` | Unit tests for broadcaster fan-out and heartbeat |
| `tests/trade_api/local_ts_broadcast/test_market_data_client.py` | Unit tests for socket client |

### Files to Modify

| File | Change |
|---|---|
| `alpha_tech_tracker/op_momentum_strategy/op_momentum_trade_engine.py` | Add `local_ts_broadcast` to `--market-data-source` choices |
| `alpha_tech_tracker/op_momentum_strategy/trade_engine.py` | Construct `LocalTSBroadcastMarketDataClient` when source is `local_ts_broadcast` |

---

### Step 1 — Socket Protocol

All messages are newline-delimited JSON (`\n` terminated) sent over a
`SOCK_STREAM` Unix domain socket. Two message types:

**Bar message** — emitted on every closed 1-min bar:
```json
{"type": "bar", "symbol": "AMD", "timestamp": "2026-05-02T09:31:00-04:00", "open": 100.25, "high": 101.00, "low": 100.10, "close": 100.80, "volume": 42381}
```

**Heartbeat message** — emitted every 30 seconds even when no bars arrive
(pre-market, lunch, gaps):
```json
{"type": "heartbeat", "ts": "2026-05-02T09:31:30-04:00"}
```

Fields match `_TSBar` exactly. `timestamp` is ISO-8601 with UTC offset.
Unix socket (`SOCK_STREAM`) provides TCP-like reliability — no partial
writes, no dropped messages between connected clients.

---

### Step 2 — `BarBroadcaster` Daemon (`bar_broadcaster.py`)

```python
SOCKET_PATH = "/tmp/ts_bar_feed.sock"
HEARTBEAT_INTERVAL = 30  # seconds

class BarBroadcaster:
    def __init__(self, ts_client, tickers: list, socket_path: str = SOCKET_PATH):
        self._ts_client = ts_client
        self._tickers = tickers
        self._socket_path = socket_path
        self._clients: list = []          # connected client sockets
        self._clients_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._server_sock = None
        self._stream: TradeStationBarStream = None
```

**`start()`**
1. Remove stale socket file if it exists (`os.unlink`)
2. Create `socket.AF_UNIX / SOCK_STREAM` server, bind to `socket_path`, `listen()`
3. Spawn `_accept_loop` daemon thread (accepts new client connections forever)
4. Spawn `_heartbeat_loop` daemon thread (sends heartbeat every 30s)
5. Create `TradeStationBarStream`, `subscribe_bars(self._on_bar, *tickers)`, `run()`
   (blocks — call `start()` from the main thread; `_accept_loop` runs concurrently)

**`_accept_loop()`**
- Loops `server_sock.accept()` in a daemon thread
- Appends each new client socket to `self._clients` under the lock
- Logs the new connection

**`_on_bar(bar)`** — called by `TradeStationBarStream` on each closed 1-min bar
- Serializes bar to JSON line
- Calls `_broadcast(line)`

**`_broadcast(line: str)`**
- Iterates over `self._clients` under the lock
- Calls `sock.sendall(line.encode())` for each
- On `OSError` (broken pipe / disconnected client): removes from list, closes socket
- Thread-safe: copy the list before iterating, then remove dead sockets after

**`_heartbeat_loop()`**
- Sleeps 30s, then calls `_broadcast` with a heartbeat JSON line
- Exits when `_stop_event` is set

**`stop()`**
- Sets `_stop_event`
- Calls `_stream.stop()`
- Closes all client sockets and the server socket
- Removes the socket file

**Broadcaster ownership: independent daemon**

The broadcaster is its own daemon — not owned by either engine. It starts first and
stays up as long as both engines are running. If it crashes, both engines detect a
stale heartbeat and alert via Telegram, but neither tries to restart it.

This mirrors the trade engine's `run/start/stop/status/restart` pattern. The
broadcaster uses the same double-fork `_daemonize()` and PID-file helpers from
`op_momentum_trade_engine.py`.

**PID and log files**
```
logs/bar_broadcaster.pid
logs/bar_broadcaster_YYYY-MM-DD.log   (rotated at midnight, kept 30 days)
```

**CLI — same action interface as the trade engine**
```bash
# Foreground (dev / debug)
python -m alpha_tech_tracker.op_momentum_strategy.bar_broadcaster run \
  --tickers AMD META PLTR ... \
  [--socket-path /tmp/ts_bar_feed.sock] \
  [--log-level INFO]

# Background daemon
python -m alpha_tech_tracker.op_momentum_strategy.bar_broadcaster start \
  --tickers AMD META PLTR ...

python -m alpha_tech_tracker.op_momentum_strategy.bar_broadcaster stop
python -m alpha_tech_tracker.op_momentum_strategy.bar_broadcaster status
python -m alpha_tech_tracker.op_momentum_strategy.bar_broadcaster restart \
  --tickers AMD META PLTR ...
```

`start` double-forks and exits immediately; the daemon writes its PID to
`logs/bar_broadcaster.pid` and logs to the dated log file.

`stop` reads the PID file, sends `SIGTERM`, polls until exit, then force-kills
with `SIGKILL` after 10 seconds — same as `_daemon_stop()` in the trade engine.

`status` prints `Running (PID N)` or `Not running`.

`restart` calls `stop` then `start`.

**Session restore**

Restores the TS session from `tradestation_tokens.json`. Sole writer to the token
file — no lock needed since neither engine writes to it when using
`local_ts_broadcast`.

---

### Step 3 — `LocalTSBroadcastMarketDataClient`
(`trade_api/local_ts_broadcast/market_data_client.py`)

```python
class LocalTSBroadcastMarketDataClient(MarketDataClient):
    def __init__(self, ts_client, socket_path: str = SOCKET_PATH):
        self._ts_client = ts_client      # TradeStationAPIClient — for warmup/fetch_bars
        self._socket_path = socket_path
        self._callback = None
        self._tickers: list = []
        self._sock = None
        self._reader_thread = None
        self._stop_event = threading.Event()
```

**`warmup(tickers, start_dt, end_dt) → dict`**
- Delegates directly to `TradeStationMarketDataClient(self._ts_client).warmup(...)`
- No socket involvement — pure REST call

**`fetch_bars(tickers, start_dt, end_dt) → dict`**
- Same delegation pattern as `warmup()`

**`subscribe_bars(callback, *tickers)`**
- Stores `callback` and `tickers` list; no socket interaction yet

**`start()`**
1. Connect `socket.AF_UNIX / SOCK_STREAM` to `self._socket_path`
2. Clear `_stop_event`
3. Spawn `_reader_loop` daemon thread

**`_reader_loop()`**
- Reads from socket using a `makefile('r')` buffered reader (handles partial lines)
- On each line:
  - Parses JSON
  - If `type == "heartbeat"`: updates `_last_heartbeat_at`, continues
  - If `type == "bar"`:
    - Checks `symbol` is in `self._tickers`; skips if not
    - Reconstructs a `_TSBar` from the JSON fields
    - Calls `self._callback(bar)`
- On `OSError` or empty read (server closed): logs warning, exits loop
- Respects `_stop_event`

**`reconnect()`**
- Calls `stop()`, then `start()`

**`stop()`**
- Sets `_stop_event`
- Closes `self._sock`
- Joins reader thread with a short timeout

**Heartbeat staleness** (optional helper for the engine watchdog):
```python
def seconds_since_heartbeat(self) -> float:
    # Returns elapsed seconds since last heartbeat or bar received
    # Used by trade_engine watchdog alongside _last_bar_received_at
```

---

### Step 4 — Feature Flag: Switching Between Market Data Sources

The `--market-data-source` CLI flag already switches between `alpaca` and `tradestation`.
Adding `local_ts_broadcast` makes it a three-way switch:

| `--market-data-source` | What connects | Use case |
|---|---|---|
| `alpaca` (default) | `AlpacaMarketDataClient` → Alpaca WebSocket | Single engine, Alpaca feed |
| `tradestation` | `TradeStationMarketDataClient` → TS HTTP stream | Single engine, TS feed |
| `local_ts_broadcast` | `LocalTSBroadcastMarketDataClient` → Unix socket | Two engines sharing one TS stream |

**Two ways to set it — CLI flag or `config.json`:**

```bash
# CLI flag (overrides config.json)
python -m alpha_tech_tracker.op_momentum_strategy.op_momentum_trade_engine run \
  --market-data-source local_ts_broadcast \
  --window M1 09:30 3 ...

# Or set it persistently in each engine folder's config.json:
# {
#   "market_data_source": "local_ts_broadcast",
#   "execution_broker": "alpaca"
# }
# Then run without the flag:
python -m alpha_tech_tracker.op_momentum_strategy.op_momentum_trade_engine run \
  --window M1 09:30 3 ...
```

`config.json` acts as the persistent feature flag — set it once per engine folder and
forget. The CLI flag overrides `config.json` when supplied, matching the existing
`execution_broker` pattern.

**`op_momentum_trade_engine.py` — extend the `--market-data-source` argument:**

```python
parser.add_argument(
    "--market-data-source",
    choices=["alpaca", "tradestation", "local_ts_broadcast"],
    default=None,                       # None → fall through to config.json, then "alpaca"
    dest="market_data_source",
    help=(
        "Market data source for live bar streaming and warmup (default: alpaca). "
        "'tradestation' — direct TS HTTP stream, requires valid TS session tokens. "
        "'local_ts_broadcast' — connect to bar_broadcaster Unix socket; requires "
        "bar_broadcaster.py running on /tmp/ts_bar_feed.sock. "
        "Can also be set via 'market_data_source' in config.json."
    ),
)
```

**`op_momentum_trade_engine.py` — resolution order in `_build_market_data_client`:**

```python
def _build_market_data_client(args):
    """Return a MarketDataClient, or None to fall back to AlpacaMarketDataClient."""
    # CLI flag takes precedence; then config.json; then default "alpaca"
    source = getattr(args, "market_data_source", None)
    if source is None:
        from alpha_tech_tracker.op_momentum_strategy.config import _load_config, CONFIG
        _load_config()
        source = CONFIG.get("market_data_source", "alpaca")

    if source == "tradestation":
        # (existing tradestation block — unchanged)
        ...
        return TradeStationMarketDataClient(ts_client)

    if source == "local_ts_broadcast":
        from alpha_tech_tracker.op_momentum_strategy.config import (
            _load_config,
            _TRADESTATION_SESSION_TOKENS,
            TRADESTATION_ENVIRONMENT,
        )
        from alpha_tech_tracker.trade_api.tradestation.client import TradeStationAPIClient
        from alpha_tech_tracker.trade_api.local_ts_broadcast.market_data_client import (
            LocalTSBroadcastMarketDataClient,
        )
        _load_config()
        ts_client = TradeStationAPIClient(environment=TRADESTATION_ENVIRONMENT)
        ts_client.restore_session(_TRADESTATION_SESSION_TOKENS)
        socket_path = CONFIG.get("ts_broadcast_socket_path", "/tmp/ts_bar_feed.sock")
        logger.info(
            "Market data source: local_ts_broadcast (socket=%s)", socket_path
        )
        return LocalTSBroadcastMarketDataClient(ts_client, socket_path=socket_path)

    return None  # caller defaults to AlpacaMarketDataClient
```

`ts_client` is still passed into `LocalTSBroadcastMarketDataClient` so that
`warmup()` and `fetch_bars()` can call the TS REST API for historical bars. The
session does not need to be verified here — the feeder owns token refresh, and the
REST calls will use the current file-resident token.

**Optional `config.json` fields:**

```json
{
  "market_data_source": "local_ts_broadcast",
  "ts_broadcast_socket_path": "/tmp/ts_bar_feed.sock",
  "execution_broker": "alpaca"
}
```

`ts_broadcast_socket_path` is optional — defaults to `/tmp/ts_bar_feed.sock` when
absent. Override it if multiple feeder instances run on the same host (e.g., one for
V3 tickers and one for AT tickers).

---

### Step 5 — Feeder Monitoring

The engine watchdog in `trade_engine.py` already tracks `_last_bar_received_at`.
With the broadcaster, bar delivery stops if the feeder crashes. The watchdog should:

1. Check `seconds_since_heartbeat()` on `LocalTSBroadcastMarketDataClient`
2. If > 2 minutes during market hours → log error + send Telegram alert
3. Attempt `reconnect()` in case the feeder restarted — the socket will be
   available again once the feeder is back up
4. If reconnect fails → log alert (feeder is down); engine continues holding
   existing positions under position monitor control

---

### Step 6 — Tests

**`test_bar_broadcaster.py`**

| Test | What it covers |
|---|---|
| `test_fan_out_to_multiple_clients` | Two sockets connected; one bar published; both receive it |
| `test_disconnected_client_removed` | Client disconnects; next broadcast removes it silently |
| `test_heartbeat_sent_on_interval` | Heartbeat arrives within 30s window |
| `test_stale_socket_file_removed_on_start` | Leftover socket file from prior run is cleaned up |

**`test_market_data_client.py`**

| Test | What it covers |
|---|---|
| `test_callback_called_for_subscribed_ticker` | Bar for subscribed ticker triggers callback |
| `test_callback_not_called_for_other_ticker` | Bar for non-subscribed ticker is filtered |
| `test_heartbeat_does_not_trigger_callback` | Heartbeat message does not call bar callback |
| `test_reconnect_re_reads_after_server_restart` | stop + start reconnects cleanly |
| `test_warmup_delegates_to_ts_client` | `warmup()` calls underlying TS client |

---

## Folder Layout for Two Live Engines

```
/home/ec2-user/
  alpha_tech_tracker_stock_engine/      ← stock engine folder
    config.json                           ("market_data_source": "local_ts_broadcast")
    logs/
      bar_broadcaster.pid               ← broadcaster PID (shared, lives here)
      bar_broadcaster_YYYY-MM-DD.log
    state/

  alpha_tech_tracker_options_engine/    ← options engine folder
    config.json                           ("market_data_source": "local_ts_broadcast")
    logs/
    state/
```

The broadcaster PID file and logs live in whichever folder you treat as the primary
(stock engine here). Both `config.json` files point to the same socket path.

---

## Startup Order

The broadcaster must be running before the engines connect. Engines wait with
backoff on `start()` if the socket isn't available yet (see Step 3 above).

**First time only — authorize TradeStation:**
```bash
cd alpha_tech_tracker_stock_engine
python -m alpha_tech_tracker.op_momentum_strategy.tradestation_auth
```

**Daily startup (before market open):**
```bash
# 1. Start broadcaster daemon first
cd alpha_tech_tracker_stock_engine
python -m alpha_tech_tracker.op_momentum_strategy.bar_broadcaster start \
  --tickers SNDK APP SHOP CVNA AMD META EXPE RH FN MU CRDO PLTR COIN CLS MSTR CRWV MRVL

python -m alpha_tech_tracker.op_momentum_strategy.bar_broadcaster status
# → Running (PID 12345)

# 2. Start stock engine
cd alpha_tech_tracker_stock_engine
python -m alpha_tech_tracker.op_momentum_strategy.op_momentum_trade_engine start \
  --window M1 09:30 3 --window A1 13:15 1 --window A2 15:00 1 --morning-split 100

# 3. Start options engine
cd alpha_tech_tracker_options_engine
python -m alpha_tech_tracker.op_momentum_strategy.op_momentum_trade_engine start \
  --window M1 09:30 3 --window A1 13:15 1 --window A2 15:00 1 --morning-split 100
```

**Daily shutdown (after market close):**
```bash
# Stop engines first, then broadcaster
cd alpha_tech_tracker_stock_engine
python -m alpha_tech_tracker.op_momentum_strategy.op_momentum_trade_engine stop

cd alpha_tech_tracker_options_engine
python -m alpha_tech_tracker.op_momentum_strategy.op_momentum_trade_engine stop

cd alpha_tech_tracker_stock_engine
python -m alpha_tech_tracker.op_momentum_strategy.bar_broadcaster stop
```

**If the broadcaster crashes mid-session:**
```bash
cd alpha_tech_tracker_stock_engine
python -m alpha_tech_tracker.op_momentum_strategy.bar_broadcaster restart \
  --tickers SNDK APP SHOP CVNA AMD META EXPE RH FN MU CRDO PLTR COIN CLS MSTR CRWV MRVL
# Engines reconnect automatically once the socket is available again
```

---

## Token Ownership

The feeder process is the **sole owner** of the TradeStation session:
- Runs `tradestation_auth.py` once to authorize and save the token
- Auto-refreshes the token via `requests-oauthlib`; only it writes to the token file
- Both engines use `LocalTSBroadcastMarketDataClient` for live bars (no TS session
  needed for the socket)
- `warmup()` and `fetch_bars()` in each engine call TS REST using the same token file
  in **read-only** mode — refreshes only happen in the feeder, eliminating the race

---

## Migration Path to Redis

When Redis becomes available, only two files change:

1. `bar_broadcaster.py`: replace the `socket.AF_UNIX` server with `redis.publish()`
2. `local_ts_broadcast/market_data_client.py`: replace socket reader with
   `redis.subscribe()` + blocking `listen()`

All engine code, `MarketDataClient` ABC, CLI flags, and tests remain unchanged.

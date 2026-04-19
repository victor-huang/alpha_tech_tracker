# TradeStation Market Data Integration Plan

**Created:** 2026-04-18  
**Branch:** `open_market_momentum_stategy`  
**Goal:** Allow the live trade engine to use TradeStation's WebSocket bar stream as an
alternative to Alpaca for market data (warmup, live bars, OR catchup). Execution broker
(order placement, quotes) remains independently configurable.

---

## Background

`LiveSignalEngine` currently hard-wires Alpaca SDK objects (`StockDataStream`,
`StockHistoricalDataClient`) throughout `signal_engine.py` and `trade_engine.py`.
All signal logic is data-source agnostic — the coupling is purely at the I/O boundary.

TradeStation primitives already exist and are proven working:
- `TradeStationBarStream` — HTTP chunked 1-min streaming, one thread/ticker, sync callback
- `TradeStationAPIClient.get_historical_bars()` — REST bar fetch for warmup and catchup
- `_TSBar` dataclass — compatible field shape with what `_append_bar()` consumes
- `record_ts_feed.py` / `TsBarRecorder` — end-to-end proof that TS bar stream works

---

## Architecture

```
OpMomentumTradeEngine
    ├── MarketDataClient (new abstract interface)
    │   ├── warmup(tickers, start_dt, end_dt) → dict[str, pd.DataFrame]
    │   ├── fetch_bars(tickers, start_dt, end_dt) → dict[str, pd.DataFrame]
    │   ├── subscribe_bars(callback, *tickers)
    │   ├── start()
    │   ├── reconnect()
    │   └── stop()
    │   ├─ impl: AlpacaMarketDataClient   (extract from LiveSignalEngine)
    │   └─ impl: TradeStationMarketDataClient (new, wraps TradeStationBarStream)
    │
    └── ExecutionClient (existing abstract interface — unchanged)
        ├─ impl: AlpacaAPIClient
        └─ impl: TradeStationAPIClient
```

**Key principle:** `MarketDataClient` and `ExecutionClient` are independently injectable.
You can run TS data + Alpaca execution, or Alpaca data + TS execution, or any combo.

---

## Implementation Phases

### Phase 1 — `MarketDataClient` abstract interface
**File:** `alpha_tech_tracker/trade_api/market_data_client.py` *(new)*

Defines the contract that `LiveSignalEngine` depends on:

```python
class MarketDataClient(ABC):
    def warmup(self, tickers, start_dt, end_dt) -> dict: ...
    def fetch_bars(self, tickers, start_dt, end_dt) -> dict: ...
    def subscribe_bars(self, callback, *tickers): ...
    def start(self): ...
    def reconnect(self): ...
    def stop(self): ...
```

Callback contract: `callback(bar)` where `bar` has `.symbol` (str), `.timestamp`
(tz-aware datetime), `.open/.high/.low/.close/.volume` (float). Both Alpaca bar objects
and `_TSBar` satisfy this contract.

**Status:** [x] Completed

---

### Phase 2 — `AlpacaMarketDataClient`
**File:** `alpha_tech_tracker/trade_api/alpaca_client/market_data_client.py` *(new)*

Extract all Alpaca-specific I/O from `LiveSignalEngine` into this class:

| Method | Extracted from |
|---|---|
| `warmup()` | `LiveSignalEngine._warmup()` — `StockHistoricalDataClient` REST call |
| `fetch_bars()` | `_catch_up_opening_bars_for_window()` — second Alpaca REST call |
| `subscribe_bars()` + `start()` | `LiveSignalEngine.start()` — `StockDataStream` setup |
| `reconnect()` | `LiveSignalEngine.reconnect()` |
| `stop()` | `LiveSignalEngine.stop()` |

**Async bridge:** Alpaca SDK requires `async def` bar handlers. `AlpacaMarketDataClient`
registers an `async def _alpaca_handler(bar)` internally that calls the sync callback
passed by `LiveSignalEngine`. The engine body stays fully sync.

Constructor: `AlpacaMarketDataClient(api_key, secret_key, feed: DataFeed)`

**Status:** [x] Completed

---

### Phase 3 — `TradeStationMarketDataClient`
**File:** `alpha_tech_tracker/trade_api/tradestation/market_data_client.py` *(new)*

Wraps `TradeStationBarStream` and `TradeStationAPIClient.get_historical_bars()`:

```
warmup()      → get_historical_bars() per ticker → DataFrame dict (same shape as Alpaca)
fetch_bars()  → same, narrower date range (used for OR catchup)
subscribe_bars() / start() / stop() / reconnect() → TradeStationBarStream (already works)
```

**Bar format note:** `_TSBar` fields are already floats. `_append_bar()` in
`LiveSignalEngine` calls `float(bar.open)` etc. — TS bars pass through unchanged.

The 1-min bars are aggregated to 5-min by the existing `_minute_buf` / `_aggregate_bars()`
logic in `LiveSignalEngine` — no changes needed there.

Constructor: `TradeStationMarketDataClient(ts_client: TradeStationAPIClient)`

**Status:** [x] Completed

---

### Phase 4 — Refactor `LiveSignalEngine`
**File:** `alpha_tech_tracker/op_momentum_strategy/signal_engine.py` *(modify)*

Replace Alpaca-specific constructor params and I/O calls with `MarketDataClient`:

**Constructor changes:**
- Remove: `api_key`, `secret_key`, `alpaca_feed`
- Add: `market_data_client: MarketDataClient`
- Keep all other params unchanged (windows, bar_recorder, etc.)

**Method changes:**

| Old | New |
|---|---|
| `_warmup()` | `market_data_client.warmup()` → iterate dict to populate `self._history` |
| `start()` | `market_data_client.subscribe_bars(self._on_bar, *tickers)` + `market_data_client.start()` |
| `reconnect()` | `market_data_client.reconnect()` |
| `stop()` | `market_data_client.stop()` |
| `_catch_up_opening_bars_for_window()` Alpaca REST call | `market_data_client.fetch_bars()` |
| `async def _handle_bar(bar)` | rename body to `_on_bar(bar)` (sync); keep async shim in `AlpacaMarketDataClient` |

**`_last_bar_received_at` tracking:** stays in `LiveSignalEngine` — set inside `_on_bar()`.  
**`_stream_started_at` tracking:** set when `market_data_client.start()` is called.

**Status:** [x] Completed

---

### Phase 5 — Refactor `OpMomentumTradeEngine`
**File:** `alpha_tech_tracker/op_momentum_strategy/trade_engine.py` *(modify)*

`OpMomentumTradeEngine.__init__` currently extracts `api_key`/`secret_key`/`alpaca_feed`
from the Alpaca client via `getattr`. Change:

- Accept optional `market_data_client: MarketDataClient = None`
- If `None`: construct `AlpacaMarketDataClient(api_key, secret_key, feed)` from existing
  alpaca client attrs (backward-compatible, no behaviour change for Alpaca users)
- Pass `market_data_client` to `LiveSignalEngine(market_data_client=...)` at startup
  (in `run()` / `_run_live()`, lines ~1741–1818 and ~1925–1998)

**Status:** [x] Completed

---

### Phase 6 — CLI wiring
**File:** `alpha_tech_tracker/op_momentum_strategy/op_momentum_trade_engine.py` *(modify)*

Add `--market-data-source {alpaca,tradestation}` flag (default: `alpaca`).

When `tradestation`:
1. `_load_config()` to pull `_TRADESTATION_SESSION_TOKENS` from `config.json`
2. Construct `TradeStationAPIClient` + `restore_session()`
3. Construct `TradeStationMarketDataClient(ts_client)`
4. Pass to `OpMomentumTradeEngine(market_data_client=...)`

TS auth setup is already handled by `tradestation_auth.py` — user runs that once before
starting the engine, same pattern as today.

**Status:** [x] Completed

---

## File Diff Summary

| File | Change |
|---|---|
| `trade_api/market_data_client.py` | **New** — abstract interface |
| `trade_api/alpaca_client/market_data_client.py` | **New** — Alpaca impl (extract from signal_engine) |
| `trade_api/tradestation/market_data_client.py` | **New** — TS impl (wrap existing bar_stream) |
| `op_momentum_strategy/signal_engine.py` | **Modify** — remove Alpaca coupling, accept MarketDataClient |
| `op_momentum_strategy/trade_engine.py` | **Modify** — accept + pass MarketDataClient |
| `op_momentum_strategy/op_momentum_trade_engine.py` | **Modify** — add `--market-data-source` CLI flag |

No changes to backtest stack, position monitor, order executor, contract selector, or
any other module.

---

## Key Design Decisions

| Decision | Rationale |
|---|---|
| `MarketDataClient` separate from `ExecutionClient` | Independent injection: TS data + Alpaca execution, or any combo |
| TS stream is 1-min; signal engine aggregates to 5-min | `_minute_buf` / `_aggregate_bars()` unchanged — TS bars enter same path |
| Warmup is per-ticker sequential for TS | TS has no batch historical endpoint; acceptable — warmup runs once at startup |
| Async bridge lives in `AlpacaMarketDataClient` | Keeps `LiveSignalEngine` sync; Alpaca SDK async requirement is an adapter concern |
| Default stays Alpaca | Zero behaviour change for existing users with no flag change |

---

## Watchdog Compatibility

`OpMomentumTradeEngine._watchdog_loop()` calls `engine.reconnect()` and checks
`engine._last_bar_received_at` and `engine._stream_started_at`. Both fields stay on
`LiveSignalEngine` — set in `_on_bar()` and on `start()` call respectively. No watchdog
changes needed.

---

## Testing Plan

- Unit test `AlpacaMarketDataClient` — mock `StockHistoricalDataClient` and `StockDataStream`
- Unit test `TradeStationMarketDataClient` — mock `TradeStationBarStream` callbacks
- Update `test_signal_engine.py` — inject a mock `MarketDataClient` instead of api_key/secret_key
- Update `test_trade_engine.py` — pass mock `MarketDataClient` to `OpMomentumTradeEngine`
- Live validation: run `ts_stream_driver.py` then engine with `--market-data-source tradestation --mock-trade-execution`

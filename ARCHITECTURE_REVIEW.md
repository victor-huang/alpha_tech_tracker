# Alpha Tech Tracker — Architecture Review

**Last updated:** April 2026  
**Scope:** Op Momentum Strategy — live trade engine, backtest stack, and broker integration layer

---

## 1. Executive Summary

The system implements an intraday opening-range momentum strategy across two execution modes that share the same signal logic:

- **Live trade engine** (`op_momentum_strategy/trade_engine.py`) — WebSocket-driven, bar-by-bar, multi-window with session recovery
- **Selector backtest** (`op_momentum_selector_backtest.py`) — batch simulation, same signal rules, sequential capital flow

**Broker layer:** Alpaca is the default execution broker. Market data (bar streaming + historical warmup) is now abstracted behind `MarketDataClient` — Alpaca and TradeStation implementations both exist and are selectable at startup via `--market-data-source`. Order execution still calls `AlpacaAPIClient` directly — see Section 6.

---

## 2. Module Map

### Live Trading

| File | Class / Entry | Responsibility |
|---|---|---|
| `op_momentum_trade_engine.py` | CLI + daemon | `run/start/stop/status` commands, log rotation, daemon PID management |
| `trade_engine.py` | `OpMomentumTradeEngine` | Central orchestrator: ticker selection, signal dispatch, entry/exit, re-entry, double-down, session recovery, multi-window state |
| `signal_engine.py` | `LiveSignalEngine` | WebSocket 5-min bar aggregation, opening-range computation, BULLISH/BEARISH signal detection |
| `position_monitor.py` | `PositionMonitor` | Intraday stop/exit loop: hard stop arming, trailing MA exit, EOD force-close, re-entry watcher creation |
| `order_executor.py` | `_place_with_fill_escalation`, `place_stock_order` | 5-step limit-order escalation with market fallback; penny-pilot tick-size handling |
| `contract_selector.py` | `TimePremiumContractSelector` | Selects shallowest ITM strike where time premium ≤ DTE-adjusted threshold |
| `position_sizer.py` | `PositionSizer` | Computes contract count (options) or share count (stocks) from window budget |
| `option_price_monitor.py` | `OptionPriceMonitor` | Background bid/ask/intrinsic snapshots; `get_fair_price()` advisor for entry/exit limit prices |
| `bar_recorder.py` | `BarRecorder` | Records live 1-min and 5-min bars to per-ticker CSV for replay |
| `config.py` | constants + `_notify()` | Strategy parameters, credential loading, Telegram/SMS gateway |
| `models.py` | dataclasses | `ActivePosition`, `SignalEvent`, `WindowConfig`, `ReentryWatcher`, `_FiveMinBar` |

### Backtest

| File | Entry | Responsibility |
|---|---|---|
| `op_momentum_selector_backtest.py` | `run_selector_backtest()` | Multi-day driver: daily top-N selection, capital flow (sequential windows, compounding), double-down |
| `op_momentum_selector.py` | `select_top_n()`, `score_ticker()` | 60-day rolling scorer; used by both live pre-market run and backtest |
| `op_momentum_backtest.py` | `run_backtest()`, `fetch_bars()` | Single-ticker signal engine; bar loop + exit logic + P&L; cache system |

### Broker Clients

| File | Class | Status |
|---|---|---|
| `trade_api/market_data_client.py` | `MarketDataClient` (ABC) | Abstract interface: warmup, fetch_bars, subscribe_bars, start/stop/reconnect |
| `trade_api/alpaca_client/market_data_client.py` | `AlpacaMarketDataClient` | Active default — Alpaca WebSocket + REST warmup; async bridge kept inside adapter |
| `trade_api/tradestation/market_data_client.py` | `TradeStationMarketDataClient` | Active — wraps `TradeStationBarStream` + REST warmup; selectable via `--market-data-source tradestation` |
| `trade_api/alpaca_client/client.py` | `AlpacaAPIClient` | Active — order execution (quotes, contracts, order placement) |
| `trade_api/etrade/client.py` | `EtradeAPIClient` | Legacy — not wired into live engine |
| `trade_api/tradestation/client.py` | `TradeStationAPIClient` | Active — used by `TradeStationMarketDataClient`; execution not yet wired |
| `order_engine.py` | `OrderEngine` | Bypassed — predates `OpMomentumTradeEngine`; not used |

---

## 3. Live Trade Engine — Data Flow

```
Pre-market (4 AM – 9:30 AM ET)
  BarRecorder starts listening (1-min + 5-min CSV recording)
  MarketDataClient.warmup() → historical bars (Alpaca REST or TradeStation REST) → MA warmup
  MarketDataClient.start() → subscribe live bars (Alpaca WebSocket or TradeStation chunked HTTP)
  LiveSignalEngine._on_bar() ← sync callback from MarketDataClient → 5-min bar aggregation
  TickerSelector.select() → 60-day rolling backtest scores → top-N tickers ranked

Opening range closes (09:30 + N bars, default 15 min)
  LiveSignalEngine._try_fire_signal()
    → BULLISH: close > OR midpoint AND close > MA20
    → BEARISH: close ≤ OR low + 20% × range AND close < MA20
  → SignalEvent buffered per window (M1 / A1 / A2)

Signal drain (_drain_pending_signals_for_window)
  Top-N selections made concurrently (parallel daemon threads)
  Each thread: _enter_position()
    → PositionSizer: size from window budget (slot_capital)
    → TimePremiumContractSelector: pick ITM strike via time-premium threshold
    → OptionPriceMonitor.get_fair_price(): initial limit price
    → order_executor._place_with_fill_escalation():
        step 0  — entry fill price (quick-exit protection, options only)
        step 0.5 — fair price from OptionPriceMonitor cache
        step 1  — mid bid/ask
        step 2  — mid ± spread/4
        step 3  — ask (buy) or bid (sell)
        fallback — market order
    → PositionMonitor.add_position()

Per-bar monitoring (every 5-min bar)
  PositionMonitor.on_bar()
    Hard stop: OR edge ± stop_pct × OR_range; arms after bar 1
    Trailing stop: close crosses MA20 (default)
    EOD: force-close at 3:55 PM ET
    → exit via _place_with_fill_escalation() (same escalation as entry)
    → _on_position_closed(): compute P&L, update _window_returned
    → create ReentryWatcher if reversal/re-entry conditions met

Re-entry / double-down
  ReentryWatcher fires on next bar crossing trigger price
  _enter_reentry() → same entry flow, inherits parent window/budget
  Double-down: freed capital from early stopout re-deployed into surviving position

Session end
  _flush_session_state() → session_{date}.json checkpoint
  On restart: _recover_session() → rebuild open positions from checkpoint
```

---

## 4. Multi-Window Capital Flow

Windows run sequentially within a day (M1 → A1 → A2). Each window inherits all returned capital (principal + P&L) from the prior window.

```
M1 deploys $10,000
  M1 exits → returns $11,200 (principal + $1,200 P&L)
    A1 budget = $11,200
      A1 exits → returns $10,800
        A2 budget = $10,800
```

**Multi-session restart normalization:** If the engine restarts mid-session, `_rebuild_window_returned` would naively accumulate capital from all prior sessions. `_get_window_budget` corrects this:

```
effective_budget = prior_returned - closed_deployed + initial_capital
                 = net_P&L_all_sessions + initial_capital
```

This preserves real P&L while collapsing duplicate principal accumulation.

---

## 5. Backtest Architecture

```
op_momentum_selector_backtest.run_selector_backtest()
  For each trading day:
    fetch_bars(tickers) → 5-min OHLCV + MA warmup (7 days lookback)
      ↓ (assembled from cache via _stitch_cache(); Alpaca API on miss)
    select_top_n(tickers, date) → 60-day rolling score → ranked top-N
      ↓ score = entry_vs_mid_pct × 0.50 + avg_win_pct × 0.30 + or_range_pct × 0.20
    compute_signals_with_backtest(df_per_ticker)
      ↓ loop 5-min bars; same BULLISH/BEARISH rules as live engine
      ↓ apply hard stop, trailing MA, EOD exits
      ↓ return trade rows (entry, exit, P&L, exit_reason)
    _apply_capital_flow(windows) → sequential M1 → A1 → A2 recycling
    _apply_doubledown_window() → reversal add-on P&L
    print daily table + cumulative stats
```

**Signal parity:** `compute_signals_with_backtest` and `LiveSignalEngine._try_fire_signal` implement the same BULLISH/BEARISH conditions. Known structural differences:
- Backtest processes bars in batch; live fires bar-by-bar (BRE/BUE timing may differ by 1 bar)
- Backtest uses final M1 P&L to size A1; live uses cost basis of open positions at drain time
- Backtest runs fresh 60-day lookback per date; live uses pre-market selector scores from startup

---

## 6. Broker Abstraction — Current State

All execution code currently calls `AlpacaAPIClient` directly. The `EXECUTION_BROKER` config flag and `TradeStationClient` exist but are not yet wired in.

| Component | Alpaca coupling | Abstraction status |
|---|---|---|
| Market data (bar streaming + warmup) | `AlpacaMarketDataClient` (default) | Abstracted ✓ — `MarketDataClient` ABC; TS impl available |
| Contract selection | `AlpacaAPIClient.get_options_contracts()` | Not abstracted |
| Order placement / cancellation | `AlpacaAPIClient.place_{stock,option}_order()` | Not abstracted |
| Order status / fill detection | `AlpacaAPIClient.order_status()` | Not abstracted |
| Account info / buying power | `AlpacaAPIClient.get_accounts()` | Not abstracted |
| Quote normalization | `get_price_from_quote()` dict format | Broker-agnostic ✓ |

**To swap execution broker** (dev_plan/broker_abstraction_phase1_refactor.md):
1. Define `ExecutionClient` interface: `place_*_order`, `cancel_order`, `order_status`, `get_accounts`
2. Implement for TradeStation (`TradeStationAPIClient` already exists)
3. Inject into `OpMomentumTradeEngine`, `order_executor`, `PositionMonitor`

---

## 7. Session Recovery

State is checkpointed to `session_{date}.json` on EOD and on `_flush_session_state()`. On restart, `_recover_session()` rebuilds open positions and window returned-capital.

**Known gaps (tracked in BUGS.md):**
- Exit orders not checked against broker on recovery — a position with a pending exit order is re-added as open without verifying broker state (BUG-008)
- No SIGTERM handler flushes state on planned daemon stop — last ~30s may be lost (BUG-009)

---

## 8. Key Files and Sizes

| File | Lines | Notes |
|---|---|---|
| `op_momentum_strategy/trade_engine.py` | ~1,500 | Central orchestrator |
| `op_momentum_strategy/position_monitor.py` | ~1,100 | Exit loop + re-entry watchers |
| `op_momentum_strategy/op_momentum_selector_backtest.py` | ~900 | Multi-day backtest driver |
| `op_momentum_strategy/op_momentum_backtest.py` | ~700 | Signal engine + cache |
| `op_momentum_strategy/signal_engine.py` | ~600 | WebSocket bar aggregation |
| `op_momentum_strategy/op_momentum_trade_engine.py` | ~620 | CLI + daemon |
| `trade_api/alpaca_client/client.py` | ~500 | Alpaca broker client |
| `op_momentum_strategy/order_executor.py` | ~400 | Fill escalation |
| `op_momentum_strategy/contract_selector.py` | ~350 | Strike selection |
| `op_momentum_strategy/option_price_monitor.py` | ~320 | Fair-price advisor |
| `op_momentum_strategy/models.py` | ~200 | Shared dataclasses |
| `trade_api/tradestation/client.py` | ~400 | TradeStation client (inactive) |
| `trade_api/etrade/client.py` | ~460 | E*TRADE client (legacy) |
| `order_engine.py` | ~230 | Legacy wrapper (bypassed) |

---

## 9. Architecture — Current and Future State

Market data is now fully abstracted. The remaining work is execution broker abstraction.

**Current state:**
```
OpMomentumTradeEngine
    ├── MarketDataClient (abstract) ✓ implemented
    │   ├── warmup() / fetch_bars()
    │   ├── subscribe_bars() / start() / stop() / reconnect()
    │   ├─ impl: AlpacaMarketDataClient   (default)
    │   └─ impl: TradeStationMarketDataClient  (--market-data-source tradestation)
    │
    └── AlpacaAPIClient (direct coupling — not yet abstracted)
        ├── place_stock_order() / place_option_order()
        ├── cancel_order() / order_status()
        ├── get_accounts()
        └── get_options_contracts() / get_option_quote*()
```

**Target state (execution abstraction — dev_plan/broker_abstraction_phase1_refactor.md):**
```
    └── ExecutionClient (abstract)
        ├── place_stock_order() / place_option_order()
        ├── cancel_order() / order_status()
        ├── get_accounts()
        └── get_options_contracts() / get_option_quote*()
        ├─ impl: AlpacaExecutionClient
        └─ impl: TradeStationExecutionClient  (client exists, needs wiring)
```

# Critical Path Map: Alpha Tech Tracker

**Created:** 2026-01-03
**Purpose:** Identify money-touching code paths that require rigorous testing

---

## Executive Summary

**Critical Paths Identified:** 5 core flows
**Money-Touching Modules:** 3 (OrderEngine, Portfolio, API Clients)
**Risk Level:** HIGH - Direct financial impact

---

## Critical Path #1: Order Placement Flow

**Risk Level:** 🔴 **CRITICAL** (Real money transactions)

### Flow Diagram
```
Strategy.check_open_position_condition()
    → OrderEngine.place()
        → [MockOrderEngine | ETradeOrderEngine].place()
            → Trade API Client (ETrade/Alpaca).place_option_order() / place_stock_order()
                → Order object created with status='open'
                    → Portfolio.add_position()
```

### Components Involved
1. **order_engine.py**
   - `OrderEngine.place()` - Routes to correct engine
   - `MockOrderEngine.place()` - Backtesting
   - `ETradeOrderEngine.place()` - Live trading

2. **trade_api/etrade/client.py**
   - `EtradeAPIClient.place_option_order()`
   - `EtradeAPIClient.place_stock_order()`

3. **trade_api/alpaca_client/client.py**
   - `AlpacaAPIClient.place_option_order()`
   - `AlpacaAPIClient.place_stock_order()`

4. **portfolio.py**
   - `Portfolio.add_position()` - Creates Position object

### Critical Validations Needed
- [ ] Order parameters are valid (price, quantity, symbol)
- [ ] Option orders have strike_price and osi_key/option_key
- [ ] API client returns valid order_id
- [ ] Position is created with correct open_price
- [ ] Order status transitions correctly (open → executed)

### Test Coverage Required
- ✅ Unit tests: Mock API responses
- ✅ Integration tests: Real API calls (paper trading)
- ✅ Error handling: Network failures, invalid orders, insufficient funds

---

## Critical Path #2: Order Execution & Position Tracking

**Risk Level:** 🔴 **CRITICAL** (Money realization)

### Flow Diagram
```
OrderEngine.execute_orders() [Mock only]
    OR
OrderEngine.sync_orders() [Live trading]
    → Trade API Client.order_status()
        → Order.status updated to 'executed'
        → Order.executed_price set
            → Portfolio tracking updated
```

### Components Involved
1. **order_engine.py**
   - `MockOrderEngine.execute_orders()` - Simulates fills
   - `ETradeOrderEngine.sync_orders()` - Polls API for status

2. **Trade API Clients**
   - `*.order_status(order_id)` - Check fill status

### Critical Validations Needed
- [ ] Order status accurately reflects reality
- [ ] executed_price matches actual fill price
- [ ] executed_at timestamp is correct
- [ ] Partial fills are handled (if applicable)
- [ ] Failed orders are marked appropriately

### Test Coverage Required
- ✅ Mock fills work correctly
- ✅ Order status sync updates positions
- ✅ Edge cases: partial fills, rejected orders

---

## Critical Path #3: Position Closing & P&L Calculation

**Risk Level:** 🔴 **CRITICAL** (Profit/loss realization)

### Flow Diagram
```
Strategy.check_close_position_condition()
    → OrderEngine.place() [sell order]
        → Order executed
            → Portfolio.close_position()
                → Position.close_price set
                → Position.status = 'closed'
                    → Portfolio.calculate_pnl()
                        → P&L computed for reporting
```

### Components Involved
1. **portfolio.py**
   - `Portfolio.close_position()` - Marks position closed
   - `Portfolio.calculate_pnl()` - Computes total P&L
   - `Portfolio.bucket_positions_pnl_by_time()` - Time-series P&L

2. **Position class**
   - P&L calculation: `(close_price - open_price) * quantity * [100 if option else 1]`

### Critical Validations Needed
- [ ] Close_price is correct
- [ ] P&L calculation handles options (×100 multiplier)
- [ ] P&L calculation handles stocks correctly
- [ ] Position status transitions to 'closed'
- [ ] close_order_id is tracked
- [ ] Decimal precision maintained (no floating point errors)

### Test Coverage Required
- ✅ Position close sets all fields correctly
- ✅ P&L calculation accurate for stocks
- ✅ P&L calculation accurate for options
- ✅ Decimal precision tests
- ✅ Time-bucketed P&L (daily, weekly, monthly)
- ✅ Edge cases: break-even trades, max profit/loss tracking

---

## Critical Path #4: Signal Generation & Trade Triggers

**Risk Level:** 🟡 **HIGH** (Drives trading decisions)

### Flow Diagram
```
Market Data Stream
    → Strategy.simulate() / market_event_handler()
        → Wave.count() - Track price waves
            → Wave.is_create_new_wave() - Detect wave boundaries
                → Wave.waves_stats() - Calculate wave metrics
                    → Strategy.check_open_position_condition()
                        → [Trigger conditions evaluated]
                            → Signal generated
                                → Order placement (Path #1)
```

### Components Involved
1. **wave.py**
   - `Wave.count()` - Updates wave with new price data
   - `Wave.is_create_new_wave()` - Detects wave reversal
   - `Wave.waves_stats()` - Computes ratios (up_waves_ratio, up_magnitude_ratio)

2. **strategy.py / tsla_strategy.py**
   - Buy triggers: `buy_trigger_up_waves_ratio`, `buy_trigger_up_magnitude_ratio`
   - Sell triggers: `is_waves_loosing_steam()`
   - Risk management: `maximum_position_loss`

3. **signal.py**
   - `Signal` class - Represents trading signal

### Critical Validations Needed
- [ ] Wave detection correctly identifies reversals
- [ ] Wave statistics are accurate (up/down ratios)
- [ ] Trigger thresholds are respected
- [ ] No false positives (spurious signals)
- [ ] Signal timing is correct (not delayed)

### Test Coverage Required
- ✅ Wave creation and boundary detection
- ✅ Wave stats calculations
- ✅ Trigger condition logic (buy/sell)
- ✅ Edge cases: insufficient data, market gaps, low volatility

---

## Critical Path #5: Market Data Streaming & Processing

**Risk Level:** 🟡 **HIGH** (Data quality affects all decisions)

### Flow Diagram
```
[Alpaca WebSocket Stream | Historical API]
    → DataAggregator (alpaca_engine.py OR alpaca_py_engine.py)
        → 5-minute bar aggregation
            → Strategy.market_event_handler()
                → Wave analysis (Path #4)
                    → Technical indicators (moving averages)
                        → Signal generation
```

### Components Involved
1. **alpaca_engine.py** (Legacy)
   - `DataAggregator` - WebSocket client for alpaca-trade-api
   - Uses `ALPACA_KEY_ID`, `ALPACA_SECRET_KEY`

2. **alpaca_py_engine.py** (Modern)
   - `DataAggregator` - Modern alpaca-py SDK
   - `get_historical_stock_data()` - Historical bars
   - Uses `ALPACA_KEY_ID`, `ALPACA_SECRET_KEY`

3. **stock_price_data_loader.py**
   - Loads cached market data

4. **strategy.py**
   - `market_data_timeout` - Detects stale data (7 hours default)

### Critical Validations Needed
- [ ] 5-minute bars are complete and accurate
- [ ] No missing data gaps
- [ ] Timestamps are correct (timezone handling)
- [ ] Data timeout detection works
- [ ] Historical vs real-time data consistency

### Test Coverage Required
- ✅ Bar aggregation produces correct OHLCV
- ✅ Timeout detection when data stops
- ✅ Historical data loading
- ✅ Timezone conversions (EST market hours)

---

## Risk Management Code Paths

**Risk Level:** 🟡 **HIGH** (Prevents catastrophic losses)

### Components
1. **strategy.py**
   - `maximum_position_loss` - Stop-loss threshold (default: $1000/$800)
   - `max_trade_per_day` - Limits overtrading (default: 2)
   - `market_data_timeout` - Prevents stale data trading

2. **Portfolio.calculate_pnl()**
   - Tracks `max_loss`, `max_profit` across all positions

### Test Coverage Required
- ✅ Stop-loss triggers position close
- ✅ Max trades per day enforced
- ✅ Stale data prevents trading

---

## Supporting Code (Lower Priority Testing)

**Risk Level:** 🟢 **MEDIUM-LOW** (Important but not money-touching)

1. **technical_analysis.py**
   - Moving average calculations
   - Support/resistance levels

2. **redis_client.py**
   - Caching layer (optional)

3. **sms.py**
   - Twilio notifications (alerting only)

4. **runner.py**
   - Daemon orchestration
   - OAuth keepalive for ETrade

---

## Test Priority Matrix

| Component | Risk | Test Priority | Coverage Target |
|-----------|------|---------------|-----------------|
| OrderEngine | 🔴 Critical | 1 | 90%+ |
| Portfolio (P&L) | 🔴 Critical | 1 | 90%+ |
| Trade API Clients | 🔴 Critical | 1 | 80%+ (mock-based) |
| Wave Analysis | 🟡 High | 2 | 70%+ |
| Signal Generation | 🟡 High | 2 | 70%+ |
| Market Data Aggregation | 🟡 High | 2 | 60%+ |
| Risk Management | 🟡 High | 2 | 80%+ |
| Technical Analysis | 🟢 Medium | 3 | 50%+ |
| Utilities (SMS, Redis) | 🟢 Low | 4 | Optional |

---

## Money-Touching Code Summary

### Absolute Must-Test (Phase 3 Priority)

1. **order_engine.py**: Lines 5-169 (entire file)
2. **portfolio.py**: Lines 8-167 (Position class + Portfolio class)
3. **trade_api/etrade/client.py**: Order methods
4. **trade_api/alpaca_client/client.py**: Order methods
5. **strategy.py**: Lines 32-49 (trigger conditions), risk management

### Formula Verification Required

**P&L Calculations:**
```python
# Stock P&L
pnl = (close_price - open_price) * quantity

# Option P&L
pnl = (close_price - open_price) * quantity * 100

# P&L Percentage
pnl_percent = total_close / total_open - 1  # Portfolio level
pnl_percent = (close - open) / open         # Position level
```

**Wave Statistics:**
```python
up_waves_ratio = num_up_waves / (num_up_waves + num_down_waves)
up_magnitude_ratio = total_up_move / (total_up_move + total_down_move)
```

**Option Cost:**
```python
# MockOrderEngine (line 96)
cost = price * 100 + fee  # Option contract = 100 shares
```

---

## Testing Strategy Recommendations

### Phase 3.1: Critical Path Tests (First)
1. OrderEngine unit tests with mocks
2. Portfolio P&L calculation tests
3. Trade API client mock tests

### Phase 3.2: Integration Tests (Second)
1. End-to-end order flow (mock trading)
2. Position lifecycle (open → close)
3. P&L aggregation (multiple positions)

### Phase 3.3: Signal & Wave Tests (Third)
1. Wave boundary detection
2. Signal trigger conditions
3. Risk management enforcement

### Phase 3.4: Edge Cases (Final)
1. Market gaps and stale data
2. Partial fills and order rejections
3. Decimal precision in P&L
4. Option vs stock handling

---

## Known Technical Debt Impacting Critical Paths

1. **Duplicate Alpaca Engines**
   - Both `alpaca_engine.py` and `alpaca_py_engine.py` exist
   - Both have `DataAggregator` classes
   - Creates confusion about which to use
   - **Recommendation:** Consolidate in Phase 4

2. **Missing Type Hints**
   - No type annotations on critical methods
   - Makes testing and refactoring harder
   - **Recommendation:** Add to OrderEngine and Portfolio first

3. **Hardcoded Values**
   - Phone numbers in strategy (line 103)
   - Magic numbers for thresholds
   - **Recommendation:** Extract to config (Phase 2)

---

## Phase 1.2 Complete ✅

**Next Step:** Phase 2.1 - Create Strategy Config Dataclasses

This critical path map will guide our test coverage decisions in Phase 3.

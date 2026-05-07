# Refactoring Plan: op_momentum_trade_engine.py → Multiple Modules

> **Status: COMPLETE** — all 9 source modules created, 62 tests passing, old monolith replaced.

## Context

`op_momentum_trade_engine.py` has grown to ~2100 lines with 6 classes, 15+ module-level
constants, daemon helpers, CLI parsing, and order execution logic all in one file.
This refactor splits it into focused, independently testable modules with clear
single responsibilities. **No behavior changes — pure restructuring.**

---

## Target Module Structure

### Source modules

```
alpha_tech_tracker/op_momentum_strategy/
  models.py              (~50 lines)   SignalEvent, _FiveMinBar, ActivePosition, _D()
  config.py              (~100 lines)  all constants, _clicksend_cfg, _load_config(), _send_sms()
  contract_selector.py   (~120 lines)  _next_friday(), _strike_increment(), ITMOptionContractSelector
  position_sizer.py      (~60 lines)   PositionSizer
  order_executor.py      (~160 lines)  _place_with_fill_escalation(), AlpacaAPIClient monkey-patch
  signal_engine.py       (~430 lines)  LiveSignalEngine
  position_monitor.py    (~420 lines)  PositionMonitor
  trade_engine.py        (~360 lines)  TickerSelector, OpMomentumTradeEngine
  op_momentum_trade_engine.py  (~100 lines)  thin CLI/daemon wrapper + re-exports (backward compat)
```

### Test modules

```
tests/op_momentum_trade_engine/           ← new dedicated test folder
  __init__.py
  test_contract_selector.py    ← TestNextFriday, TestStrikeIncrement, TestITMOptionContractSelector
  test_position_sizer.py       ← TestPositionSizer + sizer parts of TestRankWeightedSizing
  test_signal_engine.py        ← TestLiveSignalEngine
  test_position_monitor.py     ← TestPositionMonitor, TestPrintSummaryPnl
  test_trade_engine.py         ← TestTickerSelector, TestSignalBuffer, TestSignalSelectionLoop,
                                    engine parts of TestRankWeightedSizing

tests/unit/test_op_momentum_trade_engine.py   ← deleted (replaced by above)
```

---

## Module Responsibilities

### `models.py`
- `_D(x) -> Decimal` — decimal helper used by all other modules
- `@dataclass SignalEvent` — immutable signal event passed from LiveSignalEngine to engine
- `@dataclass _FiveMinBar` — aggregated 5-min OHLCV bar
- `@dataclass ActivePosition` — mutable position state (entry/exit/stops/fills)

### `config.py`
All 21 module-level constants:
`TICKERS`, `ACCOUNT_BUDGET`, `MAX_ACTIVE_SYMBOLS`, `OPENING_BARS`, `OPENING_START_TIME`,
`STOP_PCT`, `STRIKE_CALL_OFFSET`, `STRIKE_PUT_OFFSET`, `CAPITAL_PER_SYMBOL`,
`EOD_EXIT_TIME`, `MA_WARMUP_DAYS`, `ROLLING_LOOKBACK_DAYS`, `BEARISH_MA200`,
`SIGNAL_BUFFER_MINUTES`, `TRAILING_MA`, `MAX_LOSS_PCT`, `ARMED_MA20_EXIT`,
`REGIME_FILTER`, `REGIME_MA`, `RANK_WEIGHTED_SIZING`, `RANK_WEIGHTS`

Plus config file helpers:
- `_clicksend_cfg: dict = {}`
- `_load_config(config_file)` — loads alpaca credentials into env + populates `_clicksend_cfg`
- `_send_sms(message)` — ClickSend SMS with lazy import, silent skip on failure

### `contract_selector.py`
- `_next_friday(ref_date)` — compute next Friday from a date
- `_strike_increment(price)` — returns $1 / $5 / $10 based on price range
- `ITMOptionContractSelector` — finds the nearest weekly option contract for a signal

### `position_sizer.py`
- `PositionSizer` — computes contract quantity from buying power × `capital_weight`

### `order_executor.py`
- `_place_with_fill_escalation(...)` — 3-step limit → aggressive → market escalation
- `_patched_place_option_order(...)` + monkey-patch `AlpacaAPIClient.place_option_order`
  (applied at import time — same behavior as today)

### `signal_engine.py`
- `LiveSignalEngine` — streams live bars, fires `SignalEvent` after opening range closes

### `position_monitor.py`
- `PositionMonitor` — evaluates stops per bar, closes positions, prints status/summary

### `trade_engine.py`
- `TickerSelector` — pre-market ticker selection with fallback to previous day
- `OpMomentumTradeEngine` — main daily orchestrator

### `op_momentum_trade_engine.py` (kept as entry point)
Daemon helpers + CLI + `__main__` block, plus re-exports for backward compatibility:
```python
from .models import SignalEvent, ActivePosition, _FiveMinBar, _D
from .config import CAPITAL_PER_SYMBOL, MAX_ACTIVE_SYMBOLS, RANK_WEIGHTS, ...
from .contract_selector import ITMOptionContractSelector, _next_friday, _strike_increment
from .position_sizer import PositionSizer
from .signal_engine import LiveSignalEngine
from .position_monitor import PositionMonitor
from .trade_engine import TickerSelector, OpMomentumTradeEngine
```

---

## Implementation Steps

1. Create `models.py` — move `_D`, `SignalEvent`, `_FiveMinBar`, `ActivePosition`
2. Create `config.py` — move all constants + `_clicksend_cfg` + `_load_config` + `_send_sms`
3. Create `contract_selector.py` — move `_next_friday`, `_strike_increment`, `ITMOptionContractSelector`
4. Create `position_sizer.py` — move `PositionSizer`
5. Create `order_executor.py` — move `_place_with_fill_escalation` + monkey-patch block
6. Create `signal_engine.py` — move `LiveSignalEngine`
7. Create `position_monitor.py` — move `PositionMonitor`
8. Create `trade_engine.py` — move `TickerSelector` + `OpMomentumTradeEngine`
9. Rewrite `op_momentum_trade_engine.py` — daemon helpers + CLI + `__main__` + re-exports
10. Create `tests/op_momentum_trade_engine/__init__.py`
11. Split `tests/unit/test_op_momentum_trade_engine.py` into 5 new test files
12. Delete `tests/unit/test_op_momentum_trade_engine.py`
13. Run full test suite — all 58 tests must pass unchanged

Each new source file uses relative imports (`.models`, `.config`, etc.).
Run `autoflake -i --remove-all-unused-imports` on each file before finishing.

---

## Verification

```bash
# All 58 tests must pass
PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker \
  /Users/victorhuang/.pyenv/versions/alpha_tech_tracker/bin/python \
  -m pytest tests/op_momentum_trade_engine/ -q

# CLI entry point must still work
PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker \
  /Users/victorhuang/.pyenv/versions/alpha_tech_tracker/bin/python \
  -m alpha_tech_tracker.op_momentum_strategy.op_momentum_trade_engine --help
```

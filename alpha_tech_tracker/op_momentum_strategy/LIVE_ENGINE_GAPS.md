# Live Engine Gaps

Features present in `op_momentum_backtest.py` that are missing or different
in the live trading engine (`trade_engine.py` / `position_monitor.py`).

---

## Bugs

### ~~G1 — Stale `_open_position_count` reference in `_enter_position` exception handler~~ ✓ Fixed

**File:** `trade_engine.py` line ~260
**Severity:** High — crashes on any real order placement failure

When `_place_entry()` raises an exception, the except block decrements
`self._open_position_count` which no longer exists. It should decrement
`self._window_state[window_label]["open_position_count"]`.

```python
# current (broken)
self._open_position_count -= 1

# should be
self._window_state[window_label]["open_position_count"] -= 1
```

---

## Logic Differences

### G2 — Fallback exit checks `close`, backtest checks intrabar `high`

**File:** `position_monitor.py` lines 108, 135
**Severity:** Medium — live exits will be systematically later/worse on fallback hits

Backtest logic:
```python
# exits at close if the bar's high touched the fallback level
if bar["High"] >= fallback_price:
    exit_price = bar["Close"]
```

Live logic:
```python
# only triggers if close itself crosses the level
elif not pos.hard_stop_armed and close <= pos.fallback_price:
    exit_reason = "fallback_20pct"
```

Same asymmetry applies to the BEARISH side (checks `close >= fallback_price`).

**Fix:** Change the condition to check `high` (BULLISH) / `low` (BEARISH) against
`fallback_price`, and exit at the bar close — matching backtest behavior.

---

## Missing Features

### G3 — Trade duration and peak move not tracked on `ActivePosition`

**Severity:** Low — useful for post-trade analysis and Slack notifications

Backtest tracks per-trade:
- `bars_held` / `mins_held` — how long the position was open
- `max_favorable_move` — peak profit magnitude reached during the trade

`ActivePosition` has none of these fields.

---

### G4 — No win/loss stats in daily trade summary

**Severity:** Low — nice-to-have for end-of-day Slack notification

Backtest computes and prints: win rate, EV/trade, avg win %, avg loss % across
all closed trades for the session. `PositionMonitor.print_status()` only lists
individual position rows with no aggregate stats.

---

## Config Inconsistencies

### G5 — Regime MA default mismatch

**Severity:** Medium — backtests and live runs produce different results unless
`--regime-ma` is passed explicitly

| Context | Default |
|---------|---------|
| `op_momentum_backtest.py` | `--regime-ma 5` |
| `config.py` (`REGIME_MA`) | `8` |
| All docs and findings | `8` |

**Fix:** Change the backtest default from 5 to 8 to match live config and
documented findings.

---

## Out of Scope (backtest-only, not needed in live)

- Monthly / P&L distribution reports — replay analytics only
- `--source yfinance` flag — live always uses Alpaca
- `held_to_close` / `success` flags — backtest stats only

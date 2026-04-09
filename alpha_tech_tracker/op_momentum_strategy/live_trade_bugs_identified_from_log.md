# Live Trade Bugs Identified from Log

Bugs identified by reviewing the trade log and 5-min/1-min bar data from the 2026-04-08 live session.

---

## Bug 1 (Critical): `ITMOptionContractSelector` Selected OTM Strike Due to API Pagination

**Discovered:** 2026-04-08
**Trade affected:** SNDK [Bearish] A2 — `SNDK260410P00745000` x4, −$680
**Status: Fixed** — commits `6a3a902`, `867d7df`

### What happened

At 15:09 ET, the trade engine entered SNDK BEARISH (stock at $777.01) and selected the `$745` strike put — which is **$32 OTM**. The $12.30 entry premium was entirely time value with no intrinsic value. The contract lost money on any flat or upward move and had far lower delta than an ITM put would have.

Log evidence at 19:09:02 UTC:
```
SNDK BEARISH signal: stock=777.01 target_strike=850 expiry=2026-04-10
Selected contract: SNDK260410P00745000 strike=745.0 (target was 850)
```

The background option price monitor (running `TimePremiumContractSelector`) had correctly identified K≈$855–$900 as the right range at 09:33 ET, with time premiums of $0.79–$3.33 against a $3.15 target.

### Root cause

`ITMOptionContractSelector.select()` searched a broad ±20% stock-price range (`$622–$932` for SNDK at $777) with `limit=50`. The Alpaca listing API returned K=$745 in its first page of results — the target K=$850 was never in the returned set. The selector then picked K=$745 as the nearest to target among whatever was returned, with no time premium check.

### Fix (applied 2026-04-08)

`ITMOptionContractSelector` was renamed from `OptionContractSelector` and its strike search was changed to use a **narrow ±5-increment window centered on `target_strike`** as the primary search:

```python
# contract_selector.py
_OPTION_CONTRACT_SELECTOR_SEARCH_RADIUS_INCREMENTS = 5

radius = incr * _OPTION_CONTRACT_SELECTOR_SEARCH_RADIUS_INCREMENTS
contracts, expiry = _fetch_contracts_with_expiry_fallback(
    self._client, ticker, option_type,
    target_strike - radius,   # e.g. $800 for SNDK target=$850, incr=$10
    target_strike + radius,   # e.g. $900
)
```

For SNDK BEARISH at $777: target=$850, incr=$10, narrow range=[$800, $900]. With only ~10 strikes in this window, `limit=50` easily covers all results and K=$850 is guaranteed to be present. The old broad ±20% range is retained as a fallback if the narrow search returns nothing.

### Why this matters beyond SNDK

Any ticker with a dense option chain (many strikes across a wide range) can hit the pagination limit. The narrow search eliminates this by centering the query on exactly where the target strike should be.

---

## Bug 2: No Minimum OR Range Guard — Immediate `fallback_20pct` Exits

**Discovered:** 2026-04-08
**Trades affected:**
- TSLA [Bullish] A1 — `TSLA260410C00310000` x1, −$120 (entry=exit=13:26)
- FN [Bearish] A2 — `FN260417P00670000` x1, −$430 (15:09 → 15:11)

### What happened

Both positions exited on `bars_held=0` — the first monitored bar after entry.

**TSLA A1:**
- OR: high=347.82, low=347.37, range=**$0.45** (0.13% of stock price)
- `bull_fallback = OR_high − 0.20 × range = 347.82 − 0.09 = **$347.73**`
- A $0.09 downward move from OR_high triggered the fallback — smaller than normal 1-min bid/ask noise

**FN A2:**
- OR: high=611.74, low=610.62, range=**$1.12** (0.18% of stock price)
- `bear_fallback = OR_low + 0.20 × range = 610.62 + 0.224 = **$610.844**`
- First 5-min bar close=610.99 ≥ 610.844 → exit on a $0.37 move against position on a $611 stock

### Root cause

`position_monitor.py` checks:
```python
# BEARISH
elif not pos.hard_stop_armed and close >= pos.fallback_price:
    exit_reason = "fallback_20pct"
```

The fallback threshold is `OR_low + 0.20 * OR_range`. When the OR range is extremely compressed (< 0.2% of stock price), this threshold is smaller than normal intraday noise. The 1-bar opening windows (A1 at 13:15, A2 at 15:00) are especially vulnerable because a single sluggish minute produces a near-zero range.

`signal_engine.py` emits the signal without checking whether the OR range is wide enough to be tradeable.

### Fix

Add a minimum OR range filter in `signal_engine.py` before emitting a BULLISH or BEARISH signal. The check should compare OR range to stock price as a percentage, not as an absolute value:

```python
MIN_OR_RANGE_PCT = 0.003  # 0.3% — tune via backtest

or_range_pct = or_range / close
if or_range_pct < MIN_OR_RANGE_PCT:
    logger.info(
        "%s [%s]: skipping signal — OR range %.4f%% below minimum %.1f%%",
        ticker, window_label, or_range_pct * 100, MIN_OR_RANGE_PCT * 100,
    )
    return
```

The `0.3%` starting point would have blocked both trades today (0.13% and 0.18%) while leaving the normal morning window signals untouched. The exact threshold should be validated against backtest data — run a sweep over 2025 to find the value that eliminates these degenerate entries without filtering legitimate low-range days.

---

## Bug 3 (Operational): M1 Signals Entered 34 Minutes Late After Mid-Session Restart

**Discovered:** 2026-04-08
**Trades affected:** AMD [Bullish] M1 (10:19 entry, optimal ~9:45), SHOP [Bullish] M1 (10:19 entry)

### What happened

The engine was manually restarted at ~10:09 ET to adjust the M1 window time. The second engine instance warmed up, caught up to the opening bars, and re-generated M1 signals at 10:09–10:12 ET. Orders went through fill escalation (10:17 → 10:18 → 10:19 ET market order).

The M1 opening range signals are computed at ~9:45 ET (after 3 opening bars). Entering at 10:19 ET is 34 minutes past the optimal entry. By then AMD had already dropped from $232 to $228–$229 and the market direction was established.

### Root cause

No staleness guard exists for catchup signals. When the engine restarts mid-session, it replays all opening bars via catchup and fires signals as if the opening had just closed — even when significant time has elapsed.

### Fix

In `signal_engine.py` (or wherever catchup signals are emitted), add a wall-clock check before buffering a catchup signal for an elapsed window:

```python
MAX_CATCHUP_DELAY_MINUTES = 20  # configurable

now_et = _now_et()
signal_bar_et = ...  # the bar time that closed the OR
elapsed = (now_et - signal_bar_et).total_seconds() / 60

if elapsed > MAX_CATCHUP_DELAY_MINUTES:
    logger.info(
        "%s [%s]: skipping stale catchup signal — %d min since OR closed",
        ticker, window_label, int(elapsed),
    )
    return
```

This way a mid-session restart for an M1 window won't enter positions 30+ minutes past the ideal entry bar.

---

## Bug 4 (Data Anomaly): FN Pre-Computation Used Wrong Stock Price at Startup

**Discovered:** 2026-04-08
**P&L impact:** None — actual trade used correct live price

### What happened

At 09:33 ET, the background `TimePremiumContractSelector` (option price monitor) logged FN stock price as **$299.875**, approximately half the actual live price (~$600–$607):

```
FN BEARISH signal: stock=299.875 expiry=2026-04-17 dte=9 target_premium=5.397750 contracts=10
```

The actual A2 trade at 15:07 ET called `select()` fresh with `stock_price=610.62` and correctly identified `FN260417P00670000` (K=$670, $59.38 ITM, $10.62 time premium ≈ target of $10.99).

### Root cause

Likely a stale or split-adjusted Alpaca stock quote returned for FN during the pre-market warmup window (08:33 ET startup). The pre-computation re-runs every ~5 minutes throughout the day and the wrong price appeared only in the earliest runs.

### What to check

- Verify whether FN had any corporate action (e.g., forward split) on or around 2026-04-08 that could cause Alpaca to return a split-adjusted price temporarily.
- Add a sanity check in the pre-computation: if the live quote deviates by more than 30% from the last historical close (`warmup_close`), log a warning and skip the pre-computation for that ticker rather than using the bad quote.

---

## Summary Table

| # | Bug | Trades | P&L Impact | Fix Location |
|---|-----|--------|-----------|--------------|
| 1 | `ITMOptionContractSelector` broad search missed target strike (pagination) | SNDK | −$680 | **Fixed** — narrow ±5-increment search in `contract_selector.py` (commits `6a3a902`, `867d7df`) |
| 2 | No min OR range guard → instant `fallback_20pct` | TSLA, FN | −$550 | `signal_engine.py` — add `OR_range / price < 0.3%` filter before emitting signal |
| 3 | Stale M1 catchup signals after mid-session restart | AMD, SHOP | Indirect | `signal_engine.py` — add elapsed-time guard on catchup signals |
| 4 | Bad Alpaca pre-market quote for FN (stock=299.875) | None | — | `option_price_monitor.py` — add quote sanity check vs last warmup close |

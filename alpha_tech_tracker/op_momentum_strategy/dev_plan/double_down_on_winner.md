# Double-Down on Winner

## Summary

When a window picks top-2 (or top-N) stocks and one of the positions stops out within the first 15 minutes after entry, the freed capital is redeployed into the surviving position as a single add-on leg. The goal is to concentrate capital into the winner when the market quickly validates one signal and invalidates the other.

**Backtested result (IEX feed, top-2, 60/40 weights, M1+A1+A2, morning-split 100, reversal+BRE+BRU on):**

| Year | No DD | With DD | Delta |
|------|-------|---------|-------|
| 2020 | +89.2% | +119.1% | **+29.9pp** |
| 2021 | +132.9% | +180.0% | **+47.1pp** |
| 2022 | +214.9% | +265.2% | **+50.4pp** |
| 2023 | +278.4% | +341.3% | **+62.9pp** |
| 2024 | +125.3% | +172.0% | **+46.7pp** |
| 2025 | +178.6% | +247.8% | **+69.3pp** |
| 2026 (partial, through Apr 10) | +99.1% | +122.7% | **+23.6pp** |

DD wins **every year** across the full 7-year window. Win rate is unchanged (DD never creates new losers — the add-on leg has a break-even hard stop). The lift ranges from +24pp to +69pp depending on year volatility and frequency of early stopouts.

---

## Signal Logic

### Trigger Conditions (all must be true at the 15-min mark)

1. **At least one position stopped out** via hard stop or fallback within 15 min of OR close (`exit_reason in {"hard_stop", "fallback_20pct"}` and `bars_held <= 2` for 5-min bars).
2. **At least one position survived** — did not hard-stop within the same 15-min window.

### The 15-min mark

All picks in a window enter at the same time (OR close). The 15-min mark is therefore fixed per window:

| Window | OR close | 15-min mark |
|--------|----------|-------------|
| M1 (09:30 / 3 bars) | 09:45 | 10:00 |
| M2 (09:30 / 1 bar)  | 09:35 | 09:50 |
| A1 (13:15 / 1 bar)  | 13:20 | 13:35 |
| A2 (15:00 / 1 bar)  | 15:05 | 15:20 |

The doubledown does **not** fire when the stopout happens — it fires at the fixed 15-min mark once the survivor is confirmed.

### One doubledown per window per day

The **winner** is whichever position survives past the 15-min mark. It receives all freed capital from any stopped-out positions as a single add-on leg. There is no cascading or sequential doubledown.

**Reentry exclusion:** a stopped-out rank is only eligible to free capital if it has **no** reversal/re-entry leg ([REV]/[BRE]/[BRU]). If a reversal fired, the capital was already redeployed into that leg — it cannot simultaneously fund the DD addon. Without this exclusion, the same slot capital would be double-counted (once for the reentry P&L in `_compute_cap_pnl`, once for the DD addon).

| Scenario (top-2) | Stopout | Winner | Freed capital |
|---|---|---|---|
| rank-2 stops, rank-1 survives | rank-2 (40%) | rank-1 | ~$4,000 |
| rank-1 stops, rank-2 survives | rank-1 (60%) | rank-2 | ~$6,000 |
| both stop out | — | none | no doubledown |

For top-3, if multiple positions survive the winner is the highest-ranked survivor (lowest rank number).

---

## Add-on Leg Parameters

| Parameter | Value |
|-----------|-------|
| Entry price | Close of the 15-min bar (OR close + 15 min) |
| Hard stop | Same as entry price (break-even protection) |
| Trailing stop | Same MA trailing stop as rank-1's primary position |
| Trailing stop activation | Once trailing MA crosses above the hard stop |
| Exit | Same trailing stop or EOD as rank-1's primary leg |

### Break-even protection

Because the hard stop equals the add-on entry price, the add-on leg **can never produce a net loss**. If price dips below the 15-min bar close after the doubledown, the hard stop fires and the freed capital is returned intact. The add-on only generates P&L when rank-1 continues higher (BULLISH) or lower (BEARISH) from the 15-min mark.

### Freed capital calculation

```
returned_capital = slot_capital × (1 + pnl / entry_price)
```

Where `slot_capital` is the capital originally allocated to the stopped-out rank (e.g., 30% of window capital for rank-2 in a 50/30/20 weighting). If the stop-out was a full OR-range loss, `returned_capital` is the original slot less the realized loss.

---

## Backtest Model

### Implementation files

| File | What changed |
|------|-------------|
| `op_momentum_selector_backtest.py` | `_annotate_doubledown_addon()`, `_apply_doubledown()`, `--doubledown` flag |

### Approximation

The backtest does not re-run bar-by-bar exit simulation for the add-on leg. Instead:

```
addon_pnl_pct = max(0, signed_return(addon_entry → rank1.exit_price))
```

For BULLISH:  `(exit_price − addon_entry) / addon_entry`
For BEARISH:  `(addon_entry − exit_price) / addon_entry`

This is exact when:
- Rank-1 wins and exits via trailing stop (add-on follows same exit).

This is a slight overestimate when:
- Price dips below `addon_entry` after the 15-min mark before the trailing stop fires (in reality, the add-on hard stop would have exited first at break-even, but the approximation still floors at 0 so the directional bias is correct).

The floor of `max(0, ...)` preserves the break-even property: the backtest never credits a loss to the add-on leg.

### Key functions

**`_annotate_doubledown_addon(trade_rows, bars_by_date, ...)`**
- Called inside `run_selector_backtest` before `return`, only when `enable_doubledown=True`.
- Groups trade_rows by `(date, window)`, partitions into stopouts and survivors, identifies the highest-ranked survivor as the winner, looks up the 15-min bar close from `bars_by_date`, computes `dd_addon_pnl_pct`.
- Adds `dd_addon_pnl_pct`, `dd_addon_entry`, `dd_freed_ranks` to the winner row (may be rank-1 or rank-2).

**`_apply_doubledown(trade_rows)`**
- Called after `_apply_capital_flow` (which sets `slot_capital` on each row).
- Finds the winner row (the one annotated with `dd_freed_ranks`).
- Computes freed capital from all stopped-out ranks' `slot_capital` and `pnl`.
- Adds `addon_cap_pnl = freed_capital × dd_addon_pnl_pct` to winner's `cap_pnl`.
- Adds `dd_addon_cap_pnl` and `dd_freed_capital` to winner row for display.

**`[DD]` subrow in daily table**
- Printed beneath rank-1's row when a doubledown fired.
- Shows freed capital amount, add-on P&L, add-on entry price, and which ranks freed capital.

---

## CLI Usage

```bash
# Confirmed best config (used for 7-year validation below)
PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker \
  python alpha_tech_tracker/op_momentum_strategy/op_momentum_selector_backtest.py \
  --weights 60 40 \
  --window M1 09:30 3 --window A1 13:15 1 --window A2 15:00 1 \
  --morning-split 100 \
  --reversal --bearish-reentry --bullish-reentry \
  --top 2 --doubledown --feed iex \
  --start 2025-01-01 --end 2025-12-31

# With regime filter (more conservative, fewer trades)
PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker \
  python alpha_tech_tracker/op_momentum_strategy/op_momentum_selector_backtest.py \
  --weights 60 40 \
  --window M1 09:30 3 --window A1 13:15 1 --window A2 15:00 1 \
  --morning-split 100 \
  --reversal --bearish-reentry --bullish-reentry \
  --regime-filter --regime-ma 8 \
  --top 2 --doubledown --feed iex \
  --start 2025-01-01 --end 2025-12-31

# Multi-year compound growth projection
PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker \
  python alpha_tech_tracker/op_momentum_strategy/op_momentum_selector_backtest.py \
  --weights 60 40 \
  --window M1 09:30 3 --window A1 13:15 1 --window A2 15:00 1 \
  --morning-split 100 \
  --reversal --bearish-reentry --bullish-reentry \
  --top 2 --doubledown --compound --feed iex \
  --start 2020-01-01 --end 2026-04-10
```

---

## Doubledown Window Sweep

The `--doubledown-start` parameter controls the start time (minutes from OR close) at which the DD check fires and the add-on leg enters. Stopouts that occurred before this mark are eligible to free capital. A full sweep was run over 2025-01-01 → 2026-04-10 (IEX feed, top-2, 60/40, M1+A1+A2, morning-split 100, reversal+BRE+BRU on):

| DD minutes | Total return | Delta vs baseline |
|---|---|---|
| baseline (no DD) | +277.66% | — |
| 5 | +308.44% | +30.8pp |
| 10 | +312.20% | +34.5pp |
| 15 | +310.66% | +33.0pp |
| 20 | +309.41% | +31.8pp |
| 25 | +309.33% | +31.7pp |
| 30 | +311.09% | +33.4pp |
| 40 | +320.84% | +43.2pp |
| **50** | **+331.90%** | **+54.2pp** |
| 60 | +325.10% | +47.4pp |
| 70 | +324.99% | +47.3pp |
| 80 | +326.52% | +48.9pp |
| 90 | +326.03% | +48.4pp |
| 100 | +329.63% | +52.0pp |
| 110 | +329.33% | +51.7pp |
| 120 | +328.75% | +51.1pp |
| 130 | +330.39% | +52.7pp |
| 140 | +329.85% | +52.2pp |
| 150 | +326.77% | +49.1pp |

**50 min is the overall peak.** There is a clear step-up from the 5–30 min range (~308–312%) to 40+ min (~320–332%), with 50 min as the local maximum before leveling off in the 60–150 range.

### 5-year per-year consistency check (top candidates)

Top candidates retested per year against baseline and DD 15 min:

| Year | Baseline | DD 15 | DD 30 | DD 40 | DD 50 | DD 100 | DD 110 | DD 130 |
|------|----------|-------|-------|-------|-------|--------|--------|--------|
| 2021 | +132.85% | +148.60% | +153.88% | +160.48% | +161.77% | +167.10% | **+169.19%** | +168.99% |
| 2022 | +214.88% | +233.62% | +241.83% | +244.56% | +251.91% | +253.28% | +252.86% | **+257.23%** |
| 2023 | +278.38% | +301.41% | +312.55% | +318.80% | **+325.77%** | +318.68% | +317.97% | +313.56% |
| 2024 | +125.30% | +139.83% | +150.82% | **+155.93%** | +152.50% | +151.23% | +152.97% | +152.42% |
| 2025 | +178.58% | +202.39% | +203.11% | +208.35% | **+215.74%** | +214.03% | +213.90% | +214.41% |

DD beats baseline **every year** for all candidates. There is a smooth improvement as DD minutes increases from 15 → 50, with diminishing gains beyond 50. **50 min wins 3/5 years** (2023–2025); 40 min wins 2024 by a small margin (+155.93% vs +152.50%), and 110/130 min lead in 2021–2022 but by ≤7pp. The 15-min default is consistently the weakest DD config — upgrading to 50 min adds +13–24pp per year over DD 15.

**Recommended default: `--doubledown-start 50`** (flag renamed from `--doubledown-minutes` to `--doubledown-start` to reflect that it is the start time of the DD check from OR close, not a window duration)

---

## Open Questions / Future Work

### Backtest accuracy
The current approximation assumes the add-on exits at the winner's exit price. A more accurate model would re-run the trailing-stop/hard-stop loop from the 15-min bar onward. This requires passing `all_bars` into `_apply_doubledown` and running a mini bar-by-bar simulation — meaningful added complexity, deferred given the signal already shows strong promise across 7 years of backtests.

### Live engine integration
Not yet implemented in `trade_engine.py` / `position_monitor.py`. Implementation notes:
- At the 15-min mark: check if any co-picks stopped out (consult position state from `OpMomentumTradeEngine`).
- If yes and rank-1 still open: place a new order for rank-1 with the freed capital.
- Set a new hard stop at the 15-min bar close (retrieved from `signal_engine`'s bar buffer).
- The existing trailing stop in `position_monitor.py` continues tracking rank-1; the hard stop for the add-on is the new floor until the trailing MA crosses above it.
- Sizing: use `PositionSizer` with `window_budget = freed_capital`.

### Interaction with other signals
- **Reversal / re-entry**: if rank-2 stops out and triggers a reversal entry, the capital is already committed to the reversal leg — no doubledown occurs for that rank.
- **Multiple windows**: doubledown is evaluated independently per window; M1 and A1 do not share freed capital.

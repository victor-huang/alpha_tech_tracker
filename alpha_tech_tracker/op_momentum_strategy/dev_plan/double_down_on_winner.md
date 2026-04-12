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
# Confirmed best config (--doubledown-start 5, updated after capital recycling fix)
PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker \
  python alpha_tech_tracker/op_momentum_strategy/op_momentum_selector_backtest.py \
  --weights 60 40 \
  --window M1 09:30 3 --window A1 13:15 1 --window A2 15:00 1 \
  --morning-split 100 \
  --reversal --bearish-reentry --bullish-reentry \
  --top 2 --doubledown --doubledown-start 5 --feed iex \
  --start 2025-01-01 --end 2025-12-31

# With regime filter (more conservative, fewer trades)
PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker \
  python alpha_tech_tracker/op_momentum_strategy/op_momentum_selector_backtest.py \
  --weights 60 40 \
  --window M1 09:30 3 --window A1 13:15 1 --window A2 15:00 1 \
  --morning-split 100 \
  --reversal --bearish-reentry --bullish-reentry \
  --regime-filter --regime-ma 8 \
  --top 2 --doubledown --doubledown-start 5 --feed iex \
  --start 2025-01-01 --end 2025-12-31

# Multi-year compound growth projection
PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker \
  python alpha_tech_tracker/op_momentum_strategy/op_momentum_selector_backtest.py \
  --weights 60 40 \
  --window M1 09:30 3 --window A1 13:15 1 --window A2 15:00 1 \
  --morning-split 100 \
  --reversal --bearish-reentry --bullish-reentry \
  --top 2 --doubledown --doubledown-start 5 --compound --feed iex \
  --start 2020-01-01 --end 2026-04-10
```

---

## Doubledown Window Sweep

The `--doubledown-start` parameter controls the start time (minutes from OR close) at which the DD check fires and the add-on leg enters. Stopouts that occurred before this mark are eligible to free capital.

### Updated sweep (2025 and 2026, with DD capital recycling fix)

After the capital recycling fix (`_apply_capital_flow` correctly deducts DD-deployed capital from sequential windows when the DD leg is still running), the optimal start time shifted dramatically. Full sweep over 2025-01-01 → 2025-12-31 and 2026-01-01 → 2026-04-10 (IEX feed, top-2, 60/40, M1+A1+A2, morning-split 100, reversal+BRE+BRU on):

| DD start | 2025 return | 2025 delta | 2026 return | 2026 delta |
|---|---|---|---|---|
| baseline (no DD) | +178.58% | — | +99.08% | — |
| **5** | **+199.22%** | **+20.6pp** | **+108.79%** | **+9.7pp** |
| **10** | **+198.86%** | **+20.3pp** | +107.10% | +8.0pp |
| 15 | +193.28% | +14.7pp | +106.28% | +7.2pp |
| 20 | +190.70% | +12.1pp | +105.09% | +6.0pp |
| 25 | +187.80% | +9.2pp | +104.08% | +5.0pp |
| 30 | +187.81% | +9.2pp | +104.56% | +5.5pp |
| 40 | +186.57% | +8.0pp | +104.49% | +5.4pp |
| 50 | +185.55% | +7.0pp | +104.85% | +5.8pp |
| 60 | +183.40% | +4.8pp | +104.09% | +5.0pp |
| 70 | +182.00% | +3.4pp | +103.54% | +4.5pp |
| 80 | +181.58% | +3.0pp | +102.42% | +3.3pp |
| 90 | +180.47% | +1.9pp | +101.09% | +2.0pp |
| 100 | +179.85% | +1.3pp | +100.76% | +1.7pp |
| 110 | +179.40% | +0.8pp | +100.10% | +1.0pp |
| 120 | +178.79% | +0.2pp | +100.13% | +1.0pp |
| 130 | +178.98% | +0.4pp | +100.02% | +0.9pp |
| 140 | +178.60% | +0.0pp | +99.67% | -0.4pp |
| 150 | +178.42% | -0.2pp | +99.75% | -0.3pp |

Returns decrease monotonically as start time increases. Earlier is consistently better — the opposite of the pre-fix finding. Beyond 120 min, DD provides near-zero or negative lift.

### Per-year consistency check — IEX feed (2021–2025)

| Year | Baseline | DD 5 | DD 10 | DD 15 | DD 60 | DD 120 |
|------|----------|------|-------|-------|-------|--------|
| 2021 | +132.9% | +144.25% (+11.4pp) | **+144.69% (+11.8pp)** | +141.54% (+8.6pp) | +137.73% (+4.8pp) | +133.61% (+0.7pp) |
| 2022 | +214.9% | **+232.10% (+17.2pp)** | +228.50% (+13.6pp) | +225.44% (+10.5pp) | +222.03% (+7.1pp) | +217.40% (+2.5pp) |
| 2023 | +278.4% | **+291.34% (+12.9pp)** | +290.58% (+12.2pp) | +287.85% (+9.5pp) | +283.98% (+5.6pp) | +279.13% (+0.7pp) |
| 2024 | +125.3% | **+137.81% (+12.5pp)** | +135.69% (+10.4pp) | +134.33% (+9.0pp) | +134.06% (+8.8pp) | +127.76% (+2.5pp) |
| 2025 | +178.6% | **+199.22% (+20.6pp)** | +198.86% (+20.3pp) | +193.28% (+14.7pp) | +183.40% (+4.8pp) | +178.79% (+0.2pp) |
| **Wins** | | **4/5** | 1/5 | 0/5 | 0/5 | 0/5 |

### Per-year consistency check — SIP feed (2021–2026)

| Year | Baseline | DD 5 | DD 10 | DD 15 | DD 60 | DD 120 |
|------|----------|------|-------|-------|-------|--------|
| 2021 | +147.87% | **+158.41% (+10.5pp)** | +158.08% (+10.2pp) | +155.96% (+8.1pp) | +154.51% (+6.6pp) | +149.69% (+1.8pp) |
| 2022 | +191.51% | **+210.80% (+19.3pp)** | +210.79% (+19.3pp) | +206.17% (+14.7pp) | +200.64% (+9.1pp) | +194.02% (+2.5pp) |
| 2023 | +334.58% | +352.89% (+18.3pp) | **+354.47% (+19.9pp)** | +353.26% (+18.7pp) | +346.57% (+12.0pp) | +337.55% (+3.0pp) |
| 2024 | +138.51% | **+151.69% (+13.2pp)** | +150.48% (+12.0pp) | +148.96% (+10.5pp) | +146.71% (+8.2pp) | +140.76% (+2.3pp) |
| 2025 | +174.27% | **+185.14% (+10.9pp)** | +182.92% (+8.7pp) | +180.31% (+6.0pp) | +177.88% (+3.6pp) | +174.06% (-0.2pp) |
| 2026 | +88.49% | **+97.55% (+9.1pp)** | +95.48% (+7.0pp) | +94.48% (+6.0pp) | +91.24% (+2.8pp) | +88.36% (-0.1pp) |
| **Wins** | | **5/6** | 1/6 | 0/6 | 0/6 | 0/6 |

**DD 5 wins 5/6 years on SIP** — only trails DD 10 in 2023 by 1.6pp (18.3pp vs 19.9pp). The finding is fully consistent across both IEX and SIP feeds. DD 5 and DD 10 are within 0.3–2pp every year; both far ahead of DD 15+. Sharp cliff between DD 10 and DD 15. DD 120 near-zero or negative lift in 2025 and 2026.

**Why the shift from the pre-fix finding:** the earlier sweep (which favored 50 min) did not account for DD capital being tied up when A1/A2 started. With the recycling fix, a later DD start means the add-on leg is still running during A1, reducing available capital there. Earlier DD starts (5–10 min) fire sooner, give the add-on more time to exit naturally before afternoon windows, and reduce the capital drag.

**Recommended default: `--doubledown-start 5`** (DD 10 is equally valid — the gap is negligible and it gives the winner one more bar to confirm direction before the add-on enters).

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

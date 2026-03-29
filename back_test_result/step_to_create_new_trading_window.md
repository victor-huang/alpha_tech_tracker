# Steps to Evaluate and Add a New Intraday Trading Window

This document captures the end-to-end process we follow to evaluate whether a new intraday trading window is worth adding to the multi-window strategy alongside existing windows (M1, A1, A2, etc.).

---

## Overview

A "trading window" is a specific time-of-day configuration defined by:
- **Opening start time** — when the opening range begins (e.g., `09:30`, `13:15`, `15:00`)
- **Opening bars** — how many 5-minute bars form the opening range (e.g., 1 bar = 5 min, 3 bars = 15 min)
- **Entry time** — when the trade fires = start + (bars × 5 min)

Adding a new window is worth it only if:
1. It has positive EV on its own (over a long enough sample period)
2. It contributes independent signal relative to existing windows
3. It adds value in the combined multi-window capital simulation

---

## Step 1 — Sweep Candidate Opening Times and Bar Widths

Before committing to a specific config, run a broad sweep to find which time-of-day and bar-width combinations produce positive EV.

### 1a. Axis 1 — Start time sweep (fix bars = 3)

Run the backtest across all candidate start times with a fixed 3-bar (15-min) window:

```bash
for start in 09:30 09:45 10:00 10:15 10:30 11:15 13:00 13:15 13:30 14:00 14:30 15:00; do
  python op_momentum_selector_backtest.py \
    --start YYYY-01-01 --end YYYY-MM-DD \
    --regime-filter --regime-ma 8 --weights 50 30 20 \
    --opening-start $start --opening-bars 3
done
```

**What to look for**: Total return and EV/trade. Any start time with negative total return over 12+ months is ruled out. Focus on the top 3–4 candidates.

### 1b. Axis 2 — Bar width sweep (top candidates from 1a)

For the top 2–3 start times from Axis 1, sweep bar widths (1, 2, 3, 4, 6):

```bash
for bars in 1 2 3 4 6; do
  python op_momentum_selector_backtest.py \
    --start YYYY-01-01 --end YYYY-MM-DD \
    --regime-filter --regime-ma 8 --weights 50 30 20 \
    --opening-start HH:MM --opening-bars $bars
done
```

**What to look for**: The config with the highest return AND a stable win rate. Highly bar-width-sensitive configs (e.g., 1-bar +56% vs 4-bar +10%) are noisier signals — note this when deciding between candidates.

### Selection criteria

| Metric | Minimum bar |
|---|---|
| Total return (1 year sample) | > +20% |
| EV/trade | > 0 (negative EV gate applied by selector) |
| Win rate | Directionally positive vs. random |
| Sample size | > 200 trades over the test period |

---

## Step 2 — Validate Over a Longer Period

A single month or quarter can be noise. Before proceeding, validate the best config over at least 12–15 months:

```bash
python op_momentum_selector_backtest.py \
  --start 2025-01-01 --end 2026-03-28 \
  --regime-filter --regime-ma 8 --weights 50 30 20 \
  --opening-start HH:MM --opening-bars N
```

**Pass/fail**: If the window loses money or drops below +15% over the validation period, discard it. If it holds up, proceed to overlap analysis.

---

## Step 3 — Overlap Analysis vs Existing Windows

A new window that picks the same tickers as an existing window every day adds little value — you'd be doubling exposure without diversification. Run an overlap analysis to measure how independent the new window's signals are.

### Run both windows in a single backtest

```bash
python op_momentum_selector_backtest.py \
  --start 2025-01-01 --end 2026-03-28 \
  --regime-filter --regime-ma 8 --weights 50 30 20 \
  --window EXISTING HH:MM N --window NEW HH:MM N
```

Then inspect the `backtest_result/<window_name>/OVERLAP_ANALYSIS.md` (or generate one from the logs) comparing:

| Metric | Good | Concerning |
|---|---|---|
| Zero-overlap days | > 30% | < 15% |
| Rank-1 agreement | < 25% | > 40% |
| Avg shared tickers/day | < 1.0 | > 1.5 |

**Interpretation**: Morning vs afternoon pairs tend to be the most independent (42–49% zero overlap). Two morning windows at the same start time will be more correlated (25–30% zero overlap is typical) — this is acceptable if their EV differs and they fire at different bar widths.

---

## Step 4 — Combined Capital Simulation (No-Compound)

Add the new window to the existing multi-window configuration and compare total return using **no-compound mode** (daily $10k reset). This isolates the per-day strategy edge regardless of compounding sequence effects.

```bash
# Existing combo (baseline)
python op_momentum_selector_backtest.py \
  --start 2025-01-01 --end 2026-03-28 \
  --regime-filter --regime-ma 8 --weights 50 30 20 \
  --window M1 09:30 3 --window A1 13:15 1 --window A2 15:00 1 \
  --morning-split 100

# With new window added
python op_momentum_selector_backtest.py \
  --start 2025-01-01 --end 2026-03-28 \
  --regime-filter --regime-ma 8 --weights 50 30 20 \
  --window M1 09:30 3 --window A1 13:15 1 --window A2 15:00 1 --window NEW HH:MM N \
  --morning-split 100
```

**Key invariant to verify**: The existing windows' cap P&L must be identical before and after adding the new window. If M1's cap P&L changes, there is a bug or flag mismatch — see [Backtest Comparison Pitfalls](../memory/feedback_backtest_comparison_pitfalls.md). Non-overlapping windows are strictly additive.

**Pass/fail**: The new combo's total return must exceed the baseline. Even a small gain (+5–10pp) is meaningful if the window is consistently positive and doesn't hurt existing windows.

---

## Step 5 — Determine Window Position in the Capital Chain

The order of windows in `--window` determines the capital flow:

- **First group** (simultaneous): windows listed before the split count in `--morning-split`. Each gets `portfolio × split[i]` deployed at the same time.
- **Sequential** (remaining): each window after the first group inherits all returned capital (principal + P&L) from the prior window.

### Placement rules

| New window type | Recommended position | Rationale |
|---|---|---|
| Morning (9:30–10:00 range) | First group, allocate 100% | Highest EV, gets full capital |
| Midday / early afternoon (12:00–14:00) | First sequential window | Captures post-lunch directional move after morning exits |
| Late afternoon / power hour (14:30–16:00) | Last sequential window | Capital arrives from earlier windows; smaller P&L but fully additive |

**Current stack** (reference):

```
M2: 09:30 / 1 bar  → first group (100%)
A1: 13:15 / 1 bar  → sequential 1
A2: 15:00 / 1 bar  → sequential 2
```

---

## Step 6 — Multi-Year Validation (No-Compound, Per-Year)

Run each year independently (no-compound) to confirm the new window adds value across different market regimes, not just in a single favorable year:

```bash
for year in 2021 2022 2023 2024 2025; do
  python op_momentum_selector_backtest.py \
    --start ${year}-01-01 --end ${year}-12-31 \
    --regime-filter --regime-ma 8 --weights 50 30 20 \
    --window M1 09:30 3 --window NEW HH:MM N \
    --morning-split 100
done
```

**Pass/fail**: The new combo should beat the baseline (without the new window) in at least 4 of 6 years. If it hurts in multiple years, it is regime-dependent and should be used only conditionally (or not at all).

---

## Step 7 — Compound Growth Projection (Optional)

Once the new window passes Steps 1–6, run a single continuous compound run from 2021 to present to visualize the long-term growth impact:

```bash
python op_momentum_selector_backtest.py \
  --start 2021-01-01 --end 2026-03-28 \
  --regime-filter --regime-ma 8 --weights 50 30 20 \
  --window ... --morning-split ... \
  --compound
```

Compare year-end portfolio values to the current best config (`M2+A1+A2`). This is a growth *projection*, not an evaluation metric — the per-day edge (Steps 1–6) is the ground truth.

---

## Step 8 — Document the Finding

Add results to `back_test_result/FINDINGS.md`:

- **Finding N** — title the finding with the window config and date range
- Include the sweep table (Axis 1 and Axis 2 results)
- Include the overlap statistics vs existing windows
- Include the combined capital simulation results (no-compound total return comparison)
- Include multi-year validation table
- Mark next steps

Also update `SUMMARY.md` if the new window changes the recommended live trading config.

---

## Decision Checklist

Before adding a new window to the live trading config:

- [ ] Positive EV/trade over 12+ months (Step 1–2)
- [ ] Zero-overlap > 30% vs most-correlated existing window (Step 3)
- [ ] Combined total return beats baseline in no-compound simulation (Step 4)
- [ ] Existing window cap P&L unchanged when new window added (Step 4 — additivity check)
- [ ] Beats baseline in 4+ of 6 years across regimes (Step 6)
- [ ] Window position in capital chain is correct (Step 5)
- [ ] Finding documented in FINDINGS.md (Step 8)

---

## Reference: Current Window Stack

| Label | Config | Entry | EV/trade | Win rate | Position |
|---|---|---|---|---|---|
| M2 | 09:30 / 1 bar | 9:35 AM | +0.468% | 32% | First (100%) |
| A1 | 13:15 / 1 bar | 1:20 PM | +0.194% | 24% | Sequential 1 |
| A2 | 15:00 / 1 bar | 3:05 PM | +0.135% | 26% | Sequential 2 |

Conservative alternative: replace M2 with M1 (09:30 / 3 bars, 37% WR) for higher win rate at slightly lower EV/trade.

## Reference: CLI Flag Summary

| Flag | Purpose |
|---|---|
| `--window LABEL HH:MM BARS` | Define a trading window (repeat for each) |
| `--morning-split PCT [PCT ...]` | Split % for simultaneous first group (e.g., `100` or `60 40`) |
| `--compound` | Carry portfolio over days (growth projection) |
| `--regime-filter --regime-ma 8` | Apply QQQ MA8 bearish regime filter (recommended) |
| `--weights 50 30 20` | Position sizing by rank (recommended) |
| `--show-execution-log` | Print per-day window execution detail |

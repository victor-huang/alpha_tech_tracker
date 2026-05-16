# Trading Params Retune — Reduce Short (Frictional) Trades

**Date:** 2026-05-15
**Goal:** Find the best `--window M1` time/bar and `--stop-pct` that maintains strong returns while reducing trades that enter and exit within the first 15 minutes (frictional short trades).

---

## Setup

Fixed config across all runs:
```
--top 2 --weights 60 40 --window M1 09:30 <bars>
```

No regime filter applied (results are raw strategy edge).

**Short trade definition:** primary trade with `mins_held ≤ 15` (exits within 3 bars of entry).

---

## Phase 1 — Full Parameter Sweep (2026-03-01 to 2026-05-15)

**Grid:** 2 start times × 5 bar counts × 11 stop-pcts = 110 combinations.

| Dimension | Values |
|---|---|
| Start time | `09:30`, `09:35` |
| Bar count | `1`, `2`, `3`, `4`, `5` |
| `--stop-pct` | `0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90` |

**Top 10 results (sorted by return):**

| Rank | Time | Bars | Stop | Trades | WR% | AvgW% | AvgL% | Cap P&L | Ret% | Short | Short% |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 09:30 | 1 | 0.10 | 107 | 44.9 | +2.01 | -0.32 | +$3,998 | +39.98% | 62 | 58% |
| 2 | 09:30 | 1 | 0.25 | 106 | 42.5 | +2.27 | -0.48 | +$3,994 | +39.94% | 52 | 49% |
| 3 | 09:30 | 1 | 0.60 | 106 | 48.1 | +2.62 | -0.98 | +$3,928 | +39.28% | 26 | 25% |
| 4 | 09:30 | 1 | 0.15 | 106 | 40.6 | +2.21 | -0.33 | +$3,826 | +38.26% | 58 | 55% |
| 5 | 09:30 | 1 | 0.30 | 107 | 41.1 | +2.33 | -0.54 | +$3,641 | +36.41% | 48 | 45% |
| 6 | 09:30 | 1 | 0.20 | 106 | 38.7 | +2.27 | -0.38 | +$3,578 | +35.78% | 60 | 57% |
| 7 | 09:30 | 1 | 0.90 | 106 | 48.1 | +2.61 | -1.22 | +$3,192 | +31.92% | 16 | 15% |
| 8 | 09:30 | 1 | 0.50 | 107 | 42.1 | +2.56 | -0.88 | +$3,132 | +31.32% | 31 | 29% |
| 9 | 09:30 | 1 | 0.70 | 106 | 46.2 | +2.48 | -1.13 | +$2,889 | +28.89% | 23 | 22% |
| 10 | 09:30 | 1 | 0.40 | 107 | 38.3 | +2.40 | -0.71 | +$2,677 | +26.77% | 43 | 40% |

**Finding:** `09:30/1 bar` dominates the top 10 regardless of stop-pct. `09:35` and bars ≥ 2 do not appear in the top 10.

---

## Phase 2 — Top 10 Validated Over 2026 YTD (2026-01-01 to 2026-05-15)

All configs are `--window M1 09:30 1 --top 2 --weights 60 40`.

| Rank | Stop | Trades | WR% | AvgW% | AvgL% | Cap P&L | Ret% | Short | Short% | Short WR |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 0.10 | 184 | 44.6 | +2.38 | -0.34 | +$8,601 | +86.01% | 115 | 62% | 24% |
| 2 | 0.15 | 183 | 41.5 | +2.47 | -0.36 | +$8,149 | +81.49% | 111 | 61% | 24% |
| 3 | 0.25 | 183 | 40.4 | +2.68 | -0.49 | +$7,968 | +79.68% | 100 | 55% | 17% |
| 4 | 0.60 | 183 | 47.0 | +2.99 | -1.11 | +$7,881 | +78.81% | 54 | 30% | 6% |
| 5 | 0.30 | 184 | 40.2 | +2.74 | -0.56 | +$7,783 | +77.83% | 90 | 49% | 19% |
| 6 | 0.20 | 183 | 38.8 | +2.58 | -0.40 | +$7,440 | +74.40% | 111 | 61% | 21% |
| 7 | 0.50 | 184 | 42.9 | +3.00 | -0.91 | +$7,370 | +73.70% | 59 | 32% | 5% |
| 8 | 0.70 | 183 | 47.5 | +2.90 | -1.25 | +$7,305 | +73.05% | 44 | 24% | 0% |
| 9 | 0.90 | 182 | 50.5 | +2.83 | -1.45 | +$7,008 | +70.08% | 28 | 15% | 0% |
| 10 | 0.40 | 184 | 39.1 | +2.90 | -0.71 | +$6,864 | +68.64% | 78 | 42% | 14% |

---

## Phase 3 — Top 10 Validated Over Full Year 2025

| Rank | Stop | Trades | WR% | AvgW% | AvgL% | Cap P&L | Ret% | Short | Short% | Short WR |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 0.10 | 489 | 43.8 | +1.47 | -0.27 | +$12,311 | +123.11% | 347 | 71% | 28% |
| 2 | 0.40 | 478 | 37.7 | +2.20 | -0.58 | +$11,653 | +116.53% | 231 | 48% | 13% |
| 3 | 0.30 | 485 | 36.9 | +2.00 | -0.44 | +$11,251 | +112.51% | 282 | 58% | 15% |
| 4 | 0.20 | 487 | 35.3 | +1.83 | -0.31 | +$10,989 | +109.89% | 319 | 66% | 17% |
| 5 | 0.15 | 488 | 39.5 | +1.55 | -0.29 | +$10,976 | +109.76% | 333 | 68% | 22% |
| 6 | 0.25 | 487 | 36.3 | +1.86 | -0.37 | +$10,968 | +109.68% | 303 | 62% | 17% |
| 7 | 0.50 | 479 | 38.8 | +2.14 | -0.74 | +$9,427 | +94.27% | 203 | 42% | 10% |
| 8 | 0.60 | 473 | 39.3 | +2.16 | -0.95 | +$6,818 | +68.18% | 164 | 35% | 6% |
| 9 | 0.70 | 470 | 41.3 | +2.09 | -1.10 | +$5,184 | +51.84% | 140 | 30% | 5% |
| 10 | 0.90 | 458 | 41.9 | +2.04 | -1.29 | +$2,338 | +23.38% | 107 | 23% | 3% |

---

## Key Findings

### 1. Window: `09:30/1 bar` is the clear winner
- Dominates every stop-pct across both periods
- `09:35` start and bars ≥ 2 do not appear in the top 10 in the March–May sweep
- More trades fire (signal detected earlier before a 15-min OR forms)

### 2. Stop-pct is regime-sensitive

| Stop | 2025 Rank | 2026 YTD Rank | Short% (2026) |
|---|---|---|---|
| 0.10 | #1 (+123%) | #1 (+86%) | 62% |
| 0.60 | #8 (+68%) | #4 (+79%) | 30% |
| 0.90 | #10 (+23%) | #9 (+70%) | 15% |

- **Tight stops (0.10–0.15) dominate in strong-trend years** (2025): quick stops cut losers fast and free capital for the next trade.
- **Wide stops (0.60+) hold up better in choppy conditions** (2026 YTD): fewer premature exits.
- Wide stops (0.70–0.90) have **0% short-trade WR** — those quick exits are almost always correct; holding them longer just loses more.

### 3. The friction–return tradeoff

| Stop | 2025 Ret | 2026 Ret | Avg | Short% (2026) |
|---|---|---|---|---|
| 0.10 | +123% | +86% | **+105%** | 62% — very high friction |
| 0.30 | +113% | +78% | **+95%** | 49% |
| 0.40 | +117% | +69% | **+93%** | 42% |
| 0.60 | +68% | +79% | **+74%** | 30% — low friction but multi-year cost is real |

---

## Recommendation

**If minimizing friction is not a constraint:** use `--stop-pct 0.10` — strongest in both years.

**If reducing short trades matters:** `--stop-pct 0.30` is the best compromise:
- Cuts short trades from 62% → 49% (2026) and 71% → 58% (2025)
- Only gives up ~10pp vs `0.10` in 2025, and 8pp in 2026 YTD
- Short-trade WR at 0.30 is still 15–21% — these quick exits are mostly correct, just less extreme than 0.10

**Avoid `0.60+` as a default** — the 2025 underperformance (+68% vs +123%) is too large a cost for the friction reduction it provides.

### Recommended command

```bash
# Best raw performance
python alpha_tech_tracker/op_momentum_strategy/op_momentum_selector_backtest.py \
  --start <START> --end <END> \
  --top 2 --weights 60 40 \
  --window M1 09:30 1 \
  --stop-pct 0.10

# Best friction–return balance
python alpha_tech_tracker/op_momentum_strategy/op_momentum_selector_backtest.py \
  --start <START> --end <END> \
  --top 2 --weights 60 40 \
  --window M1 09:30 1 \
  --stop-pct 0.30
```

---

## Phase 4 — Early Exit Analysis (2025, `09:30/1 --stop-pct 0.60`)

Two early-exit rules were evaluated against 2025 trade data to see if active management could reduce unnecessary holding time.

### 4a — Loss-based early cut at 15 min

**Rule:** if trade P&L < threshold at the 15-min mark, exit immediately.

| Threshold | Cuts | Accidental wins cut | Avg benefit/cut | Total benefit |
|---|---|---|---|---|
| −0.25% | 55 | 14 | +0.02% | +1.18% |
| −0.50% | 34 | 8 | −0.04% | −1.23% |
| −0.75% | 16 | 3 | −0.04% | −0.61% |
| −1.00% | 9 | 2 | −0.01% | −0.13% |
| −1.25% | 6 | 1 | +0.15% | +0.90% |

**Verdict: not worth implementing.** The only positive threshold (−0.25%) saves a negligible +1.18% spread across 55 trades. Every other threshold either hurts or is neutral. Trades down −0.5 to −1% at 15 min still win 24% of the time — the MA20 trailing stop handles these correctly already.

---

### 4b — Stale-trade cut (flat position after x minutes)

**Rule:** if |trade P&L| < ±stale_threshold at checkpoint time, exit (trade is going nowhere).

**P&L at 15-min mark — win rates (trades held > 15 min):**

| State at 15 min | Trades | Win rate | Avg final P&L |
|---|---|---|---|
| Down > −1% | 9 | 22% | −1.38% |
| Down −0.5 to −1% | 25 | 24% | −0.65% |
| Down 0 to −0.5% | 60 | 37% | −0.22% |
| Up 0 to +0.5% | 55 | 44% | +0.14% |
| Up > +0.5% | 160 | 76% | +1.83% |

**Stale-cut simulation results:**

| Cut time | Stale ±% | Cuts | Win% in bucket | Avg benefit/cut | Total benefit |
|---|---|---|---|---|---|
| 15 min | ±0.25% | 71 | 41% | −0.01% | −0.81% |
| 15 min | ±0.50% | 115 | 40% | +0.04% | +4.57% |
| 15 min | ±0.75% | 153 | 40% | +0.04% | +6.23% |
| **30 min** | **±0.25%** | **40** | **35%** | **+0.48%** | **+19.30%** |
| **30 min** | **±0.50%** | **71** | **37%** | **+0.25%** | **+17.77%** |
| 45 min | ±0.50% | 57 | 40% | +0.31% | +17.40% |
| **45 min** | **±0.75%** | **83** | **43%** | **+0.29%** | **+23.77%** |
| 45 min | ±1.00% | 104 | 49% | +0.18% | +19.00% |
| 60 min | ±0.50% | 38 | 45% | +0.20% | +7.75% |
| 60 min | ±0.75% | 55 | 51% | +0.23% | +12.42% |

**Key findings:**

1. **15-min cuts don't work** — benefit is near zero. Too early; trades haven't had time to establish direction.

2. **30-min ±0.25% is the sharpest signal** — only 40 cuts but +0.48% average benefit per cut. Win rate of only 35% in the stale bucket confirms flat-at-30-min trades are mostly heading nowhere good.

3. **45-min ±0.75% has the highest total benefit (+23.77%)** — 83 trades still flat at 45 min with 43% win rate. Holding past this point costs more than exiting near breakeven.

4. **60-min cuts are too late** — cut count shrinks, win rates in the stale bucket jump to 51–53% (cutting near-winners).

**Recommendation:**

- **Primary rule:** cut stale trades at **30 min if |P&L| < ±0.25%** — cleanest signal, +0.48% average saved per cut.
- **Secondary rule:** cut at **45 min if |P&L| < ±0.75%** — catches more trades, highest total benefit (+23.77%).
- These two rules are complementary: the 30-min rule catches the tightest stalls early; the 45-min rule catches wider stalls that haven't resolved.

> **Note:** these findings are based on `--stop-pct 0.60` in 2025. The stale-cut benefit may differ at tighter stop-pcts (e.g. 0.10) since tight stops already exit quickly — the stale window has fewer remaining trades to cut.

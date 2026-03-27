# op_momentum_strategy — Backtest Findings

## Strategy Overview

**Opening Range Momentum** — trades the breakout of the first N×5-min bars each day.
- BULLISH: close above OR_high → enter long
- BEARISH: close below OR_low bottom-30% → enter short
- Default: `opening_bars=3` (15-min OR), `stop_pct=0.15`, `trailing_ma=ma20`

**Capital simulation**: $10,000 initial, weighted 50%/30%/20% × 3 slots ($5,000/$3,000/$2,000), fully compounding. See Finding 8.

**Ticker pool v2** (updated 2026-03, see Finding 5):
`SNDK, APP, SHOP, CVNA, AMD, META, EXPE, FANG, ISSC, FN, UI, MU, ANAB, PLTR, COIN, NVDA`

---

## Feature Flags

| Flag | Default | Effect |
|---|---|---|
| `--trailing-ma ma20` | ma20 | MA20 trailing stop (better than ma50 or both) |
| `--stop-pct 0.15` | 0.15 | Hard stop as fraction of OR range |
| `--opening-bars 3` | 3 | 15-min opening window |
| `--armed-ma20-exit` | off | Replace hard_stop with MA20 once armed (opt-in) |
| `--max-loss-pct` | off | Absolute per-trade loss cap |
| `--regime-filter` | off | Skip BULLISH signals when QQQ < regime_ma-day MA |
| `--regime-ma 8` | 5 | N-day MA used for QQQ regime filter |

---

## Finding 1 — MA20 Trailing Stop Outperforms MA50 and "Both"

Tested across 2021–2025. MA20 trailing stop captures more of the move than MA50 and filters noise better than running both simultaneously. **MA20 is the default.**

---

## Finding 2 — Regime Filter (QQQ MA8) Improves Risk-Adjusted Returns

**Method**: Skip BULLISH entries on days when QQQ daily close is below its 8-day MA.
Run command: `--regime-filter --regime-ma 8`

### 5-Year Comparison (2021–2025, top-3 selector, 60d rolling, stop-pct 0.15, MA20)

| Year | no_regime Return | regime8 Return | Δ Return | no_regime EV | regime8 EV | Δ EV |
|---|---|---|---|---|---|---|
| 2021 | +55.57% | +57.78% | **+2.21pp** | +0.234% | +0.266% | +0.03pp |
| 2022 | +97.61% | +96.47% | -1.14pp | +0.436% | +0.508% | **+0.07pp** |
| 2023 | +50.02% | +55.53% | **+5.51pp** | +0.212% | +0.257% | +0.05pp |
| 2024 | +27.65% | +29.82% | **+2.17pp** | +0.125% | +0.154% | +0.03pp |
| 2025 | +72.68% | +79.82% | **+7.14pp** | +0.310% | +0.381% | **+0.07pp** |

### Per-Trade Quality (SELECTED block, regime8 vs no_regime)

| Year | Trades (no) | Trades (r8) | Δ Trades | WinRate (no) | WinRate (r8) | AvgWin (no) | AvgWin (r8) | AvgLoss (no) | AvgLoss (r8) |
|---|---|---|---|---|---|---|---|---|---|
| 2021 | 712 | 652 | -60 | 31% | 32% | +1.39% | +1.38% | -0.29% | -0.27% |
| 2022 | 672 | 570 | -102 | 35% | 35% | +2.03% | +2.20% | -0.42% | -0.39% |
| 2023 | 708 | 648 | -60 | 31% | 32% | +1.37% | +1.43% | -0.32% | -0.30% |
| 2024 | 664 | 581 | -83 | 29% | 29% | +1.04% | +1.12% | -0.28% | -0.25% |
| 2025 | 703 | 629 | -74 | 36% | 36% | +1.55% | +1.67% | -0.38% | -0.36% |

### Key Observations

- **4/5 years improved** in absolute return; 2022 dipped -1.14pp but EV improved +0.07pp (already the best year)
- **EV improved every single year** — consistent quality improvement regardless of return
- **Avg loss consistently lower** — regime filter cuts the worst losing trades in downtrends
- **60–102 fewer trades per year** — less churn, fewer forced bad trades
- **Biggest wins in trending years**: 2023 (+5.51pp) and 2025 (+7.14pp) when QQQ had clear regime shifts

### Conclusion

`--regime-filter --regime-ma 8` is the **recommended default** for live trading and backtests.
- 5-year total: no_regime ~+303% vs regime8 ~+319% — net +16pp over 5 years
- Strictly better EV every year; lower avg losses every year
- The only cost is ~70 fewer trades/year (lower commissions, less monitoring needed)

---

## Finding 3 — Armed MA20 Exit (opt-in, NOT recommended by default)

`--armed-ma20-exit`: once the hard_stop_price is crossed (trade is "armed"), replaces
the fixed hard_stop exit with the MA20 trailing stop to let winners run.

**Result (March 2026 test)**: Avg wins grew +1.07% → +1.55%, but avg losses nearly
doubled -0.42% → -0.80% in a choppy market. Net return collapsed +3.96% → +0.21%.

**Trade-off**: Helps in trending markets, hurts in choppy/reversal conditions.
Keep off by default. Only activate in confirmed trending regimes.

---

## Finding 4 — March 2026 Low Returns (+3.96%) Root Cause Analysis

March 2026 was a QQQ downtrend month. Root causes of low +3.96% return:
1. **7 hard_stop exits capping wins** at only +0.10–0.40% (breakouts that reversed fast)
2. **Avg win collapsed to +1.07%** vs historical +1.37–2.03%
3. **4 days of 0W/3L** (Mar 3, 6, 13, 19) during QQQ downleg
4. **ISSC outlier loss -2.38%** on Mar 13

Regime filter (MA5) reduced avg loss from -0.42% → -0.33% and improved EV. Use `--regime-filter --regime-ma 8` to mitigate downtrend risk.

---

## Finding 5 — New Ticker Discovery: PLTR, COIN, NVDA Added to Pool

**Process**: screened 12 high-momentum candidates (NVDA, TSLA, PLTR, COIN, MSTR, ARM, RKLB, HOOD, SMCI, CRWD, NFLX, ORCL) against a 30-day window (Feb 23 – Mar 25, 2026) then confirmed the top 5 with a 90-day window (Dec 26, 2025 – Mar 25, 2026).

### 30-Day Screen Results (ranked by Net P&L, regime filter on)

| Ticker | Signals | WinRate | Net P&L | Win P&L | Loss P&L | Notes |
|---|---|---|---|---|---|---|
| COIN | 7 | 14% | +$14.15 | +$17.63 | -$3.48 | Huge bearish asymmetry |
| NVDA | 9 | 44% | +$6.16 | +$6.51 | -$0.35 | Best WR, tiny losses |
| MSTR | 6 | 33% | +$2.20 | +$3.30 | -$1.10 | Bullish-biased |
| NFLX | 10 | 40% | +$2.00 | +$4.34 | -$2.34 | Strong bearish (75%) |
| PLTR | 8 | 38% | +$1.26 | +$3.49 | -$2.23 | Solid bear (50%) |
| ARM | 6 | 33% | +$1.10 | +$1.92 | -$0.82 | OK |
| SMCI | 7 | 29% | +$0.80 | +$1.14 | -$0.34 | Weak |
| TSLA | 8 | 25% | +$0.64 | +$2.31 | -$1.67 | Weak |
| RKLB | 10 | 30% | -$0.30 | +$3.25 | -$3.55 | Skip |
| HOOD | 6 | 33% | -$0.38 | +$0.99 | -$1.37 | Skip |
| CRWD | 9 | 22% | -$0.88 | +$10.86 | -$11.74 | Skip (huge losses) |
| ORCL | 7 | 29% | -$0.70 | +$0.92 | -$1.62 | Skip |

### 90-Day Confirmation Results (Dec 26, 2025 – Mar 25, 2026, regime filter on)

| Ticker | Total | W/L | WinRate | Net P&L | AvgWin$ | AvgLoss$ | Bull | Bear | EV$/sig |
|---|---|---|---|---|---|---|---|---|---|
| PLTR | 22 | 9/13 | 41% | +$21.54 | +$2.96 | -$0.39 | 3/9 | 6/13 | +$0.98 |
| COIN | 18 | 3/15 | 17% | +$17.95 | +$8.98 | -$0.60 | 0/4 | 3/14 | +$1.03 |
| MSTR | 19 | 7/12 | 37% | +$10.67 | +$2.02 | -$0.29 | 4/6 | 3/13 | +$0.57 |
| NVDA | 22 | 6/16 | 27% | +$7.21 | +$1.56 | -$0.14 | 3/10 | 3/12 | +$0.32 |
| NFLX | 26 | 10/16 | 38% | +$4.61 | +$0.81 | -$0.22 | 3/10 | 7/16 | +$0.17 |

**Key observations:**
- **COIN**: low win rate (17%) but extreme asymmetry — avg win +$8.98 vs avg loss -$0.60; mostly bearish signal (0/4 bull, 3/14 bear). Works best in market selloffs.
- **PLTR**: best overall — 41% WR, highest net P&L, both directions working
- **NVDA**: lowest avg loss (-$0.14/trade); bullish and bearish balanced
- **MSTR**: strong bull signal (4/6 = 67%), weak bear (3/13 = 23%)

### March 2026 Impact (selector backtest, expanded pool vs original)

| Pool | Return | WinRate | AvgWin | AvgLoss | EV/trade | vs QQQ |
|---|---|---|---|---|---|---|
| Original 13-ticker (no regime) | +3.96% | — | — | — | — | vs -3.33% |
| Original 13-ticker + regime8 | ~+3.04% | — | — | — | — | vs -3.33% |
| 16-ticker pool v2 + regime8 | **+7.24%** | 45% | +1.65% | -0.36% | +0.543% | vs -3.33% |

Key day: Mar 24, COIN bearish breakout → +$17.63/share (+8.90%), driving +3.14% single-day return.

### 5-Year Validation (pool v2 vs original with regime8)

| Year | Original regime8 | Pool v2 regime8 | Δ |
|---|---|---|---|
| 2021 | +57.78% | +54.91% | -2.87pp |
| 2022 | +96.47% | +103.03% | **+6.56pp** |
| 2023 | +55.53% | +70.06% | **+14.53pp** |
| 2024 | +29.82% | +23.91% | -5.91pp |
| 2025 | +79.82% | +78.56% | -1.26pp |
| **5yr** | **+319%** | **+330%** | **+11pp net** |

### Conclusion

**PLTR, COIN, NVDA added permanently to `DEFAULT_TICKERS`.** Net 5-year gain +11pp over the original pool. The tickers excel in volatile/bearish conditions and add meaningful upside in the two strongest years (2022, 2023) while causing small underperformance in the others.

MSTR and NFLX showed individual promise but were excluded from the permanent pool because they did not consistently improve annual returns across the full 5-year validation.

---

## Finding 6 — Sector Screen: Financials & Healthcare Show Strong Individual Performance

**Sectors screened**: Commodity ETFs, Energy, Financials, Healthcare/Biotech, Materials, Leveraged ETFs (32 tickers total).
**Method**: same 30-day → 90-day pipeline used in Finding 5.

### 30-Day Screen Top 10 (Feb 23 – Mar 25, 2026, regime filter MA8)

| Group | Ticker | WR | Net P&L | EV$/sig | Notes |
|---|---|---|---|---|---|
| Financials | GS | 50% | +$43.95 | +$7.48 | Enormous avg win $12.97 |
| Healthcare | REGN | 67% | +$23.87 | +$4.64 | Best win rate in entire screen |
| Healthcare | VRTX | 50% | +$11.45 | +$1.73 | Strong bear (5/9) |
| Financials | JPM | 40% | +$8.42 | +$1.50 | Bear-biased (3/7) |
| Financials | BX | 40% | +$6.62 | +$0.87 | Bear dominant (8/21 over 90d) |
| Leveraged | SOXL | 50% | +$4.81 | +$0.86 | Balanced bull/bear |
| Energy | MPC | 43% | +$4.24 | +$1.65 | Bull-dominant (3/3 bull!) |
| Financials | MS | 40% | +$3.95 | +$1.28 | Bear-dominant (2/4) |
| Energy | CVX | 50% | +$2.57 | +$0.68 | Balanced |
| Leveraged | UVXY | 43% | +$2.28 | +$0.49 | OK |

**Eliminated**: GDXJ (0% WR), NEM (0% WR), gold miners (GDX 11% WR), USO (0%), TNA, LABU, COP, XOM

### 90-Day Confirmation Top Results (Dec 26, 2025 – Mar 25, 2026)

| Ticker | WR | Net P&L | AvgWin$ | AvgLoss$ | EV$/sig | Verdict |
|---|---|---|---|---|---|---|
| GS | 35% | +$42.15 | +$9.63 | +$1.42 | +$4.30 | ✓ PASS |
| VRTX | **59%** | +$24.25 | +$2.47 | +$0.88 | +$1.82 | ✓ PASS |
| JPM | 41% | +$20.02 | +$3.50 | +$0.45 | +$1.70 | ✓ PASS |
| REGN | 42% | +$16.09 | +$3.79 | +$1.56 | +$2.50 | ✓ PASS |
| BX | 40% | +$13.64 | +$1.74 | +$0.25 | +$0.85 | ✓ PASS |
| MRNA | 43% | +$7.90 | +$1.10 | +$0.17 | +$0.57 | ✓ PASS |
| MS | 46% | +$4.00 | +$1.02 | +$0.30 | +$0.63 | ✓ PASS |
| CVX | 33% | +$3.08 | +$0.86 | +$0.21 | +$0.42 | ✓ PASS |
| MPC | 28% | +$2.83 | +$2.02 | +$0.56 | +$0.97 | ✓ PASS |
| COP | 25% | -$0.49 | — | — | — | ✗ skip |

### 5-Year Pool Validation

| Pool | 5yr Return | Δ vs Orig |
|---|---|---|
| Orig 13-ticker | +319.42% | — |
| V2 (+ PLTR, COIN, NVDA) | +330.47% | **+11.05pp** ← winner |
| V4 (V2 + GS, REGN) | +329.27% | +9.85pp |
| V3 (V2 + GS, REGN, VRTX, JPM, BX) | +328.35% | +8.93pp |

### Conclusion

**GS and REGN are not added to DEFAULT_TICKERS** despite exceptional individual EV.
Adding them to the 16-ticker V2 pool slightly dilutes the top-3 selection in bull years, reducing 5-year net from +11pp to +9-10pp. The V2 pool (16 tickers) remains the optimal configuration.

**GS and REGN watchlist** — both have EV > $2.50/signal over 90 days. Consider monitoring manually or adding a conditional rule (e.g., include when QQQ is in a downtrend regime, where their bearish signals are most effective).

**Sectors that don't work** for OR momentum strategy:
- Commodity ETFs (GLD, GDX, GDXJ, USO, UNG) — low or zero win rates, mean-reverting behavior
- Most Materials stocks (NEM, FCX, AA) — negative net P&L
- Broad energy names (XOM, COP) — inconsistent

---

## Finding 7 — Top-3 Selection Outperforms Top-5

**Question**: does selecting 5 tickers per day instead of 3 improve returns?

**Method**: 5-year backtest (2021–2025) with V2 pool (16 tickers), regime filter MA8, all other params identical. Capital simulation splits $10,000 equally across N slots ($3,333/slot for top-3, $2,000/slot for top-5).

### Results

| Year | Top-3 | Top-5 | Δ |
|---|---|---|---|
| 2021 | +54.91% | +50.13% | -4.78pp |
| 2022 | +103.03% | +82.14% | **-20.89pp** |
| 2023 | +70.06% | +53.93% | -16.13pp |
| 2024 | +23.91% | +26.09% | +2.18pp |
| 2025 | +78.56% | +62.58% | -15.98pp |
| **5yr** | **+330.47%** | **+274.87%** | **-55.60pp** |

EV/trade is nearly identical (top-3: ~+0.31% avg, top-5: ~+0.29% avg), confirming slots 4–5 have similar per-trade quality. The loss comes entirely from **position sizing**: 5 slots means $2,000/slot vs $3,333/slot, so the same high-conviction winners compound at 60% of the capital. The only year top-5 wins is 2024 (+2.18pp), where broader diversification marginally helped.

### Conclusion

**Top-3 is the optimal selection width.** It enforces quality discipline by concentrating capital in the highest-scoring signals. Adding slots 4 and 5 dilutes rather than diversifies. `--top 3` remains the default.

---

## Finding 8 — Position Weighting 50/30/20 Outperforms Equal Weighting

**Question**: does concentrating capital on the highest-scoring pick (50% rank-1, 30% rank-2, 20% rank-3) improve 5-year returns vs equal 33.3%/slot?

**Method**: 5-year backtest (2021–2025) with V2 pool (16 tickers), regime filter MA8, MA20 trailing stop, stop-pct 0.15. Two runs per year — equal weight (`$3,333/slot × 3`) vs weighted (`50%/30%/20%`).

### Results

| Year | Equal (33/33/33) | Weighted (50/30/20) | Δ |
|---|---|---|---|
| 2021 | +54.91% | +59.92% | +5.01pp |
| 2022 | +103.03% | +108.45% | +5.42pp |
| 2023 | +70.06% | +79.82% | +9.76pp |
| 2024 | +23.91% | +29.50% | +5.59pp |
| 2025 | +78.56% | +78.78% | +0.22pp |
| **5yr** | **+1083.40%** | **+1287.81%** | **+204.41pp** |

### Conclusion

**Weighted 50/30/20 wins every single year**, with the compounding advantage growing significantly over time (+204pp over 5 years). The scoring function correctly identifies the highest-conviction signal as rank-1, and concentrating 50% of capital there amplifies the winner's contribution while the smaller ranks provide diversification. `--weights 50 30 20` is now the recommended default.

**CLI usage**: `--weights 50 30 20`

---

## Log File Index

| File | Description |
|---|---|
| `selector_bt_{year}_no_regime.log` | 2021–2025, MA20 trailing stop, no regime filter |
| `selector_bt_{year}_regime8.log` | 2021–2025, MA20 trailing stop, QQQ MA8 regime filter |
| `march2026_ma20.log` | March 2026, MA20, no regime filter (+3.96%) |
| `march2026_regime_ma5.log` | March 2026, MA20, QQQ MA5 regime filter |
| `march2026_armed_ma20_maxloss2pct.log` | March 2026, armed MA20 exit + max-loss 2% (+0.21%) |
| `selector_bt_{year}_ma20.log` | Earlier runs, MA20, various periods |
| `selector_bt_90d_ma20.log` | 90-day rolling window test |

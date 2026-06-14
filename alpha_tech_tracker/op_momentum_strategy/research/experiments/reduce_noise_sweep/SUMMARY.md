# Reduce Small Trade Noise — Sweep Summary

Full narrative and filter mechanics: `op_momentum_strategy/reduce_small_trade_noise.md`
Per-year log files: `or_range_filter_sweep/`

---

## Background

2026 YTD analysis (Jan 1 – Apr 2, M1+A1+A2, top-2, no-compound) revealed 46% of 250 trades were noise:

| Bucket | Count | % |
|---|---|---|
| Large win (>+0.5%) | 68 | 27% |
| Mid win (+0.2–0.5%) | 17 | 7% |
| Small win (0–+0.2%) | 19 | 8% |
| Zero (0.00%) | 28 | 11% |
| Small loss (0–-0.2%) | 68 | 27% |
| Mid loss (-0.2–-0.5%) | 29 | 12% |
| Large loss (>-0.5%) | 21 | 8% |

Root cause: low OR range → tight stops → entry and exit at nearly the same price, most common in afternoon windows (A1, A2) which reuse the morning OR.

---

## Phase 1 — 2026 Axis Sweep (no reversal, top-2, weights 50/30)

**Baseline**: `--start 2026-01-01 --end 2026-04-02 --top 2 --weights 50 30 --regime-filter --regime-ma 8 --window M1 09:30 3 --window A1 13:15 1 --window A2 15:00 1 --morning-split 100`

**Baseline result**: 333 trades (96W/237L), 29% WR, avg win +1.92%, avg loss -0.12%, EV +0.465%, **+83.27%**

### Axis A — `--min-or-range`

| Run | Threshold | Trades | WR | AvgWin | AvgLoss | EV | Return | RetainedReturn |
|---|---|---|---|---|---|---|---|---|
| A0 | 0.0 (baseline) | 333 (96W/237L) | 29% | +1.92% | -0.12% | +0.465% | +83.27% | 1.00 |
| A1 | 0.5% | 145 (56W/89L) | 39% | +2.54% | -0.26% | +0.819% | +64.31% | 0.77 |
| A2 | 1.0% | 102 (48W/54L) | 47% | +2.78% | -0.37% | +1.114% | +61.32% | 0.74 |
| **A3** | **1.5%** | **96 (48W/48L)** | **50%** | **+2.78%** | **-0.39%** | **+1.195%** | **+62.97%** | **0.76** |
| A4 | 2.0% | 91 (47W/44L) | 52% | +2.73% | -0.40% | +1.215% | +61.52% | 0.74 |
| A5 | 2.5% | 79 (41W/38L) | 52% | +2.45% | -0.45% | +1.057% | +48.72% | 0.59 |

Log files: `A_or_range_0_0.txt` through `A_or_range_2_5.txt`

### Axis B — `--min-score`

| Run | Threshold | Trades | WR | AvgWin | AvgLoss | EV | Return | RetainedReturn |
|---|---|---|---|---|---|---|---|---|
| B0 | 0.0 (baseline) | 333 (96W/237L) | 29% | +1.92% | -0.12% | +0.465% | +83.27% | 1.00 |
| B1 | 0.20 | 320 (93W/227L) | 29% | +1.97% | -0.13% | +0.481% | +82.93% | 1.00 |
| B2 | 0.30 | 277 (80W/197L) | 29% | +2.21% | -0.14% | +0.537% | +80.80% | 0.97 |
| B3 | 0.40 | 237 (72W/165L) | 30% | +2.27% | -0.16% | +0.576% | +74.33% | 0.89 |
| B4 | 0.45 | 208 (65W/143L) | 31% | +2.44% | -0.18% | +0.639% | +72.30% | 0.87 |
| B5 | 0.50 | 194 (61W/133L) | 31% | +2.55% | -0.19% | +0.675% | +71.55% | 0.86 |

Log files: `B_score_0_20.txt` through `B_score_0_50.txt`

### Axis C — `--min-ev`

| Run | Threshold | Trades | WR | AvgWin | AvgLoss | EV | Return | RetainedReturn |
|---|---|---|---|---|---|---|---|---|
| C0 | 0.0 (baseline) | 333 (96W/237L) | 29% | +1.92% | -0.12% | +0.465% | +83.27% | 1.00 |
| C1 | 0.05% | 322 (91W/231L) | 28% | +1.96% | -0.13% | +0.463% | +79.88% | 0.96 |
| C2 | 0.10% | 308 (91W/217L) | 30% | +1.87% | -0.13% | +0.463% | +77.98% | 0.94 |
| C3 | 0.15% | 277 (78W/199L) | 28% | +1.93% | -0.14% | +0.444% | +66.97% | 0.80 |
| C4 | 0.20% | 235 (66W/169L) | 28% | +2.06% | -0.15% | +0.469% | +61.57% | 0.74 |
| C5 | 0.30% | 169 (57W/112L) | 34% | +2.06% | -0.21% | +0.558% | +53.15% | 0.64 |

Log files: `C_ev_0_05.txt` through `C_ev_0_30.txt`

### Axis D — Combinations

| Run | Flags | Trades | WR | AvgWin | AvgLoss | EV | Return | RetainedReturn |
|---|---|---|---|---|---|---|---|---|
| D1 | or≥1.0 + score≥0.50 | 102 (48W/54L) | 47% | +2.78% | -0.37% | +1.114% | +61.32% | 0.74 |
| D2 | or≥1.5 + score≥0.50 | 96 (48W/48L) | 50% | +2.78% | -0.39% | +1.195% | +62.97% | 0.76 |
| D3 | or≥1.0 + ev≥0.30 | 93 (43W/50L) | 46% | +2.45% | -0.38% | +0.930% | +48.38% | 0.58 |
| D4 | or≥1.5 + ev≥0.30 | 88 (43W/45L) | 49% | +2.45% | -0.40% | +0.991% | +48.76% | 0.59 |
| D5 | score≥0.50 + ev≥0.30 | 135 (49W/86L) | 36% | +2.33% | -0.25% | +0.689% | +52.27% | 0.63 |
| D6 | or≥1.0 + score≥0.50 + ev≥0.30 | 93 (43W/50L) | 46% | +2.45% | -0.38% | +0.930% | +48.38% | 0.58 |

Log files: `D1_or1.0_s0.50.txt` through `D6_all.txt`

### Phase 1 Conclusions

- **`--min-or-range` is the only effective filter** — directly targets the root cause (low OR range)
- **Sweet spot: 1.5%** — WR peaks at 50%, EV at +1.195%, better than 2.0% which over-filters
- **`--min-score` and `--min-ev` add no value on top of `--min-or-range`** — high-OR tickers already score well; combining is redundant
- **`--min-ev` alone fails** — EV stays near +0.46% across all thresholds while return drops

---

## Phase 2 — Window Scope Test (2025 full year, with reversal)

**Question**: Which windows should `--min-or-range 1.5` be applied to?

**Params**: `--top 2 --weights 50 30 --regime-filter --regime-ma 8 --window M1 09:30 3 --window A1 13:15 1 --window A2 15:00 1 --morning-split 100 --reversal`

Log files: `rev2_no_filter.txt`, `rev2_or1.5_m1only.txt`, `rev2_or1.5_all.txt`, `rev2_or1.5_bars3.txt`

| Config | Primary | Reversals | WR | EV/trade | Return |
|---|---|---|---|---|---|
| No filter | 1360 (381W/979L) | 485 (207W/278L) | 28% | +0.049% | **+234.86%** |
| M1 only | 1304 (375W/929L) | 454 (196W/258L) | 29% | +0.053% | **+221.09%** |
| A1+A2 only | 451 (155W/296L) | 93 (47W/46L) | 34% | +0.214% | **+151.73%** |
| All windows | 395 (149W/246L) | 62 (36W/26L) | 38% | +0.251% | **+138.01%** |

**Per-window breakdown (A1+A2 filter)**:

| Window | Trades | WR | EV/trade | Cap Return |
|---|---|---|---|---|
| M1 | 446 | 34% | +0.155% | +136.23% |
| A1 | **2** | 100% | +13.25% | +15.30% |
| A2 | **3** | 33% | +0.206% | +0.20% |

**Critical finding**: Applying `--min-or-range 1.5` to A1 or A2 reduces afternoon trades to near-zero (2 A1 + 3 A2 for the entire year). The morning OR is fixed by 9:45 AM and cannot expand — almost no afternoon setup passes a 1.5% threshold. The -83pp return drop is caused by losing the afternoon window contribution entirely, not by filtering noise.

**Do not apply `--min-or-range` to afternoon windows.**

---

## Phase 3 — 5-Year Threshold Comparison (2021–2025, with reversal, M1 only)

**Params**: `--top 2 --weights 50 30 --regime-filter --regime-ma 8 --window M1 09:30 3 --window A1 13:15 1 --window A2 15:00 1 --morning-split 100 --reversal --min-or-range-windows M1`

Log files: `or_range_filter_sweep/{year}_{no_filter|or0.5_m1only|or1.5_m1only}.txt`

### Return by year

| Year | No filter | 0.5% M1 | Δ 0.5% | 1.5% M1 | Δ 1.5% |
|---|---|---|---|---|---|
| 2021 | +142.02% | +141.22% | -0.80pp | +111.00% | **-31.02pp** |
| 2022 | +182.67% | +182.82% | +0.15pp | +180.47% | -2.20pp |
| 2023 | +235.43% | +233.40% | -2.03pp | +219.83% | -15.60pp |
| 2024 | +101.25% | +100.45% | -0.80pp | +98.63% | -2.62pp |
| 2025 | +234.86% | +236.58% | **+1.72pp** | +221.09% | -13.77pp |
| **5-yr total** | **+896.23%** | **+894.47%** | **-1.76pp** | **+831.02%** | **-65.21pp** |

### Trade count by year

| Year | No filter (primary / rev) | 0.5% (primary / rev) | 1.5% (primary / rev) |
|---|---|---|---|
| 2021 | 1403 / 458 | 1397 / 456 | 1322 / 439 |
| 2022 | 1308 / 507 | 1307 / 506 | 1258 / 483 |
| 2023 | 1392 / 463 | 1385 / 458 | 1311 / 427 |
| 2024 | 1380 / 494 | 1377 / 492 | 1294 / 474 |
| 2025 | 1360 / 485 | 1354 / 482 | 1304 / 454 |

### Phase 3 Conclusions

- **`--min-or-range 0.5` is effectively neutral over 5 years** (-1.76pp total, noise-level variation year to year). It only removes 6–8 trades/year — the most degenerate tight-OR setups.
- **`--min-or-range 1.5` costs -65pp over 5 years**, with 2021 taking the biggest hit (-31pp). It is too aggressive for historical data.
- **The 2026 case is an anomaly**: unusually tight-OR market conditions in early 2026 made 1.5% look attractive (+62.97% vs +83.27% but with massive noise reduction). This does not generalize across years.
- **`--min-or-range 0.5` is the safe choice for live options** — removes truly unexecutable setups (OR so tight the option bid/ask spread eats all potential P&L) at essentially zero backtest cost.

---

## Final Recommendation

| Use case | Config |
|---|---|
| Pure backtest / strategy research | No filter |
| Live options — conservative | `--min-or-range 0.5 --min-or-range-windows M1` |
| Live options — aggressive noise cut (2026-style market) | `--min-or-range 1.5 --min-or-range-windows M1` |

**Never apply `--min-or-range` to A1 or A2.** Always use `--min-or-range-windows M1` (or M2) to restrict scope to the morning window.

# BULLISH Re-Entry — Backtest Findings

Config base: M1+A1+A2 windows, regime filter MA8, weights 50/30/20, no-compound.
BRE baseline = `--reversal --bearish-reentry --bearish-reentry-max-bars 3` (no BRU).
BRE+BRU = adds `--bullish-reentry --bullish-reentry-max-bars 5` (default).

```
--regime-filter --regime-ma 8 --weights 50 30 20
--window M1 09:30 3 --window A1 13:15 1 --window A2 15:00 1
--min-or-range 0.5 --min-or-range-windows M1 --morning-split 100
--reversal --bearish-reentry --bullish-reentry
```

---

## Trigger Threshold Sweep (Nov 2025 + Full 2025)

Evaluated three re-entry trigger levels:

| BRU Trigger | Nov 2025 | 2025 Full Year | BRU WR (2025) | BRU Trades (2025) |
|---|---|---|---|---|
| No BRU (BRE only) | +13.87% | +263.19% | — | — |
| `close > or_low + 0.6 × or_range` | +17.88% | +271.07% | 30% | 367 |
| `close > or_low + 0.8 × or_range` | +16.32% | +266.57% | 34% | 342 |
| **`close > or_high` (chosen)** | **+16.77%** | **+269.69%** | **38%** | **306** |

`0.8×` underperforms the BRE-alone baseline. `0.6×` adds return but at 30% WR. `close > or_high` has the best win rate and is the strongest confirmation signal — full OR breakout after the washout.

---

## `--bullish-reentry-max-bars` Sweep (Nov 2025 + Full 2025)

| max-bars | Nov 2025 | 2025 Full Year | BRU Trades (2025) | BRU WR |
|---|---|---|---|---|
| 1 | +16.61% | +268.98% | 259 (98W/161L) | 38% |
| 2 | +16.82% | +268.87% | 291 (110W/181L) | 38% |
| 3 | +16.77% | +269.69% | 306 (116W/190L) | 38% |
| **5 (default)** | **+17.37%** | **+277.66%** | 331 (129W/202L) | **39%** |
| 7 | +17.37% | +274.56% | 348 (134W/214L) | 39% |

max-bars=5 wins both periods. max-bars=7 matches Nov but slightly underperforms 2025. **Default set to 5.**

---

## March 2026

| Config | Return | BRU Trades (W/L) | BRU WR |
|---|---|---|---|
| BRE baseline | +27.04% | — | — |
| BRE + BRU (max-bars=5) | +28.52% | 21 (10W/11L) | 48% |

Delta: **+1.48pp**

---

## 2026 YTD (Jan–Mar)

| Config | Return | BRU Trades (W/L) | BRU WR |
|---|---|---|---|
| BRE baseline | +95.85% | — | — |
| BRE + BRU (max-bars=5) | +98.68% | 46 (18W/28L) | 39% |

Delta: **+2.83pp**

---

## Annual Results — BRE Baseline vs BRE+BRU (max-bars=5)

| Year | BRE Baseline | BRE + BRU | Delta | BRU Trades (W/L) | BRU WR |
|---|---|---|---|---|---|
| 2021 | +161.60% | +174.39% | **+12.79pp** | 307 (114W/193L) | 37% |
| 2022 | +236.41% | +254.61% | **+18.20pp** | 237 (105W/132L) | 44% |
| 2023 | +249.23% | +320.77% | **+71.54pp** | 334 (142W/192L) | 43% |
| 2024 | +136.12% | +159.90% | **+23.78pp** | 279 (114W/165L) | 41% |
| 2025 | +263.19% | +277.66% | **+14.47pp** | 331 (129W/202L) | 39% |

BRU improves return **every single year** from 2021–2025.
Delta ranges from +12.79pp (2021) to +71.54pp (2023).

---

## Key Observations

1. **Consistent improvement every year** — BRU adds value across bear years (2022), bull years (2023, 2024), and mixed years (2021, 2025).

2. **Win rate 37–44%** — Lower than BRE (56–71%) because the trigger requires a full OR breakout after the primary stop-out: a larger round trip than BRE's `close < or_low`.

3. **2023 standout (+71.54pp)** — Strong directional bull year with many intraday washouts followed by OR high breakouts later in the session.

4. **max-bars=5 vs max-bars=3**: gains +1.81 to +7.97pp per year; no year regresses.

5. **Bearish macro (Q1 2026) reduces BRU activity** — 46 BRU trades vs 66 BRE trades in Q1 2026. In downtrends BULLISH primaries fire less and rarely rally back above OR_high.

---

## Recommended Live Config

```bash
python alpha_tech_tracker/op_momentum_strategy/op_momentum_selector_backtest.py \
  --start 2025-01-01 --end 2025-12-31 \
  --regime-filter --regime-ma 8 --weights 50 30 20 \
  --window M1 09:30 3 --window A1 13:15 1 --window A2 15:00 1 \
  --min-or-range 0.5 --min-or-range-windows M1 --morning-split 100 \
  --reversal --bearish-reentry --bullish-reentry
```

(`--bullish-reentry-max-bars` defaults to 5 and does not need to be specified.)

---

## Log Files in This Directory

| File | Description |
|---|---|
| `march2026_bru.log` | March 2026, BRE + BRU max-bars=5 |
| `2026ytd_bru.log` | 2026 Jan–Mar, BRE + BRU max-bars=5 |
| `2021_bru.log` | 2021 full year, BRE + BRU max-bars=5 |
| `2022_bru.log` | 2022 full year, BRE + BRU max-bars=5 |
| `2023_bru.log` | 2023 full year, BRE + BRU max-bars=5 |
| `2024_bru.log` | 2024 full year, BRE + BRU max-bars=5 |
| `2025_bru.log` | 2025 full year, BRE + BRU max-bars=5 |

BRE-only baselines are in `../bearish_reentry/` (files ending `_m1a1a2_bre_max3.log`).

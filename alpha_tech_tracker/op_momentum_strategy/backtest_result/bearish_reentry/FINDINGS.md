# BEARISH Re-Entry — Backtest Findings

Config base: M1+A1+A2 windows, regime filter MA8, weights 50/30/20, no-compound.

```
--regime-filter --regime-ma 8 --weights 50 30 20
--window M1 09:30 3 --window A1 13:15 1 --window A2 15:00 1
--min-or-range 0.5 --min-or-range-windows M1 --morning-split 100 --reversal
```

---

## March 2026

| Config | Return | Cap P&L | BRE Trades (W/L) | Delta vs Baseline |
|---|---|---|---|---|
| Baseline (no BRE) | +24.22% | +$2,422.16 | — | — |
| BRE max-bars=3 | +27.04% | +$2,703.89 | 24 (15W/9L) | **+2.82pp** |

BRE win rate: **63%** in March 2026 (bearish macro month).
QQQ returned -5.09% that month.

---

## 2026 YTD (Jan–Mar)

| Config | Return | Cap P&L | BRE Trades (W/L) | Delta vs Baseline |
|---|---|---|---|---|
| Baseline (no BRE) | +85.26% | +$8,525.88 | — | — |
| BRE max-bars=3 | +95.85% | +$9,585.11 | 66 (38W/28L) | **+10.59pp** |

BRE win rate: **58%** in Q1 2026. In a strong bearish macro environment, the re-entry thesis (price continues lower after brief bounce) plays out at high frequency.

---

## Annual Results — Baseline vs BRE max-bars=3

| Year | Baseline | BRE max-bars=3 | Delta | BRE Trades (W/L) | BRE Win Rate |
|---|---|---|---|---|---|
| 2021 | +130.09% | +161.60% | **+31.51pp** | 240 (139W/101L) | 58% |
| 2022 | +180.38% | +236.41% | **+56.03pp** | 223 (124W/99L) | 56% |
| 2023 | +211.46% | +249.23% | **+37.77pp** | 200 (118W/82L) | 59% |
| 2024 | +100.86% | +136.12% | **+35.26pp** | 202 (129W/73L) | 64% |
| 2025 | +214.21% | +263.19% | **+48.98pp** | 189 (134W/55L) | 71% |

BRE improves return **every single year** from 2021–2025.
Delta ranges from +31.51pp (2021) to +56.03pp (2022).
BRE win rate is consistently 56–71%, far above the primary A2 win rate (~26%).

---

## Key Observations

1. **Consistent improvement every year** — BRE adds value in bear years (2022, +56pp), bull years (2023, 2024), and mixed years (2021, 2025).

2. **Win rate 56–71%** — Dramatically higher than the primary signals. The re-entry trigger (`close < or_low`) acts as a second confirmation that the bearish direction is resuming, filtering out bounce-and-recover patterns.

3. **2025 best year for BRE** — 71% win rate, +49pp delta. High-momentum 2025 market had more powerful intraday directional follow-through after OR breaks.

4. **2026 YTD: +10.59pp on top of already +85% baseline** — In bearish macro conditions, the re-entry captures recurring pattern of stocks bouncing briefly off support before continuing lower.

5. **Capital efficiency** — Re-entry uses the same slot capital as the primary. No additional capital allocation needed.

---

## Recommended Live Config

Add `--bearish-reentry --bearish-reentry-max-bars 3` to the standard M1+A1+A2 run:

```bash
python alpha_tech_tracker/op_momentum_strategy/op_momentum_selector_backtest.py \
  --start 2025-01-01 --end 2025-12-31 \
  --regime-filter --regime-ma 8 --weights 50 30 20 \
  --window M1 09:30 3 --window A1 13:15 1 --window A2 15:00 1 \
  --min-or-range 0.5 --min-or-range-windows M1 --morning-split 100 \
  --reversal --bearish-reentry --bearish-reentry-max-bars 3
```

---

## Log Files in This Directory

### M1+A1+A2 (primary — full config)

| File | Description |
|---|---|
| `march2026_m1a1a2_baseline.log` | March 2026, no BRE |
| `march2026_m1a1a2_bre_max3.log` | March 2026, BRE max-bars=3 |
| `2026ytd_m1a1a2_baseline.log` | 2026 Jan–Mar, no BRE |
| `2026ytd_m1a1a2_bre_max3.log` | 2026 Jan–Mar, BRE max-bars=3 |
| `2021_m1a1a2_baseline.log` | 2021 full year, no BRE |
| `2021_m1a1a2_bre_max3.log` | 2021 full year, BRE max-bars=3 |
| `2022_m1a1a2_baseline.log` | 2022 full year, no BRE |
| `2022_m1a1a2_bre_max3.log` | 2022 full year, BRE max-bars=3 |
| `2023_m1a1a2_baseline.log` | 2023 full year, no BRE |
| `2023_m1a1a2_bre_max3.log` | 2023 full year, BRE max-bars=3 |
| `2024_m1a1a2_baseline.log` | 2024 full year, no BRE |
| `2024_m1a1a2_bre_max3.log` | 2024 full year, BRE max-bars=3 |
| `2025_m1a1a2_baseline.log` | 2025 full year, no BRE |
| `2025_m1a1a2_bre_max3.log` | 2025 full year, BRE max-bars=3 |

### A2-only (exploratory — max-bars parameter sweep)

| File | Description |
|---|---|
| `march2026_baseline.log` | March 2026, A2 only, no BRE |
| `march2026_bre_max1.log` | March 2026, A2 only, BRE max-bars=1 |
| `march2026_bre_max3.log` | March 2026, A2 only, BRE max-bars=3 |
| `march2026_bre_max5.log` | March 2026, A2 only, BRE max-bars=5 |
| `2026ytd_baseline.log` | 2026 YTD, A2 only, no BRE |
| `2026ytd_bre_max3.log` | 2026 YTD, A2 only, BRE max-bars=3 |
| `2021_baseline.log` — `2025_baseline.log` | Annual A2-only baselines |
| `2021_bre_max3.log` — `2025_bre_max3.log` | Annual A2-only BRE max-bars=3 |

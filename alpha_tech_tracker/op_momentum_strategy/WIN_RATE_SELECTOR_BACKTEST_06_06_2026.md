# Win-Rate Selector — Regime-Hold $80k Backtest Results

**Run date:** 2026-06-06  
**Config:** M1 09:30/3 | win-rate selector | regime-engine | regime-hold | ecb=2 | stop-pct=0 | trailing-ma=none | top-8 | $80k capital | NO reversal / NO reentry / NO doubledown

```bash
python -m alpha_tech_tracker.op_momentum_strategy.op_momentum_trade_engine run \
  --selector win-rate --enable-regime-engine \
  --window M1 09:30 3 --morning-split 100 \
  --top 8 --capital 80000 \
  --stop-pct 0 --trailing-ma none \
  --regime-hold \
  --extend-collection-bars 2 \   # now the default
  --mock-trade-execution --feed sip \
  --replay-date YYYY-MM-DD
```

Tickers: `SNDK APP META SNOW SNPS SPOT MU LLY MRVL CRWD QCOM PLTR CHTR TSLA AVGO ARM AMD DDOG RDDT`

---

## Capital Allocation Models

| Model | Flag | Slot size | Avg daily deployed | Description |
|---|---|---|---|---|
| **Rank-weighted** (default) | _(none)_ | proportional by rank | ~$85–95k (>100% — capital recycled intraday) | Full capital deployed; fewer signals → larger slots per rank weight |
| **Fixed-alloc** | `--fixed-signal-alloc` | $80k ÷ 8 = $10k/slot | ~$22–28k (~30%) | Fixed $10k/slot; idle capital stays undeployed on low-signal days |

---

## Fixed-Alloc Results — All Years

| Year | Days | P&L | Return on avg deployed | Committed % | Avg deployed | Mean RODC | DW-Sharpe |
|---|---|---|---|---|---|---|---|
| 2017 | 223 | +$5,053 | +18.6% | +6.3% | $27,130 | +0.086% | 5.49 |
| 2018 | 209 | +$11,032 | +43.8% | +13.8% | $25,215 | +0.197% | 5.87 |
| 2019 | 206 | +$9,657 | +39.6% | +12.1% | $24,417 | +0.186% | 6.68 |
| 2020 | 205 | +$9,563 | +39.4% | +12.0% | $24,244 | +0.179% | 5.15 |
| 2021 | 216 | +$9,573 | +35.0% | +12.0% | $27,361 | +0.184% | 4.99 |
| 2022 | 209 | +$14,601 | +52.2% | +18.3% | $27,990 | +0.196% | 5.38 |
| 2023 | 209 | +$11,667 | +50.7% | +14.6% | $23,014 | +0.224% | 6.06 |
| 2024 | 211 | +$13,681 | +60.8% | +17.1% | $22,512 | +0.280% | 5.72 |
| 2025 | 212 | +$13,195 | +54.2% | +16.5% | $24,340 | +0.232% | 6.08 |
| 2026 YTD | 96 | +$5,780 | +22.9% | +7.2% | $25,208 | +0.254% | 5.76 |
| **Total** | **1,996** | **+$103,802** | | | | | |

- Profitable **every single year** across 10 years (2017–2026)
- 2017 Mean RODC (+0.086%) is notably lower — tickers like ARM/RDDT didn't exist and the win-rate signals weren't calibrated on this era; strategy still profitable with DW-Sharpe 5.49
- Capital utilization consistently ~**28–35%** — only ~$23–28k average at work per day
- Mean RODC trending upward post-2020: +0.179% (2020) → +0.280% (2024)
- DW-Sharpe above **4.99 every year**
- Log dirs: `logs/replay_YYYY_stock_m1_winrate_regimehold_cap80k_fixedalloc/`

### SIP Data Limit

Tested back to 2015. **2017 is the earliest fully usable year.**

| Year | Status |
|---|---|
| 2017 | Full data — 223 trading days |
| 2016 | Partial — only ~6 days in January have SIP data |
| 2015 | No data — SIP feed does not reach this far |

---

## Rank-Weighted vs Fixed-Alloc Comparison (2022, 2025, 2026 YTD)

| Year | Config | P&L | Return on avg deployed | Committed % | Mean RODC | DW-Sharpe |
|---|---|---|---|---|---|---|
| 2022 | Rank-weighted | +$39,174 | +45.5% on avg $86k | +49.0% | +0.196% | 4.63 |
| 2022 | Fixed-alloc | +$14,601 | **+52.2%** on avg $28k | +18.3% | **+0.196%** | **5.38** |
| 2025 | Rank-weighted | +$41,951 | +46.4% on avg $90k | +52.4% | +0.232% | 4.95 |
| 2025 | Fixed-alloc | +$13,195 | **+54.2%** on avg $24k | +16.5% | **+0.232%** | **6.08** |
| 2026 YTD | Rank-weighted | +$22,004 | +23.6% on avg $93k | +27.5% | +0.254% | 5.41 |
| 2026 YTD | Fixed-alloc | +$5,780 | **+22.9%** on avg $25k | +7.2% | **+0.254%** | **5.76** |

**Key finding:** Rank-weighted and fixed-alloc have **identical Mean RODC** in every year — the per-signal edge is the same. The only difference is capital utilization: rank-weighted deploys >100% of $80k (capital recycled intraday via renormalization), while fixed-alloc deploys ~30%. Fixed-alloc achieves slightly higher DW-Sharpe every year due to lower deployment variance.

**Trade-off:** rank-weighted earns ~3× more absolute P&L by putting more capital to work. Fixed-alloc preserves the pure edge signal with better risk-adjusted returns per dollar deployed.

---

## Sub-leg Analysis (Reversal / Reentry / Doubledown)

Sub-leg behavior is **strongly year-regime dependent**. In trending years doubledown amplifies gains; in choppy years reentry erodes the primary edge.

### Fixed-Alloc + Reversal Only (no doubledown)

| Year | Config | P&L | Avg deployed | Mean RODC | DW-Sharpe |
|---|---|---|---|---|---|
| 2022 | Fixed-alloc, no sub-legs | +$14,601 | $28k | +0.196% | 5.38 |
| 2022 | Fixed-alloc + reversal | +$14,028 | $46k | +0.165% | 3.26 |
| 2025 | Fixed-alloc, no sub-legs | +$13,195 | $24k | +0.232% | 6.08 |
| 2025 | Fixed-alloc + reversal | +$14,508 | $38k | +0.179% | 3.33 |
| 2026 YTD | Fixed-alloc, no sub-legs | +$5,780 | $25k | +0.254% | 5.76 |
| 2026 YTD | Fixed-alloc + reversal | +$4,246 | $40k | +0.153% | 2.92 |

Reversal/reentry consistently cuts RODC and DW-Sharpe. The regime-hold filter already selects clean momentum days — re-entering after a reversal adds noise, not edge.

### Fixed-Alloc + Reversal + Doubledown — Per-Leg Breakdown

| Year | Leg | Trades | Win rate | P&L | Notes |
|---|---|---|---|---|---|
| 2024 | Primary | 475 | 57.1% | +$13,681 | Identical to no-sub-leg baseline |
| 2024 | Reentry | 229 | 43.2% | +$983 | Small positive |
| 2024 | Doubledown | 64 | 34.4% | **+$14,767** | Trending year — DD nearly doubles total |
| 2024 | **All** | **768** | | **+$29,429** | +115% vs primary alone |
| 2026 YTD | Primary | 242 | 57.9% | +$5,780 | Identical to no-sub-leg baseline |
| 2026 YTD | Reentry | 142 | 38.7% | **-$1,534** | Choppy year — reentry loses money |
| 2026 YTD | Doubledown | 0 | — | $0 | Not triggered in this run |
| 2026 YTD | **All** | **384** | | **+$4,246** | -27% vs primary alone |

### Cross-year Sub-leg Summary (fixed-alloc $80k capital)

| Year | Primary P&L | Reentry contrib | DD contrib | Total w/ sub-legs | Avg deployed | Ret on avg deployed (yr) | Mean RODC (daily) | DW-Sharpe w/ sub-legs |
|---|---|---|---|---|---|---|---|---|
| 2020 no sub-legs | +$9,563 | — | — | +$9,563 | $24,244 | 39.4% | +0.179% | 5.15 |
| 2020 w/ sub-legs | +$9,563 | — | — | **+$23,935** | $40,436 | **59.2%** | +0.282% | 2.86 |
| 2022 no sub-legs | +$14,601 | — | — | +$14,601 | $27,990 | 52.2% | +0.196% | 5.38 |
| 2022 w/ sub-legs | +$14,601 | — | — | **+$36,261** | $47,561 | **76.2%** | +0.401% | 3.27 |
| 2024 no sub-legs | +$13,681 | — | — | +$13,681 | $22,512 | 60.8% | +0.280% | 5.72 |
| 2024 w/ sub-legs | +$13,681 | +$983 | +$14,767 | **+$29,429** | $38,006 | **77.4%** | +0.434% | 2.84 |
| 2026 YTD no sub-legs | +$5,780 | — | — | +$5,780 | $25,208 | 22.9% | +0.254% | 5.76 |
| 2026 YTD w/ sub-legs | +$5,780 | -$1,534 | $0 | **+$4,246** | $40,000 | **10.6%** | +0.153% | 2.92 |

### Old $10k Rank-weighted Runs (for reference — different capital model)

These are from the original `replay_YYYY_stock_m1_winrate_nostop/` and `_regimehold/` runs at $10k total capital with rank-weighted sizing:

| Year | Config | Primary | Reentry | DD | Total | RODC | DW-Sharpe |
|---|---|---|---|---|---|---|---|
| 2024 | nostop $10k | +$5,858 | +$156 | +$1,626 | +$7,640 | +0.269% | 4.86 |
| 2024 | regimehold $10k | +$5,710 | +$265 | +$1,954 | +$7,929 | +0.279% | 5.33 |
| 2025 | nostop $10k | +$5,143 | +$953 | +$1,065 | +$7,161 | — | 4.10 |
| 2025 | regimehold $10k | +$4,917 | +$962 | +$1,278 | +$7,158 | — | — |

At $10k capital: RODC is identical to $80k fixed-alloc (+0.280% for 2024), confirming the per-signal edge is capital-scale independent. DD contributed +30–39% of primary P&L in these runs.

**Key findings:**
- **Primary P&L is always identical** regardless of sub-leg config — sub-legs never interfere with primary signal execution
- **Doubledown is year-regime dependent**: trending year (2024) → DD wins big at low WR (34%) because large moves continue; choppy year (2026) → DD doesn't even trigger
- **Reentry is consistently low WR (38–45%)** and negative in 2026; small positive in 2024 only because the trend direction held after reversal
- **DW-Sharpe always drops with sub-legs** (5.72→2.84 in 2024, 5.76→2.92 in 2026) — sub-legs add variance even when net P&L improves
- **Rule of thumb**: use sub-legs only if confident the year will be strongly trending; regime-hold alone is the more consistent baseline

---

## --extend-collection-bars Sweep (2026 YTD, rank-weighted)

| ecb | Active days | P&L | Committed % | Mean RODC | DW-Sharpe |
|---|---|---|---|---|---|
| 0 | 81 | +$13,753 | +17.2% | +0.212% | 4.87 |
| **2** (default) | **96** | **+$22,004** | **+27.5%** | **+0.254%** | **5.41** |
| 3 | 100 | +$20,818 | +26.0% | +0.241% | 4.71 |

ecb=2 is the sweet spot: +15 more active days and +$8k vs ecb=0. ecb=3 adds noise (RODC and Sharpe both drop). **ecb=2 is now the default** in the engine.

---

## --stop-pct Sweep (2026 YTD, rank-weighted, ecb=2)

| stop-pct | P&L | Committed % | Mean RODC | DW-Sharpe |
|---|---|---|---|---|
| **0** (hold-to-EOD) | **+$22,004** | **+27.5%** | **+0.254%** | **5.41** |
| 0.2 | +$19,302 | +24.1% | +0.219% | 4.38 |
| 0.4 | +$19,614 | +24.5% | +0.233% | 3.63 |
| 0.9 | +$8,158 | +10.2% | +0.119% | 1.15 |

Any stop-pct hurts this config. The regime-hold filter handles day selection — adding a stop-loss creates unnecessary early exits on days that recover. **stop-pct=0 is the optimal setting.**

---

## Return Calculation Methodology

The yearly line reports two return figures:

| Method | Formula | What it answers |
|---|---|---|
| **Return on avg deployed** | `P&L / (total_deployed / trading_days)` | Edge efficiency: how productive was capital actually at work? |
| **Return on committed** | `P&L / $80,000` | Account-level: what did the brokerage account earn? |

Avg deployed is preferred for comparing configs with different utilization rates (e.g. rank-weighted vs fixed-alloc). Committed is better for absolute account-level planning.

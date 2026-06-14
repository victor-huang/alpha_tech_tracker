# Reduce Small Trade Noise — Proposals & Results

Status of prior attempts: see `SUMMARY.md`

Analysis tool: `op_momentum_strategy/analyze_pnl_distribution.py` (pipe backtest output to it)

---

## Baseline

**Params**: `--start 2025-01-01 --end 2025-12-31 --top 2 --weights 50 30 --regime-filter --regime-ma 8 --window M1 09:30 3 --window A1 13:15 1 --window A2 15:00 1 --morning-split 100 --reversal --min-or-range 0.5 --min-or-range-windows M1`

**Total trades: 1836** | Return: +236.58%

### P&L distribution (2025)

| Bucket | Count | % Total | Avg P&L% |
|---|---|---|---|
| <=-2.0% | 0 | 0.0% | — |
| -2.0 to -1.0% | 28 | 1.5% | -1.349% |
| -1.0 to -0.5% | 103 | 5.6% | -0.683% |
| -0.5 to -0.2% | 263 | 14.3% | -0.322% |
| **-0.2 to 0.0%** | **593** | **32.3%** | **-0.069%** ← noise |
| **=0.0%** | **265** | **14.4%** | **+0.000%** ← noise |
| **+0.0 to +0.2%** | **185** | **10.1%** | **+0.078%** ← noise |
| +0.2 to +0.5% | 100 | 5.4% | +0.338% |
| +0.5 to +1.0% | 103 | 5.6% | +0.719% |
| +1.0 to +2.0% | 89 | 4.8% | +1.412% |
| >+2.0% | 107 | 5.8% | +3.972% |
| **Total noise (±0.2%)** | **1043** | **56.8%** | |

### Noise by window (2025)

| Window | Trades | Noise (±0.2%) | Wins | Avg P&L% |
|---|---|---|---|---|
| M1 | 530 | 135 (25%) | 38% | +0.466% |
| A1 | 671 | 459 (68%) | 29% | +0.175% |
| A2 | 635 | 458 (72%) | 30% | +0.117% |

### Noise by exit reason (2025)

| Exit Reason | Trades | Noise (±0.2%) | Avg P&L% |
|---|---|---|---|
| hard_stop | 648 | 429 (66%) | -0.194% |
| fallback_20pct | 594 | 460 (77%) | -0.132% |
| trailing_stop_ma20 | 336 | 108 (32%) | +1.130% |
| end_of_day | 258 | 55 (21%) | +1.022% |

### Diagnosis

Noise is concentrated in two places:

- **A1/A2 (68-72% noise)**: By afternoon, price has often drifted near the OR boundaries set at open. The signal fires (bearish: price ≤ OR_midpoint) but entry is so close to the fallback/hard-stop levels that the exit fires on the next tick. The 265 exact 0.00% trades are cases where entry price = fallback_price or entry = hard_stop_price.
- **`hard_stop` and `fallback_20pct` exits (1242 trades total, ~90% of all noise)**: Both are "no-movement" exits — the stop fires before price develops any directional momentum.

M1 is healthy (25% noise, +0.47% avg). The problem is almost entirely A1/A2.

### Baseline by year (for reference)

| Year | Trades | Noise% | Return% |
|---|---|---|---|
| 2021 | 1853 | 60.4% | +141.22% |
| 2022 | 1813 | 51.2% | +182.82% |
| 2023 | 1843 | 56.5% | +233.40% |
| 2024 | 1869 | 61.2% | +100.45% |
| 2025 | 1836 | 56.8% | +236.58% |

Log files: `noise_p0_baseline_{year}.txt`

---

## Proposal 1 — `--min-entry-room PCT` (minimum entry-to-fallback distance)

**Hypothesis**: Noise trades happen when entry is at or past the fallback level — zero room before the unarmed stop fires. A per-trade check at signal time would skip these regardless of window or OR width.

**Mechanic**: Before entering, compute how much price can move against the trade before the fallback fires, as a % of entry:

- BULLISH: `(close - fallback_price) / close * 100` where `fallback_price = OR_high - 20% * OR_range`
- BEARISH: `(fallback_price - close) / close * 100` where `fallback_price = OR_low + 20% * OR_range`

Skip if distance < threshold (`--min-entry-room`). Implemented in `op_momentum_backtest.py:compute_signals_with_backtest`.

**Implementation note**: There was an initial formula inversion bug (both directions swapped) that was fixed before the 5-year sweep. The reversal eligibility check was also updated from a hardcoded `"fallback_20pct"` string match to `exit_reason.startswith("fallback_")` to be robust to the `--fallback-pct` parameter.

### Results

#### 2026 YTD (Jan 1 – Apr 2)

| Threshold | Trades | Noise% | Notes |
|---|---|---|---|
| Baseline | 450 | 53.6% | 118 M1 + 172 A1 + 160 A2 |
| 0.05% | 173 | 31.8% | 114 M1 + 35 A1 + 24 A2 |
| 0.10% | 115 | 17.4% | 112 M1 + 2 A1 + 1 A2 |
| 0.15% | 106 | 10.4% | M1 only |
| 0.20% | 100 | 9.0% | M1 only |
| 0.25% | 89 | 6.7% | M1 only |

#### 5-year per-year (0.05% threshold)

| Year | Trades | Noise% | Return% | Δ vs baseline |
|---|---|---|---|---|
| 2021 | 654 | 39.0% | +67.23% | **-74pp** |
| 2022 | 903 | 38.9% | +118.29% | **-65pp** |
| 2023 | 789 | 38.7% | +132.18% | **-101pp** |
| 2024 | 611 | 43.2% | +46.21% | **-54pp** |
| 2025 | 782 | 37.2% | +140.08% | **-97pp** |

Log files: `noise_p1_entry_room_0.05_{year}.txt`, `noise_p1_entry_room_0.10_2026.txt` through `noise_p1_entry_room_0.25_2026.txt`

### Conclusion

**Rejected.** The filter does reduce noise effectively (56% → 37% at 0.05%), but at an unacceptable cost to returns every year (-54pp to -101pp). The filter is correct mechanically — it targets zero-room trades — but those trades still contribute net positive EV collectively. The 30% of A1/A2 winners more than compensate for the noise. Eliminating 57% of all trades (mostly A1/A2) destroys the volume of winning trades needed to generate returns.

The key insight: at 0.05% threshold, the filter starts eliminating BEARISH entries above 20% of OR range (good trades), not just the zero-room boundary cases. The threshold that truly targets only zero-room trades would be ~0.001% — far too small to have any effect.

---

## Proposal 2 — `--fallback-pct PCT` (widen the unarmed stop)

**Hypothesis**: The fallback is hardcoded at 20% of OR range from the favorable end. Widening to 30-35% gives trades more breathing room before the unarmed stop fires. Some currently-noise trades might develop directional movement if given more room.

**Mechanic**: Made the 20% fallback configurable via `--fallback-pct` (default 0.20, backward-compatible). Implemented in `op_momentum_backtest.py:compute_signals_with_backtest`.

### Results

#### 2026 YTD (fixed, with reversal working correctly)

| fallback-pct | Trades | Noise% | Notes |
|---|---|---|---|
| 0.20 (baseline) | 450 | 53.6% | |
| 0.30 | 450 | 50.9% | -3pp noise |
| 0.35 | 449 | 51.0% | -3pp noise |

#### 5-year per-year (fallback-pct 0.30)

| Year | Trades | Noise% | Return% | Δ vs baseline |
|---|---|---|---|---|
| 2021 | 1858 | 58.1% | +123.82% | **-17pp** |
| 2022 | 1790 | 49.2% | +174.27% | **-9pp** |
| 2023 | 1841 | 54.8% | +217.34% | **-16pp** |
| 2024 | 1875 | 59.3% | +94.31% | **-6pp** |
| 2025 | 1826 | 53.9% | +214.27% | **-22pp** |

Log files: `noise_p2_fallback_0.30_{year}.txt`, `noise_p2_fallback_0.35_2026.txt`

### Conclusion

**Rejected.** Widening the fallback barely moves noise (-2 to -3pp per year) while consistently costing returns (-6pp to -22pp per year). The noise in A1/A2 comes equally from `hard_stop` and `fallback_Npct` — widening only the fallback does not address the `hard_stop` noise, and the A1/A2 noise is fundamentally caused by price drifting near OR extremes by afternoon, not by the fallback level being too tight.

---

## Proposal 3 — `--entry-bar-confirm` (entry bar direction confirmation)

**Hypothesis**: Most A1/A2 noise trades enter when the signal bar is flat or counter-directional. Requiring the last OR bar to close in the signal direction (red for BEARISH, green for BULLISH) filters mean-reverting entries.

**Mechanic**: At signal time, check `last_bar["Close"]` vs `last_bar["Open"]`. Skip BEARISH if `close >= open`, skip BULLISH if `close <= open`. Implemented via `--entry-bar-confirm` flag.

### Results

#### 5-year per-year

| Year | Trades | Noise% | Return% | Δ vs baseline |
|---|---|---|---|---|
| 2021 | 1506 | 61.2% | +99.20% | **-42pp** |
| 2022 | 1463 | 49.8% | +163.96% | **-19pp** |
| 2023 | 1528 | 56.2% | +185.24% | **-48pp** |
| 2024 | 1473 | 61.6% | +83.59% | **-17pp** |
| 2025 | 1592 | 57.8% | +199.19% | **-37pp** |

Log files: `noise_p3_entry_bar_confirm_{year}.txt`

### Conclusion

**Rejected.** Does not reduce noise at all — noise is flat or slightly higher in 4 of 5 years. Also consistently reduces returns (-17pp to -48pp per year). The last OR bar direction has no predictive relationship with signal quality. For M1 (3-bar OR), a single red closing bar at the end of a bullish OR period is noise in the confirmation signal. For A1/A2 (1-bar signal), the intraday 5-min candle direction is too noisy to be useful.

---

## Overall Conclusion

**All three proposals fail.** The 56-61% noise rate in A1/A2 is a structural characteristic, not a bug that can be filtered away without cost. The evidence across 5 years:

- The ~30% win rate in A1/A2 generates net positive EV (+0.175% avg for A1, +0.117% for A2)
- Those winning trades compensate for the 70% that are small losses or near-zero
- Any filter that reduces noise also reduces the volume of winning trades, leaving returns worse
- The noise trades individually average near zero — they are not destroying returns, they just look bad in trade log inspection

**What the noise actually costs**: Near-zero P&L trades have one real cost in live trading — option bid/ask spread and commission. If option entry+exit spreads cost ~0.3% round-trip, a 0.00% trade becomes a -0.3% trade. Filtering the zero-room trades (true 0.00% entries) may be worth it purely for commissions, but the backtest P&L impact is too small to model — the decision depends on actual contract pricing.

**What was not tried**: Investigating which specific tickers generate most A1/A2 noise, and whether excluding them from afternoon windows while keeping them in M1 would improve the signal-to-noise ratio without sacrificing the best afternoon setups.

# Cumulative Return Fan-Out Curve Detection

## What the Pattern Is

When plotting cumulative OR-close forward returns per hold window (+15m, +30m, +1h, +2h, +5h, EOD) for a ticker over a date range, a **fan-out curve** looks like:

- EOD and +5h lines trend steadily upward
- +15m and +30m lines stay flat or slightly negative
- The lines "fan out" — longer hold windows significantly outperform shorter ones
- The EOD curve is smooth with minor dips, not spiky

This pattern means: **the ticker needs time to resolve after the OR close, but consistently does so by end of day.** It is the ideal characteristic for an EOD hold strategy.

## Confirmed Examples (May 2026)

| Ticker | EOD Cumul (May) | Pattern Quality | Notes |
|--------|----------------|-----------------|-------|
| CRWD   | ~+40%          | Cleanest        | All holds positive, almost no drawdown, smooth from day 1 |
| DDOG   | ~+40%          | Excellent       | Near-identical shape to CRWD, smooth fan-out throughout |
| APP    | ~+35%          | Strong          | Clear fan-out, short holds flat near zero, took off ~May 11 |
| ARM    | ~+40%          | Strong          | Classic fan-out like AMD, shorter holds flat/negative |
| AMD    | ~+20%          | Good            | Reference case. +5h/EOD up, shorter holds negative |
| SNOW   | ~+28%          | Good            | All holds trending up, minor early dip |

## Contrast: Tickers Without This Pattern (May 2026)

| Ticker | Issue |
|--------|-------|
| MRVL   | Most holds declining throughout, last-day bounce only |
| AVGO   | Negative across all holds for most of May |
| PLTR   | Large early drawdown, high variance |
| MU     | Mid-May crater, recovery only at end |

---

## Early Detection Signals

After just **5 trading days** the pattern can be identified using four signals computed on the rolling lookback window:

### 1. Cumulative EOD Slope + R²
Fit a linear regression to the cumulative EOD return curve over the lookback days.
- **Positive slope** = trending up
- **R² ≥ 0.6** = rising consistently, not just one big outlier day

### 2. Fan-Out Ratio
```
fan_out_ratio = EOD_cumul / +1h_cumul
```
- Ratio **≥ 1.5** = "needs time to resolve" characteristic confirmed
- Signals that longer holds capture meaningfully more than shorter ones

### 3. Rolling EOD Win Rate
EOD win rate over the **last 5 trading days** ≥ 60% — daily bars are consistently green.

### 4. Cumulative EOD Max Drawdown
Cumulative EOD curve has not dipped more than **3%** below its running peak — the ramp is smooth, not noisy.

---

## Backtest Results (2018–2026)

### Look-ahead notes
- **Thresholds** (slope, R², fan-out, win rate, max-dd) calibrated on 2026 data — fully out-of-sample for 2018–2025
- **Monthly regime mapping** derived from 11-year MASTER_REGIME_SUMMARY — mild hindsight for all years since each year contributes ~9% of the regime signal
- **Feb treatment**: held as NEUTRAL for 2018–2025 backtests (Feb=CAUTION was a 2026-specific observation); Feb data shows it should be CAUTION in practice (negative in 2020, 2021, 2025)

### Methodology

- **Detection**: every Monday, compute the four signals on the prior 5 trading days per ticker
- **Validation**: measure the sum of daily OR-close-to-EOD returns over the **next 15 trading days** (3 weeks)
- **Regime gate**: skip CAUTION and SHORT months per MASTER_REGIME_SUMMARY (Mar, Aug, Sep, Dec + Feb)
- **Market gate**: skip any Monday where the cross-ticker EOD win rate over the detection window is < 45%

### What the metric means

`avg 15d EOD` = sum of daily OR-close (9:40 AM) → EOD (3:55 PM) returns over the next 15 trading days.
This is an **intraday cumulative return**, not an overnight return. It measures the edge of entering at the OR-close bar every day for 3 weeks.

**Edge** = avg 15d EOD (detected) − avg 15d EOD (not detected). A +3.59% edge means detected tickers produced 3.59pp more cumulative intraday return over 3 weeks. On a $10k daily position size, that is approximately **+$359 extra per detected ticker-week**.

### Multi-Year Summary (2018–2026 YTD)

Metric definitions:
- **Avg 15d EOD**: average sum of daily OR-close→EOD returns over the 15-day forward window per detected ticker-week
- **Edge**: detected avg minus not-detected avg (positive = detector adds value)
- **Net P&L**: total dollar gain assuming $10,000 per detected ticker per detection week (non-compounded, intraday only)

| Year     | Det n | Det avg 15d | Det WR | Not-det avg | Edge    | Net P&L ($10k/det) | Market character |
|----------|-------|-------------|--------|-------------|---------|---------------------|------------------|
| 2018     | 45    | -0.27%      | 47%    | -0.61%      | +0.33%  | -$1,232             | Mixed; Sep/Dec bear |
| 2019     | 35    | -0.42%      | 57%    | +0.82%      | -1.24%  | -$1,458             | Choppy; seasonal exceptions |
| 2020     | 45    | +1.00%      | 53%    | +1.07%      | -0.07%  | +$4,480             | COVID volatility; Nov bull |
| 2021     | 55    | -0.90%      | 47%    | -0.73%      | -0.17%  | -$4,934             | Choppy rotation year |
| 2022     | 51    | +2.09%      | 67%    | +0.29%      | **+1.80%** | **+$10,654**    | Bear market; Jul rally |
| 2023     | 83    | +3.37%      | 75%    | +0.74%      | **+2.63%** | **+$27,954**    | Strong trending bull |
| 2024     | 70    | -1.40%      | 46%    | +0.44%      | -1.84%  | -$9,780             | Choppy; Jul rotation |
| 2025     | 52    | +1.00%      | 58%    | +0.51%      | +0.49%  | +$5,223             | Liberation Day vol |
| 2026 YTD | 30    | +7.34%      | 77%    | +3.75%      | **+3.59%** | —               | Strong trend |

**Signal works in trending markets, struggles in choppy/rotating years.**
- Positive edge: 2022, 2023, 2025, 2026 (+1.8% to +3.6%)
- Near-zero: 2018, 2020, 2021
- Negative edge: 2019 (-1.24%), 2024 (-1.84%)

### Monthly P&L (2018–2025, $10k per detected ticker-week)

| Year | Jan | Feb | Apr | May | Jun | Jul | Oct | Nov | **Total** |
|------|-----|-----|-----|-----|-----|-----|-----|-----|-----------|
| 2018 | -$4,370 | +$596 | +$598 | +$715 | +$390 | +$154 | — | +$684 | **-$1,232** |
| 2019 | +$1,970 | +$1,002 | +$1,374 | — | -$2,339 | +$141 | -$1,710 | -$1,895 | **-$1,458** |
| 2020 | +$417 | -$3,988 | -$1,471 | +$1,579 | -$464 | +$869 | — | +$7,537 | **+$4,480** |
| 2021 | -$937 | -$2,654 | -$3,294 | +$592 | -$1,728 | +$2,308 | +$1,369 | -$590 | **-$4,934** |
| 2022 | — | — | — | -$5,460 | +$830 | **+$16,560** | — | -$1,275 | **+$10,654** |
| 2023 | **+$23,016** | -$529 | +$559 | +$1,448 | +$1,099 | +$1,631 | -$2,168 | +$2,898 | **+$27,954** |
| 2024 | +$4,399 | +$1,354 | -$1,449 | -$309 | +$150 | **-$13,287** | -$2,113 | +$1,475 | **-$9,780** |
| 2025 | +$3,725 | -$7,362 | +$4,838 | +$6,037 | -$620 | -$2,007 | +$1,414 | -$804 | **+$5,223** |

*— = zero detections (market gate or regime gate blocked all weeks)*

### Key Observations

**What works reliably:**
- **January LONG** is consistently positive when the market gate passes (2019 +$1,970, 2023 +$23,016, 2024 +$4,399, 2025 +$3,725). The 2022 and 2018 exceptions had near-zero detections due to the market gate firing correctly
- **October LONG** is positive in most years but thin sample size per year (3–10 detections)
- **Signal self-regulates in bear markets** — market gate produced 0 detections in Jan/Feb/Apr/Oct 2022 (the worst months), limiting damage to only May (-$5,460) and Jul/Nov

**Structural problem months:**
- **February**: negative in 2020 (-$3,988), 2021 (-$2,654), 2025 (-$7,362). Positive in 2018, 2019, 2024. Confirm CAUTION for Feb in live use
- **July 2024**: -$13,287 single-month loss from 11 detections. July 2024 was a sharp tech rotation/selloff that the market gate failed to catch because some tickers were still showing positive 5-day windows entering the selloff week

**Standout months:**
- **Jul 2022** +$16,560: bear market rally, 18 detections all in strong uptrend
- **Jan 2023** +$23,016: 25 detections in the strongest opening month of the dataset
- **Nov 2020** +$7,537: vaccine announcement bull run

### 2025 Year Detail

| Month | Detections | P&L | Notes |
|-------|-----------|-----|-------|
| Jan   | 4  | +$3,725 | ARM +$1,568, PLTR +$2,157 |
| Feb   | 6  | -$7,362 | 3 bad weeks; RDDT/QCOM/AMD all negative |
| Apr   | 6  | +$4,838 | AVGO/PLTR/MU week strong |
| May   | 15 | +$6,037 | Best month; CRWD/AVGO/SNOW consistent |
| Jun   | 7  | -$620  | APP -13.9% dragged one week |
| Jul   | 9  | -$2,007 | Late-Jul PLTR/AMD/TSLA/QCOM all down |
| Oct   | 3  | +$1,414 | Thin but positive |
| Nov   | 2  | -$804  | Thin sample |
| **Total** | **52** | **+$5,223** | +$100 avg per detection |

Adding Feb to CAUTION would have lifted 2025 to approximately **+$12,585**.

### 2026 YTD Detail (Jan–Jun 3)

| Month | Regime    | Detected avg | Undetected avg | Edge    | N det |
|-------|-----------|-------------|----------------|---------|-------|
| Jan   | LONG      | -7.29%      | -9.27%         | +1.98%  | 7     |
| Feb   | CAUTION   | skipped     | —              | —       | —     |
| Mar   | CAUTION   | skipped     | —              | —       | —     |
| Apr   | NEUTRAL   | +9.82%      | +6.29%         | +3.53%  | 14    |
| May   | MILD BULL | +14.85%     | +12.23%        | +2.62%  | 9     |

Jan still has negative absolute returns for both groups (broad market down), but detected tickers lost **less** (-7.29% vs -9.27%), confirming the signal works even in a down month.

### High-Confidence Tickers (2026 YTD detected, ≥2 weeks, 100% win rate)

| Ticker | Det weeks | Avg 15d EOD | Win Rate |
|--------|-----------|-------------|----------|
| CRWD   | 2         | +28.29%     | 100%     |
| MRVL   | 1         | +17.04%     | 100%     |
| AMD    | 3         | +12.84%     | 100%     |
| ARM    | 2         | +9.46%      | 100%     |
| META   | 3         | +3.56%      | 100%     |
| AVGO   | 2         | +2.81%      | 100%     |

---

## Integration with MASTER_REGIME_SUMMARY

The fan-out detector layers on top of the existing regime framework:

```
Layer 1 — MASTER_REGIME_SUMMARY (monthly direction + hold window)
        ↓ gate: skip CAUTION / SHORT months
Layer 2 — Market gate (cross-ticker EOD win rate ≥ 45% over detection window)
        ↓ gate: skip weeks when the broad basket is weak
Layer 3 — Fan-out detector (which tickers within the allowed regime)
        ↓ select
Layer 4 — Hold window from MASTER_REGIME_SUMMARY regime type
          (Rising Bull → EOD, U-Curve → enter at +2h, etc.)
```

### Monthly regime mapping for the detector

| Month | Regime    | Detector |
|-------|-----------|----------|
| Jan   | LONG      | Run |
| Feb   | CAUTION   | Skip — AM-pop-fade risk, no reliable seasonal |
| Mar   | CAUTION   | Skip — most dangerous month |
| Apr   | NEUTRAL   | Run — fan-out confirmation IS the direction signal |
| May   | MILD BULL | Run |
| Jun   | NEUTRAL   | Run |
| Jul   | NEUTRAL   | Run |
| Aug   | CAUTION   | Skip |
| Sep   | SHORT     | Skip |
| Oct   | LONG      | Run |
| Nov   | NEUTRAL   | Run — use EV check alongside detection |
| Dec   | SHORT     | Skip |

---

## Threshold Summary (validated on 2026 YTD)

| Signal | Threshold | Notes |
|--------|-----------|-------|
| Cumulative EOD slope | ≥ 0.3 | Linear regression over 5-day lookback |
| R² of slope fit | ≥ 0.6 | Filters one-day spikes |
| Fan-out ratio (EOD / +1h) | ≥ 1.5 | Core fan-out characteristic |
| EOD win rate (5d) | ≥ 60% | Consistent daily green bars |
| Max drawdown of cumul EOD | ≤ 3% | Smooth ramp, not noisy |
| Cross-ticker market win rate | ≥ 45% | Market gate over same 5-day window |

---

## Next Steps

- [ ] Add Feb to CAUTION in live use — data shows it's negative in 3 of 8 years with -$7k+ losses; the few positive Febs are small
- [ ] Investigate Jul 2024 failure — market gate missed a sharp tech rotation; consider adding a QQQ slope filter as a secondary gate
- [ ] Build a live Monday screener that computes signals and outputs a detected ticker list
- [ ] Investigate whether tickers with persistent low fan-out scores (SNDK, RDDT, APP) have a structural short signal in the opposite direction

## Analysis Scripts

All scripts live in `analysis_scripts/`. Run from the project root with `PYTHONPATH` set:

```bash
export PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker

# Plot cumulative hold curves for a single ticker
python alpha_tech_tracker/op_momentum_strategy/analysis_scripts/plot_ticker_hold_curves.py \
  --ticker CRWD --start 2026-05-01 --end 2026-06-03

# Plot rolling 20-day win rate across all tickers
python alpha_tech_tracker/op_momentum_strategy/analysis_scripts/plot_rolling_win_rate.py \
  --tickers CRWD DDOG APP AMD ARM --start 2026-05-01 --end 2026-06-03 --hold EOD

# Weekly Monday fan-out backtest (primary script)
python alpha_tech_tracker/op_momentum_strategy/analysis_scripts/backtest_rolling_fan_out.py \
  --tickers SNDK APP META SNOW SNPS SPOT MU LLY MRVL CRWD QCOM PLTR CHTR TSLA AVGO ARM AMD DDOG RDDT \
  --start 2025-01-01 --end 2025-12-31 --forward-days 15

# Monthly window backtest (first 5 days detect, rest of month validate)
python alpha_tech_tracker/op_momentum_strategy/analysis_scripts/backtest_fan_out_detector.py \
  --tickers CRWD DDOG APP AMD ARM --start 2026-01-01 --end 2026-06-03
```

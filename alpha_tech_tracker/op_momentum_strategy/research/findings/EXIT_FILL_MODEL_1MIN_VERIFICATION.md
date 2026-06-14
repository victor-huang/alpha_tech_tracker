# Exit Fill Model — 1-min Verification (2026-05-24, 7-year analysis: 2018–2024)

## TL;DR

`--no-exit-at-bar-close` inflates P&L on the 5-window M1+A1+A2+A3+A4 / top-2 config across all 7 years tested. Total optimistic P&L (2018–2024) is **+$149,276** vs **+$16,683** under realistic 5-min default — a $132,593 artificial gap.

**The simple 1-min "first-cross" fill upgrade is a structural loser, not a regime quirk.** Across 7 years it loses **−$77,562 vs 5-min default**:

| Year | Δ 1-min vs 5-min |
|---|---|
| 2018 | −$9,516 |
| 2019 | −$8,952 |
| 2020 | −$16,256 |
| 2021 | −$9,803 |
| 2022 | −$21,722 |
| 2023 | −$16,820 |
| 2024 | **+$5,506** ← only positive year |

The 2024 "+$5,506 free win" headline does not generalize — it's 1 of 7. In chop/bear years, 1-min "first-cross" triggers at intra-bar overshoots that the 5-min bar-close detection naturally rides through. The 1-min upgrade needs a smarter fill model (confirmation rule, next-bar-open, or late-bar-only triggering) before deployment is justified.

**Selector feedback is real but smaller than initially implied.** Proper net P&L decomposition: run the optimistic selector to pick tickers, then execute those picks with realistic 5-min bar-close fills (`analyze_clean_optimistic_pnl.py`). **Net selection benefit = +$11,315 over 7 years (~+$1.6k/yr)**, positive in 5 of 7 years. Earlier figures (+$60,172) counted only gross ≥0.5% genuine winners' cap P&L without netting opt-mode losers — that's a gain-side gross, not a net edge. The decomposition shows: **89% of the optimistic-vs-default gap is pure fill artifact ($89,336)**; only **11% is real selection benefit ($11,315)**.

**Bonus finding: the underlying strategy has weaker edge than headline numbers implied.** Default 5-min P&L (current live engine behaviour) across 7 years: only **+$16,683 total = ~+2.4% per year on $10k/day reset**. Yearly variance is high (−$860 to +$8,381). The "+12.7%/+100%-style" optimistic figures were always artifacts. Re-validation of window selection, weights, and even basic strategy fit is warranted against the realistic 5-min baseline.

> **Counting note (correction):** Earlier numbers in this doc undercounted by ignoring sub-trade legs (BR / BRU / REV are real intraday capital deployments and routinely produce ≥0.5% winners — see e.g. 2023-11-08 A2 CVNA BRU +1.29%). The corrected count below treats each leg as a separate trade. Earlier "+144 legs / +$20,663" figure was primary-only; corrected figure is "+250 legs / +$34,747".
>
> **Counter coverage**: the 3 sub-leg types (REV, BR, BRU) match the printer's `_REENTRY_TYPES` table in `op_momentum_selector_backtest.py:1547` and exhaust every leg that can fire under `--reversal --bearish-reentry --bullish-reentry`. BREV (bearish reversal, `--bearish-reversal`) and DD add-on (`--doubledown`) are not enabled in this config — verified zero rows with `brev_entry_price` or `dd_addon_*` keys in 2023. If those flags are turned on in future analyses, extend `compare_picks_big_winners.py`'s `SUB_LEGS` list correspondingly.

## Config under investigation

```bash
python alpha_tech_tracker/op_momentum_strategy/op_momentum_selector_backtest.py \
  --top 2 \
  --window M1 09:30 3 --window A1 10:00 3 --window A2 11:45 2 \
  --window A3 13:15 1 --window A4 15:15 2 \
  --bearish-reentry --bullish-reentry --reversal \
  --start 2024-01-01 --end 2024-12-31 \
  --feed sip --min-hold-bars 1 \
  [--no-exit-at-bar-close]   # toggle under study
```

## How `--no-exit-at-bar-close` changes the fill

In `op_momentum_backtest.py`, primary trade exits at `hard_stop` and `fallback_20pct`:

```python
# default (exit_at_bar_close=True)
_bull_stop_fill = bar_close

# --no-exit-at-bar-close (exit_at_bar_close=False)
_bull_stop_fill = hard_stop_price if bar["High"] >= hard_stop_price else bar["Open"]
```

A `hard_stop_hit` for BULLISH requires `bar_close ≤ hard_stop_price`, so filling at the stop level (rather than `bar_close`) yields a higher exit price — an optimistic fill. Symmetric inflation for BEARISH.

**Re-entry sub-trades (REV / BR / BRU) are NOT affected** — they always fill at the stop level (see `op_momentum_backtest.py:855-857, 948-949, 1099`). All the inflation flows through primary trades.

## Direct fill evidence

Same trade, same window, same exit_reason, different fill (2024-01-02 to 2024-01-10):

| Trade | Optimistic exit | Default exit | Δ | Verdict |
|---|---|---|---|---|
| 2024-01-02 A2 MSTR BULLISH hard_stop | 714.25 → +$0.25 WIN | 709.37 → −$4.63 LOSS | $4.88 | flips |
| 2024-01-08 M1 COIN BEARISH hard_stop | 153.54 → +$0.29 WIN | 154.39 → −$0.56 LOSS | $0.85 | flips |
| 2024-01-09 A1 MSTR BEARISH fallback | 581.22 → −$4.15 | 585.09 → −$8.02 | $3.87 | size only |

Many `--no-exit-at-bar-close` WIN rows are pennies (+$0.00, +$0.01, +$0.04) at `hard_stop` — these are stop-above-entry geometry cases (`hard_stop = or_high − 0.15 × or_range` sits ≥ entry when close lands in the 50–85% band of the OR).

## Year-2024 totals (1,910 trades)

| Fill model | Cap P&L | Return on $10k/day reset |
|---|---|---|
| 5-min default (live engine today) | **−$860** | **−8.6%** |
| 1-min realistic re-fill | **+$4,646** | **+46.5%** |
| 5-min optimistic (`--no-exit-at-bar-close`) | **+$19,779** | +197.8% |

Per-window roll-up:

| Window | OR bars | Trades | 5-min $ | 1-min $ | Opt $ | 1-min recovers gap |
|---|---|---|---|---|---|---|
| M1 | 3 | 443 | −2,181 | +440 | +7,604 | 26.8% |
| A1 | 3 | 346 | +979 | +1,833 | +4,476 | 24.4% |
| A2 | 2 | 351 | −1,068 | −288 | +1,493 | 30.5% |
| A3 | 1 | 364 | +1,008 | +1,391 | +3,194 | 17.5% |
| A4 | 2 | 406 | +403 | +1,270 | +3,012 | 33.2% |

## Year-2023 totals (1,856 trades) — regime-dependent reversal

| Fill model | Cap P&L | Return on $10k/day reset |
|---|---|---|
| 5-min default | **+$8,381** | **+83.8%** |
| 1-min realistic re-fill | **−$8,439** | **−84.4%** |
| 5-min optimistic (`--no-exit-at-bar-close`) | **+$31,912** | +319.1% |

Per-window roll-up:

| Window | Trades | 5-min $ | 1-min $ | Opt $ | 1-min vs 5-min |
|---|---|---|---|---|---|
| M1 | 453 | +4,183 | −3,284 | +14,591 | **−$7,467** |
| A1 | 338 | +1,079 | −1,224 | +5,364 | −$2,302 |
| A2 | 361 | +2,008 | −1,510 | +5,343 | −$3,517 |
| A3 | 356 | +1,721 | −1,057 | +4,612 | −$2,778 |
| A4 | 348 | −610 | −1,365 | +2,002 | −$755 |

### Why 1-min hurts in 2023 — chop and intra-bar overshoot

Of 1,417 primary stop/fallback exits with a 1-min cross in 2023, **546 (39%) had a 1-min cross at a price worse than the 5-min bar close** — price overshot the stop intra-bar then recovered by bar close. The 5-min "wait for bar close" detection acts as an unintentional hedge against intra-bar noise; the 1-min "first cross" model triggers at the worst tick.

Example trades that flipped from default WIN to 1-min LOSS in 2023:

| Date | Window | Ticker | Sig | %5m | %1m | %opt |
|---|---|---|---|---|---|---|
| 2023-07-27 | M1 | CLS | BULLISH | +0.50% | **−1.46%** | +2.12% |
| 2023-02-28 | M1 | CRDO | BULLISH | +0.10% | **−0.48%** | +0.90% |
| 2023-09-08 | M1 | PLTR | BULLISH | +0.59% | **−0.39%** | +0.88% |

These three trades alone illustrate the pattern: realistic 5-min bar-close held through the dip, but 1-min "first cross" locked in the worst intra-bar price.

## Year-2022 totals (1,725 trades) — bear-year confirms 1-min model fails

| Fill model | Cap P&L | Return on $10k/day reset |
|---|---|---|
| 5-min default | **+$61** | **+0.6%** (essentially breakeven) |
| 1-min realistic re-fill | **−$21,661** | **−216.6%** |
| 5-min optimistic | **+$24,911** | +249.1% |

Per-window: 1-min "first-cross" recovery is negative in every window (−76% to −127%). M1 takes the biggest hit at −$9,000 between 5-min and 1-min realistic.

| Window | Trades | 5-min $ | 1-min $ | Opt $ |
|---|---|---|---|---|
| M1 | 444 | −2,399 | −11,395 | +8,669 |
| A1 | 283 | −924 | −4,145 | +3,311 |
| A2 | 321 | +1,517 | −3,015 | +5,075 |
| A3 | 304 | −329 | −2,821 | +2,483 |
| A4 | 373 | +2,196 | −285 | +5,373 |

## Cross-year (2018–2024) consolidated comparison

| Year | Default 5-min | 1-min realistic | Optimistic | Δ 1-min vs 5-min | Opt-vs-default gap |
|---|---|---|---|---|---|
| 2018 | +$1,791 | −$7,725 | +$16,027 | −$9,516 | $14,236 |
| 2019 | +$3,035 | −$5,917 | +$14,819 | −$8,952 | $11,784 |
| 2020 | +$3,971 | −$12,285 | +$23,607 | −$16,256 | $19,637 |
| 2021 | +$304 | −$9,498 | +$18,221 | −$9,803 | $17,917 |
| 2022 | +$61 | −$21,661 | +$24,911 | −$21,722 | $24,850 |
| 2023 | +$8,381 | −$8,439 | +$31,912 | −$16,820 | $23,531 |
| 2024 | −$860 | +$4,646 | +$19,779 | **+$5,506** | $20,639 |
| **7-yr** | **+$16,683** | **−$60,879** | **+$149,276** | **−$77,562** | **$132,593** |

### Net selection benefit (CORRECTED — proper net P&L, not gross winner sum)

Method: run optimistic selector to choose tickers (using inflated rolling history), then execute those picks with realistic 5-min bar-close fills. Net selection benefit = clean-optimistic P&L − default P&L.

| Year | Default $ | Clean Opt $ | Raw Opt $ | **Selection benefit** | **Fill artifact (noise)** |
|---|---|---|---|---|---|
| 2018 | +1,417 | −176 | +8,685 | −1,593 | +8,861 |
| 2019 | +1,857 | +3,390 | +9,791 | +1,532 | +6,401 |
| 2020 | +3,859 | +1,527 | +16,579 | −2,332 | +15,052 |
| 2021 | −445 | +2,672 | +14,755 | +3,117 | +12,083 |
| 2022 | +1,055 | +1,633 | +21,365 | +578 | +19,732 |
| 2023 | +4,196 | +10,478 | +24,263 | +6,282 | +13,785 |
| 2024 | −2,250 | +1,482 | +14,903 | +3,732 | +13,421 |
| **7-yr** | **+9,690** | **+21,005** | **+110,341** | **+11,315** | **+89,336** |

**Of the +$100,651 gap between Raw Optimistic and Default: 89% is fill artifact noise; only 11% is real selection benefit.**

### Earlier gross-counting metric (kept for reference)

The earlier table counted only ≥0.5% genuine big-winner cap P&L (gain side, no losses netted). It came out to +$60,172 over 7 years. That measure overstates the actual money-on-the-table by ~5x because optimistic-mode picks also produce losers that offset the gross winner sum. The correct net selection-benefit figure is the +$11,315 line above.

### Conclusions from 7-year data

1. **1-min "first-cross" upgrade is a structural loser.** Net **−$77,562 over 7 years**. Only 2024 (trendy year) saw a positive effect — 6 of 7 years lose under this model. Worst year 2022 (−$21.7k). Do not deploy this fill model in production.

2. **Selector-feedback is real but smaller than first claimed: ~+$1.6k/yr net.** Properly netting losers and winners on opt-mode unique picks vs default-mode picks under realistic fills: **+$11,315 over 7 years (~+$1.6k/yr)**, positive in 5 of 7 years. Earlier "+$60,172" figure counted only gross winner cap P&L — useful as a directional signal but not a money-on-table estimate. The selector mis-ranking exists but the dollars at stake are modest, and worth pursuing only as a side-quest after the fill model is sorted.

3. **Default 5-min config has weak underlying edge.** 7-yr total **+$16,683 on $10k/day reset = ~+2.4%/yr**. Yearly P&L range −$860 to +$8,381. The "+12.7%/+100%-style" headline numbers visible in optimistic backtests were always artifacts. Re-validate window selection, weights, and basic strategy fit against `exit_at_bar_close=True` before relying on it for sizing.

4. **Realistic upper bound (Clean Optimistic) is ~+$3k/yr, not +$15k/yr.** Running the optimistic selector but executing trades with realistic 5-min fills: 7-yr P&L = +$21,005 (mh=1) or +$22,342 (mh=0). That's the most that "fixing the selector" could deliver — roughly 2× the default 5-min baseline, but nowhere near the raw optimistic figure. **~85–89% of the raw optimistic backtest's apparent edge is fill-artifact noise.**

5. **`--min-hold-bars 1` is a useful noise filter.** Removing it (mh=0) increases optimistic fill artifact by ~33% (+$29k over 7 years) without changing the underlying selection benefit. Keep mh=1 for honest backtest comparisons.

### Year-over-year P&L stability check

| Mode | Years positive (of 7) | Best year | Worst year | 7-yr total |
|---|---|---|---|---|
| Default 5-min | 6/7 | +$8,381 (2023) | −$860 (2024) | +$16,683 |
| 1-min realistic | 1/7 | +$4,646 (2024) | −$21,661 (2022) | −$60,879 |
| Optimistic | 7/7 | +$31,912 (2023) | +$14,819 (2019) | +$149,276 |
| **Clean Optimistic** (noise removed) | **6/7** | **+$10,478 (2023)** | **−$176 (2018)** | **+$21,005** |

### Per-year P&L after noise adjustment (Clean Optimistic)

"Clean Optimistic" = run optimistic-mode selector to pick tickers (using inflated rolling history) but execute those picks with realistic 5-min bar-close fills (no stop-level inflation). This is the **realistic upper bound** for what the strategy can earn from selector-quality alone.

#### With `--min-hold-bars 1` (recommended baseline; suppresses bar-0 stop-out inflation)

| Year | Default 5-min | **Clean Optimistic** | Raw Optimistic | Selection benefit | Fill artifact (noise) |
|---|---|---|---|---|---|
| 2018 | +$1,417 | −$176 | +$8,685 | −$1,593 | +$8,861 |
| 2019 | +$1,857 | +$3,390 | +$9,791 | +$1,532 | +$6,401 |
| 2020 | +$3,859 | +$1,527 | +$16,579 | −$2,332 | +$15,052 |
| 2021 | −$445 | +$2,672 | +$14,755 | +$3,117 | +$12,083 |
| 2022 | +$1,055 | +$1,633 | +$21,365 | +$578 | +$19,732 |
| 2023 | +$4,196 | +$10,478 | +$24,263 | +$6,282 | +$13,785 |
| 2024 | −$2,250 | +$1,482 | +$14,903 | +$3,732 | +$13,421 |
| **7-yr** | **+$9,690** | **+$21,005** | **+$110,341** | **+$11,315** | **+$89,336** |

Clean-optimistic 7-yr total = +$21,005 = ~+30%/yr no-compound on $10k/day reset (~2× the default-mode edge).

#### With `--min-hold-bars 0` (no bar-0 suppression)

| Year | Default 5-min | **Clean Optimistic** | Raw Optimistic | Selection benefit | Fill artifact (noise) |
|---|---|---|---|---|---|
| 2018 | +$777 | −$346 | +$13,023 | −$1,123 | +$13,369 |
| 2019 | +$1,182 | +$2,875 | +$12,208 | +$1,694 | +$9,332 |
| 2020 | +$2,705 | +$3,375 | +$21,867 | +$671 | +$18,492 |
| 2021 | +$715 | +$1,806 | +$18,159 | +$1,091 | +$16,353 |
| 2022 | +$513 | +$160 | +$25,950 | −$353 | +$25,790 |
| 2023 | +$7,021 | +$12,588 | +$30,545 | +$5,567 | +$17,958 |
| 2024 | −$1,703 | +$1,884 | +$19,293 | +$3,587 | +$17,409 |
| **7-yr** | **+$11,209** | **+$22,342** | **+$141,046** | **+$11,133** | **+$118,703** |

### Effect of `--min-hold-bars` on fill artifact (noise)

| Metric | mh=1 | mh=0 | Δ |
|---|---|---|---|
| 7-yr default 5-min P&L | +$9,690 | +$11,209 | +$1,519 |
| 7-yr clean optimistic | +$21,005 | +$22,342 | +$1,337 |
| 7-yr raw optimistic | +$110,341 | +$141,046 | +$30,705 |
| **7-yr fill artifact (noise)** | **+$89,336** | **+$118,703** | **+$29,367 (+33%)** |
| 7-yr selection benefit | +$11,315 | +$11,133 | −$182 |

`--min-hold-bars 1` is a **noise filter**, not a strategy edge changer. It suppresses bar-0 stop-out exits where the "stop above entry" geometry produces the most extreme optimistic-vs-realistic fill gaps. Real selection benefit barely changes (~$11k both modes); default 5-min P&L is marginally lower (−$1.5k), but the optimistic noise drops by ~$29k. Use mh=1 for honest backtest comparison.

## Where the optimistic gap comes from

Decomposing the +$20,639 optimistic-vs-default gap:

| Source | $ | % of gap |
|---|---|---|
| Small-trade fill inflation (tiny "WIN at stop" rows) | ~$13,000 | ~63% |
| **Real selection-quality improvement (different picks)** | **~$7,088** | **~34%** |
| Stop-fill artifact in big winners | ~$460 | ~2% |

### 1-min recovery in detail

1,449 of 1,454 primary stop/fallback exits had a 1-min close cross the stop level within the same 5-min exit bar (99.7% coverage). 271 sub-trade refills (none fell back to the 5-min close in any meaningful number).

The 1-min re-fill recovers ~27% of the gap on average. Recovery rate varies by window from 17.5% (A3, 1-bar OR — stops near entry so the 5-min close already approximates the 1-min cross) to 33.2% (A4, 2-bar OR).

## Big-winner analysis (≥0.5% gain)

Default mode produces 280 genuine big winners (non-stop exits) for +$18,022. Optimistic mode produces **337 genuine big winners (+57) for +$25,110 (+$7,088)** — and these gains are independent of fill model.

Pick overlap: 1,016 shared picks, 894 unique to default, 1,093 unique to optimistic. On UNIQUE picks alone, optimistic gets **+57 more genuine ≥0.5% winners worth +$7,142** in real P&L.

### Why is this real?

The selector scores tickers on 60-day rolling stats including `avg_win_pct` and `ev_trade`. When fed inflated history, certain tickers rank higher and pass the `ev_trade > 0` gate. These tickers then go on to produce **genuine** trailing-MA-stop and EOD wins that the default-mode selector misses by ranking them out of the top-2.

The default selector penalizes tickers whose hard-stops sit near entry: their realistic small-loss stop fills drag down `avg_win_pct`, even though those same tickers also produce strong upside trades. The optimistic mode "smooths" this by treating those stop fills as flat — exposing the underlying upside the realistic mode hides.

### Big winners (≥+0.8%) on stop/fallback exits

Only **10 trades** out of 1,454 stop-fill trades reach ≥+0.8% in optimistic mode. Of those:
- **2 (20%) achievable** — ≥+0.8% even in 1-min realistic
- **8 (80%) pure artifact** — only optimistic shows ≥+0.8%

So ≥+0.8% gainers via stop-fill manipulation are rare; the artifact's bulk comes from many small-trade flips, not a few big winners.

## Caveats on the 1-min verification

1. **Same-bar window only**: the verification only checks 1-min crosses *within* the 5-min bar that the default backtest exited on. A real 1-min live engine might exit EARLIER on a bar where price intra-bar pierced the stop then recovered — that case is not modeled.
2. **No selector-feedback loop**: ticker picks held fixed to default-mode picks. The full benefit of 1-min in live trading would include slightly different picks (since 1-min-corrected history feeds the selector).
3. **No compounding propagation**: per-trade slot capital comes from default-mode capital flow; daily $10k reset keeps this small for 2024.

Per-trade fill divergence is bounded — under stop_pct=0.15 the maximum 1-min vs 5-min cross delta is on the order of the 5-min bar's intrabar range. The +$5,506 number is a first-order estimate; a proper 1-min-native backtest could land ±10–20% of this figure.

## Implications and next steps

1. **Don't use `--no-exit-at-bar-close` numbers as live targets.** Phase 11 of `trading_params_retune_reduce_short_trades.md` was correct: it is research-only.

2. **The simple 1-min "first-cross" upgrade is NOT an unconditional win.** Helps trendy years (2024 +$5,506) but hurts chop years (2023 −$16,820). Net across both years: −$11,314. Do not deploy without first validating an improved 1-min fill model. Promising variants to test:
   - **Confirmation rule** — require 2 consecutive 1-min closes past stop before exiting
   - **Next-bar-open fill** — detect at 1-min close, fill at the next 1-min open (small recovery delay)
   - **Late-bar 1-min only** — keep 5-min bar-close detection but allow 1-min triggers only in the final 30s of each 5-min bar (cuts the lag without the whipsaw cost)

3. **The selector under-ranks stop-vulnerable tickers — robust across years, fixable independently of the exit fill.** Worth ~+$6,500–7,000/year. Ideas:
   - Score history on 1-min-realistic fills (close to live engine reality, partially captures the benefit)
   - Use upside-only metrics (median up move, max favorable excursion) less penalized by tiny stop fills
   - Decouple stop-loss penalty from the rolling win-rate score
   - Re-tune `score_entry_weight` / `score_vol_ratio_weight` after switching to corrected history

4. **Reconsider config viability across regimes.** This 5-window M1+A1+A2+A3+A4 / top-2 config delivered +83.8% in 2023 but −8.6% in 2024 under default 5-min. The strategy edge is not stable. Re-run window-additivity and regime-filter studies with `exit_at_bar_close=True` (and ideally a confirmed 1-min fill model) before relying on this config for production sizing.

## Tooling

All analysis scripts live in `alpha_tech_tracker/op_momentum_strategy/analysis_scripts/`:

| Script | Purpose |
|---|---|
| `verify_1min_fills.py` | Run default backtest, re-fill stop/fallback exits with 1-min bar closes, compare to optimistic. Saves per-trade detail JSON. |
| `analyze_big_winners.py` | Bucket stop/fallback trades by which fill model produces ≥0.8% gain. Quantifies achievable vs artifact. |
| `compare_picks_big_winners.py` | Run both default and optimistic, compare picks and count genuine ≥0.5% winners by exit reason. Gross winner counting. |
| `analyze_clean_optimistic_pnl.py` | Proper net decomposition: run optimistic selector, execute its picks with realistic 5-min fills, compute selection benefit vs fill artifact. Supports `--min-hold-bars 0/1`. **Use this for actual money-on-table estimates.** |

### Reproducing

```bash
source ~/.pyenv/versions/alpha_tech_tracker/bin/activate
export PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker
cd /Users/victorhuang/work/alpha_tech_tracker

# Full-year 1-min verification (~5 min after caches warmed)
python alpha_tech_tracker/op_momentum_strategy/analysis_scripts/verify_1min_fills.py \
  --start 2024-01-02 --end 2024-12-31

# Big-winner classification on the produced detail JSON
python alpha_tech_tracker/op_momentum_strategy/analysis_scripts/analyze_big_winners.py

# Picks vs picks comparison (runs both backtests)
python alpha_tech_tracker/op_momentum_strategy/analysis_scripts/compare_picks_big_winners.py

# Net selection-vs-noise decomposition across 2018-2024
python alpha_tech_tracker/op_momentum_strategy/analysis_scripts/analyze_clean_optimistic_pnl.py \
  --min-hold-bars 1
```

Detail outputs (all 7 years):
- `logs/verify_1min_fills_2018-01-02_2018-12-31.json`
- `logs/verify_1min_fills_2019-01-02_2019-12-31.json`
- `logs/verify_1min_fills_2020-01-02_2020-12-31.json`
- `logs/verify_1min_fills_2021-01-04_2021-12-31.json`
- `logs/verify_1min_fills_2022-01-03_2022-12-30.json`
- `logs/verify_1min_fills_2023-01-03_2023-12-29.json`
- `logs/verify_1min_fills_2024-01-02_2024-12-31.json`

## Related

- `trading_params_retune_reduce_short_trades.md` Phase 11 — original `--no-exit-at-bar-close` analysis for 1-bar windows
- `op_momentum_backtest.py:607-694` — primary trade exit fill logic (`exit_at_bar_close` branches)
- `op_momentum_backtest.py:855-857, 948-949, 1099` — sub-trade fill (always stop-level)

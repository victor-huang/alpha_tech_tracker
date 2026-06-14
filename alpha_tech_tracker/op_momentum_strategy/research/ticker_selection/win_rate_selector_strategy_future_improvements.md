# Win-Rate Selector — Strategy Future Improvements

Research synthesis combining 9-year backtest findings (2018–2026), 11-year regime analysis
(MASTER_REGIME_SUMMARY, 2016–2026), and current academic/hedge fund literature.

**Related docs:**
- `WIN_RATE_SELECTOR_BACKTEST.md` — baseline performance (9/9 years profitable, Sharpe 2.7–5.5)
- `WIN_RATE_SELECTOR_MODE.md` — configuration and signal flow reference
- `win_rate_selector_capital_deployment_comparison.md` — pool vs fixed-slot capital models
- `op_momentum_screener_analysis/MASTER_REGIME_SUMMARY.md` — 11-year seasonal pattern database

---

## Baseline Performance (What We're Improving From)

| Metric | Current value |
|---|---|
| Years profitable | 9/9 (2018–2026) |
| Annual return range | +33% (2020) to +76% (2024) |
| Sharpe ratio range | 2.70 (2020) to 5.49 (2019) |
| 9-year total return | +477% (pool model, $10k capital) |
| Max single-day loss | −$333 (2024-02-12) |
| Max weekly loss | −$444 (2020-03) |
| Signal win rate | ~53–56% across all signal counts |

**Known weaknesses:**
- Raw win-rate ranking ignores magnitude (Low-WR Positive EV tickers systematically under-ranked)
- Regime engine controls entry direction but not exit timing
- No volatility-regime gate — position count is fixed regardless of VIX environment
- Equal-dollar sizing ignores ticker volatility differences
- Afternoon windows (A1 1:15 PM) not conditioned on morning outcome

---

## Improvement 1 — Replace Win Rate Ranking with Kelly Composite
**Priority: 1 | Implementation: 1 line | Confidence: High**

### Problem

Raw EOD win rate ignores magnitude. A ticker winning 70% at +0.3%/win and −1.5%/loss has
negative EV. A ticker winning 45% at +2.5%/win and −0.8%/loss is strongly positive EV.
The current sort ranks the 70% WR ticker first — the opposite of what the data supports.

This mismatch drives the "Low-WR Positive EV" anomaly observed in MASTER_REGIME_SUMMARY:
Nov 2019 (38.9% WR → +8.72% monthly P&L), Sep 2017, Sep 2019. In those months, the
current selector likely deprioritized the best tickers.

### Academic support

- **Kelly criterion literature**: `f* = (p × b − q) / b` where b = avg_win / avg_loss.
  Win rate alone is not the objective — EV-weighted win rate is.
- **Zarattini, Barbon & Aziz (SSRN 2024)**: "A Profitable Day Trading Strategy For The
  U.S. Equity Market" — volume-filtered ORB achieves Sharpe 2.4; their selection relies
  on expected-value characteristics of "Stocks in Play", not raw directional win rate.
- **Chuk (SSRN 2026)**: Regime-filtered ORB win rate jumps from 46.8% (unfiltered) to
  65.4% — the filter is a quality gate, equivalent to an EV gate applied at the signal level.

### Implementation

`_compute_hold_history` already computes `medians[None]` (EOD median return). It encodes
sign and magnitude in a single number. Switch the sort key in `_rank_tickers_by_eod_win_rate`:

```python
# Current (ma_open_range_momentum_screener.py, _rank_tickers_by_eod_win_rate):
ranked.sort(key=lambda x: -x[1]["win_rates"][None])

# Proposed — Kelly composite (win_rate × magnitude proxy):
ranked.sort(key=lambda x: -x[1]["medians"][None])
```

If avg_win and avg_loss are tracked in `_compute_hold_history` (requires adding two
accumulators), use the explicit Kelly composite instead:

```python
def _kelly_score(hist):
    wr = hist["win_rates"].get(None, 0) / 100.0
    avg_win = hist.get("avg_win", 0)   # needs to be computed in _compute_hold_history
    avg_loss = hist.get("avg_loss", 0)
    if avg_loss == 0:
        return wr
    return wr * avg_win / abs(avg_loss)

ranked.sort(key=lambda x: -_kelly_score(x[1]))
```

### Validation

Backtest `medians[None]` sort vs `win_rates[None]` sort for 2018–2025 replay.
Check: do Low-WR Positive EV months (Nov 2019, Sep 2017, Sep 2019) improve?
A P&L increase in those months with no regression in high-WR months confirms the change.

---

## Improvement 2 — VIX Regime Gate for Position Count
**Priority: 2 | Implementation: Medium | Confidence: High**

### Problem

Position count is fixed at `--top N` regardless of volatility environment. The worst
drawdown weeks in the backtest (2020-03: −$296, 2024-02: −$322) both align with VIX
spikes into the >25 range. The QQQ MA8 filter gates direction but not sizing.

### Academic support

- **Chuk (SSRN 2026)**: Optimal VIX range for ORB is 15–25. Below 12 (mean-reversion
  dominates), above 30 (momentum crashes) — the edge degrades. Static configs underperform
  VIX-adaptive ones by **8–12 percentage points**.
- **Daniel & Moskowitz (JFE 2016) "Momentum Crashes"**: Momentum has written-call-option-like
  exposure in bear markets. Largest losses occur when market has fallen AND VIX is elevated.
  Volatility scaling (inverse of prior-month realized vol) reduces drawdowns ~50% with
  minimal long-run cost.
- **Moreira & Muir (2017)**: WML portfolios scaled by inverse lagged VIX produce
  substantially higher Sharpe ratios than unscaled portfolios.

### Implementation

Add `--vix-regime-gate` flag to the trade engine. Pre-market, fetch prior-day VIX close
(VIXY as proxy or cached daily bars). Adjust effective `top_n` by VIX band:

```python
def _apply_vix_gate(self, base_top_n: int, vix: float) -> int:
    if vix < 12 or vix > 35:
        return max(1, base_top_n - 2)   # outside productive band
    if vix > 25:
        return max(1, base_top_n - 1)   # elevated but not extreme
    return base_top_n                   # sweet spot (12–25)
```

For the no-stop model specifically, add a **session-level bail** at 11:30 AM:
if total realized + unrealized P&L is below −2.5% of deployed capital, exit all positions.
Chuk (2026): "after 11:30 AM ET, ORB entries are empirically thin-market head-fakes."

### VIX data source

```python
# In WinRateTickerSelector.fetch_bars() or pre-market routine:
vix_bars = fetch_bars(["VIXY"], yesterday, yesterday, source="alpaca")
prior_vix = float(vix_bars["VIXY"].iloc[-1]["Close"]) if not vix_bars["VIXY"].empty else 20.0
```

---

## Improvement 3 — Rank-Weighted Slot Sizes in Win-Rate Mode
**Priority: 3 | Implementation: Small (reuse existing infra) | Confidence: High**

### Problem

`WinRateTickerSelector` sets `ev_trade=1.0` as a sentinel for all top-N picks — every
pick gets equal capital. But the composite selector proves 50/30/20 weights beat equal
weighting every year over 5 years (+204pp). The same logic applies here: the #1 ranked
ticker (highest Kelly composite) should get more capital than the #N ticker.

### Academic support

- **AQR Capital**: positions scaled to contribute equal risk, not equal dollars. The
  Kelly-ranked ticker deserves a larger Kelly fraction of capital.
- **Kelly theory**: fractional Kelly allocation is proportional to the signal's edge.
  If Rank 1 has 30% higher Kelly score than Rank 2, it should receive proportionally
  more capital.

### Implementation

Change the `ev_trade` sentinel in `WinRateTickerSelector.select()` to be
rank-proportional rather than a flat 1.0. The existing `--rank-weighted-sizing` weights
infrastructure in the drain can then apply correctly:

```python
# In WinRateTickerSelector.select(), after computing picks list:
weights = _normalize_weights([0.50, 0.30, 0.20, 0.15, 0.12, 0.10, 0.08, 0.06][:len(picks)])
self.rolling_stats = {
    ticker: {
        "ev_trade": weights[i] * len(picks),  # sentinel scaled by rank weight
        "avg_win_pct": 0.0,
        "win_rate": 0.0,
    }
    for i, ticker in enumerate(picks)
}
```

Then pass `--rank-weighted-sizing W1 W2 ...` in the CLI and the drain will size
accordingly. No changes needed in the drain itself.

---

## Improvement 4 — Wire Regime Hold Window to Exit Decision
**Priority: 4 | Implementation: Medium | Confidence: High**

### Problem

The regime engine determines entry *direction* (LONG/SHORT/NO_POSITION) but not exit
*timing*. The 11-year MASTER_REGIME_SUMMARY has already solved the hold-window problem
empirically — but this knowledge is not wired to the position monitor.

Current behavior: all positions exit at 3:55 PM (EOD) in no-stop mode regardless of
seasonal regime. But the data shows September exits at +15m would have captured 6 of 7
bear September AM-pop-fades; October EOD hold has zero false positives across 9 years.

### Evidence from MASTER_REGIME_SUMMARY

| Month | Optimal hold window | Years confirmed | Rule |
|---|---|---|---|
| September | +15m (exit ~10:00 AM) | 7/10 bear | AM-pop-fade dominant; +15m positive in 6/7 bear years |
| October | EOD or +3h | 9/11 positive | Rising curve; zero false positives |
| December | +1h30m or SHORT | 8/10 bear | Near-flat years peak mid-morning |
| August | +15m, confirm +30m | High variance | Extend only if July was rising-curve bull |

### Implementation

`RegimeState` already exposes a `hold_window` field (visible in log: `"Hold: EOD [Seasonal Default]"`).
Wire it to `PositionMonitor`'s force-close time:

```python
# In PositionMonitor (or run_replay entry point):
hold_minutes = self._regime_state.hold_window_minutes  # None = EOD
if hold_minutes is not None:
    position_exit_time = entry_bar_time + timedelta(minutes=hold_minutes)
else:
    position_exit_time = eod_force_close  # 15:55 default
```

`hold_window_minutes` values: 15 (September), 90 (December near-flat), None (EOD).
The regime is determined pre-market from prior-day data — no lookahead introduced.

---

## Improvement 5 — ATR Floor for Hybrid Stop Configuration
**Priority: 5 | Implementation: Medium | Confidence: Medium-High**

### Problem

The OR-range-based hard stop (15% of OR range) is proportionally correct for average OR
days but can be too tight on narrow-OR days. A ticker's normal ATR may be 2× the narrow
OR range — the stop fires on noise before a signal has time to develop.

This applies specifically to configurations that use a stop (not no-stop mode).

### Academic support

- **Kestner (2003)**: ATR stops vs. fixed % stops across 15 futures markets over 20 years:
  **+28% Sharpe improvement, −19% max drawdown**.
- **Modern replications (2020–2025)**: 2× ATR stop produces −32% drawdown, +15%
  performance improvement vs. fixed stops.
- **Optimal intraday ATR multiplier**: 1.5×–2× ATR for day trading.

### Implementation

Replace the fixed `stop_pct × OR_range` with a hybrid floor:

```python
# In position monitor hard-stop calculation:
atr_5day = _compute_5day_atr(ticker_df, entry_date)
hard_stop_distance = max(
    self._stop_pct * or_range,   # existing OR-range stop
    1.5 * atr_5day               # ATR floor — prevents noise-triggered exits
)
```

ATR is computable from the warmup bars already fetched by the selector — no additional
data fetch needed.

---

## Improvement 6 — Condition Afternoon Windows on Morning Outcome
**Priority: 6 | Implementation: Config + small code | Confidence: Medium-High**

### Problem

A1 (1:15 PM) and A2 (3:00 PM) windows are currently entered unconditionally — capital is
deployed regardless of whether the morning signal succeeded. But morning momentum is
5× stronger than afternoon momentum, which means a failed morning is a regime signal
for the afternoon session.

### Academic support

**Gao, Han, Li & Zhou (JFE 2018) "Market Intraday Momentum"** — the definitive paper
on intraday time-of-day alpha:

| Window | Gross return | Notes |
|---|---|---|
| First 30-min (9:30–10:00) | ~41 bps/day | Strongest effect; institutional rebalancing |
| Afternoon (1:00–2:30 PM) | ~8 bps/day | Real but 5× weaker |
| Last 30-min (3:30–4:00 PM) | ~8 bps/day | Independent end-of-day effect |

4:00 PM returns revert the next morning — supports 3:55 PM force-close rule.

### Implementation

Gate A1 capital deployment on M1 outcome at +45 minutes:

```python
# In _on_window_drain() or sequential window capital logic:
if window_label == "A1":
    m1_pnl_at_1015 = self._window_realized_pnl.get("M1", Decimal("0"))
    if m1_pnl_at_1015 <= 0:
        logger.info("A1 skipped — M1 was negative at check time")
        return  # skip A1 entries; deploy into A2/A3 only
```

A2 (3:00 PM) does NOT require M1 confirmation — it captures the independent
last-30-min rebalancing effect identified in Gao et al. Weight A2 more aggressively
relative to A1 when running multi-window configs.

---

## Improvement 7 — Day-of-Week Filter
**Priority: 7 | Implementation: Small (validate first) | Confidence: Medium**

### Academic support

**Chuk (SSRN 2026)**: VIX + day-of-week (Mon/Wed/Fri) filter raises ORB win rate from
46.8% to 65.4%. Tue/Thu show systematically weaker ORB performance — likely due to
institutional rebalancing and options hedging flows concentrating on Mon/Wed/Fri.

### Validation step required

Before implementing, pull the 1,807-day replay log and compute average daily P&L by
day of week. If Mon/Wed/Fri show ≥15% higher average P&L than Tue/Thu, apply a sizing
multiplier:

```python
DOW_SIZING = {0: 1.0, 1: 0.80, 2: 1.0, 3: 0.80, 4: 1.0}  # Mon=0, Tue=1, ...
effective_slot = base_slot * DOW_SIZING[replay_date.weekday()]
```

Use a multiplier (not a binary exclude) — Tue/Thu still have positive expectation, just
lower. Reducing size by 20% on those days preserves participation while lowering exposure.

---

## Improvement 8 — Monthly Walk-Forward Ticker Pool Refresh
**Priority: 8 | Implementation: Process (not code) | Confidence: Medium**

### Problem

The 19-ticker pool is manually curated and updated episodically (V3 replaced V2 in
April 2026). Stale momentum leaders fade; new ones emerge. Static universes can also
inflate backtested results if the pool selection contains any hindsight.

### Academic support

- **CSSA Analytics (universe selection literature)**: Walk-forward pool refresh
  outperforms static universes — it eliminates look-ahead bias and adapts to changing
  momentum regimes.
- **Size vs. quality tradeoff (Indian equity study, MomentumLAB 2024)**: Small curated
  pools still generate meaningful alpha; dynamic refresh keeps the curation current.
- **Correlation risk**: Small tech-heavy pools can exhibit intraday cross-ticker
  correlation > 0.7 during sector selloffs. Dynamic refresh helps by rotating in
  lower-correlated candidates when tech-sector correlation spikes.

### Implementation (monthly process using existing tools)

1. Maintain a 40-ticker candidate pool (current 19 + 21 candidates across sectors)
2. On the first trading day of each month, run:
   ```bash
   python alpha_tech_tracker/op_momentum_strategy/op_momentum_selector_backtest.py \
     --tickers <all-40-candidates> \
     --start <63-trading-days-ago> --end <yesterday> \
     --window M1 09:30 3 --morning-split 100 \
     --regime-filter --regime-ma 8
   ```
3. Sort output by `win_rate × avg_win_pct` (Kelly composite)
4. Retain top 17–19 with constraint: ≥ 3 sectors represented
5. Update `--tickers` in the live engine config for the new month

The `op_momentum_screener_analysis/` pipeline already does this annually — the monthly
refresh applies the same tooling at a shorter horizon.

---

## Improvement 9 — HMM Regime Detection (Research Project)
**Priority: 9 | Implementation: High (multi-sprint) | Confidence: Medium**

### Problem

The current regime detection has a 2–5 day lag for bull→bear transitions
(MASTER_REGIME_SUMMARY: "Bull → Bear: 2–5 day lag — you absorb some losses first").
The first losing day of a bear month is unavoidable; the next 2–4 days are not.

### Academic & industry support

- **Two Sigma**: Uses Hidden Markov Models (HMM) for regime identification — multi-state
  (3–5 states: strong bull, mild bull, neutral, mild bear, strong bear) vs. the current
  binary LONG/SHORT approach. HMM is trained on observable signals and updates in near
  real-time rather than requiring a rolling confirmation window.
- **HMM Intraday Momentum (arXiv 2020)**: HMM applied to intraday momentum signals
  identifies regime transitions within 1–2 bars vs. the 3–5 day lag in rolling checks.
- **Deep Momentum + Changepoint Detection (arXiv 2021)**: Changepoint detection added
  to momentum models reduces lag on regime transitions by ~60%.

### Input data (already available)

The 11-year dataset provides daily:
- `signal_count` (fires per day)
- `eod_win_rate`
- `avg_hold_return` at +15m, +30m, +1h, +2h, +5h, EOD
- `hold_curve_slope` (rising/flat/declining)

A 3-state HMM trained on these features (BULL / NEUTRAL / BEAR) would:
1. Identify transitions 1–2 days earlier than the current 5-day rolling check
2. Assign transition probabilities (soft regime) rather than binary states
3. Scale position sizes proportionally to the bull probability rather than on/off

### Suggested starting point

```python
# Use hmmlearn library (already in Python ecosystem)
from hmmlearn import hmm
model = hmm.GaussianHMM(n_components=3, covariance_type="full", n_iter=100)
X = np.array([[wr, count, eod_ret] for wr, count, eod_ret in daily_observations])
model.fit(X[:-252])   # train on all but the last year
states = model.predict(X)  # 0=bull, 1=neutral, 2=bear
```

---

## Implementation Sequence

### Sprint 1 — High-confidence, low-effort (backtest before deploying)
1. Switch sort key from `win_rates[None]` to `medians[None]` in `_rank_tickers_by_eod_win_rate`
2. Expose `--rank-weighted-sizing` in `WinRateTickerSelector` via rank-proportional `ev_trade` sentinel
3. Run 2018–2025 full replay to confirm improvements, check for regressions

### Sprint 2 — Structural exit improvement
4. Wire `RegimeState.hold_window_minutes` to `PositionMonitor` force-close time
5. Add September/December/August hold-window values to `get_current_regime()` output
6. Run Sep/Dec/Aug months in isolation to measure improvement

### Sprint 3 — Volatility regime gating
7. Add VIX pre-market fetch to `WinRateTickerSelector.fetch_bars()` or engine pre-market routine
8. Implement `--vix-regime-gate` flag with position-count reduction by VIX band
9. Backtest 2020 (COVID vol), 2022 (bear VIX spikes) to validate drawdown reduction

### Sprint 4 — Afternoon window conditioning & day-of-week
10. Validate day-of-week P&L distribution from existing replay logs
11. If Mon/Wed/Fri advantage confirmed: add DOW sizing multiplier
12. Gate A1 entries on M1 outcome at +45 minutes

### Sprint 5 — Pool refresh process
13. Establish 40-ticker candidate list
14. Run first monthly walk-forward refresh
15. Document results vs. static pool for the same period

### Sprint 6+ — Research projects
16. ATR-based hybrid stop (requires ATR computation in warmup bars)
17. HMM regime detection prototype

---

## Summary Table

| # | Improvement | Effort | P&L impact | Stability impact | Academic source |
|---|---|---|---|---|---|
| 1 | Kelly composite ranking (medians sort) | 1 line | High | Low | Kelly; Zarattini 2024 |
| 2 | VIX regime gate (position count) | Medium | High | High (crash protection) | Chuk 2026; Daniel & Moskowitz 2016 |
| 3 | Rank-weighted sizing in win-rate mode | Small | High | Medium | AQR; Kelly theory |
| 4 | Regime hold-window → exit time | Medium | High | High | MASTER_REGIME_SUMMARY 11yr data |
| 5 | ATR floor for hybrid stop | Medium | Medium | Medium | Kestner 2003 (+28% Sharpe) |
| 6 | Condition A1 on M1 outcome | Small | Medium | Medium | Gao et al. JFE 2018 |
| 7 | Day-of-week filter (validate first) | Small | Unknown | Low | Chuk 2026 |
| 8 | Monthly pool walk-forward refresh | Process | Medium-term | Medium | CSSA; universe selection lit |
| 9 | HMM regime detection | High | High (lag cut 3–5d → 1d) | High | Two Sigma; arXiv 2020/2021 |

---

*Created: 2026-06-04*
*Based on: WIN_RATE_SELECTOR_BACKTEST.md, MASTER_REGIME_SUMMARY.md,*
*win_rate_selector_capital_deployment_comparison.md, WIN_RATE_SELECTOR_MODE.md*
*Academic sources: Zarattini et al. SSRN 2024, Chuk SSRN 2026, Gao et al. JFE 2018,*
*Daniel & Moskowitz JFE 2016, Kestner 2003, Moreira & Muir 2017, Kelly criterion literature*

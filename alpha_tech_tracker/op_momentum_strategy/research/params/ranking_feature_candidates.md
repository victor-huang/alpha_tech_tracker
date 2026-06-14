# Ranking Feature Candidates — SOTA Momentum Gap Analysis

Date: 2026-05-25
Context: Comparison of the current `score_ticker()` formula in `op_momentum_selector.py` against state-of-the-art momentum literature and intraday-trading practice. Goal: identify high-signal feature dimensions not yet exploited.

---

## Current ranking inputs (baseline)

From `op_momentum_selector.py:275-372` + `CLAUDE.md`:

| Group | Features used |
|---|---|
| Intraday signal quality | `entry_vs_mid_pct`, `or_range_pct`, `or_vol_ratio`, ADR-normalized OR (e05ebd7), MA20/MA50 gate, QQQ OR alignment (cfbc4db) |
| Historical edge | `avg_win_pct`, `win_rate`, `ev_trade`, `ev_trend` on 60-day rolling |
| Daily context | `dist_52w_low_pct`, `consec_streak`, `prev_day_vol_ratio`, `daily_ma200_dist`, `daily_ma50_dist`, direction-aware `trend_align` |
| Regime gate (binary, not in score) | QQQ MA8 |

---

## Tier 1 — directly fills gaps in current model

### 1. Distance to 52-week HIGH (George & Hwang 2004)
The single most replicated cross-sectional momentum anomaly. We track `dist_52w_low` but not high. Near-high stocks breaking out of an OR have a documented edge over far-from-high stocks doing the same setup.
- Data: daily bars only — already cached.
- Compute: `(price - 52w_high) / 52w_high` (negative or zero).
- Direction-aware: reward proximity for BULLISH, penalize for BEARISH (mirror with 52w-low).

### 2. Path smoothness / "Frog-in-the-Pan" (Da, Gurun, Warachka 2014)
A 60-day return achieved via many small steady up-days outperforms the same return achieved via a few big jumps. Current EV stats reward magnitude but are blind to information discreteness.
- Compute: `|days_up - days_down| / total_days` over 60d lookback, or signed-day-count z-score.
- Lower discreteness = stronger continuation.

### 3. Overnight vs intraday return decomposition (Lou, Polk, Skouras 2019)
Stocks where recent returns are driven by **overnight** moves (retail/sentiment) behave very differently from those driven by **intraday** moves (institutional flow). Strong filter for fade-vs-continue.
- Compute over 20d: `overnight_return_share = sum(open_t / close_{t-1} - 1) / sum(total_return)`.
- High overnight share = lower continuation odds; high intraday share = higher.

### 4. First-30-min return as continuation predictor (Gao, Han, Li, Zhou 2018)
The morning return predicts the afternoon return with statistical significance. Our `entry_vs_mid_pct` captures *where* price closed in the OR, not the *signed magnitude* of the opening move relative to historical first-30-min behavior.
- Compute: `or_close_return = (or_close - prev_close) / prev_close`, then z-score against 60-day distribution of same-window returns for the ticker.

### 5. Idiosyncratic / beta-adjusted momentum (Blitz, Huij, Martens 2011)
Residualize each ticker's recent return against QQQ. A stock up 20% in a market up 18% has near-zero idio momentum; up 20% in a flat market has lots. We already have QQQ regime gating; the missing piece is using **residual** return as a positive ranking input.
- Compute: rolling 60-day regression of ticker daily return on QQQ daily return → use intercept + residual sum.

---

## Tier 2 — microstructure features for intraday systems

### 6. Volume-weighted OR position
Today we use closing tick's position in OR. VWAP-in-OR captures whether buying was distributed across the range (strong) vs concentrated at one extreme (weak / late-arriving).
- Compute from the 3 × 5-min OR bars: `(VWAP_OR - or_low) / or_range`.

### 7. Cumulative signed volume / order-flow imbalance during OR
Even a coarse uptick/downtick proxy gives an edge over equal-weight volume.
- Compute: for each OR bar, `signed_vol = volume * sign(close - open)`. Sum across 3 bars, normalize by total volume.

### 8. Bar shape on OR-close bar
Tells you whether the close at OR-high was a clean push (full body, no upper wick) vs a faded test (long upper wick).
- `body_ratio = |close - open| / (high - low)`
- `upper_wick_ratio = (high - max(open,close)) / (high - low)`
- `lower_wick_ratio = (min(open,close) - low) / (high - low)`

### 9. Pre-market gap magnitude + first-15-min gap-fill flag
Gap-and-go (gap that holds) vs gap-fade (gap filled in OR) are statistically distinct setups. Currently both are treated the same.
- `gap_pct = (today_open - prev_close) / prev_close`
- `gap_filled_in_or = (gap_up and or_low <= prev_close) or (gap_down and or_high >= prev_close)`

### 10. Time-of-day-conditional RVOL
Replace `or_vol_ratio` (vs same-day average) with: this 9:30–9:45 volume vs prior 20 days' 9:30–9:45 volume. Standard "RVOL" used by intraday desks.

---

## Tier 3 — risk / regime features

### 11. Realized-volatility penalty (Asness-Frazzini-Pedersen)
Low-vol winners outperform high-vol winners in cross-sectional momentum. ADR normalization helps signal scale but isn't used as a *cost* in ranking.
- Compute 20d realized vol → penalize high-vol tickers in score.

### 12. MAX effect (Bali, Cakici, Whitelaw 2011)
Penalize tickers with a recent single-day extreme positive return; lottery-like stocks underperform.
- `max_daily_return_20d` → negative weight.

### 13. Bayesian shrinkage of ticker EV
60-day rolling EV on 17 tickers is small-sample noisy. Shrinking each ticker's EV toward the pool mean (weight by sample count) materially improves out-of-sample momentum portfolios.
- `ev_shrunk = (n_signals * ev_ticker + k * ev_pool_mean) / (n_signals + k)`, with `k` ≈ 5–10.

### 14. Option-market features (IV percentile, skew, put/call OI)
We already trade options, so the data is essentially free. Front-week IV often telegraphs continuation vs reversal.

---

## Tier 4 — biggest potential edge, more effort

### 15. Earnings calendar / post-earnings drift (PEAD)
Earnings beats produce persistent multi-week drift. "N days post-earnings" + "beat/miss" is highly predictive.

### 16. News sentiment / catalyst presence
Even a binary "had ≥1 news item in last 24h" boosts breakout reliability.

### 17. Cross-sectional z-score ranking
Refactor: turn all features into within-pool z-scores per day, then sum. More robust to feature-scale drift than the current additive-with-hand-tuned-weights formula. This is the standard AQR/2Sigma momentum-book construction.

---

## Recommended next steps

If picking 4 features to backtest first (cheapest data, highest documented effect size on intraday/short-horizon momentum):

1. **52-week high proximity** (Tier 1, #1)
2. **Overnight vs intraday return share** (Tier 1, #3)
3. **VWAP-in-OR + OR-close bar shape** (Tier 2, #6 + #8)
4. **Bayesian shrinkage of ticker EV** (Tier 3, #13 — improves what we already compute)

Action: draft a sweep against the 2021–2025 backtest with each added incrementally to the current formula (weight ∈ {0.05, 0.10, 0.15, 0.20}), measure ΔP&L and Δwin-rate per year + 5-year compound.

---

---

# Part 2 — Bear / Choppy Regime Momentum

The features above optimize for the dominant pattern in our backtests: trending up-tape continuation. Down years (2018 Q4, 2020 H1, 2022, 2025) and choppy years behave structurally differently. This section catalogs what's documented to work in those regimes and what we currently lack.

## What's structurally different in down/chop regimes

1. **Asymmetry of down moves** (Black 1976 "leverage effect"): downside moves are faster and more volatile than upside moves of equal magnitude. Bear OR breakdowns travel further in less time — argues for tighter stops and faster trailing on BEARISH signals.
2. **Momentum crashes** (Daniel & Moskowitz 2016): cross-sectional momentum factor has its worst drawdowns at the *transition* from bear to bull (March 2009, April 2020). Past winners become past losers overnight. Our `ev_trade` lookback (60d) and `consec_streak` features will be *most wrong* exactly at these turns.
3. **Trend-following beats cross-sectional in bears**: 2008, 2018, 2022 — *time-series* momentum (TSMOM, Moskowitz-Ooi-Pedersen 2012) outperforms cross-sectional momentum because correlations rise to 1 and security selection adds no value. The "what to trade" question dissolves; only "long or short" matters.
4. **Chop ≠ down-trend**: a sideways VIX-elevated tape (most of 2015, parts of 2023, 2025 YTD) destroys both long and short breakout systems. Mean reversion (fade extremes) beats momentum here. Detecting *which regime* matters more than feature selection within a regime.
5. **Failed breakouts dominate**: the OR-high-tag-then-fade is the signature pattern of chop and bear rallies. Currently we trade it as a primary BULLISH, then sometimes re-enter via reversal — the up-front filter is missing.

## Features and structural changes we don't have

### Regime / chop detection (Tier 1)

#### A. VIX level + term structure
- **VIX level** > 25: short-side EV documented to be higher; long-side EV degraded.
- **VIX9D / VIX ratio > 1.0** (term structure backwardation): panic / continuation regime. Historically the single best "short trend day" signal.
- Use as a multiplicative scoring boost on BEARISH signals + reduction on BULLISH signals, not a hard gate.

#### B. Chop detection — ADX / Choppiness Index / Hurst exponent
- **ADX < 20** on daily QQQ = sideways tape → suppress breakout-entry sizing or skip entirely.
- **Choppiness Index** (Dreiss): `100 * log10(sum(TR,N) / (max(High,N) - min(Low,N))) / log10(N)`. Values > 61.8 = choppy, < 38.2 = trending. Cheap to compute, well-tested by intraday traders.
- **Hurst exponent** > 0.55 = trending; < 0.45 = mean-reverting. Costly but the academically standard regime classifier.

#### C. Bear-regime gate (mirror of current QQQ MA8 long gate)
We currently use QQQ MA8 to gate any trade. For asymmetric scoring:
- QQQ < MA8 *and* MA8 < MA21 = bear regime → boost BEARISH EV weight, lower BULLISH score floor.
- QQQ > MA8 *and* MA8 > MA21 = bull regime → current behavior.
- Mixed = chop → trade smaller or skip.

#### D. Market internals — breadth, advance/decline, sector dispersion
- **Cumulative TICK** (NYSE TICK), **Advance/Decline line**, **% of S&P above 50-day MA**: leading indicators of regime turns. Daily features only — cheap.
- **Sector dispersion** (cross-sectional std of XLK, XLU, XLP, XLY, XLE returns): low dispersion = correlation-to-1 = bear regime. High dispersion = stock-picking regime.

### Asymmetric short-side features (Tier 1)

#### E. 52-week LOW proximity (George-Hwang mirror)
Mirror of the long-side feature in Part 1. Stocks breaking *below* OR while near 52-week lows have stronger continuation than stocks breaking below from healthy uptrends.

#### F. Short-interest / borrow-rate filter
Avoid shorting high-short-interest names (squeeze risk). Conversely, *fading rallies* in high-SI names in a bear regime is a documented edge (the "short squeeze fade"). Data: FINRA short interest, Ortex, S3.

#### G. Credit-spread signal — HYG / LQD ratio
HYG (high-yield) underperforming LQD (investment-grade) is one of the most reliable leading indicators of equity stress. A 5–10 day declining HYG/LQD ratio gives a 1–3 day lead on equity weakness. Use to up-weight BEARISH signals.

#### H. Defensive-ticker leadership flag
When XLU, XLP, GLD lead XLY, XLK, XLF on rolling 5d basis → defensive regime → bias short-side scoring.

### Failed-breakout / fakeout features (Tier 2)

#### I. Pre-OR overnight gap reversal
Gap-up that fills in OR → BEARISH bias. Gap-down that fills in OR → BULLISH bias. (Mirror of feature #9 in Part 1, but used as a *primary* signal in chop rather than just a tie-breaker.)

#### J. OR-high tag + reject
If `or_high` was touched but close is in bottom 50% of OR → "failed breakout" → primes a SHORT signal even when our current BEARISH conditions don't fire (close not in bottom 20%). This is the single most-traded chop setup by discretionary traders.

#### K. Lower-high / lower-low daily structure
Two consecutive lower daily highs + lower daily lows = bearish market structure. Trivial daily feature. Boost BEARISH EV weight.

### Mean-reversion overlay for chop (Tier 2)

#### L. RSI-2 / RSI-5 extremes on daily bars
In detected chop regime (#B above), fade extremes instead of trading breakouts: RSI(2) > 90 = short, RSI(2) < 10 = long. This is the Larry Connors family of systems — documented to outperform momentum in sideways tapes.

#### M. Distance-from-20MA on intraday basis
2+ ATR above MA20 in choppy regime = mean-reversion short candidate. Currently used as a momentum *gate*, not as a counter-trend signal.

### Momentum-crash protection (Tier 3)

#### N. Drawdown of strategy itself as a regime signal (Daniel-Moskowitz)
When recent strategy P&L is in steep drawdown *and* market is rallying off a low, **reduce position sizing** or **flatten**. This is the simplest known fix for the momentum-crash problem. Implementable as: rolling 10-day strategy DD > X% AND QQQ 5d return > Y% → cut size by 50%.

#### O. Volatility scaling (Moskowitz-Ooi-Pedersen)
Size each position inversely to recent realized vol. Standard TSMOM construction: `position_size = target_vol / realized_vol`. Smooths returns across regimes and is the closest thing the academic literature has to a "regime-free" momentum implementation.

### Defensive / convexity overlay (Tier 3)

#### P. Long-volatility tail hedge
On VIX > 30 OR HYG/LQD signal, allocate a small fraction (1–3%) to long-VIX call positions. Pays for the cost of the rest of the system's drawdown in tail events. The "1.5% bleed for tail protection" trade.

#### Q. Regime-specific ticker pool
Maintain a *defensive* pool (utilities, staples, gold miners, TLT) for use during bear regimes — the current pool is high-beta growth (AMD, PLTR, COIN, MSTR, CRWV). In bear regimes those tickers *all* short well but also squeeze hard. A blended pool with low-beta names smooths bear-regime P&L.

## Years to backtest against

| Year | Character | What to verify |
|---|---|---|
| 2018 | Bull → Q4 crash → V-bounce | Did current system survive Oct–Dec 2018? Test regime gate + bear-side scoring boost. |
| 2020 | COVID crash + V-recovery | Test momentum crash protection (#N). Daniel-Moskowitz turn in March-April. |
| 2022 | Full bear, low VIX-of-VIX | Test bear-regime gate (#C) + credit signal (#G). |
| 2025 (full) | Choppy / bear-leaning | Test chop detection (#B) + failed-breakout primary signal (#J). |
| 2026 YTD | Mixed | Already have data — sanity check. |

## Recommended first 4 to test (bear/chop)

1. **Choppiness Index gate + VIX level filter** (#B + #A) — single regime classifier; expected to reduce false-positive breakouts.
2. **Failed-breakout primary BEARISH signal** (#J) — captures the dominant chop pattern we currently miss.
3. **Credit-spread (HYG/LQD) BEARISH boost** (#G) — daily-bar feature, free data via Alpaca.
4. **Volatility scaling / inverse-vol sizing** (#O) — regime-agnostic improvement that should help every year, but especially 2018 Q4 / 2020 / 2022.

Action: run each independently against 2018, 2020, 2022, 2025 with `--compound off`, compare Δ P&L per year and Δ max drawdown. The right test metric for bear-regime features is *drawdown reduction*, not total return.

---

## References

- George, T. J., & Hwang, C. Y. (2004). "The 52-week high and momentum investing." *Journal of Finance*.
- Da, Z., Gurun, U. G., & Warachka, M. (2014). "Frog in the pan: Continuous information and momentum." *Review of Financial Studies*.
- Lou, D., Polk, C., & Skouras, S. (2019). "A tug of war: Overnight versus intraday expected returns." *Journal of Financial Economics*.
- Gao, L., Han, Y., Li, S. Z., & Zhou, G. (2018). "Market intraday momentum." *Journal of Financial Economics*.
- Blitz, D., Huij, J., & Martens, M. (2011). "Residual momentum." *Journal of Empirical Finance*.
- Asness, C., Frazzini, A., & Pedersen, L. (2014). "Quality minus junk." *AQR Working Paper*.
- Bali, T. G., Cakici, N., & Whitelaw, R. F. (2011). "Maxing out: Stocks as lotteries and the cross-section of expected returns." *Journal of Financial Economics*.
- Jegadeesh, N., & Titman, S. (1993). "Returns to buying winners and selling losers." *Journal of Finance*.
- Daniel, K., & Moskowitz, T. (2016). "Momentum crashes." *Journal of Financial Economics*.
- Moskowitz, T., Ooi, Y. H., & Pedersen, L. (2012). "Time series momentum." *Journal of Financial Economics*.
- Black, F. (1976). "Studies of stock price volatility changes." *Proceedings of the American Statistical Association*.
- Dreiss, E. W. (1993). "The Choppiness Index." (technical analysis literature)
- Connors, L., & Alvarez, C. (2009). *Short Term Trading Strategies That Work*. TradingMarkets Publishing.

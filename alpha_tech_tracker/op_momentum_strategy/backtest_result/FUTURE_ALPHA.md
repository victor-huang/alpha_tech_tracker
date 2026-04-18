# Future Alpha Research

Research into hedge fund strategies, academic papers, and practitioner findings relevant to
the op-momentum strategy. Covers areas worth exploring, areas to avoid, and competitive context.

Compiled: 2026-04-11

---

## Competitive Context — Comparable Funds & Academic Strategies

### Zarattini, Barbon & Aziz (Concretum Group) — Closest Academic Parallel

The most directly comparable published research to this strategy.

**Paper: "A Profitable Day Trading Strategy For The U.S. Equity Market" (2024)**
- Universe: 7,000 US stocks, 2016–2023
- Method: 5-minute ORB on "Stocks in Play" (unusually high pre-market volume from catalysts)
- Top-20 Stocks in Play portfolio: **+1,600% net, Sharpe 2.81, annualized alpha 36%**
- Key finding: restricting to high-activity names is the primary alpha driver — random stock
  selection with the same ORB rules produces far weaker results
- https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4729284
- https://www.quantconnect.com/research/18444/opening-range-breakout-for-stocks-in-play/

**Paper: "Beat the Market: Intraday Momentum for SPY" (2024)**
- Applied to SPY only with trailing stops on supply/demand imbalance
- 2007–2024: **+1,985% net, Sharpe 1.33, annualized 19.6%**
- https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4824172
- https://concretumgroup.com/papers/

**Takeaway for this strategy**: Our options-leveraged version on 16 high-beta tickers
structurally outperforms their equity-only benchmark. The fixed high-beta pool (V2/AT) is
the equivalent of their "Stocks in Play" filter — pre-screened for OR breakout quality.

---

### Gao, Han, Li & Zhou — Seminal Academic Foundation

**Paper: "Intraday Momentum: The First Half-Hour Return Predicts the Last Half-Hour Return"**
(Journal of Financial Economics, 2015)
- S&P 500 ETF, 1993–2013
- First 30-min return predicts last 30-min return; simple long/short: **+6.34% annualized on SPY**
- Effect strongest on: high volatility days, high volume days, recession periods, macro news days
- Replicated globally across 17 developed markets, Sharpe 0.87–1.73 per asset class
- Theoretical underpinning for why multiple intraday windows (M1 at 9:30, A1 at 1:15,
  A2 at 3:00) each independently capture distinct phases of institutional and retail flow
- PDF: https://c.mql5.com/forextsd/forum/173/intraday_momentum_-_the_first_half-hour_return_predicts_the_last_half-hour_return.pdf
- Summary: https://alphaarchitect.com/attention-prop-traders-the-first-half-hour-of-trading-predicts-the-last-half-hour/

---

### Renaissance Technologies (Medallion Fund)

- 66% gross / 39% net annually 1988–2018
- Right on only **~50.75% of trades** — edge from tiny per-trade advantages applied at scale
- Uses Hidden Markov models for regime detection and Bayesian updating; single unified model
- Beta to S&P 500 ≈ −1.0 (effectively market-neutral)
- **Takeaway**: validates "concentrate on edge, filter aggressively" principle. Our MA8 regime
  filter and top-N weighted selection are structurally analogous. Replication of their scale
  is impossible but their selectivity principle is already embedded in this strategy.
- https://www.quantvps.com/blog/jim-simons-trading-strategy
- https://www.quantifiedstrategies.com/jim-simons/

---

### Jane Street

- Their disclosed intraday options approach (2024 Manhattan legal proceeding): short both calls
  and puts simultaneously, expecting range-bound conditions, then unwind before close
- This is the **inverse** of this strategy — premium selling, not directional momentum
- Their edge is in gamma management and market-making, not forecasting
- **Takeaway**: not a relevant model. Different alpha source entirely.
- https://www.npr.org/transcripts/nx-s1-5551163

---

## Alpha Sources Worth Exploring

### 1. Earnings Calendar Filter ★★★ HIGH PRIORITY — lowest effort

**Evidence**: Practitioner consensus across Option Alpha, Market Chameleon, Predicting Alpha.
ORB signals during earnings windows are contaminated by IV crush and gap behavior driven by
fundamental surprise, not technical momentum. Strategies that explicitly filter out earnings
days show improved Sharpe and reduced drawdown.

**Implementation**: Flag any ticker in the pool with earnings within ±2 trading days.
Skip that ticker's signals for those days. If only 1 eligible ticker remains after filtering,
use single-slot sizing. No predictive modelling required — calendar lookup only.

**Expected impact**: Fewer blowup days, cleaner EV distribution per ticker.

References:
- https://optionalpha.com/blog/earnings-edge-backtested-earnings-trade-ideas
- https://www.predictingalpha.com/earnings-options-strategy/
- https://marketchameleon.com/EarningsReport/EarningsOptionStrategyScreener

---

### 2. VIX/VIX3M Term Structure as Secondary Regime Gate ★★★ HIGH PRIORITY

**Evidence**: When VIX (30-day IV) exceeds VIX3M (90-day IV), the term structure inverts to
backwardation — a signal of acute market stress. Research shows:
- Backwardation is a contrarian BULLISH equity signal, marking oversold conditions
- Deep backwardation (ratio > 1.10) historically marks the best re-entry points after the
  ratio begins to roll back to contango
- VIX/VIX3M > 1.05 during a QQQ above-MA8 day = conflicted signal; reduce BULLISH size

**Why complementary to MA8**: MA8 is slow and trend-following (lags several days). VIX term
structure is real-time stress detection. They trigger on different market conditions.

**Implementation**:
- VIX/VIX3M > 1.05 AND QQQ above MA8 → reduce BULLISH position size 30–50%
- VIX/VIX3M > 1.15 → skip BULLISH signals regardless of MA8
- VIX/VIX3M rolling back below 1.0 from above → aggressive BULLISH sizing signal

References:
- https://macrosynergy.com/research/vix-term-structure-as-a-trading-signal/
- https://flashalpha.com/articles/volatility-term-structure-contango-backwardation-events
- https://quantpedia.com/strategies/exploiting-term-structure-of-vix-futures
- https://www.cboe.com/insights/posts/inside-volatility-trading-is-vix-backwardation-necessarily-a-sign-of-a-future-down-market/

---

### 3. Pre-Market Gap Direction as Signal Alignment Filter ★★ MEDIUM PRIORITY

**Evidence**: Lou, Polk & Skouras ("A Tug of War: Overnight vs Intraday Expected Returns")
found that essentially all three-factor momentum alpha accrues overnight (0.95%/month overnight
vs 0.11%/month intraday). Pre-market gap direction reflects overnight informed-trader flow.

When a stock gaps up overnight AND fires a BULLISH ORB signal, two independent signals are
aligned — overnight informed flow + intraday momentum. When they conflict (gap down, BULLISH
ORB), the signal is weaker.

**Implementation**: Add pre-market gap direction as a ranking tie-breaker in the score formula.
Gap-aligned signals get a scoring bonus; conflicting gap signals get a penalty or half sizing.
Low implementation cost — prior close and pre-market open are both available at 9:30 AM.

References:
- http://www.econ.yale.edu/~shiller/behfin/2015-04-11/lou_polk_skouras.pdf
- https://www.researchgate.net/publication/349675327_The_cross-section_of_intraday_and_overnight_returns

---

### 4. IV Rank-Based Position Sizing ★★ MEDIUM PRIORITY

**Evidence**: Notre Dame intraday options papers document that options bought at low IV Rank
have better expected P&L because directional gains are not offset by IV crush, and vol expansion
from the intraday move can add to P&L. Morning IV changes of +0.42% aligned with momentum
winner patterns signal genuine informed flow vs. noise.

- IV Rank < 30 (cheap options): full position size
- IV Rank 30–60 (normal): standard size
- IV Rank > 60 (expensive options): half size or use stock instead

**Requires**: adding an IV Rank data source at signal time (Barchart API or CBOE data feed).

References:
- https://www3.nd.edu/~zda/IntraOption.pdf
  ("Intraday Option Return: A Tale of Two Momentum")
- https://www3.nd.edu/~zda/intramom.pdf
  ("Hedging Demand and Market Intraday Momentum")
- https://www.sciencedirect.com/science/article/abs/pii/S1386418120300343
  ("Options-Implied Information and the Momentum Cycle")
- https://www.barchart.com/options/iv-rank-percentile

---

### 5. VWAP-Trailing Exit for Afternoon Windows ★★ MEDIUM PRIORITY

**Evidence**: Maróy (2025) extended the Zarattini SPY momentum strategy with VWAP-based exits
and improved Sharpe from under 2.0 to **above 3.0**, with annualized returns above 50%.
VWAP is a natural intraday support/resistance level where institutional rebalancing occurs.
The U-shaped intraday volume curve means VWAP is most meaningful in the 10:00–11:30 AM and
2:30–3:55 PM windows — matching the A1 (1:15 PM) and A2 (3:00 PM) window structure.

**Implementation**: For A1 and A2 windows, replace hard 3:55 PM EOD close with a VWAP-trail
stop. Exit when price crosses VWAP against the position direction, capped at 3:55 regardless.
M1 morning window keeps the current EOD close (VWAP less useful mid-day).

**Note**: backtest requires VWAP per-bar data, which must be computed from 5-min bars.

References:
- https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5095349
  (Maróy 2025 — VWAP exit optimization)
- https://www.sciencedirect.com/science/article/abs/pii/S0378426607003226
- https://web.stanford.edu/~boyd/papers/pdf/vwap_opt_exec.pdf

---

### 6. Volume Put/Call Ratio as Pre-Signal Confirmation ★★ MEDIUM PRIORITY (higher effort)

**Evidence**: Pan & Poteshman (2006, Journal of Finance) — stocks with low 5-day volume PCR
(more call buying) outperform by **40+ basis points the next day**. Source is nonpublic
information in the options market (hedge fund flow), not technical noise. Replicated
across multiple markets. IV spread (IV_call − IV_put) and IV skew further identify
early-stage vs late-stage momentum direction.

**Implementation**: Before confirming a ticker as top-2, check that the 5-day volume PCR
is directionally consistent with the signal:
- BULLISH signal: PCR below its 20-day median (more call activity than put activity)
- BEARISH signal: PCR above its 20-day median (elevated put demand)

**Requires**: real-time options volume data (available via Alpaca options API or Barchart).

References:
- https://www.nber.org/system/files/working_papers/w10925/w10925.pdf
  (Pan & Poteshman — Information of Option Volume for Future Stock Prices)
- https://www.sciencedirect.com/science/article/abs/pii/S038742661400106X
  (PCR as predictor — ScienceDirect)
- https://www.sciencedirect.com/science/article/abs/pii/S0304405X16000167
  (O/S ratio and stock returns — ScienceDirect)
- https://www.mdpi.com/2227-7099/7/1/24
  (Volume PCR vs Open Interest PCR — MDPI)

---

### 7. Fractional Kelly / Volatility-Adjusted Sizing ★ LOWER PRIORITY

**Evidence**: arXiv 2025 (Kelly+VIX hybrid for put-writing options) found improved information
ratios and lower max drawdowns vs fixed sizing. Short memory (3–5 day lookback) outperforms
longer lookbacks for intraday options. Always use 0.5× Kelly (half-Kelly) to control variance.

Kelly fraction = W − (1−W)/R, where W = rolling 20-day win rate, R = avg_win / avg_loss.
Position size = Kelly fraction × 0.5 × slot_capital.

**Caution**: Full Kelly causes extreme concentration in winning streaks. Half-Kelly is standard.
Our existing 60/40 weight scheme is structurally Kelly-like; this would be a per-ticker
dynamic overlay on top of the rank-based weights.

References:
- https://arxiv.org/html/2508.16598v1
  (Kelly + VIX hybrid for options, 2025)
- https://www.frontiersin.org/journals/applied-mathematics-and-statistics/articles/10.3389/fams.2020.577050/full
- https://blog.quantinsti.com/risk-constrained-kelly-criterion/

---

## Areas to Avoid / Deprioritize

### Standard TA Indicators (RSI, MACD, Bollinger Bands) — SKIP

Already covered. MA20 is the trend filter; OR high/low is the volatility band; stop-pct is the
range-based hard stop. Additional indicators are redundant at 5-minute bar frequency.
Zarattini et al. explicitly show simple ORB outperforms TA-overlay in the same universe.
Near-zero net alpha in liquid large-cap equities after transaction costs.

### Fundamental Analysis Signals — SKIP

Quarterly cadence vs. minute-level signals. Lookahead risk (which quarter is "known" at
9:30 AM?). No academic evidence that P/E, revenue growth, or earnings quality signals
improve intraday ORB alpha. Pool is pre-screened; adding fundamental filters re-introduces
selection bias.

### Overnight / Multi-Day Holds — SKIP

Weekly options theta and earnings gap risk work against overnight holds.
The EOD 3:55 PM force-close is academically validated by Zarattini et al. as
one of the most important structural implementation details for ORB strategies.
Multi-day options momentum is a different strategy (longer gamma exposure, different
capital requirements).

### Sector Rotation / Cross-Sector Signals — SKIP

Confirmed by internal sector screen (Finding 6 in FINDINGS.md): adding GS, JPM, REGN, VRTX
to the pool reduces 5-year return from +330% to +328–329% despite strong individual EV.
Cross-sector signals work at quarterly frequency (Concretum Group's "Century of Profitable
Industry Trends"), not intraday. Concentration in the highest-EV names outperforms
diversification.

### Low-Liquidity Tickers — SKIP

ANAB removed for sparse bars (17/day); UI removed for Alpaca sparse extended-hours bars.
Pool V2 and AT are already optimized for liquidity. Adding thin names introduces:
- Wide bid/ask on options (execution slippage wipes alpha)
- Missing bars that break MA series continuity
- Unreliable OR formation

### Complex ML Signal Extraction — DEPRIORITIZE

Renaissance and Two Sigma succeed with ML because of decades of clean tick data, PhD teams,
and out-of-sample validation infrastructure. For a solo trader on a 7-year backtest:
- Overfitting risk far exceeds potential gain
- Simple ORB + selectivity achieves Sharpe 2.81 without ML (Zarattini 2024)
- Adding ML layers to a working strategy is a documented failure mode in the academic
  literature on strategy decay

---

## Priority Implementation Roadmap

| Priority | Feature | Effort | Expected Impact |
|---|---|---|---|
| 1 | Earnings calendar filter | 1 day | Fewer blowup days, cleaner EV |
| 2 | VIX/VIX3M secondary regime gate | 2–3 days | Complements MA8, real-time stress detection |
| 3 | Pre-market gap alignment scoring | 1–2 days | Independent confirming signal, low complexity |
| 4 | IV Rank tiered position sizing | 3–5 days | Reduces IV crush drag on options buying cost |
| 5 | VWAP-trailing exit for A1/A2 | 3–5 days | Targeted Sharpe uplift on afternoon windows |
| 6 | Volume PCR pre-signal filter | 5–7 days | Strong academic backing, requires options data feed |
| 7 | Half-Kelly dynamic sizing | 3–4 days | Marginal improvement over current 60/40 scheme |

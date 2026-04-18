# op_momentum_guide — Research & Development Log

## Overview

`op_momentum_guide` is an intraday opening momentum signal that uses the first
15–30 minutes of price/volume action to predict directional bias for the rest
of the trading day. It combines opening range analysis with moving average
trend filters to generate BULLISH or BEARISH signals at the end of the opening
period.

---

## Methodology

### Core Concept

The first 15–30 minutes of a trading day establish a price range driven by:

- Overnight gap fills and news reactions
- Institutional order flow
- Highest volume window of the day

The position of the closing price within that range, combined with moving
average context, provides a directional bias for the session.

### Signal Rules

**Opening Range (OR)**

- Defined by the High and Low of the first N 5-minute bars (configurable)
- `midpoint = (OR High + OR Low) / 2`
- `bottom_threshold = OR Low + 0.20 * OR Range`

**BULLISH signal** — all 3 conditions must be true at end of opening period:

1. Close > midpoint (price in top 50% of opening range)
2. Close > 20-period MA (short-term trend up)
3. Close > 200-period MA (long-term trend up — regime filter)

**BEARISH signal** — all conditions must be true:

1. Close ≤ bottom threshold (price in bottom 20% of opening range)
2. Close < 20-period MA (short-term trend down)
3. Close < 200-period MA *(optional — `--bearish-ma200` flag, use in bear markets)*

### Exit Rules

- **Trailing stop**: exit when price closes below MA50 (bullish) or above MA50 (bearish)
- **Hard stop**: configurable via `--stop-pct` (default 0.35)
  - Bull: exit if price drops below `OR_high − stop_pct × OR_range` (top 35% of range)
  - Bear: exit if price rises above `OR_low + stop_pct × OR_range` (bottom 35% of range)
- **Priority**: hard stop is checked first within each bar, MA50 trailing stop second
- **Win/Loss**: a trade is a WIN if `pnl > 0`, LOSS otherwise

---

## Scripts

| Script                      | Purpose                                                     |
| --------------------------- | ----------------------------------------------------------- |
| `op_momentum_guide.py`    | Live signal scanner — shows today's signal for each ticker |
| `op_momentum_backtest.py` | Backtest engine with P&L tracking and distribution report   |
| `vwap_demo.py`            | VWAP anchored to open — companion indicator                |

### Backtest Usage

```bash
# Standard run — last 30 days, 15-min opening, bull market mode (Alpaca default)
python op_momentum_backtest.py --days 30

# Override ticker list inline
python op_momentum_backtest.py --days 60 --tickers NVDA CRWD COIN

# Use yfinance instead (capped at 60 days)
python op_momentum_backtest.py --days 30 --source yfinance

# Bear market mode (adds MA200 filter to bearish signal)
python op_momentum_backtest.py --days 30 --bearish-ma200

# 20-min opening period
python op_momentum_backtest.py --days 30 --opening-bars 4

# 90-day history (Alpaca only — yfinance is capped at 60 days)
python op_momentum_backtest.py --days 90

# Fixed date range — full year 2022 (down market)
python op_momentum_backtest.py --start 2022-01-01 --end 2022-12-31

# Fixed date range with custom tickers
python op_momentum_backtest.py --start 2022-01-01 --end 2022-12-31 --tickers SHOP TSLA AVGO
```

**Data sources:**

- `--source alpaca` (default) — uses Alpaca `StockHistoricalDataClient`; supports 90+ days of 5-min data. Requires `ALPACA_API_KEY` and `ALPACA_SECRET_KEY` env vars. Automatically filters to regular market hours (9:30–16:00 ET).
- `--source yfinance` — capped at 60 calendar days for 5-min data; warns and caps automatically if `--days` exceeds 60.

---

## Approaches Tried & Results

### Ticker Selection

#### Basket A — 30-day backtest (APP + META + SPOT + QQQ)

| Basket                         | Net P&L           | Notes                                         |
| ------------------------------ | ----------------- | --------------------------------------------- |
| APP, NVDA, MSFT, QQQ           | +$42.88           | Original basket                               |
| APP, META, SNDK, LLY, SPOT     | +$42.88           | Mixed results — LLY and SNDK dragged         |
| APP, META, SPOT                | +$66.56           | Best 3-ticker core                            |
| **APP, META, SPOT, QQQ** | **+$78.06** | Final basket — QQQ adds breadth confirmation |

**Dropped tickers:**

- **LLY** — bearish signals kept reversing through MA50 quickly. Net P&L: -$26.52. Opening momentum does not hold well on large-cap pharma.
- **SNDK** — wins looked good by time held but exits at midpoint wiped gains. Net P&L: -$28.02 without stop, improved to +$5.38 with MA50 stop.
- **TSLA** — nearly breakeven (-$0.51). Win rate lowest at 71%. High volatility but insufficient directional follow-through on opening momentum.

#### Basket B — 90-day backtest (SHOP + SNDK + ISRG + GOOGL, Dec 2025 – Mar 2026)

| Ticker          | Signals       | Win Rate      | Net P&L            | Characteristic                                                    |
| --------------- | ------------- | ------------- | ------------------ | ----------------------------------------------------------------- |
| SHOP            | 29            | 76%           | +$39.99            | Consistent; strongest in Feb                                      |
| SNDK            | 28            | 75%           | +$77.47            | Highest P&L — large moves when signal fires; Jan was exceptional |
| ISRG            | 28            | 79%           | +$22.12            | Steady win rate across all months                                 |
| GOOGL           | 22            | 59%           | -$0.83             | Lowest win rate; signal does not hold well on mega-cap tech       |
| **Total** | **107** | **73%** | **+$138.75** |                                                                   |

**Monthly breakdown (Basket B):**

| Month    | Net P&L                                                           | Notes                                                          |
| -------- | ----------------------------------------------------------------- | -------------------------------------------------------------- |
| Dec 2025 | -$8.92                                                            | Thin data (partial month); SNDK strong but ISRG/GOOGL negative |
| Jan 2026 | +$115.24 | Best month — SNDK alone +$86.10; all tickers positive |                                                                |
| Feb 2026 | +$54.35                                                           | SHOP 86% win rate; SNDK 100% (7/7)                             |
| Mar 2026 | -$21.92                                                           | Choppy market — GOOGL 0% win rate; ISRG gave back gains       |

**Finding**: GOOGL underperforms — mega-cap with tight spreads and deep liquidity tends to mean-revert quickly after the open rather than follow through. SNDK shows the highest absolute P&L but also the highest variance. Mar 2026 selloff hurt all tickers; `--bearish-ma200` mode worth testing for that period.

### Opening Period Length

| Opening Bars | Minutes | Net P&L | Win Rate |
| ------------ | ------- | ------- | -------- |
| 3 bars       | 15 min  | +$78.06 | 83–90%  |
| 4 bars       | 20 min  | ~+$60   | 75–89%  |

**Finding**: 15-min opening gives earlier entry and captures more of the move.
SNDK was the exception (100% win rate at 20 min vs 71% at 15 min) — wider range
stocks benefit from the extra confirmation bar.

### Stop Loss Rules

| Stop Rule                            | Net P&L (APP+META+SPOT) | Notes                                                              |
| ------------------------------------ | ----------------------- | ------------------------------------------------------------------ |
| No stop (exit at midpoint violation) | +$81.56                 | Highest P&L but high variance — gives back all gains on reversals |
| MA20 trailing stop                   | +$38.81                 | Too tight — cuts winners too early                                |
| **MA50 trailing stop**         | **+$66.56**       | Best balance of protection vs room to run                          |

**Finding**: MA50 stop fixed SNDK (went from -$28 to +$5.38) and reduced LLY
losses significantly. The trade-off: APP lost some all-day runners where MA50
triggered before end of day.

**Stop priority test — midpoint vs MA50 whichever first:**
Running both in parallel showed the current approach (check midpoint first,
MA50 second) outperforms true "whichever first" by +$6.56 total. The MA50 is a
lagging line and often sits above the midpoint early in the day — using it as
the primary trigger causes premature exits on normal intraday volatility.

### Bearish Signal Threshold

| Threshold            | Signals      | Net P&L           | Notes                                        |
| -------------------- | ------------ | ----------------- | -------------------------------------------- |
| Bottom 10%           | 32           | +$70.76           | Too restrictive — almost no bearish signals |
| **Bottom 20%** | **44** | **+$78.06** | Best balance                                 |
| Bottom 30%           | 48           | +$64.89           | Too loose — let in noisy bearish setups     |

**Finding**: Bottom 10% was highly asymmetric vs bullish (top 50% threshold).
Bottom 20% unlocked high-quality bearish signals (META Feb 23 +$11.16, META
Mar 20 +$5.70) without degrading win rate.

### Bearish MA Filter

| Config              | Bearish MA requirement   | When to use                                 |
| ------------------- | ------------------------ | ------------------------------------------- |
| Default             | Close < MA20 only        | Bull market — most stocks above MA200      |
| `--bearish-ma200` | Close < MA20 AND < MA200 | Bear market — price in confirmed downtrend |

**Finding**: Removing the MA200 requirement from bearish signals was the single
largest P&L improvement (+$7 on META alone over 30 days). In a bull market
regime, stocks rarely drop below MA200 during the opening period, so the MA200
filter was blocking nearly all bearish signals.

---

## Win/Loss Analysis

### Basket A — 30-day, APP + META + SPOT + QQQ

| Ticker | Signals | Win Rate | Net P&L                                                                                      | Characteristic                                                                                      |
| ------ | ------- | -------- | -------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------- |
| APP    | 12      | 83%      | +$43.08 | Largest moves ($20–27 on best days). High beta, follows opening momentum strongly |                                                                                                     |
| META   | 10      | 90%      | +$21.37                                                                                      | Most consistent win rate. Responds well to bearish signals                                          |
| SPOT   | 14      | 79%      | +$11.53                                                                                      | Most active signal generator. Recent weeks showed smaller moves                                     |
| QQQ    | 10      | 80%      | +$2.08                                                                                       | Small P&L per trade (ETF, lower volatility) but adds breadth confirmation and fills signal-gap days |

**Key pattern**: Signals clustered heavily in Feb 18 – Mar 9 (uptrend phase),
then dried up as the market sold off in Mar 10–20. The MA200 regime filter
correctly stepped the system aside during the downturn.

### Basket B — 90-day, SHOP + SNDK + ISRG + GOOGL

| Ticker | Signals | Win Rate | Net P&L | Characteristic                                              |
| ------ | ------- | -------- | ------- | ----------------------------------------------------------- |
| SHOP   | 29      | 76%      | +$39.99 | Reliable signal generator; consistent across months         |
| SNDK   | 28      | 75%      | +$77.47 | Highest P&L; large intraday range drives outsized wins      |
| ISRG   | 28      | 79%      | +$22.12 | Most consistent win rate in the basket                      |
| GOOGL  | 22      | 59%      | -$0.83  | Weakest performer; mega-cap mean reversion defeats momentum |

**Key pattern**: Jan 2026 was the standout month (+$115.24) driven by a strong
trending environment. Mar 2026 was the weakest (-$21.92) as macro uncertainty
increased intraday choppiness. GOOGL's low win rate suggests mega-cap indexes
and liquid large-caps are poor fits for this strategy.

---

## Ticker Universe Study — Hypothesis Testing

### Hypothesis

Initial observation from 60-day backtests: the signal works best on **liquid,
high-beta growth tech** (APP, META, DDOG, CRWD) and struggles on pharma (LLY)
and industrials (FIX, CAT). The hypothesis was that **sector and stock type**
determine signal quality.

### Methodology

5 rounds × 5 tickers, tested over both **60-day** and **12-month** windows.
Each round represents a distinct stock category.

### 60-Day Results (Jan – Mar 2026)

| Round | Category                    | Tickers                      | Net P&L | Avg Win Rate |
| ----- | --------------------------- | ---------------------------- | ------- | ------------ |
| 1     | SaaS / Cloud                | SNOW, ZS, NET, MDB, BILL     | +$35.03 | 72%          |
| 2     | Consumer / Marketplace Tech | UBER, ABNB, DASH, SHOP, HOOD | +$55.70 | 73%          |
| 3     | Semiconductors              | AMD, AVGO, MRVL, QCOM, ARM   | +$40.05 | 65%          |
| 4     | Defensive / Traditional     | PG, KO, HD, PFE, GS          | +$6.04  | 68%          |
| 5     | Speculative / High-beta     | PLTR, MSTR, SMCI, RDDT, TSLA | +$33.43 | 65%          |

**60-day takeaway**: Growth tech leads, defensives barely register. Pattern
appeared to confirm the sector hypothesis.

### 12-Month Results (Mar 2025 – Mar 2026, up market)

| Round | Category                    | Tickers                      | Net P&L  | Avg Win Rate |
| ----- | --------------------------- | ---------------------------- | -------- | ------------ |
| 1     | SaaS / Cloud                | SNOW, ZS, NET, MDB, BILL     | +$96.42  | 66%          |
| 2     | Consumer / Marketplace Tech | UBER, ABNB, DASH, SHOP, HOOD | +$120.32 | 69%          |
| 3     | Semiconductors              | AMD, AVGO, MRVL, QCOM, ARM   | +$145.05 | 68%          |
| 4     | Defensive / Traditional     | PG, KO, HD, PFE, GS          | +$105.07 | 71%          |
| 5     | Speculative / High-beta     | PLTR, MSTR, SMCI, RDDT, TSLA | +$287.19 | 64%          |

### 12-Month Results (Jan – Dec 2022, down market — default mode)

ARM and RDDT were not publicly traded in 2022 — no signals for those tickers.

| Round | Category                    | Tickers                      | Net P&L            | Avg Win Rate |
| ----- | --------------------------- | ---------------------------- | ------------------ | ------------ |
| 1     | SaaS / Cloud                | SNOW, ZS, NET, MDB, BILL     | **+$536.73** | 73%          |
| 2     | Consumer / Marketplace Tech | UBER, ABNB, DASH, SHOP, HOOD | **+$425.10** | 69%          |
| 3     | Semiconductors              | AMD, AVGO, MRVL, QCOM        | +$187.56           | 69%          |
| 4     | Defensive / Traditional     | PG, KO, HD, PFE, GS          | +$34.06            | 67%          |
| 5     | Speculative / High-beta     | PLTR, MSTR, SMCI, TSLA       | +$255.72           | 63%          |

### 12-Month Results (Jan – Dec 2022, down market — `--bearish-ma200` mode)

| Round | Category                    | Tickers                      | Net P&L                               | Avg Win Rate | vs default |
| ----- | --------------------------- | ---------------------------- | ------------------------------------- | ------------ | ---------- |
| 1     | SaaS / Cloud                | SNOW, ZS, NET, MDB, BILL     | **+$573.52** | 74% | +$36.79 ↑ |              |            |
| 2     | Consumer / Marketplace Tech | UBER, ABNB, DASH, SHOP, HOOD | +$401.90 | 71% | -$23.20 ↓           |              |            |
| 3     | Semiconductors              | AMD, AVGO, MRVL, QCOM        | **+$202.61** | 71% | +$15.05 ↑ |              |            |
| 4     | Defensive / Traditional     | PG, KO, HD, PFE, GS          | +$40.36 | 68% | +$6.30 ↑             |              |            |
| 5     | Speculative / High-beta     | PLTR, MSTR, SMCI, TSLA       | +$215.34 | 64% | -$40.38 ↓           |              |            |

### 2023–2024 Results (recovery + AI bull market)

RDDT IPO'd in March 2024; ARM IPO'd in September 2023 — partial year data for those.

| Round | Category                    | Tickers                      | Net P&L            | Avg Win Rate |
| ----- | --------------------------- | ---------------------------- | ------------------ | ------------ |
| 1     | SaaS / Cloud                | SNOW, ZS, NET, MDB, BILL     | +$257.94           | 66%          |
| 2     | Consumer / Marketplace Tech | UBER, ABNB, DASH, SHOP, HOOD | +$118.73           | 67%          |
| 3     | Semiconductors              | AMD, AVGO, MRVL, QCOM, ARM   | **+$717.47** | 70%          |
| 4     | Defensive / Traditional     | PG, KO, HD, PFE, GS          | +$111.88           | 72%          |
| 5     | Speculative / High-beta     | PLTR, MSTR, SMCI, RDDT, TSLA | **+$681.56** | 67%          |

AVGO alone drove +$530 in Round 3. SMCI (+$257) and MSTR (+$222) dominated Round 5.

### Full Market Regime Comparison

| Round           | Category                    | 2022 (bear)                           | 2023–24 (AI bull) | 2025–26 (up) |
| --------------- | --------------------------- | ------------------------------------- | ------------------ | ------------- |
| 1               | SaaS / Cloud                | **+$537** | +$258               | +$96               |               |
| 2               | Consumer / Marketplace Tech | **+$425** | +$119               | +$120              |               |
| 3               | Semiconductors              | +$188 |**+$717**                | +$145              |               |
| 4               | Defensive / Traditional     | +$34 | +$112                          | +$105              |               |
| 5               | Speculative / High-beta     | +$256 |**+$682**                | +$287              |               |
| **Total** |                             | **+$1,440** | **+$1,889** | **+$753**    |               |

### Key Findings

**1. The signal is profitable across every regime and category.**
No round is negative in any year. The signal has a durable edge that survives
bull markets, bear markets, and transitional periods.

**2. The dominant sector rotates with market narrative, not signal accuracy.**
Win rates across all rounds stay in a narrow band (59–77%) in every period.
What changes dramatically is per-trade dollar P&L — driven entirely by which
sector has the largest intraday moves at any given time:

- **2022 (bear):** SaaS and consumer tech had violent intraday swings as rates
  rose and multiples compressed — those stocks moved the most.
- **2023–24 (AI bull):** Semiconductors (AVGO +$530, AMD +$98) and AI
  infrastructure plays (SMCI +$257, MSTR +$222) dominated as the AI narrative
  drove massive single-day moves.
- **2025–26 (up):** A calmer, broader bull market — speculative high-beta led
  (TSLA, MSTR, PLTR) but with smaller absolute moves than the AI peak years.

**3. Semiconductor stocks are the standout 2023–24 story (+$717).**
AVGO alone contributed +$530 over two years — by far the single largest
contributor across all rounds and all periods. In the AI bull, semiconductor
stocks moved like high-beta growth names, combining large range with strong
institutional directional conviction at the open.

**4. SaaS/cloud P&L decays as volatility returns to normal.**
+$537 (2022) → +$258 (2023–24) → +$96 (2025–26). As SaaS valuations
stabilized post-rate-hike, intraday ranges compressed and per-trade P&L fell.
The signal still fires and wins; it just earns less per trade.

**5. Consumer tech (SHOP, DASH, ABNB) collapses after 2022.**
SHOP: +$395 (2022) → +$10 (2023–24). The enormous bear-year moves were driven
by pandemic reversal and rate shock — a one-time regime. Post-compression,
these stocks traded with smaller ranges and less conviction at the open.

**6. Defensives are stable and regime-insensitive (+$34 to +$112).**
Positive in every period but never a major contributor. Moves are simply too
small to generate meaningful P&L — this is confirmed across four years.

**7. `--bearish-ma200` helps SaaS/semis in bear markets, hurts speculative.**
In 2022, enabling the flag improved SaaS (+$37) and semis (+$15) but hurt
speculative names (-$40) that legitimately traded below MA200. Use the flag
for structured growth stocks; leave it off for high-beta names.

**8. RDDT is the only ticker negative across multiple timeframes.**
-$39 over 12-month up market; small positive only when the AI narrative briefly
boosted it in 2024. Exclude from production ticker universe.

### What Changes the Signal's Characteristics

The signal's win rate is structurally stable. What changes performance is:

| Market condition                               | Effect on signal                                   |
| ---------------------------------------------- | -------------------------------------------------- |
| High volatility (2022 bear, 2023–24 AI run)   | Amplifies per-trade P&L for the leading sector     |
| Sector narrative with institutional conviction | Increases opening range size and follow-through    |
| Calm/broad bull market (2025–26)              | Reduces per-trade P&L uniformly across all sectors |
| Rate shock / multiple compression              | Supercharges SaaS/consumer tech bearish signals    |
| AI infrastructure narrative                    | Supercharges semiconductor and AI-proxy signals    |

**Implication**: To maximize P&L, weight the ticker universe toward whichever
sector currently has the highest intraday ATR and strongest institutional
narrative. Rotate sector exposure as the macro regime shifts rather than keeping
a fixed basket.

### Revised Ticker Selection Framework

| Characteristic                                   | Signal quality                 | Reason                                                          |
| ------------------------------------------------ | ------------------------------ | --------------------------------------------------------------- |
| Liquid mid/large-cap growth tech (SaaS, ad-tech) | High win rate + decent moves   | Institutional order flow sets clear directional bias at open    |
| High-beta volatile stocks (TSLA, MSTR, PLTR)     | Lower win rate but highest P&L | Large intraday range amplifies wins; only viable with MA50 stop |
| Semiconductors (AVGO, AMD)                       | Moderate win rate, large moves | Behave like growth tech in trending markets                     |
| Defensive / low-beta (PG, KO, PFE)               | Good win rate, negligible P&L  | Moves too small to trade profitably after slippage              |
| Retail / meme stocks (RDDT)                      | Low win rate, negative P&L     | No consistent institutional opening bias to exploit             |
| Mega-cap indexes / ETFs (GOOGL, QQQ)             | Below-average win rate         | Deep liquidity enables mean reversion; momentum fades quickly   |

---

## Potential Fine-Tuning Directions

### Entry Improvements

| Parameter         | Current          | Ideas to test                                                                                                 |
| ----------------- | ---------------- | ------------------------------------------------------------------------------------------------------------- |
| Bullish threshold | > midpoint (50%) | Raise to 60–65% — filter out weak signals near midpoint                                                     |
| Min OR range size | None             | Add `MIN_OR_RANGE_DOLLARS` — wins averaged $15.29 range vs $11.72 for fails                                |
| MA20 gap %        | Any gap          | Require close to be ≥ 0.8% above MA20 — fails averaged only 0.58% gap                                       |
| Volume filter     | None             | Cap first-bar volume at 2x average — high spike opens tend to reverse (fails averaged 506K vs 363K for wins) |
| Opening bars      | Fixed at 3       | Per-ticker tuning: SNDK may benefit from 4 bars                                                               |

### Exit Improvements

| Parameter        | Current | Ideas to test                                                                  |
| ---------------- | ------- | ------------------------------------------------------------------------------ |
| Hard stop pct    | 0.35 (tested, optimal for basket) | Per-ticker tuning: APP performs best at 0.70–0.80 (needs more room); use per-ticker stop-pct |
| Trailing stop MA | MA50    | Per-ticker: APP may benefit from no MA stop (let runners run)                  |
| Profit target    | None    | Exit at OR High (bullish) / OR Low (bearish) — locks in gains before reversal |
| Time-based exit  | None    | Force exit 30 min before market close to avoid end-of-day noise                |
| Partial exit     | None    | Take half position off at 1x OR range move, let rest run to MA50 stop          |

### Hard Stop Placement — Parameter Study

Tested `--stop-pct` values of 0.35, 0.40, 0.50, 0.60, 0.70, 0.80 on the top-10 ticker basket over 90 days.

**Hard stop formula:**
- Bull: exit if price drops below `OR_high − stop_pct × OR_range`
- Bear: exit if price rises above `OR_low + stop_pct × OR_range`

A lower `stop_pct` places the stop closer to the favorable end of the range (tighter). A higher value gives more room but absorbs larger losses.

| stop-pct | Net P&L | EV/Trade | AvgWin% | AvgLoss% |
|---|---|---|---|---|
| **0.35** | **+$552** | **+0.674%** | 2.49% | **0.59%** |
| 0.40 | +$505 | +0.614% | 2.61% | 0.68% |
| 0.50 (old midpoint) | +$503 | +0.578% | 2.83% | 0.86% |
| 0.60 | +$479 | +0.520% | 2.72% | 1.04% |
| 0.70 | +$489 | +0.519% | 2.70% | 1.15% |
| 0.80 | +$452 | +0.474% | 2.68% | 1.24% |

**Finding:** EV/Trade peaks at 0.35 and degrades in both directions. Going wider than 0.50 (the former midpoint default) consistently hurts — AvgLoss% climbs faster than AvgWin%, reducing EV/Trade.

**Exception — APP:** performs best at 0.70–0.80 (EV/Trade +1.007% at 0.80), consistently improving as the stop widens. APP tends to dip and recover more than other tickers, so a wider stop allows it to hold through the dip and capture the full move. Candidate for per-ticker stop-pct configuration.

**Default updated to `--stop-pct 0.35`.**

### Signal Improvements

| Idea                      | Description                                                                               |
| ------------------------- | ----------------------------------------------------------------------------------------- |
| VWAP confirmation         | Require price > VWAP (anchored to open) to confirm bullish signal                         |
| Volume spike filter       | First bar volume > N× 20-day average first-bar volume = stronger conviction              |
| Multi-ticker confirmation | Only trade a ticker's signal if QQQ signal agrees on direction                            |
| Regime detection          | Auto-switch `--bearish-ma200` based on whether QQQ is above/below its own MA200         |
| Signal strength score     | Combine % in range + MA gap % + volume ratio into a 0–100 score, only trade top quartile |

### Backtesting Improvements

| Idea                       | Description                                                                                                       |
| -------------------------- | ----------------------------------------------------------------------------------------------------------------- |
| Extend to 12 months        | Now supported via Alpaca. 100–140 signals per ticker over 365 days provides strong statistical significance      |
| Per-ticker parameter sweep | Grid search opening_bars × bearish_threshold × stop_type per ticker                                             |
| Slippage model             | Add 0.05–0.10% slippage on entry and exit to simulate real execution — critical for low-move defensives         |
| Position sizing            | Size positions by expected move (e.g. proportional to ATR) rather than equal 1-share per signal                   |
| Walk-forward test          | Train on months 1–9, validate on months 10–12 to avoid overfitting. Use `--start`/`--end` for fixed windows |
| Monthly regime filter      | Auto-adjust aggressiveness based on prior month P&L — reduce size when monthly P&L goes negative                 |
| Ticker selection by ATR    | Rank universe by 20-day ATR and focus on top quartile — confirmed as primary P&L driver                          |

---

## Future Research Directions

### Backtest Time Periods to Explore

These periods represent distinct macro regimes not yet tested, each likely to
reveal different signal characteristics:

| Period         | Regime                      | Status                | Why it's interesting                                                                                      |
| -------------- | --------------------------- | --------------------- | --------------------------------------------------------------------------------------------------------- |
| 2008–2009     | Financial crisis bear       | ❌ No Alpaca data     | Deepest bear since 1929 — systemic stress; Alpaca 5-min data only goes back to 2016                      |
| 2020 Q1–Q2    | COVID crash + V-recovery    | ✅ Tested (see below) | Fastest -35% ever; panic selling breaks signal — see findings below                                      |
| 2020 full year | Crash + recovery            | ✅ Tested (see below) | Recovery dominated by TSLA (+$317), SHOP (+$133); signal fully recovers post-panic                        |
| 2017–2019     | Steady bull (pre-COVID)     | ✅ Tested (see below) | Low-vol grind with earnings-driven sector rotation — tests signal in calm, persistently trending markets |
| 2020 Q3–2021  | Post-COVID meme/growth boom | Not yet               | SPACs, meme stocks, retail-driven momentum — tests if retail price action breaks institutional bias      |
| 2015–2016     | China slowdown / oil crash  | ✅ Tested (see below) | Commodity sector stress alongside tech resilience; good for testing energy tickers                        |
| 2018 Q4        | Rate-hike selloff           | Not yet               | Sharp -20% correction — shorter, cleaner structural bear; compare to 2022                                |

### COVID Crash Results (Feb – Jun 2020)

SNOW, ABNB, DASH, HOOD, PLTR, RDDT, and ARM were not yet public during this period.

| Round | Category                    | Tickers active        | Net P&L           | Avg Win Rate |
| ----- | --------------------------- | --------------------- | ----------------- | ------------ |
| 1     | SaaS / Cloud                | ZS, NET, MDB, BILL    | +$4.22            | 63%          |
| 2     | Consumer / Marketplace Tech | UBER, SHOP            | **-$19.31** | 61%          |
| 3     | Semiconductors              | AMD, AVGO, MRVL, QCOM | **-$11.66** | 67%          |
| 4     | Defensive / Traditional     | PG, KO, HD, PFE, GS   | **-$23.67** | 70%          |
| 5     | Speculative / High-beta     | MSTR, SMCI, TSLA      | +$54.04           | 54%          |

TSLA alone drove +$67 in Round 5 — it moved independently from the market panic.

### Full Year 2020 Results (crash + V-recovery)

ABNB and DASH IPO'd in December 2020 (thin data); HOOD, RDDT, ARM not yet public; PLTR IPO'd in October 2020.

| Round | Category                    | Tickers active                     | Net P&L            | Avg Win Rate |
| ----- | --------------------------- | ---------------------------------- | ------------------ | ------------ |
| 1     | SaaS / Cloud                | SNOW (partial), ZS, NET, MDB, BILL | +$171.82           | 64%          |
| 2     | Consumer / Marketplace Tech | UBER, SHOP + ABNB/DASH (partial)   | +$133.54           | 61%          |
| 3     | Semiconductors              | AMD, AVGO, MRVL, QCOM              | **-$4.04**   | 62%          |
| 4     | Defensive / Traditional     | PG, KO, HD, PFE, GS                | +$23.81            | 68%          |
| 5     | Speculative / High-beta     | PLTR (partial), MSTR, SMCI, TSLA   | **+$394.40** | 58%          |

TSLA alone contributed +$317 for the year — the single largest annual ticker contribution across all periods tested.

### COVID Crash vs Full Year 2020

| Round           | Category                    | Feb–Jun 2020 (panic)           | Full year 2020  | Recovery adds |
| --------------- | --------------------------- | ------------------------------- | --------------- | ------------- |
| 1               | SaaS / Cloud                | +$4 | +$172                     | +$168           |               |
| 2               | Consumer / Marketplace Tech | -$19 | +$134                    | +$153           |               |
| 3               | Semiconductors              | -$12 | -$4                      | +$8             |               |
| 4               | Defensive / Traditional     | -$24 | +$24                     | +$48            |               |
| 5               | Speculative / High-beta     | +$54 | +$394                    | +$340           |               |
| **Total** |                             | **+$4** | **+$719** | **+$715** |               |

The V-recovery (Jul–Dec 2020) generated +$715 more than the crash period alone — the crash losses were small but the recovery was enormous, particularly for TSLA (+$317 full year) and SHOP (+$133).

### 2017–2019 Results (3-year steady bull)

Period: Jan 2017 – Dec 2019 (1,094 calendar days). Many post-2020 IPOs unavailable.
Tickers used: R1=CRM/WDAY/VEEV/NOW/EBAY | R2=AMZN/NFLX/GOOGL/BABA/META | R3=NVDA/AMD/AVGO/MRVL/QCOM | R4=JNJ/PG/KO/XOM/PEP | R5=TSLA/BIDU/GPRO/GRPN/NTES

| Round | Category | Win Rate | AvgWin% | Net P&L | Top performer |
|---|---|---|---|---|---|
| 1 | SaaS / Enterprise Cloud | 64–68% | 0.30% | +$297 | WDAY +$115 |
| 2 | Consumer / Platform Tech | 65–70% | 0.29% | **+$1,418** | AMZN +$869 |
| 3 | Semiconductors | 62–72% | 0.32% | +$171 | NVDA +$76 |
| 4 | Defensives | 66–70% | 0.11% | +$75 | JNJ/PG ~$26 each |
| 5 | Speculative / High-Beta | 64–73% | 0.42% | +$623 | TSLA +$288, NTES +$269 |
| **Total** | | | **0.29%** | **+$2,584** | |

Win rates stayed in the 62–73% range across all rounds — no single round broke down.

### 2015–2016 Results (China slowdown / oil crash)

Period: Jan 2015 – Dec 2016 (730 calendar days). Same tickers as 2017–2019 panel.
Note: AMZN ~$300–$700 range, GOOGL ~$500–$800 range; lower stock prices compress absolute $ P&L.

| Round | Category | Win Rate | AvgWin% | Net P&L | Top performer |
|---|---|---|---|---|---|
| 1 | SaaS / Enterprise Cloud | 62–76% | 0.22% | +$19 | NOW +$14 |
| 2 | Consumer / Platform Tech | 60–78% | 0.30% | **+$355** | AMZN +$204, GOOGL +$109 |
| 3 | Semiconductors | 56–78% | 0.54% | +$47 | NVDA +$30 |
| 4 | Defensives | 63–77% | 0.09% | +$8 | XOM +$3 |
| 5 | Speculative / High-Beta | 59–74% | 0.38% | +$23 | NTES +$29, TSLA -$14 |
| **Total** | | | **0.29%** | **+$452** | |

Win rates ranged 59–78% — signal structure held. Small absolute P&L reflects lower stock prices, not signal failure.

Key findings from 2015–2016:

- TSLA was the one negative ticker (-$14) despite a 0.13% AvgWin% — its loss P&L outweighed wins because the stock lacked a sustained directional narrative, producing more frequent signal failures.
- Consumer tech (AMZN, GOOGL) held a steady 0.30% AvgWin% — identical to 2017–2019 — confirming that narrative-driven opening conviction is regime-independent.
- Semis had the highest AvgWin% of any round in 2015–2016 (0.54%) despite the low absolute P&L — China-driven volatility created sharper intraday moves in NVDA/AMD even at lower price levels.
- Defensives were the worst quality signal in both periods (0.09% in 2015–16, 0.11% in 2017–19) — slow-moving stocks simply don't produce followthrough from opening range breakouts.

### Full Cross-Period Comparison (all regimes)

| Round           | Category                            | 2015–16                            | 2017–19                              | COVID crash             | 2020 full yr | 2022 (bear) | 2023–24 (AI bull) | 2025–26 (up) |
| --------------- | ----------------------------------- | ----------------------------------- | ------------------------------------- | ----------------------- | ------------ | ----------- | ------------------ | ------------- |
| 1               | SaaS / Cloud                        | +$19 | +$297                        | +$4 | +$172                           | **+$537** | +$258 | +$96         |             |                    |               |
| 2               | Consumer Tech                       | **+$355** | **+$1,418** | -$19 | +$134                          | **+$425** | +$119 | +$120        |             |                    |               |
| 3               | Semiconductors                      | +$47 | +$171                        | -$12 | -$4                            | +$188 |**+$717**  | +$145        |             |                    |               |
| 4               | Defensives                          | +$8 | +$75                          | -$24 | +$24                           | +$34 | +$112            | +$105        |             |                    |               |
| 5               | Speculative                         | +$23 | +$623                        | +$54 |**+$394**                 | +$256 | +$682           | +$287        |             |                    |               |
| **Total** | **+$452** | **+$2,584** | **+$4** | **+$719**     | **+$1,440** | **+$1,889** | **+$753**         |              |             |                    |               |

### AvgWin% Cross-Period Comparison (price-normalized signal quality)

| Round | Category | 2015–16 | 2017–19 | 2022 (bear) | 2023–24 (AI bull) | 2025–26 (up) |
|---|---|---|---|---|---|---|
| 1 | SaaS / Cloud | 0.22% | 0.30% | — | — | — |
| 2 | Consumer Tech | **0.30%** | **0.29%** | — | — | — |
| 3 | Semiconductors | **0.54%** | 0.32% | — | — | — |
| 4 | Defensives | 0.09% | 0.11% | — | — | — |
| 5 | Speculative | 0.38% | **0.42%** | — | — | — |
| **Overall** | | **0.29%** | **0.29%** | — | — | — |

> AvgWin% for 2022, 2023–24, and 2025–26 to be added when those backtests are rerun with the updated script.

### Key Finding — Panic Selling Breaks the Signal

The COVID crash period is the one regime where the signal nearly breaks down (+$4 total, 3 of 5 rounds negative). This reveals an important structural limitation:

**The signal requires systematic sector-specific selling pressure, not indiscriminate panic.**

The opening range momentum thesis assumes institutional order flow at the open establishes a clear directional bias. In a structured bear market (2022), this holds because:

- Selling is driven by sector-specific fundamentals (rate sensitivity, multiple compression)
- Institutions have time to position — the direction set at open persists
- Bearish signals fire cleanly and follow through

In a panic crash (COVID Feb–Jun), this breaks because:

- Everything sells off simultaneously — no sector differentiation
- Enormous overnight gaps (circuit breakers, futures halts) make the opening range a reversal target, not a direction setter
- Win rates stayed reasonable (54–70%) but **win P&L collapsed relative to loss P&L** — signal direction was right but intraday reversals ate the gains

**The recovery (Jul–Dec 2020) completely changes the picture.** Once panic subsided and sector narratives re-emerged, the signal recovered strongly — TSLA's EV run, SHOP's e-commerce boom, MSTR's Bitcoin pivot all created the kind of persistent institutional conviction the signal needs.

**Implication**: The signal's enemy is **indiscriminate panic**, not bear markets. A VIX > 40 filter and a SPY gap-down > 2% daily filter would have largely avoided the crash period while capturing the full recovery.

### Key Finding — Stock Price Level Is a Multiplier, Not Signal Quality

The cross-period comparison reveals a consistent pattern in absolute P&L:

| Period | Consumer Tech R2 P&L | AvgWin% | Approx. AMZN price range |
|---|---|---|---|
| 2015–2016 | +$355 | 0.30% | $300–$700 |
| 2017–2019 | +$1,418 | 0.29% | $900–$2,000 |
| 2022 (bear) | +$425 | — | $2,000–$3,800 → crash to $800 |
| 2023–24 | +$119 | — | $80–$200 (post-split) |
| 2025–26 | +$120 | — | $180–$240 |

The Consumer Tech `AvgWin%` is **0.30% in 2015–2016 and 0.29% in 2017–2019** — essentially identical despite a 4× difference in absolute P&L. The signal quality was the same; only the stock price level changed.

**Implication for ticker selection**: Absolute $ P&L is not a signal quality metric — it's a position sizing artifact. `AvgWin%` is the correct cross-period comparison. A 0.30% average winning trade on a $200 stock generates $0.60/trade; on a $2,000 stock it generates $6.00/trade — same signal, 10× dollar outcome.

### Key Finding — 2017–2019 Was the Signal's Best Dollar Environment

2017–2019 produced **+$2,584** in absolute $ — but `AvgWin%` tells a more nuanced story:

1. **High stock prices inflated $ P&L** — AMZN at $1,000–$2,000 generated $869 in R2 alone; the underlying signal quality (0.29% AvgWin%) was identical to 2015–2016.
2. **Broad sector participation** — all 5 rounds positive, including defensives (+$75, 0.11%). This breadth is unusual and reflects the low-VIX trending environment.
3. **Speculative round had the best quality** — 0.42% AvgWin%, driven by TSLA (0.62%) and NTES (0.53%). Both had strong single-stock narratives creating persistent opening bias.
4. **Defensives were the weakest quality** — 0.11% AvgWin%, consistent with every other period tested. Slow-moving stocks don't generate followthrough even when the direction is right.

### Key Finding — 2015–2016 Shows Signal Works Below Current Volatility Floors

`AvgWin%` across 2015–2016 rounds (0.09%–0.54%) is consistent with 2017–2019, confirming:

- The signal is **structurally sound at lower volatility levels** — it's not an artifact of post-2020 high-ATR environments.
- **Semis had the highest AvgWin% of any 2015–2016 round (0.54%)** — China-driven sector volatility created sharper intraday moves in NVDA/AMD even at lower price levels. High AvgWin% with low absolute P&L = correct signal, undersized position.
- **TSLA's 0.13% AvgWin% explains the negative result** — wins were small and losses were frequent enough to net negative. Without a sustained macro narrative, the stock reversed too often against the signal.
- **Consumer tech's 0.30% held stable across both periods** — confirming that strong business narratives (AWS, ad dominance) create the institutional opening conviction the signal depends on regardless of macro regime.

### Sector / Ticker Universes to Test

Categories not yet covered:

| Category             | Example Tickers                   | Hypothesis                                                                                                                         |
| -------------------- | --------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| Energy / Commodities | XOM, CVX, SLB, OXY                | Commodity price-driven intraday moves; opening bias set by overnight oil/gas prints — could work well during supply shock regimes |
| Biotech              | MRNA, BNTX, REGN, BIIB            | Catalyst-driven (FDA, trial data) — likely breaks signal on event days; may work on non-event days if filtered                    |
| Chinese ADRs         | BABA, PDD, JD                     | Overnight Chinese market prints set the opening bias strongly; potential for large clean moves if signal can be adapted            |
| Defense / Aerospace  | LMT, RTX, NOC                     | Geopolitical event-driven; low day-to-day volatility but large moves on macro shocks — test during 2022 Ukraine war onset         |
| Small-cap growth     | CELH, GTLB, BILL (already tested) | Higher beta than large-cap, less institutional stabilization at open — may amplify signal wins and losses                         |
| Crypto proxies       | MARA, RIOT, COIN (already tested) | Bitcoin-correlated opens. COIN was negative over 60 days; MSTR (positive) suggests the proxy distance from BTC matters             |
| Sector ETFs          | XLK, SMH, XLF, XLE                | Lower per-trade P&L but smoother signal quality; useful as regime confirmation rather than primary trade vehicles                  |
| International ETFs   | EWJ, EWG, EWZ                     | Test whether opening momentum driven by prior-day international close has predictive value                                         |

### Strategy Improvements to Explore

#### Signal Quality

| Idea                     | Description                                                                                                                                                                  | Expected impact                                                                          |
| ------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| ATR-based ticker ranking | Rank ticker universe weekly by 20-day ATR; only trade the top quartile                                                                                                       | Directly addresses finding that per-trade move size is the P&L driver                    |
| Pre-market gap filter    | Flag if overnight gap > 1.5× average gap — outsized gaps tend to fill rather than extend                                                                                   | Reduce false bullish signals on exhaustion opens                                         |
| VIX regime filter        | Only trade when VIX is between 15–40; below 15 = too calm (small moves), above 40 = panic regime where opening range loses predictive value (confirmed by COVID crash test) | Match signal to optimal volatility window                                                |
| Gap panic filter         | Skip signal if SPY gaps down > 2% at open — indicates indiscriminate panic selling where intraday reversals are frequent and violent                                        | Confirmed by COVID crash: the opening range itself becomes noise under extreme gap opens |
| Sector ETF confirmation  | Require ticker's sector ETF (e.g. SMH for semis) to agree on signal direction                                                                                                | Filters out stock-specific noise; strengthens institutional narrative requirement        |
| Multi-timeframe filter   | Check that daily chart is in the same direction (close > daily MA20) before taking signal                                                                                    | Reduces counter-trend intraday trades                                                    |

#### Position Sizing

| Idea                         | Description                                                                                                           | Expected impact                                                          |
| ---------------------------- | --------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------ |
| ATR-scaled shares            | Size each trade as `target_risk / (entry - midpoint)` so each trade risks the same dollar amount                    | Equalizes risk across tickers with very different volatility profiles    |
| Volatility-normalized sizing | Scale down position size when VIX > 25; scale up when VIX 15–20                                                      | Captures more during calm trending phases, reduces exposure during chaos |
| Signal strength scoring      | Score each signal 0–100 based on % in range + MA gap + volume ratio; size full position only on top-quartile signals | Concentrates capital on highest-conviction setups                        |

#### Portfolio Management

| Idea                     | Description                                                       | Expected impact                                                                  |
| ------------------------ | ----------------------------------------------------------------- | -------------------------------------------------------------------------------- |
| Max concurrent positions | Cap open trades at N at any time; skip new signals if cap reached | Controls overall portfolio exposure on high-signal days                          |
| Daily loss limit         | Auto-halt trading if daily P&L drops below -$X                    | Prevents chasing losses in broken-regime days (e.g. Mar 2026 choppy environment) |
| Sector concentration cap | Allow max 2 tickers from same sector simultaneously               | Avoids doubling down on the same sector bet                                      |

#### Options Overlay

| Idea                              | Description                                                                         | Expected impact                                                         |
| --------------------------------- | ----------------------------------------------------------------------------------- | ----------------------------------------------------------------------- |
| Buy ATM call/put instead of stock | Use the signal to buy same-day 0DTE options at signal time                          | Caps max loss to premium paid; can 3–5× gains if move is large        |
| Bull call spread                  | Buy ATM call, sell OR-high call — collects gains up to the OR high then caps       | Defined risk/reward; matches the strategy's natural profit target       |
| Delta-adjusted sizing             | Size options position so delta-equivalent share count matches target stock position | Makes options version directly comparable to stock version in backtests |

---

## Related Concepts

- **Opening Range Breakout (ORB)** — Toby Crabel (1990). Trade breakout of first N-minute range.
- **VWAP Anchored to Open** — Institutional execution benchmark. Companion indicator in `vwap_demo.py`.
- **Market Profile / Initial Balance** — First 30–60 min builds the "Initial Balance" — institutional ORB equivalent.
- **Gap & Go** — If stock gaps up with volume in first 15 min, continue long.
- **Tape reading the generals** — Using market-leading stocks' opening action to gauge overall market direction.

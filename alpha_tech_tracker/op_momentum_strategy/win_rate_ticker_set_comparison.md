# Win-Rate Strategy — Ticker Set Comparison

Tracks how different ticker universes perform under the same win-rate strategy configuration.
All runs use: M1 09:30/3 · selector=win-rate · regime-engine · no-stop · top-8 · $10k pool
unless noted otherwise.

---

## Configuration (baseline)

```bash
python -m alpha_tech_tracker.op_momentum_strategy.op_momentum_trade_engine run \
  --selector win-rate --enable-regime-engine \
  --window M1 09:30 3 --morning-split 100 \
  --bearish-reentry --bullish-reentry --reversal \
  --doubledown --doubledown-start 10 \
  --trailing-ma none --stop-pct 0 \
  --top 8 --capital 10000 \
  --mock-trade-execution --feed sip \
  --replay-date YYYY-MM-DD
```

---

## Set A — Original Momentum Pool (19 tickers)

**Tickers:** `SNDK APP META SNOW SNPS SPOT MU LLY MRVL CRWD QCOM PLTR CHTR TSLA AVGO ARM AMD DDOG RDDT`

**Selection criteria:** High-beta momentum names with strong OR signal history; mix of semis,
cloud, AI infra, and consumer tech. Hand-curated based on win-rate screener signal frequency.

**Log dir:** `logs/replay_2026_stock_m1_winrate_nostop/`

### 2026 YTD Results (Jan 2 – Jun 4, 98 trading days)

| Month | P&L | Return |
|---|---|---|
| Jan | +$27 | +0.3% |
| Feb | +$628 | +6.3% |
| Mar | +$344 | +3.4% |
| Apr | +$675 | +6.7% |
| May | +$1,658 | +16.6% |
| Jun YTD | +$5 | +0.0% |
| **Total** | **+$3,337** | **+33.4%** |

| Metric | Value |
|---|---|
| Trading days with signals | 98 / 106 |
| No-signal days | 8 |
| Avg signals per day | ~2.5 |
| Best week | +$847 (May 4) |
| Worst week | −$138 (Apr 27) |
| Best month | May +$1,658 (+16.6%) |

**Character:** High-beta momentum names make large OR moves. May 2026 trade deal rally
was captured strongly via SNDK, APP, DDOG. More volatile month-to-month but higher peak alpha.

---

## Set B — QQQ Top-15 by Dollar Volume (2026)

**Tickers:** `NVDA TSLA MU MSFT AAPL AMZN AMD GOOGL META AVGO INTC PLTR GOOG NFLX MRVL`

**Selection criteria:** Top 15 QQQ components ranked by average daily dollar volume Jan–Jun 2026.
Objective, liquidity-first selection. No hand-curation.

| Rank | Ticker | Avg Daily $Vol | Avg Volume | Avg Close |
|---|---|---|---|---|
| 1 | NVDA | $33.3B | 172.7M | $193 |
| 2 | TSLA | $24.6B | 60.8M | $406 |
| 3 | MU | $22.3B | 43.5M | $491 |
| 4 | MSFT | $15.0B | 36.0M | $416 |
| 5 | AAPL | $12.8B | 47.4M | $270 |
| 6 | AMZN | $11.3B | 48.4M | $235 |
| 7 | AMD | $10.8B | 38.6M | $278 |
| 8 | GOOGL | $10.6B | 32.0M | $334 |
| 9 | META | $10.2B | 16.1M | $635 |
| 10 | AVGO | $8.9B | 24.8M | $362 |
| 11 | INTC | $8.3B | 120.3M | $65 |
| 12 | PLTR | $7.1B | 48.5M | $148 |
| 13 | GOOG | $7.0B | 21.1M | $332 |
| 14 | NFLX | $4.0B | 44.7M | $90 |
| 15 | MRVL | $3.4B | 24.0M | $118 |

**Log dir:** `logs/replay_2026_stock_m1_winrate_qqq15/`

### 2026 YTD Results (Jan 2 – Jun 4, 84 trading days with signals)

| Month | P&L | Return |
|---|---|---|
| Jan | +$122 | +1.2% |
| Feb | +$716 | +7.2% |
| Mar | +$540 | +5.4% |
| Apr | +$636 | +6.4% |
| May | +$452 | +4.5% |
| Jun YTD | +$179 | +1.8% |
| **Total** | **+$2,645** | **+26.5%** |

| Metric | Value |
|---|---|
| Trading days with signals | 84 / 106 |
| No-signal days | 22 |
| Avg signals per day | 2.77 |
| Best week | +$552 (Mar 9) |
| Worst week | −$144 (Mar 2) |
| Best month | Feb +$716 (+7.2%) |

**Signal distribution:**

| Signals/day | Days | % |
|---|---|---|
| 1 | 23 | 27.4% |
| 2 | 16 | 19.0% |
| 3 | 21 | 25.0% |
| 4 | 13 | 15.5% |
| 5 | 6 | 7.1% |
| 6 | 2 | 2.4% |
| 7 | 3 | 3.6% |

---

---

## Set C — Russell 2000 Top-20 by Dollar Volume (2026)

**Tickers:** `HOOD RKLB ASTS SOFI IONQ SMCI OKLO RDDT NU HIMS RKT CIFR MARA DKNG AFRM HUT RIOT LUNR JOBY CLSK`

**Selection criteria:** Top 20 Russell 2000 components ranked by average daily dollar volume Jan–Jun 2026.
Small/mid-cap names with high intraday activity — AI/robotics, crypto mining, fintech, EV.

| Rank | Ticker | Avg Daily $Vol | Avg Volume | Avg Close |
|---|---|---|---|---|
| 1 | HOOD | $2.5B | 29.8M | $84 |
| 2 | RKLB | $2.1B | 24.2M | $85 |
| 3 | ASTS | $1.7B | 17.7M | $92 |
| 4 | SOFI | $1.2B | 65.0M | $19 |
| 5 | IONQ | $1.2B | 26.5M | $42 |
| 6 | SMCI | $1.1B | 37.9M | $30 |
| 7 | OKLO | $871M | 12.2M | $69 |
| 8 | RDDT | $864M | 5.4M | $164 |
| 9 | NU | $812M | 53.8M | $15 |
| 10 | HIMS | $748M | 31.6M | $24 |
| 11 | RKT | $481M | 28.0M | $17 |
| 12 | CIFR | $480M | 27.7M | $17 |
| 13 | MARA | $469M | 46.2M | $10 |
| 14 | DKNG | $367M | 14.3M | $26 |
| 15 | AFRM | $356M | 6.0M | $60 |
| 16 | HUT | $343M | 5.0M | $68 |
| 17 | RIOT | $331M | 18.9M | $17 |
| 18 | LUNR | $329M | 13.6M | $23 |
| 19 | JOBY | $299M | 28.0M | $11 |
| 20 | CLSK | $287M | 24.2M | $12 |

**Log dir:** `logs/replay_2026_stock_m1_winrate_r2000top20/`

### 2026 YTD Results (Jan 2 – Jun 4, 92 trading days with signals)

| Month | P&L | Return |
|---|---|---|
| Jan | +$486 | +4.9% |
| Feb | +$2,664 | +26.6% |
| Mar | +$3,133 | +31.3% |
| Apr | +$1,047 | +10.5% |
| May | +$717 | +7.2% |
| Jun YTD | +$102 | +1.0% |
| **Total** | **+$8,148** | **+81.5%** |

| Metric | Value |
|---|---|
| Trading days with signals | 92 / 106 |
| No-trade days | 14 |
| Avg signals per day | ~3.5 (est.) |
| Best day | +$884 (Apr 2) |
| Worst day | −$202 (Feb 3) |
| Best month | Mar +$3,133 (+31.3%) |
| Worst month | Jan +$486 (+4.9%) |

**Character:** High-beta R2000 names make explosive OR moves. Feb–Mar 2026 was exceptional
(+57.9% combined) driven by HOOD, RKLB, ASTS, and IONQ riding the AI/space/fintech rally.
May was weaker than Set A because Set A's SNDK/APP/DDOG captured the trade deal rally better.
Crypto miners (MARA, RIOT, HUT, CIFR) add significant vol — both upside and downside.

---

## Head-to-Head: All Three Sets (2026 YTD)

| Metric | Set A (Original 19) | Set B (QQQ Top-15) | Set C (R2000 Top-20) |
|---|---|---|---|
| Total P&L | +$3,337 | +$2,645 | **+$8,148** |
| Return on $10k | +33.4% | +26.5% | **+81.5%** |
| Signal days / 106 | 98 | 84 | 92 |
| No-trade days | 8 | 22 | 14 |
| Best month | May +$1,658 | Feb +$716 | Mar +$3,133 |
| Worst month | Jan +$27 | Jan +$122 | Jan +$486 |
| Monthly range | +0.3% → +16.6% | +1.2% → +7.2% | +4.9% → +31.3% |
| Best day | n/a | n/a | +$884 (Apr 2) |
| Worst day | n/a | n/a | −$202 (Feb 3) |

### Key differences

**Set C dominates in absolute return.** +81.5% vs +33.4% for Set A and +26.5% for Set B.
The high-beta R2000 names make significantly larger intraday moves off the OR, translating
directly to higher P&L per signal.

**Set C's Feb–Mar 2026 was exceptional.** +26.6% + +31.3% = +57.9% in two months.
The AI infrastructure, space, and fintech names (HOOD, RKLB, ASTS, IONQ, SMCI) had
sustained momentum runs that the win-rate selector captured cleanly.

**Set C's May was weak relative to Set A.** Set A: +16.6% vs Set C: +7.2%. The US–China trade
deal rally that drove SNDK, DDOG, and APP in Set A did not lift the crypto miners and
speculative AI names in Set C as much.

**Set C has higher variance.** Monthly swings from +4.9% to +31.3% vs Set A's +0.3% to +16.6%.
The crypto mining exposure (MARA, RIOT, HUT, CIFR) adds tail risk on down-momentum days.

**Set B (QQQ mega-caps) remains the weakest.** Mega-cap names grind rather than OR-breakout.

### Why Set C outperforms

Russell 2000 small-caps with high dollar volume are extreme OR momentum candidates:
- Very high beta vs QQQ and SPY — same OR setup generates 3–5× the move
- News-driven catalysts (AI fundraising, space launches, crypto price) create decisive OR breaks
- Win-rate selector's historical signal quality screen filters the noise; what fires tends to move

The trade-off is higher daily variance and more exposure to sector rotation risk. On crypto
down-days (MARA, RIOT, HUT all correlate), the pool takes simultaneous losses.

---

## Planned Experiments

| Set | Description | Status |
|---|---|---|
| A | Original 19-ticker momentum pool | ✅ 2018–2026 complete |
| B | QQQ top-15 by dollar volume (2026) | ✅ 2026 YTD complete |
| C | Russell 2000 top-20 by dollar volume (2026) | ✅ 2026 YTD complete |
| D | Hybrid: Set A ∪ Set C high-signal names (drop crypto miners) | Planned |
| E | Sector rotation: best OR signal tickers per month | Planned |

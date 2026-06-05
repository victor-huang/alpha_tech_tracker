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

## Head-to-Head: Set A vs Set B (2026 YTD)

| Metric | Set A (Original 19) | Set B (QQQ Top-15) |
|---|---|---|
| Total P&L | +$3,337 | +$2,645 |
| Return on $10k | +33.4% | +26.5% |
| Signal days / 106 | 98 | 84 |
| No-signal days | 8 | 22 |
| Avg signals/day | ~2.5 | 2.77 |
| Best month | May +$1,658 | Feb +$716 |
| Worst month | Jan +$27 | Jan +$122 |
| Monthly range | +0.3% → +16.6% | +1.2% → +7.2% |

### Key differences

**Set A fires more often.** 98 vs 84 signal days — the original pool generates OR signals on
nearly every trading day. The mega-cap names in Set B (MSFT, AAPL, GOOGL, AMZN) trend smoothly
and rarely produce decisive OR breakouts.

**Set A has higher peak alpha but more variance.** May 2026 (+16.6%) was driven by SNDK, APP,
and DDOG — mid-cap momentum names not in Set B. Set B's best month was February (+7.2%).

**Set B is more consistent month-to-month.** Monthly return range of 1.2%–7.2% vs 0.3%–16.6%.
The mega-caps produce smaller but steadier intraday moves.

**Set B has worse no-signal days.** 22 idle days vs 8. High-liquidity names like MSFT and AAPL
frequently fail the volume gate or OR midpoint cross, producing no tradeable setup.

**INTC is notable.** Ranked #11 by dollar volume due to high share count and low price ($65).
Its OR signals may not be as clean as the price-action-driven names in Set A.

### Why Set A outperforms

The win-rate OR strategy favors tickers that:
- Make decisive moves in the first 15 minutes (high intraday range relative to ATR)
- Have sufficient volume to pass the volume gate reliably
- Are driven by stock-specific news/momentum rather than broad index tracking

Set A's momentum names (SNDK, DDOG, APP, RDDT) fit this profile better than the mega-cap
index-movers in Set B, which tend to gap and grind rather than trend cleanly from the OR.

---

## Planned Experiments

| Set | Description | Status |
|---|---|---|
| A | Original 19-ticker momentum pool | ✅ 2018–2026 complete |
| B | QQQ top-15 by dollar volume (2026) | ✅ 2026 YTD complete |
| C | Hybrid: Set A ∪ Set B high-signal names | Planned |
| D | Sector rotation: best OR signal tickers per month | Planned |

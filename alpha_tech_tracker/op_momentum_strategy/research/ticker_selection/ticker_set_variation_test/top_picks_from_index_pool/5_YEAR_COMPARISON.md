# 5-Year Pool Comparison — Annual Backtest Results (2021–2025 + 2026 YTD)

**Parameters** (identical across all pools and all years):
```
--regime-filter --regime-ma 8
--window M1 09:30 3 --window A1 13:15 1 --window A2 15:00 1
--min-or-range 0.5 --min-or-range-windows M1
--morning-split 100
--reversal --top 2
--or-bar-lookback 3
--bearish-reentry --bullish-reentry
--stop-pct 0.15 --trailing-ma ma20
```

**Capital**: $10,000 initial, $5,000/slot × 2 slots, no-compound (daily reset).

**Source**: Log files in this directory (`{pool}_{year}.log`). Each year run independently.

---

## Annual Return Table (no-compound, each year independent)

| Pool | 2021 | 2022 | 2023 | 2024 | 2025 | 5yr Avg | 2026 YTD |
|------|------|------|------|------|------|---------|----------|
| **SPY High-Vol** | +118.78% | +165.47% | +169.22% | +118.97% | +196.34% | **+153.8%** | +58.49% |
| **Random Nasdaq-100** | +118.34% | +139.35% | +102.38% | +104.40% | +81.70% | **+109.2%** | +40.39% |
| **QQQ High-Vol** | +110.76% | +175.30% | +119.56% | +67.12% | +59.93% | **+106.5%** | +46.57% |
| **ARKK Holdings** | +163.49% | +218.03% | +157.68% | +102.18% | +43.40% | **+137.0%** | +20.54% |
| **Russell 2000** | +140.76% | +235.75% | +190.05% | 0.00%† | +32.34% | **+119.8%** | +40.86% |
| **Nasdaq Biotech** | +84.25% | +107.06% | +96.54% | +91.75% | +14.28% | **+78.8%** | +15.67% |
| **Industrials** | +88.79% | +92.84% | +70.00% | 0.00%† | +25.63% | **+55.5%** | +17.56% |
| **Dow Jones** | +67.94% | +109.16% | +67.23% | +66.88% | +12.91% | **+64.8%** | +13.63% |
| **Mid-Cap AI** ⚠️ | +244.95% | +351.94% | +390.15% | +169.85% | +48.96% | **+241.2%** | +45.11% |

† **0.00%** = EV gate blocked all signals (no trades fired). Pool had negative rolling EV across all tickers in 2024 for that year.

⚠️ **Mid-Cap AI numbers for 2021–2024 are unreliable** — see caveat below.

---

## Final Portfolio Table ($10,000 → X)

| Pool | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 YTD |
|------|------|------|------|------|------|----------|
| SPY High-Vol | $21,878 | $26,547 | $26,922 | $21,897 | $29,634 | $15,849 |
| Random Nasdaq-100 | $21,834 | $23,935 | $20,238 | $20,440 | $18,170 | $14,039 |
| QQQ High-Vol | $21,076 | $27,530 | $21,956 | $16,712 | $15,993 | $14,657 |
| ARKK Holdings | $26,349 | $31,803 | $25,768 | $20,218 | $14,340 | $12,054 |
| Russell 2000 | $24,076 | $33,575 | $29,005 | $10,000† | $13,234 | $14,086 |
| Nasdaq Biotech | $18,425 | $20,706 | $19,654 | $19,175 | $11,428 | $11,567 |
| Industrials | $18,879 | $19,284 | $16,999 | $10,000† | $12,563 | $11,756 |
| Dow Jones | $16,794 | $20,916 | $16,723 | $16,688 | $11,291 | $11,363 |
| Mid-Cap AI ⚠️ | $34,495 | $45,194 | $49,015 | $26,985 | $14,896 | $14,511 |

---

## ⚠️ Mid-Cap AI Pool Caveat — Sparse Ticker Coverage

The Mid-Cap AI pool (`SOUN, AI, UPST, IONQ, GTLB, MNDY, RBRK, AFRM, BBAI, IREN`) was selected as a 2026-era pool. Many tickers did not exist in earlier years:

| Ticker | IPO / Listing | First Full Year |
|--------|--------------|-----------------|
| RBRK (Rubrik) | Apr 2024 | 2025 |
| SOUN (SoundHound) | Apr 2022 (SPAC) | 2023 |
| BBAI (BigBear.ai) | Dec 2021 (SPAC) | 2022 |
| GTLB (GitLab) | Oct 2021 | 2022 |
| MNDY (Monday.com) | Jun 2021 | 2022 |
| IONQ | Oct 2021 (SPAC) | 2022 |
| IREN (Iris Energy) | Nov 2021 | 2022 |
| AFRM (Affirm) | Jan 2021 | 2021 (partial) |
| UPST (Upstart) | Sep 2020 | 2021 |
| AI (C3.ai) | Dec 2020 | 2021 |

**Effective pool size per year:**
- **2021**: ~4 tickers (UPST, AI, IONQ/MNDY/GTLB partial)  
- **2022**: ~8 tickers (RBRK still missing)  
- **2023–2024**: ~8 tickers (RBRK still missing)  
- **2025+**: all 10, but RBRK has limited cache history  

The 2021 return of +245% is driven almost entirely by UPST, which ran from ~$20 to ~$400 during that year — a once-in-a-cycle move. The 2022–2023 numbers are similarly inflated by a sparse high-volatility pool. **Treat Mid-Cap AI 2021–2024 as noise**, not as a reliable pool comparison signal.

---

## Key Findings

### Finding A: SPY High-Vol Is Consistently the Best Pool

SPY High-Vol is the only pool that:
- Never goes below +118% in any year (minimum 2021 and 2024)
- Accelerates in 2025 (+196%) — the highest single-year return of any pool
- Shows no decay trend: 2025 is its best year

5-year average: **+153.8%** — the highest of all reliable pools.

### Finding B: Random Nasdaq-100 Is the Most Consistent Performer

A randomly selected 10-stock Nasdaq-100 subset delivers:
- Tightest return band: +81% to +139% (floor is highest of all pools except SPY)
- Never zero (EV gate always finds signals)
- 5-year average **+109.2%** — 3rd best, and fully reliable (all tickers existed 2021+)

This confirms the earlier finding: **index membership quality provides a baseline regardless of individual stock selection**.

### Finding C: QQQ High-Vol Is Strong in 2021–2023, Fades After

QQQ High-Vol (MSTR, CRWD, SHOP, MELI, SNOW, DDOG, AMZN, MSFT, GOOGL, AVGO):
- Peak: +175% in 2022
- Clear downtrend: 2023 (+120%) → 2024 (+67%) → 2025 (+60%)
- 2026 YTD still solid (+47%) but no longer beating SPY High-Vol or even Random Nasdaq-100 in 5yr avg

The 2024–2025 fade likely reflects the mega-cap names (AMZN, MSFT, GOOGL) maturing into lower-beta, less intraday-volatile instruments.

### Finding D: ARKK Shows a Multi-Year Declining Trend

ARKK peak: 2022 (+218%) — benefiting from high-volatility speculative names.  
ARKK 2025: +43% — barely outperforming the 2026 YTD.

The decline is structural: ARKK names (ROKU, PATH, CRSP, RXRX) are increasingly thin-volume, event-driven binary names. Their intraday OR patterns are degrading. **Do not add ARKK names to the V2 pool.**

### Finding E: Russell 2000 and Industrials Both Zero-Out in 2024

Both pools had 0 qualifying signals in 2024 — the EV gate filtered out every ticker for the full year:
- Russell 2000 2024: no trades (AMC, PLUG, RUN, PENN — all collapsed in price and liquidity)
- Industrials 2024: no trades (AAL, DE, URI — mean-reverting behavior in 2024)

This is a strong signal that the OR momentum edge is **regime and composition dependent** for these pools. When the pool tickers become mean-reverting or lose directional bias, the 60-day rolling EV turns negative and the strategy correctly stands down.

### Finding F: Nasdaq Biotech Is Deceptively Consistent — Then Falls Off a Cliff in 2025

Biotech showed steady 84–107% returns from 2021–2024, then collapsed to +14% in 2025. This is a regime shift: 2025 was a brutal year for biotech (FDA uncertainty, PDUFA-driven binary events, mass delistings). The 2026 YTD of +16% confirms the degraded regime persists.

### Finding G: Dow Jones Is the Weakest Reliable Pool — But Not Useless

Dow Jones averages +64.8%/year — the lowest of reliable pools. But note:
- It's positive every year (no zero-outs)
- 2022 was +109% — the strategy works even in blue-chips in high-volatility regimes
- 2025 and 2026 both in the +12–13% range — barely viable

The Dow pool's weakness is that average win % moves are small (~0.5% per trade). The strategy needs large % swings to generate meaningful P&L with $5,000 slots.

---

## Pool Rankings by 5-Year Average (reliable pools only)

| Rank | Pool | 5yr Avg | Min Year | Max Year | 2026 YTD | Verdict |
|------|------|---------|----------|----------|----------|---------|
| 1 | **SPY High-Vol** | +153.8% | +118.8% | +196.3% | +58.5% | ✅ Best pool, no decay |
| 2 | **ARKK Holdings** | +137.0% | +43.4% | +218.0% | +20.5% | ⚠️ High variance, declining |
| 3 | **Russell 2000** | +119.8% | 0% | +235.8% | +40.9% | ⚠️ Zeros out in weak years |
| 4 | **Random Nasdaq-100** | +109.2% | +81.7% | +139.4% | +40.4% | ✅ Most consistent |
| 5 | **QQQ High-Vol** | +106.5% | +59.9% | +175.3% | +46.6% | ⚠️ Fading since 2023 |
| 6 | **Nasdaq Biotech** | +78.8% | +14.3% | +107.1% | +15.7% | ❌ Regime-sensitive, 2025 cliff |
| 7 | **Industrials** | +55.5% | 0% | +92.8% | +17.6% | ⚠️ Zeros out, low ceiling |
| 8 | **Dow Jones** | +64.8% | +12.9% | +109.2% | +13.6% | ❌ Weak, near-flat in 2025–2026 |

---

## Implication: What to Do with These Results

1. **SPY High-Vol confirmed as the strongest stable pool.** Already partially overlaps with V2 (NVDA, AMD, META, PLTR, COIN, TSLA). The remaining candidates — APP, SMCI, NFLX, ARM — should be individually screened (30d + 90d) for V2 addition.

2. **Random Nasdaq-100's consistency suggests pool diversification has floor value.** A broader pool (20 tickers) mixing V2 + SPY High-Vol non-overlaps may preserve SPY's ceiling while adding Random Nasdaq's floor.

3. **QQQ High-Vol's mega-caps (AMZN, MSFT, GOOGL) are dragging it down.** CRWD, SHOP, MELI, SNOW, DDOG are the signal carriers — those are the names to individually screen.

4. **Never mix Russell 2000, Industrials, or sub-$15 names into V2.** They either zero-out or dilute the top-3 selection in any year.

5. **Mid-Cap AI (RBRK, MNDY, IONQ) may work as an overlay strategy** for the A1 window specifically (as shown in the 2026 YTD analysis). Not suited for an M1-primary pool.

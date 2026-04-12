# QQQ Regime Signal Filter — Findings

Tested two QQQ daily-MA-based signal suppression filters:

1. **Bullish regime filter** (`--regime-filter`): suppress **BULLISH** signals when QQQ
   is below its N-day MA (i.e., avoid going long in a bear market).
2. **Bearish signal filter** (contrarian): suppress **BEARISH** signals when QQQ is
   at or above its N-day MA (i.e., avoid going short in a bull market).

Both filters used the prior business day's QQQ close (not today's) to avoid lookahead
bias — data known by 9:45 AM ET before signal time.

---

## Finding 1 — Bullish Regime Filter (`--regime-filter`)

### Bug: original results were inflated by lookahead

The original `build_bearish_regime_dates` used **today's** QQQ close to decide whether
to suppress today's BULLISH signal. Today's close is not known at 9:45 AM ET when the
signal fires — this was a 1-day lookahead bias.

After fixing to use the **prior day's** close (shift the regime set forward +1 business
day), all historical outperformance disappeared.

### Sweep results (2025-01-01 → 2026-04-10, post-fix, SIP feed)

Config: top-2, weights 60/40, M1+A1+A2, morning-split 100, reversal+BRE+BRU

| Filter | Return | Trades | Win rate |
|---|---|---|---|
| off (baseline) | +262.75% | 1802 | 47.7% |
| MA3 | — | — | — |
| MA5 | — | — | — |
| MA8 | — | — | — |
| … | — | — | — |

No MA value (3–50) beat the no-filter baseline after the lookahead fix.

### Conclusion

The regime filter's entire historical edge (original 5-year: +16pp) was the 1-day
lookahead — using today's QQQ close to decide today's trade. After correcting to use
only prior-day settled data, the filter adds no value on a clean backtest.

**Recommendation: do not use `--regime-filter` in live or backtest configs.**

---

## Finding 2 — Bearish Signal Filter (contrarian)

Hypothesis: in a bull market (QQQ above its MA), BEARISH signals are low-conviction
and should be skipped.

### Sweep results (2025-01-01 → 2026-04-10, SIP feed)

Config: top-2, weights 60/40, M1+A1+A2, morning-split 100, reversal+BRE+BRU, SIP feed

| Filter | Return | Trades | Win rate |
|---|---|---|---|
| **off** | **+262.75%** | 1802 | 47.7% |
| MA3 | +211.81% | 1587 | 48.3% |
| MA5 | +211.72% | 1560 | 49.2% |
| MA8 | +220.71% | 1557 | 48.4% |
| MA10 | +211.98% | 1564 | 48.3% |
| MA13 | +210.28% | 1528 | 49.5% |
| MA15 | +212.67% | 1536 | 49.3% |
| MA20 | +219.58% | 1545 | 49.3% |
| MA30 | +217.73% | 1555 | 48.7% |
| MA50 | +219.89% | 1538 | 49.3% |

Every MA value tested loses to the no-filter baseline by **~40–50pp**.

### Why the filter hurts

BEARISH signals in this strategy fire on stocks showing downside OR breakouts below MA20
and MA200. These are ticker-specific technical breakdowns, not market-direction trades.
The pool (TSLA, NVDA, COIN, PLTR, etc.) contains high-beta names that can sell off hard
on any given day regardless of QQQ trend. Suppressing their bearish signals during bull
regime removes real edge — it mistakes "the market is up" for "this stock can't go down."

Win rate increases slightly (e.g. MA13: 49.5% vs 47.7%) but trade count drops by ~15%
and the removed trades evidently had positive EV overall.

### Conclusion

The contrarian bearish signal filter consistently hurts return across all MA periods
tested. BEARISH signals are valuable in bull markets for this pool and should not be
suppressed by a broad QQQ regime overlay.

**Recommendation: do not implement or use this filter.**

---

## Summary

| Filter | Direction | Result |
|---|---|---|
| Bullish regime filter (`--regime-filter`) | Skip BULLISH when QQQ bearish | Appeared to work; entire edge was lookahead bias — removed |
| Bearish signal filter (contrarian) | Skip BEARISH when QQQ bullish | Hurts by ~40–50pp across all MA values — removed |

Neither filter provides clean edge when implemented without lookahead. Both were removed
from `op_momentum_backtest.py` and `op_momentum_selector_backtest.py`.

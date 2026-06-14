# Short Trade Re-entry Strategy — Findings

**Analysis script:** `analyze_short_trade_reentry.py`
**Replay config:** M1 09:30/1 + A1 10:30/6 | stop-pct 0.1 | reversal | top-2 | weights 60/40 | $10k capital
**Short trade definition:** original trade closed within ≤15 min (via `fallback_20pct`, `hard_stop`, or `trailing_stop_ma20`)

---

## Strategy Overview

After a trade exits early (≤15 min), instead of moving on, we observe the price for a short window and route to one of two branches:

**Branch A — Price reclaims:**
If the price closes back above (BULLISH) or below (BEARISH) the original exit level within 5–20 min post-exit, re-enter the **same direction** on the next bar open. Hold for flat-cut minutes, with a hard stop.

**Branch B — Price fails to reclaim:**
If no reclaim is seen in the 5–20 min window, enter the **opposite direction** 25 min after the original exit. Hold for flat-cut minutes, with a hard stop.

**Key parameters:**
| Parameter | Default tested | Best found |
|---|---|---|
| Watch window | 5–20 min post-exit | 5–20 min |
| Branch B delay | +5 min past watch-end (25 min total) | 25 min |
| Hard stop | 1% of deployed capital | **0.5%** |
| Flat cut (hold time) | 120 min | **240 min** |
| Stop checked against | bar Low (long) / bar High (short) | — |

---

## MDD Cliff — The Core Insight

Across all 4 years, trades that never reach -0.5% MDD have 60–90% win rates. Once a trade touches -0.5% drawdown, win rate drops to 15–25%. This cliff is the structural edge.

| MDD bucket | Win rate (typical) | Observation |
|---|---|---|
| 0% (never went negative) | 5–80% | Mixed — often front-runs or fails immediately |
| > -0.5% | **60–90%** | Strong edge zone |
| -0.5% to -1% | 15–27% | Edge collapses |
| < -1% | < 15% | Stop-out territory |

**Implication:** A 0.5% hard stop preserves the good trades and cuts the bad ones before they bleed. Wider stops (1–2%) allow more of the -0.5% to -1% MDD zone to survive and drag down results.

---

## Parameter Sweep Results (4-year net improvement vs original P&L)

Net improvement = re-entry P&L − original short-trade P&L (original trades were already losses).

```
stop%   hold  |     2023     2024     2025     2026 |   4yr net
--------------------------------------------------------------------
0.005   60    |   +6,057   +2,246   +2,489   +2,674 |   +13,465
0.005   90    |   +5,559   +3,202   +1,908   +2,399 |   +13,069
0.005   120   |   +5,781   +2,596   +1,990   +2,874 |   +13,242
0.005   150   |   +6,323   +2,853   +1,783   +2,608 |   +13,568
0.005   180   |   +6,887   +2,662   +1,563   +2,590 |   +13,702
0.005   240   |   +7,381   +3,333   +1,987   +2,110 |   +14,811  ← BEST

0.01    60    |   +4,363     +766   -1,397   +2,568 |    +6,301
0.01    120   |   +4,601     +782   -2,463   +2,996 |    +5,916
0.01    180   |   +5,991     +594   -1,933   +3,088 |    +7,740
0.01    240   |   +7,560   +1,605   -1,269   +2,331 |   +10,226

0.015   240   |   +5,907   +1,470     +311   +2,427 |   +10,115
0.02    240   |   +6,944   +1,830   -1,333   +2,824 |   +10,265
0.03    240   |  +10,457   +1,967   -2,005   +2,970 |   +13,389
```

**Winner: `--stop-pct 0.005 --max-hold-min 240`** — +$14,811 net improvement across 4 years, positive in all 4 years.

---

## Best Config Results: 0.5% stop / 240-min flat cut

### Per-year summary

| Year | Short trades | Branch A | Branch B | WR | Total P&L | Original P&L | Net impr |
|---|---|---|---|---|---|---|---|
| 2023 | 485 | 201 | 284 | 19.2% | +$2,690 | -$4,691 | **+$7,381** |
| 2024 | 433 | 173 | 260 | 20.8% | +$888 | -$2,445 | **+$3,333** |
| 2025 | 628 | 275 | 353 | 15.9% | -$2,146 | -$4,133 | **+$1,987** |
| 2026 | 206 | 112 | 94 | 18.9% | +$628 | -$1,482 | **+$2,110** |
| **4yr** | **1,752** | **761** | **991** | **18.5%** | **+$2,060** | **-$12,752** | **+$14,811** |

### Per-year Branch detail

| Year | Branch | n | WR | Avg win | Avg loss | Stop-out | P&L |
|---|---|---|---|---|---|---|---|
| 2023 | A (same-dir) | 201 | ~21% | +3.02% | -0.49% | 79.6% | +$2,106 |
| 2023 | B (reversal) | 284 | ~17% | +2.22% | -0.50% | 80.3% | +$585 |
| 2024 | A (same-dir) | 173 | ~27% | +2.44% | -0.48% | 73.4% | +$2,058 |
| 2024 | B (reversal) | 260 | ~17% | +1.72% | -0.49% | 79.6% | -$1,170 |
| 2025 | A (same-dir) | 275 | ~17% | +2.44% | -0.49% | 82.5% | -$630 |
| 2025 | B (reversal) | 353 | ~15% | +1.93% | -0.49% | 82.7% | -$1,517 |
| 2026 | A (same-dir) | 112 | ~22% | +2.29% | -0.50% | 78.6% | +$489 |
| 2026 | B (reversal) | 94 | ~17% | +2.35% | -0.49% | 81.9% | +$138 |

**Branch A consistently outperforms Branch B.** Branch B (reversal) is the weaker leg — it drags in 2024 and 2025.

---

## Known Issues / Broken Slot

**Branch B at 10:30 ET consistently fails (0–7% WR)**:
Branch B fires at 10:30 ET when the original trade was from the A1 10:30 window. At this time, the A1 window's opening-range momentum is still intact, so a reversal immediately loses to continued directional pressure.

| Year | 10:30 Branch B | WR | Avg P&L% |
|---|---|---|---|
| 2023 | 41 trades | 7.3% | -0.79% |
| 2024 | 36 trades | 0.0% | -1.00% |
| 2025 | 53 trades | 11.3% | -1.44% |

**Potential fix:** Suppress Branch B when `reentry_hhmm` falls in the 10:30–11:00 window, or apply a longer delay for A1-window trades.

---

## Why Win Rate Is Low (~15–20%) but Net Improvement Is Positive

The 0.5% stop is very tight — ~78–82% of re-entries are stopped out. But:
- Losers are capped at exactly -0.5% of deployed capital
- Winners run 2–3% on average (4–6× the risk)
- The net improvement vs original P&L is positive because the **original short trades were already losses** (-$12,752 combined). Even a modest recovery strategy beats doing nothing.

The strategy is essentially a **1:4–1:6 risk/reward system with a low hit rate** — asymmetric payoff structure rather than a high-probability setup.

---

## Comparison: Default 1% stop vs Best 0.5% stop (4-year)

| Config | 4yr net improvement | 2025 drag |
|---|---|---|
| 1% stop / 120 min (original) | +$5,916 | -$2,463 |
| 1% stop / 240 min | +$10,226 | -$1,269 |
| **0.5% stop / 240 min** | **+$14,811** | **+$1,987** |

The tighter stop is the decisive factor — it converts 2025 from a drag to a contributor.

---

## Implementation Notes

**Script:** `analyze_short_trade_reentry.py`

```bash
# Best config
PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker \
  python alpha_tech_tracker/op_momentum_strategy/analyze_short_trade_reentry.py \
  --year 2026 --stop-pct 0.005 --max-hold-min 240

# Supported years: 2023, 2024, 2025, 2026
# Cache file naming:
#   2023: alpaca_5min_{TICKER}_2022-11-02_2023-12-31.json
#   2024: alpaca_5min_{TICKER}_2023-11-02_2024-12-31.json
#   2025: alpaca_sip_5min_{TICKER}_2024-11-02_2025-12-31.json
#   2026: alpaca_sip_5min_{TICKER}_2026-01-01_2026-05-15.json
```

**CLI flags:**
| Flag | Default | Description |
|---|---|---|
| `--year` | 2026 | Year to analyse; auto-selects log dir and cache files |
| `--stop-pct` | 0.01 | Hard stop as fraction of entry price |
| `--max-hold-min` | 120 | Minutes before flat cut |
| `--watch-start` | 5 | Min after exit to start watching for Branch A confirmation |
| `--watch-end` | 20 | Min after exit to end watch window |
| `--no-trigger-delay` | 5 | Extra min past watch-end before Branch B fires |
| `--max-orig-dur` | 15 | Max original trade duration to qualify as "short" |

---

## Open Questions / Next Steps

1. **Suppress Branch B at 10:30 ET** — filter out the broken A1 reversal slot; estimate +$300–500 improvement per year.
2. **Branch A only** — since Branch A consistently outperforms Branch B, test Branch-A-only execution.
3. **Regime filter** — 2025 is the worst year (trending); test suppressing re-entries on days where QQQ is in a strong trend (e.g., QQQ MA8 slope > threshold).
4. **Capital sizing** — currently re-uses original `qty`. Consider scaling down to a fixed % of window budget to cap per-day exposure.
5. **Live validation** — the entire analysis uses replay logs, not live fills. Slippage on re-entry and stop-out fills (especially the 0.5% stop) needs live testing before deployment.

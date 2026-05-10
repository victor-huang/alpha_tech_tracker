# Backtest Parameter Sweep — 2026

**Feed:** sip  
**Top-N (fixed):** `--top 2 --weights 60 40`  
**Windows (fixed):** M1 09:30/3, A1 10:00/3, A2 13:15/1, A3 15:15/1  
**Features (fixed):** --morning-split 100, --doubledown --doubledown-start 10, --reversal, --bullish-reentry, --bearish-reentry

---

## YTD Context (Jan–May 2026)

Baseline vs trailing-switch-only over the full year to date:

| Month | Baseline | + trailing-switch after-arm |
|---|---|---|
| Jan | +37.99% | +28.58% |
| Feb | +53.33% | +42.11% |
| Mar | +16.85% | +17.66% |
| Apr | +13.79% | +22.17% |
| May | -0.98% | +0.82% |
| **YTD compound** | **+120.98%** | **+111.35%** |

The trailing switch costs ~10pp YTD because Jan–Feb were strong trending months where MA20 trailing stop gave positions room to run. From March onward the trailing switch wins every month. Regime filter compounds this effect — it also clips Jan/Feb entries.

---

## Round 1 — Apr–May sweep (2026-04-01 → 2026-05-08)

Base for this round: `--trailing-ma-switch after-arm` (no other extras)  
Reference: Apr +22.17%, May +0.82%, Total +23.00%

| ID | Description | Apr % | May % | Total % | Trades | W/L |
|---|---|---|---|---|---|---|
| C00 | Baseline (no extras) | +13.79% | -0.98% | +12.81% | 178 | 87W/91L |
| C02 | + trailing-ma-switch after-arm | +22.17% | +0.82% | +23.00% | 182 | 96W/86L |
| **C03** | **+ regime MA8 + trailing-ma-switch after-arm** | **+22.77%** | **+0.97%** | **+23.73%** | 185 | 93W/92L |
| C01 | + regime MA8 only | +15.38% | -0.94% | +14.45% | 180 | 88W/92L |
| C10 | + regime + trailing + min-or-range 0.2 | +21.69% | +0.94% | +22.62% | 182 | 90W/92L |
| C08 | + regime + trailing + min-or-range 0.3 | +19.98% | **+1.46%** | +21.44% | 173 | 86W/87L |
| C09 | + regime + trailing + qqq-align | +17.20% | +1.90% | +19.10% | 172 | **97W/75L** |
| C07 | + regime + trailing + bearish-ma200 | +18.94% | +0.26% | +19.20% | 184 | 97W/87L |
| C04 | + regime + qqq-align | +14.14% | +2.73% | +16.86% | 172 | 87W/85L |
| C05 | + regime + bearish-ma200 | +17.41% | -1.76% | +15.65% | 182 | 86W/96L |
| C11 | AT pool + regime + trailing | **+26.44%** | -5.05% | +21.39% | 171 | 78W/93L |
| C12 | + regime + trailing + qqq-align + bearish-ma200 | +14.41% | +1.04% | +15.46% | 151 | 79W/72L |
| C06 | + regime + min-or-range 0.3 | +13.14% | -0.27% | +12.87% | 166 | 84W/82L |

---

## Round 2 — Mar–May sweep (2026-03-01 → 2026-05-08)

Base for this round: `--trailing-ma-switch after-arm`  
Reference: Mar +17.66%, Apr +22.17%, May +0.82%, 3-month compound +40.65%

### Single param additions

| Config | Mar % | Apr % | May % | 3mo Total |
|---|---|---|---|---|
| `--stop-pct 0.10` | +23.63% | +23.11% | +2.29% | +49.03% |
| `--trailing-ma-switch after-target --trailing-ma-switch-factor 0.5` | +22.22% | +23.12% | +2.63% | +47.97% |
| `--doubledown-start 5` | +17.81% | +22.20% | +3.63% | +43.64% |
| `--min-or-range 0.2` | +19.82% | +21.58% | +0.80% | +42.19% |
| `--bullish-reentry-max-bars 8` | +18.01% | +22.17% | +0.82% | +41.01% |
| `--reversal-max-bars 5` | +17.66% | +22.17% | +0.82% | +40.66% |
| `--bearish-ma200` | +20.87% | +20.19% | -0.50% | +40.57% |
| `--stop-pct 0.20` | +17.61% | +18.84% | -0.41% | +36.04% |
| `--min-ev 0.1` | +15.64% | +19.54% | +1.08% | +36.26% |
| `--regime-filter --regime-ma 10` | +15.13% | +19.32% | +0.43% | +34.88% |
| `--regime-filter --regime-ma 5` | +12.45% | +21.14% | +0.88% | +34.47% |
| `--regime-filter --regime-ma 20` | +11.76% | +20.41% | +1.35% | +33.53% |
| `--qqq-align-filter` | +11.77% | +18.34% | +2.44% | +32.54% |
| `--close-top-pct 0.10` | +13.83% | +1.71% | +5.10% | +20.64% |

### Combo stacking

| Config | Mar % | Apr % | May % | 3mo Total |
|---|---|---|---|---|
| **stop-pct 0.10 + dd-start 5** | **+24.07%** | **+23.35%** | **+4.23%** | **+51.64%** |
| after-target 0.5x + dd-start 5 | +23.19% | +22.84% | +4.84% | +50.87% |
| stop-pct 0.10 + after-target 0.5x + dd-start 5 | +22.21% | +23.53% | +4.92% | +50.66% |
| stop-pct 0.10 + after-target 0.5x | +21.60% | +24.58% | +2.59% | +48.77% |
| stop-pct 0.10 + min-or-range 0.2 | +24.65% | +22.00% | +2.27% | +48.91% |
| stop-pct 0.10 + after-target 0.5x + min-or-range 0.2 | +22.68% | +23.47% | +2.57% | +48.71% |
| stop-pct 0.10 + bearish-ma200 | +24.28% | +21.29% | +0.18% | +45.75% |
| stop-pct 0.10 + after-target 0.5x + bearish-ma200 | +24.20% | +17.40% | +1.89% | +43.48% |

---

## Findings

### Best Apr–May config: C03 — +23.73% (beats QQQ +21.72%)

**`--trailing-ma-switch after-arm --regime-filter --regime-ma 8`**

Both months green: Apr +22.77%, May +0.97%.

```bash
python alpha_tech_tracker/op_momentum_strategy/op_momentum_selector_backtest.py \
  --top 2 --weights 60 40 \
  --window M1 09:30 3 --window A1 10:00 3 --window A2 13:15 1 --window A3 15:15 1 \
  --morning-split 100 --doubledown --doubledown-start 10 \
  --reversal --bullish-reentry --bearish-reentry \
  --regime-filter --regime-ma 8 --trailing-ma-switch after-arm \
  --start 2026-04-01 --end 2026-05-08 --feed sip
```

### Best Mar–May config: stop-pct 0.10 + dd-start 5 — +51.64% (3-month compound)

**`--trailing-ma-switch after-arm --stop-pct 0.10 --doubledown-start 5`**

All three months strongly positive: Mar +24.07%, Apr +23.35%, May +4.23%.

```bash
python alpha_tech_tracker/op_momentum_strategy/op_momentum_selector_backtest.py \
  --top 2 --weights 60 40 \
  --window M1 09:30 3 --window A1 10:00 3 --window A2 13:15 1 --window A3 15:15 1 \
  --morning-split 100 --doubledown --doubledown-start 5 \
  --reversal --bullish-reentry --bearish-reentry \
  --trailing-ma-switch after-arm --stop-pct 0.10 \
  --start 2026-03-01 --end 2026-05-08 --feed sip
```

⚠️ **Caution:** `--stop-pct 0.10` is not validated over Jan–Feb (strong trending months). A tighter stop may cut winning trades early when the market trends cleanly. Run a full YTD backtest before adopting live.

### Key Lessons

| Finding | Detail |
|---|---|
| `--trailing-ma-switch after-arm` is the dominant lever | Alone it turns May from -0.98% to +0.82% and April from +13.79% to +22.17%. Biggest single flag. |
| Trailing switch costs Jan–Feb | In the strong Jan–Feb uptrend, MA20 trailing gives trades more room. Trailing switch exits too early there (-9pp YTD). Net positive from March onward. |
| `--stop-pct 0.10` dramatically helps choppy markets | Cuts losses faster when OR breakouts fail. Mar +6pp, Apr +1pp, May +1.5pp vs default 0.15. Not validated for trending months. |
| `--doubledown-start 5` consistently lifts May | Fires the DD addon earlier, recycling more capital into winners. May improves +3–4pp with minimal April cost. |
| Regime filter clips Jan–Feb gains | Every regime config underperforms baseline in Jan–Feb. Only adopt if comfortable trading fewer days in strong uptrends. |
| All regime filter MA values (5/8/10/20) hurt March | March was mixed-to-bearish — the regime filter suppressed many valid bearish entries. |
| `--close-top-pct 0.10` is too restrictive | April collapses to +1.71%. The moderate signal filter cuts too many good entries in volatile conditions. |
| AT pool is high-beta — works both ways | Apr +26.44% but May -5.05%. Best avoided in chop. |
| `--qqq-align-filter` is conservative overall | Helps May but consistently hurts Mar and Apr by filtering valid contra-QQQ entries. |

---

## Config Details

All configs use `--top 2 --weights 60 40` and inherit the fixed base:
```
--window M1 09:30 3 --window A1 10:00 3 --window A2 13:15 1 --window A3 15:15 1
--morning-split 100 --doubledown --doubledown-start 10
--reversal --bullish-reentry --bearish-reentry
--start 2026-04-01 --end 2026-05-08 --feed sip
```

| ID | Extra flags |
|---|---|
| C00 | *(none — baseline)* |
| C01 | `--regime-filter --regime-ma 8` |
| C02 | `--trailing-ma-switch after-arm` |
| C03 | `--regime-filter --regime-ma 8 --trailing-ma-switch after-arm` |
| C04 | `--regime-filter --regime-ma 8 --qqq-align-filter` |
| C05 | `--regime-filter --regime-ma 8 --bearish-ma200` |
| C06 | `--regime-filter --regime-ma 8 --min-or-range 0.3` |
| C07 | `--regime-filter --regime-ma 8 --trailing-ma-switch after-arm --bearish-ma200` |
| C08 | `--regime-filter --regime-ma 8 --trailing-ma-switch after-arm --min-or-range 0.3` |
| C09 | `--regime-filter --regime-ma 8 --trailing-ma-switch after-arm --qqq-align-filter` |
| C10 | `--regime-filter --regime-ma 8 --trailing-ma-switch after-arm --min-or-range 0.2` |
| C11 | `--ticker-set AT --regime-filter --regime-ma 8 --trailing-ma-switch after-arm` |
| C12 | `--regime-filter --regime-ma 8 --trailing-ma-switch after-arm --qqq-align-filter --bearish-ma200` |

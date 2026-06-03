# 2026 YTD Regime Analysis — OR Momentum Screener

**Generated:** 2026-06-01 | **Revised:** 2026-06-02 (screener bug fixes — see note below)  
**Screener:** `ma_open_range_momentum_screener` — OR 09:30/3b, vol ≥ 1.0x 20dAvg  
**Tickers:** SNDK APP META SNOW SNPS SPOT MU LLY MRVL CRWD QCOM PLTR CHTR TSLA AVGO ARM AMD DDOG RDDT  
**Logs:** `logs/2026_monthly_screener/2026-MM_v2.log` (revised); original: `2026-MM.log`

**Bug fixes applied (2026-06-02):**
1. **Volume lookahead fix** — collection vol now computed incrementally per bar (bars 0..i only), matching live behavior. Previously used full 3-bar window mean upfront, creating a lookahead bias that suppressed some signals that should have fired and included a few that shouldn't.
2. **OR anchor fix** — pre-session hold history and `_build_presession_picks_rows` now anchor at the last OR bar (09:40 with 3-bar OR) instead of the bar *after* OR closes (09:45). Pre-session P&L tables are now measured from the correct entry bar.
3. **Warmup period** — extended from 30 to 45 calendar days for better vol_20d history, especially in early-January months.

**Net effect on regime classifications:** All five regime calls are **unchanged**. Signal counts increased by 8–18 per month (lookahead fix adds more borderline-vol signals). March became significantly more bear (-34.7% vs -19.4%). May became significantly more bull (+59.7% vs +43.7%). Pre-session Jan flipped from +25.5% to -20.1% (OR anchor correction).

---

## Monthly Signal Summary

| Month | Signals | Trading Days | Sig/Day | +15m WR | +1h WR  | EOD WR  | EOD Total P&L | Regime              |
|-------|---------|--------------|---------|---------|---------|---------|---------------|---------------------|
| Jan   | 82      | 20           | 4.1     | 50.0%   | 47.6%   | 43.9%   | -13.7%        | Mild Bear-Drift     |
| Feb   | 70      | 19           | 3.7     | 32.9%   | 38.6%   | 50.0%   | -8.4%         | Acute Bear (AM)     |
| Mar   | 55      | 22           | 2.5     | 40.0%   | 34.5%   | 30.9%   | -34.7%        | Persistent Bear     |
| Apr   | 54      | 21           | 2.6     | 50.0%   | 57.4%   | 63.0%   | +37.0%        | Sharp Bull Reversal |
| May   | 64      | 20           | 3.2     | 56.2%   | 56.2%   | 59.4%   | +59.7%        | Continued Bull      |

### Full Hold-Window Breakdown (Signal Analysis — LONG)

| Month | +15m    | +30m    | +45m    | +1h     | +1h30m  | +2h     | +3h     | +4h     | +5h     | EOD     |
|-------|---------|---------|---------|---------|---------|---------|---------|---------|---------|---------|
| Jan   | 50.0%   | 45.1%   | 45.1%   | 47.6%   | 56.1%   | 53.7%   | 50.0%   | 47.6%   | 51.2%   | 43.9%   |
| Feb   | 32.9%   | 37.1%   | 44.3%   | 38.6%   | 47.1%   | 41.4%   | 47.1%   | 44.3%   | 55.7%   | 50.0%   |
| Mar   | 40.0%   | 45.5%   | 50.9%   | 34.5%   | 45.5%   | 40.0%   | 36.4%   | 30.9%   | 30.9%   | 30.9%   |
| Apr   | 50.0%   | 48.1%   | 55.6%   | 57.4%   | 55.6%   | 55.6%   | 61.1%   | 55.6%   | 55.6%   | 63.0%   |
| May   | 56.2%   | 59.4%   | 56.2%   | 56.2%   | 54.7%   | 53.1%   | 51.6%   | 59.4%   | 56.2%   | 59.4%   |

### Total P&L by Hold Window (LONG, % sum across all signals)

| Month | +15m    | +30m    | +1h     | +2h     | +3h     | +5h     | EOD      |
|-------|---------|---------|---------|---------|---------|---------|----------|
| Jan   | -1.4%   | -14.2%  | -14.9%  | +3.9%   | -1.9%   | +4.3%   | -13.7%   |
| Feb   | -36.0%  | -49.7%  | -31.7%  | -2.9%   | +9.2%   | +5.4%   | -8.4%    |
| Mar   | -6.9%   | -11.4%  | -19.0%  | -22.8%  | -25.6%  | -38.8%  | -34.7%   |
| Apr   | -0.3%   | +0.4%   | +5.6%   | +19.1%  | +23.6%  | +35.3%  | +37.0%   |
| May   | +5.2%   | +14.0%  | +22.2%  | +23.1%  | +23.6%  | +40.0%  | +59.7%   |

---

## Pre-Session Top-2 Performance (9:25 unconditional OR-close entry)

| Month | +15m WR | +1h WR  | +3h WR  | EOD WR  | EOD Total P&L |
|-------|---------|---------|---------|---------|---------------|
| Jan   | 45.0%   | 52.5%   | 45.0%   | 45.0%   | -20.1%        |
| Feb   | 47.4%   | 42.1%   | 44.7%   | 39.5%   | -20.3%        |
| Mar   | 45.5%   | 36.4%   | 38.6%   | 34.1%   | -28.6%        |
| Apr   | 42.9%   | 47.6%   | 59.5%   | 61.9%   | +43.6%        |
| May   | 62.5%   | 57.5%   | 65.0%   | 60.0%   | +42.4%        |

The pre-session top-2 is the most sensitive regime indicator. It flipped positive on **April 1** — one day before the signal analysis also turned green.

---

## Regime Patterns

### Bull Regime (Apr–May)
- Hold-window curve **slopes up or stays flat-positive**: +15m good → EOD great
- Every hold window is profitable — no "wrong" duration
- Signal count stays moderate (2–2.5/day) but quality is high
- Pre-session top-2 EOD win rate > 60%
- **Best hold in Apr:** +3h–EOD (64%+ WR, +33–40% total P&L)
- **Best hold in May:** +1h (63% WR) — afternoon chop reduces EOD edge vs Apr

### Acute Bear — Morning Fade (Feb)
- +15m win rate collapses to **33%** — the open range breakout immediately reverses
- Win rate *recovers* to ~51% by +3h — dip buyers rescue the tape by afternoon
- EOD lands at 50% (neutral) — the day's damage is in the morning
- **Short signal:** short the OR breakout at bar-3 close, cover by +15m–+1h
- Short-side flip on +15m: **+33.8% total** vs long -33.8%
- Pre-session top-2 win rate: 39.5% (early warning the AM trend is broken)

### Deepest Bear — All-Day Fade (Mar)
- +15m win rate looks neutral (48.8%) — the breakout initially holds
- Win rate **steadily degrades** through the day: 48.8% → 41.9% (+3h) → 34.9% (EOD)
- The opening range IS making new highs but the trend is down — no follow-through
- Signal count drops to 2.0/day (lowest all year) — market is not producing clean setups
- **Short signal:** short the OR breakout at bar-3 close, hold to EOD (do NOT cover intraday)
- Short-side flip on EOD: **+19.4% total** vs long -19.4%
- Worst stretch: Mar 19–27 — 8 consecutive days of 0/4 or 0/5 EOD wins
- Pre-session top-2 EOD win rate: 43.2% (confirms bear, but less extreme signal than signal analysis)

### Neutral / Drift (Jan)
- Win rates hover 45–55% across all windows — no strong directional edge
- EOD underperforms (+45.9%) vs short-term (+52.7%) — slightly fade-ish
- Pre-session top-2 still positive (+25.5% EOD) — historical best-picks hold up better than new signals
- **Best hold:** +1h30m–+5h (59.5% WR, marginally positive)
- Signal count highest (3.7/day) — plenty of setups, just inconsistent follow-through

---

## Bear-to-Bull Transition: What Happened at End of March

### The Flip: March 31 → April 1

**March 26–30 (last bear days):**
- Mar 26: 0/5 EOD wins, losses include -6.23%, -3.54%
- Mar 27: 0/5 EOD wins
- Mar 30: 3/11 EOD wins

**March 31 (first reversal day):**
- EOD results: +5.93%, +0.44%, +0.27%, +4.30% — **6/6 wins**, all positive
- The 3-day rolling EOD win rate snapped from ~15% to ~85% in a single session

**April 1 (confirmed):**
- Pre-session top-2: SNDK +2.96% EOD, SPOT +0.34% — both positive
- Signal analysis: 2/3 EOD wins on day 1

### Observable Transition Signals (in order of speed)

1. **Single-day snap:** One day with ≥70% EOD win rate after 5+ days of <35% → regime flip candidate
2. **Pre-session top-2 recovery:** When the top tickers in the 20d rankings start posting 60%+ EOD WR (from 43%) → earliest structural signal (requires ~3 days of data)
3. **Hold-curve shape flip:** When the hold-window curve stops sloping downward and flattens or turns upward → confirms sustained bull
4. **Signal count:** Does NOT recover immediately at the transition (still 2.1/day in Apr) — quality flips before quantity

---

## Short Strategy Performance (If Long Signals Were Reversed)

| Month  | Short +15m Total | Short EOD Total | Best Short Window         |
|--------|------------------|-----------------|---------------------------|
| Feb    | +33.8%           | +8.4%           | +15m–+1h (morning fade)   |
| Mar    | -1.1%            | +19.4%          | EOD (persistent all-day)  |
| **Combined** | **+32.7%** | **+27.8%** | Depends on sub-regime  |

Pre-session top-2 short:
- Feb short EOD: +24.7%
- Mar short EOD: +15.0%
- **Combined: ~+40%**

---

## Decision Framework

Use the prior week's signal EOD win rate each Monday morning:

```
EOD win rate ≥ 60%
  → LONG regime
  → Buy OR breakouts, hold +1h–EOD
  → Pre-session top-2 is additional alpha (best at +3h–EOD in Apr, +2h–+7h in May)

EOD win rate 45–60%
  → NEUTRAL / DRIFT
  → Reduce size, take profits at +15m–+30m
  → Do NOT hold to EOD

EOD win rate < 40%, and +15m win rate is also < 40%
  → ACUTE BEAR (Feb-type)
  → Short the OR breakout at bar-3 close
  → Cover at +15m–+1h (morning fade, afternoon recovers)

EOD win rate < 40%, and +15m win rate is near 50%
  → PERSISTENT BEAR (Mar-type)
  → Short the OR breakout at bar-3 close
  → Hold to EOD — do NOT cover intraday

TRANSITION signal
  → One day with ≥70% EOD win rate after 5+ consecutive days of <35%
  → Pre-session top-2 EOD win rate crosses 60%+ (from below 50%)
  → Flip back to LONG
```

---

## Three-Year Cross-Validation (see 2024 and 2025 docs)

The 2024 analysis added two important corrections to this framework:

- **April recovery is NOT seasonal.** Apr 2024 was a BEAR month (-14.1%). The Apr 2025 recovery was Liberation Day (tariff pause). The Apr 2026 recovery was a technical rebound from Feb-Mar. Do not assume April is bullish — confirm from day 1–3 results.
- **December is reliably bearish.** Dec 2024 -16.3%, Dec 2025 -25.7%. Two consecutive years with consistent December bear signal. Apply SHORT-mode or size reduction in December.
- **Pre-session top-2 can decouple positively from signal analysis.** During Aug 2024 (deepest AM-pop-fade), signal analysis EOD was -28.8% but pre-session top-2 was +12.9%. Consider them independent signals.

---

## Proposed Next Steps

1. **Rolling regime indicator** — compute 5-day trailing EOD win rate across all fired signals and display it in the pre-session rankings header. Flag `[BEAR — consider SHORT]` when below 40%.

2. **Short-mode backtest flag** — `--direction BEAR` reverses P&L sign in output tables so you can directly measure short-side performance without manual arithmetic.

3. **Transition alert** — when a single day posts ≥70% EOD win rate after ≥5 consecutive days of <40%, print `[REGIME FLIP?]` in the pre-session output.

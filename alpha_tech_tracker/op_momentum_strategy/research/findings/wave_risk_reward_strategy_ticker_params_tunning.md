# Wave Risk/Reward — Ticker and Parameter Tuning

Does the `wave_risk_reward.py` setup work beyond the QQQ + SNDK window it was developed on, and
can its box settings be tuned per ticker? Studies run 2026-10-04 with
`analysis_scripts/wave_risk_reward_backtest.py` on cached Alpaca SIP 5-min bars. Background and
earlier findings: [`WAVE_RISK_REWARD_FINDINGS.md`](WAVE_RISK_REWARD_FINDINGS.md); usage:
[`guides/WAVE_RISK_REWARD_GUIDE.md`](../../guides/WAVE_RISK_REWARD_GUIDE.md).

## Summary

- **The setup is ticker-specific.** Over Jan 2 – Oct 2 2026 the best configuration (box signals
  + long-only opening drive, held to the close) made **+156.66% on SNDK but −8.74% on META**,
  after 5 bps costs.
- **On SNDK most of the total is the stock's rally** (+604% buy and hold). A buy-every-morning
  baseline made +137.90%; the edge is that a green first bar **doubles the return per trade**
  (+1.379% vs +0.734%) with half the trades.
- **On META nothing works, even before costs.** Every configuration loses after costs, the
  opening drive is about flat before them, and the green-first-bar filter is no better than
  buying every day.
- **Tuning META's box settings on 3 months does not survive out of sample.** Of 864 setting/exit
  pairs, 23 were profitable on Jul–Oct and only 6 of those also on Jan–Jun. The best tuned
  setting (+4.45%) lost 2.55% on the earlier 6 months; the 15 best had a median of −2.33% there.
- **Ticker selection looks more promising than per-ticker tuning:** the box and opening-drive
  setup only works clearly on strongly trending, high-volatility names.
- **AMD (Finding 4):** box signals have no directional edge (−10.73% before costs over 3 months);
  more fades only reach breakeven; the **wave pullback long** — added for AMD's impulse-wave
  style — made +4.36% (Jul–Oct) and +5.55% on the unseen Jan–Jun 2026.
- **But the pullback edge did not last into 2025 (Findings 5–8).** Tuning AMD's pullback settings
  overfit (best Jan–Jun setting +46.49%, then −11.14% on Jul–Oct); monthly re-tuning on 4 weeks
  lost in 2025 (−2.68%); the default lost 7.50% on AMD 2025. Only coarser waves (C1,
  `--min-wave-bar-ranges 3`) stayed positive on AMD in both years. The run-up and volatility
  triggers did not hold across years.
- **Deep bounce (Finding 9):** buying the first green bar after a deep down wave (≥ 2 × the median
  wave) made +6.09% over AMD's last 3 months (80% win) and +14.72% to +19.69% over 2026, but lost
  in every variant on 2025 (−5% to −20%).
- **Best AMD 2026 combination (Finding 10):** deep bounce + pullback long, +29.59% over Jan–Oct
  2026 with `target-trail` (110 trades, at most 2 open at once) — but −18.81% on 2025. The
  setups that work on AMD in 2026 are the same dip-buying idea and share the same bad year.

## Method

- **Trades:** one per signal, entry at the signal bar's close, exit by `--exit` (`target`,
  `giveback` = out after giving back 32% of the best open profit once up 0.25 × risk, or `eod`),
  at the session close at the latest. A bar touching both stop and target counts as the stop; a
  gap through the stop fills at the open.
- **Costs:** 5 bps round trip unless noted.
- **Totals** are per-trade returns added together with a full position on every trade — not
  compounded, so not directly comparable with buy and hold.
- **Baselines** (one-off script, same trade rules): *buy 09:35 every day* — long at the first
  bar's close with the stop at its low; *green first bar* — the same, only when the first bar
  closes above its open.

---

## Finding 1 — SNDK, full year 2026

Jan 2 – Oct 2 2026, 188 sessions.

| Configuration | Trades | Win | Avg / trade | Total |
|---|---|---|---|---|
| box signals, `--exit target`, no costs | 143 | 41% | +0.003% | +0.45% |
| box signals, `--exit giveback` | 143 | 50% | +0.078% | +11.13% |
| box signals, `--exit eod` | 143 | 38% | +0.141% | +20.12% |
| box + `--opening-drive both`, `--exit giveback` | 332 | 50% | +0.236% | +78.33% |
| box + `--opening-drive both`, `--exit eod` | 332 | 38% | +0.454% | +150.75% |
| box + `--opening-drive long`, `--exit giveback` | 242 | 52% | +0.332% | +80.44% |
| **box + `--opening-drive long`, `--exit eod`** | 242 | 40% | **+0.647%** | **+156.66%** |

Against SNDK's own move:

| Reference | Trades | Avg / trade | Total |
|---|---|---|---|
| buy and hold (244.35 → 1719.35) | — | — | **+604%** |
| buy 09:35 every day, held to close | 188 | +0.734% | +137.90% |
| **green first bar only**, held to close | 99 | **+1.379%** | +136.54% |
| buy 09:35 every day, give-back exit | 188 | +0.373% | +70.16% |
| **green first bar only**, give-back exit | 99 | **+0.700%** | +69.32% |

- The opening drive is almost all of the profit: +130.62% of the +150.75% (189 trades, held to
  the close).
- The short drive is a small drag on SNDK this year (about −6% held to the close, −2% with the
  give-back exit), so long-only is better here.
- Box signals add +11% to +20%; with the give-back exit they lost in January, February, April
  and May and were mostly positive from June (July flat at −0.04%).
- By month (opening drive both, held to the close): Jan +24.6, Feb −11.0, Mar +21.4, Apr +5.3,
  May +26.8, Jun +15.6, Jul +23.6, Aug +26.5, Sep +20.1 (%). July made money even though SNDK
  fell 42% that month.

## Finding 2 — META, full year 2026

Jan 2 – Oct 2 2026, 189 sessions.

| Configuration | Trades | Win | Avg / trade | Total |
|---|---|---|---|---|
| box signals, `--exit target`, no costs | 146 | 35% | −0.013% | −1.88% |
| box signals, `--exit giveback` | 146 | 36% | −0.099% | −14.42% |
| box signals, `--exit eod` | 146 | 33% | −0.039% | −5.72% |
| box + `--opening-drive both`, `--exit giveback` | 334 | 43% | −0.069% | −23.05% |
| box + `--opening-drive both`, `--exit eod` | 334 | 30% | −0.045% | −15.10% |
| box + `--opening-drive long`, `--exit eod` (best) | 230 | 31% | −0.038% | −8.74% |
| box + `--opening-drive short`, `--exit eod` | 250 | 31% | −0.048% | −12.07% |

Against META's own move:

| Reference | Trades | Avg / trade | Total |
|---|---|---|---|
| buy and hold (663.04 → 728.07) | — | — | +10% |
| buy 09:35 every day, held to close | 189 | −0.013% | −2.37% |
| green first bar only, held to close | 84 | −0.036% | −3.03% |
| green first bar only, give-back exit | 84 | −0.095% | −7.99% |

- **No edge before costs either:** 5 bps takes about 17% off 334 trades, so the opening drive
  held to the close is roughly +1.6% before costs.
- By signal type (opening drive both, held to the close): opening drive −9.38% (188 trades),
  gap −3.96%, narrow-box breaks −1.15%, fades −0.03%.
- Only March (+6.5%) and August (+6.3%) were positive; April was worst (−12.7%). META chopped
  all year: four down months of 8–11%, then +30% in September.

### SNDK vs META

| | SNDK | META |
|---|---|---|
| Buy and hold, 2026 | +604% | +10% |
| Opening drive long + box, held to close | **+156.66%** | **−8.74%** |
| Green first bar, avg per trade (held to close) | +1.379% | −0.036% |
| Buy every day, avg per trade (held to close) | +0.734% | −0.013% |

Consistent with the earlier 20-ticker test (green first bar +0.14% per trade before costs): the
opening-drive edge is thin in general and only large on strongly trending, high-volatility names.

## Finding 3 — Tuning META's box settings (tune Jul–Oct, validate Jan–Jun)

**Question:** can the box settings be tuned so META works over the last 3 months — and does
that hold on a period the settings were not chosen on?

**Grid (432 settings × 3 exits, 5 bps):**

| Setting | Values |
|---|---|
| `--min-wave-bar-ranges` | 1.5, 2, 3 |
| `--min-box-waves` | 2, 3 |
| `--small-wave-ratio` | 1.0, 1.5 |
| `--max-box-height-ratio` | 1.5, 2, 3 |
| `--box-stop-ratio` | 0.2, 0.5, 1.0 |
| `--reversion-box-bars` | 6 (fades on), 999 (fades off) |
| `--regime-switch` | `ma-stack`, `off` |

Box signals only (no opening drive). Each setting runs once over Jan 2 – Oct 2 2026 and its
trades are split by entry date: **tune window Jul 2 – Oct 2**, **validation window Jan 2 –
Jul 1**. Settings with fewer than 20 tune-window trades were excluded from ranking.

| | Tune window (Jul–Oct) | Validation (Jan–Jun) |
|---|---|---|
| defaults, best exit (`eod`) | 48 trades, −4.19% | 98 trades, −1.52% |
| **best tuned:** wave 3, regime off, `eod` | 86 trades, **+4.45%** (+0.052% / trade) | 205 trades, **−2.55%** |
| 15 best tuned | all +0.4% to +4.5% | 5 of 15 profitable, median **−2.33%** |

- Only **23 of 864** setting/exit pairs were profitable in the tune window; **6** of those were
  also profitable in validation.
- **Correlation of tune vs validation totals: +0.26** — picking the best recent setting mostly
  picks noise.
- Even the best is about +0.05% per trade — the size of the 5 bps cost.

Settings profitable in both windows:

| Settings | Exit | Tune | Validation |
|---|---|---|---|
| defaults + `--regime-switch off` | eod | 110 trades, +0.80% | 234 trades, +4.36% |
| wave 2, box waves 3, small 1.0, height 1.5, stop 1.0, no fades, regime off | giveback | 22 trades, +1.93% (55% win) | 39 trades, +1.41% (69% win) |
| wave 3, box waves 2, small 1.5, height 3, stop 0.2, fades, regime off | eod | 81 trades, +1.33% | 207 trades, +1.47% |
| wave 2, box waves 3, small 1.0, height 1.5, stop 0.2, no fades, regime off | giveback | 22 trades, +1.25% | 39 trades, +1.17% |
| wave 2, box waves 3, small 1.0, height 2, stop 1.0, no fades, regime off | giveback | 24 trades, +1.02% | 43 trades, +0.85% |

Patterns:
- **The MA-stack regime switch hurts META:** all 15 best tuned settings and all 6 that held up
  have it off — the opposite of QQQ + SNDK (Findings 8 and 10 of the main doc).
- **Strict boxes with the give-back exit win often but rarely trade:** at least 3 box waves,
  small waves, a low height cap and a stop at the far side of the box give 54–69% win rates, but
  only about 7 trades a month at +0.02–0.09% each.

**Conclusion:** don't trade box signals on META. The most stable choice — defaults with
`--regime-switch off --exit eod` — is about breakeven after costs (+0.007% / +0.019% per trade).

---

## Finding 4 — AMD: why box signals fail, and the wave pullback

### Box signals, Jul 2 – Oct 2 2026 (65 sessions)

| Configuration (5 bps unless noted) | Trades | Win | Total |
|---|---|---|---|
| box signals, `--exit target`, no costs | 47 | 26% | −10.73% |
| box signals, `--exit giveback` | 47 | 36% | −8.64% |
| box signals, `--exit eod` | 47 | 21% | −20.39% |
| box, `--regime-switch off`, `--exit eod` | 106 | 21% | −38.19% |
| box + `--opening-drive long`, `--exit giveback` | 82 | 45% | −2.23% (the drive alone +6.41%, 35 trades) |

AMD buy and hold +17.7% (Jul −12%, Aug +2%, Sep +33%); green first bar with the give-back exit
+0.183% per trade vs +0.032% for buying every morning.

### Why the box signals fail

| AMD narrow-box breaks | Value |
|---|---|
| Moved the signal's way after 15 / 60 min | 44% / 48% (median ≈ −0.02%) |
| Box height | 0.34 × ADR |
| Stop distance (20% of the box) | ≈ 1 average 5-min bar range |
| Stopped out / target reached first | 67% / 4% |
| Median best open profit | 1.26R against a ≈ 3.5R target |

- **No direction:** a break of a small intraday box is a coin flip on AMD; the MA-stack regime
  adds nothing (the signals it blocked did the same as the ones it allowed).
- **Geometry:** a stop within one bar range and a 3.5R target need a clean trend. Widening the
  stop (`--box-stop-ratio` 0.5 / 1.0) raised the win rate (36% → 51%) but not the total
  (−8.6% to −9.8%) — the missing piece is direction, not room.
- **Gap signals chase:** entered 0.85 box heights past the edge, then reversed (30% / 40% the
  signal's way at 15 / 60 min); −8.12% of the −8.64% total.
- **Context matters** (narrow-box breaks pooled over AMD, SNDK and META, 178 breaks, 60-minute
  move): breaks that were also a new session high/low averaged +0.362% (46) vs −0.185% for the
  rest (132); with breakout-bar volume ≥ 1.5× average as well, 64% win and +1.09% mean — but only
  22 breaks.

### More fades and stop-and-reverse

Varying `--reversion-box-bars` (6 / 5 / 4 / 3), the regime switch and stop-and-reverse (target
exit, 5 bps): the best was **fade threshold 4, `ma-stack`, stop-and-reverse off: −3.22% over 64
trades, +2.35% without gap signals** (fades 37 trades, +3.40%). Allowing fades in trends made
them lose; stop-and-reverse lost in 23 of 24 settings; gap signals were the largest loss in
every setting. Not validated out of sample.

### Wave pullback

AMD has few tight boxes and moves in impulse waves, so `--wave-pullback` was added (main doc,
Finding 15). Pullback longs, threshold 2, `--exit target-trail`, 5 bps:

| | Trades | Win | Total | Avg / trade |
|---|---|---|---|---|
| Jul 2 – Oct 2 | 18 | 61% | **+4.36%** | +0.242% |
| Jan 2 – Jul 1 (unseen) | 27 | 56% | **+5.55%** | +0.205% |

The only AMD setup positive in both windows; pullback shorts lost (−3.34% / −12.48%, `target`).

## Finding 5 — Tuning AMD's pullback settings (Jan–Jun tune, Jul–Oct 2026 check)

New options made the pullback levels tunable (`--pullback-touch-fib`, `--pullback-floor-fib`,
`--pullback-stop-fib`, `--pullback-target-ext`). Grid: wave size 1.5 / 2 / 3, impulse threshold
1.5 / 1.75 / 2 / 2.5 / 3, touch 23.6 / 38.2 / 50%, entry floor 50 / 61.8 / 78.6%, stop 78.6 /
88.6 / 100 / 115%, target extension 1.0 / 1.272 / 1.618, five exits — 7,425 setting/exit pairs,
pullback longs only, 5 bps. A fast replay (impulses recorded once per wave size, pullback logic
replayed) reproduced the real script exactly (default: 27 trades +5.55%, 18 trades +4.36%).

| | Tune: Jan 2 – Jul 1 | Check: Jul 2 – Oct 2 |
|---|---|---|
| best tuned (wave 1.5, threshold 1.5, touch 23.6%, held to close) | +46.49% (82 trades) | **−11.14%** |
| 20 best tuned | median +44.90% | **0 of 20 positive**, median −12.40% |
| default | +5.55% | +4.36% |

- AMD rose **147%** Jan–Jun (vs +17.7% Jul–Oct); 99% of settings made money there, so tuning
  rewarded the loosest dip-buying. **Correlation of tune vs check: −0.48.**
- Reverse direction (tune on the choppier Jul–Oct, check Jan–Jun): the 20 best were all positive
  on Jan–Jun (median +8.82%) — settings that survive chop also survive a trend.
- Families that held on Jul–Oct across all their combinations: wave size 3 (99% positive vs 34%
  for 1.5), threshold 3 (97%), touch 50% (77%).

Candidates in the real backtest (pullback longs, 5 bps):

| Setting | AMD Jan–Jun | AMD Jul–Oct | SNDK Jan–Jun | SNDK Jul–Oct | META Jan–Jun | META Jul–Oct |
|---|---|---|---|---|---|---|
| default | +5.55% | +4.36% | +10.96% | +5.16% | +1.62% | +1.35% |
| C1: wave size 3 | +3.62% | +4.29% | +9.53% | +4.21% | +2.38% | +3.67% |
| C2: wave 3, threshold 1.75, touch 23.6%, trail 25% | +16.22% | +12.52% | +9.07% | −0.94% | −0.36% | +3.71% |
| C3: wave 3, threshold 1.5, touch/floor 50%, trail 25% | +8.08% | +9.56% | −3.32% | −1.83% | −0.86% | −3.70% |
| C4: wave 2, threshold 1.75, touch/floor 50%, trail 25% | +9.61% | +8.95% | −4.09% | −2.74% | +0.12% | −3.91% |

C2 was chosen on AMD's Jul–Oct (in-sample there); C3 and C4 are clearly fitted to AMD.

## Finding 6 — Rolling walk-forward: tune on 4 weeks, trade the next month

Each month, the best setting over the previous 20 sessions (≥ 3 trades) is traded the following
month. Fixed settings and the hindsight-best per month for comparison (AMD, pullback longs, 5 bps):

| | 2026 Feb–Sep | months > 0 | 2025 Feb–Dec | months > 0 |
|---|---|---|---|---|
| default (fixed) | +10.37% | 4/8 | −7.86% | 3/11 |
| C1 (fixed) | +7.87% | 4/8 | **+5.36%** | **7/11** |
| C2 (fixed) | **+29.25%** | **8/8** | −1.16% | 5/11 |
| re-tuned monthly | +24.74% | 7/8 | −2.68% | 4/11 |
| re-tuned, strict family (wave ≥ 2, threshold ≥ 1.75, target exits) | +20.29% | 6/8 | −1.59% | 3/11 |
| hindsight best each month (ceiling) | +80.97% | 8/8 | +71.65% | 11/11 |

- **Re-tuning chases the last regime.** In 2026 it moved to the loosest settings after the
  April–June run (AMD +74% / +46% / +13%) and lost **14.65% in July** when AMD fell 18%; strict
  settings came through almost unhurt (C2 +1.83%, default −3.31%). The pick changed every month.
- The hindsight ceiling shows the opportunity exists, but a 4-week lookback cannot find it.

**Triggers** (conditions over the trailing 20 sessions vs the default's next 20 sessions; rolling
daily, overlapping samples):

| Condition | 2026 next-20 mean (% > 0) | 2025 next-20 mean (% > 0) |
|---|---|---|
| strategy made money / lost money | +1.29% (64%) / +1.26% (54%) | −1.06% (28%) / −0.54% (36%) |
| AMD up > 10% / not | +0.85% (52%) / +1.54% (63%) | −1.18% (26%) / −0.37% (38%) |
| daily range above / at or below median | −0.27% (42%) / **+2.82% (76%)** | −0.57% (40%) / −0.89% (26%) |

- The strategy's own recent result predicts nothing.
- **Volatility reversed between years** (calm was good in 2026, slightly worse in 2025); as a
  gate it also removed good trades (C2 2026: +29.25% → +13–21%).
- Only the run-up pattern pointed the same way in both years — tested in Finding 8.

## Finding 7 — AMD, full year 2025 (nothing tuned on it)

AMD 2025: +75.1% buy and hold (122.29 → 214.18), mostly calm (daily range 3–4%; April 6.2%,
Oct–Nov 5–5.6%). 5 bps costs:

| Configuration | Trades | Win | Total | Same in 2026 |
|---|---|---|---|---|
| pullback long, default, target-trail | 62 | 44% | **−7.50%** (3/11 months up) | positive |
| **pullback long, C1** | 23 | 61% | **+5.36%** (7/11) | positive |
| pullback long, C2 | 52 | 54% | −1.16% (5/11) | positive |
| pullback short, default | 49 | 59% | +4.01% | lost |
| box signals, target exit | 169 | 36% | −3.03% | lost |
| long opening drive, held to close | 135 | 32% | +12.05% | lost |
| long opening drive, give-back exit | 135 | 44% | −10.58% | +6.41% (3 months) |
| buy 09:35 every day, held to close | 250 | 23% | +8.24% | — |

The default pullback lost even in AMD's strongest months (June +28%: −2.72%; July +27%:
−0.27%). The direction that works flips by year: pullback shorts and the long drive held to the
close made money in 2025 and lost in 2026.

## Finding 8 — Run-up filter (negative) and pullback longs across years

**Filter:** skip a pullback long when the ticker's return over the previous 20 sessions (close 21
sessions back to yesterday's close) exceeds a threshold. Tested at 5 / 10 / 15 / 20% on AMD, SNDK
and META, 2025 and Jan–Oct 2026, for the default, C1 and C2: at every threshold it improved only
**1–2 of 6** ticker/year cells and lowered the combined total in almost every case. It helps in
losing years (SNDK 2025 default −10.68% → up to +2.88%) but removes the best trades in winning
years (AMD 2026 default +9.91% → about +0.5%). Not useful.

Pullback longs without the filter (target-trail, 5 bps):

| Setting | AMD 2025 | AMD 2026 | SNDK 2025 | SNDK 2026 | META 2025 | META 2026 | Positive |
|---|---|---|---|---|---|---|---|
| default | −7.50% | +9.91% | −10.68% | +16.12% | −2.64% | +2.97% | 3/6 |
| **C1** (`--min-wave-bar-ranges 3`) | **+5.36%** | **+7.91%** | −12.75% | **+13.74%** | −2.34% | **+6.05%** | **4/6** |
| C2 (AMD-tuned) | −1.16% | +28.73% | −5.08% | +8.13% | −7.14% | +3.35% | 3/6 |

All three lost on SNDK and META in 2025. C1 is the most consistent, and the only one positive on
AMD in both years.

## Finding 9 — Deep bounce: buy the first green bar after a deep down wave

`--deep-bounce` (off by default): when a down wave at least `--deep-wave-ratio` (2) × the median
lookback wave size finishes — the Wave module ends it once price bounces 23.6% off the low — the
first green bar fires `bounce long` while price is still below the target. Stop at the wave low −
`--deep-bounce-stop-buffer` (0.1) × wave size; target `--deep-bounce-target-fib` of the wave back
up (0.5 = half way, 1.0 = its start). Mirror for shorts after a big up wave.

AMD deep-bounce longs, box signals off, 5 bps (depth 1.5 / 2 / 3 × target 0.5 / 1.0 × four
exits × with/without a price-above-MA200 filter were tested). Depth 2, target half way:

| Exit | Jul 2 – Oct 2 2026 | Jan 2 – Oct 2 2026 | 2025 |
|---|---|---|---|
| `target` | 20 trades, **80%** win, **+6.09%** | 65, 71%, +14.72% | 78, 58%, **−10.71%** |
| `target-trail` | 20, 80%, +4.26% | 65, 65%, **+19.69%** | 78, 56%, −11.31% |
| `giveback` | 20, 70%, +0.87% | 65, 58%, +5.80% | 78, 62%, −5.16% |
| `eod` | 20, 45%, −3.15% | 65, 51%, +21.37% | 78, 40%, −14.57% |

- **All 24 setting/exit combinations lost on 2025**, even at 56–62% win rates: the stop sits
  well below the entry while the half-way target is close, so losers outweigh winners.
- The **MA200 trend filter** cut the 2025 loss (best −1.01%) but removed most of the 2026 gain
  (4 trades in the last 3 months).
- Depth 1.5 is too loose (more trades, worse results); depth 3 too rare (8 trades in 3 months).

## Finding 10 — Combining the setups that worked for AMD in 2026

Box signals off, 5 bps, each signal traded independently (overlapping positions allowed; "max
open" is the most trades open at once). Wave size 3 is shared by every setup in the run.

| Setup | Exit | Jul–Oct 2026 | Jan–Oct 2026 | 2025 | Max open (2026) |
|---|---|---|---|---|---|
| deep bounce | target-trail | +4.26% | +19.69% | −11.31% | 1 |
| pullback long | target-trail | +4.36% | +9.91% | −7.50% | 1 |
| pullback long, wave 3 (C1) | target | +4.55% | +10.66% | **+5.54%** | 1 |
| long opening drive | target-trail | +0.89% | **−8.30%** | −11.17% | 1 |
| **deep bounce + pullback** | **target-trail** | **+8.62%** | **+29.59%** (110 trades, 62% win) | −18.81% | 2 |
| deep bounce + pullback | target | +10.26% | +23.99% | −17.99% | 2 |
| deep bounce + pullback, wave 3 | target | +7.96% | +19.78% | −9.39% | 2 |
| bounce + pullback + drive | target-trail | +9.51% | +21.29% | −29.98% | 3 |
| bounce + pullback + drive, wave 3 | target | +13.03% | +6.53% | −12.63% | 2 |

- **Deep bounce + pullback long is the best AMD 2026 combination.** The two rarely overlap (10
  of 110 trades), so the total is close to the sum of its parts (+19.69% + +9.91%).
- **The long opening drive lost over 2026** (−13.52% with `target`, −8.30% with `target-trail`)
  and drags every combination it joins — its 3-month gain was not representative.
- **Every 2026 winner loses on 2025.** Combining doubles the 2026 gain and roughly doubles the
  2025 loss: the setups are all dip-buying, so they share the same good and bad years.
- The only AMD setting positive in both years is still **C1 alone** (`target` exit: +10.66% in
  2026, +5.54% in 2025).

Run the best 2026 combination:

```bash
python -m alpha_tech_tracker.op_momentum_strategy.analysis_scripts.wave_risk_reward_backtest \
  --tickers AMD --start 2026-01-02 --end 2026-10-02 --no-box-signals \
  --deep-bounce long --wave-pullback long --exit target-trail --cost-bps 5
```

## Recommendations

1. **Choose tickers before tuning settings.** The same configuration ranges from +156.66% (SNDK)
   to −8.74% (META). Next: run the 2026 backtest across the cached tickers and check whether the
   results line up with average daily range or trend (for example distance above the daily MA)
   — a candidate ticker-selection rule.
2. **Treat per-ticker settings with suspicion.** On META, 3-month tuning barely predicted the
   previous 6 months (correlation +0.26). Any per-ticker setting needs an out-of-sample check.
3. **The regime switch may need to be per ticker** — it helped QQQ + SNDK and hurt META.
4. **AMD in a 2026-style year (sharp drops that recover):** deep bounce + pullback long,
   `--no-box-signals --deep-bounce long --wave-pullback long --exit target-trail` (+29.59% over
   Jan–Oct 2026). It is year-dependent (−18.81% on 2025) — size it accordingly and drop the long
   opening drive.
5. **For AMD-like names (impulse waves, few tight boxes)** the wave pullback long is the best
   option tested, but use **C1** (`--no-box-signals --wave-pullback long
   --min-wave-bar-ranges 3 --exit target-trail`) — the only setting positive on AMD in both 2025
   and 2026. Expect a small edge with few trades.
6. **Don't re-tune monthly, and don't loosen settings after a run-up** (Finding 6). Fixed strict
   settings beat 4-week re-tuning in both years.
7. **Triggers tested and rejected:** the strategy's own recent result, a volatility gate, and the
   run-up filter (Findings 6 and 8).
8. **Still untested:** a bear-market year for SNDK-like names, costs other than 5 bps, a
   one-position-at-a-time rule for combined setups, and a regime signal that tells a 2026-style
   year (dips recover) from a 2025-style year (dips don't) in advance.

## Reproduction

```bash
cd /Users/victorhuang/work/alpha_tech_tracker
source ~/.pyenv/versions/alpha_tech_tracker/bin/activate
export PYTHONPATH=$PWD

# Findings 1 and 2 (swap SNDK for META; add --opening-drive long|both and --exit giveback|eod)
python -m alpha_tech_tracker.op_momentum_strategy.analysis_scripts.wave_risk_reward_backtest \
  --tickers SNDK --start 2026-01-02 --end 2026-10-02 \
  --opening-drive long --exit eod --cost-bps 5

python -m alpha_tech_tracker.op_momentum_strategy.analysis_scripts.wave_risk_reward_backtest \
  --tickers META --start 2026-01-02 --end 2026-10-02 \
  --opening-drive long --exit eod --cost-bps 5

# Finding 3: one grid point, e.g. the defaults with the regime switch off, per window
python -m alpha_tech_tracker.op_momentum_strategy.analysis_scripts.wave_risk_reward_backtest \
  --tickers META --start 2026-07-02 --end 2026-10-02 --regime-switch off --exit eod --cost-bps 5
```

The full 432-setting grid and the buy-every-morning / green-first-bar baselines came from
one-off scripts that were not committed; the grid and split above are enough to rebuild them on
top of `TradeSimulator` and `apply_costs` in the backtest module. Running a window on its own
(as in the last command) loads its own warm-up; that command reproduces the split-run numbers
exactly (110 trades, +0.80%), but other settings may differ slightly.

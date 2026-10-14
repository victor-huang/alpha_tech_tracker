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
- **AMD 2025 works the other way (Finding 11):** shorting the top of a big up wave
  (`--deep-bounce short`) made +9.11% on 2025 and lost 14–31% in 2026. In 2025 almost all of
  AMD's +77% came overnight (in-session only +6%), so intraday rallies faded; in 2026 the session
  itself rose 86%, so dips recovered. Trailing in-session drift is a candidate regime switch.
- **No indicator picks the setup in advance (Finding 12):** daily-trend rules, 12 intraday
  indicators (~2,500 rules) and rotating by the setups' own recent results were chosen on 2025 and
  failed on 2026, or only worked in a narrow pocket. Rotating among the five wave setups with a
  slow rule was positive in both years, but no better than C1 alone in 2025.
- **The overnight hold is the biggest find (Finding 13):** buy the 15:55 close, sell the next
  open (`--overnight-hold`). On AMD with the daily-MA200 filter: +63.73% in 2025 and +43.73% in
  2026, and it sat out most of 2022 (+1.34%). Across 24 tickers it was positive on 19 of 24 in
  2025 and 18 of 23 in 2026 (median +23.5% / +10.7%, every day, 5 bps).
- **Which tickers to hold overnight (Finding 14):** rank monthly by 120-session total return
  (momentum) and hold the top 3–5. Chosen on 2025 (+60.52% vs +26.45% for all 24 tickers) and it
  held on 2026 (+67.86% vs +16.99%). A ticker's own overnight history does not predict its next
  overnight returns (correlation +0.01).
- **A per-ticker setup scan (Finding 15):** `wave_risk_reward_scan.py` backtests every setup on
  a ticker, picks exits on the first half of the period, checks them on the second, and recommends
  the setups that made money in both. AMAT's recommendation changed with its regime (overnight
  hold when its gains came overnight, intraday longs when they came in-session).
- **Back to 2020 (Findings 21–24, split-adjusted bars):** the weekly top-3 rotation that worked in
  2025–26 made only +3.3% over 2020–24 (all types) and about +12% (R1) on the allocated capital.
  Every short, box and bounce setup lost money in almost every year; only overnight holds and drive
  long made money, and both are long exposure. A choppy-ticker filter, a 10-session track-record
  filter and an MA50 gate did not help (Findings 20–21).
- **What does carry forward (Findings 22–24, chosen on 2020–22, checked on 2023–26):** overnight
  MA200 on the 2 strongest tickers (furthest above their 200-day MA and up most today), only when
  QQQ is above its 200-day MA, plus drive long on the 2 most volatile tickers that trigger. Up in 6
  of 7 years on four $10k slots (2022 −7%, 2021/2023/2025 +12–18%, 2024 +41%, 2020 +81%,
  2026 YTD +93%, +69% without MRNA), worst drawdown −$9.9k. **But see Finding 30: these numbers
  are on a ticker list chosen with hindsight.**
- **Without hindsight in the ticker list the edge mostly disappears (Finding 30):** on the actual
  Nasdaq-100's top 8 by the previous month's return, the same strategy made +70% compounded Jan 2020 –
  Oct 2026 (QQQ +253%, SPY +142%), vs +586% on the research list. Its advantage is defensive (2022
  −2.5% vs QQQ −33%); no setup earns in a bear market, so stepping aside is the defense (Finding 29).
- **The intraday clock is the same every year since 2020 (Finding 26):** the opening run tops at
  10:00, the morning low lands at 10:35–10:45 and its rebound tops at 11:35–11:45; 72–76% of the
  day's strongest up waves start before 11:30. Drive long's 65% failure rate in 2026 is normal, and
  a bad week does not predict the next (Finding 25).
- **But the clock can't be traded from a confirmed turn (Finding 27):** the morning-dip "second wave"
  entry (`--second-wave long`) lost in every form tried, and selling drive long earlier than the close
  always did worse.
- **Drive long's stop (Finding 28):** re-entering after the stop-out doesn't pay; the first bar's low is
  the right stop on the 2 most volatile tickers, while a 2% stop suits drive long on every signal
  (+28% profit in 2023–26 at about the same drawdown). Trading it only while the ticker is above its
  daily MA20 cut drawdowns on 22 of 28 tickers but total profit from +474% to +178%.

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

## Finding 11 — Shorting the top of a big up wave, and why AMD's years are opposites

`--deep-bounce short`: after an up wave at least `--deep-wave-ratio` × the median lookback wave
size finishes, short the first red bar; stop at the wave high + 0.1 × wave size, target
`--deep-bounce-target-fib` of the wave back down. Same grid as Finding 9 (depth 1.5 / 2 / 3 ×
target 0.5 / 1.0 × four exits × with/without a price-below-MA200 filter), box signals off, 5 bps.
Depth 2, target half way:

| Exit | **2025** | Jan 2 – Oct 2 2026 | Jul 2 – Oct 2 2026 |
|---|---|---|---|
| `target` | 81 trades, 70% win, **+3.99%** | −13.88% | −0.53% |
| `target-trail` | 81, 68%, **+9.11%** | −20.90% | −4.06% |
| `giveback` | 81, 70%, **+7.08%** | −20.61% | −4.87% |
| `eod` | 81, 53%, **+4.34%** | −27.12% | −4.83% |

- All 8 depth-2 setting/exit combinations were positive on 2025 (target 1.0: +3.14% to +6.28%);
  depth 3 smaller (+1.2% to +3.6%); depth 1.5 lost.
- It is the mirror of the deep-bounce long: heavy losses in 2026 (−14% to −31% over Jan–Oct).
- Requiring a downtrend (price below the 5-min MA200) made it worse: the rallies worth fading in
  2025 happened while AMD trended up.

### Overnight vs in-session returns

| AMD | Total | Overnight (prior close → open) | In-session (open → close) | Dips ≥ 2% that recovered over half | Rallies ≥ 2% that gave back over half |
|---|---|---|---|---|---|
| 2025 | +77% | **+68%** | **+6%** | 32% of 98 | 39% of 98 |
| Jan–Oct 2026 | +196% | +59% | **+86%** | 46% of 76 | 35% of 98 |

In 2025 almost all of AMD's gain came **overnight**; within the session price went roughly
nowhere, so intraday rallies faded and dips kept falling. In 2026 buyers lifted the stock
**during** the session, so dips recovered. Every setup here trades only within the session, which
is why dip-buying and rally-fading swap places between the two years.

### Working AMD setups by year type (5 bps)

| Year type | Setup | Result |
|---|---|---|
| **2025-style** (gains overnight, flat in-session) | deep-bounce short, depth 2, `target-trail` | **+9.11%** (2025) |
| | long opening drive, held to the close | +12.05% (2025) |
| | pullback short, default | +4.01% (2025) |
| **2026-style** (strong in-session drift) | deep bounce long + pullback long, `target-trail` | **+29.59%** (Jan–Oct 2026) |
| **Both years** | pullback long C1 (`--min-wave-bar-ranges 3`) | +5.36% (2025), +7.91% (2026) |

**Candidate regime switch (untested):** in-session drift is measurable in real time — e.g. the sum
of open-to-close returns, or the dip-recovery rate, over the trailing 20 sessions. Trade the long
dip-buying setups when it is positive and short the tops of big up waves when it is flat or
negative. Unlike the triggers rejected in Findings 6 and 8, it has a mechanism behind it; it still
needs a point-in-time backtest across both years.

Run the 2025-style setup:

```bash
python -m alpha_tech_tracker.op_momentum_strategy.analysis_scripts.wave_risk_reward_backtest \
  --tickers AMD --start 2025-01-02 --end 2025-12-31 --no-box-signals \
  --deep-bounce short --exit target-trail --cost-bps 5
```

## Finding 12 — Picking the setup in advance: indicators and rotation (negative)

The question: can something known each morning tell a 2026-style day (dips recover → long
setups) from a 2025-style day (rallies fade → short big-wave tops)? Long side = deep bounce long +
pullback long; short side = `--deep-bounce short`; target-trail, 5 bps. Rules were chosen on 2025
and tested unchanged on Jan–Oct 2026; each indicator uses data up to the previous close.

**Daily trend** (above daily MA20 / 50 / 200, MA20 and MA50 slope, MA20 > MA50, full stack, 20-day
return, 20-day in-session drift; singles and AND/OR pairs, 243 rules):

| | 2025 | 2026 |
|---|---|---|
| short Jan–May, long Jun–Dec (switch on the daily trend) | **−15.26%** | — |
| "above daily MA200 → long, else short" | −13.69% | +29.59% |
| 20 best rules on 2025 | +3.3% to +6.9% | **1 of 20 positive**, median −11.74% |
| MA20 > MA50 > MA200 and 20-day return up → long, else short | +3.27% | +11.40% |

In 2025 the long setups lost every month after AMD turned up (Jun–Dec −14.66%) while the short
made +9.70% in that uptrend — the daily trend shows which way AMD moves across days, not whether
intraday dips recover.

**Intraday indicators** (trailing 20 sessions: dip-recovery rate, rally-fade rate, in-session vs
overnight return, close location, 5-min autocorrelation, closes above VWAP, gap-fill rate, ADR,
relative strength vs QQQ, QQQ above MA50, QQQ in-session drift, setup momentum; ~2,500 rules):
the 20 best on 2025 were **all negative on 2026** (median −16.02%). The one survivor, "5-min
autocorrelation > 0 → long, else short" (+8.31% / +16.63%), was fragile: neighbouring
cutoffs/lookbacks often lost in one year, the 10-session lookback lost in 2025 at every cutoff,
SNDK lost in 2025 at every setting and META in most.

**Rotation by the setups' own recent results** (shadow-trade every setup; trade those with
traction, using only trades closed before the day; every variant reported, none chosen):

| Universe | 2025 | 2026 |
|---|---|---|
| all 10 setups (box, drive, pullback, bounce, both sides) | 11 of 12 rules negative | mixed |
| five wave setups (bounce long/short, pullback long/short, C1) | 3 of 12 positive | **12 of 12 positive** (+7.23% to +28.84%) |
| best slow rules, five wave setups | top 2 by trailing 40 sessions +2.04%; top 1 by 60 sessions +2.62%; last 10 trades +1.53% | +12.33%; +9.36%; +7.23% |

Rotation catches a strong edge (2026's deep-bounce long) but not a small, steady one (2025's
short): normal losing streaks switch it off. Each setup's edge persisted for several quarters,
then flipped around the turn of the year — a trailing rule sees the flip about a quarter late.

## Finding 13 — Overnight hold: buy the close, sell the next open

`--overnight-hold always|ma200|ma20-ma200|ma50-rising`: buy the session's 15:55 bar close
(market-on-close), sell the next session's first bar open (market-on-open), no stop or target.
Filters use daily moving averages of session closes including today's.

**Why:** every other setup here is flat by the close, and AMD's return often comes overnight:

| AMD | Buy and hold | Overnight part | In-session part |
|---|---|---|---|
| 2022 | −55% | −22% | −42% |
| 2023 | +124% | +21% | **+89%** |
| 2024 | −10% | **+64%** | −46% |
| 2025 | +77% | **+68%** | +6% |
| Jan–Oct 2026 | +196% | +59% | **+86%** |

**AMD, 5 bps:**

| Filter | 2022 | 2023 | 2024 | 2025 | Jan–Oct 2026 | Total |
|---|---|---|---|---|---|---|
| every day | **−31.87%** | +5.02% | +44.23% | +51.28% | +43.73% | +112.39% |
| **close above daily MA200** | **+1.34%** (45 trades) | −3.89% | +13.41% | **+63.73%** | **+43.73%** | **+118.32%** |
| close above MA20 and MA200 | −14.17% | +0.48% | +17.67% | +60.93% | +35.23% | +100.14% |
| daily MA50 rising | −23.82% | +13.49% | +9.38% | +69.24% | +37.80% | +106.09% |

The MA200 filter sat out most of the 2022 bear market at the cost of a smaller 2024 (AMD spent
much of 2024 below its MA200 while still gaining overnight). Worst single nights: −6% to −11%.

**24 tickers, 5 bps** (AMD APP ARM AVGO COIN CRWD DDOG HOOD IONQ JPM LLY LUNR META MU NVDA OKLO
PLTR QCOM QQQ RDDT RKLB SNDK SNOW TSLA):

| Filter | 2025: positive / median | Jan–Oct 2026*: positive / median / worst ticker |
|---|---|---|
| every day | **19 / 24**, **+23.51%** | **18 / 23**, **+10.70%**, APP −62.42% |
| close above daily MA200 | 18 / 24, +22.55% | 16 / 23, +3.69%, TSLA −17.31% |
| daily MA50 rising | 20 / 24, +22.64% | 13 / 23, +1.00%, RDDT −24.91% |

\* CRWD excluded in 2026: a 4-for-1 split on 2026-07-02 (772.45 close → 191.44 open) shows as a
−75% night because the cached 5-min bars are not split-adjusted.

- **Every day was positive in both years on 14 tickers** (AMD, AVGO, DDOG, HOOD, IONQ, META, MU,
  NVDA, OKLO, PLTR, QQQ, RKLB, SNDK, SNOW); with the MA200 filter on 12. Biggest: SNDK (+92% /
  +106%), MU (+73% / +97%), AVGO, APP 2025, OKLO, AMD.
- **The filter trades upside for protection.** In 2026 MA200 cut big losers (APP −62% → −8%,
  COIN −29% → +7%, TSLA −26% → −17%) but also skipped winners still gaining overnight while below
  their MA200 (OKLO, IONQ, RKLB, SNOW), so its median fell to +3.69%.
- **Consistent losers** are tickers whose gains come in-session: CRWD and LLY 2025, QCOM and ARM
  2025, JPM — the in-session / overnight split decides it, as on AMD.

**Caveats:** overnight gap risk (single nights −10% to −36%, e.g. LUNR −35.8%, IONQ/OKLO −22%),
earnings nights (no earnings calendar here), market-on-close / market-on-open fills may cost more
than 5 bps, unadjusted data breaks around splits, and the long-only overnight effect is a known
anomaly that can fade. It has also only been tested in 2022–2026.

```bash
python -m alpha_tech_tracker.op_momentum_strategy.analysis_scripts.wave_risk_reward_backtest \
  --tickers AMD --start 2025-01-02 --end 2025-12-31 --no-box-signals --overnight-hold ma200 --cost-bps 5
```

## Finding 14 — Which tickers to hold overnight: momentum

Monthly walk-forward on the 24 cached tickers, Jan 2025 – Sep 2026: at each month start, rank
tickers using only data up to the previous session, hold the picks overnight every night of the
month (15:55 close → next open, 5 bps per night), equal weight. Nights with |log gap| > 0.5 are
treated as splits (flat). Totals are the average per ticker held, summed over the months.
Baseline — all 24 tickers every night: **+26.45% (2025), +16.99% (Jan–Sep 2026)**.

| Ranked by (trailing) | Picks | 2025 | 2026 | Beats all 24 in both |
|---|---|---|---|---|
| **total return, 120 sessions (momentum)** | **top 3** | **+60.52%** | **+67.86%** | **yes** |
| total return, 120 sessions | top 5 | +33.09% | +51.98% | yes |
| total return, 60 sessions | top 5 | +40.62% | +38.29% | yes |
| total return, 60 sessions | top 10 | +35.07% | +33.63% | yes |
| overnight return, 60 sessions | top 3 | +41.01% | +25.88% | yes |
| overnight return, 120 sessions | top 3 | +7.18% | +68.20% | no |
| overnight minus in-session, 60 / 120 sessions | top 3–10 | +9.6% to +22.9% | +3.9% to +51.1% | mostly no |
| close above daily MA200 | all that qualify | +23.27% | +28.30% | no |

- **Every momentum variant beat holding all tickers in both years**, and the bottom-ranked
  tickers did much worse (120-session top 3 vs bottom 3: +60.52% vs +11.50% in 2025, +67.86% vs
  +4.27% in 2026). The best rule on 2025 was also the best on 2026.
- **A ticker's own overnight history does not select:** overnight returns in consecutive
  60-session blocks are uncorrelated (+0.01), and "gains come overnight" picked worse tickers than
  its bottom ranks.
- **Top-3 picks:** 2025 mostly OKLO, HOOD, RKLB, PLTR; 2026 mostly SNDK (11 of 21 months) and MU
  (10). 14 of 21 months positive; worst month −10.4% (Feb 2026), best +29.9% (Oct 2025). Top 5:
  also 14 of 21, worst −12.4% (LUNR −49.5% in March 2025).
- **Caveat — biased universe:** the 24 tickers were cached because they were hot names in
  2025–26, so momentum is picking from a list already full of winners. The real test is a broad
  universe (e.g. the Nasdaq-100), not yet cached.

## Finding 15 — Finding the setups for a new ticker: `wave_risk_reward_scan.py`

The scan backtests every setup on its own over a period split in two halves by session count:
box breaks, box fades, gap signals, drive long/short, pullback long/short, pullback long C1, deep
bounce long/short, overnight always / ma200. Each intraday setup's exit is chosen on the first
half and checked on the second. Recommended = positive in both halves with ≥ 5 trades in each
(one per overlapping family, by first half); the combination's result is the sum, since the setups
trade independently. 5 bps.

| Ticker, period | Overnight / in-session (1st half, 2nd half) | Recommended (exit) | Combined 1st / 2nd half |
|---|---|---|---|
| AMD, 2025 | +2% / +12%, +65% / −6% | pullback long C1 (target), bounce short (target-trail), overnight ma200 | +14.35% / +64.03% |
| AMAT, Oct 2025 – Oct 2026 | +28% / +25%, +60% / −3% | drive short (eod), pullback long C1 (target), overnight always | +27.12% / +54.61% |
| AMAT, 2025 | −1% / +19%, −2% / +37% | box break (giveback), drive long (giveback), pullback long (eod), overnight ma200 | +14.70% / +14.60% |
| SNDK, Oct 2025 – Oct 2026 | +134% / +148%, +84% / +33% | drive long (eod), overnight always, bounce long (eod), drive short (target), box break, box fade, box gap, pullback long C1 (giveback) | +228.09% / +169.05% |
| SNPS, Oct 2025 – Oct 2026 | −9% / −11%, +25% / −1% | bounce long (target-trail), box gap (eod), pullback long C1 (eod) | +15.93% / +5.79% |
| MSFT, Oct 2025 – Oct 2026 | −11% / −19%, +12% / +23% | box fade (eod), box gap (target), pullback long C1 (target) | +4.42% / +10.91% |
| META, Oct 2025 – Oct 2026 | −5% / −16%, +16% / +10% | **none** | — |
| LLY, Oct 2025 – Oct 2026 | +3% / +10%, +40% / −13% | **none** (overnight −1.32% / +28.70%) | — |

- On AMD the scan independently recovers the setups found by hand in Findings 7–13.
- **AMAT's recommendation changed with its regime:** in the last 12 months its gains came
  overnight (+60% in the second half vs −3% in-session) and the overnight hold led; in 2025 its
  gains came in-session (+19% / +37%) and the intraday long setups led. Re-run the scan as the
  regime changes; the overnight / in-session line in the report shows which way a ticker leans.
- **Pullback long C1 was recommended for 5 of the 7 tickers** (AMD, AMAT, SNPS, MSFT, SNDK) — the
  most portable intraday setup, though it trades rarely and earns modest amounts.
- **The overnight hold qualified only where gains came overnight in both halves** (SNDK, AMAT, AMD
  2025). MSFT, SNPS, META and LLY had negative overnight returns in Q4 2025 – Q1 2026, consistent
  with Finding 14: they would not have ranked near the top on momentum then.
- **SNDK's +228% / +169% adds eight setups that are all long the same rally** — not diversified;
  the core is the long opening drive held to the close (+88.06% / +74.76%) and the overnight hold
  (+81.53% / +64.24%).
- **META and LLY have no setup that made money in both halves** — a valid answer: don't trade them
  for now; re-scan as they change (LLY's overnight hold turned strongly positive in the second half).
- Limits: one split per run (two halves), results add up only if each setup gets its own capital,
  and the setups themselves were developed on AMD/SNDK/META data.

```bash
python -m alpha_tech_tracker.op_momentum_strategy.analysis_scripts.wave_risk_reward_scan \
  --tickers AMAT --start 2025-10-01 --end 2026-10-02
```

## Finding 16 — Earnings calendar: skip the night into the release

`--earnings skip` (see the guide's Earnings calendar section) drops trades that carry an earnings
reaction: the overnight hold entered the session before the release gap, and intraday signals on
the reacting session. Run on the 8-ticker setup report, 2026-07-02 .. 2026-10-02, 5 bps
(`backtest_result/wave_setups/2026-07-02_2026-10-02{,_earnings-skip}/`). One release per ticker
in the window:

| Ticker | Reaction session (close vs prior close) | Overnight into it | Overnight always: all → skip |
|---|---|---|---|
| AMD | 2026-08-05 −8.42% | −7.94% | +7.43% → **+15.37%** |
| MRNA | 2026-07-31 −5.43% | −0.10% | +45.58% → +45.68% |
| META | 2026-07-30 −8.17% | −10.51% | +7.65% → **+18.16%** |
| SNPS | 2026-08-27 +13.37% | +2.27% | +19.70% → +17.43% |
| MSFT | 2026-07-30 +15.06% | **+11.77%** | +5.78% → −5.99% |
| MDB | 2026-09-02 −13.78% | −13.20% | −47.00% → −33.79% |
| SPOT | 2026-08-04 −1.74% | −4.10% | −15.74% → −11.65% |
| SPCX | 2026-08-05 −14.02% | −10.83% | −20.33% → −9.50% |

- **The night into earnings is a coin flip with a fat tail:** 6 of 8 lost (−0.1% to −13.2%),
  2 won (MSFT +11.8%, SNPS +2.3%). Net across the 8: −32.6% on 8 nights, versus the ordinary nights
  that carry the overnight edge on AMD, META and MRNA.
- **Skipping helped 6 of 8 tickers.** It is a risk filter, not an edge: one night decides the
  outcome either way (MSFT turns from +5.8% to −6.0% by skipping its one good night).
- **It does not fix MDB.** MDB's −24.1% gap on Sep 28 was not an earnings release; the overnight
  hold still loses −33.8% with earnings skipped. Ticker selection (Finding 14) is still the main
  guard.
- **Intraday setups barely change:** one trade per ticker per setup at most moves (e.g. AMD drive
  long −1.26% → +1.56%, MDB C1 +2.24% → +3.98%).
- Sample: one quarter, 8 releases. Before relying on it, rerun over a year
  (`--earnings only` shows the earnings trades alone).
- **Made the default for the overnight hold** (2026-10-05): it skips the night into a release
  unless `--overnight-include-earnings` is given. Intraday setups are unchanged unless
  `--earnings skip`. Overnight results in Findings 13–15 were run before this default and
  include the earnings nights.

## Finding 17 — Rotating setups forward: how often to re-pick (walk-forward, no hindsight)

`analysis_scripts/wave_setup_walk_forward.py`. Each ticker trades the top 3 setups of a trailing
look-back (fixed exits, one per family, money-makers only), re-picked every block; $10k per ticker
in three $3,333 sleeves, fixed size, 5 bps. Picks only use trades entered before the block. A
setting is only trusted when it was chosen on an earlier calibration period.

**2-week rotation, SNDK MDB GOOGL APP, Jul 6 – Oct 6 2026:** +$1,293 (+3.2% of $40k), against
+$4,847 for the hindsight top 3 and −$5,495 buy & hold. SNDK alone +$2,035; MDB and APP negative.
A setup's last 2 weeks barely predicted its next 2.

**Look-back x hold sweep (same window, 12 settings):** −$783 to +$1,293, and every setting lost
money in the second half (after Aug 20). Choosing the best one afterwards is hindsight: picked on
Feb 17 – Jul 2 instead (24 settings), the winner (10-session look-back, 20-session hold) made
+$1,214 in the test, 14th of 24 (median +$1,374).

**Keep a setup until it loses over 2 weeks** (2-month look-back, user-defined in advance):
+$1,777 on Feb 17 – Jul 2 and +$1,805 on Jul 6 – Oct 6 (+4.5% of $40k), vs re-picking every 2 weeks
on the same look-back (+$2,573 / +$1,496). The order of the rules flips between periods — noise.

**3-month look-back, how often to update** (calibration Sep 2 2025 – Jul 2 2026; test Jul 6 – Oct 6):

| Update | Calibration | Test |
|---|---|---|
| every week (chosen on calibration) | +$12,157 | +$1,081 |
| every 2 weeks | +$11,129 | +$956 |
| every 4 weeks | +$11,929 | +$804 |
| keep until a 2-week loss | +$10,691 | +$1,096 |
| keep until a 4-week loss | +$10,023 | +$1,068 |
| every 8 weeks | +$9,605 | +$350 |
| every 3 months | +$10,388 | −$261 |
| every 6 months | +$7,751 | −$85 |

**Decay of a pick** (average $ per ticker per 2 weeks after the pick): calibration +$132, +$113,
+$121, +$95, +$98, +$101 over 12 weeks; test +$60, +$86, +$43, then −$69, −$56, −$144. Picks went
stale after 4–6 weeks in the test, so update every 1–2 weeks (it costs little when nothing changes).

## Finding 18 — What picks setups that keep working (selection research, no hindsight)

`analysis_scripts/wave_setup_selection_research.py`. Every week, for each ticker x setup: track-record
measures and ticker / QQQ conditions known before the week, and the setup's next-week result.
Calibration Sep 2 2025 – Jul 2 2026 (42 weeks), test Jul 6 – Oct 6 2026 (13 weeks); every result
also with trades capped at ±10% (AMD's Oct 2025 and MRNA's Aug 2026 news gaps). Three baskets:
10 tickers with SNDK, 10 without SNDK (TSLA instead), and 20 tickers (MDB GOOGL APP AMD META MSFT
AMAT SPOT MRNA TSLA QQQ SNPS LLY COIN SHOP CRWV CRM NVDA PLTR AVGO; SNDK excluded as an outlier,
SPCX dropped because the symbol changed from an ETF to a new stock in 2026, CRWD for its split).

**Ranking measure:** the plain 3-month total beat recency-weighted, consistency, risk-adjusted
(t-stat), win rate, profit factor and "positive on both 1 and 3 months" — in both periods, raw and
capped, in all three baskets.

**Setup types:** short and box setups lost money the following week on average, in both periods,
even with a positive 3-month record (e.g. 10 tickers with SNDK: −0.25% / −0.10% per setup-week for
shorts, −0.13% / −0.16% for box). Dropping them (R1) beat keeping them (R0) everywhere:

| Basket ($10k per ticker, weekly) | R0 calibration / test | R1 calibration / test | R1 test capped |
|---|---|---|---|
| 10 with SNDK | +$13,316 / +$7,269 | +$17,635 / +$7,875 | +$4,630 |
| 10 without SNDK | +$4,861 / +$5,647 | +$8,386 / +$5,701 | +$2,625 |
| 20 tickers | +$10,681 / +$8,294 | +$13,178 / +$9,127 | +$5,622 |

On 20 tickers R1 was up in all 3 test months and on 14 of 20 tickers in each period.

**Conditions (switch signals):**
- A setup's own 3-month record is the most consistent: overnight holds with a positive record
  +0.67% vs +0.11% the next week (calibration) and +0.34% vs −0.32% (test, without SNDK).
- Long setups' edge came mostly from SNDK; without it they were flat in calibration.
- Ticker or QQQ trend flips sign for overnight holds between periods (good on strong tickers in
  calibration, bad in the test) — not a usable switch.
- Rejected rules: long setups only above MA50 (R2) — better in calibration, worse in the test, in
  all three baskets; pausing a setup type after a losing month across tickers (R3) — worst rule
  every time, because overnight losing streaks reverse quickly (−147 in March then +135 in April,
  −104 in July then +214 in August, summed 1-month results).

**Ticker momentum on top of R1** (keep the top 3 / 5 tickers by 20/60/120-session return, $10k per
kept ticker): always about doubles the calibration return on capital used, but the test does not
agree — on 10 tickers the calibration pick beat "all tickers" (11.1% vs 5.7% raw), on 20 tickers it
lost (2.4% vs 4.6% raw), and the best look-back changes between periods. It also leaves most of
the capital idle (+$720 vs +$9,127 on 20 tickers in the test). Not adopted.

**Overnight short** (short the 15:55 close, cover at the next open, mirror of the overnight hold):
lost on 11 of 11 tickers in calibration (−628% summed) and 8 of 11 in the test (−133%); only
shorting when the long overnight hold lost over 3 months still lost (−100% / −10%). Not added.

**Recipe (R1):** every week, rank each ticker's long setups (drive long, pullback long, C1, bounce
long) and overnight holds by their last-3-month total, trade the top 3 that are positive with at
least 3 trades (one per family). About +0.7% a month on the full capital in calibration and
+0.9–1.5% a month in the test on 20 tickers; most of the return comes from whichever tickers trend.

## Finding 19 — Betting against losing setups: reversals and the drive fade (negative)

**Reversing setups that lost money.** A reversed setup takes the opposite side at the same entry and
exits at the same moment (net % = −original − 0.10% for costs on both sides). Added to the weekly
ranking (20 tickers, Finding 18 data) as a candidate whenever a setup's 3-month total was ≤ −X%,
the reversed picks lost money at every threshold, in both periods, raw and capped:

| Ranking | Reverse below | Calibration | Test | Reversed picks (calibration / test) |
|---|---|---|---|---|
| all setups | — | +$10,449 | +$8,294 | — |
| | −10% | +$4,290 | +$4,805 | −$5,281 / −$2,919 |
| R1 | — | +$12,962 | +$9,072 | — |
| | −10% | +$6,370 | +$5,676 | −$5,236 / −$2,862 |

Setups down >10% over 3 months earned about +0.4% the next week on average (they bounced), so the
reversal lost about 0.5% per pick-week. FN's opening drive long (−23.4% Jul 10 – Oct 7 2026)
illustrates both problems: most of the loss came in July, before a −10% rule could see it
(reversing from the first eligible week, Aug 10, made +3.7%, not the hindsight +20.2%), and the plain
mirror of a drive trade has no stop — it caps the win at the original's stop and takes the full
move on trend days (Oct 6: −10.5% in one week).

**The drive fade** (`--drive-fade`, the opening drive reversed with its own stop: short after a green
first bar, stop above its high + 0.1 × its range, target its low; mirror for red bars). On 21 tickers
(the Finding 18 pool + FN), Jun 2025 – Oct 2026, target exit: drive fade short −299.8% over 3,441
trades and drive fade long −207.4% over 3,668, each positive on 3 of 21 tickers. A positive 3-month
record did not help (next week −0.25% calibration, −0.23% test). Added to the ranking it lowered
every result (R0 test +$9,272 → +$7,484; R1 +$10,005 → +$9,316).

**Drive fade variants** (`analysis_scripts/wave_drive_fade_variants.py`, 68,340 simulated trades:
4 exits × 3 stop cushions × 18 filters known at 9:35, calibration Sep 2 2025 – Jul 2 2026, test
Jul 6 – Oct 6 2026). Every exit and stop lost in both periods without a filter (best: −224.9% /
−147.6%); a wider stop or holding to the close was worse. Of 168 variants with ≥ 150 calibration
trades, 3 were positive in calibration and none in the test (best: fading gaps ≥ 0.5 ADR, +36% →
−75%). Filters tried: stretch from the 5-min MA200 (5/10/20 bar ranges), correction (below MA50,
above MA200), downtrend, with / against the daily trend, 20-day return, big first bars, gaps.
Correction + MA200 stretch ≥ 10 was the only one positive in both periods (+22.1% on 104 trades,
+4.6% on 41) — too few trades to trade; worth re-checking on a later window. "With the daily trend
+ stretch" lost in calibration and won in the test: regime-dependent, like the overnight hold.

**Conclusion:** the opening move tends to continue, and a setup's losing streak tends to end
rather than continue — betting against either did not work out of sample. The drive fade stays in
the code but is opt-in (`OPT_IN_SETUPS`): the setup report, scan and `config --refresh` skip it
unless named with `--setups`, so a lucky 3 months cannot put it into the monitor's top 3.

## Finding 20 — Drive long vs drive short as a trend read, and the choppy-ticker filter (negative)

Studies run 2026-10-09/10 on the 21 tickers of the two setup tapes (the EC2 seven, the 13-ticker set
and LLY), drive long and drive short held to the close, 5 bps.

**Live week check (Oct 5–9 2026).** The EC2 monitor's drive alerts for Oct 7–9 summed to +20.7%
against +21.2% in the backtest of the same days; the gap is the 15:45 reference price used for the
MOC sell alert. Over the week the 13 tickers whose top 3 included a drive setup made +31.3% (52
trades, 42% winners) vs +29.9% for every drive trade on all 21 (105 trades).

**Long minus short P&L reads the in-session trend.** Over Sep 21 – Oct 9 2026 (15 sessions), a
ticker's drive-long minus drive-short total correlated +0.84 with its summed open-to-close move,
+0.66 with its close-to-close return and −0.53 with its overnight gaps — by construction, since both
trades run from 09:35 to the close. Tickers that rose mostly overnight (SNPS +33%, gaps +20%) or
gapped up and sold off in session (CRWV) read the other way. Both sides losing marked a choppy
ticker (DDOG +27% on the period, drive long −8.8%, short −7.1%).

**Choppy filter: skip a ticker's drive trades when both sides lost over the last N sessions.**
Weekly decisions, 27 tickers. Next-week result of the drive setups a 3-month ranking would trade,
average per setup-week, choppy vs not:

| Period | 10 sessions | 15 sessions | 20 sessions |
|---|---|---|---|
| Jan–Aug 2025 (new data) | −0.06% vs −0.28% | +0.16% vs −0.33% | +0.24% vs −0.35% |
| Sep–Dec 2025 | −0.21% vs −0.05% | −0.44% vs −0.00% | −0.39% vs −0.02% |
| Sep 2025 – Jul 2026 | −0.07% vs +0.17% | +0.12% vs +0.11% | +0.22% vs +0.09% |
| Jul – Oct 2026 | −0.22% vs +0.63% | −0.26% vs +0.57% | +0.20% vs +0.49% |

The sign flips between periods and between look-backs (the 15-session filter would have cost 27
points in Sep 2025 – Jul 2026). Not adopted: a short losing streak on both sides doesn't predict the
next week. Side result: in Jan–Aug 2025 the drive setups a 3-month ranking would pick lost money
(−175% summed over 785 setup-weeks) — the first sign that the 2025–26 results were regime-specific.

## Finding 21 — The monitor's approach back to 2020 (split-adjusted)

Setup reports for 2020–2024, one per year (each starting the previous Sep 15 for the look-back),
on split-adjusted Alpaca bars (`Adjustment.SPLIT`, cached separately from the unadjusted cache, so
CRWD can be included). Tickers per year are those listed by the previous October: 21 in 2020 (AMAT
AMD AVGO CHTR CLS CRM CRWD DDOG FN GOOGL LLY MDB META MRNA MSFT NVDA QQQ SHOP SNPS SPOT TSLA), + PLTR
SNOW in 2021, + APP COIN in 2022–23, + ARM in 2024. Yahoo has no earnings history this far back for
some tickers, so their overnight holds include earnings nights.

**Weekly top-3 rotation** (63-session look-back, re-picked every 5 sessions, $10k per ticker in 3
sleeves; return on the allocated capital):

| Year | Tickers | R0 (all types, the monitor) | R1 (long + overnight) | Ticker buy & hold (avg) | QQQ |
|---|---|---|---|---|---|
| 2020 | 21 | +3.4% | +6.6% | +131% | +46% |
| 2021 | 23 | +2.3% | +2.9% | +43% | +26% |
| 2022 | 25 | −4.2% | −3.8% | −44% | −33% |
| 2023 | 25 | −2.3% | +0.3% | +110% | +52% |
| 2024 | 26 | +4.5% | +6.4% | +79% | +26% |

All of the profit came from overnight holds (+8.6, +4.5, −2.1, −0.3, +6.3 points under R0); long
intraday, short intraday and box setups were flat to negative every year. Picking a ticker's best
recent setup did not carry forward the way it did in Sep 2025 – Oct 2026 (Findings 17–18).

**Every setup, every signal** (fixed exits, $k at $10k per trade):

| Setup | 2020 | 2021 | 2022 | 2023 | 2024 | Sep 2025 – Oct 2026 |
|---|---|---|---|---|---|---|
| overnight ma200 | +57.9 | +13.6 | −26.2 | −10.6 | +57.7 | +59.5 |
| overnight always | +55.3 | +27.6 | −112.5 | −6.8 | +73.9 | +78.1 |
| drive long | −0.2 | +5.0 | −11.9 | +5.8 | +7.0 | +36.2 |
| pullback long C1 | −2.8 | +3.7 | −1.0 | +6.4 | −2.6 | 0.0 |
| pullback long | −7.4 | +1.0 | −1.1 | +3.7 | −6.2 | −2.3 |
| drive short | −33.7 | −13.8 | +14.6 | −32.6 | −17.7 | +0.8 |
| bounce long / short, box break / fade / gap, pullback short | negative in every period except pullback short 2021 (+1.0) | | | | | |

**Drive long and pullback long with filters** ($10k per trade, return on the money deployed): every
signal, drive long made +$5.7k over 14,927 trades in 2020–24 (+0.004% per trade) and pullback long
−$10.0k. Trading a setup only when it made money on that ticker over the previous 10 sessions made
both worse (−$10.5k / −$8.6k). Only taking signals with the ticker above its 50-day MA improved drive
long to +$14.9k over 9,146 trades (+0.016%), all from 2020; it lost more in 2022 (−0.12% per trade vs
−0.04%) and didn't help pullback long (−$6.4k). Sep 2025 – Oct 2026 was the exception for drive long
(+0.12% per trade every signal, +0.17% above MA50).

## Finding 22 — Mixing setups and tickers (chosen on 2020–22, tested on 2023–26)

All choices made on 2020–2022 only; 2023, 2024 and Sep 2025 – Oct 2026 are out of sample.

- **Setups:** only overnight ma200 was positive over 2020–22 (+$45.3k); on the test it made +$106.6k,
  up in 2 of 3 periods (2023 −$10.6k).
- **Ticker x setup pairs** that made money in all 3 calibration years (13 pairs, e.g. AMD/drive long,
  TSLA/box break, MRNA/pullback long C1) lost $6.0k in the test, 0 of 3 periods up. A ticker's fit
  with a setup doesn't persist.
- **Rolling ranking with longer memory** (each ticker's top 3 by the last 63/126/252 sessions,
  re-picked monthly): +$33k to +$100k in the test, no better than trading the long setups everywhere.
- **Ticker volatility** (20-day stdev of daily returns, ranked across tickers each day, known before
  the day) was the one selection that held: the more volatile half beat the calmer half for both
  setups in calibration and test — drive long +$41.3k vs +$7.8k in the test, overnight ma200
  +$62.1k vs +$44.4k.

Drive long + overnight ma200 on the more volatile half: +50%, +10%, −18%, 0%, +31% on peak capital
in use for 2020–24 and +53% for Sep 2025 – Oct 2026 (QQQ +46, +26, −33, +52, +26%). It behaves like
part-time long exposure, losing less than QQQ in 2022 and missing 2023.

## Finding 23 — Picking the top 2 tickers from daily candles and moving averages

Daily candles rebuilt from the backtest bars. About 25 features known at the signal: the previous
days' candle (body and wicks in ATR units, close location in the range, inside day, NR7, up/down
streak), distance from the 10/20/50/200-day MAs and the slopes of the 20/50-day MAs, 1/5/20-day
returns, ATR%, distance from the 20-day high and low, today's opening gap (drive setups, entry
09:35), and today's candle through the 15:45 bar (overnight, entry at the close). Each day the top 2
tickers with a signal are traded; features chosen on 2020–22.

**Measure features by the top 2's average result, not by daily rank correlation.** Rank correlation
said to avoid volatile tickers for drive long: with a 30% win rate, volatile names lose a little
more on most days but win far more on the few trend days that make the money. Scoring each feature
by the average net % of the top 2 it picks matches P&L.

**Overnight ma200 — the strongest names carry overnight.** The top 2 by a composite of distance
above the 200-day MA (yesterday and at 15:45) and today's return so far, average net % per trade:

| Period | Top 2 | All signals | Random 2 | Bottom 2 | Return on two $10k slots |
|---|---|---|---|---|---|
| 2022 (calibration) | −0.15% | −0.22% | −0.19% | −0.16% | −34% |
| 2023 | +0.03% | −0.02% | −0.00% | +0.00% | +7% |
| 2024 | +0.22% | +0.12% | +0.17% | +0.07% | +54% |
| 2025 | +0.05% | +0.08% | +0.14% | +0.01% | +13% |
| 2026 (Jan 1 – Oct 6) | +0.47% | +0.10% | +0.05% | +0.09% | +90% |

Distance above the 200-day MA alone beat the average in all 3 calibration and all 3 earlier test
periods. 2025 is the one test year where the top 2 did worse than random. The profit is spread
across tickers (without the best ticker: 2024 +$7.3k, 2026 +$7.4k); 2026 includes one +84% MRNA
night (Aug 18). Worst nights −14%.

**Drive long:** no candle or MA composite (nor a ridge fit on all features) beat taking every
signal on the test years; only higher ATR% did, in every test period. **Drive short:** nothing
worked; every selection lost in 2023 and 2024 (shorting after an up-streak only reached about
break-even). Drop drive short.

## Finding 24 — When not to trade

Market-level rules on top of Finding 23's picks (overnight top 2 by strength, drive long top 2 by
ATR%), each known before the trade, chosen on 2020–22. P&L $k at $10k per trade:

| Overnight top 2, trade only when… | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|---|---|
| always | +33.2 | +1.3 | −6.7 | +1.0 | +10.3 | +3.6 | +15.2 |
| QQQ above its 200-day MA | +28.8 | +1.3 | −0.7 | +0.1 | +10.3 | +5.5 | +14.6 |
| ≥ 40% of tickers above their 200-day MA (chosen on 2020–22) | +30.8 | +1.3 | −1.6 | +0.4 | +10.3 | +4.4 | +13.7 |
| QQQ above its 20-day MA | +25.1 | +1.3 | −3.1 | −1.0 | +7.9 | −1.6 | +9.3 |

| Drive long top 2, trade only when… | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|---|---|
| always | +3.6 | +5.8 | −2.2 | +4.7 | +6.1 | +0.2 | +22.4 |
| QQQ above its 20-day MA (chosen on 2020–22) | +8.8 | +6.7 | +7.0 | +3.4 | +0.5 | −1.3 | +12.2 |
| QQQ above its 200-day MA | +5.7 | +5.8 | −4.4 | +4.7 | +6.1 | −4.5 | +22.4 |

The rules work like insurance: each cuts the 2022 loss and costs profit in rising years. QQQ above
its 200-day MA is the cheap one for overnight holds: it saved $6.0k in 2022 and $1.9k in 2025 (the
Mar–May tariff selloff), and cost $4.4k in 2020 (the V-shaped COVID rebound) and $1.5k across 2023
and 2026. Short-term rules (QQQ 20-day) and the strategy's own last
20 sessions cost far more than they saved. Drive long is better without a rule.

**Combined:** overnight top 2 only when QQQ closed above its 200-day MA, drive long top 2 always
(four $10k slots, return on $40k):

| Year | P&L | Return | Capped ±10% | Max drawdown | Months up |
|---|---|---|---|---|---|
| 2020 | +$32.3k | +81% | +64% | −$6.8k | 10/12 |
| 2021 | +$7.1k | +18% | +11% | −$5.7k | 8/12 |
| 2022 | −$2.9k | −7% | −12% | −$9.9k | 5/12 |
| 2023 | +$4.9k | +12% | +8% | −$3.5k | 8/12 |
| 2024 | +$16.4k | +41% | +39% | −$4.7k | 7/12 |
| 2025 | +$5.7k | +14% | +12% | −$6.6k | 6/12 |
| 2026 (to Oct 6) | +$37.0k | +93% | +68% | −$6.0k | 9/10 |

2026 without MRNA (excluded from the pool, so other tickers fill its slots): +$27.4k, +69% (+63% capped),
same drawdown. MRNA added 103 trades for +$9.8k: drive long +$6.4k; overnight +$3.4k, of which the +84%
night on Aug 18 was +$8.4k and its other 61 nights lost about $5k.

Without the QQQ rule: 2022 −22%, 2025 +10% with a −$10.7k drawdown. Results swing with whether
volatile growth stocks trend that year. Caveats: one bear market in the data; 2 positions per setup
is concentrated; 2025 is split-adjusted on 26 tickers, 2026 comes from the unadjusted 2025–26
reports (22 tickers, including SNDK and CRWV, without CRWD, CLS, SNOW, DDOG, ARM and CHTR).

## Finding 25 — Drive long failure weeks in 2026, and what follows them

Every drive long signal in 2026 (Jan 2 – Oct 7, 2,065 signals on 22 tickers, held to the close with the
first bar's low as the stop): 65.4% failed (net ≤ 0). That is the setup's normal state — a few
all-day trends pay for many early stop-outs; 77% of the failed trades were stopped by 10:30 and 89%
by noon.

**Weeks with more than 70% failing** (13 of 41): Jan 26–30 (85%, −42.8% summed), Mar 9–27 (81%, 77%,
76%; the only month above 70% and the only losing month, −42.9%), Apr 6–10 (80%, while QQQ rose
4.5%), May 18–22, Jun 8–19, Jul 13–24, Sep 8–18 and Sep 28 – Oct 2 (88%, −34.0%, the worst). Only the
March sell-off and July lined up with a falling QQQ; April and June were up weeks where the open
faded.

**A bad week doesn't predict the next one.** In 2026, 9 of the 13 bad weeks were followed by a
profitable week (next week +0.25% per trade vs +0.10% after other weeks; e.g. Jan 26–30 −42.8 then
+32.8, May 18–22 then +37.3). Across 2020–2026 the link disappears: correlation of a week's failure
rate with the next week's result +0.05 over 354 weeks, negative in 2020–21 (−0.30, −0.15) and
positive from 2022. After the worst weeks (> 74% failing) the next week averaged +0.00% per trade,
the same as any week. One small, fairly consistent effect: the day after a day with > 80% failing
was better than other days in 6 of 7 years (about +0.09% per trade; 2026 the exception).

So don't pause drive long after a bad week or cut size after a bad day — consistent with the
negative equity-curve rules in Findings 20 and 24.

## Finding 26 — When the strongest up wave happens (2020–2026, wave module)

Each session split into waves by `analyze_bars` (default wave settings, as the setups use); 2020–25
on the split-adjusted bars with each year's tickers (Finding 21), 2026 on the 21 non-QQQ tickers of
the 2025–26 reports; about 39,000 ticker-days and 254,000 waves. Picking the day's strongest wave
uses the whole day, so this describes the intraday rhythm; it is not a signal by itself.

**The day's strongest up wave** (largest % up wave per ticker-day):

| Year | Median start | Median top | Typical gain | Starts 9:30–10:00 | 10:00–11:30 | 11:30–13:30 | After 13:30 |
|---|---|---|---|---|---|---|---|
| 2020 | 10:20 | 11:35 | 1.73% | 42% | 30% | 16% | 12% |
| 2021 | 10:15 | 11:25 | 1.48% | 43% | 30% | 16% | 11% |
| 2022 | 10:20 | 11:35 | 2.14% | 41% | 29% | 17% | 12% |
| 2023 | 10:15 | 11:35 | 1.52% | 43% | 30% | 18% | 9% |
| 2024 | 10:15 | 11:25 | 1.54% | 45% | 29% | 18% | 9% |
| 2025 | 10:20 | 11:35 | 1.64% | 43% | 29% | 18% | 10% |
| 2026 | 10:10 | 11:20 | 1.98% | 46% | 30% | 15% | 8% |

Median duration 50 minutes every year; 72–76% start before 11:30.

**Buying at the open:** on 46–50% of ticker-days the first wave is up from the open. It tops at a
median of **10:00 in every year** (middle half 9:45–10:25), gains 1.4–2.0%, and is the day's strongest
up wave 59–65% of the time (65% in 2026).

**Morning sell-off and the second wave** (largest down wave starting before 11:30, then the up wave
right after it): the sell-off starts at 09:50–09:55, the **morning low lands at 10:35–10:45 every
year**, and the rebound tops at 11:35–11:45 after recovering 70–76% of the drop (median drop −1.3%
to −1.9%, rebound +1.0% to +1.4%). The rebound is the day's strongest up wave 40–45% of the time.

Within 2026 the timing barely moved by month; March–April ran 10–20 minutes later (March sell-off
start 10:00 and low 10:45; April's strongest wave 10:20–12:00, the year's longest) and moves shrank
from September (to about 1.0–1.5%). 2026 differs from earlier years only in degree: bigger moves, a
slightly earlier and more decisive open, fewer afternoon waves. The 2022 bear market had the same
clock with bigger moves.

**For the setups:** drive long buys at 09:35, just before the opening run usually tops (10:00); on
about half the days the stock then sells off to around 10:40, where the first-bar-low stop is hit.
Most of the day's up move is done by about 11:45 while drive long holds to the close.

## Finding 27 — Buying the morning dip ("second wave") and selling drive long early (negative)

Both ideas from Finding 26, tested 2020–2026 on every signal (2020–25 split-adjusted with each year's
tickers, 2026 on the 22 tickers of the 2025–26 reports), 5 bps, chosen on 2020–22 and checked on
2023–26.

**The setup:** `--second-wave long` in `wave_risk_reward.py`, the morning dip "second wave" long entry.
When the wave module turns up (price takes back 23.6% of the down wave, after at least 7 bars) from a
down wave whose low came inside `--second-wave-window` (default 10:15–11:15) and that is at least
`--second-wave-ratio` (1.0) x the median lookback wave, buy that bar's close; stop below the dip's
lowest low minus 0.1 x the dip, target 61.8% of the dip back; one per session, none after
`--second-wave-latest-entry` (12:00 — a turn can be confirmed hours after the low). Opt-in like the
drive fade (`OPT_IN_SETUPS`). The backtest also gained `--exit time` (stop, else the close of the bar
ending at `--exit-time`), and `analyze_bars` now records each wave's `confirmed_at` bar.

**Drive long exits** (average net % per trade, every signal):

| Exit | 2020–22 | 2023–26 | Later years up |
|---|---|---|---|
| Hold to close (current) | −0.008% | +0.046% | 4 of 4 |
| 14:00 | −0.019% | +0.046% | 4 of 4 |
| 13:00 / 12:00 | −0.019% / −0.015% | +0.026% / +0.019% | 2 of 4 |
| 11:30 / 11:00 / 10:30 | −0.029% / −0.033% / −0.023% | +0.008% / −0.004% / −0.009% | 1 of 4 |
| End of the first up wave (wave turn) | −0.038% | −0.003% | 1 of 4 |
| Giveback / target | −0.048% / −0.051% | +0.002% / −0.021% | 1 of 4 |

The earlier the exit, the worse: 58–68% of drive long trades are stopped every year, and the setup
lives on the third of days that trend into the close. Keep holding to the close.

**The second wave, as designed:** lost in every year (−0.01% to −0.11% per trade at the defaults). Of 672
variants (low window 10:00–11:30 / 10:15–11:15 / 10:30–11:00, dip 0.5–2 x median, targets 50–100%,
two stops, seven exits), 6 were positive on 2020–22 — all on 2020 alone — and none on 2023–26. The
"recovers 73% of the drop" in Finding 26 is measured from the low, known only afterwards; by the
time the wave module confirms the turn about a quarter of the rebound is gone, and many confirmed
turns are pauses before a lower low.

**Variants tried after that** (all negative or too thin to trade):
- *Shallow dips above the 5-min MA200* (dip 0.5–1 x median, dip low or entry above MA200; 39% of
  dips qualify): with the target exit −0.05% / −0.05% per trade (2020–22 / 2023–26), 0 of 7 years
  up. Shallow dips beat deep ones in both periods (averaged over every window, target and exit:
  −0.040% vs −0.056% and −0.020% vs −0.053%) — the one consistent pattern; the MA200 filter added
  nothing (slightly better in calibration, worse later).
- *Hold the rebound to the close:* the best exit for the rebound too (average over variants
  −0.020% / +0.016% vs −0.059% / −0.040% for the target), but still about break-even. The
  calibration pick (shallow, dip low ≥ 0.5% above MA200, low 10:30–11:00) went +0.076% → −0.010%.
  The steadiest version — any dip, entry above MA200, low 10:30–11:00, held to close — was up in 6
  of 7 years but lost on 2020–22 overall (−0.023% / +0.051%); on the seven EC2 tickers in 2026 it
  made +0.04% per trade (175 trades, +7.7% summed), winning on AMD, MDB, SNPS, APP and SNDK and
  losing on CRWV (−13.8%) and MRNA, the names that trend from the open (drive long on the same
  tickers: +0.48% per trade, +323% summed).
- *Buy after the first large down wave of the morning* (window 09:30–12:00, first dip ≥ 1/1.5/2/3 x
  median, low by 10:30/11:00/12:00, with and without the MA200 filter; candidates generated against
  a 100% target so strong rebounds are not dropped): 0 of 320 variants positive on 2020–22, and the
  bigger the dip the worse (held to close, low by 11:00: −0.041% / −0.020% at 1x, −0.070% / −0.046%
  at 2x). A large first dip is more often the start of a down day. Only 2026 paid for buying big dips
  above MA200 (+0.13% to +0.68% per trade) — a dips-get-bought year; the 2020–22 pick still lost 4.5%
  on the EC2 tickers in 2026.

**Conclusion:** buying morning weakness has no lasting edge on these tickers; shallower dips are less
bad than deep ones, and any long that buys strength should be held to the close. The second wave
stays in the code, opt-in.

## Finding 28 — Drive long risk controls: re-entry, wider stops, a daily MA switch, and drawdown

Drive long re-simulated straight from the 5-min bars (green first bar, buy its close, hold to the
close; the baseline matches the backtest exactly), 20,246 drive long days 2020–2026 (2020–25
split-adjusted with each year's tickers, 2026 on the 22 tickers of the 2025–26 reports), 5 bps,
chosen on 2020–22 and checked on 2023–26. Drawdown = largest peak-to-trough fall of daily P&L at $10k
per trade.

**Re-entering after the stop-out.** About two-thirds of drive long trades are stopped (58% in 2026), at
a median 09:45; 56% of those close back above the entry later (median 10:25). Buying again once on
that close and holding to the close:

| Re-entry rule | 2020–22 | 2023–26 | Years up | Added per drive long day (2023–26) |
|---|---|---|---|---|
| Any time, stop at the low since the stop-out | −0.054% | +0.009% | 3 of 7 | +0.003% |
| Any time, original stop | −0.055% | +0.008% | 3 of 7 | +0.003% |
| Any time, no stop | −0.038% | +0.038% | 4 of 7 | +0.013% |
| By 14:00, no stop | −0.037% | +0.049% | 5 of 7 | +0.015% |
| By 11:00, low since the stop-out | −0.064% | +0.013% | 3 of 7 | +0.003% |

Every version lost on 2020–22; re-entries won 36–50% (retaking the entry often tops out again). On the
seven EC2 tickers in 2026 the 197 re-entries summed −15.8% (CRWV −16.0%, MDB −10.3%, MRNA −9.6%; SNPS
+10.8%, SNDK +9.2%, AMD +2.7%) against +323% for drive long itself. Not adopted.

**Wider stops** (15 rules known at entry: the first bar's low minus 0–3 x its range or 2/4/8 x the
average 5-min bar, 1/2/3% below entry, 0.5/1 x the 20-day average daily range below entry, the
previous day's low, no stop):

*Every drive long signal* (about 11–12 trades a day):

| Stop | Avg 2020–22 | Avg 2023–26 | P&L 2023–26 | Max DD 2020–22 | Max DD 2023–26 | Worst day |
|---|---|---|---|---|---|---|
| First bar's low (current) | −0.008% | +0.046% | +$54.5k | −$35.9k | −$19.4k | −$2.6k |
| 2% below entry | −0.006% | +0.059% | +$69.8k | −$37.7k | −$20.3k | −$3.9k |
| 0.5 x daily range below entry | +0.005% | +0.059% | +$69.4k | −$43.8k | −$20.1k | −$4.1k |
| 4 x avg 5-min bar below the low | +0.004% | +0.077% | +$90.7k | −$51.7k | −$23.3k | −$10.3k |
| 2 x first bar's range below the low | −0.007% | +0.080% | +$94.4k | −$57.9k | −$23.4k | −$7.5k |
| Previous day's low | +0.007% | +0.059% | +$63.1k | −$52.1k | −$28.3k | −$11.1k |
| No stop | +0.009% | +0.081% | +$94.7k | −$67.6k | −$27.2k | −$13.9k |

2020–22 can't separate the stops (all within ±0.02% per trade of zero); later, wider stops add
+0.01% to +0.04% per trade, paid for with deeper drawdowns and worse single days. A 2% stop (or 0.5 x
the daily range) is the best trade-off: +28% more profit in 2023–26 at nearly the same drawdown.

*Top 2 most volatile per day* (20-day average daily range; the strategy's drive long leg, two $10k
slots):

| Stop | Avg 2020–22 | Avg 2023–26 | P&L 2023–26 | Max DD 2020–22 | Max DD 2023–26 | Worst day | Return / DD 2023–26 |
|---|---|---|---|---|---|---|---|
| First bar's low (current) | +0.006% | +0.225% | +$42.6k | −$14.7k | −$6.4k | −$1.0k | 6.6 |
| 1% below entry | −0.029% | +0.189% | +$35.7k | −$13.8k | −$6.3k | −$0.4k | 5.7 |
| 3% below entry | −0.051% | +0.249% | +$47.1k | −$20.9k | −$8.7k | −$0.6k | 5.4 |
| 4 x avg 5-min bar below the low | −0.054% | +0.225% | +$42.5k | −$22.6k | −$8.1k | −$1.8k | 5.2 |
| No stop | +0.036% | +0.219% | +$41.4k | −$18.2k | −$10.0k | −$2.2k | 4.2 |

On volatile tickers the first bar is already wide (median risk 1.26% of price), so a wider stop adds no
return later and raises the drawdown 30–60%; it also made 2022 much worse (−0.24% to −0.37% per trade
vs −0.12%). This selection uses the daily range rather than Finding 23–24's ATR% (gaps included), so
its 2022 differs slightly from those findings.

**Conclusion:** keep the first-bar-low stop on the strategy's drive long leg (best return per unit of
drawdown, smallest worst day, best 2022). For drive long on every signal or a broad list, a 2% stop
below entry (or 0.5 x the daily range) adds about +0.013% per trade at nearly the same drawdown. No
stop and re-entry after the stop-out are not worth it.

**A per-ticker daily MA switch** (take drive long only while the stock is above its daily MA: on once a
daily close breaks above it, off once one breaks below; yesterday's close vs its MA, known pre-open).
58% of drive long days come while the stock is above its 20-day MA.

| All tickers, $10k per trade | Avg 2020–22 | Avg 2023–26 | P&L 2020–22 | Max DD 2020–22 | P&L 2023–26 | Max DD 2023–26 |
|---|---|---|---|---|---|---|
| Pure drive long | −0.008% | +0.046% | −$7.1k | −$35.9k | +$54.5k | −$19.4k |
| Only above daily MA20 | +0.010% | +0.019% | +$4.6k | −$14.0k | +$13.2k | −$21.0k |
| Only above daily MA50 | +0.003% | +0.044% | +$1.7k | −$20.3k | +$31.7k | −$10.5k |
| Only above daily MA10 | +0.002% | +0.030% | +$1.0k | −$17.2k | +$20.3k | −$11.1k |
| Only below daily MA20 | −0.031% | +0.087% | −$11.7k | −$31.2k | +$41.3k | −$15.2k |

The switch helped in 2020–22 (2022 above all) and backfired in 2023–26, where signals below the 20-day MA
were the best (+0.087% per trade): a stock that has pulled back below its MA20 and opens green often
starts a strong rebound day. Per ticker (28 tickers, summed net % per trade over the years each has
data):

| | Pure | Above MA20 | Above MA50 |
|---|---|---|---|
| Summed over tickers, 2020–2026 | +474% | +178% | +333% |
| 2020–22 / 2023–26 | −71% / +545% | +46% / +132% | +17% / +317% |
| Tickers with a better total | — | 13 of 28 | 12 of 28 |
| Tickers with a smaller drawdown | — | 22 of 28 | 21 of 28 |
| Median return / drawdown per ticker | 0.40 | 0.02 | 0.27 |

It splits by ticker type: of the 13 tickers where drive long lost money, the MA20 switch improved 11 (CRM
−61.9% → +3.4%, SNPS −10.0% → +36.9%, DDOG −53.6% → −10.8%); of the 15 where it made money it improved
only SHOP and LLY and gutted the trenders (TSLA +84.2% → +9.0%, APP +82.7% → +10.5%, CLS +54.4% → +2.4%,
AMD +37.0% → −15.9%). Which group a ticker belongs to isn't known in advance (Finding 22), and the
strategy's top-2-by-volatility pick favours the trenders, where the switch hurts most. On the seven EC2
tickers in 2026 it raised the average trade (+0.59% vs +0.48%) but cut the total from +323% to +215% on
45% fewer trades, without a smaller combined drawdown (−37.8% vs −32.9% summed); it helped MDB (−1.3% →
+12.2%) and MRNA's drawdown (−44% → −28%) and erased CRWV (+49.9% → +1.0%).

Not adopted: the switch lowers drawdown on most tickers but costs more return than it saves. The QQQ
200-day rule (overnight only, Finding 24) and the volatility pick are the cheaper risk controls.

## Finding 29 — Offense plus defense: no setup earns in a bear market; step aside instead

The offense is Finding 23–24's pair: overnight ma200 on the 2 strongest tickers and drive long on the 2
most volatile, $10k per trade, four slots ($40k). The search was for a defensive leg for the bear regime
(QQQ's previous close below its 200-day MA: 21 sessions in 2020, 234 in 2022, 19 in 2023, 46 in 2025, 12
in 2026), on the same ticker list as Findings 21–24.

**Every setup in the bear regime** (every signal, fixed exits): over 2020–22 all lost except box gap
(+$0.6k). Drive short made +0.03% per trade in the 2022 bear regime but −0.84% in the March 2020 crash —
bear-market rebounds stop shorts out; shorts only paid in January 2022, before QQQ crossed below its
MA200. Drive long lost −$16.0k in 2020–22 bear days and made +$16.3k in 2023–26 ones (the April 2025
rebound); overnight ma200 lost −$14.9k / −$1.2k.

**Combinations** (return on $40k; the 2023–26 drawdown in brackets):

| Combination | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 | Max DD 2020–22 |
|---|---|---|---|---|---|---|---|---|
| A offense always on | +92.0 | +17.7 | −22.3 | +14.3 | +40.9 | +9.6 | +94.0 | −37.9% (−26.8%) |
| B overnight off in bear (Finding 24) | +80.9 | +17.7 | −7.2 | +12.1 | +40.9 | +14.2 | +92.5 | −29.3% (−16.7%) |
| C everything off in bear | +86.1 | +17.7 | −12.9 | +11.9 | +40.9 | +2.6 | +92.3 | −16.6% (−22.6%) |
| C + drive short (top 2 by ATR%) in bear | +77.3 | +17.7 | −13.7 | +7.0 | +40.9 | −9.0 | +100.3 | −29.2% (−34.1%) |
| C + drive short (top 2 by up-streak) in bear | +79.2 | +17.7 | −9.2 | +7.3 | +40.9 | +1.1 | +99.9 | −18.1% (−24.1%) |
| C + pullback long C1 in bear | +82.3 | +17.7 | −11.5 | +20.9 | +40.9 | +2.6 | +96.8 | −24.8% (−22.6%) |
| C + drive short when QQQ < its MA50 | +77.4 | +20.6 | −19.3 | +11.5 | +30.1 | +2.2 | +98.8 | −22.4% (−26.2%) |
| Drive long / drive short switched by QQQ's MA50, no overnight | +13.1 | +12.1 | −5.2 | +0.7 | −0.7 | −5.4 | +46.1 | −23.5% (−24.8%) |

A $10k short QQQ held while QQQ is below its MA200 made +11.7% in 2022 but lost in every other bear stretch
(2020 −13.4%, 2023 −11.6%, 2025 −7.0%, 2026 −4.3%). Most of 2022's loss in B and C is the MA200's lag
(January 2022, before the switch turned). B had the best 2022, 2025 and 2023–26 drawdown; C the smallest
2020–22 and overall drawdown (−22.6% vs −29.3%).

On this ticker list, Jan 2020 – Oct 9 2026: B +251% simple ($10k per trade), +586% compounded yearly; C
+239% / +494%; B capped at ±10% per trade about +190% / +352%. Buy and hold over the same period (daily
SIP bars, first 2020 open to the Oct 9 2026 close): QQQ +250% (+266% with dividends), max drawdown −35.6%;
SPY +141% (+165%), −34.2%. **Finding 30 shows these strategy numbers depend on the ticker list.**

## Finding 30 — Ticker selection without hindsight: the edge was mostly the ticker list

Findings 21–29 chose their rules without hindsight but ran on a ticker list assembled in 2026 from names
already known to be strong. Here the same strategy (same setups, top-2 selection, B and C rules, 5 bps,
split-adjusted bars fetched directly) runs on universes that could have been picked at the time.

**Yearly: the top 8 Nasdaq-100 members by the previous calendar year's return.** Membership was
reconstructed from memory at first (spot checks against the change log below agree: ENPH, TTD and ZM were
not members at the end of 2019); the yearly picks were not re-run on the verified membership.

| (return on $40k) | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 | Compounded | Max DD |
|---|---|---|---|---|---|---|---|---|---|
| A always on | +8.0 | −6.4 | −28.4 | −20.8 | +33.7 | −11.4 | +48.5 | +0.8% | −75% |
| B | +5.4 | −6.4 | −20.5 | −24.1 | +33.7 | −9.8 | +47.8 | +6.0% | −69% |
| C | +16.0 | −6.4 | −9.4 | −27.1 | +33.7 | −17.4 | +46.3 | +15.9% | −60% |

Drive long lost in 6 of 7 years. A year's winners often reverse (2021's list was 2020's pandemic winners
PTON, ZM, DOCU, PDD, MRNA) or are low-volatility (2023's was 2022's defensive winners VRTX, TMUS, ORLY,
GILD, BKR — the worst year, −24%).

**Monthly: the top 8 by the previous calendar month's return, on actual membership.** Membership on any
date is rebuilt from Wikipedia's current constituents table with every dated change after that date undone
(228 changes since 2007; 101–103 members at each year-end, GOOG and GOOGL counted separately; only GOOGL
traded). Monthly returns come from Alpaca daily closes (compounding weekly returns gives the same number);
all 169 tickers that were members at some month-end Nov 2019 – Sep 2026 had data, delisted ones included.
82 months picked 140 different tickers, most often TSLA (24 months), AMD (19), NVDA (18).

| (return on $40k) | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 | Compounded | Capped ±10% | Max DD |
|---|---|---|---|---|---|---|---|---|---|---|
| A always on | +42.9 | −3.8 | −27.7 | −16.1 | +26.6 | −12.3 | +33.3 | +23.4% | +10.4% | −58% |
| **B overnight off in bear** | +38.6 | −3.8 | −2.5 | −16.1 | +26.6 | −7.7 | +33.7 | **+70.3%** | +51.4% | −33% |
| C all off in bear | +36.2 | −3.8 | −4.9 | −16.9 | +26.6 | −9.3 | +35.1 | +60.5% | +55.1% | −36% |
| QQQ buy & hold | +47.6 | +26.8 | −33.1 | +53.8 | +24.8 | +20.2 | +22.3 | +253% | | −36% |
| SPY buy & hold | +16.3 | +26.9 | −19.5 | +24.3 | +23.3 | +16.4 | +14.2 | +142% | | −34% |

B's legs ($k): drive long +7.9, −1.3, +0.4, −0.1, +4.9, −3.4, +6.1; overnight +7.6, −0.2, −1.4, −6.3, +5.8,
+0.3, +7.4. Its profit came from the months the picks held that year's leaders (2020 TSLA +$7.4k, FI,
ZM, PDD; 2024 NVDA, AMD, CEG, TSLA; 2026 SNDK +$8.8k, MU +$5.3k).

**All 8 tickers instead of the top 2** (every signal, eight $10k slots, return on $80k): A +4.5%, B +38.4%
(max DD −36%), C +58.5% (−25%) compounded; average trade +0.008% / +0.019% / +0.028%. By leg: overnight
ma200 with the QQQ rule alone +49.3% (max DD −20%, +0.037% per trade, down only in 2022 −4.0% and 2023
−9.7%); drive long on every signal −6.4% (−0.006% per trade, 4 of 7 years down). The top-2 selection adds
value (B +70% vs +38%); drive long needs it to have any edge.

**Why the original list did so much better:**

| | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|---|---|
| Original list: average stock's return that year | +137% | +44% | −44% | +116% | +79% | +42% | +72% |
| Monthly top 8: return in the months held, compounded | +110% | +28% | −24% | +44% | +7% | +33% | +39% |
| Original list / top 8: average daily move | 2.5 / 2.5% | 2.0 / 1.8% | 3.0 / 2.2% | 2.0 / 1.7% | 2.2 / 1.8% | 2.3 / 2.0% | 2.9 / 3.0% |
| Overnight ma200 per trade, original / top 8 | +0.13 / +0.09% | +0.03 / +0.03% | −0.21 / −0.20% | −0.02 / −0.05% | +0.12 / +0.04% | +0.08 / +0.05% | +0.11 / +0.07% |
| Drive long per trade, original / top 8 | 0.00 / −0.04% | +0.02 / +0.01% | −0.04 / −0.10% | +0.02 / −0.01% | +0.02 / +0.04% | +0.03 / −0.01% | +0.17 / +0.10% |

- The original list is mostly stocks now known to have had exceptional years: its average stock beat QQQ
  in 5 of 7 years, often 2–3x. Nine of its tickers were never in the Nasdaq-100 (SNDK, CRWV, COIN, FN, CLS,
  SPOT, LLY, CRM, SNOW), so no index rule could have found them.
- Both setups earn from stocks that keep trending (overnight drift in a steady uptrend; days that run
  open to close), so per-trade results were 1.5–3x higher on the original list in up years.
- It is trend persistence, not volatility: both universes move about the same each day; last month's
  winners stall (2024: +7% in the months held vs +79% for the original list).
- A few big winners carry the original list (2026: median stock +9%, average +72%).

**Conclusion:** on a universe chosen without hindsight the strategy makes about 8% a year (B, monthly top
8) against about 20% for QQQ, with a similar drawdown; its one clear advantage is the bear market (2022
−2.5% vs −33%). The +586% on the original list is mostly the ticker list. The setups help with timing; the
edge comes from holding stocks that keep trending, and last month's return doesn't find them reliably. The
overnight leg with the QQQ rule is the most robust piece (+49% alone on all eight monthly tickers, −20%
drawdown).

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
8. **AMD in a 2025-style year (gains overnight, flat sessions):** short the tops of big up waves,
   `--no-box-signals --deep-bounce short --exit target-trail` (+9.11% on 2025; Finding 11).
9. **Overnight hold as a core setup (Finding 13):** `--overnight-hold ma200` for protection or
   `always` for upside, on tickers whose returns come overnight; check a ticker's overnight vs
   in-session split before using it, and skip earnings nights if possible.
10. **Don't rely on a regime indicator to switch setups** (Finding 12); if rotating, use only the
    wave setups and a slow rule (top 2 by trailing 40 sessions).
11. **For a new ticker, run the scan** (Finding 15) on the last 12 months, trade the recommended
    setups, and re-run it periodically; for the overnight hold, prefer tickers in the top 3–5 by
    120-session momentum (Finding 14).
12. **Still untested:** a bear-market year for SNDK-like names, costs other than 5 bps, and a
   one-position-at-a-time rule for combined setups.
13. **Pick setups with R1 (Finding 18):** long setups and overnight holds only, ranked by their
    3-month total, top 3 positive with ≥ 3 trades. Skip short and box setups. Back to 2020 it made
    only about +2.4% a year (Finding 21) — treat its 2025–26 results as regime-specific.
14. **Update the picks every week or two (Finding 17);** picks held 8+ weeks lost money in the
    2026 test. The monitor does this with `config --refresh --types long overnight --min-trades 3`.
15. **Prefer a broad pool (20+ liquid tickers) over filtering it** — momentum ticker filters, MA50
    gates and pausing setup types after a bad month all failed out of sample (Finding 18).
16. **Don't bet against losing setups** — neither reversing them nor fading the opening drive held
    up out of sample (Finding 19).
17. **Trade only drive long and overnight ma200** (Findings 21–22). Every short, box and bounce
    setup lost money in almost every year 2020–2026, and no ticker selection rescued drive short
    (Finding 23).
18. **Select tickers across the pool, not setups per ticker** (Findings 22–23): overnight ma200 on
    the 2 tickers furthest above their 200-day MA and up most at 15:45; drive long on the 2 most
    volatile tickers (20-day ATR%) that trigger. A ticker's fit with a setup, its recent setup
    results (10 sessions or a choppy streak) and candle shapes did not carry forward (Findings 20–23).
19. **Skip overnight holds when QQQ closed below its 200-day MA** (Finding 24) — cheap insurance
    against a 2022-style bear market. Don't gate drive long, and avoid short-term market rules
    (QQQ 20-day MA) and equity-curve rules.
20. **Size for long exposure:** the combined strategy made money in 6 of 7 years but swings from
    +12% to +93% with the growth-stock trend, lost 7% in 2022, and 2 positions per setup is
    concentrated (worst nights −14%). Before trading it, re-run 2026 on the same 26 tickers plus
    SNDK/CRWV with split-adjusted bars, and check costs above 5 bps.
21. **Keep trading drive long through bad weeks** (Finding 25): a > 70% failure week says nothing
    about the next one across 2020–2026.
22. **Hold drive long to the close and don't buy the morning dip (Finding 27):** every earlier exit
    (10:30–14:00, the end of the first up wave, giveback, target) did worse, and the second-wave
    entry lost in every form tried (as designed, shallow + MA200, held to close, first large dip).
    If a dip entry is ever revisited, prefer shallow dips and hold to the close; "any dip, entry
    above MA200, low 10:30–11:00, held to close" is the one version worth re-checking on new data.
23. **Drive long stops (Finding 28):** keep the first bar's low as the stop on the 2 most volatile
    tickers (the strategy's leg); for drive long on every signal or a broad list use 2% below entry
    (or 0.5 x the 20-day average daily range). Don't re-enter after the stop-out, and don't drop the
    stop — no stop roughly doubles the drawdown. Don't gate drive long by the ticker's own daily
    MA20/MA50: it rescues choppy names but guts the trending ones, which the volatility pick favours.
24. **Treat results on a hand-picked ticker list as an upper bound (Finding 30).** The same strategy made
    +586% on the research list and +70% on the actual Nasdaq-100's monthly top 8 (QQQ +253%). Any new
    result should be checked on a universe chosen without hindsight (the monthly-membership pipeline).
25. **If trading the strategy:** re-pick the tickers each month from actual Nasdaq-100 members by the
    previous month's return, keep the top-2 selection, and keep the QQQ 200-day rule; the overnight leg
    is the most robust part. The EC2 monitor's hand-picked list carries the hindsight risk of Finding 30.
26. **No setup earns in a bear market (Finding 29).** Step aside (B or C) instead of adding shorts or a
    short-QQQ hedge, both of which lost in the 2020, 2023 and 2025 bear stretches.
27. **Next research:** ticker selection that finds stocks which keep trending (2–6-month lookbacks, new
    52-week highs, smoothness or share of up days, relative strength vs QQQ), tested on the monthly
    membership; and a QQQ core with the overnight leg as an overlay.

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

**Findings 20–30** came from one-off scripts that were not committed. To rebuild them:
1. Split-adjusted bars: point `op_momentum_backtest._CACHE_DIR` at a separate folder and wrap
   `StockBarsRequest` with `adjustment=Adjustment.SPLIT` (both set in a `sitecustomize.py` on
   `PYTHONPATH`, so process-pool workers get them too) — never mix adjusted bars into
   `market_data/cache/`.
2. One setup report per year: `wave_risk_reward_setup_report --tickers <year's tickers>
   --start <year-1>-09-15 --end <year>-12-31` (2025: `--setups "drive long" "drive short"
   "overnight ma200"`), keeping each year's trades with the fixed exits (`load_trades`).
3. Weekly rotation: `walk_forward(trades, tickers, sessions, start, 63, 5, 3, 10000, 0.0, 1, False,
   types)` from `wave_setup_walk_forward.py` per year.
4. Daily candles from the same bars (full session and through the 15:45 bar); features use only
   prior days, plus today's open (drive) or today's candle to 15:45 (overnight). Top 2 per day by
   feature rank; features and rules chosen on 2020–22 only.
5. Finding 26: `analyze_bars(_load_bars(ticker, <year-1>-09-15, <year>-12-31, DataFeed.SIP))["waves"]`
   per ticker-year (same range as the yearly reports, so the split-adjusted cache hits); per wave
   take `w.df.index[0]` as the start, `wave_end_time(w)` as the top or bottom, and
   `wave_end_price(w) / wave_start_price(w) − 1` as the move.
6. Finding 27: one `analyze_bars` pass per ticker-year with `opening_drive="long"`, `second_wave="long"`,
   a wide `second_wave_window`, `second_wave_ratio=0.5` and `second_wave_once_per_session=False` (every
   candidate, filtered afterwards; take the first passing candidate per session), then
   `TradeSimulator.run(signal, exit, exit_at=...)` per exit; the "wave turn" exit sells at the
   `confirmed_at` bar of the first wave after the entry whose previous wave was up.
7. Finding 28: per ticker-year from the same bars — green first bar, entry its close; stop hit when a
   later bar's low reaches it (fill at the lower of that bar's open and the stop), else the session's
   last close; average 5-min bar = mean high-low of the previous 78 bars, daily range = 20-session mean
   (high − low) / close of earlier sessions. Re-entry: the first bar from the stop bar on whose close
   is above the original entry. Drawdown from daily P&L summed at $10k per trade. MA switch: daily
   closes from the same bars, `close > close.rolling(n).mean()` shifted one session. (2026 bars: load with
   an end date whose +7-day fetch window matches the cached file, or the loader asks Alpaca for recent
   SIP data the subscription refuses.)
8. Findings 29–30: QQQ regime = previous close vs its 200-day (or 50-day) MA from daily closes.
   Nasdaq-100 membership from the raw wikitext of Wikipedia's "List of NASDAQ-100 companies" (current
   table) and "Historical components of the Nasdaq-100" (dated changes), fetched 2026-10-11 with
   `index.php?title=...&action=raw`; undo every change after the date. Daily closes and 5-min bars come
   straight from Alpaca (`StockBarsRequest`, `Adjustment.SPLIT`, SIP, ending at the last completed
   session), not through the cache loader. Signals from `analyze_bars(bars, WaveRiskRewardParams(
   box_signals=False, opening_drive="long", overnight_hold="ma200"), ticker_earnings_windows(...))` per
   ticker-year with 13 months of warm-up; selection features from the same bars (prior-day ATR20%,
   distance above the daily MA200 yesterday and at 15:45, return to 15:45).

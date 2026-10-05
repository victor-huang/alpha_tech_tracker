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
  style — made +4.36% (Jul–Oct) and +5.55% on the unseen Jan–Jun, and also held up on SNDK and
  META.

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

## Recommendations

1. **Choose tickers before tuning settings.** The same configuration ranges from +156.66% (SNDK)
   to −8.74% (META). Next: run the 2026 backtest across the cached tickers and check whether the
   results line up with average daily range or trend (for example distance above the daily MA)
   — a candidate ticker-selection rule.
2. **Treat per-ticker settings with suspicion.** On META, 3-month tuning barely predicted the
   previous 6 months (correlation +0.26). Any per-ticker setting needs an out-of-sample check.
3. **The regime switch may need to be per ticker** — it helped QQQ + SNDK and hurt META.
4. **For AMD-like names (impulse waves, few tight boxes)** use the wave pullback long with
   `--no-box-signals --exit target-trail`; it also held up on SNDK and META.
5. **Still untested:** a bear-market year for SNDK-like names, and costs other than 5 bps.

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

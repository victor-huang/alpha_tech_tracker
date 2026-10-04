# Wave Risk/Reward — Signal Research Findings

Research log for `analysis_scripts/wave_risk_reward.py` (usage:
[`guides/WAVE_RISK_REWARD_GUIDE.md`](../../guides/WAVE_RISK_REWARD_GUIDE.md)). Studies run
2026-10-04 on cached Alpaca SIP 5-min bars.

## Summary

- **Best result so far (Finding 14):** default box signals plus `--opening-drive both`, with 5 bps
  round-trip costs, on QQQ + SNDK, Jun 1 – Oct 2 2026: **+75.04%** over 311 trades holding to the
  session close (`--exit eod`), **+49.45%** with the give-back exit; every full month positive in
  both. **It is an SNDK result:** SNDK made +83.55% / +55.25% while **QQQ lost in every
  configuration once costs are included**, and SNDK rose enormously over the period. Not yet a
  reliable edge — it needs a wider ticker set and a bear period.
- **Box breakouts do not predict direction.** Over 30 sessions, in-session breakouts and
  breakdowns moved the signal's way 36–57% of the time at 5 min to the session close, and R/R did
  not rank outcomes (Spearman +0.10).
- **Wide-box fades looked strong over 30 sessions** (+0.72R, 16 trades) **but failed on Jun–Oct**
  (−3.68%): they lost in June and July and only paid in August and September. Breakouts did the
  opposite. Results are regime-dependent.
- **Stop-and-reverse breakouts are the one consistent loser:** 14–22% win rate in every test.
  Now off by default (`--stop-and-reverse` to enable), which lifted the best configuration from
  +9.41% to +13.62% (Finding 10).
- **Box signals structurally miss opening moves.** On SNDK, 30 of 52 large/medium legs (5 of 7
  large) start in the first 15 minutes, before any box exists (Finding 11). The simplest opening
  rule — buy a green first bar, short a red one, stop at its extreme, give-back exit — beat a
  trade-every-day baseline on both sides in all three samples tested (Finding 12) and is now
  `--opening-drive`.
- **The exit leaves most of a caught leg on the table.** On the same SNDK signals a give-back
  exit made +19.29% against +7.54% for the fixed target (Finding 11); on QQQ + SNDK Jun–Oct it
  made +28.01% against +13.62% (Finding 13).
- **The setup is ticker-specific** — see
  [`wave_risk_reward_strategy_ticker_params_tunning.md`](wave_risk_reward_strategy_ticker_params_tunning.md):
  over 2026 the best configuration made +156.66% on SNDK but −8.74% on META, and tuning META's
  box settings on 3 months did not hold out of sample.
- **The MA-stack regime switch helps** (+4.39% → +9.41%, 345 → 145 trades); an efficiency-ratio
  trend filter and the opening-range bias both hurt.

## Method

**Data:** regular-hours 5-min bars from `fetch_bars()` (Alpaca SIP cache). Tickers and windows
are given per finding.

**Trade evaluation** (scratch scripts, not committed — see [Reproduction](#reproduction)):
- Entry at the signal bar's close, in the signal's direction (breakout / fade long = long).
- Exit at the signal's own stop or target, whichever comes first, else at the session's last
  close. A bar that touches both counts as a stop. A gap through the stop fills at the open.
- One trade per signal, no position overlap rules, **no costs or slippage**.
- `avg R` = mean of (exit − entry) / risk, signed by direction; `total %` = sum of per-trade
  returns in percent (not compounded).

**Caveat on every result below:** 2 tickers (sometimes 6), 30–87 sessions, settings picked on
the same data. Treat totals as optimistic.

---

## Finding 1 — Legacy risk/reward and wave counting issues

Before building the script, the existing `wave.py` and the strategy R/R
(`strategy.py:upside_potential/downside_risk`, duplicated in `tsla_strategy.py`) were reviewed:

- `wave.py` dropped waves when replaying bars into a new wave (`skip_create_new_wave` was
  ignored), started waves from wicks while tracking closes, and documented a 2% minimum wave size
  that was really ≈0.031%. Fixed in `a657db4`.
- The strategy R/R sets risk to 0.01 when price sits on the 10-bar low below MA20, inflating the
  ratio into the hundreds; upside can be negative; it is long-only. The new script floors risk at
  `--min-risk-pct` instead.

## Finding 2 — Volatility-scaled wave size

Six tickers (NVDA, TSLA, JPM, MSFT, COIN, QQQ), Aug 17 – Sep 14 2026. Waves per session:

| Minimum wave size | Waves / session (range across tickers) |
|---|---|
| fixed 0.031% (old `wave.py` default) | 8.5 – 9.7 |
| **2 × avg bar range (default)** | 5.5 – 6.5 |
| 3 × | 4.0 – 4.8 |
| 4 × | 2.9 – 3.5 |
| 5 × | 2.3 – 2.7 |
| 6 × | 1.8 – 2.2 |

Scaling by the trailing average bar range gives comparable wave counts across tickers with very
different volatility. 2× was chosen as the balance between noise and signal count.

## Finding 3 — A stop at the far side of the box caps breakout R/R near 1

With the stop at the opposite box edge, risk ≥ box height while the target is max(box height,
median wave) and the box is ≤ 2× the median wave, so R/R rarely exceeds 1. Same six tickers and
window, 53 signals:

| `--box-stop-ratio` | Median R/R | Middle half | Share ≥ 1.5 |
|---|---|---|---|
| 1.0 (opposite edge) | 0.89 | 0.50 – 0.98 | 4% |
| 0.5 | 1.60 | 0.66 – 1.89 | 53% |
| **0.2 (default)** | **2.95** | 0.83 – 4.03 | 64% |

The higher R/R comes from a tighter stop, not a better setup — see Finding 5: about two-thirds of
breakouts then stop out.

## Finding 4 — Box settings for 1–3 signals per session

Target: 1–3 signals per ticker per session. 36-combination sweep, six tickers (QQQ, SNDK, NVDA,
TSLA, JPM, COIN), 30 sessions to Oct 2 2026:

| Wave size | Min box waves | Small-wave ratio | Max height | Signals / day | Days with 1–3 | Median R/R (excl. gap) |
|---|---|---|---|---|---|---|
| 2.0 | 3 | 1.0 | 1.5 (old) | 0.33 | 32% | 3.54 |
| **2.0** | **2** | **1.5** | **2.0** (default) | **1.58** | **87%** | **3.73** |
| 1.0 | 3 | 1.5 | 2.0 | 1.37 | 82% | 3.43 |

Two-wave boxes and a looser small-wave cutoff drive the count; R/R did not degrade. About a third
of signals are gap signals.

## Finding 5 — Breakout signals do not predict direction (30 sessions)

QQQ + SNDK, Aug 21 – Oct 2 2026, settings from Finding 4, no regime filter, no wide boxes.

Share of in-session signals where price moved in the signal's direction:

| | 5 min | 15 min | 30 min | 60 min | Session close |
|---|---|---|---|---|---|
| QQQ (32) | 45% | 43% | 39% | 48% | 42% |
| SNDK (28) | 57% | 42% | 44% | 48% | 36% |

Trade results:

| | Target / stop / close | Win | Avg R | Total |
|---|---|---|---|---|
| QQQ in-session | 3 / 20 / 8 | 23% | −0.26 | −1.37% |
| QQQ gap | 6 / 5 / 4 | 40% | +0.06 | −0.26% |
| SNDK in-session | 3 / 20 / 5 | 21% | −0.26 | −5.82% |
| SNDK gap | 4 / 10 / 5 | 32% | −0.37 | −9.34% |

R/R terciles of in-session signals won 20%, 20% and 26%; Spearman(R/R, trade %) = +0.10. A stop
20% inside the box sits within normal 5-min noise.

## Finding 6 — Wide-box fades over 30 sessions

Same data. Boxes ≥ N bar lengths tall fade their edges and stop-and-reverse on the break:

| `--reversion-box-bars` | Signal | Trades | Win | Avg R | Total |
|---|---|---|---|---|---|
| 6 | **fade** | 16 | 56% | **+0.72** | **+4.39%** |
| | stop-and-reverse | 4 | 50% | +0.34 | +0.55% |
| | narrow-box breakout | 54 | 20% | −0.32 | −8.00% |
| 5 | **fade** | 28 | 54% | +0.53 | **+7.08%** |
| | stop-and-reverse | 8 | 25% | −0.33 | −2.54% |
| 4 | **fade** | 51 | 47% | +0.33 | +6.01% |
| | stop-and-reverse | 18 | 22% | −0.36 | −5.16% |

Fades were positive on both tickers at every threshold; 83% were in profit after 60 min at 6.
Finding 7 shows this window was unrepresentative.

## Finding 7 — Fades fail on a longer window (Jun 1 – Oct 2)

QQQ + SNDK, 85 sessions per ticker, `--reversion-box-bars 6`, no regime filter:

| Signal | Trades | Win | Avg R | Total |
|---|---|---|---|---|
| narrow-box breakout | 182 | 35% | +0.03 | +7.53% |
| fade | 47 | 43% | +0.09 | **−3.68%** |
| stop-and-reverse | 16 | 19% | −0.54 | **−7.30%** |
| gap | 98 | 42% | −0.08 | +8.23% |

By month:

| Month | Fades | Fade win | Fade total | Narrow-box breakout total |
|---|---|---|---|---|
| June | 11 | 27% | −3.36% | **+18.70%** |
| July | 15 | 33% | −5.10% | +0.63% |
| August | 10 | 50% | −0.02% | −3.88% |
| September | 11 | 64% | **+4.79%** | −8.84% |

June trended (breakouts paid, fades lost); September ranged (the reverse). The 30-session test
sat entirely in the range-bound stretch. Lower thresholds made fades worse: 97 fades / −10.22% at
5, 164 / −7.18% at 4. SNDK trended (breakouts +9.35%, gap signals +12.66%, fades −4.85%); QQQ was
roughly flat for every type.

## Finding 8 — Regime switch: the 5-min MA stack helps

Same window, all signal types. Rules: type only (trend → breaks, range → fades) or type +
direction (trend up → breakouts, trend down → breakdowns, range → fades).

| Filter | Trades | Win | Avg R | Total | Jun | Jul | Aug | Sep |
|---|---|---|---|---|---|---|---|---|
| none | 345 | 37% | −0.02 | +4.39% | +34.5 | −14.1 | −13.0 | −4.4 |
| MA stack, type | 151 | 41% | −0.01 | +9.83% | +14.1 | −11.8 | +6.8 | +0.2 |
| **MA stack, type + direction** | 139 | 42% | +0.00 | **+8.98%** | +12.8 | −12.2 | +6.9 | +1.8 |
| ↳ excluding stop-and-reverse | 131 | 44% | +0.05 | **+14.06%** | +16.1 | −10.4 | +6.9 | +1.8 |
| efficiency ratio (78 bars, 0.3), type | 75 | 36% | −0.04 | −21.77% | | | | |
| efficiency ratio (78 bars, 0.2), type | 127 | 40% | +0.03 | −10.06% | | | | |
| efficiency ratio (234 bars, 0.2), type | 70 | 40% | +0.11 | −5.15% | −0.3 | −13.2 | +2.6 | +5.8 |

Built in as `--regime-switch ma-stack` (type + direction), it gives **145 trades, +9.41%**
(QQQ −1.34%, SNDK +10.74%; by month +12.9 / −12.0 / +5.7 / +3.0). The small difference from the
prototype is intentional: a signal the regime skips no longer suppresses a later repeat. By type:
narrow-box breakouts +9.06% (89), fades +3.56% (28), gap +0.99% (21), stop-and-reverse **−4.21%**
(7, 14% win).

At signal bars the stack read range 58%, up 22%, down 20%, so the switch cut the signal rate to
about 0.8 per session.

## Finding 9 — Opening-range bias: negative

`--regime-switch opening-range`: below the opening-range low and within N average bar ranges
under MA200 → only short box tops; the mirror → only buy box bottoms; otherwise MA stack. Same
window, 12 configurations; selected:

| Configuration | Trades | Per day | Total | Bias fades only |
|---|---|---|---|---|
| MA stack (default) | 145 | 0.83 | **+9.41%** | — |
| OR 3 bars, distance 5 | 156 | 0.90 | +5.16% | 18, 22% win, −3.34% |
| OR 3 bars, distance 10 | 138 | 0.79 | −3.65% | 28, 32% win, −2.63% |
| OR 4 bars, distance 20 | 104 | 0.60 | +1.26% | 28, 36% win, −3.66% |
| OR 6 bars, distance 5 | 150 | 0.86 | +8.38% | 11, 36% win, +0.02% |
| OR 6 bars, distance 20 | 101 | 0.58 | +2.13% | 18, 33% win, −2.50% |

Bias fades lost in 11 of 12 configurations (22–36% win), were rare (0.06–0.17 per day) and
crowded out the MA-stack signals.

Is the bias itself directional? Share of sessions where price moved the bias's way in the hour
after the first biased bar:

| | OR 3 bars, distance 10 | OR 3 bars, distance 40 | OR 6 bars, distance 40 |
|---|---|---|---|
| QQQ | 35% | 37% | 47% |
| SNDK | 59% | 58% | 45% |

The condition held on 77–92% of sessions, so it is barely selective, and its direction flips
with ticker and opening-range length. For QQQ the opening-range break mostly reversed within the
hour. This differs from the op_momentum strategy, which enters *at* the break with a trailing MA
stop on daily-selected tickers.

## Finding 10 — Stop-and-reverse off by default

`--stop-and-reverse` added, default off: a wide-box break that follows a fade on the same box no
longer fires (the box still retires on the break). Same window and trade rules:

| Configuration | Trades | Per day | Win | Avg R | Total | QQQ | SNDK | Jun | Jul | Aug | Sep |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **defaults (ma-stack, S&R off)** | 138 | 0.79 | 43% | **+0.05** | **+13.62%** | −0.32 | +13.94 | +16.2 | −11.0 | +5.7 | +3.0 |
| ma-stack + `--stop-and-reverse` | 145 | 0.83 | 41% | +0.01 | +9.41% | −1.34 | +10.74 | +12.9 | −12.0 | +5.7 | +3.0 |
| `--regime-switch off`, S&R off | 328 | 1.89 | 38% | +0.00 | +12.89% | −5.47 | +18.37 | +38.2 | −10.8 | −10.8 | −5.1 |

The new default is better or equal in every month and on both tickers. Turning the regime switch
off reaches a similar total only through June, with three losing months after it.

## Finding 11 — Catching SNDK's large and medium legs (Aug 3 – Oct 2)

Legs are measured **independently of the `Wave` module**, as a hindsight zigzag on 5-min closes
within each session: a leg ends when price reverses ≥ 0.25 × ADR (prior 20 sessions'
high−low). Large ≥ 0.75 × ADR, medium ≥ 0.4 × ADR. One zigzag leg is usually 2–4 script waves.
A leg is *caught* when a signal in its direction fires before half the leg is done.

SNDK had 52 legs (7 large, median 0.97 × ADR; 45 medium, median 0.55 × ADR).

| Configuration | Large caught | Medium caught | Signals against the leg |
|---|---|---|---|
| defaults | 1 / 7 | 3 / 45 | 5 |
| wave size 1.0 or 1.5, lookback 6 waves, or both | 1 / 7 | 3 / 45 | 5 – 10 |
| `--regime-switch off` | 2 / 7 | 8 / 45 | 11 |
| opening-range breakout (first close outside the first 3 bars) | 3 / 7 | 9 / 45 | — |

- **30 of the 52 legs, including 5 of the 7 large, start in the first 15 minutes** — no box can
  exist yet. In the first half of other missed legs, most bars had no box; with a box, price was
  usually still inside it.
- **Exits:** a caught leg's fixed target captured a median 34–41% of the leg, against 63–100%
  if held to the leg's end. On the same 35 default signals:

| Exit | Win | Avg % | Total |
|---|---|---|---|
| fixed target (current) | 43% | +0.215 | +7.54% |
| session close | 43% | +0.421 | +14.74% |
| close across MA8 | 31% | +0.215 | +7.51% |
| **give-back** (out after giving back 32% of the best open profit, once up ≥ 0.25 × risk) | **54%** | **+0.551** | **+19.29%** |

The give-back values were not tuned (32% matches `daily_longest_leg.py`'s retrace).

## Finding 12 — Entry rules for the opening up leg

Target: up legs starting in the first 15 minutes (≥ 0.4 × ADR, same zigzag; about a third of
sessions). 13 long entry rules, decided at a bar's close by 10:30, each with its own stop and
the give-back exit; plus a baseline of buying the 09:35 close every day (stop at the first
bar's low). Samples: SNDK Aug 3 – Oct 2 2026 (44 sessions), SNDK Jun 2025 – Jul 2026 (277, out
of sample), and 20 other tickers Jun – Oct 2026 (1,740). Every rule was mirrored to the short
side to separate a real edge from the period's bull drift.

Average return per trade (give-back exit), trades in brackets:

| Rule | SNDK Aug–Oct | SNDK earlier | 20 tickers | Short mirror vs short baseline |
|---|---|---|---|---|
| baseline: buy 09:35 every day | +0.77 (44) | +0.33 (276) | +0.10 (1,719) | short baseline −0.24 / +0.04 / −0.02 |
| **green first bar** | **+0.85** (23) | **+0.73** (152) | **+0.14** (810) | **beats it in all 3** (−0.21 / +0.25 / −0.00) |
| 2-bar impulse ≥ 0.25 × ADR | +0.70 (5) | +0.65 (58) | −0.05 (260) | beats it strongly (+0.40 / +1.18 / +0.16) |
| opening-range breakout, 1 bar | +0.57 (22) | +0.16 (149) | −0.05 (845) | beats it (−0.12 / +0.31 / +0.01) |
| opening-range breakout, 2 bars | +0.22 (20) | +0.12 (127) | −0.11 (726) | mixed |
| 2-bar breakout + gap up | +0.82 (9) | +0.50 (70) | −0.16 (377) | no |

Large opening up legs caught: green first bar 3/5, 17/36, 74/187 (52–61% win); 1-bar breakout
5/5, 27/36, 126/187; baseline 4/5, 24/36, 130/187.

- Buying every day was profitable but shorting every day was not, so much of the long-side
  profit is drift. **Only the first-bar direction beat its own baseline on both sides in every
  sample.** Added as `--opening-drive` (off by default).
- Breakouts catch the most legs but buy after the move and lose to the baseline on longs.
- The 2-bar impulse works for SNDK and on the short side, but not for longs on the wider pool.
- Caveats: both periods were bull markets (SNDK rose enormously), no costs (+0.14% per trade on
  the pool is thin), entry assumes a fill at the 09:35 close, give-back values untuned, leg
  thresholds are judgement calls.

## Finding 13 — Exit models on the default signals (Jun 1 – Oct 2)

First run of the committed backtest (`wave_risk_reward_backtest.py --compare-exits`), defaults,
QQQ + SNDK, no costs. The target row reproduces Finding 10 exactly.

| Exit | Trades | Win | Avg % | Avg R | Total | Exits (target / giveback / stop / close) |
|---|---|---|---|---|---|---|
| target (current) | 138 | 43% | +0.099 | +0.05 | +13.62% | 21 / 0 / 72 / 45 |
| **giveback** (32%, armed at 0.25 × risk) | 138 | **57%** | **+0.203** | +0.09 | **+28.01%** | 0 / 83 / 43 / 12 |
| session close | 138 | 42% | +0.189 | +0.16 | +26.09% | 0 / 0 / 72 / 66 |

Letting winners run roughly doubles the total; the give-back exit also lifts the win rate. Same
caveats as before: 2 tickers, 4 months, no costs, give-back values untuned.

## Finding 14 — Opening drive + exits, with costs (Jun 1 – Oct 2)

QQQ + SNDK, default box signals, 5 bps round trip unless noted (`wave_risk_reward_backtest.py`):

| Configuration | Trades | Win | Total | QQQ | SNDK | Jun | Jul | Aug | Sep |
|---|---|---|---|---|---|---|---|---|---|
| defaults, `--exit target`, no costs | 138 | 43% | +13.62% | −0.32 | +13.94 | +16.2 | −11.0 | +5.7 | +3.0 |
| defaults, `--exit giveback`, no costs | 138 | 57% | +28.01% | −1.04 | +29.05 | | | | |
| defaults, `--exit eod` | 138 | 38% | +19.19% | −0.91 | +20.11 | | | | |
| defaults, `--exit giveback` | 138 | 46% | +21.11% | −4.39 | +25.50 | +7.9 | −3.4 | +7.2 | +10.0 |
| `--opening-drive long`, `--exit giveback` | 219 | 47% | +40.82% | −5.13 | +45.94 | | | | |
| `--opening-drive both`, `--exit giveback` | 311 | 46% | **+49.45%** | −5.80 | +55.25 | +0.7 | +19.0 | +11.8 | +20.9 |
| **`--opening-drive both`, `--exit eod`** | 311 | 35% | **+75.04%** | −8.51 | +83.55 | +13.7 | +16.5 | +26.2 | +21.5 |

By signal type for the two best rows (giveback / eod): opening drive +28.34% / +55.85% (173
trades), gap +15.83% / +9.54% (21), narrow-box breaks +5.45% / +6.91% (89), fades −0.17% /
+2.75% (28). October (2 sessions) lost about 3% in both.

- The opening drive is the main contributor and every full month is positive in both rows.
- Holding to the close beats the give-back exit on SNDK in this period — consistent with SNDK's
  strong up-drift. The give-back exit wins more often (46% vs 35%) and is the more conservative
  choice; Finding 12's mirror test is the evidence that the first-bar direction is not pure drift.
- **QQQ loses in every row with costs** — this configuration is not a QQQ strategy.

---

## Current best configuration (as of 2026-10-04)

**Highest total:** default box signals + `--opening-drive both`, held to the session close.
**More conservative:** the same signals with the give-back exit. Both from Finding 14 (QQQ +
SNDK, Jun 1 – Oct 2 2026, 5 bps costs):

| Configuration | Trades | Win | Total | QQQ | SNDK |
|---|---|---|---|---|---|
| `--opening-drive both --exit eod` | 311 | 35% | **+75.04%** | −8.51% | +83.55% |
| `--opening-drive both --exit giveback` | 311 | 46% | **+49.45%** | −5.80% | +55.25% |

```bash
cd /Users/victorhuang/work/alpha_tech_tracker
source ~/.pyenv/versions/alpha_tech_tracker/bin/activate
export PYTHONPATH=$PWD

# 1. Backtest the best configuration (reproduces +75.04% / +49.45% below)
python -m alpha_tech_tracker.op_momentum_strategy.analysis_scripts.wave_risk_reward_backtest \
  --tickers QQQ SNDK --start 2026-06-01 --end 2026-10-02 \
  --opening-drive both --exit eod --cost-bps 5

python -m alpha_tech_tracker.op_momentum_strategy.analysis_scripts.wave_risk_reward_backtest \
  --tickers QQQ SNDK --start 2026-06-01 --end 2026-10-02 \
  --opening-drive both --exit giveback --cost-bps 5

# 2. Chart the same signals (the chart has no exit model)
python -m alpha_tech_tracker.op_momentum_strategy.analysis_scripts.wave_risk_reward \
  --tickers QQQ SNDK --days 87 --end 2026-10-02 --opening-drive both
```

Every other setting is a default:

```
--regime-switch ma-stack (no --stop-and-reverse) --reversion-box-bars 6 --box-stop-ratio 0.2
--min-box-waves 2 --small-wave-ratio 1.5 --max-box-height-ratio 2.0
--min-wave-bar-ranges 2 --lookback-waves 10 --repeat-overlap-bars 1.0 --min-risk-pct 0.001
--giveback 0.32 --giveback-arm-r 0.25 (giveback exit only)
```

**Read before using:** over full-year 2026 this configuration (long-only drive) made +156.66% on
SNDK and −8.74% on META —
[`wave_risk_reward_strategy_ticker_params_tunning.md`](wave_risk_reward_strategy_ticker_params_tunning.md).
The profit is SNDK's (QQQ loses in every configuration with costs), both
periods tested were bull markets, the 5 bps cost and 09:35 fill are assumptions, and several
settings were chosen on this same data.

| Setting | Source |
|---|---|
| `--opening-drive both` | Finding 12 (beats a trade-every-day baseline on both sides); Finding 14 |
| `--exit eod` / `--exit giveback` | Findings 11, 13, 14 |
|---|---|
| `ma-stack` | Finding 8 — beat no filter, efficiency ratio and opening range |
| stop-and-reverse off | Finding 10 — the one signal type that lost in every test |
| `--box-stop-ratio 0.2` | user choice; Finding 3 |
| `--reversion-box-bars 6` | best per-trade on Jun–Oct (Finding 7); 5 looked better only on 30 sessions |
| box `2 / 1.5 / 2.0` | Finding 4 — tuned for signal count, not P&L |
| `--min-wave-bar-ranges 2` | Finding 2 — tuned for wave counts, not P&L |
| `--lookback-waves`, `--repeat-overlap-bars`, `--min-risk-pct` | not swept |

## Open questions and next steps

0. **Give-back exit and opening drive** — the committed backtest now has the give-back exit and
   costs; next, test `--opening-drive` and the give-back exit on a bear period (for example 2022
   from cached history) and on a wider ticker set. Recheck Findings 11–12 with legs built from
   the `Wave` module.

1. ~~Drop stop-and-reverse~~ — done, off by default (Finding 10).
2. **Validate on a wider sample** — 10+ cached tickers over 6–12 months before trusting any
   setting.
3. **Longer-horizon regime** — the 5-min stack only sees about 2.5 days and cannot tell June
   from September. Test a QQQ-based regime (the op_momentum QQQ MA8 filter has multi-year
   support) or a daily MA regime as of the prior close.
4. **Signal rate** — the regime switch leaves about 0.8 signals per session against the 1–3
   target.
5. **Costs** — no spread or slippage modelled; QQQ's per-trade moves are small enough for this to
   matter.

## Reproduction

`analysis_scripts/wave_risk_reward_backtest.py` reproduces the trade-based findings with the
trade rules in [Method](#method) (usage in the guide's *Backtesting* section). For example:

```bash
# Findings 10 and 13 (138 trades, +13.62% target / +28.01% giveback)
... wave_risk_reward_backtest --tickers QQQ SNDK --start 2026-06-01 --end 2026-10-02 --compare-exits
# Finding 7 (no regime filter, stop-and-reverse on)
... wave_risk_reward_backtest --tickers QQQ SNDK --start 2026-06-01 --end 2026-10-02 \
    --regime-switch off --stop-and-reverse
# Finding 11 (leg catch, 1/7 large, 3/45 medium)
... wave_risk_reward_backtest --tickers SNDK --start 2026-08-03 --end 2026-10-02 --legs
```

The forward-return tables (Finding 5), the efficiency-ratio prototype (Finding 8), the
opening-range direction check (Finding 9) and the opening-leg rule study with its mirror test
(Finding 12) came from one-off scripts that were not committed.

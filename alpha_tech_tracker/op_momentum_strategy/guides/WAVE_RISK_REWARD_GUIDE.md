# Wave Risk/Reward Guide

`analysis_scripts/wave_risk_reward.py` counts price waves on 5-min bars, finds consolidation
boxes from those waves, flags breakout / breakdown / fade signals, and computes long and short
risk/reward at every bar. Every metric is point-in-time: bars are replayed one at a time, so a
bar's numbers only use data known at its close.

It answers: *where are the consolidations right now, which way did price leave them, and what
did the trade look like at that moment?*

> **Status (2026-10-04):** an analysis and charting tool, not a validated strategy. No
> configuration has shown a reliable edge yet — see
> [`research/findings/WAVE_RISK_REWARD_FINDINGS.md`](../research/findings/WAVE_RISK_REWARD_FINDINGS.md)
> before trading any of its signals.

---

## Best configuration so far — copy and run

From [Finding 14](../research/findings/WAVE_RISK_REWARD_FINDINGS.md#finding-14--opening-drive--exits-with-costs-jun-1--oct-2)
(QQQ + SNDK, Jun 1 – Oct 2 2026, 5 bps round-trip costs): default box signals plus the opening
drive made **+75.04%** held to the session close and **+49.45%** with the give-back exit —
almost all of it from SNDK; QQQ lost in every configuration once costs were included.

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

To run it on other tickers or dates, change `--tickers`, `--start`/`--end` (backtest) or
`--days`/`--end` (chart).

### Most consistent signal so far — wave pullback longs

From [Finding 15](../research/findings/WAVE_RISK_REWARD_FINDINGS.md#finding-15--wave-pullback-buy-the-bounce-after-a-strong-wave):
buy the bounce after a strong up wave pulls back into its 38.2–61.8% retracement, held past the
impulse high with `--exit target-trail` (5 bps costs). Positive on all three tickers in both
windows; smaller per ticker than the opening drive on SNDK, but the only setup that works on AMD:

| Ticker | Jul 2 – Oct 2 | Jan 2 – Jul 1 (not used to build it) |
|---|---|---|
| AMD | 18 trades, 61% win, **+4.36%** | 27 trades, 56% win, **+5.55%** |
| SNDK | 17 trades, 59% win, **+5.16%** | 35 trades, 57% win, **+10.96%** |
| META | 18 trades, 39% win, **+1.35%** | 32 trades, 62% win, **+1.62%** |

```bash
# Backtest the pullback on its own (box signals off)
python -m alpha_tech_tracker.op_momentum_strategy.analysis_scripts.wave_risk_reward_backtest \
  --tickers AMD --start 2026-07-02 --end 2026-10-02 \
  --no-box-signals --wave-pullback long --exit target-trail --cost-bps 5

# Chart it
python -m alpha_tech_tracker.op_momentum_strategy.analysis_scripts.wave_risk_reward \
  --tickers AMD --days 21 --end 2026-09-30 --no-box-signals --wave-pullback long
```

---

## Setup

```bash
cd /Users/victorhuang/work/alpha_tech_tracker
source ~/.pyenv/versions/alpha_tech_tracker/bin/activate
export PYTHONPATH=$PWD
```

Bars come from `fetch_bars()` (Alpaca, cached under `market_data/cache/`), so a cache miss needs
`ALPACA_API_KEY` / `ALPACA_SECRET_KEY`. With the default `--feed sip` the end date is clamped to
the last completed session (today's session becomes available after 20:00 ET). Charts use
plotly ≥ 4.7 for `rangebreaks`; the repo pins 7.1.0.

## Quick start

```bash
# Last 5 sessions of NVDA (defaults)
python -m alpha_tech_tracker.op_momentum_strategy.analysis_scripts.wave_risk_reward

# Two tickers over 30 sessions
python -m alpha_tech_tracker.op_momentum_strategy.analysis_scripts.wave_risk_reward \
  --tickers QQQ SNDK --days 30

# A fixed window: Jun 1 - Oct 2 2026 (--days counts sessions, not calendar days)
python -m alpha_tech_tracker.op_momentum_strategy.analysis_scripts.wave_risk_reward \
  --tickers QQQ SNDK --days 87 --end 2026-10-02
```

A run takes a few seconds per ticker with a warm cache and writes one HTML chart per ticker to
`charts/wave_rr/<TICKER>_<first>_<last>.html`.

---

## How it works

### 1. Bars and moving averages
Regular-hours 5-min bars only (09:30–16:00 ET). MA 8/20/50/200 are simple moving averages of
the 5-min closes and run continuously across sessions (MA200 ≈ 2.6 sessions). The script loads
5 extra sessions before the display window to warm them up.

### 2. Waves
Bars are fed into `alpha_tech_tracker.wave.Wave`:
- A wave starts at its first bar's open and tracks new highs/lows on closes. Its direction is
  `up` when it set more new highs than lows, `down` otherwise (`n/a` until it has one).
- A wave ends on a 23.6% retracement of its range, once it is at least 7 bars long and its range
  reaches the minimum wave size; it is force-ended after 78 bars.
- **Minimum wave size scales with volatility:** `--min-wave-bar-ranges` (default 2) × the
  average 5-min bar range % over the trailing `--volatility-window-bars` (78) bars, updated every
  bar. `--min-wave-price-change` pins a fixed fraction instead.
- **Waves never span the overnight gap:** the wave in progress ends at each session's last bar.
  Wave history and stats still carry across sessions.

### 3. Consolidation box
Walking back from the latest finished wave over the lookback window (`--lookback-waves 10`, or
`--lookback-bars N`):
- at least `--min-box-waves` (2) consecutive waves, each ≤ `--small-wave-ratio` (1.5) × the
  median lookback wave size,
- spanning ≤ `--max-box-height-ratio` (2.0) × that median.

The box runs from their lowest low to their highest high. Each box also records its **bar
length** — the average high−low of the 5-min bars inside it.

**Narrow box** (height < `--reversion-box-bars` × bar length, default 6): a breakout setup.
Retires once the wave in progress grows past the small-wave size.

**Wide box** (height ≥ 6 bar lengths): a range. Retires when it breaks out or down.

### 4. Signals

| Signal | Box | Fires on | Stop | Target |
|---|---|---|---|---|
| `breakout` | narrow | first close above the box high | box high − `--box-stop-ratio` × height (0.2) | entry + max(box height, median up-wave) |
| `breakdown` | narrow | first close below the box low | box low + 0.2 × height | entry − max(box height, median down-wave) |
| `fade short` | wide | first close within 1 bar length of the box high | box high + 1 bar length | box low |
| `fade long` | wide | first close within 1 bar length of the box low | box low − 1 bar length | box high |
| `breakout` | wide | first close above box high + 1 bar length | box high | entry + max(box height, median up-wave) |
| `breakdown` | wide | first close below box low − 1 bar length | box low | entry − max(box height, median down-wave) |
| `drive long` | — | first bar of the session closes green (`--opening-drive`) | first bar's low | entry + median up-wave |
| `drive short` | — | first bar of the session closes red (`--opening-drive`) | first bar's high | entry − median down-wave |
| `pullback long` | — | after a strong up wave touched its 38.2% retracement, first green bar closing between the 61.8% level and the impulse high (`--wave-pullback`) | 78.6% retracement | impulse high |
| `pullback short` | — | mirror after a strong down wave (red bar) | 78.6% retracement | impulse low |

- **Stop-and-reverse is off by default.** A wide-box breakout/breakdown that follows a fade on
  the same box would stop the fade out and reverse it. It lost in every test, so it only fires
  with `--stop-and-reverse`; otherwise it is kept in `reversal_skipped_signals` (the box still
  retires on the break). A wide-box break with no fade before it fires either way.
- **Opening drive is off by default.** `--opening-drive both|long|short` adds the first-bar
  signals above, at most one per session. They need no box and are not gated by the regime
  switch or repeat suppression. In testing they were traded with a *give-back* exit — out once
  32% of the best open profit is given back, after a move of at least 0.25 × risk — rather than
  the target; this script reports the target-based R/R only.
- **Wave pullback is off by default.** `--wave-pullback both|long|short` adds the pullback
  signals above. An impulse is a finished wave at least `--strong-wave-ratio` (2) × the median
  lookback wave size; waves force-ended at the session close don't count. A setup is cancelled
  when price hits the 78.6% stop or closes beyond the impulse extreme before an entry, and at
  the session close. Not gated by the regime switch or repeat suppression. Shorts lost in
  testing — use `long`. Best traded with the backtest's `target-trail` exit, since R/R to the
  impulse extreme is usually only 0.5–1.5.
- **Switches:** `--no-box-signals` turns off every box signal (boxes and their R/R are still
  computed and drawn), so the opening drive or the pullback can run on their own.
  `--no-gap-signals` drops gap signals and keeps them in `gap_skipped_signals`.
- Each box fires each signal at most once.
- **Gap signals:** a signal on a session's first bar from a box formed in an earlier session is
  labelled `gap breakout`, `gap fade short`, etc.
- **Repeat suppression:** the same signal in the same session is dropped when its box edge sits
  within `--repeat-overlap-bars` (1.0) × the session's average bar range of the edge that
  already fired, unless a different signal fired in between.
- **Risk floor:** risk is at least `--min-risk-pct` (0.1%) of price, so a stop sitting on the
  price cannot blow up the ratio.
- Without a box, the per-bar R/R uses the most recent swing (down-wave low for longs, up-wave
  high for shorts) as the stop and the median wave size as the target.

### 5. Regime switch

| `--regime-switch` | Behaviour |
|---|---|
| `ma-stack` (default) | Each bar is **up** when MA8 > MA20 > MA50 > MA200, **down** when fully reversed, **range** otherwise. Up fires only breakouts, down only breakdowns, range only fades. |
| `opening-range` | After the first `--opening-range-bars` (3) bars, a bar is **bearish** while its close is below the opening-range low and below MA200 by ≤ `--max-ma200-distance-bars` (10) × the average bar range; **bullish** on the mirror. Bearish only shorts the top zone of any box (narrow or wide), bullish only buys the bottom zone. Bars without a bias fall back to `ma-stack`. |
| `off` | Every signal fires. |

Signals the regime blocks are kept in `regime_skipped_signals` and counted in the summary. The
`ma-stack` regime only looks at the ticker's own 5-min MAs — no QQQ and no daily timeframe.

---

## Options

| Group | Option | Default | Meaning |
|---|---|---|---|
| Run | `--tickers` | `NVDA` | One or more tickers |
| | `--days` | 5 | Trailing sessions to display and summarize |
| | `--end` | today | Last session (YYYY-MM-DD) |
| | `--feed` | `sip` | `sip` or `iex` |
| | `--out-dir` | `charts/wave_rr` | Chart output directory |
| Waves | `--min-wave-bar-ranges` | 2 | Minimum wave size in average 5-min bar ranges |
| | `--volatility-window-bars` | 78 | Bars in the trailing average bar range |
| | `--min-wave-price-change` | — | Fixed minimum as a fraction of price (overrides the above) |
| | `--lookback-waves` | 10 | Finished waves in the stats/box window |
| | `--lookback-bars` | — | Use recent waves covering ≥ N bars instead |
| Boxes | `--min-box-waves` | 2 | Consecutive small waves per box |
| | `--small-wave-ratio` | 1.5 | Box wave ≤ this × median wave size |
| | `--max-box-height-ratio` | 2.0 | Box height ≤ this × median wave size |
| | `--reversion-box-bars` | 6 | Wide-box threshold in bar lengths (999 disables fades) |
| Signals | `--stop-and-reverse` | off | Fire the breakout/breakdown that reverses a stopped wide-box fade |
| | `--opening-drive` | `off` | First-bar signal: `both`, `long` (green bar) or `short` (red bar) |
| | `--wave-pullback` | `off` | Pullback after a strong wave: `both`, `long` or `short` |
| | `--strong-wave-ratio` | 2 | Impulse threshold in median lookback wave sizes |
| | `--pullback-touch-fib` | 0.382 | Retracement the pullback must touch before an entry |
| | `--pullback-floor-fib` | 0.618 | Deepest retracement an entry bar may close at |
| | `--pullback-stop-fib` | 0.786 | Retracement where the stop sits (1.0 = impulse start) |
| | `--pullback-target-ext` | 1.0 | Target = impulse start + ext × impulse size (1.0 = impulse extreme) |
| | `--no-box-signals` | — | Turn off breakouts, breakdowns and fades |
| | `--no-gap-signals` | — | Drop gap signals |
| R/R | `--box-stop-ratio` | 0.2 | Breakout stop back inside the box (1.0 = opposite edge) |
| | `--min-risk-pct` | 0.001 | Risk floor as a fraction of price |
| | `--repeat-overlap-bars` | 1.0 | Same-session repeat suppression distance |
| Regime | `--regime-switch` | `ma-stack` | `ma-stack`, `opening-range` or `off` |
| | `--opening-range-bars` | 3 | Opening-range length, normally 3–6 (`opening-range` only) |
| | `--max-ma200-distance-bars` | 10 | MA200 band for the bias (`opening-range` only) |

### Examples

```bash
# Every signal type, no regime filter
... wave_risk_reward --tickers QQQ SNDK --days 30 --regime-switch off

# Breakouts only: no wide-box fades, stop at the opposite box edge
... wave_risk_reward --tickers NVDA --days 10 --reversion-box-bars 999 --box-stop-ratio 1.0

# Opening-range bias with a 6-bar opening range and a wider MA200 band
... wave_risk_reward --tickers SNDK --days 30 --regime-switch opening-range \
    --opening-range-bars 6 --max-ma200-distance-bars 20

# Opening-drive signals on SNDK (buy a green first bar, short a red one)
... wave_risk_reward --tickers SNDK --days 44 --end 2026-10-02 --opening-drive both

# Coarser waves (about 4-5 per session instead of about 6)
... wave_risk_reward --tickers TSLA --days 10 --min-wave-bar-ranges 3
```

---

## Output

### Console
One block per ticker:

```
QQQ   539 waves (251 up / 284 down)   25 breakout   25 breakdown   7 fade long   11 fade short   (8 gap, 0 stop-and-reverse, 21 repeats suppressed, 116 skipped by regime, 3 stop-and-reverse skipped)
  2026-06-01 10:55  breakout        @ 739.47  up     breakout  box 735.81-739.40  R/R  4.56  stop 738.68  target 743.06
  2026-06-01 13:25  breakout        @ 743.42  up     breakout  box 740.33-742.95  R/R  2.64  stop 742.43  target 746.04
  2026-06-02 11:05  fade short      @ 744.82  range  reversion box 740.21-745.57  R/R  3.05  stop 746.33  target 740.21
  ...
latest 2026-10-02 15:55
  close 749.55  regime range
  MA8 749.40 MA20 749.04 MA50 749.27 MA200 744.88
  wave #699 up (30 bars)
  lookback 10 waves: 5 up / 5 down
  breakout box 747.78-750.75
  long R/R n/a (stop n/a, tgt n/a)
  short R/R n/a (stop n/a, tgt n/a)
chart: charts/wave_rr/QQQ_2026-06-01_2026-10-02.html
```

Each signal line shows time, label, price, regime at the bar, box mode (`breakout` = narrow,
`reversion` = wide) and range, and the R/R with stop and target; `(stop & reverse)` marks a
breakout that stopped a fade out (only with `--stop-and-reverse`). The `latest` block is the snapshot at the last bar. R/R reads
`n/a` when price sits inside a narrow box between the two breakout stops, as above.

### Chart
- **Top panel:** candles, MA 8/20/50/200, up/down wave legs (start price → extreme), boxes (blue
  = narrow, orange = wide), signal markers (filled = in-session, hollow = gap; green/red =
  breakout/breakdown, cyan/orange = fade long/short, diamonds = opening drive, circles = wave
  pullback), and dotted
  opening-range high/low lines (first `--opening-range-bars` bars) for every session.
- **Bottom panel:** long and short R/R per bar, capped at 10, with a dotted line at 1.
- **Hover** any bar for its close, regime, MAs, wave number and direction, lookback up/down
  counts, box, and long/short R/R with stops and targets.
- Overnight hours, weekends and market holidays are removed from the time axis.

### Using it from Python
`analyze_bars(bars, WaveRiskRewardParams(...))` returns `snapshots` (one row per bar with every
metric above), `waves`, `boxes`, `signals`, `suppressed_signals`, `regime_skipped_signals` and
`reversal_skipped_signals`.
`bars` is a regular-hours frame with lowercase OHLC and `ma_<period>` columns — build it with
`add_moving_averages(regular_hours(raw_bars))`.

---

## Backtesting

`analysis_scripts/wave_risk_reward_backtest.py` turns every signal into one trade, using the same
signal options as the charting script (all of the options above except `--days`/`--out-dir`):

```bash
# Defaults, every exit model side by side
python -m alpha_tech_tracker.op_momentum_strategy.analysis_scripts.wave_risk_reward_backtest \
  --tickers QQQ SNDK --start 2026-06-01 --end 2026-10-02 --compare-exits

# Opening drive with the give-back exit and 5 bps round-trip costs, trades to CSV
... wave_risk_reward_backtest --tickers SNDK --start 2026-08-03 --end 2026-10-02 \
    --opening-drive both --exit giveback --cost-bps 5 --csv-out trades.csv

# Leg-catch report: how many large/medium hindsight legs the signals catch
... wave_risk_reward_backtest --tickers SNDK --start 2026-08-03 --end 2026-10-02 --legs
```

| Option | Default | Meaning |
|---|---|---|
| `--start` / `--end` | required / today | Backtest window (sessions); 45 calendar days before `--start` are loaded for warm-up |
| `--exit` | `target` | `target`: the signal's stop or target. `target-trail`: the stop until the target is reached, then the give-back trail instead of taking profit. `giveback`: the stop, or once up `--giveback-arm-r` × risk, the first close that gives back `--giveback` of the best open profit. `eod`: the stop, else the session close |
| `--compare-exits` | off | Also print all three exits side by side |
| `--giveback` / `--giveback-arm-r` | 0.32 / 0.25 | Give-back exit settings |
| `--cost-bps` | 0 | Round-trip cost taken off every trade |
| `--legs` | off | Leg-catch report (all legs and opening legs, large and medium) |
| `--leg-reversal-adr` / `--large-leg-adr` / `--medium-leg-adr` | 0.25 / 0.75 / 0.4 | Leg definition, in multiples of ADR |
| `--csv-out` | — | Write every trade (chosen exit) to CSV |

Trade rules: entry at the signal bar's close; every exit mode exits at the session close at the
latest; a bar touching both stop and target counts as the stop; a gap through the stop fills at
the bar's open; signals on a session's last bar are skipped. Times in the CSV are bar *open*
times (Alpaca convention), so an entry stamped 09:30 filled at that bar's 09:35 close. The
report shows results overall and by signal type, ticker and month. Tests:
`tests/op_momentum_trade_engine/test_wave_risk_reward_backtest.py`.

---

## Caveats

- **Bar order:** 5-min OHLC hides whether the high or low printed first. Waves and signals use
  closes; the trade evaluation in the findings doc counts a bar that hits both stop and target as
  a stop.
- **The last wave is unfinished:** its direction can still flip, and the wave before it can be
  shortened when its end moves back to the extreme.
- **Signal rate:** with the defaults, QQQ and SNDK averaged about 0.8 signals per session
  (Jun–Oct 2026); `--regime-switch off` gives about 1.9.
- **Tests:** `tests/op_momentum_trade_engine/test_wave_risk_reward.py`.

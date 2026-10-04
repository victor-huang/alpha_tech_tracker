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

- **Stop-and-reverse is off by default.** A wide-box breakout/breakdown that follows a fade on
  the same box would stop the fade out and reverse it. It lost in every test, so it only fires
  with `--stop-and-reverse`; otherwise it is kept in `reversal_skipped_signals` (the box still
  retires on the break). A wide-box break with no fade before it fires either way.
- **Opening drive is off by default.** `--opening-drive both|long|short` adds the first-bar
  signals above, at most one per session. They need no box and are not gated by the regime
  switch or repeat suppression. In testing they were traded with a *give-back* exit — out once
  32% of the best open profit is given back, after a move of at least 0.25 × risk — rather than
  the target; this script reports the target-based R/R only.
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
  breakout/breakdown, cyan/orange = fade long/short, diamonds = opening drive), and dotted
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

## Caveats

- **Bar order:** 5-min OHLC hides whether the high or low printed first. Waves and signals use
  closes; the trade evaluation in the findings doc counts a bar that hits both stop and target as
  a stop.
- **The last wave is unfinished:** its direction can still flip, and the wave before it can be
  shortened when its end moves back to the extreme.
- **Signal rate:** with the defaults, QQQ and SNDK averaged about 0.8 signals per session
  (Jun–Oct 2026); `--regime-switch off` gives about 1.9.
- **Tests:** `tests/op_momentum_trade_engine/test_wave_risk_reward.py`.

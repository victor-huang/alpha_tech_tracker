# Intraday Leg Analysis Guide

Two analysis scripts that study *when* in the session a ticker makes its big moves, measured on
5-min bars:

| Script | Question it answers | View |
|---|---|---|
| `analysis_scripts/daily_longest_leg.py` | When does each day's largest clean leg start and end? Which tickers had the strongest up/down leg on a given day, and how does that compare with their recent legs? | Hindsight — the whole day is known |
| `analysis_scripts/intraday_leg_timing.py` | If I enter a fast move after it confirms, which time of day actually pays? | Tradeable — entry at the close of the confirming bar |

Use `daily_longest_leg.py` for the daily review. Use `intraday_leg_timing.py` when evaluating
entry windows.

---

## Setup

```bash
cd /Users/victorhuang/work/alpha_tech_tracker
source ~/.pyenv/versions/alpha_tech_tracker/bin/activate
export PYTHONPATH=$PWD
```

Both scripts fetch 5-min bars through `fetch_bars()` (Alpaca, cached under `market_data/cache/`),
so they need the usual `ALPACA_API_KEY` / `ALPACA_SECRET_KEY` for a cache miss.

**Which day is "latest":** with the default `--feed sip`, the end date is clamped to the last
completed session. Today's session becomes available after extended hours close at **20:00 ET**;
before that, a run covers through the previous session, and two runs on the same day return
identical results.

---

## daily_longest_leg.py

### Daily routine

The standard daily run uses a 3-week (15-session) window over this 22-ticker set:

```bash
python alpha_tech_tracker/op_momentum_strategy/analysis_scripts/daily_longest_leg.py \
  --tickers QQQ SPOT PLTR LLY HOOD SPCX CRM MRNA CRWD COIN MSFT SNDK AMAT AMD CRWV FN APP META GOOGL SNPS RH MDB \
  --sessions 15 \
  --csv-out legs_$(date +%F).csv
```

It takes about 10 seconds with a warm cache.

### Common variations

```bash
# Top up/down legs for a specific past day (also moves the data window to end on that day)
... --sessions 15 --date 2026-09-23

# Top 10 per side, averaged against the prior 10 sessions, ranked by move relative to ADR
... --top 10 --avg-sessions 10 --top-rank-by adr

# Long baseline: where does the biggest leg start over a full year?
... --sessions 250

# "Longest running" by time instead of size (legs must still move >= 0.25x ADR)
... --rank-by duration

# Judge the 32% give-back on wicks instead of closes (stricter; legs get shorter)
... --retrace-basis wick

# Zone/summary tables only, no top-leg tables
... --top 0
```

### What counts as a leg

For every session the script finds, **with the whole day known**, the single largest up leg and
the single largest down leg that never gave back more than **32%** of its progress while it was
running. "Biggest" is the larger of the two.

- **Close basis (default):** the leg starts at a bar's open and is tracked on 5-min closes, the way
  a 5-min closing chart reads. `--retrace-basis wick` anchors on the bar low/high instead.
- **Min-progress exemption:** until a leg has travelled `--min-progress-adr` (default 0.1) × ADR it
  only has to hold above its start. Otherwise the first tick of noise off a low would count as a
  32% give-back of a near-zero move. A side effect: the `med retr` column can show give-backs above
  32%, because a dip in that early phase is measured against a tiny base. That is expected.
- **ADR:** mean regular-hours (high − low) / open over the **20 sessions before** the leg's session.
  It never uses the session's own range.

### Output sections

1. **Per ticker** — for up, down and biggest legs:
   - share of sessions whose leg **starts** and **ends** in each zone;
   - median start time, end time, duration, % and $ move, move × ADR, share of the day's
     high-low range, deepest give-back absorbed;
   - share of starts by 15-min bucket (`--bucket-minutes` to change).
2. **WHEN THE DAY'S LONGEST LEG STARTS** — one row per ticker: the most common start zone and its
   share for up/down/biggest legs, plus `big up%` (share of days the biggest leg was up).
3. **TOP N UP LEGS / TOP N DOWN LEGS ON `<date>`** — the day's strongest legs across the ticker set.

Zones (ET):

| Zone | Window |
|---|---|
| open 30m | 09:30–10:00 |
| morning | 10:00–11:30 |
| midday | 11:30–13:30 |
| afternoon | 13:30–15:00 |
| power hour | 15:00–16:00 |

The zones are different lengths, so compare shares per minute when judging them against each other.

### Reading the top-leg tables

```
 # tkr     start    end  mins      from        to   move %    move $  xADR |  5d avg %   5d avg $  n  vs avg
 1 MSFT    09:30  09:55    25    498.74    516.90   +3.64%   +$18.16  1.84 |    +1.02%     +$5.07  5   3.56x
```

| Column | Meaning |
|---|---|
| `start` | Open time of the leg's first 5-min bar |
| `end` | Close time of the bar that set the leg's extreme |
| `from` / `to` | Leg start price and extreme price |
| `move %` / `move $` | Size of the leg; `$` is **per share** |
| `xADR` | Move as a multiple of the prior 20-session ADR |
| `5d avg %` / `5d avg $` | The same ticker's average leg **in the same direction** over the `--avg-sessions` sessions **before** the day (the day itself is excluded) |
| `n` | How many of those sessions had a leg in that direction |
| `vs avg` | Day's % move ÷ the prior average; above 1 means an unusually large move for that ticker |

Ranking defaults to `% move`, which favours volatile names. `--top-rank-by adr` ranks by `xADR`
instead, so a +2% move in a quiet stock can outrank +4% in a volatile one.

### CSV output

`--csv-out` writes one row per session × kind (`up`, `down`, `biggest`) with start/end times,
zones, 15-min bucket, duration, prices, `move_pct`, `move_usd`, `adr_pct`, `adr_multiple`,
`day_range_share` and `max_retrace`. It is the easiest input for ad-hoc pivots, e.g. comparing
start-zone shares between runs.

### All flags

| Flag | Default | Meaning |
|---|---|---|
| `--tickers` | 7-ticker sample | Tickers to scan |
| `--sessions` | 250 | Trailing sessions to analyse (15 for the daily routine) |
| `--end` | today | Last session to include, clamped for SIP |
| `--date` | latest session | Day for the top-leg tables; also sets `--end` when `--end` is not given |
| `--feed` | `sip` | `sip` or `iex` |
| `--retrace` | 0.32 | Largest give-back a leg may absorb, as a fraction of its progress |
| `--retrace-basis` | `close` | `close` or `wick` |
| `--min-progress-adr` | 0.10 | Progress (× ADR) before the retrace limit applies |
| `--rank-by` | `move` | Pick each day's leg by size (`move`) or by `duration` |
| `--min-move-adr` | 0.25 | With `--rank-by duration`, the smallest move a leg must make |
| `--bucket-minutes` | 15 | Width of the start-time buckets |
| `--top` | 5 | Tickers per top up/down table; 0 turns the tables off |
| `--avg-sessions` | 5 | Prior sessions averaged for each top ticker |
| `--top-rank-by` | `pct` | Rank top legs by `pct` move or by `adr` multiple |
| `--csv-out` | none | Write every leg to a CSV |

---

## intraday_leg_timing.py

Finds every fast leg in the session — not just the biggest — and scores what a trader entering
after confirmation would have captured.

```bash
python alpha_tech_tracker/op_momentum_strategy/analysis_scripts/intraday_leg_timing.py \
  --tickers MRNA SNDK NVDA COIN \
  --retrace-basis close --sessions 60 \
  --csv-out legs_timing.csv
```

- **Leg:** a move of at least `--min-move-adr` (0.25) × ADR reached within `--impulse-bars`
  (3 = 15 min) of a bar open, before a `--retrace` (20%) give-back. It then runs until price gives
  back 20% of its start-to-extreme distance.
- **Capture:** enter at the close of the bar that qualified the leg, exit at the retracement
  level (or the bar open if price gapped through it).
- **`capt/sess`:** summed capture divided by **all** sessions, so it rewards both frequency and
  quality. This is the column to rank entry windows by.
- Use `--retrace-basis close`. On the default wick basis, 40–60% of legs end on the very bar that
  qualified them, which makes capture look like zero.
- Groups with fewer than `--min-legs` (5) legs are not eligible for "best"; small buckets are noise.

---

## Caveats

- **`daily_longest_leg.py` is hindsight.** It shows when the main move usually starts, not that it
  can be identified in real time. For tradeable numbers use `intraday_leg_timing.py` or a backtest.
- **No costs or slippage** in either script.
- **Small windows are noisy.** With 15 sessions each day is 6.7 percentage points; treat per-ticker
  differences of one or two days as noise and cross-check against a 250-session run.
- **Sparse tickers** (e.g. SPCX, which has gaps in its history) can produce odd durations.

## Tests

```bash
PYTHONPATH=$PWD python -m pytest \
  tests/op_momentum_trade_engine/test_daily_longest_leg.py \
  tests/op_momentum_trade_engine/test_intraday_leg_timing.py -v
```

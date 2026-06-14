# Win-Rate Selector Mode

Configuration guide for running the trade engine with `--selector win-rate`.

---

## What it is

The win-rate selector replaces the default composite-score ranking with a simpler,
historically-grounded picker. Before market open it ranks every ticker in the pool
by its **20-day EOD win rate** (fraction of days the stock closed higher from the
OR-close bar to end of day) and trades the top-N.

It also activates a different signal engine path — **win-rate signal mode** — that
mirrors the `ma_open_range_momentum_screener` logic exactly, producing signals that
are directly comparable to what the screener prints each morning.

---

## How signals differ from the default mode

| | Default (`score-rank`) | Win-rate (`--selector win-rate`) |
|---|---|---|
| **Pre-session picks** | Top-N by 60-day composite score (entry position, avg win, OR range) | Top-N by 20-day EOD win rate |
| **Signal fires when** | OR closes (exactly at bar N) | First bar within collection window that meets conditions |
| **BULLISH condition** | `close > OR_mid AND close > MA20 AND close > MA200` | `close > OR_mid AND collection_vol > vol_20day_avg AND any MA in OR range` |
| **BEARISH condition** | `close ≤ OR_low + 20% × OR_range AND close < MA20` | `close < OR_mid AND collection_vol < vol_20day_avg AND close < MA20 AND close < MA200` |
| **Volume gate** | None | collection_vol vs 20-day avg over the collection window time slots |
| **MA gate** | Price position relative to MA | At least one of MA20/MA50/MA200 must overlap the OR range |
| **Collection window** | 1 bar (OR close) | Up to 3 bars starting from the last OR bar (15 min total) |
| **Drain ranking** | Composite score (entry_vs_mid, avg_win, OR range) | `(up_pct_from_prev_close, MA_count_in_OR, vol_ratio)` |
| **Screener parity** | Independent | Signals match `ma_open_range_momentum_screener` output exactly |

---

## Required parameters

```bash
--selector win-rate
```

Activates `WinRateTickerSelector` for pre-session pick ranking and switches the signal
engine to win-rate signal mode (OR-range MA overlap + volume gate + 3-bar collection window).

```bash
--window M1 09:30 3
```

Opening range window: label `M1`, start `09:30` ET, `3` bars (15-minute OR). The collection
window starts from the last OR bar (9:40) and scans up to 3 bars (9:40 / 9:45 / 9:50).

```bash
--morning-split 100
```

Deploy 100% of the session capital in the M1 window. Required when only one window is defined.

```bash
--top 2
```

Number of pre-session picks to watch and enter per window. The win-rate selector picks the
top-N tickers by 20-day EOD win rate; signals from non-picked tickers are ignored.

```bash
--tickers TICKER1 TICKER2 ...
```

Ticker pool to score and pick from. Pass the same list to the screener if you want matching
output. The win rate is computed from the last 20 trading days within this pool.

---

## Recommended optional parameters

```bash
--enable-regime-engine
```

Loads `RegimeEngine` (MASTER_REGIME_SUMMARY pattern rules). Determines daily direction
(`LONG`, `SHORT`, `CAUTION`, `NO_POSITION`). When active, the win-rate selector operates
direction-aware: `LONG` → top-N highest EOD win rate, `SHORT` → bottom-N.

```bash
--feed sip
```

SIP (consolidated) feed. Required to match screener output — the screener always uses SIP.
IEX data can differ slightly in bar close prices, shifting the signal bar or vol ratio.

```bash
--trailing-ma none
```

Disables the trailing MA stop. Useful when comparing signal P&L across a date range, since
the MA trailing stop interacts with the screener's hold-window concept but not one-to-one.
For live trading with win-rate picks, `--trailing-ma ma20` (default) is still appropriate.

```bash
--stop-pct 0.9
```

Hard stop as a fraction of OR range. `0.9` allows 90% of the OR range against you before
stopping — effectively a very wide stop suited to stock trading where the full OR range is
the natural risk unit. For options, keep the default `0.15`.

```bash
--trade-type stock
```

Trade stocks instead of options. The win-rate selector does not require options — it is
primarily used for stock replay and screener parity testing.

---

## Replay and backtesting

Run a single day or date range against historical bars to compare with screener output:

```bash
python -m alpha_tech_tracker.op_momentum_strategy.op_momentum_trade_engine run \
  --tickers SNDK APP META SNOW SNPS SPOT MU LLY MRVL CRWD QCOM PLTR CHTR TSLA AVGO ARM AMD DDOG RDDT \
  --selector win-rate \
  --replay-start 2026-05-19 --replay-end 2026-05-19 \
  --window M1 09:30 3 --morning-split 100 \
  --top 2 \
  --enable-regime-engine \
  --trade-type stock \
  --capital 10000 \
  --stop-pct 0.9 \
  --mock-trade-execution \
  --trailing-ma none \
  --feed sip
```

Multi-day range (resets capital each day by default):

```bash
python -m alpha_tech_tracker.op_momentum_strategy.op_momentum_trade_engine run \
  --tickers SNDK APP META SNOW SNPS SPOT MU LLY MRVL CRWD QCOM PLTR CHTR TSLA AVGO ARM AMD DDOG RDDT \
  --selector win-rate \
  --replay-start 2026-05-01 --replay-end 2026-05-31 \
  --window M1 09:30 3 --morning-split 100 \
  --top 2 \
  --enable-regime-engine \
  --trade-type stock \
  --capital 10000 \
  --stop-pct 0.9 \
  --mock-trade-execution \
  --trailing-ma none \
  --feed sip
```

---

## Screener parity — running both tools together

The screener and the engine now produce identical signal sets when pointed at the same
ticker pool, the same OR window, and the same SIP feed. Use this to cross-check before
a live session.

**Screener** (single-date backtest, shows all signals):

```bash
python -m alpha_tech_tracker.op_momentum_strategy.ma_open_range_momentum_screener \
  --tickers SNDK APP META SNOW SNPS SPOT MU LLY MRVL CRWD QCOM PLTR CHTR TSLA AVGO ARM AMD DDOG RDDT \
  --date 2026-06-03 \
  --feed sip \
  --print-all
```

**Engine replay** (same date, win-rate selector — log lines prefixed `WIN-RATE SIGNAL`):

```bash
python -m alpha_tech_tracker.op_momentum_strategy.op_momentum_trade_engine run \
  --tickers SNDK APP META SNOW SNPS SPOT MU LLY MRVL CRWD QCOM PLTR CHTR TSLA AVGO ARM AMD DDOG RDDT \
  --selector win-rate \
  --replay-start 2026-06-03 --replay-end 2026-06-03 \
  --window M1 09:30 3 --morning-split 100 \
  --top 19 \
  --enable-regime-engine \
  --trade-type stock \
  --capital 10000 \
  --stop-pct 0.9 \
  --mock-trade-execution \
  --trailing-ma none \
  --feed sip
```

> Set `--top 19` (or the full pool size) when verifying parity — this shows every signal
> that fired without filtering to just the top-2 picks.

**What to compare:**
- Direction (BULL/BEAR) and signal time per ticker should match exactly.
- Vol ratio shown in the screener (`1.18x 20dAvg`) should match `vol=N avg=M` in the engine log.
- Any mismatch after the warmup fix (screener uses 30-day calendar warmup) is a data or feed difference.

---

## Live trading

The win-rate selector can be used in live or paper trading. Replace `--mock-trade-execution`
with `--live` (or omit both for paper account with real order flow):

```bash
python -m alpha_tech_tracker.op_momentum_strategy.op_momentum_trade_engine run \
  --tickers SNDK APP META SNOW SNPS SPOT MU LLY MRVL CRWD QCOM PLTR CHTR TSLA AVGO ARM AMD DDOG RDDT \
  --selector win-rate \
  --window M1 09:30 3 --morning-split 100 \
  --top 2 \
  --enable-regime-engine \
  --trade-type stock \
  --stop-pct 0.9 \
  --trailing-ma ma20 \
  --feed sip
```

For options trading, add `--trade-type options` (default) and remove `--stop-pct 0.9`
(revert to the standard `0.15`).

---

## Parameters that have no effect in win-rate mode

These flags belong to the `score-rank` path and are silently ignored when
`--selector win-rate` is active:

| Flag | Why it doesn't apply |
|---|---|
| `--score-entry-weight` | Composite score not computed |
| `--score-avg-win-weight` | Composite score not computed |
| `--score-win-rate-weight` | Composite score not computed |
| `--score-rel-strength-weight` | Composite score not computed |
| `--score-ev-trend-weight` | Composite score not computed |
| `--min-ev` | EV gate bypassed (sentinel `ev_trade=1.0` set for all picks) |
| `--dynamic-ev-gate` and `--dg-*` | Dynamic EV gate not evaluated |
| `--direction-split-ev` and `--ds-*` | Direction EV gate not evaluated |
| `--adaptive-lookback` and `--al-*` | Score-rank lookback not used |
| `--min-pool-vote` | Pool vote computed from EV stats — not relevant |
| `--normalize-or-by-adr` | ADR normalisation is a scoring step |
| `--qqq-or-weight` | QQQ OR score bonus not applied |
| `--min-score` | No composite score to floor |
| `--lookback` | Win-rate lookback is fixed at 20 days (not configurable) |

---

## Signal flow summary

```
Pre-market (before 9:30 AM ET)
  └─ WinRateTickerSelector.fetch_bars()  — loads 20+ days from Alpaca
  └─ WinRateTickerSelector.select()      — ranks pool by 20d EOD win rate
  └─ Picks top-N (e.g. AMD, SPOT)        — only these tickers' signals are entered

9:30–9:40 AM: OR bars 1-3 arrive
  └─ LiveSignalEngine collects 3 OR bars per ticker (win_rate_signal_mode=True)

9:40 AM: last OR bar arrives — OR complete, collection window opens
  └─ _try_fire_win_rate_signal() called on bar 9:40 (collection bar 1)
      ├─ check any MA20/50/200 inside OR range → skip if none
      ├─ compute vol_20day_avg from 20 prior trading days at this time slot
      ├─ BULL: close > OR_mid AND collection_vol > vol_20day_avg → fire
      ├─ BEAR: close < OR_mid AND vol < avg AND close < MA20 AND close < MA200 → fire
      └─ neutral: no signal, try again at 9:45

9:45 AM (if no signal at 9:40): collection bar 2
  └─ same conditions, incremental vol avg (bars 9:40 + 9:45)

9:50 AM (if still no signal): collection bar 3 — final chance
  └─ same conditions, vol avg over all 3 collection bars

Signal buffered → drain at collection deadline
  └─ filter: only tickers in pre-session picks have rolling_stats
  └─ rank by (up_pct_from_prev_close, MA_count_in_OR, vol_ratio) descending
  └─ enter top-N
```

---

## Worked example — 2026-05-19

This walkthrough traces a single day end-to-end: screener signals, engine pre-selection,
regime filter, drain, entry, and exit. All output is from actual replays against the
Alpaca SIP feed.

### Step 1 — Screener (reference signal list)

```
$ python -m alpha_tech_tracker.op_momentum_strategy.ma_open_range_momentum_screener \
    --tickers SNDK APP META SNOW SNPS SPOT MU LLY MRVL CRWD QCOM PLTR CHTR TSLA AVGO ARM AMD DDOG RDDT \
    --date 2026-05-19

========================================================================================
MA Open Range Momentum Screener — 2026-05-19  OR: 09:30 / 3 bars  Collection: 3 bars
========================================================================================
Ticker   Dir    Signal at  OR Low-High        Close    Up%     MAs in OR          Vol/20dAvg
----------------------------------------------------------------------------------------
DDOG     BULL   09:50      207.10-213.00      213.69   +2.33%  MA20/MA50          1.01x
CRWD     BULL   09:40      615.02-629.00      622.02   +0.52%  MA20               1.92x
MU       BULL   09:40      663.00-701.14      683.83   +0.34%  MA20/MA50          1.16x
APP      BEAR   09:40      482.01-503.78      485.70   -1.36%  MA20/MA50/MA200    0.56x
AMD      BEAR   09:45      410.70-428.75      413.84   -1.70%  MA20/MA50          0.54x
QCOM     BEAR   09:40      196.20-201.50      197.70   -2.92%  MA20/MA50/MA200    0.52x

Signals: 6 total (3 BULL, 1 BEAR)
QQQ: Bearish | vol 1.00x 20dAvg
```

Six signals across the pool: 3 BULL, 3 BEAR.

### Step 2 — Engine pre-market selection (before 9:30 AM)

The `WinRateTickerSelector` ranks the pool by 20-day EOD win rate and picks the top-2:

```
WinRateTickerSelector [LONG] top-2: ['AMD', 'SPOT']
Replay 2026-05-19 — pre-market picks: ['AMD', 'SPOT']
```

Both AMD and SPOT are watched for signals. The regime engine reads May as a seasonal
LONG month: `Regime: LONG | Hold: EOD [Seasonal Default]`.

### Step 3 — Signal collection (9:30–9:50 AM)

Every ticker's bars are fed through the signal engine. All 6 screener signals fire
in the engine with identical conditions:

```
WIN-RATE SIGNAL [M1] APP  BEARISH  close=485.70 or_mid=492.89 MAs=['MA20','MA50','MA200'] vol=49789  avg=88746
WIN-RATE SIGNAL [M1] MU   BULLISH  close=683.83 or_mid=682.07 MAs=['MA20','MA50']         vol=1384447 avg=1189446
WIN-RATE SIGNAL [M1] CRWD BULLISH  close=622.02 or_mid=622.01 MAs=['MA20']                vol=113913  avg=59482
WIN-RATE SIGNAL [M1] QCOM BEARISH  close=197.70 or_mid=198.85 MAs=['MA20','MA50','MA200'] vol=310498  avg=601048
WIN-RATE SIGNAL [M1] AMD  BEARISH  close=413.84 or_mid=419.73 MAs=['MA20','MA50']         vol=620250  avg=1138399
WIN-RATE SIGNAL [M1] DDOG BULLISH  close=213.69 or_mid=210.05 MAs=['MA20','MA50']         vol=123165  avg=121566
```

Signal times and vol ratios match the screener exactly.

### Step 4 — Drain (9:45 AM collection deadline)

Three filters reduce the 6 candidates to 1 entry:

| Signal | Filter applied | Result |
|---|---|---|
| APP BEARISH | Regime LONG → BEARISH blocked | **Skipped** |
| MU BULLISH | Not a pre-market pick → no rolling stats | **Skipped** |
| CRWD BULLISH | Not a pre-market pick → no rolling stats | **Skipped** |
| QCOM BEARISH | Regime LONG → BEARISH blocked | **Skipped** |
| AMD BEARISH | Pre-market pick but regime LONG → BEARISH blocked | **Skipped** |
| DDOG BULLISH | Fires at 9:50 (after drain deadline) → direct entry | **Entered** |

> DDOG fires on collection bar 3 (9:50), five minutes after the drain deadline (9:45).
> Signals that arrive after the drain go through the direct entry path. Since no positions
> were opened during the drain, `open_position_count = 0 < top_n = 2`, so DDOG enters at rank 0.
> SPOT never fires any signal — the pre-market pick doesn't trade without a qualifying signal.

### Step 5 — Entry and exit

```
SIMULATE BUY_OPEN  stock DDOG  shares=23  simulated_fill=213.69  (9:50 AM)
SIMULATE SELL_CLOSE stock DDOG shares=23  simulated_fill=215.54  (3:55 PM EOD)
```

```
Daily P&L: +$43.41  (+0.87% on $5,000 deployed)  │  cap: +$43.41 (+0.43%)
```

Capital split: 10k total / top_n=2 = $5,000 per slot. Only 1 slot filled → only
$5,000 deployed. The remaining $5,000 is idle (AMD pre-pick had no BULLISH signal,
SPOT had no signal at all).

### Key takeaways from this day

1. **Regime kills your primary pick.** AMD was the top EOD win-rate pick but signalled
   BEARISH on a LONG regime day. The engine correctly skipped it.

2. **Non-picks that signal are ignored at drain time.** MU and CRWD both fired BULLISH
   but weren't in the pre-market selection — they're filtered at drain by the absence of
   rolling stats. This is by design: win-rate pre-selection is the entry gate.

3. **Late-firing signals (collection bar 3) bypass the drain.** DDOG fired at 9:50, after
   the 9:45 drain deadline. It entered through the direct path. If two positions had already
   been filled by the drain, DDOG would have been blocked by `open_position_count >= top_n`.

4. **Screener and engine agree on all 6 signals.** Every direction, bar time, and vol ratio
   is identical — the two tools are now fully aligned on the same signal logic.

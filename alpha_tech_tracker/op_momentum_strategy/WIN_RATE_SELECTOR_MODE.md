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

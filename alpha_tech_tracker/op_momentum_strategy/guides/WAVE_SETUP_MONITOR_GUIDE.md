# Wave Setup Monitor Guide

`wave_setup_monitor.py` watches each ticker's best wave_risk_reward setups during the trading day
and sends buy/sell alerts (Telegram/SMS through `config._notify`, plus a CSV log). **Alerts only:
it places no orders.** The setups and their exits are the ones the setup report ranks, so live
alerts follow the backtest's rules.

## Quick start

```bash
source ~/.pyenv/versions/alpha_tech_tracker/bin/activate
export PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker

# 1. Rank the setups (skip if a recent report exists)
python -m alpha_tech_tracker.op_momentum_strategy.analysis_scripts.wave_risk_reward_setup_report \
  --tickers AMD META GOOGL AMAT SHOP SPOT

# 2. Config: each ticker's top 3 setups from that report (edit the JSON if you like)
python -m alpha_tech_tracker.op_momentum_strategy.wave_setup_monitor config \
  --report alpha_tech_tracker/op_momentum_strategy/backtest_result/wave_setups/2026-07-06_2026-10-05 \
  --tickers AMD META GOOGL AMAT SHOP SPOT

# 3. Start the daemon (TradeStation data), then check it
python -m alpha_tech_tracker.op_momentum_strategy.wave_setup_monitor start --market-data-source tradestation
python -m alpha_tech_tracker.op_momentum_strategy.wave_setup_monitor status
```

The process runs one session and exits 5 minutes after the close. Start it each trading morning
before 09:25 ET so the overnight holds get their sell-at-the-open alert (see Scheduling). On
weekends and NYSE holidays (including MLK Day, Presidents' Day and Juneteenth) it exits straight
away. On early-close days (13:00: July 3 Mon–Thu, the day after Thanksgiving, Dec 24) the close
alerts move with the close and the overnight hold is skipped, as in the backtest. Started after
the open, the overnight sell alert says "now" and the exit is priced on the first bar it sees
(outcome `late open`).

## Weekly refresh (recommended recipe)

Research (Findings 17–18 in the ticker-tuning doc) found the most robust way to choose the setups:
**long setups and overnight holds only, ranked by their last-3-month total, top 3 positive with at
least 3 trades, re-picked every week.** `config --refresh` does it in one step: it runs the setup
report over the trailing window ending today, then writes the config from its last 63 sessions.

```bash
python -m alpha_tech_tracker.op_momentum_strategy.wave_setup_monitor config --refresh \
  --tickers MDB GOOGL APP AMD META MSFT AMAT SPOT MRNA TSLA QQQ SNPS LLY COIN SHOP CRWV CRM NVDA PLTR AVGO \
  --types long overnight --min-trades 3 --workers 4
```

- The report lands in `backtest_result/wave_setups/monitor_refresh/<start>_<end>/`; the config
  records its `window`, `types` and `min_trades`.
- It takes roughly 1–3 minutes per ticker (`--workers` processes; each needs ~150–250 MB, so
  use 1–2 on a small box, or refresh on another machine and copy the config).
- Schedule it once a week before the session, e.g. Monday 05:00 PT, ahead of the 06:00 `start`:
  `0 5 * * 1 cd ... && ... wave_setup_monitor config --refresh --tickers ... --types long overnight --min-trades 3 --workers 1`.
- `config --report DIR` (no `--refresh`) still builds a config from an existing report;
  `--lookback-sessions N` ranks on its last N sessions only.

## Running the daemon

### Before the first run

1. **Python:** the `alpha_tech_tracker` virtualenv, with `PYTHONPATH` set to the repo root; run
   the commands from the repo root.
2. **config.json** (`op_momentum_strategy/config.json`): Telegram/ClickSend settings for the alerts
   (the same ones the trade engine uses), and the data source's credentials.
3. **Data source:**
   - TradeStation: run `tradestation_auth.py` once so `config.json` holds a valid session. Check it with
     `TradeStationAPIClient(...).verify_session()` or a 60 s foreground trial (below).
   - Alpaca: `ALPACA_API_KEY` / `ALPACA_SECRET_KEY`; see Data plan for SIP vs IEX.
4. **Monitor config:** `logs/wave_setup_monitor_config.json`, written by the `config` command
   (Quick start step 2). It needs the setup report's `trades.csv`, which is local data: on another
   machine, generate the config where the report is and copy the JSON over.

### Commands

| Command | What it does |
|---|---|
| `run` | Foreground, logs to the terminal and the log file. Ctrl-C to stop. Writes the PID file, so `status`/`stop` work too. |
| `start` | Background daemon for the rest of the session. Refuses if one is already running. |
| `status` | `Monitor running (PID n)` or `Monitor is not running.` |
| `stop` | SIGTERM (SIGKILL after 10 s); the monitor saves its state and sends the summary first. |
| `restart` | `stop` then `start`. State is kept: no repeated alerts, overnight holds remembered. |

Every command takes the same options (`--market-data-source`, `--workers`, `--no-notify`, ...);
pass them to `start`/`restart`, not to `stop`/`status`.

**Trial run** before relying on it — 60 s in the foreground, no notifications, scratch state:

```bash
timeout 60 python -m alpha_tech_tracker.op_momentum_strategy.wave_setup_monitor run \
  --market-data-source tradestation --no-notify --state-file /tmp/wsm_trial.json --log-file /tmp/wsm_trial.log
grep -E "warmup|stream|SYSTEM|ERROR" /tmp/wsm_trial.log
```

Expect one `TS warmup <ticker> — N bars` line per ticker, `starting live 1-min stream`, and
`SYSTEM monitor started`.

### Files

| File | Contents |
|---|---|
| `logs/wave_setup_monitor_config.json` | Tickers and setups to watch |
| `logs/wave_setup_monitor_<date>.log` | Log: 5-min bars, alerts (`ALERT ...`), system messages (`SYSTEM ...`), errors |
| `logs/wave_setup_alerts_<date>.csv` | One row per alert: time, ticker, setup, action, price, stop, target, message |
| `logs/wave_setup_monitor_state.json` | Alerted signals, open trades, overnight holds (do not delete while holding overnight) |
| `logs/wave_setup_monitor.pid` | PID of the running monitor |

Follow the day with `tail -f logs/wave_setup_monitor_$(date +%F).log | grep -E "ALERT|SYSTEM|ERROR"`.

### macOS

- `start` launches a separate `run --detached` process in its own session. macOS crashes a
  double-forked child once it touches system frameworks (segfault "crashed on child side of
  fork"), so the Linux-style fork is not used there.
- **Sleep stops it.** Keep the Mac awake while it runs: `caffeinate -i -w $(cat logs/wave_setup_monitor.pid) &`
  blocks idle sleep until the monitor exits; closing the lid still sleeps the Mac. A sleep longer
  than 5 minutes in the session triggers the `no market data` alert.

### Linux / EC2

- `start` double-forks into a daemon (the trade engine's helpers); stdout/stderr go to the log.
- **Memory:** each monitor uses about 150–250 MB (pandas, warm-up bars, streams), plus about
  100 MB per `--workers` process. On a small box use `--workers 0` (evaluate in the main
  process; ~1.5 s per ticker per bar, fine for a handful of tickers) and check
  `free -m` first. On the 905 MB / no-swap EC2 box that already runs the bar broadcaster and two
  trade engines (~240 MB free), starting the monitor made the box stop answering SSH (likely
  out of memory). Add swap or use a bigger instance before running it there, e.g.
  `sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile`.
- The `local_ts_broadcast` source only serves the broadcaster's own ticker list
  (`bar_broadcaster.py --tickers`, default V3 pool); for other tickers use `tradestation`.

### Scheduling

Start it every weekday at 09:00 ET; on holidays it exits by itself, and a second `start` while
one is running is refused.

Linux (cron; the EC2 crontab uses `CRON_TZ=America/Los_Angeles`, so 06:00 PT = 09:00 ET):

```
CRON_TZ=America/Los_Angeles
0 6 * * 1-5 cd /home/ec2-user/alpha_tech_tracker && PYTHONPATH=/home/ec2-user/alpha_tech_tracker /home/ec2-user/.pyenv/versions/alpha_tech_tracker/bin/python -m alpha_tech_tracker.op_momentum_strategy.wave_setup_monitor start --market-data-source tradestation --workers 0 >> /home/ec2-user/wave_setup_monitor_cron.log 2>&1
```

macOS: a launchd agent (`~/Library/LaunchAgents/com.alphatech.wave-setup-monitor.plist`) that runs the
same `start` command at 06:00 local (Pacific) Monday–Friday, then
`launchctl load ~/Library/LaunchAgents/com.alphatech.wave-setup-monitor.plist`. The Mac must be awake
at that time (System Settings → Battery → Options, or `pmset repeat wake MTWRF 05:55:00`).

### Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `insufficient subscription` in the log, `no market data` alert | Alpaca account without real-time SIP: use `--market-data-source tradestation` or `--feed iex` |
| `subscription does not permit querying recent SIP data` | Delayed-SIP Alpaca plan: start before 09:30, or accept the backfilled gap after a restart |
| `TradeStation session invalid — run tradestation_auth.py first` | Session expired: re-run `tradestation_auth.py` |
| `status` says not running right after `start` on macOS, log has no traceback | An old build double-forked; update the code (the macOS start re-executes instead) |
| `Monitor already running (PID n)` | `stop` first, or `restart`; a stale PID file of a dead process is ignored |
| No alerts at all during the session | A quiet day can have no signals (and then no 16:05 summary). Check the log: a `5-min <ticker> HH:MM ...` line per ticker every 5 minutes means data is flowing; look for `SYSTEM` / `ERROR` lines otherwise |

## Alerts

| When | Alert | Notes |
|---|---|---|
| A setup fires on a closed 5-min bar | `BUY` / `SHORT ticker \| setup \| ~entry \| stop \| target \| exit rule` | Entry = that bar's close. Place the stop as an order: the monitor checks stops on closed 5-min bars only. |
| Stop, target or give-back trail hit | `SELL` / `COVER ... hit on the HH:MM bar @ price \| P&L` | Backtest exit rules per setup (below). |
| ~15:50 (once every ticker's 15:45 bar is in, 15:51 latest) | `SELL` / `COVER ... at the close (MOC)` for open intraday trades; `BUY ... at the close (MOC)` for overnight holds | Uses the 15:45 bar's close. `SKIP` when the next open carries an earnings release. |
| 09:25 next morning | `SELL ... at the open (MOO before 09:28)` | For each overnight hold in the state file. |
| 16:05 | Session summary | Closed trades with P&L, holds carried overnight. |
| Start-up | `monitor started for <date>: N tickers` | Daily sign of life; also notes an early close. |
| Start-up | `short setups on: QQQ closed X, below its 50-day MA Y (drive, overnight on ...)` (or `off`) | Whether today's down-market shorts are on. See [Short alerts](#short-alerts). |
| 09:35, on a gated session | `SHORT ticker \| short drive \| ~price \| stop` | Red first bar. A stop-out may be followed by one `SHORT ... short drive re-entry` (no stop). |
| ~15:50, on a gated session | `SHORT ticker \| short overnight \| at the close (MOC)` | Covered by `COVER ... at the open (MOO)` the next morning; `SKIP` before earnings. |
| Start-up, about 30 s later | `signal stats, last 10 sessions ...` | Drive long and overnight hold win rates. See [Signal stats](#signal-stats). |
| No 1-min bar for 5 min in the session | `no market data since HH:MM ...`, then `market data restored ...` | Sent once per outage. The stream is reconnected every 2 min meanwhile; the gap's bars are backfilled when data returns, but signals and stop checks inside it are missed. |
| A reversal candle near a wave's low or high | `LOW?` / `HIGH? ticker \| pattern(s) \| ~price (HH:MM bar close) \| wave down/up N avg bars, low/high so far` | Information only: no trade is opened or tracked. See [Reversal alerts](#reversal-alerts). |

Every alert is also appended to `logs/wave_setup_alerts_<date>.csv`; the log is
`logs/wave_setup_monitor_<date>.log`.

**MOC cutoffs:** Nasdaq 15:55, NYSE 15:50. The default 15:50 alert meets Nasdaq's but not NYSE's.
For NYSE-listed tickers (SPOT, CRM, LLY, ...) use `--close-decision-bar 15:40`: the decision
uses the 15:40 bar and the alert comes about 15:45. Entries are not alerted from the decision
bar on.

## Drive long options

Two opt-in changes to the config's `drive long` trades (off by default; ticker-tuning doc, Findings 32, 35, 36):

- **`--drive-trail`:** while a drive long is open, each newly confirmed dip (the wave model with 7-bar waves, 38.2%
  retrace, 1.5 average bars) raises its stop to the dip's low → `RAISE STOP ticker | drive long | stop X`. The bar's
  stop check comes first, then the raise. It beat plain drive long on 8 of 13 single-ticker checks by small margins:
  it helps in strong uptrends and gives a little back in chop.
- **`--drive-reentry`:** after a drive long is stopped out, one `BUY ticker | drive long re-entry | ... back above the
  stop-out level X | stop Y | hold to the close` when a bar closes back above the stop that was hit, before 15:00;
  stop at the low since the stop-out. It helped where stop-outs recovered (PLTR, AMD, SNPS) and hurt where they kept
  falling (CRWV, DDOG, MDB): better in 6 of 11 ticker-periods of 2025–26, not yet checked on 2020–24.

With both on, the re-entry is trailed too and its stop-out level is the raised stop; that combination was not tested. After a
restart the day's bars are replayed through open drive longs in order (stop check, then raise) and a raised stop gets
one `RAISE STOP ... (caught up after a restart)` alert; after a data gap or an out-of-order bar, dips confirmed after a
trade's entry raise its stop for the bars to come (`... (caught up after a data gap)`).

## Short alerts

On sessions where the market gate is on, the monitor also alerts down-market shorts (`short_setups.py`). They are the
two shorts that held up in nine down markets 2020–2026 (ticker-tuning doc, Finding 37); alerts only, like everything
else here.

- **Gate:** decided once per session from the previous daily close. Default `--short-gate qqq-ma50`: on when QQQ closed
  below its 50-day moving average. `always` and `off` are the other choices; the gate is one function
  (`short_setups.gate_status`) so a better market indicator can replace it. The start-up alert says on or off and why.
- **Tickers:** `--short-tickers`, default the config's tickers plus QQQ (added to the stream).
- **drive:** a red first 5-min bar → `SHORT ... ~close (09:30 bar close) | stop its high | cover at the close`. If the
  stop is hit, one re-entry when a bar closes back below that high before 15:00 → `SHORT ... short drive re-entry |
  no stop | cover at the close`. Both are covered by the 15:50 `COVER ... at the close (MOC)` alert.
- **overnight:** at the close decision (15:50 alert) → `SHORT ... short overnight | at the close (MOC)`; the next
  morning `COVER ... at the open (MOO before 09:28)`. Skipped the night into an earnings release (`SKIP`) and on
  early-close days.
- **retest** (opt-in: `--short-setups drive overnight retest`): `SHORT LIMIT` when a new rally high is confirmed (a
  sell limit just below it for the next bar), `SHORTED` when it fills, `LOWER STOP` on each new lower rally high,
  covered at the close. It lost out of sample once a look-ahead in its study was fixed; it is there for testing.

| Short setup (gate on) | Down windows up | Sum, 9 down windows | 2026 outside them |
|---|---|---|---|
| overnight | 7 of 9 | +1,114% | −211% |
| drive + re-entry | 7 of 9 | +318% | −17% |
| retest (opt-in) | 5 of 9 | −229% | −48% |

The edges are thin (+0.06–0.15% per trade, summed at $10k per trade, 5 bps, no borrow cost) and the overnight short
carries gap risk; `--no-short-setups` turns them all off.

- **On a gated session with the overnight short on, the long overnight holds are skipped** (`SKIP ... short setups
  are on today`), so the monitor never alerts BUY and SHORT at the same close. With `--short-setups drive` the long
  holds stay on: in 2026 the overnight short lost on all 24 tickers tested (−$6,776) while the skipped long holds would
  have made +$2,953 (ticker-tuning doc, Finding 38), so `--short-setups drive` suits shallow pullbacks; turn the
  overnight short back on for a crash.
- **A configured `drive short` setup** already alerts the red-first-bar short, so the monitor doesn't send a second
  one for that ticker; its stop-out still gets the re-entry.
- **Tickers added only for shorts** (QQQ by default) get no reversal alerts and are left out of the start-up stats.
- **An open overnight trade in the state file keeps its ticker streamed** at the next start, whatever the config or
  flags, so its next-open SELL / COVER alert and exit are not lost.

## Trend filters

Opt-in daily trend filters (`--trend-filters`, none by default; `trend_filters.py`, ticker-tuning doc, Finding 40).
Each is decided once at start-up from the daily bars before the session; one start-up alert lists the result, e.g.
`trend filters | overnight holds off: QQQ 601.20, above its 200-day MA 560.40, -1.8% over 10 sessions | AMD off:
pullback long (10-session high 512.00 vs 540.30 before)`. A missing daily history turns the filtered setups off.

- **`overnight`:** every overnight hold in the config, only while QQQ is above its 200-day MA and up over the last 10
  sessions; otherwise `SKIP ... trend filter: <reason>` at the close. The best rule over four years (sum of trade %
  per year, overnight always):

  | QQQ condition | 2020 | 2022 | 2025 | 2026 to Nov 6 | Four years |
  |---|---|---|---|---|---|
  | every night | +303 | −579 | +365 | +92 | +181 |
  | above its 50-day MA | +385 | −258 | +322 | +45 | +495 |
  | **above its 200-day MA and up over 10 sessions** | +282 | **−56** | +384 | +57 | **+667** |

  The MA200 keeps the holds out of a bear year (2022: 77 of 2,707 nights) and the 10-session return trims weak
  stretches; it gives up a little in a steady year (2026). A sharp drop that starts while QQQ is still up over 10
  sessions is not caught.
- **`pullback`:** pullback long / pullback long C1 only while the ticker's 10-session high is above the 10 sessions
  before; a blocked setup is not evaluated. Mixed: the kept trades beat the dropped ones in 2020 and 2022 but not in
  2025 or outside the 2026 study windows, and made only +0.03 to +0.08% each. Leave it off.

A drive-short filter (QQQ below its 10-day EMA and the ticker down over 20 sessions) looked good on the windows it was
picked on and failed in all four full years; it was removed. `analysis_scripts/trend_filter_check.py <setup report
trades.csv ...>` replays the filters on any setup report.

## Signal stats

Sent once per session when the monitor starts (with the midnight cron restart, just after
midnight; a later restart the same session does not resend it): how drive
long and the overnight hold have been doing lately, as a guide to how much to trust today's signals.

```
signal stats, last 10 sessions (09-30 to 10-13), 21 tickers:
drive long: 30/106 won (28%), avg +0.03%
overnight ma200: 83/133 won (62%), avg +0.06%, 15 pending
monitored (MRNA SNDK APP AMD MDB CRWV SNPS), by day:
10-09 drive long 1/4 won (25%), avg +2.64% | overnight 2/5 won (40%), avg -0.70%
10-12 drive long 0/1 won (0%), avg -1.35% | overnight 0/5 won (0%), avg -2.52%
10-13 drive long 4/6 won (67%), avg +0.99% | overnight 5 pending (exit at the next open)
```

- **First block:** the last 10 completed sessions, pooled over the stats tickers (`--stats-tickers`;
  default the 21 setup-tape tickers: the 7 EC2 tickers, SPOT COIN MSFT SNOW CRWD AMAT FN DDOG ARM CLS
  META SPCX CHTR, and LLY).
- **By day:** the last 3 completed sessions, over the monitored tickers.
- **Drive long** is the setup report's `drive long`: the first bar green, stop at its low, held to
  the close. **Overnight** is `overnight ma200`: buy the 15:55 bar's close when it is above the
  200-day average, sell the next open, skip nights into earnings. A trade counts on its entry
  session; a hold bought but not yet sold (the latest night, before the open) is counted as
  pending, not as a win or loss. "no trades" means nothing was entered. Early-close days have no
  15:55 bar and so no hold, like the backtest. No costs.
- The numbers match `wave_risk_reward_backtest` trade for trade (AMD, SNDK, MRNA, MSFT, COIN, META,
  AMAT, DDOG checked).
- Tickers the monitor does not watch are fetched from the market data source one at a time (about
  30 s for 21 tickers). It runs in a background thread after the stream starts and the
  computation goes to the `--workers` pool; with `--workers 0` it shares the main process, which
  can delay bar handling a little in the first minute if started during the session. History
  requests take turns with the monitor's own refetches and backfills, since they share the
  client's session.
- A ticker whose history fails is listed under `no data`; missing daily closes are noted and count
  no overnight holds; any other failure is logged and sends nothing. `--no-signal-stats` turns it
  off.

## Reversal alerts

On by default for every ticker in the config: a message when a reversal candle shows up near the
low of a down wave or the high of an up wave. It does not open a trade and it was never backtested
for P&L. It says a wave may be turning, which can help you judge an entry or exit.

**When it fires** (`reversal_watch.py`): each closed 5-min bar goes through the wave model the way
`analyze_bars` builds it. A bar is a *candidate low* when the current wave is down, it has fallen at
least 3 average bars (the trailing 78-bar mean high − low) from its high to this bar's low, and
this bar's low is within 1 average bar of the wave's lowest low. A candidate high is the mirror.
On a candidate it checks three patterns, with the minimum candle size set to the average bar:

| Pattern | Bars | At the real low (2025 / 2026) | At the real high (2025 / 2026) | Firings |
|---|---|---|---|---|
| `piercing`: piercing line at lows, dark cloud cover at highs | previous + this | 69% / 56% | 65% / 61% | about 1 a month per ticker per side |
| `push` | previous + this | 65% / 53% | 59% / 61% | about 1–2 a month per ticker per side |
| `long_tail`: long tail on a candidate, next bar closes beyond it | this + next (alerts one bar late) | 55% / 53% | 51% / 51% | about 1 every 2 days per ticker per side |
| *any candidate bar (baseline)* | | 31% / 29% | 29% / 27% | |

"At the real low" means within one bar of the finished wave's lowest low, pooled over the seven
monitored tickers (AMD, APP, CRWV, MDB, MRNA, SNDK, SNPS) from
[research/ticker_characteristic](../research/ticker_characteristic/README.md). A replay of those
bars through `ReversalWatch` fires on the same bars as the study (2025 and 2026, all seven tickers).
Patterns that fire on the same bar and side share one alert. Not alerted: the session's first two
bars, which are not candidates, and the last bar (15:55, or 12:55 on an early-close day), which
closes as the market does.

`--reversal-patterns piercing push` picks the patterns (default: all three) and
`--no-reversal-alerts` turns them off. They are logged to the alerts CSV with action `LOW?` /
`HIGH?` and setup `reversal <patterns>`. A restart does not repeat them.

- **Warm-up:** at startup each ticker's last sessions are replayed through the wave model (about
  0.1 s per ticker; enough for the current wave and the 78-bar averages, and the same signals as a
  full replay). The replay sends no alerts, so a reversal on the bar closed just before a restart
  is not alerted.
- **Gaps:** after a delayed-feed start no reversal alerts are sent until the gap is backfilled; then
  the watch is rebuilt. If the backfill fails, reversal alerts stay off for the rest of the session.
  A late or out-of-order bar also rebuilds the watch, without an alert.
- **Bad data:** a bar with a zero or missing price is skipped. An error in the reversal check is
  logged, rebuilds the watch, and never stops the setup alerts for that bar.
- **Wave size:** the watch always uses the default wave size (`--min-wave-bar-ranges 2`), whatever
  the setups use.

## Data plan

The backtests use Alpaca **SIP** bars. Streaming SIP live needs a real-time SIP subscription.
Without one, the Alpaca stream fails with `insufficient subscription`, and history newer than
15 minutes is refused (`subscription does not permit querying recent SIP data`). Options:

- **TradeStation** (`--market-data-source tradestation`, run `tradestation_auth.py` first): full
  consolidated prices, closest to the backtest.
- **Alpaca IEX** (`--feed iex`): free and real-time, but IEX prints only part of the volume, so bar
  highs/lows (and some signals) differ from the SIP backtest.
- **Alpaca SIP** with a real-time plan: the default.

Starting before 09:30 needs no recent data (warm-up ends at the previous close). A restart during
the session on a delayed-SIP plan warms up to 16 minutes ago and backfills that gap once it can
be queried; signals inside the gap are not alerted.

## Setups and exits

The config lists setup names from the setup report. Each uses the scan's options
(`wave_risk_reward_scan.SETUP_RUNS`) and the report's fixed exit (`REPORT_EXITS`):

| Setup | Exit |
|---|---|
| box break / box fade / box gap | target or stop |
| drive long / drive short | stop, else the close |
| drive fade long / drive fade short | target (the first bar's other extreme) or stop |
| pullback long / short / long C1 | stop until the target, then trail (32% give-back) |
| bounce long / short | target or stop |
| overnight always / ma200 | buy at the close, sell at the next open; skips the night into earnings |

## How it works

- **Data:** the trade engine's switch, `--market-data-source alpaca|tradestation|local_ts_broadcast`
  (default: `config.json` `market_data_source`, else Alpaca with `--feed sip`). It warms up
  about 20 calendar days of 5-min bars, then streams 1-min bars and builds 5-min bars, emitted when
  the fifth minute arrives (or 20 s after the period ends). The period in progress at start-up is
  refetched whole when it ends. If no 1-min bar arrives for 120 s during the session, the stream
  is reconnected.
- **Signals:** on each new 5-min bar, `analyze_bars` re-runs over the last 10 sessions (window
  start fixed for the day) with each setup's options, in a process pool (`--workers`). Only
  signals on the new bar alert. Overnight holds are decided directly: the earnings calendar plus
  the moving-average filter on split-adjusted daily closes.
- **State:** `logs/wave_setup_monitor_state.json` keeps alerted signals, open trades and
  overnight holds, so a restart neither repeats alerts nor forgets a hold. On restart it replays
  today's bars through the open trades, so a stop hit while it was down is caught. Signals that
  fired while it was down are not alerted.

## Differences from the backtest

Replay check (Sep 17–30 2026, AMD META GOOGL AMAT SHOP SPOT, top 3 setups each, real 5-min bars
fed through the monitor): 92 of 92 backtest trades matched, +26.39% vs +26.36%. The one exit
difference is the close rule below (GOOGL drive long on Sep 30 hit its stop after the 15:50 alert).

- **10-session window:** the backtest replays months of history. Waves and boxes depend only on
  recent bars, so signals rarely differ; the replay check below measures it.
- **Close:** intraday trades exit at the close via the 15:50 alert; stops are not checked after
  that alert (the trade is assumed closing at MOC). Overnight entries use the 15:55 bar's close,
  like the backtest, but the decision is made on the 15:45 bar.
- **Fills:** alerts come a few seconds after each 5-min bar closes, so live fills differ from the
  bar-close prices the backtest uses.

## Options

| Option | Default | Meaning |
|---|---|---|
| `config --report DIR` | — | Setup report folder with trades.csv |
| `config --tickers ...` | every ticker in the report | Tickers to monitor |
| `config --top N` | 3 | Setups per ticker (one per overlapping family, money-makers only) |
| `config --types ...` | all | Setup types to consider: `long`, `short`, `box`, `overnight` (recommended: `long overnight`) |
| `config --min-trades N` | 1 | Trades a setup needs in the window (recommended: 3) |
| `config --lookback-sessions N` | whole report (63 with `--refresh`) | Rank on the report's last N sessions |
| `config --refresh` | off | Run the setup report for `--tickers` over the trailing window ending today first |
| `--config PATH` | `logs/wave_setup_monitor_config.json` | Config to write / read |
| `--market-data-source` | config.json, else alpaca | `alpaca`, `tradestation` (run `tradestation_auth.py` first), `local_ts_broadcast` |
| `--feed` | `sip` | Alpaca feed |
| `--close-decision-bar` | `15:45` | `15:40` to alert about 15:45 for NYSE MOC |
| `--workers` | CPUs − 1 | Processes evaluating setups (0 = main process) |
| `--reversal-patterns ...` | `piercing push long_tail` | Reversal candles alerted (information only) |
| `--no-reversal-alerts` | off | No reversal alerts |
| `--drive-trail` | off | Raise an open drive long's stop to each new confirmed dip low |
| `--drive-reentry` | off | One drive long re-entry back above the stop-out level |
| `--short-setups ...` | `drive overnight` | Down-market shorts alerted on gated sessions (`retest` opt-in) |
| `--no-short-setups` | off | No short setups |
| `--short-gate` | `qqq-ma50` | When shorts are on: `qqq-ma50`, `always`, `off` |
| `--short-tickers ...` | config tickers + QQQ | Tickers for the short setups |
| `--trend-filters ...` | none | Opt-in daily trend filters: `overnight` (QQQ above its 200-day MA and up over 10 sessions), `pullback` |
| `--stats-tickers ...` | the 21 setup-tape tickers | Tickers pooled in the start-up signal stats |
| `--no-signal-stats` | off | No start-up signal stats |
| `--no-notify` | off | Log and CSV only |
| `--state-file`, `--pid-file`, `--log-file`, `--log-level` | under `logs/` | |

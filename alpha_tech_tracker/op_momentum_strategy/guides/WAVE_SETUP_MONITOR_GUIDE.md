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
| No 1-min bar for 5 min in the session | `no market data since HH:MM ...`, then `market data restored ...` | Sent once per outage. The stream is reconnected every 2 min meanwhile; the gap's bars are backfilled when data returns, but signals and stop checks inside it are missed. |
| A reversal candle near a wave's low or high | `LOW?` / `HIGH? ticker \| pattern(s) \| ~price \| wave size, low/high so far \| study precision \| info only` | Information only: no trade is opened or tracked. See [Reversal alerts](#reversal-alerts). |

Every alert is also appended to `logs/wave_setup_alerts_<date>.csv`; the log is
`logs/wave_setup_monitor_<date>.log`.

**MOC cutoffs:** Nasdaq 15:55, NYSE 15:50. The default 15:50 alert meets Nasdaq's but not NYSE's.
For NYSE-listed tickers (SPOT, CRM, LLY, ...) use `--close-decision-bar 15:40`: the decision
uses the 15:40 bar and the alert comes about 15:45. Entries are not alerted from the decision
bar on.

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
bars, which are not candidates, and the last bar, which closes at 16:00.

`--reversal-patterns piercing push` picks the patterns (default: all three) and
`--no-reversal-alerts` turns them off. They are logged to the alerts CSV with action `LOW?` /
`HIGH?` and setup `reversal <patterns>`. A restart does not repeat them. At startup each ticker's
warm-up bars are replayed through the wave model (about 1 s per ticker); the replay sends no alerts.

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
| `--no-notify` | off | Log and CSV only |
| `--state-file`, `--pid-file`, `--log-file`, `--log-level` | under `logs/` | |

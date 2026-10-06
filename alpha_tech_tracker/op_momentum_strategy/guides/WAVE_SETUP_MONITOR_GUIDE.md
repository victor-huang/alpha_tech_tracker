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

# 3. Run: foreground, or as a daemon
python -m alpha_tech_tracker.op_momentum_strategy.wave_setup_monitor run
python -m alpha_tech_tracker.op_momentum_strategy.wave_setup_monitor start --market-data-source tradestation
python -m alpha_tech_tracker.op_momentum_strategy.wave_setup_monitor status
python -m alpha_tech_tracker.op_momentum_strategy.wave_setup_monitor stop
```

The process runs one session and exits 5 minutes after the close. Start it each trading morning
before 09:25 (cron/launchd), so the overnight holds get their sell-at-the-open alert. On weekends
and NYSE holidays (including MLK Day, Presidents' Day and Juneteenth) it exits straight away. On
early-close days (13:00: July 3 Mon–Thu, the day after Thanksgiving, Dec 24) the close alerts move
with the close and the overnight hold is skipped, as in the backtest. Started after the open, the
overnight sell alert says "now" and the exit is priced on the first bar it sees (outcome
`late open`).

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

Every alert is also appended to `logs/wave_setup_alerts_<date>.csv`; the log is
`logs/wave_setup_monitor_<date>.log`.

**MOC cutoffs:** Nasdaq 15:55, NYSE 15:50. The default 15:50 alert meets Nasdaq's but not NYSE's.
For NYSE-listed tickers (SPOT, CRM, LLY, ...) use `--close-decision-bar 15:40`: the decision
uses the 15:40 bar and the alert comes about 15:45. Entries are not alerted from the decision
bar on.

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
| `--config PATH` | `logs/wave_setup_monitor_config.json` | Config to write / read |
| `--market-data-source` | config.json, else alpaca | `alpaca`, `tradestation` (run `tradestation_auth.py` first), `local_ts_broadcast` |
| `--feed` | `sip` | Alpaca feed |
| `--close-decision-bar` | `15:45` | `15:40` to alert about 15:45 for NYSE MOC |
| `--workers` | CPUs − 1 | Processes evaluating setups (0 = main process) |
| `--no-notify` | off | Log and CSV only |
| `--state-file`, `--pid-file`, `--log-file`, `--log-level` | under `logs/` | |

# Wave Strategy Engine Guide

The wave strategy engine trades the wave setup monitor's signals with stock orders. It is the trade engine run with
`--strategy wave-setups`: the same strategy code as the monitor (`wave_strategy/strategy.py`, `WaveSetupStrategy`)
decides every entry and exit, and `wave_strategy_runner.py` (`WaveStrategyRunner`) turns those decisions into
positions and orders. **Intraday only:** overnight setups in the config are logged and never traded.

The monitor keeps running on its own (own process, state and alert CSV); the engine reads the same config and takes
the same flags, so a mock day of the engine matches the monitor's alert CSV one to one.

How it was built and verified: `dev/active/WAVE_STRATEGY_TRADE_ENGINE_PLAN.md` (steps A0–B3). The setups, alerts,
shorts and trend filters themselves are described in `guides/WAVE_SETUP_MONITOR_GUIDE.md`.

## Quick start

```bash
source ~/.pyenv/versions/alpha_tech_tracker/bin/activate
export PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker
E="python -m alpha_tech_tracker.op_momentum_strategy.op_momentum_trade_engine"

# Mock (no orders, no broker client), the prod monitor's flags, foreground
$E run --strategy wave-setups --mock-trade-execution --market-data-source tradestation \
  --short-setups drive --short-gate qqq-ma50-down10 --trend-filters overnight

# Same as a daemon; status / stop / restart take --strategy wave-setups too (its own PID file)
$E start --strategy wave-setups --mock-trade-execution --market-data-source tradestation \
  --short-setups drive --short-gate qqq-ma50-down10 --trend-filters overnight
$E status --strategy wave-setups
$E stop --strategy wave-setups
```

Without `--strategy` (or with `--strategy or`) the trade engine runs the opening-range options/stock strategy exactly
as before; the two can run side by side.

## Modes

| Mode | Flags | Orders | Fills recorded |
|---|---|---|---|
| Mock | `--mock-trade-execution` | none; no broker client is built | the strategy's own prices (signal bar close, stop, target, last close), so they match the monitor's alerts |
| Paper | (default broker settings, paper keys) | `order_executor.place_stock_order` through `--execution-broker`, as the OR engine | broker fill on the position; the strategy keeps its reference prices for its decisions |
| Live | `--live` | as paper, live account | as paper |

Roll out in that order: mock beside the monitor for about a week (compare daily, below), then Alpaca paper, then live.

## Options

The engine takes the monitor's flag names and defaults (except `--workers`):

| Flag | Default | Meaning |
|---|---|---|
| `--strategy wave-setups` | `or` | Run the wave strategy instead of the OR engine |
| `--wave-config` | `logs/wave_setup_monitor_config.json` | Tickers and setups (the monitor's config file) |
| `--wave-balance` | 20000 | Capital the engine trades with |
| `--wave-slots` | 10 | Most positions open at once; each trade gets balance / slots ($2,000) |
| `--wave-state-file` | `logs/wave_strategy_engine_state.json` | State for same-session restarts |
| `--workers` | 0 | Setup evaluations inline (0) or in a process pool of N |
| `--close-decision-bar` | 15:45 | Bar after which open trades get the close decision |
| `--short-setups`, `--no-short-setups`, `--short-gate`, `--short-tickers` | monitor's | Down-market shorts (only intraday shorts are traded) |
| `--drive-trail`, `--drive-reentry` | off | Drive long options |
| `--trend-filters` | none | Daily trend filters (`overnight` only affects setups the engine doesn't trade) |
| `--market-data-source` | as the OR engine | `tradestation`, `local_ts_broadcast` (needs the bar broadcaster), ... |
| `--no-notify` | off | No Telegram / SMS |

`--replay-*` flags are refused with `--strategy wave-setups`; replay with `wave_monitor_replay.py run --engine`
(below).

## How it trades

- **Entries:** each BUY / SHORT intent of an intraday setup. Shares = $balance / slots ÷ price
  (`PositionSizer.compute_stock`). Skipped (logged `WAVE skipped (...)`) when every slot is taken, when the balance
  less the open positions' cost is below one slot, or when the broker's buying power is short.
- **Exits:** the strategy's SELL / COVER intents (stop, target, give-back, close decision) close the position through
  `PositionMonitor._close_position`; the OR engine's own exit rules (hard stop arming, trailing MA, re-entry watchers)
  never run on these positions. `RAISE STOP` intents (`--drive-trail`) move the position's stop.
- **End of session:** anything still open is closed at its last close (`end_of_day`).
- **Failed close orders** are retried on the ticker's next 3 bars, then a system alert asks for a manual close; the end
  of the session tries a market order whatever the count.
- **Notifications** start with `[wave engine]`; mock order messages with `[SIMULATE]`. One summary at the close
  (trades closed, $ total).

## Files

All under `logs/` of the checkout it runs from (`cli/daemon._LOG_DIR`):

| File | Contents |
|---|---|
| `wave_strategy_engine_<date>.log` | Log: 5-min bars, `WAVE ...` decisions and skips, `SYSTEM ...` messages, errors |
| `wave_strategy_engine_trades_<date>.csv` | One row per order: time, ticker, setup, action, price, shares, order, pnl |
| `wave_strategy_engine_state.json` | Strategy state, open positions, failed closes (same session only) |
| `wave_strategy_engine.pid` | PID of the daemon (unless `--pid-file` is given) |

Follow the day with `tail -f logs/wave_strategy_engine_$(date +%F).log | grep -E "WAVE|SYSTEM|ERROR"`.

## Restarts

`stop` / `restart` / SIGTERM / a crash during the session only save the state: open positions stay open, and a restart
the same session restores them and keeps managing their exits. Positions left open by an earlier session are not
restored; the engine alerts them ("check the broker"). A market holiday logs "Market closed today" and exits.

## EC2

Since 2026-11-20 the engine runs in mock mode beside the monitor (crontab, 04:00 ET weekdays, after the 03:30 ET
`trade_engines.sh restart` pulls the code and restarts the bar broadcaster):

```
0 4 * * 1-5 cd /home/ec2-user/alpha_tech_tracker && PYTHONPATH=/home/ec2-user/alpha_tech_tracker \
  /home/ec2-user/.pyenv/versions/alpha_tech_tracker/bin/python -m alpha_tech_tracker.op_momentum_strategy.op_momentum_trade_engine \
  restart --strategy wave-setups --mock-trade-execution --no-notify --market-data-source local_ts_broadcast --workers 0 \
  --short-setups drive --short-gate qqq-ma50-down10 --trend-filters overnight >> /home/ec2-user/wave_strategy_engine_cron.log 2>&1
```

It reads bars from the local broadcaster (no extra TradeStation streams); the broadcast client reconnects by itself
when the broadcaster restarts. Keep its flags in step with the monitor's crontab line.

**Daily check** (on the node, after the close): the engine should have traded every intraday entry / exit the monitor
alerted, at the same prices, except entries it skipped for slots or balance (see `WAVE skipped` in its log).

```bash
cd ~/alpha_tech_tracker && D=$(mktemp -d) && day=$(date +%F)
cp logs/wave_setup_alerts_$day.csv logs/wave_strategy_engine_trades_$day.csv $D/
PYTHONPATH=$PWD ~/.pyenv/versions/alpha_tech_tracker/bin/python -m \
  alpha_tech_tracker.op_momentum_strategy.analysis_scripts.wave_monitor_replay parity $D $D
```

## Replay and parity

`analysis_scripts/wave_monitor_replay.py` replays recorded sessions through the monitor or, with `--engine`, through
the runner (mock fills), and `parity` checks the engine traded every intraday entry / exit the monitor alerted:

```bash
B=alpha_tech_tracker/op_momentum_strategy/backtest_result/wave_strategy_refactor_baseline
M="python -m alpha_tech_tracker.op_momentum_strategy.analysis_scripts.wave_monitor_replay"
OUT=$(mktemp -d)
$M run --bundle $B/bundle --out $OUT/prod -- --short-setups drive --short-gate qqq-ma50-down10 --trend-filters overnight
$M run --engine --bundle $B/bundle --out $OUT/engine -- --short-setups drive --short-gate qqq-ma50-down10 \
  --trend-filters overnight
$M parity $OUT/prod $OUT/engine
```

On the 2026-11-02..11 baseline every monitor entry / exit was traded (prod flags 140 / 140 rows; all options on
132 / 132, plus 10 exits the monitor drops after a mid-session restart).

## Differences from the monitor

- **Intraday only:** no overnight holds (no MOC entries / MOO exits). Overnight setups stay in the strategy so the
  intraday decisions match the monitor's, and are logged `WAVE not traded (overnight)`.
- **Capital limits:** the monitor alerts every signal; the engine skips entries when the slots or the balance are used.
- **Restarts:** a mid-session monitor restart loses its open trades' exit alerts (known monitor bug, see the plan);
  the engine keeps the positions and their exits.
- **Live fills:** in paper / live the broker's fill goes on the position and the trades CSV, while the strategy keeps
  deciding on its reference prices, so P&L differs from the monitor's by the slippage.

Not built yet: overnight holds in the engine, TradeStation execution, protective stop orders at the broker.

## Code map

| File | Role |
|---|---|
| `cli/args.py` | `--strategy` and the wave flags; refuses `--replay-*`; picks the wave PID file |
| `cli/wave.py` | `wave_setups` (config + short tickers), `build_wave_runner`, `run_wave_strategy` (SIGTERM = stop) |
| `op_momentum_trade_engine.py` | Branches `run` / `start` to the wave runner; mock builds no broker client |
| `wave_strategy_runner.py` | `WaveStrategyRunner`: session loop, intents → positions / orders, state, trades CSV |
| `strategies/base.py` | The `Strategy` protocol the runner drives |
| `wave_strategy/` | The strategy shared with the monitor: `strategy.py`, `feed.py` (`BarFeed`), `intents.py`, `trades.py`, `specs.py`, `session.py`, `bars.py` |

Tests: `tests/op_momentum_trade_engine/test_wave_strategy_runner.py`, `test_wave_strategy_cli.py`,
`test_wave_strategy.py`, `test_wave_strategy_feed.py`, `test_wave_strategy_intents.py`.

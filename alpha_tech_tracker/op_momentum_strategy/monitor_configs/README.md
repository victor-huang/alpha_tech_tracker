# Prod monitor configs

Copies of the wave setup monitor config that ran on the EC2 box (`~/alpha_tech_tracker/logs/wave_setup_monitor_config.json`),
kept for reference. Add a dated file here whenever prod changes, and update the table.

| File | In prod | Tickers and setups | How it was picked |
|---|---|---|---|
| `2026-10-06_prod.json` | Oct 6 2026 | MRNA (drive long, overnight always, pullback long), SNDK (drive long, drive short, overnight always), APP (drive short, box gap, bounce short), GOOGL (drive short, drive long, overnight always) | Setup report top 3 per ticker |
| `2026-10-07_prod.json` | Oct 7 – Nov 6 2026 (backup on EC2: `logs/wave_setup_monitor_config.json.bak-20261007-prod`) | MRNA (drive long, overnight always, pullback long), SNDK (drive long, drive short, overnight always), APP (drive short, box gap, bounce short), AMD (overnight always, bounce long, pullback long), MDB (drive long, pullback long, box break), CRWV (drive short, box break, drive long), SNPS (overnight always, drive short, pullback long C1) | Setup report Jul 9 – Oct 6 2026, top 3 per ticker by fixed-exit total |
| `2026-11-09_prod.json` | from Nov 9 2026 (deployed Nov 8, 22:43 ET; loaded by the 00:00 ET Monday restart) | MRNA, SNDK, APP, SNPS, SHOP, AMD: each drive long + pullback long (C1 for SNDK, APP) + overnight always | Mix search over 582 five-to-seven-ticker sets (May 7 – Sep 7 picked, Sep 8 – Nov 6 checked) from the Oct 7 list and the Nov 6 `ticker_screen` picks; AMD added for spread |

## Monitor flags (cron command on EC2)

| From | Flags |
|---|---|
| Oct 27 2026 | `--short-setups drive` |
| Nov 9 2026 | `--short-setups drive overnight --short-gate qqq-ma50-down10 --overnight-short-gate qqq-ma200 --trend-filters overnight` |

Last five weeks (Oct 5 – Nov 6 2026, same rules): the Nov 9 set +$969 (max drawdown −$635), the Oct 7 set +$629
(−$444).

## Results for reference (backtest, $10k, the Nov 9 flags, May 7 – Nov 6 2026)

| Set | 6 months | Max drawdown | Worst week | Sep 8 – Nov 6 |
|---|---|---|---|---|
| Oct 7 config (7 tickers, its own setups) | +$6,148 | −$750 | −$391 | +$1,324 |
| MRNA SNDK APP SNPS SHOP, new setups | +$7,613 | −$729 | −$368 | +$2,059 |
| MRNA SNDK APP SNPS SHOP AMD, new setups (in prod from Nov 9) | +$6,170 | −$757 | −$448 | +$1,817 |

The Oct 7 list and its setups were picked on Jul–Oct data and the new sets partly on Sep–Nov, so both are flattered
by hindsight; see the ticker-tuning doc, Findings 39–42.

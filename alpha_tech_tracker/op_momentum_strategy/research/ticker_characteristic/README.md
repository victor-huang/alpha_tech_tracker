# Ticker characteristics

One document per ticker, recording how that stock behaves intraday: which candle patterns mark its wave
lows and highs, how its waves are sized and timed, and which setups have and have not worked on it. The
cross-ticker research lives in
[`research/findings/wave_risk_reward_strategy_ticker_params_tunning.md`](../findings/wave_risk_reward_strategy_ticker_params_tunning.md);
these pages collect what is specific to one ticker.

Conventions, so the pages stay comparable:

- **Bars:** regular-hours 5-min SIP bars from Alpaca, split-adjusted, with volume.
- **Waves:** the wave model (`alpha_tech_tracker/wave.py`) replayed bar by bar exactly as
  `wave_risk_reward.analyze_bars` builds it, so every "candidate" uses only what was known on that bar.
- **Candidates and hits:** a candidate bottom is a bar where the current wave is down, has fallen at least 3
  average bars (the trailing 78-bar mean high − low) from its high to this bar's low, and trades within 1
  average bar of the wave's lowest low so far — the moments a dip buyer asks "is this the low?". A candidate is
  a hit when it is within one bar of the finished wave's lowest low. Tops mirror this.
- **Precision** = hits / firings of a signal; **lift** = precision / the baseline share of candidates that are
  hits; **recall** = the share of all hits the signal fires on.
- **Every result names its years.** A pattern found on one year counts only once it holds on another.
- **Pattern functions** live in `alpha_tech_tracker/technical_analysis.py`: `long_tail_reversal`,
  `long_tail_reversal_combo`, `engulfing_reversal`, `piercing_reversal`, `push_reversal`, and from these studies
  `confirmed_long_tail_reversal` (long tail + the next candle closing beyond it) and
  `volume_long_wick_reversal` (a 50%+ wick on 1.5x volume); `piercing_reversal(trend="down")` is the dark cloud cover. On 5-min bars pass the
  ticker's average bar range as a fraction of price as `daily_movement_minimum` (the defaults are for daily
  candles).

| Ticker | Page | Last updated |
|---|---|---|
| AMD | [AMD.md](AMD.md) | 2026-10-14 |
| APP | [APP.md](APP.md) | 2026-10-14 |
| CRWV | [CRWV.md](CRWV.md) | 2026-10-14 |
| MDB | [MDB.md](MDB.md) | 2026-10-14 |
| MRNA | [MRNA.md](MRNA.md) | 2026-10-14 |
| SNDK | [SNDK.md](SNDK.md) | 2026-10-14 |
| SNPS | [SNPS.md](SNPS.md) | 2026-10-14 |

## Across the monitored tickers (candle patterns at wave lows and highs, 2025 and 2026)

The seven tickers on the EC2 wave monitor, studied the same way. What they share:

- **The reversal bar is wider and on heavier volume than the look-alike bars around it**, for every ticker,
  side and year (range 1.00–1.28x vs 0.81–1.00x average; volume 0.89–1.39x vs 0.73–1.01x).
- **A long wick alone is no signal** (lift 0.78–1.09 everywhere), and **closing beyond the previous bar's
  extreme comes late** (lift 0.60–0.90 everywhere: the turn is usually two or more bars back).
- **A long tail confirmed by the next bar is the most dependable common signal**: lift 1.60–1.93 at lows and
  1.53–2.18 at highs, for every ticker in both years, about 0.35–0.55 firings a day, catching 4–8% of extremes.
- **Push and piercing are the most accurate but rare** (often 60–90%, about one firing a week or less) and
  vary more from year to year.
- **Morning / evening star does not help** (lift 0.48–1.41, mostly below 1).

| Ticker | Baseline at lows 2025 / 2026 | Long tail + confirm at lows | Wick ≥ 50% + volume ≥ 1.5x at lows | Long tail + confirm at highs | Volume at real lows vs others (2026) |
|---|---|---|---|---|---|
| AMD | 32% / 32% | 57% / 57% | 46% / 57% | 49% / 44% | 1.23x vs 0.88x |
| APP | 32% / 25% | 53% / 47% | 47% / 38% | 52% / 51% | 1.13x vs 0.91x |
| CRWV | 31% / 29% | 56% / 51% | 48% / 41% | 57% / 49% | 1.17x vs 0.84x |
| MDB | 33% / 26% | 59% / 50% | 52% / 36% | 51% / 56% | 1.02x vs 0.77x |
| MRNA | 27% / 27% | 51% / 47% | 45% / 47% | 48% / 55% | 1.01x vs 0.73x |
| SNDK | 31% / 34% | 52% / 60% | 47% / 48% | 53% / 58% | 1.36x vs 1.01x |
| SNPS | 33% / 31% | 53% / 54% | 42% / 40% | 50% / 47% | 0.93x vs 0.77x |

Piercing / dark cloud, push and long tail + confirm are alerted live by the wave setup monitor
(`reversal_watch.py`, information only; see `guides/WAVE_SETUP_MONITOR_GUIDE.md`, Reversal alerts).

Pairs are 2025 / 2026 precision. These are measures of finding the extreme, not of profit; trading them (with
stops, the top signals as exits and costs) is the next step, on years they were not found on.

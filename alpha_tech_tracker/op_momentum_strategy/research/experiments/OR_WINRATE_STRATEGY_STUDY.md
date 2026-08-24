# OR-Direction + Trailing-Win-Rate Strategy Study

Study period: 2026-08-22 → 2026-08-23. Backtest coverage 2019-01-01 → 2026-08-20 (8 years).

## Question

Can a stock strategy be built from three inputs — the opening-range direction, a
rolling per-ticker win rate, and option put/call open interest — and does it add
anything over the existing M1 options window?

**Answer: marginally positive on stock, not tradeable on options.** Roughly
+8–11%/year on a $10k daily book after 5bp costs, negative at 10bp. The put/call
leg could not be tested at all (see Negative Results).

## Strategy as tested

| Stage | Rule |
|---|---|
| Universe | V3 live pool, 17 tickers (`op_momentum_selector.DEFAULT_TICKERS`) |
| Selection | Top-N by 15:50 win rate over the prior 10 sessions, minimum 50% |
| Direction | `or_close > or_mid` → long; `or_close < or_mid` → short. OR = first 3 five-min bars |
| Entry | 09:45 ET at the OR close |
| Hard stop | 5% adverse from entry |
| Trailing | MA on 5-min closes, active after 1 bar |
| Time exit | 14:15 ET default (11:15 PT); 15:50 tested |
| Regime gate | No longs when QQQ closed below its daily MA20 on the **prior** session |
| Extension gate | Skip entries >1.5 × rolling ADR from the stock's daily MA20 |
| Sizing | $10k per session split across surviving picks, reset daily, no compounding |

P&L is stock-based, gross of financing and borrow.

## Best configurations

```bash
# highest scoring in the final harness
--stop-pct 5 --regime-gate longs --top 3 \
--trail-strong 50 --trail-consolidation 20 --trail-weak 8 --regime-source benchmark

# most robust across harness versions — recommended
--stop-pct 5 --regime-gate longs --top 3 --trailing-ma-period 20

# for costs >= 10bp
--stop-pct 5 --regime-gate longs --top 3 \
--trail-strong 50 --trail-consolidation 20 --trail-weak 8 --min-or-vol-ratio 1.5
```

### P&L % of the $10k base, by year

| config | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026¹ | TOTAL | up |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| QQQ-adaptive t3, 0bp | +16.6 | +0.4 | +3.1 | +42.3 | +2.7 | +18.6 | +48.2 | +36.5 | **+168.3** | 8/8 |
| MA20 fixed t3, 0bp | +14.3 | −6.3 | +11.8 | +50.9 | +12.3 | +2.2 | +17.7 | +45.4 | **+148.2** | 7/8 |
| stock-adaptive t2, 0bp | +27.9 | −10.2 | +1.1 | +58.1 | −9.2 | +9.3 | +19.8 | +56.6 | +153.5 | 6/8 |
| stock-adaptive t3, 0bp | +26.5 | −1.6 | +7.3 | +29.0 | −9.2 | −0.7 | +23.6 | +50.2 | +125.2 | 5/8 |
| vol≥1.5 gate t3, 0bp | +5.0 | +13.2 | −1.5 | +16.7 | +2.1 | +19.5 | +11.7 | +11.4 | +78.1 | 7/8 |
| stock-adaptive t3, no realloc | +15.6 | −3.2 | +2.4 | +19.8 | −0.5 | +1.4 | +15.6 | +23.5 | +74.6 | 6/8 |

¹ 2026 is YTD through 08-20.

### Cost sensitivity — the binding constraint

| config | 0bp | 2bp | 5bp | 10bp | trades |
|---|---:|---:|---:|---:|---:|
| MA20 fixed t3 | +148.2 | +116.6 | +69.2 | **−9.8** | 3,294 |
| QQQ-adaptive t3 | +168.3 | — | +88.6 | — | 3,287 |
| vol≥1.5 gate t3 | +78.1 | — | +54.1 | **+30.2** | 564 |

Breakeven sits between 8 and 10bp for the unfiltered variants. The volume gate is
the only configuration still clearly positive at 10bp, because 564 trades pay six
times less total cost than 3,294.

## Robust findings

These held across every version of the harness.

1. **A regime gate on longs is the single most valuable filter.** Blocking bull
   signals when QQQ closed below its daily MA20 yesterday lifted 8-year totals by
   ~17pp and fixed 2020, the only losing year at the time. Blocking shorts in the
   mirror case (`--regime-gate both`) destroys value: shorting strength works,
   buying weakness does not.
2. **MA20 trailing beats MA8.** MA8 exits at a 15–20 minute median hold, roughly
   half of trades inside 15 minutes, forfeiting most of the excursion the signal
   generates. MA20 raises median hold to ~35 minutes. MA30/MA50 do not improve
   further.
3. **A 5% hard stop beats a stop at the OR extreme.** The OR extreme sits ~1.4%
   from entry and is clipped by noise: it fired on 9–11% of trades at a 0% win
   rate. At 5% it fires on <2% and the tail is still capped.
4. **Looser exits beat tighter ones, up to a point.** Widening the stop 3% → 5%
   added ~15pp. Loosening beyond MA20, or removing the trailing entirely, reverses.
5. **The market's direction on the day dominates outcomes.** Trades aligned with
   QQQ's open→close returned +$24,777 against −$16,777 for trades fighting it — an
   18pp win-rate spread. This is attribution only: QQQ's close is not knowable at
   09:45. It explains why the strategy fails, not how to avoid it.
6. **OR volume predicts trade quality, U-shaped in P&L.** Volume ≥2.5× the
   ticker's prior 20-session OR average: 59.3% win rate and $20.01/trade versus
   42.4% and $0.76 for the 1–1.5× bucket. Average-volume opens are the dead zone.
   Max favourable excursion rises monotonically with volume (1.04% → 2.09%).
7. **Costs, not signal, are the constraint.** Per-trade edge tops out near 16bp
   gross and 5–10bp of friction removes most of it.

## Negative results

- **Put/call open interest could not be tested.** Alpaca exposes only the latest
  open interest: expired expiries return zero rows and there is no as-of-date
  parameter. `--pc-mode snapshot` applies one reading to every session, which is
  both a lookahead and a constant per-ticker bias — it bans tickers rather than
  gating signals. A real test needs a dated CSV built by recording daily snapshots
  going forward (`--pc-mode file`).
- **MA20 entry confirmation hurts** (−31pp). Requiring the OR close beyond the
  5-min MA20 removes ~30% of entries, disproportionately winners. The
  OR-midpoint break already encodes the momentum. Note the live engine *does* use
  this, paired with a much stricter bear rule.
- **Regime-adaptive trailing does not beat fixed MA20.** Tested with both QQQ's
  and each stock's own daily stack, and with mappings from time-exit to MA50.
  Holding to the time exit in strong regimes is the worst idea tested
  (−22.6% in 2020) — the trailing stop does more work in trending markets than in
  broken ones.
- **Exiting at 14:15 ET instead of 15:50 hurt** when trailing was loose or absent
  (−37pp over three years). With MA20/MA8 trailing active the two exit times give
  **identical** results, because the trailing stop always fires first.
- **The volume gate improves quality but costs total return** at low friction:
  +148% → +78% at 0bp while per-trade rises $4.50 → $13.84. It only wins once
  costs reach ~10bp.
- **Survivorship bias is large and measurable.** A hand-picked 7-ticker pool
  (SNDK/APP/NVDA/LLY/MRNA/COIN/HOOD, chosen with 2026 hindsight) scored +63.2%
  over 8 years where the V3 pool scored +23.3% under identical rules — roughly
  three times the edge, entirely from ticker selection after the fact.

## Walk-forward test of ticker selection (2023–2026)

Separate from the backtest, the `ticker_stats_report` bias table was walked forward
one session at a time: the pick for day D uses only sessions before D, and is traded
only when that day's opening range fires in the picked direction.

Two hit definitions are reported. **Intraday hit** counts sessions whose move in the
OR's direction reached the follow-through bar (0.25 x ADR), so it measures whether the
stock travelled. **EOD hit** counts sessions still profitable at 15:50, so it measures
whether the move held.

| year | sel n | sel intraday | base intraday | sel EOD | base EOD |
|---|---:|---:|---:|---:|---:|
| 2023 | 1,167 | 62% | 60% | +0.05% | -0.01% |
| 2024 | 1,062 | 59% | 60% | -0.01% | -0.04% |
| 2025 | 1,275 | 63% | 62% | +0.10% | +0.06% |
| 2026 YTD | 789 | 62% | 62% | +0.10% | +0.08% |

**Selection is worth +0.3pp intraday hit and +3.5bp EOD over 4,293 trades — inside
noise.** Six rules were tried: trailing EOD win rate, trailing median return, trailing
intraday hit, an exit switched by the 15m-vs-EOD spread, regime-conditioned variants,
and the thrust waiver. None beat taking every signal.

Regime conditioning does not rescue it. No QQQ trend bucket holds its sign across four
years — `BREAKDOWN_ATTEMPT` runs -8pp (2024), +9pp (2025), +9pp (2026);
`DOWNTREND` runs +17pp (2023), 0pp (2025), -12pp (2026). With six buckets across four
years the cells scatter around zero.

### The one relationship that replicates everywhere

| year | baseline avg max gain | baseline avg EOD |
|---|---:|---:|
| 2023 | +1.46% | -0.01% |
| 2024 | +1.52% | -0.04% |
| 2025 | +1.97% | +0.06% |
| 2026 YTD | +2.21% | +0.08% |

Every trade generates 1.5–2.2% of favourable excursion while holding to 15:50 captures
within ±0.08% of zero. The OR direction call has no end-of-day edge in any of these four
years; the backtest only profits through the stop, the MA20 trailing exit and the two
gates. **Any further work belongs in the exit rule, not in picking tickers.**

## Not robust — read before trusting any ranking

Variant rankings are **unstable to implementation details**. Changing only the
tie-break rule and the selection-history window moved results by 40–90pp and
reordered the leaderboard:

| variant | before | after |
|---|---:|---:|
| stock-adaptive t3 | +180.4% (1st) | +125.2% (4th) |
| QQQ-adaptive t3 | +73.8% (5th) | +168.3% (1st) |
| top-2 vs top-3 | top-2 won | flips by variant |

Treat the fine-grained choices — adaptive vs fixed, stock vs index regime source,
top-2 vs top-3 — as indistinguishable with 8 years and one pool. Only the seven
robust findings above should inform decisions.

## Defects found in the harness

All were found and fixed during the study. Each one changed results materially,
which is why the numbers above supersede everything reported earlier.

| defect | effect | fix |
|---|---|---|
| Benchmark/stock daily bars fetched with 45-day warmup | daily MA200 was NaN until ~September, so the "strong" regime was **impossible in Jan–Aug of every year** | `BENCHMARK_WARMUP_DAYS = 500` |
| ADR extension cap computed from the last 20 sessions of the whole period | lookahead; flattered worst years (−0.8% → −4.3% once fixed) | rolling prior-20 mean, shifted |
| Capital sized across picks *before* the gates | filtered slots sat idle instead of being reallocated; understated every result (+97.3% → +148.5% on identical trades) | size across survivors; `--no-reallocate` keeps the old behaviour |
| Ties broke on reverse ticker name | late-alphabet tickers systematically won slots; win rates quantize to 10% steps so ties are common | tie-break on OR volume ratio, known at 09:45 |
| Selection history sliced from the reporting window | first 10 sessions of every run dropped, ~80 sessions over 8 years | history reaches into the warmup window |

Two known limitations left in place deliberately: the selection win rate is
computed on *ungated* outcomes (it measures the signal, not the filtered book),
and with reallocation a single surviving pick receives the full $10k, so maximum
single-name exposure is 100% of the daily book.

## Files

| path | purpose |
|---|---|
| `analysis_scripts/or_winrate_pc_backtest.py` | the backtest; all flags above |
| `analysis_scripts/ticker_stats_report.py` | OR-direction stats, option OI skew, opening volume, daily movement |
| `backtest_result/best_*.csv`, `final_*.csv` | per-trade rows |
| `trade_api/alpaca_client/client.py` | `get_options_open_interest()`, `main_monthly_expiry()` |

Byproducts worth keeping regardless of the strategy verdict:

- `get_options_open_interest()` on `AlpacaAPIClient` — call/put and put/call OI
  ratios for any expiry and strike band, plus `open_interest` now surfaced from
  `get_options_contracts()` with pagination. 20 unit tests.
- `ticker_stats_report.py` — per-ticker bull/bear OR outcome stats with
  ADR-normalised follow-through thresholds.

## Open questions

1. Start recording daily put/call OI so `--pc-mode file` becomes testable in ~2 months.
2. Walk-forward validation: every number here is in-sample on a pool selected in 2026.
3. Does the regime gate on longs help the existing M1 options window? That is the
   one finding most likely to transfer.
4. Concentration cap on reallocation — 100% single-name exposure is aggressive.

## Reproduce

```bash
source ~/.pyenv/versions/alpha_tech_tracker/bin/activate
export PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker

python -m alpha_tech_tracker.op_momentum_strategy.analysis_scripts.or_winrate_pc_backtest \
  --tickers CHTR APP SHOP CVNA AMD META EXPE JPM TSLA MU CRDO PLTR COIN CLS MSTR CRWV MRVL \
  --start 2019-01-01 --end 2026-08-20 \
  --stop-pct 5 --regime-gate longs --top 3 --trailing-ma-period 20 \
  --cost-bps 5 --weekly
```

# Recommended top-15 rules (as of 2026-11-09)

The rules to trade, defined once in `alpha_tech_tracker/research/recommended_rules.py` (`RECOMMENDED`), with the backtest that settled the open choices. Outputs: `research/top_performers_output/uptrend_formation/recommended_rules/` (`performance.csv`, `by_year.csv`).

## The rules

All books are top 15, equal weight, rebalanced every 10 trading days (the biweekly checkpoints), no holding buffer and no market gate.

| Tier | Selection | Exit between checkpoints |
|---|---|---|
| Large (≥ $10B) | Trend filter; rank by 180-day return / vol_60d^0.5. The first 5 places go to the 3 strongest big-volume gap-ups and the 2 strongest fresh 52-week highs (both above the 20/50/200-day averages, last 10 trading days). | Sell on a close 25% below the peak close since entry. |
| Small | Trend filter; rank by composite, excluding names whose share count rose 10%+ in a year; top-30% gross-profitability names moved to the front of the top 30. | Sell on a close 15% below the peak close since entry. |
| Mid | Skip. | |

A stopped-out name stays out until the next checkpoint, when it can be bought back if it is still on the list.

## Daily and biweekly commands

```
# biweekly, after the checkpoint day's close: the lists, with new and dropped names and each name's entry checkpoint
PYTHONPATH=. python -m alpha_tech_tracker.research.paper_lists --refresh
# daily, after the close: trailing-stop status of every held name
PYTHONPATH=. python -m alpha_tech_tracker.research.exit_watch
```

`paper_lists` also prints the previous Large rule (`large_previous`) for comparison.

## Backtest, 2020–2026

### Small safeguards

The earlier suggestion listed a $20M dollar-volume floor and an 8-checkpoint streak cap as safeguards, but the Small rule never applied them.

| Small rule | CAGR | Sharpe | Max DD | Vol |
|---|---|---|---|---|
| **base (recommended)** | **18.6%** | **0.83** | −43% | 24% |
| + $20M dollar-volume floor | 8.3% | 0.41 | −52% | 39% |
| + streak cap | 18.8% | 0.84 | −43% | 24% |
| + both | 9.1% | 0.43 | −52% | 39% |

The floor removes the quiet, profitable small caps the rule is built on and leaves the volatile ones. The streak cap does not matter, so it is left out. Keep each position small relative to a name's daily dollar volume instead.

### Exits

| Tier | Exit | CAGR | Sharpe | Max DD | Exits / year | Years better than no exit |
|---|---|---|---|---|---|---|
| Large | none | 30.6% | 1.08 | −28% | 0 | |
| Large | **25% trailing stop** | **30.6%** | **1.10** | **−27%** | 11 | 4/7 |
| Large | 15% trailing stop | 25.8% | 1.00 | −26% | 47 | 3/7 |
| Large | close below 50-day average | 26.9% | 1.06 | −30% | 91 | 2/7 |
| Small | none | 18.6% | 0.83 | −43% | 0 | |
| Small | **15% trailing stop** | **20.4%** | **1.00** | **−25%** | 21 | 2/7 |
| Small | 25% trailing stop | 19.8% | 0.93 | −34% | 4 | 2/7 (2 ties) |
| Small | close below 50-day average | 17.8% | 0.97 | −21% | 96 | 3/7 |

- **Large:** the 50-day exit that helped the previous Large rule hurts the 180-day rule: it sells leaders on ordinary pullbacks. A 25% trailing stop costs nothing and trims the drawdown slightly; it is a safety net, not an edge.
- **Small:** the 15% stop nearly halves the drawdown. Its return gain comes from the 2020 crash and rebound; in 5 of 7 years it costs 1–7 points. It is insurance against a crash, paid for in normal years.

## Caveats

- **In-sample:** the Large rule's 180-day setting was chosen out of sample from 2022 on ([walk_forward_tuning_2020_2026.md](walk_forward_tuning_2020_2026.md)), but the exits and the full-period figures here use all seven years.
- **Survivorship and execution:** as in [selection_filters_2020_2026.md](selection_filters_2020_2026.md). Stops are simulated at the close that breaches them.

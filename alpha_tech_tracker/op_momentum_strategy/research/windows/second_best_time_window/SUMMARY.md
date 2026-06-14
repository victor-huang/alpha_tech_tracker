# Opening Window Sweep — 2025-01-01 → 2026-03-27

**Params**: `--regime-filter --regime-ma 8 --weights 50 30 20 --top 3`, pool = V2 (16 tickers), capital = $10,000

## Axis 1 — Entry time sweep (fixed 3 bars / 15-min window)

| Opening start | Entry time | Final portfolio | Total return |
|---|---|---|---|
| **09:30** | **9:45** | **$22,299** | **+123%** |
| 10:00 | 10:15 | $16,716 | +67% |
| 10:15 | 10:30 | $15,642 | +56% |
| 09:45 | 10:00 | $15,578 | +56% |
| 11:15 | 11:30 | $14,006 | +40% |
| 10:30 | 10:45 | $13,373 | +34% |
| 13:00 | 13:15 | $13,009 | +30% |
| 13:30 | 13:45 | $12,055 | +21% |

**Top 3 start times**: `09:30`, `10:00`, `10:15`

## Axis 2 — Window width sweep (top 3 start times)

| Opening start | Bars | Window | Entry time | Final portfolio | Total return | Win rate |
|---|---|---|---|---|---|---|
| **09:30** | **1** | **5 min** | **9:35** | **$23,926** | **+139%** | **32%** |
| 09:30 | 4 | 20 min | 9:50 | $20,256 | +103% | 35% |
| 09:30 | 2 | 10 min | 9:40 | $19,870 | +99% | 31% |
| 09:30 | 3 | 15 min | 9:45 | $22,299 | +123% | 37% |
| 09:30 | 6 | 30 min | 10:00 | $17,340 | +73% | 37% |
| 10:00 | 1 | 5 min | 10:05 | $17,352 | +74% | 27% |
| 10:00 | 6 | 30 min | 10:30 | $16,102 | +61% | 33% |
| 10:00 | 4 | 20 min | 10:20 | $16,377 | +64% | 33% |
| 10:00 | 3 | 15 min | 10:15 | $16,716 | +67% | — |
| 10:00 | 2 | 10 min | 10:10 | $15,769 | +58% | 30% |
| 10:15 | 1 | 5 min | 10:20 | $17,532 | +75% | 26% |
| 10:15 | 2 | 10 min | 10:25 | $15,670 | +57% | 32% |
| 10:15 | 4 | 20 min | 10:35 | $13,863 | +39% | 29% |
| 10:15 | 6 | 30 min | 10:45 | $13,192 | +32% | 31% |

## Conclusions

- **Overall winner: `09:30 / 1 bar` (entry 9:35) → $23,926 (+139%)** — fastest signal, captures the opening breakout before it reverses
- **Second: `09:30 / 3 bars` (entry 9:45) → $22,299 (+123%)** — the confirmed default; more stable signal with higher win rate (37% vs 32%)
- **Third: `09:30 / 4 bars` (entry 9:50) → $20,256 (+103%)** — slightly later but still strong
- All top results cluster around `09:30` start; any shift away from it costs significantly
- `10:00` and `10:15` are consistent #2/#3 start times but trail by 50–70pp
- Win rate is notably lower for 1-bar (`09:30/1`: 32%) vs 3-bar (`09:30/3`: 37%) — 1-bar trades are noisier with bigger wins compensating

## Note on `09:30 / 1 bar`

The 1-bar entry fires at the close of the 9:30 bar (i.e. 9:35), before any opening range has formed. It essentially bets on the first 5 minutes' direction. Higher return but lower win rate — more volatile in live trading and harder to execute reliably.

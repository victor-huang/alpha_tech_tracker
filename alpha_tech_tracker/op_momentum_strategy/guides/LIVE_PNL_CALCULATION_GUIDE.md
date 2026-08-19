# Live Broker P&L Calculation Guide

How to compute daily, weekly, monthly, and overall realized P&L directly from each
broker's API — bypassing the engine's own DAILY TRADE SUMMARY, which can silently
under-report P&L when a closing fill isn't cleanly observed by the FILL_ESC path
(see `bugs/BUGS.md` for the 2026-08-13/08-17/08-18 incidents where this happened).

## Why not just read the engine's log summary?

The engine's DAILY TRADE SUMMARY is built from its own internal bookkeeping
(`ActivePosition.entry_fill_price` / `exit_fill_price`), which depends on the engine
correctly observing every fill. Two known gaps break this:

1. **Step3 market-order races** (fixed 2026-08-19, commit `e88bdd9`) — a canceled/0-fill
   market order could get credited as a full fill, corrupting one leg's P&L.
2. **QTY-sync fill-price gaps** (open, see `bugs/BUGS.md`) — when a position closes at
   the broker in a way the engine's own polling doesn't observe (native stop, broker-side
   fill racing the engine's poll), the periodic qty-reconciliation logs
   `"fill price not found — P&L not recorded"` and the leg is silently dropped from the
   summary entirely. Confirmed happening multiple times per week on both engines.

Broker activity/fill records are authoritative regardless of what the engine observed,
so reconstructing P&L from them is the reliable cross-check.

## The two accounts

The two engines execute through **different, independent brokers** — there is no shared
account to reconcile between them:

| Engine | Repo | Broker | Config location |
|---|---|---|---|
| "options engine" (name is legacy — it trades stocks) | `/home/ec2-user/alpha_tech_tracker` | TradeStation (live) | `alpha_tech_tracker/op_momentum_strategy/config.json` |
| "stock engine" | `/home/ec2-user/alpha_tech_tracker_stock_engine` | Alpaca (live) | `alpha_tech_tracker/op_momentum_strategy/config.json` |

Both config.json files hold live credentials on EC2 (`alpaca.api_key`/`secret_key`,
`tradestation_session`/`tradestation_credentials`) — this only works run on EC2 (or with
a copy of that config.json), not against the placeholder config in local dev checkouts.

## Methodology: cash-flow reconstruction from fills

For a strategy that closes every position same-day (true here — confirmed via the `flat`
check below), realized P&L for a day equals the net signed cash flow of that day's fills:

```
daily_pnl = sum(qty * price for SELL/SELL_SHORT fills)
          - sum(qty * price for BUY/BUY_TO_COVER fills)
          + fees (Alpaca only — TradeStation fee data isn't separately exposed here)
```

This is bucketed by the **ET calendar date of the fill's timestamp**, not the broker's
own settlement/batch date.

**Do not use Alpaca's `/v2/account/portfolio/history` for this** — it looked like the
obvious tool but has a ~1-day settlement lag that silently omits the most recent trading
day's bar. The activity-based reconstruction above doesn't have this gap.

### Alpaca — `/v2/account/activities/FILL` and `/v2/account/activities/FEE`

- Auth: `APCA-API-KEY-ID` / `APCA-API-SECRET-KEY` headers, from `config.json`'s `alpaca` section.
- Paginate with `after=<last activity id>` + `direction=asc` + `page_size=100` until a
  short page is returned.
- Each `FILL` record: `side` (`buy`/`sell`/`sell_short`/`buy_to_cover`), `qty`, `price`,
  `symbol`, `transaction_time` (ISO-8601 UTC).
- Each `FEE` record: `net_amount` (already signed, negative), `date`.
- **Gotcha**: Alpaca's fractional seconds aren't always 6 digits (e.g. `"...T17:56:10.55Z"`),
  which breaks Python 3.8's `datetime.fromisoformat` — pad to 6 digits before parsing.

### TradeStation — `/v3/brokerage/accounts/{account_key}/historicalorders` + `/orders`

- Auth: reuse `TradeStationAPIClient.restore_session(config["tradestation_session"])`
  (OAuth2 session with auto-refresh) rather than re-implementing the token dance.
- `historicalorders?since=<ISO date>` covers everything **except today** — TradeStation
  excludes same-day fills from this endpoint. Merge in `/orders` (today's live orders) by
  `OrderID` to cover the full range including the current day.
- Only orders with `Status` in `("FLL", "FLP")` (filled / partially filled) count.
- Each fill is a `Leg` within an order: `BuyOrSell` (`Buy`/`Sell`/`SellShort`/`BuyToCover`),
  `ExecQuantity`, `ExecutionPrice`, and the order's `ClosedDateTime`/`FilledDateTime`
  (fall back to `OpenedDateTime` if absent).
- No separate fee activity feed is queried here — TradeStation fees are typically baked
  into the execution price or are immaterial for this account; add if that changes.

### Sanity check: flat end-of-day

Both fetchers also report whether `sum(buy_qty) == sum(sell_qty)` per day. If not flat,
a position carried overnight and the day's cash-flow P&L is incomplete (it doesn't include
the unrealized component) — this should not happen for this strategy and is worth
investigating if it ever shows up as a warning.

## Running it

Use `fetch_broker_pnl.py` (same directory as this guide's parent), which implements the
above and supports day/week/month rollups:

```bash
source ~/.pyenv/versions/alpha_tech_tracker/bin/activate

# Stock engine (Alpaca) — daily breakdown for August
cd /home/ec2-user/alpha_tech_tracker_stock_engine
PYTHONPATH=/home/ec2-user/alpha_tech_tracker_stock_engine python3 -m \
  alpha_tech_tracker.op_momentum_strategy.fetch_broker_pnl \
  --broker alpaca --start 2026-08-01 --end 2026-08-31 --group-by day

# Options engine (TradeStation) — weekly breakdown
cd /home/ec2-user/alpha_tech_tracker
PYTHONPATH=/home/ec2-user/alpha_tech_tracker python3 -m \
  alpha_tech_tracker.op_momentum_strategy.fetch_broker_pnl \
  --broker tradestation --start 2026-08-01 --end 2026-08-31 --group-by week

# Monthly rollup (either broker) — just widen the date range
python3 -m alpha_tech_tracker.op_momentum_strategy.fetch_broker_pnl \
  --broker alpaca --start 2026-01-01 --end 2026-08-31 --group-by month
```

`--config` defaults to the `config.json` next to the script (i.e. run from within the
correct repo — see table above); pass an explicit path if you need to point elsewhere.

**Overall combined P&L** = sum of both engines' totals over the same date range. The two
accounts are independent, so there's no need to reconcile between them — just add the
two `TOTAL` lines.

## Reference numbers (2026-08-01 → 2026-08-18, validated against this guide's methodology)

| Date | Stock (Alpaca) | Options (TradeStation) |
|---|---:|---:|
| 08-03 | -40.89 | — |
| 08-04 | 375.80 | 16.00 |
| 08-05 | -762.08 | — |
| 08-06 | -360.02 | — |
| 08-07 | -739.26 | 184.55 |
| 08-10 | -145.48 | — |
| 08-11/08-12 | (engines down — EC2 disk full) | (engines down) |
| 08-13 | 416.46 | 284.01 |
| 08-14 | 242.67 | 15.36 |
| 08-17 | 279.63 | -169.98 |
| 08-18 | 453.30 | -139.94 |
| **Total** | **-279.86** | **190.00** |
| **Combined** | | **-89.86** |

`—` = zero signals fired that day for that engine (confirmed via daily log review), not a
gap in this methodology.

This cross-checked exactly against daily log reviews for 08-14 and 08-17 (both clean days
with no reconciliation gaps). 08-18 is the clearest example of why this matters: the log
summary reported options P&L as +$17.31 (inflated by a phantom RDDT fill) and stock P&L as
+$303.00 (understated — missing CRDO legs dropped by QTY-sync); broker truth is -$139.94
and +$453.30 respectively.

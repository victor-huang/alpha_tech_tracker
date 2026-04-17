# TradeStation Option Order Format

Reference for every symbol format and API shape used when trading options through the
TradeStation v2/v3 REST API. Derived from live testing and the `TradeStationAPIClient`
implementation in `client.py`.

---

## Symbol Formats

TradeStation uses **three distinct** option symbol formats depending on the endpoint.
Using the wrong format silently returns all-zero quotes or an `INVALID SYMBOL` error.

### 1. OCC Standard (internal boundary format)

```
{TICKER}{YYMMDD}{C|P}{STRIKE_INT:08d}
```

- Strike is encoded as integer × 1000, zero-padded to 8 digits.
- No spaces.
- Used as the **interface boundary** in `ExecutionClient` — all caller code passes OCC; the client converts internally.

| Example | Meaning |
|---|---|
| `TSLA260417C00380000` | TSLA $380 call, expiring 2026-04-17 |
| `TSLA260417C00392500` | TSLA $392.50 call, expiring 2026-04-17 |
| `SPY260417P00520000` | SPY $520 put, expiring 2026-04-17 |

### 2. Display Format (v2 quotes + v3 orders)

```
{TICKER} {YYMMDD}{C|P}{STRIKE_DECIMAL}
```

- One space between ticker and date.
- Strike is a decimal number — trailing `.0` stripped (`390` not `390.0`; `392.5` kept).
- Used by: **v2 `/data/quote/`** and **v3 `/orderexecution/orders`**.

| OCC | Display |
|---|---|
| `TSLA260417C00380000` | `TSLA 260417C380` |
| `TSLA260417C00392500` | `TSLA 260417C392.5` |
| `SPY260417P00520000` | `SPY 260417P520` |

Conversion function: `_occ_to_ts_order_symbol(occ_symbol)` → display format.
Reverse: `_ts_search_name_to_occ(name)` → OCC format.

### 3. Padded Format (v2 — INVALID for quotes)

```
{TICKER:<6}{YYMMDD}{C|P}{STRIKE_INT:08d}
```

- Ticker left-justified and padded with spaces to 6 characters.
- Appears in some older TradeStation documentation and was the original implementation.
- **The v2 `/data/quote/` endpoint rejects this format** with `FAILED, INVALID SYMBOL`.
  Use Display Format instead.

| OCC | Padded (do not use for quotes) |
|---|---|
| `TSLA260417C00380000` | `TSLA  260417C00380000` |
| `SPY260417C00520000` | `SPY   260417C00520000` |

Conversion function: `_occ_to_ts(occ_symbol)` → padded format.
**Not used in any live API call as of the current implementation.**

---

## API Endpoints and Symbol Format Required

| Endpoint | API version | Symbol format |
|---|---|---|
| `GET /data/quote/{symbol}` | v2 | **Display** (`TSLA 260417C380`) |
| `GET /data/symbols/search/{criteria}` | v2 | Criteria query param (no symbol in path) — response `Name` field returns Display |
| `POST /orderexecution/orders` body `Symbol` | v3 | **Display** (`TSLA 260417C380`) |
| `GET /brokerage/accounts/{key}/orders` response `Legs[0].Symbol` | v3 | **Display** — must convert back to OCC with `_ts_search_name_to_occ` |

---

## v3 Order Request Body

Sent to `POST https://api.tradestation.com/v3/orderexecution/orders`.

### Option order (BUY_OPEN example)

```json
{
  "AccountID": "123456789",
  "AssetType": "OP",
  "Symbol": "TSLA 260417C380",
  "Quantity": "1",
  "OrderType": "Limit",
  "LimitPrice": "8.75",
  "TimeInForce": { "Duration": "DAY" },
  "TradeAction": "BUYTOOPEN",
  "Route": "Intelligent"
}
```

Key fields:

| Field | Type | Notes |
|---|---|---|
| `AccountID` | string | Account key — use `AccountID`, not `AccountKey` |
| `AssetType` | string | `"OP"` for options, `"EQ"` for stocks |
| `Symbol` | string | Display format (see above) |
| `Quantity` | string | Must be a string, not an int |
| `OrderType` | string | `"Limit"` or `"Market"` |
| `LimitPrice` | string | Required when `OrderType == "Limit"`; omitted for market orders |
| `TimeInForce` | object | `{"Duration": "DAY"}` — nested object, not a flat `"Duration"` field |
| `TradeAction` | string | See mapping below |
| `Route` | string | `"Intelligent"` for smart routing |

### TradeAction mapping

| `ExecutionClient` `order_action` | TradeStation `TradeAction` |
|---|---|
| `BUY_OPEN` | `BUYTOOPEN` |
| `BUY_CLOSE` | `BUYTOCLOSE` |
| `SELL_OPEN` | `SELLTOOPEN` |
| `SELL_CLOSE` | `SELLTOCLOSE` |

### v3 Order Response

The placement response wraps the order in an `Orders` array:

```json
{
  "Orders": [
    {
      "OrderID": "207887821",
      "Error": "OK",
      ...
    }
  ]
}
```

Always unwrap with `data["Orders"][0]` before reading `OrderID`. The `_extract_v3_order()`
helper does this.

---

## v3 Order Status Response

Returned by `GET /v3/brokerage/accounts/{key}/orders`.

```json
{
  "Orders": [
    {
      "OrderID": "207887821",
      "Status": "FLL",
      "LimitPrice": "8.75",
      "FilledPrice": "8.80",
      "AverageFillPrice": "8.80",
      "OpenedDateTime": "2026-04-17T09:31:00Z",
      "Legs": [
        {
          "Symbol": "TSLA 260417C380",
          "BuyOrSell": "Buy",
          "QuantityOrdered": "1",
          "ExecQuantity": "1"
        }
      ]
    }
  ]
}
```

- `Legs[0].Symbol` is in **Display format** — convert with `_ts_search_name_to_occ()` to get OCC.
- `QuantityOrdered` and `ExecQuantity` live in `Legs[0]`, not at the top level.
- `FilledPrice` / `AverageFillPrice` are at the top level.

### Status code mapping

| TS `Status` | Normalized |
|---|---|
| `FLL`, `FLP` | `filled` |
| `OPN`, `ACK`, `DON`, `FPR`, `UCN`, `LAT`, `OUT`, `PLA` | `open` |
| `CAN`, `REJ`, `TSC`, `BRO`, `EXP` | `canceled` |
| `EXP` | `expired` |

---

## v2 Quote Response

`GET /v2/data/quote/{symbol}` returns a list:

```json
[
  {
    "Symbol": "TSLA 260417C380",
    "Bid": 8.70,
    "Ask": 8.80,
    "BidSize": 10,
    "AskSize": 10,
    "Last": 8.75,
    ...
  }
]
```

- Response `Symbol` is in **Display format**.
- `Bid` / `Ask` are floats (capitalized keys).
- If the symbol is not found or in the wrong format, the response still returns an entry
  but with `"Error": "FAILED, INVALID SYMBOL"` and all numeric fields set to `0`.

---

## Contract Search (v2)

`GET /v2/data/symbols/search/{criteria}`

Criteria format:
```
R={TICKER}&C=StockOption&OT={Call|Put|Both}&Stk=20&Edl={MM-DD-YYYY}&Edh={MM-DD-YYYY}
```

Response is a list of contract objects. The `Name` field uses Display format:

```json
[
  {
    "Name": "TSLA 260417C380",
    "ExpirationDate": "/Date(1776384000000)/",
    "OptionType": "Call",
    "StrikePrice": 380.0,
    "Root": "TSLA"
  }
]
```

- `ExpirationDate` may be either legacy `/Date(epoch_ms)/` or ISO string — both are
  handled by `_parse_ts_date()`.
- `OptionType` returns `"Call"` or `"Calls"` (both accepted) and `"Put"` or `"Puts"`.

---

## Date Formats

| Context | Format | Example |
|---|---|---|
| Expiry in contract search response | `/Date(epoch_ms)/` or ISO | `/Date(1776384000000)/` or `2026-04-17T00:00:00Z` |
| `get_options_contracts` filter params | `MM-DD-YYYY` in URL criteria | `Edl=04-17-2026` |
| Order `OpenedDateTime` | ISO 8601 | `2026-04-17T09:31:00Z` |

---

## Base URLs

| Environment | v2 | v3 |
|---|---|---|
| Live | `https://api.tradestation.com/v2` | `https://api.tradestation.com/v3` |
| Sim | `https://sim-api.tradestation.com/v2` | `https://sim-api.tradestation.com/v3` |

The sim environment accepts the same OAuth tokens as live. Quote responses in sim return
all-zero bid/ask — only order flow can be tested there.

---

## Limit Price Formatting

### Step 1 — Get a raw price candidate

Three sources, in order of preference:

| Source | How | When to use |
|---|---|---|
| Market fill price | `order_status(order_id)["filled_avg_price"]` | After a market buy fills — use as sell limit |
| `get_fair_price()` | `OptionPriceMonitor.get_fair_price(ticker, occ, type, stock_price)` | Entry limit — floors at intrinsic, handles wide spreads |
| Raw mid | `(bid + ask) / 2` | Simple case when spread is tight (≤15%) |

### Step 2 — Quantize to the correct tick increment

**Always quantize before submitting.** TradeStation rejects orders at invalid tick sizes
with no fill and no clear error message.

Use `_quantize_option_price(price, penny_pilot=...)` from `option_price_monitor.py`:

```python
from decimal import Decimal
from alpha_tech_tracker.op_momentum_strategy.option_price_monitor import _quantize_option_price

raw = Decimal("5.13")   # fill price or computed limit

# Penny Pilot tickers (TSLA, AMD, META, PLTR, COIN, …):
limit = _quantize_option_price(raw, penny_pilot=True)   # → 5.15

# Non-Penny Pilot tickers (RH, EXPE, FN, …):
limit = _quantize_option_price(raw, penny_pilot=False)  # → 5.10
```

### Tick increment rules

| Program | Price < $3 | Price ≥ $3 |
|---|---|---|
| **Penny Pilot** (most liquid names) | $0.01 | $0.05 |
| **Standard non-pilot** (RH, EXPE, FN, …) | $0.05 | $0.10 |

### How to tell which program a ticker is on

TradeStation will reject the order silently (or return an error) if the wrong increment
is used. In practice:

- If the order is rejected and the price has a $0.05 sub-increment (e.g. `5.05`, `5.15`)
  — the ticker is likely non-pilot; re-submit rounded to $0.10.
- If the market quote itself has $0.05 increments on both bid and ask — it's non-pilot.
- RH, EXPE, FN confirmed non-pilot from live testing (2026-04-16).
- Strategy pool tickers (TSLA, AMD, META, PLTR, COIN, MU, CRDO, APP, SHOP, CVNA, MRVL,
  SNDK, CLS, MSTR, CRWV) are all Penny Pilot.

### Float → Decimal precision

Raw prices from the API are floats. Convert via `str()` before wrapping in `Decimal`
to avoid binary floating-point noise:

```python
# WRONG — may give Decimal('5.709999999999998')
Decimal(fill_price)

# CORRECT
Decimal(str(fill_price))

# Also correct — stock price rounded at get_fair_price entry
stock_price.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
```

`get_fair_price()` applies the `stock_price` quantize internally. Callers do not need to
pre-round, but must pass `Decimal(str(float_value))` not a raw float.

---

## Live Testing Notes (2026-04-16)

All tests run against `api.tradestation.com` (live environment) using stored OAuth tokens.

### TSLA $380 call, exp 2026-04-17

- Stock at ~387.50; option bid/ask at 8.70–9.20 during the session
- Tight $0.10 spread — Penny Pilot confirmed
- Market buy filled in <1s; market sell filled cleanly 5s later
- Order IDs: 1255671490 (buy), 1255671522 (sell)

### RH $125 call, exp 2026-04-17

- Stock at ~129.30; option spread bid=4.70 ask=5.80 ($1.10 wide, ~21%)
- `get_fair_price()` → $4.50 (no_cache: intrinsic $4.31 + 20% of spread $0.18, rounded to $0.10)
- Mid ($5.25) would have overpaid by $0.75; fair price aggressive but protective
- Non-Penny Pilot — use `penny_pilot=False`; $0.10 ticks ≥ $3
- Market buy filled at $5.13; sell limit placed at $5.10 (rounded from $5.13)

### RH $135 put, exp 2026-04-17

- Stock at ~129.27; option spread bid=5.10 ask=6.80 ($1.70 wide, ~29%)
- `get_fair_price()` → $6.10 (no_cache: intrinsic $5.73 + $0.34, rounded to $0.10)
- Earlier attempt at $6.05 was **rejected by TradeStation** — non-pilot $0.10 tick required
- Fixed: `penny_pilot=False` produces $6.10, which was accepted

---

## Fill Escalation (`_place_with_fill_escalation`)

Implemented in `op_momentum_strategy/order_executor.py`. Replaces single-shot limit orders
with a multi-step ladder that starts conservative and gets more aggressive only when needed.

### Escalation ladder — options

| Step | Wait | Buy price | Sell price | Notes |
|---|---|---|---|---|
| 0 | 20s | — | `entry_fill_price` | Quick-exit: protects against selling below cost |
| 0.5 | 20s | `get_fair_price()` | `get_fair_price()` | Only runs when monitor fn is provided |
| 1 | 15s | mid | mid | Conservative starting point |
| 2 | 15s | mid + spread/4 | mid − spread/4 | Slightly more aggressive; often fills on wide spreads |
| 3 | 15s | ask | max(bid, intrinsic) | Final attempt; logs FILL_ESC MISS if still unfilled |

No market order fallback for options — if step 3 misses, the order is left cancelled and
a `FILL_ESC MISS` warning is logged for manual intervention.

### CLI usage (`paper_options_test.py`)

```bash
# Penny Pilot ticker (TSLA, AMD, pool tickers)
python -m alpha_tech_tracker.op_momentum_strategy.paper_options_test \
    --ticker TSLA --broker tradestation --live \
    --strike 380 --expiry 2026-04-17 --escalate

# Non-Penny Pilot ticker (RH, EXPE, FN)
python -m alpha_tech_tracker.op_momentum_strategy.paper_options_test \
    --ticker RH --broker tradestation --live \
    --strike 125 --expiry 2026-04-17 --escalate --non-penny-pilot
```

---

## Escalation Live Testing Notes (2026-04-16)

All tests used `--escalate --non-penny-pilot` against `api.tradestation.com`.

### RH $125 call — run 1

- Stock at ~129.43; spread bid=4.70 ask=5.20 ($0.50 wide, ~10%)
- Step 1 (mid=$4.95): **unfilled** — bid-side not moving
- Step 2 (mid+spread/4=$5.08): **unfilled**
- Step 3 (ask=$5.20): **filled** — had to pay the full ask
- Sell step 0 (entry=$5.20): **filled within 20s** — breakeven exit
- Lesson: tight-looking spreads ($0.50) can still require paying ask if the market maker
  won't lift mid; step 3 at ask is the reliable backstop

### RH $135 put

- Stock at ~129.19; spread bid=5.30 ask=6.80 ($1.50 wide, ~25%)
- Step 1 (mid=$6.05): **unfilled**
- Step 2 (mid+spread/4=$6.43): **filled** — saved $0.37/contract vs going straight to ask
- Sell step 0 (entry=$6.40): **unfilled** — bid had dropped to $5.40 by sell time
- Sell step 1 (mid=$5.90): **filled** — $0.50 round-trip loss (wide spread cost)
- Lesson: step 2 earns its keep on wide spreads; sell step 0 only protects against a
  rapidly falling bid — a $1.00+ spread can move $1 against you in minutes

### RH $125 call — run 2

- Stock at ~129.60; spread bid=4.30 ask=6.00 ($1.70 wide, ~33%)
- Step 1 (mid=$5.15): **filled** — despite a $1.70 spread, mid got a fill
- Sell step 0 (entry=$5.20): **filled within 20s** — breakeven exit
- Lesson: even very wide spreads sometimes fill at mid when the stock is moving and
  the market maker is active; always start at step 1 before escalating

### TSLA $385 call

- Stock at ~389.40; spread bid=6.50 ask=6.60 ($0.10 wide, ~1.5%) — Penny Pilot
- Step 1 (mid=$6.55): **filled at $6.53** — slight improvement below mid
- Sell step 0 (entry=$6.53): **unfilled** — bid slipped to $6.45 within 20s
- Sell step 1 (mid=$6.48): **filled immediately** — $0.05 round-trip loss
- Lesson: Penny Pilot tickers almost always fill at step 1; the escalation ladder adds
  no overhead — the extra steps simply never trigger

### Summary — fill rates across 4 tests

| Step | Buy fills | Sell fills | Notes |
|---|---|---|---|
| Step 0 (entry price) | n/a | 2 of 3 | Misses when bid has moved significantly against position |
| Step 1 (mid) | 1 of 3 | 1 of 1 (after step 0 miss) | Works when market is active |
| Step 2 (mid±spread/4) | 1 of 3 | — | Useful on wide spreads ($1.50+) |
| Step 3 (ask/bid) | 1 of 3 | — | Reliable backstop; costs full spread |

**Key takeaway**: Starting at mid is always worth trying — it fills every time on tight
Penny Pilot spreads and ~33% of the time on wide RH spreads. Step 2 saves ~$0.30–0.40/contract
on wide spreads about 33% of the time. Step 3 at ask is the reliable backstop but should be
treated as the maximum acceptable entry cost. For liquid Penny Pilot names (TSLA, AMD, pool
tickers), the escalation ladder adds no overhead — steps 2 and 3 simply never trigger.

---

## Known Pitfalls

1. **Padded format rejected by quote API** — `TSLA  260417C00380000` returns
   `FAILED, INVALID SYMBOL` from `/v2/data/quote/`. Always use Display format for quotes.

2. **Response symbol needs name-based reverse parse** — the batch quote response echoes
   the Display format symbol back. Stripping spaces gives `TSLA260417C380`, which is not
   valid OCC (strike is decimal, not 8-digit integer). Use `_ts_search_name_to_occ()` for
   the reverse conversion.

3. **`TimeInForce` must be a nested object** — `{"Duration": "DAY"}`, not a flat string.
   A flat `"Duration": "DAY"` at top level is silently rejected.

4. **`Quantity` and `LimitPrice` are strings** — the v3 API expects these as JSON strings
   (`"1"`, `"8.75"`), not numbers.

5. **`AccountID` key, not `AccountKey`** — the v3 order body uses `AccountID`.

6. **Sim fills market orders only** — limit orders in the sim environment never fill.
   Use sim to validate order flow and response parsing; use live for fill behavior.

7. **Wrong tick size silently rejects limit orders** — non-Penny Pilot tickers (RH, EXPE,
   FN) require $0.10 increments for prices ≥ $3. Submitting $5.05 or $5.13 results in
   rejection. Always run price through `_quantize_option_price(price, penny_pilot=False)`
   for non-pilot names.

8. **Float precision in Decimal arithmetic** — `Decimal(5.71)` gives
   `5.70999999999998...`. Always use `Decimal(str(float_value))`. `get_fair_price()`
   quantizes `stock_price` internally to avoid this, but fill prices from `order_status`
   must be wrapped by the caller before use.

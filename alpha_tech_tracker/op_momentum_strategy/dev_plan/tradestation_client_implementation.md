# TradeStation Client Implementation

**Status:** Implemented and live-tested (2026-04-16)

`TradeStationAPIClient` is a concrete `ExecutionClient` that routes stock and option
orders through TradeStation. It follows the same design pattern as `AlpacaAPIClient` —
normalized return dicts, typed exceptions, no preview/confirm step.

**Files:**
```
alpha_tech_tracker/trade_api/tradestation/
├── __init__.py
├── client.py                         # TradeStationAPIClient
└── tradestation_api_response.py      # Fixture response dicts for unit tests

alpha_tech_tracker/op_momentum_strategy/
└── tradestation_auth.py              # Auth helper CLI
```

---

## API Version Notes

The TradeStation REST API has two active versions. The client uses **both**:

| Version | Used for |
|---|---|
| `v2` (`/v2/...`) | Stock/option quotes, options chain search |
| `v3` (`/v3/...`) | Everything else: accounts, orders, cancel, streaming |

**Base URLs:**
- Live: `https://api.tradestation.com`
- Simulation: `https://sim-api.tradestation.com`

The client stores both:
```python
self._base_url    = _BASE_URLS[environment] + "/v2"
self._v3_base_url = _BASE_URLS[environment] + "/v3"
```

---

## Correct Endpoint Reference

| Method | HTTP | Path |
|---|---|---|
| List accounts | GET | `/v3/brokerage/accounts` |
| Account balances | GET | `/v3/brokerage/accounts/{accountId}/balances` |
| Stock/option quotes | GET | `/v2/data/quote/{symbols}` |
| Options chain search | GET | `/v2/data/symbols/search/{criteria}` |
| Option expirations | GET | `/v3/marketdata/options/expirations/{underlying}` |
| Place order | POST | `/v3/orderexecution/orders` |
| Account orders (status) | GET | `/v3/brokerage/accounts/{accountId}/orders` |
| Cancel order | DELETE | `/v3/orderexecution/orders/{orderId}` |
| Live bar stream | GET (chunked) | `/v3/marketdata/stream/barcharts/{symbol}` |
| Historical bars | GET | `/v3/marketdata/barcharts/{symbol}` |

> **Note:** The original plan used v2 for all endpoints. All order/account paths on v2
> return 400/403. Only quotes and symbol search remain on v2.

---

## Authentication

OAuth 2.0 Authorization Code flow via `requests_oauthlib.OAuth2Session`.

**Scopes:** `openid offline_access profile MarketData ReadAccount Trade OptionSpreads`

**Token lifetimes:**
- Access token: 20 minutes (auto-refreshed transparently by `OAuth2Session`)
- Refresh token: indefinite — re-auth only needed if manually revoked

**One-time setup:**
```bash
python -m alpha_tech_tracker.op_momentum_strategy.tradestation_auth
```

**Verify stored session:**
```bash
python -m alpha_tech_tracker.op_momentum_strategy.tradestation_auth --verify
```

### `config.json` structure

```json
{
  "execution_broker": "tradestation",
  "tradestation_credentials": {
    "client_id": "YOUR_CLIENT_ID",
    "client_secret": "YOUR_CLIENT_SECRET"
  },
  "tradestation": {
    "account_key": "YOUR_ACCOUNT_ID",
    "environment": "live"
  },
  "tradestation_session": {
    "access_token": "...",
    "refresh_token": "...",
    "token_type": "Bearer",
    "expires_at": 1234567890.0
  }
}
```

`account_key` is the numeric `AccountID` returned by the v3 accounts endpoint (e.g.
`"12041669"`). This is the account's ID, not the display name.

---

## Option Symbol Formats

TradeStation uses **three distinct symbol formats** depending on context:

### 1. OCC format (internal representation)
Used throughout the trade engine and position tracking.
```
TSLA260417C00392500
```
Pattern: `{ticker}{YYMMDD}{C|P}{strike * 1000, zero-padded to 8 digits}`

### 2. Padded quote format (v2 quote endpoint)
Used for `get_option_quote_by_occ` and `get_option_quotes_by_occ_batch`.
```
TSLA  260417C00392500   (ticker left-padded to 6 chars)
```

### 3. Display/order format (v2 search results + v3 order execution)
Used for `get_options_contracts` name field AND `place_option_order` symbol body.
```
TSLA 260417C392.5   (space after ticker, decimal strike)
```

### Conversion helpers in `client.py`

| Function | Input | Output | Used by |
|---|---|---|---|
| `_occ_to_ts(occ)` | OCC | Padded quote format | `get_option_quote_by_occ`, `get_option_quotes_by_occ_batch` |
| `_ts_to_occ(ts)` | Padded quote format | OCC | Quote response parsing |
| `_occ_to_ts_order_symbol(occ)` | OCC | Display/order format | `place_option_order` |
| `_ts_search_name_to_occ(name)` | Display/order format | OCC | `get_options_contracts`, `_normalize_order` |

---

## Account Fields (v3)

v3 balances response uses different field names than v2:

| v2 field (original plan) | v3 field (actual) | Maps to |
|---|---|---|
| `BODNetCash` | `CashBalance` | `cash` |
| `RealTimeBuyingPower` | `BuyingPower` | `buying_power` |
| `RealTimeEquity` | `Equity` | `equity`, `portfolio_value` |

---

## Order Placement (v3)

### Request body

v3 `/orderexecution/orders` uses `AccountID` and nested `TimeInForce`:

```json
{
  "AccountID": "12041669",
  "AssetType": "OP",
  "Symbol": "TSLA 260417C392.5",
  "Quantity": "1",
  "OrderType": "Limit",
  "LimitPrice": "1.00",
  "TimeInForce": {"Duration": "DAY"},
  "TradeAction": "BUYTOOPEN",
  "Route": "Intelligent"
}
```

Key differences from v2 (original plan):
- `AccountKey` → `AccountID`
- `Duration: "DAY"` (flat) → `TimeInForce: {"Duration": "DAY"}` (nested)
- Symbol must be display/order format (`"TSLA 260417C392.5"`), not padded OCC

### Response shape

v3 wraps the result in an `Orders` array:
```json
{
  "Orders": [
    {"OrderID": "1255310562", "Error": "OK", "Message": "..."}
  ]
}
```

The helper `_extract_v3_order(data)` unwraps `data["Orders"][0]`.

For after-hours or rejected orders, `Error` will be `"FAILED"` but an `OrderID` is still
returned. The order appears in the account order list with `Status: "REJ"`.

### `TradeAction` mapping

| `order_action` param | `TradeAction` in body |
|---|---|
| `BUY_OPEN` | `BUYTOOPEN` |
| `BUY_CLOSE` | `BUYTOCLOSE` |
| `SELL_OPEN` | `SELLTOOPEN` |
| `SELL_CLOSE` | `SELLTOCLOSE` |

---

## Order Status (v3)

`GET /v3/brokerage/accounts/{accountId}/orders` returns all orders for the session.
The `_normalize_order` method reads from the nested `Legs` array:

```json
{
  "OrderID": "1255310562",
  "Status": "REJ",
  "LimitPrice": "1",
  "FilledPrice": "0",
  "Duration": "DAY",
  "OpenedDateTime": "2026-04-16T07:07:41Z",
  "Legs": [
    {
      "Symbol": "TSLA 260417C392.5",
      "QuantityOrdered": "1",
      "ExecQuantity": "0",
      "BuyOrSell": "Buy"
    }
  ]
}
```

| Normalized field | Source |
|---|---|
| `symbol` | `Legs[0].Symbol` → converted to OCC via `_ts_search_name_to_occ` |
| `quantity` | `Legs[0].QuantityOrdered` |
| `filled_qty` | `Legs[0].ExecQuantity` |
| `side` | `Legs[0].BuyOrSell` |
| `limit_price` | `LimitPrice` (top-level) |
| `filled_avg_price` | `FilledPrice` (top-level) |
| `submitted_at` | `OpenedDateTime` |

### Status code map

```python
_TS_STATUS_MAP = {
    "OPN": "open",   "ACK": "open",  "DON": "open",
    "FPR": "open",   "UCN": "open",  "LAT": "open",
    "OUT": "open",   "PLA": "open",
    "FLL": "filled", "FLP": "filled",
    "CAN": "canceled", "REJ": "canceled", "TSC": "canceled",
    "BRO": "canceled", "EXP": "expired",
}
```

`REJ` was added during live testing — orders rejected after hours have this status.

---

## Cancel Order (v3)

`DELETE /v3/orderexecution/orders/{orderId}`

If the order is already closed (rejected, filled, or cancelled), the API returns HTTP 400
`"Not an open order."`. The client handles this gracefully — logs at INFO level and
returns `{"status": "canceled"}` instead of raising.

---

## Options Chain Search (v2)

`GET /v2/data/symbols/search/{criteria}`

Criteria format: `R={ticker}&C=StockOption&OT={Call|Put|Both}&Stk={numStrikes}`

For a specific expiry: `&Edl={MM-DD-YYYY}&Edh={MM-DD-YYYY}`

**Known response quirks:**

| Field | Format | Parse method |
|---|---|---|
| `Name` | `"TSLA 260417C342.5"` (display format) | `_ts_search_name_to_occ()` |
| `ExpirationDate` | `"/Date(1776398400000)/"` (epoch ms) | `_parse_ts_date()` |
| `OptionType` | `"Call"` or `"Put"` (not `"Calls"`/`"Puts"`) | Check for both spellings |

The original plan assumed `OptionType == "Calls"` — the actual API returns `"Call"`. This
caused all contracts to be silently filtered out. Fixed to accept `"Call"` or `"Calls"`.

---

## Bugs Found and Fixed During Live Testing (2026-04-16)

| # | Method | Bug | Root cause | Fix |
|---|---|---|---|---|
| 1 | `_get_account_key` | HTTP 403 | v2 path `/users/{user_id}/accounts` requires different auth scope | Switch to v3 `/brokerage/accounts`; use `AccountID` field (not `Key`) |
| 2 | `get_accounts` | Wrong values returned | v2 field names (`BODNetCash`, `RealTimeBuyingPower`) don't exist in v3 | Use v3 fields: `CashBalance`, `BuyingPower`, `Equity` |
| 3 | `get_options_contracts` | Always returned empty list | `OptionType == "Calls"` never matched; API returns `"Call"` | Accept `"Call"` or `"Calls"` |
| 4 | `get_options_contracts` | Date parsing crash | `ExpirationDate` is `/Date(epoch_ms)/` not `YYYY-MM-DD` | New `_parse_ts_date()` helper parses epoch-ms JSON dates |
| 5 | `get_options_contracts` | Wrong OCC symbols | `_ts_to_occ()` on display name `"TSLA 260417C342.5"` produces garbage | New `_ts_search_name_to_occ()` parses display name and re-encodes strike to OCC 8-digit format |
| 6 | `order_status` | HTTP 400 unauthorized | v2 path `/accounts/{key}/orders` uses wrong account key format | Switch to v3 `/brokerage/accounts/{accountId}/orders` |
| 7 | `_normalize_order` | Wrong symbol/qty/filled fields | v3 order records store symbol and quantities inside `Legs[0]`, not top-level | Read `Legs[0].Symbol`, `Legs[0].QuantityOrdered`, `Legs[0].ExecQuantity` |
| 8 | `place_option_order` | HTTP 400 "Invalid symbol" | v3 order endpoint requires display format `"TSLA 260417C392.5"`, not padded OCC | New `_occ_to_ts_order_symbol()` converts OCC → display format |
| 9 | `place_option_order` / `place_stock_order` | HTTP 400 "Missing duration" | v3 uses `TimeInForce: {Duration: "DAY"}` not flat `Duration: "DAY"` | Nest duration under `TimeInForce` object |
| 10 | `place_option_order` / `place_stock_order` | Empty `order_id` returned | v3 response is `{"Orders": [{...}]}`, not a flat dict | New `_extract_v3_order()` unwraps `data["Orders"][0]` |
| 11 | `cancel_order` | v2 path | v2 `/orders/{id}` returns 400 | Switch to v3 `/orderexecution/orders/{id}` |
| 12 | `cancel_order` | Raises on already-closed orders | API returns 400 `"Not an open order."` for REJ/CAN orders | Catch this specific 400 and return `canceled` gracefully |

---

## Testing

All tests in `tests/trade_api/tradestation/test_client.py`.

```python
def _make_client():
    client = TradeStationAPIClient(
        client_id="test_client_id",
        client_secret="test_client_secret",
        selected_account_key="123456",
        environment="sim",
    )
    client._session = MagicMock()
    client._user_id = "testuser"
    return client

def _mock_response(data, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = data
    return resp
```

Key mock targets:
- `client._session.get` for all read endpoints
- `client._session.post` for order placement
- `client._session.delete` for cancel

The fixture file `tradestation_api_response.py` contains realistic v3 response dicts for
each endpoint. Update these if the API shape changes.

### Test classes to cover

| Class | Behaviors |
|---|---|
| `TestSymbolConversions` | All four conversion helpers; roundtrip OCC→display→OCC; non-integer strikes; 3/4/5-char tickers |
| `TestGetAccounts` | v3 field names; account key lazy-resolution; first active account used |
| `TestGetStockQuote` | Single/multi; nested shape matches `_stock_bid_ask()` format |
| `TestGetOptionQuoteByOcc` | OCC→padded conversion before URL; bid/ask/mid |
| `TestGetOptionQuotesByOccBatch` | Single HTTP call; keyed by OCC; missing symbols logged |
| `TestGetOptionsContracts` | Criteria format; `_parse_ts_date()`; `_ts_search_name_to_occ()`; `OptionType` filter |
| `TestPlaceOptionOrder` | v3 path; display symbol format; nested `TimeInForce`; `_extract_v3_order` unwrapping |
| `TestPlaceStockOrder` | Same v3 path; EQ asset type; BUY/SELL mapping |
| `TestOrderStatus` | v3 path; `Legs[0]` field extraction; all status codes |
| `TestCancelOrder` | v3 path; graceful "not an open order" 400 handling |

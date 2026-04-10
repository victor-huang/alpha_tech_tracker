# TradeStation Client Implementation Plan

**Goal:** Add `TradeStationAPIClient` as a third concrete `ExecutionClient` so the live
trading engine can route stock and option orders through TradeStation. Follows the same
pattern as `AlpacaAPIClient` (the newer design) — not the ETrade client. No changes to
strategy logic.

**Design reference:** `alpha_tech_tracker/trade_api/alpaca_client/client.py`
- Delegate HTTP calls to a thin internal session object (no manual JSON parsing in methods)
- Return rich normalized dicts: include `symbol`, `quantity`, `side`, `type`, `submitted_at`, `raw_response`
- Raise typed `APIError` / `APIInvalidArgumentError` exceptions (same class names as Alpaca client)
- No preview/confirm step before placing orders

API version used: **v2** (`https://api.tradestation.com/v2`)
Auth: OAuth 2.0 Authorization Code flow via `requests_oauthlib.OAuth2Session`
No new Python packages required — `requests_oauthlib` is already installed.

---

## API Reference Summary

| Purpose | Method | Path |
|---|---|---|
| List accounts | GET | `/v2/users/{user_id}/accounts` |
| Account balances | GET | `/v2/accounts/{account_key}/balances` |
| Stock/option quotes | GET | `/v2/data/quote/{symbols}` |
| Options chain / search | GET | `/v2/data/symbols/search/{criteria}` |
| Place order | POST | `/v2/orders` |
| Account orders (status) | GET | `/v2/accounts/{account_key}/orders` |
| Cancel order | DELETE | `/v2/orders/{order_id}` |

Base URLs:
- Live: `https://api.tradestation.com`
- Simulation (paper): `https://sim-api.tradestation.com`

---

## Files to Create / Modify

### New files

```
alpha_tech_tracker/trade_api/tradestation/
├── __init__.py
├── client.py                         # TradeStationAPIClient
└── tradestation_api_response.py      # Fixture response dicts for unit tests

alpha_tech_tracker/op_momentum_strategy/
└── tradestation_auth.py              # Auth helper (mirrors etrade_auth.py)

tests/trade_api/tradestation/
├── __init__.py
└── test_client.py
```

### Modified files

- `alpha_tech_tracker/op_momentum_strategy/config.py` — new constants, `_load_config()` additions, `build_execution_client()` extension
- `alpha_tech_tracker/op_momentum_strategy/config.json` — placeholder credentials section (already gitignored)

---

## 1. Authentication

### OAuth 2.0 Flow

TradeStation uses Authorization Code flow. Unlike ETrade's OOB/console-paste approach,
the callback is captured by a temporary local HTTP server on `localhost:8080`.

**Scopes required:** `openid offline_access MarketData ReadAccount Trade OptionSpreads`

**Token lifetimes:**
- Access token: **20 minutes** (auto-refreshed transparently by `OAuth2Session`)
- Refresh token: **indefinite** — re-auth only needed if refresh token is manually revoked

**Key URLs:**
- Authorization redirect: `https://signin.tradestation.com/authorize`
- Token exchange + refresh: `https://signin.tradestation.com/oauth/token`

### Token Storage in config.json

```json
{
  "execution_broker": "tradestation",
  "tradestation_credentials": {
    "client_id": "YOUR_CLIENT_ID",
    "client_secret": "YOUR_CLIENT_SECRET",
    "redirect_uri": "http://localhost:8080"
  },
  "tradestation": {
    "account_key": "YOUR_ACCOUNT_KEY",
    "environment": "live"
  },
  "tradestation_session": {
    "access_token": "...",
    "refresh_token": "...",
    "token_type": "Bearer",
    "expires_at": 1712345678.0,
    "scope": "openid offline_access MarketData ReadAccount Trade OptionSpreads"
  }
}
```

`account_key` is the numeric `Key` field returned by the accounts list endpoint (not the
account name/number displayed in the UI). It is used as the path param for balances and
orders endpoints, and as `AccountKey` in order submission.

---

## 2. Option Symbol Format

TradeStation uses OCC/OSI format but **space-pads the ticker to 6 characters** before
the date portion:

```
TSLA  250420C00240000   (4-char ticker → 2 trailing spaces)
SPY   250321C00520000   (3-char ticker → 3 trailing spaces)
AAPL  250117C00200000   (4-char ticker → 2 trailing spaces)
```

**Conversion rules:**
- **Inbound** (API response → internal): strip all spaces → standard OCC `TSLA250420C00240000`
- **Outbound** (internal OCC → API request): pad ticker with spaces to 6 chars, then append `YYMMDD{C|P}{8-digit strike}`

Helper functions in `client.py`:
```python
def _occ_to_ts(occ_symbol: str) -> str:
    """TSLA250420C00240000 → 'TSLA  250420C00240000'"""

def _ts_to_occ(ts_symbol: str) -> str:
    """'TSLA  250420C00240000' → 'TSLA250420C00240000'"""
```

---

## 3. `TradeStationAPIClient` — Method Specification

### Constructor

```python
class TradeStationAPIClient(ExecutionClient):
    def __init__(
        self,
        client_id=None,
        client_secret=None,
        redirect_uri="http://localhost:8080",
        selected_account_key=None,
        environment="live",   # "live" | "sim"
    ):
```

- `client_id` falls back to `os.environ.get("TS_CLIENT_ID")`
- `client_secret` falls back to `os.environ.get("TS_CLIENT_SECRET")`
- `environment` drives base URL: `"live"` → `api.tradestation.com`, `"sim"` → `sim-api.tradestation.com`
- `self._session = None` — set by `restore_session()` or `authorize_session()`
- `self._user_id = None` — captured from token response; needed for accounts endpoint
- `self._account_key = selected_account_key` — lazily resolved if None

### Status Normalization Map

```python
_TS_STATUS_MAP = {
    "OPN": "open",
    "ACK": "open",
    "DON": "open",
    "FPR": "open",           # partially filled, still open
    "UCN": "open",           # cancel pending (treat as still open)
    "LAT": "open",
    "OUT": "open",
    "FLL": "filled",
    "FLP": "filled",         # partial fill then remainder canceled
    "CAN": "canceled",
    "REJ": "canceled",
    "TSC": "canceled",
    "BRO": "canceled",
    "EXP": "expired",
}
```

### `authorize_session(self) -> dict`

1. Raise `RuntimeError` if `client_id` or `client_secret` is missing (same guard as ETrade)
2. Build authorization URL with all required scopes
3. Start `http.server.HTTPServer` on `localhost:8080` to capture the `?code=` callback
4. Open browser via `webbrowser.open()`
5. Wait for the callback (single request); extract `code` from query string
6. Exchange code for tokens via POST to token URL
7. Capture `userid` from token response; store as `self._user_id`
8. Build `OAuth2Session` with auto-refresh configured (see `restore_session`)
9. Return full token dict so caller can persist it

### `restore_session(self, token: dict)`

```python
from requests_oauthlib import OAuth2Session

self._session = OAuth2Session(
    client_id=self._client_id,
    token=token,
    auto_refresh_url="https://signin.tradestation.com/oauth/token",
    auto_refresh_kwargs={
        "client_id": self._client_id,
        "client_secret": self._client_secret,
    },
    token_updater=self._on_token_refresh,
)
```

`_on_token_refresh(new_token)` persists the refreshed token by calling
`_save_tradestation_session_tokens(new_token)` from `config.py`. This ensures the
updated access token survives process restarts within the 20-minute window.

### `verify_session(self) -> bool`

- `GET /v2/users/{user_id}/accounts` — if 200, return True; otherwise False
- Falls back to `GET /v2/data/quote/MSFT` if `_user_id` is not yet populated
- Returns False on any exception

### `get_accounts(self) -> dict`

1. `GET /v2/accounts/{account_key}/balances`
2. Parse response fields:
   - `buying_power` ← `RealTimeBuyingPower`
   - `cash` ← `BODNetCash`
   - `portfolio_value` ← `RealTimeEquity`
3. Return normalized dict matching Alpaca client shape:
   ```python
   {
       "account_id": str,
       "cash": float,
       "buying_power": float,
       "portfolio_value": float,
       "equity": float,          # same as portfolio_value for TS
       "raw_response": dict,     # full API response
   }
   ```

If `_account_key` is None, first call `GET /v2/users/{user_id}/accounts`, use the first
active account's `Key`, and cache it.

### `get_stock_quote(self, symbols) -> dict`

- `GET /v2/data/quote/{symbols}` (comma-separated if multiple)
- Normalize response to the same nested shape the rest of the system expects
  (matches `_stock_bid_ask()` in `models.py`):
  ```python
  {"QuoteResponse": {"QuoteData": [{"All": {"bid": float, "ask": float, ...}}]}}
  ```
- Response fields: `Bid`, `Ask`, `Last`, `Volume`

### `get_option_quote_by_occ(self, occ_symbol: str) -> dict`

- Convert OCC → TS padded symbol via `_occ_to_ts()`
- `GET /v2/data/quote/{ts_symbol}`
- Return `{"bid": float, "ask": float, "mid": (bid+ask)/2}`

### `get_option_quotes_by_occ_batch(self, occ_symbols: list) -> dict`

- Convert all OCC symbols to TS format; join with commas
- Single `GET /v2/data/quote/{all_symbols}` — genuine batch, no loop
- Parse `Quotes` array; key result by original OCC symbol (convert back via `_ts_to_occ()`)
- Omit any symbols missing from the response (illiquid/expired); log a warning

### `get_options_contracts(self, ...) -> list`

Uses `GET /v2/data/symbols/search/{criteria}` with TradeStation's key=value criteria format.

**Criteria encoding:**
```
R={ticker}&C=StockOption&OT={Call|Put|Both}&Stk=20
```

For specific expiry date: add `Edl={MM-DD-YYYY}&Edh={MM-DD-YYYY}` with same date as both bounds.
For date range: add `Edl={start}&Edh={end}`.
For strike range: add `Spl={low}&Sph={high}`.

**Response normalization per contract:**
```python
{
    "symbol": _ts_to_occ(item["Name"]),   # strip spaces
    "expiration_date": "YYYY-MM-DD",       # parse from item["ExpirationDate"]
    "strike_price": float(item["StrikePrice"]),
    "option_type": "call" if item["OptionType"] == "Calls" else "put",
    "contract_size": 100,
}
```

Apply `strike_price_gte` / `strike_price_lte` filtering post-response if provided.

### `place_option_order(self, ...) -> dict`

- `POST /v2/orders` — **no preview/confirm step required**
- Request body:
  ```json
  {
    "AccountKey": "123456",
    "AssetType": "OP",
    "Symbol": "TSLA  250420C00240000",
    "Quantity": "1",
    "OrderType": "Limit",
    "LimitPrice": "10.50",
    "Duration": "DAY",
    "TradeAction": "BUYTOOPEN",
    "Route": "Intelligent"
  }
  ```
- `TradeAction` mapping from `order_action` parameter:
  - `"BUY_OPEN"` → `"BUYTOOPEN"`
  - `"BUY_CLOSE"` → `"BUYTOCLOSE"`
  - `"SELL_OPEN"` → `"SELLTOOPEN"`
  - `"SELL_CLOSE"` → `"SELLTOCLOSE"`
- `price_type` mapping: `"LIMIT"` → `"Limit"`, `"MARKET"` → `"Market"`
- `SMART_MARKET`: fetch mid via `get_option_quote_by_occ()`, compute price at 90% of spread toward bid, use as `"Limit"` order
- Raise `ValueError` if neither `_option_symbol_override` nor a valid OCC symbol is provided
- Return normalized dict matching Alpaca client shape:
  ```python
  {
      "order_id": str,
      "symbol": str,
      "quantity": float,
      "filled_qty": float,
      "side": str,              # "BUY" or "SELL"
      "type": str,              # "Limit" or "Market"
      "status": str,            # normalized via _TS_STATUS_MAP
      "limit_price": float,
      "filled_avg_price": float,
      "submitted_at": str,      # TimeStamp from response
      "raw_response": dict,
  }
  ```

### `place_stock_order(self, ...) -> dict`

- Same `POST /v2/orders` endpoint
- `AssetType`: `"EQ"`, `Symbol`: plain ticker
- `TradeAction`: `"BUY"` or `"SELL"` based on `side` parameter
- `OrderType`: `"Limit"` or `"Market"`
- Raise `APIInvalidArgumentError` if `order_type == "LIMIT"` and `limit_price` is None (same exception class as Alpaca client)
- Return same normalized dict shape as `place_option_order`

### `order_status(self, order_id: str) -> dict`

- `GET /v2/accounts/{account_key}/orders` filtered by scanning for matching `OrderID`
- Response fields per order: `OrderID`, `Status`, `ExecuteQuantity`, `FilledPrice`, `LimitPrice`, `TimeStamp`
- Map `Status` through `_TS_STATUS_MAP`
- Return same normalized dict shape as `place_option_order` / `place_stock_order`

Note: the orders endpoint returns all orders for the day, not a single order by ID. Filter
by `OrderID` field. If not found, return status `"open"` with zeroed numeric fields.

### `cancel_order(self, order_id: str) -> dict`

- `DELETE /v2/orders/{order_id}` — no request body
- Return normalized dict matching Alpaca client shape:
  ```python
  {"order_id": order_id, "status": "canceled", "message": "Cancel request submitted"}
  ```
- Raise `APIError` on HTTP 4xx (e.g., already filled)

---

## 4. `tradestation_auth.py`

Mirrors `etrade_auth.py`. CLI flags: `--verify`, `--sim`, `--account-key`.

```
Usage:
    # Authorize and store tokens (opens browser, captured automatically)
    python -m alpha_tech_tracker.op_momentum_strategy.tradestation_auth

    # Check whether stored tokens are still valid
    python -m alpha_tech_tracker.op_momentum_strategy.tradestation_auth --verify

    # Use simulation environment
    python -m alpha_tech_tracker.op_momentum_strategy.tradestation_auth --sim
```

**`_authorize(account_key, environment)`**
- Instantiate `TradeStationAPIClient`, call `authorize_session()`
- Call `_save_tradestation_session_tokens(token)` from `config.py`
- Print confirmation with config file path

**`_verify(account_key, environment)`**
- Load stored `_TRADESTATION_SESSION_TOKENS` from config
- Call `restore_session(token)`, then `verify_session()`
- Return bool; exit with code 0/1

---

## 5. `config.py` Changes

### New module-level variables

```python
TRADESTATION_ACCOUNT_KEY = None
TRADESTATION_ENVIRONMENT = "live"   # "live" | "sim"
_TRADESTATION_SESSION_TOKENS: dict = {}
```

Update `EXECUTION_BROKER` comment:
```python
EXECUTION_BROKER = "alpaca"   # "alpaca" | "etrade" | "tradestation"
```

### `_load_config()` additions

Add to the `global` declaration: `TRADESTATION_ACCOUNT_KEY, TRADESTATION_ENVIRONMENT`

After the ETrade block:
```python
# TradeStation account config
ts = cfg.get("tradestation", {})
if ts.get("account_key"):
    TRADESTATION_ACCOUNT_KEY = str(ts["account_key"])
if ts.get("environment"):
    TRADESTATION_ENVIRONMENT = ts["environment"]

# TradeStation stored session tokens
_TRADESTATION_SESSION_TOKENS.clear()
_TRADESTATION_SESSION_TOKENS.update(cfg.get("tradestation_session", {}))

# TradeStation credentials → env vars
ts_creds = cfg.get("tradestation_credentials", {})
for cfg_key, env_key in (
    ("client_id", "TS_CLIENT_ID"),
    ("client_secret", "TS_CLIENT_SECRET"),
):
    if ts_creds.get(cfg_key) and not os.environ.get(env_key):
        os.environ[env_key] = ts_creds[cfg_key]
```

### New `_save_tradestation_session_tokens(token: dict, config_file=_CONFIG_FILE)`

Mirrors `_save_etrade_session_tokens()` but writes the full token dict (which includes
`access_token`, `refresh_token`, `expires_at`, `token_type`, `scope`) to
`cfg["tradestation_session"]`.

### `build_execution_client()` extension

Insert before the Alpaca fallback:
```python
if EXECUTION_BROKER == "tradestation":
    from alpha_tech_tracker.trade_api.tradestation.client import TradeStationAPIClient
    client = TradeStationAPIClient(
        selected_account_key=TRADESTATION_ACCOUNT_KEY,
        environment=TRADESTATION_ENVIRONMENT,
    )
    if _TRADESTATION_SESSION_TOKENS.get("access_token"):
        client.restore_session(_TRADESTATION_SESSION_TOKENS)
        if client.verify_session():
            logger.info("TradeStation session restored from stored tokens")
            return client
        logger.warning(
            "Stored TradeStation session expired — run tradestation_auth.py to renew"
        )
    client.authorize_session()
    return client
```

---

## 6. Test Plan

All tests in `tests/trade_api/tradestation/test_client.py` are fully mocked.

### Fixture file: `tradestation_api_response.py`

Realistic response dicts for each endpoint:
- `accounts_response` — array with one account (`Key`, `Name`, `Status`)
- `balances_response` — array with `RealTimeBuyingPower`, `RealTimeEquity`, `BODNetCash`
- `stock_quote_response` — `Quotes` array with `Bid`, `Ask`, `Last`, `Symbol`
- `option_quote_response` — single option symbol quote
- `option_search_response` — array of option symbol objects from symbol search
- `place_order_response` — `{"OrderID": "207887821", "Message": "Order submitted", "OrderStatus": "Ok"}`
- `orders_filled_response` — orders list with `Status: "FLL"`, `ExecuteQuantity`, `FilledPrice`
- `orders_open_response` — `Status: "OPN"`
- `orders_cancelled_response` — `Status: "CAN"`
- `cancel_order_response` — `{"OrderID": "...", "Message": "Cancel request submitted", "OrderStatus": "Ok"}`

### Helper functions

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

Note: unlike the ETrade client which uses `json.loads(response.text)`, the TS client
uses `response.json()` — so mocks use `.json.return_value` not `.text`. This matches
the cleaner Alpaca-style design where the session object handles HTTP and the client
methods only deal with parsed data.

### Test Classes

| Class | Behaviors covered |
|---|---|
| `TestOccTsSymbolConversion` | `_occ_to_ts` and `_ts_to_occ` roundtrip; 3/4/5-char tickers; non-integer strikes |
| `TestGetAccounts` | Buying power/cash/equity extraction; account key lazy-resolution; first-account fallback |
| `TestGetStockQuote` | Single symbol nested shape; multiple comma-joined symbols; `Bid`/`Ask` field mapping |
| `TestGetOptionQuoteByOcc` | OCC→TS conversion before URL; bid/ask/mid returned; non-integer strike |
| `TestGetOptionQuotesByOccBatch` | Genuine batch (single HTTP call); result keyed by OCC; missing symbol omitted |
| `TestGetOptionsContracts` | Criteria format for specific expiry; date range; strike range; `OptionType` filter; normalization of padded symbol; empty result |
| `TestPlaceOptionOrder` | Single POST (no preview); `BUYTOOPEN`/`SELLTOCLOSE`/etc mapping; padded symbol in body; limit price; SMART_MARKET fetches quote first; missing symbol raises |
| `TestPlaceStockOrder` | `BUY`/`SELL` mapping; limit price in body; market order omits limit; missing limit price raises |
| `TestOrderStatus` | `FLL`→`filled`; `OPN`→`open`; `CAN`→`canceled`; filled qty and avg price extracted; order not found returns open |
| `TestCancelOrder` | DELETE method used; normalized return dict; 4xx raises APIError |
| `TestRestoreSession` | `OAuth2Session` created; auto-refresh URL configured; token_updater set |
| `TestVerifySession` | 200→True; 401→False; no session→False; exception→False |
| `TestAuthorizeSession` | Returns token dict; missing credentials raises RuntimeError |

### Integration test stubs (marked, skipped without credentials)

```python
@pytest.mark.tradestation
@pytest.mark.credentials
@pytest.mark.integration
class TestTradeStationIntegration:
    def test_get_accounts_integration(self): ...
    def test_get_stock_quote_integration(self): ...
```

---

## 7. Implementation Order

1. `alpha_tech_tracker/trade_api/tradestation/__init__.py`
2. `alpha_tech_tracker/trade_api/tradestation/client.py`
3. `alpha_tech_tracker/trade_api/tradestation/tradestation_api_response.py`
4. `tests/trade_api/tradestation/__init__.py`
5. `tests/trade_api/tradestation/test_client.py`
6. `alpha_tech_tracker/op_momentum_strategy/tradestation_auth.py`
7. `alpha_tech_tracker/op_momentum_strategy/config.py` (extend)
8. `alpha_tech_tracker/op_momentum_strategy/config.json` (add placeholder section)

---

## 8. Open Questions

- **`user_id` for accounts endpoint:** The v2 `/users/{user_id}/accounts` endpoint needs the
  `userid` field from the token response. Need to confirm this is returned by
  `signin.tradestation.com/oauth/token` in the same token exchange response, or whether
  it requires a separate `/userinfo` call.

- **`order_status` by ID:** The v2 API returns all orders for the day via
  `/accounts/{key}/orders`, not a single order by ID. Filtering the list by `OrderID`
  works but is inefficient for frequent polling. Check if v3 has a single-order endpoint.

- **Simulation account key:** The `sim-api` environment may use a different `account_key`
  than the live account. Confirm whether the same key works across environments or
  whether a separate config field is needed.

import logging
import os
import re
import webbrowser
from datetime import datetime
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

from requests_oauthlib import OAuth2Session

from alpha_tech_tracker.trade_api.execution_client import ExecutionClient, InsufficientFundsError

logger = logging.getLogger("trade_api.tradestation")

_AUTH_URL = "https://signin.tradestation.com/authorize"
_TOKEN_URL = "https://signin.tradestation.com/oauth/token"
_SCOPES = "openid offline_access profile MarketData ReadAccount Trade OptionSpreads"

_BASE_URLS = {
    "live": "https://api.tradestation.com",
    "sim": "https://sim-api.tradestation.com",
}

_TS_STATUS_MAP = {
    "OPN": "open",
    "ACK": "open",
    "DON": "open",
    "FPR": "open",
    "UCN": "open",
    "LAT": "open",
    "OUT": "open",
    "PLA": "open",
    "FLL": "filled",
    "FLP": "filled",
    "CAN": "canceled",
    "REJ": "canceled",
    "TSC": "canceled",
    "BRO": "canceled",
    "REJ": "canceled",
    "EXP": "expired",
}

_TRADE_ACTION_MAP = {
    "BUY_OPEN": "BUYTOOPEN",
    "BUY_CLOSE": "BUYTOCLOSE",
    "SELL_OPEN": "SELLTOOPEN",
    "SELL_CLOSE": "SELLTOCLOSE",
}


class APIError(Exception):
    def __init__(self, code, message):
        self.code = code
        self.message = message
        super().__init__(message)


class APIInvalidArgumentError(APIError):
    pass


def _occ_to_ts(occ_symbol: str) -> str:
    """Convert OCC symbol to TradeStation padded format.

    e.g. 'TSLA250420C00240000' -> 'TSLA  250420C00240000'
    """
    m = re.match(r"^([A-Z]+)(\d{6}[CP]\d{8})$", occ_symbol)
    if not m:
        raise ValueError(f"Cannot parse OCC symbol: {occ_symbol}")
    ticker, suffix = m.groups()
    padded_ticker = ticker.ljust(6)
    return padded_ticker + suffix


def _ts_to_occ(ts_symbol: str) -> str:
    """Convert a TradeStation option symbol to standard 21-char OCC format.

    Handles two TS symbol variants:
    - Padded quote format:   'TSLA  250420C00240000' -> 'TSLA250420C00240000'
    - Display/positions API: 'APP 260501C410'        -> 'APP260501C00410000'
                             'TSLA 260417C392.5'     -> 'TSLA260417C00392500'
    """
    ts_symbol = ts_symbol.strip()
    # Padded format: ticker (up to 6 chars, space-padded) + YYMMDD + C/P + 8-digit strike
    m = re.match(r"^([A-Z]+)\s*(\d{6}[CP]\d{8})$", ts_symbol)
    if m:
        return m.group(1) + m.group(2)
    # Display format: ticker + space(s) + YYMMDD + C/P + decimal strike (no leading zeros)
    m = re.match(r"^([A-Z]+)\s+(\d{6})([CP])(\d+(?:\.\d+)?)$", ts_symbol)
    if m:
        ticker, date_str, cp, strike_str = m.groups()
        strike_int = round(float(strike_str) * 1000)
        return f"{ticker}{date_str}{cp}{strike_int:08d}"
    raise ValueError(f"Cannot parse TS symbol: {ts_symbol!r}")


def _occ_to_ts_order_symbol(occ_symbol: str) -> str:
    """Convert OCC symbol to the display format expected by v3 order execution.

    The v3 /orderexecution/orders endpoint uses the search-result display format
    (e.g. 'TSLA 260417C392.5') rather than the padded quote format.

    e.g. 'TSLA260417C00392500' -> 'TSLA 260417C392.5'
         'TSLA260417C00390000' -> 'TSLA 260417C390'
    """
    m = re.match(r"^([A-Z]+)(\d{6})([CP])(\d{8})$", occ_symbol)
    if not m:
        raise ValueError(f"Cannot parse OCC symbol: {occ_symbol!r}")
    ticker, date_str, cp, strike_raw = m.groups()
    strike = int(strike_raw) / 1000
    strike_str = f"{strike:g}"  # removes trailing zeros: 392.5 -> '392.5', 390.0 -> '390'
    return f"{ticker} {date_str}{cp}{strike_str}"


def _ts_search_name_to_occ(name: str) -> str:
    """Convert a TradeStation symbol-search Name to OCC format.

    Search results use a display name like 'TSLA 260417C342.5' rather than
    the padded quote format 'TSLA  260417C00342500'.  We need to re-encode
    the decimal strike into the 8-digit OCC integer representation.

    e.g. 'TSLA 260417C342.5' -> 'TSLA260417C00342500'
    """
    clean = name.replace(" ", "")
    m = re.match(r"^([A-Z]+)(\d{6})([CP])([\d.]+)$", clean)
    if not m:
        raise ValueError(f"Cannot parse TS search name: {name!r}")
    ticker, date_str, cp, strike_str = m.groups()
    strike_int = round(float(strike_str) * 1000)
    return f"{ticker}{date_str}{cp}{strike_int:08d}"


def _parse_ts_date(date_str: str) -> str:
    """Parse a TradeStation date value to YYYY-MM-DD string.

    Handles both the legacy /Date(epoch_ms)/ JSON format and ISO strings.
    """
    from datetime import datetime as _dt
    m = re.match(r"/Date\((\d+)\)/", date_str)
    if m:
        ms = int(m.group(1))
        return _dt.utcfromtimestamp(ms / 1000).strftime("%Y-%m-%d")
    return str(date_str)[:10]


def _extract_v3_order(data: dict) -> dict:
    """Extract the first order record from a v3 orderexecution response.

    v3 wraps placement responses as {'Orders': [{...}]}.
    Returns the inner order dict, or the raw data if the shape is unexpected.
    """
    if isinstance(data, dict) and "Orders" in data:
        orders = data["Orders"]
        if orders:
            return orders[0]
    return data


def _parse_tick_from_error(message: str):
    """Extract the required tick size from a TradeStation tick-rejection message.

    Confirmed format from production RejectReason field (2026-04-17):
      "Price = 41.65000000 not rounded to a valid price increment [ 0.1 ]"
      "Price = 0.09000000 not rounded to a valid price increment [ 0.05 ]"

    The tick appears inside square brackets at the end.  A secondary pattern
    covers HTTP-level 400 messages which use a different phrasing.

    Returns a Decimal tick if one is found, else None.
    """
    patterns = [
        r"price increment\s*\[\s*([\d.]+)\s*\]",
        r"increment[s]?\s+of\s+([\d.]+)",
        r"multiple\s+of\s+([\d.]+)",
    ]
    for pat in patterns:
        m = re.search(pat, message, re.IGNORECASE)
        if m:
            try:
                return Decimal(m.group(1))
            except Exception:
                pass
    return None


def _is_ts_insufficient_funds(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "insufficient" in msg and ("buying power" in msg or "funds" in msg or "balance" in msg)


class _CallbackHandler(BaseHTTPRequestHandler):
    """Minimal HTTP handler that captures the OAuth callback code."""

    auth_code = None

    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        if "code" in params:
            _CallbackHandler.auth_code = params["code"][0]
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Authorization complete - you can close this tab.")

    def log_message(self, format, *args):
        pass  # suppress request logging


class TradeStationAPIClient(ExecutionClient):
    def __init__(
        self,
        client_id=None,
        client_secret=None,
        redirect_uri="http://localhost:8080",
        selected_account_key=None,
        environment="live",
    ):
        self._client_id = client_id or os.environ.get("TS_CLIENT_ID")
        self._client_secret = client_secret or os.environ.get("TS_CLIENT_SECRET")
        self._redirect_uri = redirect_uri
        self._account_key = selected_account_key
        self._environment = environment
        self._base_url = _BASE_URLS.get(environment, _BASE_URLS["live"]) + "/v2"
        self._v3_base_url = _BASE_URLS.get(environment, _BASE_URLS["live"]) + "/v3"
        self._session = None
        self._user_id = None

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    def authorize_session(self) -> dict:
        if not self._client_id or not self._client_secret:
            raise RuntimeError(
                "TradeStation credentials are missing.\n"
                "Set TS_CLIENT_ID and TS_CLIENT_SECRET environment variables,\n"
                "or add 'tradestation_credentials' to config.json."
            )

        oauth = OAuth2Session(
            client_id=self._client_id,
            redirect_uri=self._redirect_uri,
            scope=_SCOPES,
        )
        auth_url, _ = oauth.authorization_url(
            _AUTH_URL,
            audience="https://api.tradestation.com",
        )

        _CallbackHandler.auth_code = None
        server = HTTPServer(("localhost", 8080), _CallbackHandler)
        server.timeout = 120

        print(f"\nOpening browser for TradeStation authorization...")
        print(f"If the browser does not open, visit:\n  {auth_url}\n")
        webbrowser.open(auth_url)

        while _CallbackHandler.auth_code is None:
            server.handle_request()
        server.server_close()

        token = oauth.fetch_token(
            _TOKEN_URL,
            code=_CallbackHandler.auth_code,
            client_secret=self._client_secret,
            include_client_id=True,
        )
        self._user_id = token.get("userid")
        self._build_session(token)
        return token

    def restore_session(self, token: dict):
        self._user_id = token.get("userid")
        self._build_session(token)

    def verify_session(self) -> bool:
        if self._session is None:
            return False
        try:
            url = self._base_url + "/data/quote/MSFT"
            response = self._session.get(url)
            return response.status_code == 200
        except Exception:
            return False

    def _build_session(self, token: dict):
        from requests.adapters import HTTPAdapter

        from alpha_tech_tracker.op_momentum_strategy.config import (
            _save_tradestation_session_tokens,
        )

        self._session = OAuth2Session(
            client_id=self._client_id,
            token=token,
            auto_refresh_url=_TOKEN_URL,
            auto_refresh_kwargs={
                "client_id": self._client_id,
                "client_secret": self._client_secret,
            },
            token_updater=_save_tradestation_session_tokens,
        )
        adapter = HTTPAdapter(pool_connections=30, pool_maxsize=30)
        self._session.mount("https://", adapter)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get(self, path: str, **kwargs) -> dict:
        response = self._session.get(self._base_url + path, **kwargs)
        return self._parse(response)

    def _post(self, path: str, json: dict) -> dict:
        response = self._session.post(self._base_url + path, json=json)
        return self._parse(response)

    def _delete(self, path: str) -> dict:
        response = self._session.delete(self._base_url + path)
        return self._parse(response)

    def _parse(self, response) -> dict:
        data = response.json()
        if response.status_code in (200, 201):
            return data
        code = str(response.status_code)
        message = data.get("Message", str(data))
        logger.error("TradeStation API error %s: %s", response.status_code, message)
        if response.status_code == 400:
            raise APIInvalidArgumentError(code=code, message=message)
        raise APIError(code=code, message=message)

    def _get_account_key(self) -> str:
        if self._account_key is not None:
            return str(self._account_key)
        response = self._session.get(self._v3_base_url + "/brokerage/accounts")
        data = self._parse(response)
        accounts = data if isinstance(data, list) else data.get("Accounts", [])
        active = [a for a in accounts if a.get("Status") == "Active"]
        account = active[0] if active else accounts[0]
        self._account_key = str(account["AccountID"])
        return self._account_key

    def _normalize_order(self, raw: dict, order_id: str = None) -> dict:
        status_code = raw.get("Status", "OPN")
        leg = raw.get("Legs", [{}])[0] if raw.get("Legs") else {}

        raw_symbol = leg.get("Symbol") or raw.get("Symbol", "")
        try:
            symbol = _ts_search_name_to_occ(raw_symbol) if raw_symbol else ""
        except ValueError:
            symbol = raw_symbol

        quantity = float(leg.get("QuantityOrdered") or raw.get("Quantity") or 0)
        filled_qty = float(leg.get("ExecQuantity") or raw.get("ExecuteQuantity") or 0)
        filled_price_raw = raw.get("FilledPrice") or raw.get("AverageFillPrice")

        return {
            "order_id": str(raw.get("OrderID", order_id or "")),
            "symbol": symbol,
            "quantity": quantity,
            "filled_qty": filled_qty,
            "side": leg.get("BuyOrSell", raw.get("Type", "")),
            "type": raw.get("Duration", "DAY"),
            "status": _TS_STATUS_MAP.get(status_code, "open"),
            "limit_price": float(raw["LimitPrice"]) if raw.get("LimitPrice") else None,
            "filled_avg_price": float(filled_price_raw) if filled_price_raw else None,
            "submitted_at": raw.get("OpenedDateTime") or raw.get("TimeStamp"),
            "reject_reason": raw.get("RejectReason"),
            "raw_response": raw,
        }

    # ------------------------------------------------------------------
    # ExecutionClient interface
    # ------------------------------------------------------------------

    def get_accounts(self) -> dict:
        account_key = self._get_account_key()
        response = self._session.get(
            self._v3_base_url + f"/brokerage/accounts/{account_key}/balances"
        )
        data = self._parse(response)
        balances = data if isinstance(data, list) else data.get("Balances", [])
        b = balances[0]
        option_bp_raw = b.get("RealTimeOptionBuyingPower")
        cash = float(b.get("CashBalance", 0))
        # PDT-flagged margin accounts report BuyingPower=0; fall back to CashBalance
        bp_raw = float(b.get("BuyingPower", 0))
        buying_power = bp_raw if bp_raw > 0 else cash
        return {
            "account_id": str(account_key),
            "cash": cash,
            "buying_power": buying_power,
            "option_buying_power": float(option_bp_raw) if option_bp_raw is not None else None,
            "portfolio_value": float(b.get("Equity", 0)),
            "equity": float(b.get("Equity", 0)),
            "raw_response": b,
        }

    def get_historical_bars(
        self,
        symbol: str,
        start_dt,
        end_dt,
        interval: int = 1,
        unit: str = "Minute",
    ) -> list:
        """Fetch historical bars from TradeStation v3 /marketdata/barcharts/{symbol}.

        Returns a list of _TSBar objects ordered oldest-first.

        Args:
            symbol:   Ticker symbol (e.g. "TSLA")
            start_dt: tz-aware datetime — first bar open time to include.
                      Shifted back by one interval internally because the API's
                      firstdate param is exclusive.
            end_dt:   tz-aware datetime — last bar close time to include.
            interval: Bar width in units (default 1). Use 5 for 5-min bars.
            unit:     "Minute" (default) or "Daily".
        """
        from datetime import timedelta
        from alpha_tech_tracker.trade_api.tradestation.bar_stream import _TSBar

        effective_start = start_dt - timedelta(minutes=interval)
        params = {
            "interval": interval,
            "unit": unit,
            "firstdate": effective_start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "lastdate": end_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "sessiontemplate": "Default",
        }
        url = self._v3_base_url + f"/marketdata/barcharts/{symbol}"
        response = self._session.get(url, params=params)
        data = self._parse(response)
        bars_raw = data.get("Bars", []) if isinstance(data, dict) else []
        return [
            _TSBar.from_ts_dict(b, symbol, interval_minutes=interval)
            for b in bars_raw
            if b.get("Open")
        ]

    def get_stock_quote(self, symbols, **_) -> dict:
        if isinstance(symbols, list):
            symbols_str = ",".join(symbols)
        else:
            symbols_str = symbols
            symbols = [symbols]

        data = self._get(f"/data/quote/{symbols_str}")
        quotes = data if isinstance(data, list) else data.get("Quotes", [])

        formatted = {}
        for q in quotes:
            sym = q["Symbol"]
            formatted[sym] = {
                "QuoteResponse": {
                    "QuoteData": [
                        {
                            "All": {
                                "bid": float(q.get("Bid", 0)),
                                "ask": float(q.get("Ask", 0)),
                                "bid_size": q.get("BidSize"),
                                "ask_size": q.get("AskSize"),
                                "last": q.get("Last"),
                            }
                        }
                    ]
                }
            }

        if len(symbols) == 1:
            return formatted.get(symbols[0], formatted)
        return formatted

    def get_option_quote_by_occ(self, occ_symbol: str) -> dict:
        ts_symbol = _occ_to_ts_order_symbol(occ_symbol)
        data = self._get(f"/data/quote/{ts_symbol}")
        quotes = data if isinstance(data, list) else data.get("Quotes", [])
        q = quotes[0]
        bid = float(q.get("Bid", 0))
        ask = float(q.get("Ask", 0))
        return {"bid": bid, "ask": ask, "mid": (bid + ask) / 2}

    def get_option_latest_trade_by_occ(self, occ_symbol: str):
        return None

    def get_option_quotes_by_occ_batch(self, occ_symbols: list) -> dict:
        if not occ_symbols:
            return {}
        # Build display-format symbols and keep a reverse mapping back to OCC
        ts_symbols = [_occ_to_ts_order_symbol(s) for s in occ_symbols]
        ts_to_occ_map = {ts: occ for ts, occ in zip(ts_symbols, occ_symbols)}

        data = self._get(f"/data/quote/{','.join(ts_symbols)}")
        quotes = data if isinstance(data, list) else data.get("Quotes", [])

        result = {}
        for q in quotes:
            raw_sym = q.get("Symbol", "")
            occ = ts_to_occ_map.get(raw_sym)
            if occ is None:
                # Response may strip trailing .0 or reformat — try name-based parse
                try:
                    occ = _ts_search_name_to_occ(raw_sym)
                except ValueError:
                    pass
            if occ is None or occ not in occ_symbols:
                logger.warning("Unexpected symbol in batch quote response: %s", raw_sym)
                continue
            bid = float(q.get("Bid", 0))
            ask = float(q.get("Ask", 0))
            result[occ] = {"bid": bid, "ask": ask, "mid": (bid + ask) / 2}

        missing = set(occ_symbols) - set(result)
        for sym in missing:
            logger.warning("Symbol missing from batch quote response: %s", sym)
        return result

    def get_options_contracts(
        self,
        underlying_symbol: str,
        expiration_date=None,
        expiration_date_gte=None,
        expiration_date_lte=None,
        option_type=None,
        strike_price_gte=None,
        strike_price_lte=None,
        limit: int = 100,
    ) -> list:
        ot_map = {"call": "Call", "put": "Put", "CALL": "Call", "PUT": "Put"}
        ot = ot_map.get(option_type, "Both") if option_type else "Both"

        criteria = f"R={underlying_symbol}&C=StockOption&OT={ot}&Stk=20"

        if expiration_date is not None:
            if hasattr(expiration_date, "strftime"):
                date_str = expiration_date.strftime("%m-%d-%Y")
            else:
                dt = datetime.strptime(str(expiration_date), "%Y-%m-%d")
                date_str = dt.strftime("%m-%d-%Y")
            criteria += f"&Edl={date_str}&Edh={date_str}"
        elif expiration_date_gte is not None or expiration_date_lte is not None:
            if expiration_date_gte is not None:
                if hasattr(expiration_date_gte, "strftime"):
                    low_str = expiration_date_gte.strftime("%m-%d-%Y")
                else:
                    low_str = datetime.strptime(str(expiration_date_gte), "%Y-%m-%d").strftime("%m-%d-%Y")
                criteria += f"&Edl={low_str}"
            if expiration_date_lte is not None:
                if hasattr(expiration_date_lte, "strftime"):
                    high_str = expiration_date_lte.strftime("%m-%d-%Y")
                else:
                    high_str = datetime.strptime(str(expiration_date_lte), "%Y-%m-%d").strftime("%m-%d-%Y")
                criteria += f"&Edh={high_str}"

        data = self._get(f"/data/symbols/search/{criteria}")
        items = data if isinstance(data, list) else []

        contracts = []
        for item in items:
            strike = float(item.get("StrikePrice", 0))
            if strike_price_gte is not None and strike < float(strike_price_gte):
                continue
            if strike_price_lte is not None and strike > float(strike_price_lte):
                continue

            raw_exp = item.get("ExpirationDate", "")
            exp_date = _parse_ts_date(raw_exp)

            opt_type_raw = item.get("OptionType", "")
            opt_type = "call" if opt_type_raw in ("Call", "Calls") else "put"

            if option_type and opt_type != option_type.lower():
                continue

            try:
                occ_symbol = _ts_search_name_to_occ(item["Name"])
            except ValueError:
                logger.warning("Skipping unparseable contract name: %s", item.get("Name"))
                continue

            contracts.append(
                {
                    "symbol": occ_symbol,
                    "underlying_symbol": item.get("Root", underlying_symbol),
                    "expiration_date": exp_date,
                    "strike_price": strike,
                    "option_type": opt_type,
                    "contract_size": 100,
                }
            )
            if len(contracts) >= limit:
                break

        return contracts

    def place_option_order(
        self,
        symbol,
        option_key=None,
        price=None,
        order_id=None,
        preview_order=None,
        price_type="LIMIT",
        option_type="CALL",
        order_action="BUY_OPEN",
        quantity=1,
        _option_symbol_override=None,
    ) -> dict:
        if _option_symbol_override:
            occ_symbol = _option_symbol_override
        else:
            raise APIInvalidArgumentError(
                code="MISSING_OPTION_SYMBOL",
                message="_option_symbol_override (OCC symbol) is required",
            )

        ts_symbol = _occ_to_ts_order_symbol(occ_symbol)
        trade_action = _TRADE_ACTION_MAP.get(order_action, "BUYTOOPEN")

        if price_type.upper() == "SMART_MARKET":
            quote = self.get_option_quote_by_occ(occ_symbol)
            bid, ask = quote["bid"], quote["ask"]
            mid = (bid + ask) / 2
            price = float(Decimal(str(round(bid + (mid - bid) * 0.1, 2))))
            price_type = "LIMIT"

        order_type = "Limit" if price_type.upper() == "LIMIT" else "Market"

        body = {
            "AccountID": self._get_account_key(),
            "AssetType": "OP",
            "Symbol": ts_symbol,
            "Quantity": str(quantity),
            "OrderType": order_type,
            "TimeInForce": {"Duration": "DAY"},
            "TradeAction": trade_action,
            "Route": "Intelligent",
        }
        if order_type == "Limit":
            if price is None:
                raise APIInvalidArgumentError(
                    code="MISSING_LIMIT_PRICE",
                    message="price is required for LIMIT orders",
                )
            body["LimitPrice"] = f"{float(price):g}"

        try:
            response = self._session.post(
                self._v3_base_url + "/orderexecution/orders", json=body
            )
            data = self._parse(response)
        except APIError as exc:
            if _is_ts_insufficient_funds(exc):
                raise InsufficientFundsError(str(exc)) from exc
            raise
        order_data = _extract_v3_order(data)

        return {
            "order_id": str(order_data.get("OrderID", "")),
            "symbol": occ_symbol,
            "quantity": float(quantity),
            "filled_qty": 0.0,
            "side": order_action,
            "type": order_type,
            "status": "open",
            "limit_price": float(price) if price is not None else None,
            "filled_avg_price": None,
            "submitted_at": None,
            "raw_response": data,
        }

    def place_stock_order(
        self,
        symbol: str,
        quantity: int,
        side: str = "BUY",
        order_type: str = "MARKET",
        limit_price: float = None,
        time_in_force: str = "DAY",
        trade_action: str = None,
    ) -> dict:
        _TS_ACTION_MAP = {
            "BUY_OPEN": "BUY",
            "SELL_CLOSE": "SELL",
            "SELL_SHORT": "SELLSHORT",
            "BUY_COVER": "BUYTOCOVER",
        }
        if trade_action is not None:
            ts_trade_action = _TS_ACTION_MAP.get(trade_action.upper(), trade_action.upper())
        else:
            ts_trade_action = "BUY" if side.upper() == "BUY" else "SELL"
        ts_order_type = "Limit" if order_type.upper() == "LIMIT" else "Market"

        if ts_order_type == "Limit" and limit_price is None:
            raise APIInvalidArgumentError(
                code="MISSING_LIMIT_PRICE",
                message="limit_price is required for LIMIT orders",
            )

        body = {
            "AccountID": self._get_account_key(),
            "AssetType": "EQ",
            "Symbol": symbol.upper(),
            "Quantity": str(quantity),
            "OrderType": ts_order_type,
            "TimeInForce": {"Duration": time_in_force.upper()},
            "TradeAction": ts_trade_action,
            "Route": "Intelligent",
        }
        if ts_order_type == "Limit":
            body["LimitPrice"] = f"{float(limit_price):g}"

        try:
            response = self._session.post(
                self._v3_base_url + "/orderexecution/orders", json=body
            )
            data = self._parse(response)
        except APIError as exc:
            if _is_ts_insufficient_funds(exc):
                raise InsufficientFundsError(str(exc)) from exc
            raise
        order_data = _extract_v3_order(data)

        return {
            "order_id": str(order_data.get("OrderID", "")),
            "symbol": symbol.upper(),
            "quantity": float(quantity),
            "filled_qty": 0.0,
            "side": trade_action,
            "type": ts_order_type,
            "status": "open",
            "limit_price": float(limit_price) if limit_price is not None else None,
            "filled_avg_price": None,
            "submitted_at": None,
            "raw_response": data,
        }

    def order_status(self, order_id: str) -> dict:
        account_key = self._get_account_key()
        response = self._session.get(
            self._v3_base_url + f"/brokerage/accounts/{account_key}/orders",
            params={"pageSize": 200},
        )
        data = self._parse(response)
        orders = data if isinstance(data, list) else data.get("Orders", [])

        for order in orders:
            if str(order.get("OrderID", "")) == str(order_id):
                return self._normalize_order(order, order_id)

        logger.warning("Order %s not found in today's orders — treating as open", order_id)
        return {
            "order_id": order_id,
            "symbol": "",
            "quantity": 0.0,
            "filled_qty": 0.0,
            "side": "",
            "type": "",
            "status": "open",
            "limit_price": None,
            "filled_avg_price": None,
            "submitted_at": None,
            "raw_response": {},
        }

    def get_open_positions(self) -> dict:
        # NOTE: the /positions endpoint returns option symbols in display format
        # (e.g. 'APP 260501C410'), NOT the padded quote format ('APP   260501C00410000').
        # _ts_to_occ() handles both variants and converts to standard OCC keys so
        # callers can look up positions by pos.option_symbol without format mismatch.
        account_key = self._get_account_key()
        response = self._session.get(
            self._v3_base_url + f"/brokerage/accounts/{account_key}/positions"
        )
        try:
            data = self._parse(response)
        except Exception:
            logger.warning("get_open_positions: failed to parse response")
            return {}
        positions_list = data.get("Positions", []) if isinstance(data, dict) else []
        result = {}
        for p in positions_list:
            qty = float(p.get("Quantity", 0))
            if qty == 0:
                continue
            ts_symbol = p.get("Symbol", "")
            try:
                occ = _ts_to_occ(ts_symbol)
            except ValueError:
                # Plain stock ticker — store under the stripped ticker so callers
                # using pos.ticker as the lookup key can find it.
                result[ts_symbol.strip()] = {"qty": qty}
                continue
            result[occ] = {"qty": qty}
        return result

    def get_filled_orders(self, symbol: str, limit: int = 5) -> list:
        import pytz
        from datetime import timedelta
        ET = pytz.timezone("America/New_York")

        # Convert OCC option symbol to TS display format; plain tickers pass through
        try:
            ts_symbol = _occ_to_ts_order_symbol(symbol)
        except ValueError:
            ts_symbol = symbol.upper()

        since = (datetime.utcnow().date() - timedelta(days=3)).isoformat()
        account_key = self._get_account_key()
        response = self._session.get(
            self._v3_base_url + f"/brokerage/accounts/{account_key}/historicalorders",
            params={"symbol": ts_symbol, "since": since, "pageSize": max(limit * 3, 20)},
        )
        try:
            data = self._parse(response)
        except Exception:
            logger.warning("get_filled_orders: failed to fetch orders for %s", symbol)
            return []

        hist_orders = data if isinstance(data, list) else data.get("Orders", [])

        # historicalorders only covers completed trading days — same-day fills live on
        # /orders.  Always merge both sources so a manual close placed earlier today is
        # never missed when the ticker was also traded in the past 3 days (which would
        # make historicalorders non-empty and skip the old fallback-only path).
        today_orders: list = []
        try:
            resp2 = self._session.get(
                self._v3_base_url + f"/brokerage/accounts/{account_key}/orders",
                params={"pageSize": 200},
            )
            data2 = self._parse(resp2)
            all_today = data2 if isinstance(data2, list) else data2.get("Orders", [])
            today_orders = [o for o in all_today if ts_symbol in (
                (o.get("Legs") or [{}])[0].get("Symbol", "")
            )]
        except Exception:
            logger.warning("get_filled_orders: /orders fetch failed for %s", symbol)

        # Merge historical + today, deduplicate by OrderID.
        seen_ids: set = set()
        orders: list = []
        for raw in hist_orders + today_orders:
            oid = str(raw.get("OrderID", ""))
            if oid in seen_ids:
                continue
            seen_ids.add(oid)
            orders.append(raw)
        result = []
        for raw in orders:
            if raw.get("Status") not in ("FLL", "FLP"):
                continue

            filled_price_raw = raw.get("FilledPrice") or raw.get("AverageFillPrice")
            if not filled_price_raw:
                continue

            leg = raw.get("Legs", [{}])[0] if raw.get("Legs") else {}

            # Normalize side to "buy" or "sell"
            buy_or_sell = leg.get("BuyOrSell", "").lower()
            if not buy_or_sell:
                trade_action = leg.get("TradeAction", "").lower()
                buy_or_sell = "buy" if "buy" in trade_action else "sell"

            filled_qty_raw = leg.get("ExecQuantity") or raw.get("ExecuteQuantity") or 0

            filled_at = None
            filled_at_raw = raw.get("ClosedDateTime") or raw.get("FilledDateTime") or raw.get("TimeStamp")
            if filled_at_raw:
                try:
                    dt = datetime.fromisoformat(str(filled_at_raw).replace("Z", "+00:00"))
                    if dt.tzinfo is None:
                        dt = ET.localize(dt)
                    filled_at = dt
                except Exception:
                    pass

            result.append({
                "order_id": str(raw.get("OrderID", "")),
                "filled_avg_price": float(filled_price_raw),
                "filled_qty": float(filled_qty_raw),
                "side": buy_or_sell,
                "filled_at": filled_at,
            })

            if len(result) >= limit:
                break

        return result

    def cancel_order(self, order_id: str) -> dict:
        response = self._session.delete(
            self._v3_base_url + f"/orderexecution/orders/{order_id}"
        )
        if response.status_code == 400:
            msg = response.json().get("Message", "")
            if "not an open order" in msg.lower():
                logger.info("Cancel skipped — order %s is already closed: %s", order_id, msg)
                return {"order_id": order_id, "status": "canceled", "message": msg}
        data = self._parse(response)
        return {
            "order_id": order_id,
            "status": "canceled",
            "message": data.get("Message", "Cancel request submitted"),
        }

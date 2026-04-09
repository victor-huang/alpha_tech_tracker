import json
import logging
import os
import queue
import random
import re
import string
import threading
import urllib.parse
import webbrowser
from datetime import date

from requests_oauthlib import OAuth1Session

from alpha_tech_tracker.trade_api.execution_client import ExecutionClient

logger = logging.getLogger("etrade_api.etrade")

_ETRADE_STATUS_MAP = {
    "EXECUTED": "filled",
    "PARTIAL_FILL": "open",
    "OPEN": "open",
    "UNCONFIRMED": "open",
    "DO_NOT_EXERCISE": "open",
    "CANCEL_REQUESTED": "canceled",
    "CANCELLED": "canceled",
    "REJECTED": "canceled",
    "EXPIRED": "expired",
}


def _parse_occ_symbol(occ_symbol: str) -> tuple:
    """
    Parse an OCC option symbol into its components.
    e.g. "TSLA250420C00240000" → ("TSLA", 2025, 4, 20, "CALL", 240.0)
    """
    m = re.match(r"^([A-Z]+)(\d{2})(\d{2})(\d{2})([CP])(\d{8})$", occ_symbol)
    if not m:
        raise ValueError(f"Cannot parse OCC symbol: {occ_symbol}")
    ticker, yy, mm, dd, cp, strike_str = m.groups()
    return (
        ticker,
        2000 + int(yy),
        int(mm),
        int(dd),
        "CALL" if cp == "C" else "PUT",
        int(strike_str) / 1000.0,
    )


def _build_occ_symbol(
    ticker: str, year: int, month: int, day: int, option_type: str, strike: float
) -> str:
    """Build OCC symbol from individual components."""
    cp = "C" if option_type.upper() == "CALL" else "P"
    strike_int = round(strike * 1000)
    return f"{ticker}{year % 100:02d}{month:02d}{day:02d}{cp}{strike_int:08d}"


class APIError(Exception):
    def __init__(self, code, message):
        self.code = code
        self.message = message
        super().__init__(message)


class APIInvalidArgumentError(APIError):
    pass


class ClientError(Exception):
    pass


class EtradeAPIClient(ExecutionClient):
    def __init__(
        self,
        key_id=None,
        client_secret=None,
        is_sandbox_enabled=False,
        selected_account_id=None,
    ):
        self._api_key = key_id or os.environ.get("ETRADE_API_KEY_ID")
        self._client_secret = client_secret or os.environ.get("ETRADE_API_SECRET_KEY")
        self._session = None
        self._selected_account_id = selected_account_id
        self._account_id_key = None  # lazily resolved for balance API

        if is_sandbox_enabled:
            self._base_url_host = "apisb.etrade.com"
        else:
            self._base_url_host = "api.etrade.com"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _base_url(self):
        return f"https://{self._base_url_host}"

    def _parse_response(self, response):
        if response.status_code in [200, 201]:
            return json.loads(response.text)
        error_obj = json.loads(response.text)
        logger.error("ETrade API error %s: %s", response.status_code, response.text)
        if response.status_code == 400:
            raise APIInvalidArgumentError(
                code=error_obj["Error"]["code"],
                message=error_obj["Error"]["message"],
            )
        raise APIError(
            code=error_obj["Error"]["code"],
            message=error_obj["Error"]["message"],
        )

    def _generate_order_id(self, length=8):
        chars = string.ascii_letters + string.digits
        return "".join(random.choice(chars) for _ in range(length))

    def round_nearest(self, x, smallest_unit):
        return round(x / smallest_unit) * smallest_unit

    def _parse_option_key(self, option_key):
        """Parse legacy option key format "YYYY-MM-DD sSTRIKE"."""
        expiry_year, expiry_month, remaining = option_key.split("-")
        expiry_day, strike_price = remaining.split()
        strike_price = strike_price[1:]  # strip leading 's'
        return [expiry_year, expiry_month, expiry_day, strike_price]

    def _get_account_id_key(self) -> str:
        """Return accountIdKey for the selected account (cached after first call)."""
        if self._account_id_key is not None:
            return self._account_id_key
        url = self._base_url() + "/v1/accounts/list.json"
        data = self._parse_response(self._session.get(url))
        accounts = data["AccountListResponse"]["Accounts"]["Account"]
        if self._selected_account_id:
            for acct in accounts:
                if str(acct["accountId"]) == str(self._selected_account_id):
                    self._account_id_key = acct["accountIdKey"]
                    return self._account_id_key
        self._account_id_key = accounts[0]["accountIdKey"]
        return self._account_id_key

    def _fetch_option_chain(
        self,
        symbol: str,
        expiry: date,
        chain_type: str,
        strike_gte=None,
        strike_lte=None,
        limit: int = 100,
    ) -> list:
        """Call ETrade option chain API for a specific expiry date."""
        params = {
            "symbol": symbol,
            "expiryYear": expiry.year,
            "expiryMonth": expiry.month,
            "expiryDay": expiry.day,
            "chainType": chain_type,
            "noOfStrikes": min(limit, 50),
            "optionCategory": "STANDARD",
            "skipAdjusted": "true",
        }
        if strike_gte is not None and strike_lte is not None:
            params["strikePriceNear"] = (float(strike_gte) + float(strike_lte)) / 2

        url = self._base_url() + "/v1/market/optionchains.json"
        data = self._parse_response(self._session.get(url, params=params))

        pairs = data.get("OptionChainResponse", {}).get("OptionPair", [])
        contracts = []
        for pair in pairs:
            for side_key in ("Call", "Put"):
                opt = pair.get(side_key)
                if opt is None:
                    continue
                opt_type = opt.get("optionType", "").upper()
                if chain_type != "CALLPUT" and opt_type != chain_type:
                    continue
                strike = float(opt.get("strikePrice", 0))
                if strike_gte is not None and strike < float(strike_gte):
                    continue
                if strike_lte is not None and strike > float(strike_lte):
                    continue
                occ_symbol = _build_occ_symbol(
                    symbol, expiry.year, expiry.month, expiry.day, opt_type, strike
                )
                contracts.append(
                    {
                        "symbol": occ_symbol,
                        "underlying_symbol": symbol,
                        "expiration_date": str(expiry),
                        "strike_price": strike,
                        "option_type": opt_type,
                        "contract_size": 100,
                    }
                )
        return contracts[:limit]

    def _get_option_expiry_dates(self, symbol: str) -> list:
        """Return sorted list of available option expiry dates for a symbol."""
        url = self._base_url() + "/v1/market/optionexpiredate.json"
        data = self._parse_response(
            self._session.get(url, params={"symbol": symbol, "expiryType": "ALL"})
        )
        expiry_items = (
            data.get("OptionExpireDateResponse", {}).get("ExpirationDate", [])
        )
        dates = []
        for item in expiry_items:
            try:
                dates.append(date(int(item["year"]), int(item["month"]), int(item["day"])))
            except (KeyError, ValueError):
                pass
        return sorted(dates)

    def _normalize_order_status(self, etrade_status: str) -> str:
        return _ETRADE_STATUS_MAP.get(etrade_status.upper(), "open")

    def _build_option_order_instrument(
        self,
        ticker: str,
        year: int,
        month: int,
        day: int,
        option_type: str,
        strike: float,
        order_action: str,
        quantity: int,
    ) -> dict:
        strike_val = int(strike) if strike == int(strike) else strike
        return {
            "Product": {
                "securityType": "OPTN",
                "symbol": ticker,
                "callPut": option_type,
                "expiryDay": day,
                "expiryMonth": month,
                "expiryYear": year,
                "strikePrice": strike_val,
            },
            "orderAction": order_action,
            "quantityType": "QUANTITY",
            "quantity": quantity,
        }

    def _preview_option_order_raw(
        self,
        ticker: str,
        year: int,
        month: int,
        day: int,
        option_type: str,
        strike: float,
        price,
        price_type: str,
        order_action: str,
        quantity: int,
    ) -> dict:
        instrument = self._build_option_order_instrument(
            ticker, year, month, day, option_type, strike, order_action, quantity
        )
        payload = {
            "PreviewOrderRequest": {
                "orderType": "OPTN",
                "clientOrderId": self._generate_order_id(),
                "Order": [
                    {
                        "allOrNone": "false",
                        "priceType": price_type,
                        "orderTerm": "GOOD_FOR_DAY",
                        "marketSession": "REGULAR",
                        "stopPrice": "",
                        "limitPrice": price if price_type == "LIMIT" else "",
                        "Instrument": [instrument],
                    }
                ],
            }
        }
        url = f"{self._base_url()}/v1/accounts/{self._selected_account_id}/orders/preview.json"
        return self._parse_response(self._session.post(url, json=payload))

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    def read_oauth_verifier_from_file(self, json_file_path, delete_after_read=True):
        try:
            with open(json_file_path, "r") as f:
                data = json.load(f)
                logger.info("File %s content: %s", json_file_path, data)
            if delete_after_read:
                os.remove(json_file_path)
                logger.info("Deleted file %s after reading", json_file_path)
            return data["oauth_verifier"]
        except Exception as e:
            logger.error("Failed to read file %s: %s", json_file_path, e)

    def input_with_timeout(self, prompt, timeout=20):
        input_queue = queue.Queue()

        def get_input():
            input_queue.put(input(prompt))

        t = threading.Thread(target=get_input)
        t.start()
        t.join(timeout)
        if t.is_alive():
            logger.warning("Input timeout. No input received.")
            return None
        return input_queue.get()

    def authorize_session(self):
        callback_url = "oob"
        session = OAuth1Session(
            self._api_key,
            client_secret=self._client_secret,
            callback_uri=callback_url,
        )

        request_token_url = f"https://{self._base_url_host}/oauth/request_token"
        request_token_info = session.fetch_request_token(request_token_url)

        access_token = urllib.parse.quote(request_token_info["oauth_token"])
        token_secret = urllib.parse.quote(request_token_info["oauth_token_secret"])

        authorization_url = (
            f"https://us.etrade.com/e/t/etws/authorize"
            f"?key={self._api_key}&token={access_token}"
        )
        webbrowser.open(authorization_url)
        print(f"Please go to {authorization_url} and authorize access")

        oauth_verifier = None
        remain_retries = 2
        while oauth_verifier is None and remain_retries > 0:
            try:
                oauth_verifier = self.input_with_timeout("Auth Text: ")
            except Exception as e:
                logger.error("Problem reading input: %s", e)
            try:
                data_file = "/home/ec2-user/alpha_tech_tracker/web_server/auth_call_back_data.json"
                oauth_verifier = self.read_oauth_verifier_from_file(data_file)
            except Exception as e:
                logger.error("Problem reading data file: %s", e)
            remain_retries -= 1

        redirect_response = (
            f"https://127.0.0.1/callback?oauth_token={access_token}"
            f"&oauth_token_secret={token_secret}&oauth_verifier={oauth_verifier}"
        )
        session.parse_authorization_response(redirect_response)

        access_token_url = f"https://{self._base_url_host}/oauth/access_token"
        access_token_info = session.fetch_access_token(access_token_url)
        logger.info(access_token_info)

        self._session = session
        return session

    # ------------------------------------------------------------------
    # ExecutionClient interface
    # ------------------------------------------------------------------

    def get_accounts(self) -> dict:
        """Return account state including buying_power from ETrade balance API."""
        account_id_key = self._get_account_id_key()
        url = self._base_url() + f"/v1/accounts/{account_id_key}/balance.json"
        data = self._parse_response(
            self._session.get(
                url, params={"instType": "BROKERAGE", "realTimeNAV": "true"}
            )
        )
        computed = data["BalanceResponse"]["Computed"]
        return {
            "account_id": str(self._selected_account_id or ""),
            "buying_power": float(computed.get("cashBuyingPower", 0)),
            "portfolio_value": float(
                computed.get("realTimeValues", {}).get("totalAccountValue", 0)
            ),
            "cash": float(computed.get("cashBalance", 0)),
        }

    def get_stock_quote(self, symbols) -> dict:
        """Return stock or option quote(s) in Alpaca-compatible nested format."""
        url = self._base_url() + "/v1/market/quote/" + symbols + ".json"
        return self._parse_response(self._session.get(url))

    def get_option_quote_by_occ(self, occ_symbol: str) -> dict:
        """Return bid/ask/mid for a single option identified by OCC symbol."""
        ticker, year, month, day, opt_type, strike = _parse_occ_symbol(occ_symbol)
        strike_str = str(int(strike)) if strike == int(strike) else str(strike)
        etrade_key = f"{ticker}:{year}:{month:02d}:{day:02d}:{opt_type}:{strike_str}"
        raw = self.get_stock_quote(etrade_key)
        all_data = raw["QuoteResponse"]["QuoteData"][0]["All"]
        bid = float(all_data["bid"])
        ask = float(all_data["ask"])
        mid = (bid + ask) / 2
        return {"bid": bid, "ask": ask, "mid": mid}

    def get_option_quotes_by_occ_batch(self, occ_symbols: list) -> dict:
        """Return bid/ask/mid for multiple options. Falls back gracefully on errors."""
        result = {}
        for occ in occ_symbols:
            try:
                result[occ] = self.get_option_quote_by_occ(occ)
            except Exception as e:
                logger.warning("Batch quote failed for %s: %s", occ, e)
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
        """Return available contracts from ETrade option chain API."""
        chain_type = "CALLPUT"
        if option_type:
            chain_type = option_type.upper()

        if expiration_date is not None:
            if isinstance(expiration_date, date):
                expiry = expiration_date
            else:
                expiry = date.fromisoformat(str(expiration_date))
            return self._fetch_option_chain(
                underlying_symbol, expiry, chain_type,
                strike_price_gte, strike_price_lte, limit,
            )

        # Range query (monthly fallback path): find earliest available expiry in range
        gte = (
            date.fromisoformat(str(expiration_date_gte))
            if expiration_date_gte
            else date.min
        )
        lte = (
            date.fromisoformat(str(expiration_date_lte))
            if expiration_date_lte
            else date.max
        )
        available = self._get_option_expiry_dates(underlying_symbol)
        in_range = [d for d in available if gte <= d <= lte]
        if not in_range:
            return []
        earliest = min(in_range)
        return self._fetch_option_chain(
            underlying_symbol, earliest, chain_type,
            strike_price_gte, strike_price_lte, limit,
        )

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
        """
        Place an option order via ETrade's preview → place flow.
        _option_symbol_override accepts an OCC symbol; symbol/option_key are
        ignored when it is provided.
        Returns normalized dict with order_id and status.
        """
        if _option_symbol_override:
            ticker, year, month, day, opt_type, strike = _parse_occ_symbol(
                _option_symbol_override
            )
        elif option_key:
            y, m, d, s = self._parse_option_key(option_key)
            ticker, year, month, day, opt_type, strike = (
                symbol, int(y), int(m), int(d), option_type, float(s)
            )
        else:
            raise APIInvalidArgumentError(
                code="MISSING_OPTION_KEY",
                message="Either option_key or _option_symbol_override is required",
            )

        if price_type.upper() == "SMART_MARKET":
            occ = _build_occ_symbol(ticker, year, month, day, opt_type, strike)
            q = self.get_option_quote_by_occ(occ)
            price = self.round_nearest(
                q["bid"] + (q["ask"] - q["bid"]) / 2 * 0.9, 0.05
            )
            price_type = "LIMIT"

        preview = self._preview_option_order_raw(
            ticker, year, month, day, opt_type, strike,
            price, price_type.upper(), order_action, quantity,
        )
        preview_id = preview["PreviewOrderResponse"]["PreviewIds"][0]["previewId"]

        instrument = self._build_option_order_instrument(
            ticker, year, month, day, opt_type, strike, order_action, quantity
        )
        client_order_id = self._generate_order_id()
        payload = {
            "PlaceOrderRequest": {
                "orderType": "OPTN",
                "clientOrderId": client_order_id,
                "PreviewIds": [{"previewId": preview_id}],
                "Order": [
                    {
                        "allOrNone": "false",
                        "priceType": price_type.upper(),
                        "orderTerm": "GOOD_FOR_DAY",
                        "marketSession": "REGULAR",
                        "stopPrice": "",
                        "limitPrice": price if price_type.upper() == "LIMIT" else "",
                        "Instrument": [instrument],
                    }
                ],
            }
        }
        url = (
            f"{self._base_url()}/v1/accounts/{self._selected_account_id}/orders/place.json"
        )
        response = self._parse_response(self._session.post(url, json=payload))
        placed_order_id = response["PlaceOrderResponse"]["OrderIds"][0]["orderId"]

        return {
            "order_id": str(placed_order_id),
            "client_order_id": client_order_id,
            "symbol": _option_symbol_override or option_key or "",
            "quantity": float(quantity),
            "filled_qty": 0.0,
            "status": "open",
            "limit_price": price if price_type.upper() == "LIMIT" else None,
            "filled_avg_price": None,
            "raw_response": response,
        }

    def place_stock_order(
        self,
        symbol: str,
        quantity: int,
        side: str = "BUY",
        order_type: str = "MARKET",
        limit_price: float = None,
        time_in_force: str = "DAY",
    ) -> dict:
        """Place an equity order via ETrade's preview → place flow."""
        order_action = "BUY" if side.upper() == "BUY" else "SELL"
        price_type = order_type.upper()
        instrument = {
            "Product": {"securityType": "EQ", "symbol": symbol},
            "orderAction": order_action,
            "quantityType": "QUANTITY",
            "quantity": quantity,
        }
        client_order_id = self._generate_order_id()
        order_body = {
            "allOrNone": "false",
            "priceType": price_type,
            "orderTerm": "GOOD_FOR_DAY",
            "marketSession": "REGULAR",
            "stopPrice": "",
            "Instrument": [instrument],
        }
        if price_type == "LIMIT":
            if limit_price is None:
                raise APIInvalidArgumentError(
                    code="MISSING_LIMIT_PRICE",
                    message="limit_price required for LIMIT orders",
                )
            order_body["limitPrice"] = limit_price
        else:
            order_body["limitPrice"] = ""

        preview_payload = {
            "PreviewOrderRequest": {
                "orderType": "EQ",
                "clientOrderId": client_order_id,
                "Order": [order_body],
            }
        }
        preview_url = (
            f"{self._base_url()}/v1/accounts/{self._selected_account_id}/orders/preview.json"
        )
        preview = self._parse_response(
            self._session.post(preview_url, json=preview_payload)
        )
        preview_id = preview["PreviewOrderResponse"]["PreviewIds"][0]["previewId"]

        place_payload = {
            "PlaceOrderRequest": {
                "orderType": "EQ",
                "clientOrderId": self._generate_order_id(),
                "PreviewIds": [{"previewId": preview_id}],
                "Order": [order_body],
            }
        }
        place_url = (
            f"{self._base_url()}/v1/accounts/{self._selected_account_id}/orders/place.json"
        )
        response = self._parse_response(
            self._session.post(place_url, json=place_payload)
        )
        placed_order_id = response["PlaceOrderResponse"]["OrderIds"][0]["orderId"]

        return {
            "order_id": str(placed_order_id),
            "client_order_id": client_order_id,
            "symbol": symbol,
            "quantity": float(quantity),
            "filled_qty": 0.0,
            "side": order_action,
            "type": price_type,
            "status": "open",
            "limit_price": limit_price,
            "filled_avg_price": None,
            "raw_response": response,
        }

    def order_status(self, order_id: str) -> dict:
        """Return normalized order status dict (status: filled | open | canceled | expired)."""
        url = (
            f"{self._base_url()}/v1/accounts/{self._selected_account_id}"
            f"/orders/{order_id}.json"
        )
        data = self._parse_response(self._session.get(url))
        order = data["OrdersResponse"]["Order"][0]
        detail = order["OrderDetail"][0]
        etrade_status = detail.get("status", "OPEN")
        normalized = self._normalize_order_status(etrade_status)

        instrument = detail.get("Instrument", [{}])[0]
        filled_qty = float(instrument.get("filledQuantity", 0))
        avg_price = instrument.get("averageExecutionPrice")

        return {
            "order_id": str(order.get("orderId", order_id)),
            "status": normalized,
            "filled_qty": filled_qty,
            "filled_avg_price": float(avg_price) if avg_price is not None else None,
            "limit_price": float(detail.get("limitPrice", 0)) or None,
            "raw_response": data,
        }

    def cancel_order(self, order_id: str) -> dict:
        """Cancel a pending order."""
        payload = {"CancelOrderRequest": {"orderId": int(order_id)}}
        url = (
            f"{self._base_url()}/v1/accounts/{self._selected_account_id}/orders/cancel.json"
        )
        data = self._parse_response(self._session.put(url, json=payload))
        return {
            "order_id": str(order_id),
            "status": "canceled",
            "raw_response": data,
        }

    # ------------------------------------------------------------------
    # Legacy methods (kept for backward compatibility)
    # ------------------------------------------------------------------

    def get_option_quote(self, symbol, option_key, option_type="CALL"):
        """Legacy: get option quote using old option_key format."""
        y, m, d, strike = self._parse_option_key(option_key)
        etrade_key = f"{symbol}:{y}:{m}:{d}:{option_type}:{strike}"
        return self.get_stock_quote(etrade_key)

    def get_price_from_quote(
        self, quote, percentage_deviate_from_mid_point=-0.1, smallest_unit=0.05
    ):
        bid = quote["QuoteResponse"]["QuoteData"][0]["All"]["bid"]
        ask = quote["QuoteResponse"]["QuoteData"][0]["All"]["ask"]
        mid_price_diff = (ask - bid) / 2
        mid_price = bid + mid_price_diff
        selected_price = self.round_nearest(
            bid + mid_price_diff * (1 + percentage_deviate_from_mid_point),
            smallest_unit,
        )
        selected_price = round(selected_price, 2)
        return {"bid": bid, "ask": ask, "mid": mid_price, "s-mid": selected_price}

    def preview_option_order(
        self,
        symbol,
        option_key,
        price=None,
        price_type="LIMIT",
        option_type="CALL",
        order_action="BUY_OPEN",
        quantity=1,
    ):
        """Legacy: preview only (does not place)."""
        y, m, d, s = self._parse_option_key(option_key)
        return self._preview_option_order_raw(
            symbol, int(y), int(m), int(d), option_type, float(s),
            price, price_type, order_action, quantity,
        )

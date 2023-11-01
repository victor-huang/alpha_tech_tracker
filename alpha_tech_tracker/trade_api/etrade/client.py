import json
import logging
import os
import random
import string
import time
import urllib.parse
import uuid
import webbrowser

from requests_oauthlib import OAuth1Session

logger = logging.getLogger("etrade_api.etrade")


class APIError(Exception):
    def __init__(self, code, message):
        self.code = code
        self.message = message
        super().__init__(message)


class APIInvalidArgumentError(APIError):
    pass


class ClientError(Exception):
    pass


class EtradeAPIClient:
    def __init__(
        self,
        key_id=None,
        client_secret=None,
        is_sandbox_enabled=False,
        selected_account_id=None,
    ):
        self._api_key = key_id or os.environ.get("ETRADE_API_KEY_ID")
        self._client_secret = client_secret or os.environ.get("ETRADE_API_SECRET_KEY")
        self._session = None  # Oauth1Session
        self._selected_account_id = selected_account_id

        if is_sandbox_enabled:
            self._base_url_host = "apisb.etrade.com"  # sandbox
        else:
            self._base_url_host = "api.etrade.com"

    def _base_url(self):
        return f"https://{self._base_url_host}"

    def _parse_response(self, response):
        if response.status_code in [200, 201]:
            return json.loads(response.text)
        else:
            print("API Error: ", response.status_code, response.text)
            error_obj = json.loads(response.text)
            if response.status_code == 400:
                raise APIInvalidArgumentError(
                    code=error_obj["Error"]["code"],
                    message=error_obj["Error"]["message"],
                )
            else:
                raise APIError(
                    code=error_obj["Error"]["code"],
                    message=error_obj["Error"]["message"],
                )

    def _generate_order_id(self, length=8):
        chars = string.ascii_letters + string.digits
        return "".join(random.choice(chars) for _ in range(length))

    def _parse_option_key(self, option_key):
        expiry_year, expiry_month, remaining = option_key.split(
            "-"
        )  # e.g. "2024-10-13 s14"
        expiry_day, strike_price = remaining.split()
        strike_price = strike_price[1:]

        return [expiry_year, expiry_month, expiry_day, strike_price]

    def round_nearest(self, x, smallest_unit):
        return round(x / smallest_unit) * smallest_unit

    def authorize_session(self):
        session = OAuth1Session(
            self._api_key, client_secret=self._client_secret, callback_uri="oob"
        )

        request_token_url = "https://api.etrade.com/oauth/request_token"
        request_token_info = session.fetch_request_token(request_token_url)

        access_token = urllib.parse.quote(request_token_info["oauth_token"])
        token_secret = urllib.parse.quote(request_token_info["oauth_token_secret"])

        authorization_url = f"https://us.etrade.com/e/t/etws/authorize?key={self._api_key}&token={access_token}"
        webbrowser.open(authorization_url)
        print(f"Please go to {authorization_url} and authorize access")

        oauth_verifier = input("Auth Text: ")
        redirect_response = f"https://127.0.0.1/callback?oauth_token={access_token}&oauth_token_secret={token_secret}&oauth_verifier={oauth_verifier}"
        session.parse_authorization_response(redirect_response)

        access_token_url = "https://api.etrade.com/oauth/access_token"
        access_token_info = session.fetch_access_token(access_token_url)
        logger.info(access_token_info)

        self._session = session

        return session

    def get_stock_quote(self, symbols):
        quote_api_url = self._base_url() + "/v1/market/quote/" + symbols + ".json"
        response = self._session.get(quote_api_url)
        quote = self._parse_response(response)

        return quote

    def get_option_quote(self, symbol, option_key, option_type="CALL"):
        expiry_year, expiry_month, expiry_day, strike_price = self._parse_option_key(
            option_key
        )

        option_quote_key = f"{symbol}:{expiry_year}:{expiry_month}:{expiry_day}:{option_type}:{strike_price}"
        option_quote = self.get_stock_quote(option_quote_key)

        return option_quote

    def get_price_from_quote(
        self, quote, percentage_deviate_from_mid_point=-0.1, smallest_unit=0.05
    ):
        """
        params:
            percentage_deviate_from_mid_point: percentage deviation from the mid point price, positive means scale toward ask, negative meann scale toward bid
        """

        decimal_place = 2
        bid = quote["QuoteResponse"]["QuoteData"][0]["All"]["bid"]
        ask = quote["QuoteResponse"]["QuoteData"][0]["All"]["ask"]
        mid_price_diff = (ask - bid) / 2
        mid_price = bid + mid_price_diff

        selected_price = self.round_nearest(
            bid + mid_price_diff * (1 + percentage_deviate_from_mid_point),
            smallest_unit,
        )
        selected_price = round(selected_price, decimal_place)

        print(
            f"Price, Bid: {bid}, Ask: {ask}, Mid: {mid_price}, SMid: {selected_price}"
        )

        return {
            "bid": bid,
            "ask": ask,
            "mid": mid_price,
            "s-mid": selected_price,
        }

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
        expiry_year, expiry_month, expiry_day, strike_price = self._parse_option_key(
            option_key
        )

        account_id = self._selected_account_id
        order_id = self._generate_order_id()

        preview_option_order_payload = {
            "PreviewOrderRequest": {
                "orderType": "OPTN",
                "clientOrderId": "1231231231",
                "Order": [
                    {
                        "allOrNone": "false",
                        "priceType": price_type,
                        "orderTerm": "GOOD_FOR_DAY",
                        "marketSession": "REGULAR",
                        "stopPrice": "",
                        "limitPrice": price,  # this is not being used
                        "Instrument": [
                            {
                                "Product": {
                                    "securityType": "OPTN",
                                    "symbol": symbol,
                                    "callPut": option_type,
                                    "expiryDay": expiry_day,
                                    "expiryMonth": expiry_month,
                                    "expiryYear": expiry_year,
                                    "strikePrice": strike_price,
                                },
                                "orderAction": order_action,
                                "quantityType": "QUANTITY",
                                "quantity": quantity,
                            }
                        ],
                    }
                ],
            }
        }

        print(preview_option_order_payload)

        preview_order_endpoint = f"https://{self._base_url_host}/v1/accounts/{account_id}/orders/preview.json"
        response = self._session.post(
            preview_order_endpoint, json=preview_option_order_payload
        )
        preview_order = self._parse_response(response)
        print(preview_order)

        #  import ipdb; ipdb.set_trace()
        # preview_order['PreviewOrderResponse']['PreviewIds'][0]['previewId']

        return {order_id: preview_order}

    def place_option_order(
        self,
        symbol,
        option_key,
        price,
        order_id=None,
        preview_order=None,
        price_type="LIMIT",
        option_type="CALL",
        order_action="BUY_OPEN",
        quantity=1,
    ):
        if price_type == "SMART_MARKET":
            quote = self.get_option_quote(symbol, option_key, option_type=option_type)
            price_info = self.get_price_from_quote(quote)
            price = price_info["s-mid"]
            price_type = "LIMIT"

        if preview_order is None:
            preview_order_by_id = self.preview_option_order(
                symbol=symbol,
                option_key=option_key,
                order_action=order_action,
                price_type=price_type,
                price=price,
                option_type=option_type,
                quantity=quantity,
            )

            for _order_id, _preview_order in preview_order_by_id.items():
                order_id = _order_id
                preview_order = _preview_order

            if len(preview_order_by_id) > 2:
                raise (ClientError("Can not handled multiple order from PreviewOrder"))

        preview_order_id = preview_order["PreviewOrderResponse"]["PreviewIds"][0][
            "previewId"
        ]
        order_id = self._generate_order_id()
        order_id = order_id or self._generate_order_id()
        account_id = self._selected_account_id

        expiry_year, expiry_month, expiry_day, strike_price = self._parse_option_key(
            option_key
        )

        place_option_order_payload = {
            "PlaceOrderRequest": {
                "orderType": "OPTN",
                "clientOrderId": order_id,
                "PreviewIds": [{"previewId": preview_order_id}],
                "Order": [
                    {
                        "allOrNone": "false",
                        "priceType": price_type,
                        "orderTerm": "GOOD_FOR_DAY",
                        "marketSession": "REGULAR",
                        "stopPrice": "",
                        "limitPrice": price,
                        "Instrument": [
                            {
                                "Product": {
                                    "securityType": "OPTN",
                                    "symbol": symbol,
                                    "callPut": option_type,
                                    "expiryDay": expiry_day,
                                    "expiryMonth": expiry_month,
                                    "expiryYear": expiry_year,
                                    "strikePrice": strike_price,
                                },
                                "orderAction": order_action,
                                "quantityType": "QUANTITY",
                                "quantity": quantity,
                            }
                        ],
                    }
                ],
            }
        }

        palce_order_endpoint = (
            f"https://{self._base_url_host}/v1/accounts/{account_id}/orders/place.json"
        )

        response = self._session.post(
            palce_order_endpoint, json=place_option_order_payload
        )
        order_info = self._parse_response(response)

        return order_info

    def cancel_order(self, order_id):
        account_id = self._selected_account_id

        cancel_order_payload = {"CancelOrderRequest": {"orderId": order_id}}

        cancel_order_endpoint = (
            f"https://{self._base_url_host}/v1/accounts/{account_id}/orders/cancel.json"
        )

        response = self._session.put(cancel_order_endpoint, json=cancel_order_payload)
        cancel_order_info = self._parse_response(response)

        return cancel_order_info

    def order_status(self, order_id):
        account_id = self._selected_account_id
        order_status_endpoint = f"https://{self._base_url_host}/v1/accounts/{account_id}/orders/{order_id}.json"
        response = self._session.get(order_status_endpoint)

        order_status_info = self._parse_response(response)

        return order_status_info


"""
Example client init and auth
"""
#  client = EtradeAPIClient(selected_account_id="<account_id>")
#  client.authorize_session()


"""
Buy call option with preview step
"""
#  print(client.get_stock_quote("TSLA"))
#  preview_order_by_id = client.preview_option_order(
#  symbol="TSLA",
#  option_key="2023-10-20 s240",
#  order_action="SELL_CLOSE",
#  )

#  print(preview_order_by_id)


#  for order_id, preview_order in preview_order_by_id.items():
#  order_info = client.place_option_order(
#  symbol="TSLA",
#  option_key="2023-10-20 s240",
#  price=1,
#  preview_order=preview_order,
#  order_action="SELL_CLOSE",
#  )

#  print(order_info)


"""
Buy call option without preview step
"""
#  client.place_option_order(
#  symbol="TSLA",
#  option_key="2023-10-20 s240",
#  price=1,
#  order_action="BUY_OPEN",
#  )

"""
Get Option Quote and prices
"""

#  quote = client.get_option_quote(
#  symbol="TSLA", option_key="2023-10-20 s240", option_type="CALL"
#  )
#  client.get_price_from_quote(quote)

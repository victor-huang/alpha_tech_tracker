"""
Fixture response dicts mirroring real TradeStation v3 API responses.
Used by unit tests — do not import in production code.
"""

accounts_response = {
    "Accounts": [
        {
            "AccountID": "123456",
            "Status": "Active",
            "Alias": "My Account",
            "Name": "123456MSA",
            "DisplayName": "123456MSA",
            "Type": "M",
            "TypeDescription": "Margin",
        }
    ]
}

balances_response = {
    "Balances": [
        {
            "AccountID": "123456",
            "CashBalance": "48000",
            "BuyingPower": "50000",
            "Equity": "52000",
            "RealTimeOptionBuyingPower": "50000",
            "DayTradingQualified": True,
            "PatternDayTrader": False,
        }
    ]
}

stock_quote_response = [
    {
        "Symbol": "TSLA",
        "Bid": 245.10,
        "Ask": 245.30,
        "Last": 245.20,
        "Volume": 12000000,
        "AssetType": "STOCK",
        "Error": None,
    }
]

option_quote_response = [
    {
        "Symbol": "TSLA  250420C00240000",
        "Bid": 10.20,
        "Ask": 10.60,
        "Last": 10.40,
        "Volume": 5000,
        "AssetType": "STOCKOPTION",
        "Error": None,
    }
]

# v3 search results use display name format ("TSLA 250417C240"), not padded OCC.
# ExpirationDate uses /Date(epoch_ms)/ format. OptionType is "Call"/"Put" (not "Calls"/"Puts").
option_search_response = [
    {
        "Name": "TSLA 250417C240",
        "Description": "TSLA Apr 17 2025 240 Call",
        "Category": "StockOption",
        "ExpirationDate": "/Date(1744848000000)/",
        "ExpirationType": "W",
        "OptionType": "Call",
        "StrikePrice": 240.0,
        "Root": "TSLA",
        "Underlying": "TSLA",
    },
    {
        "Name": "TSLA 250417C245",
        "Description": "TSLA Apr 17 2025 245 Call",
        "Category": "StockOption",
        "ExpirationDate": "/Date(1744848000000)/",
        "ExpirationType": "W",
        "OptionType": "Call",
        "StrikePrice": 245.0,
        "Root": "TSLA",
        "Underlying": "TSLA",
    },
    {
        "Name": "TSLA 250417P240",
        "Description": "TSLA Apr 17 2025 240 Put",
        "Category": "StockOption",
        "ExpirationDate": "/Date(1744848000000)/",
        "ExpirationType": "W",
        "OptionType": "Put",
        "StrikePrice": 240.0,
        "Root": "TSLA",
        "Underlying": "TSLA",
    },
]

# v3 order placement wraps the result in {"Orders": [...]}.
place_order_response = {
    "Orders": [
        {
            "OrderID": "207887821",
            "Error": "OK",
            "Message": "Order submitted",
        }
    ]
}

# v3 order status responses wrap orders in {"Orders": [...]} and store
# symbol/qty inside Legs[0] rather than at the top level.
orders_open_response = {
    "Orders": [
        {
            "AccountID": "123456",
            "OrderID": "207887821",
            "Status": "OPN",
            "Duration": "DAY",
            "LimitPrice": "10.50",
            "FilledPrice": "0",
            "OpenedDateTime": "2025-04-20T09:31:00Z",
            "Legs": [
                {
                    "Symbol": "TSLA 250420C240",
                    "QuantityOrdered": "1",
                    "ExecQuantity": "0",
                    "BuyOrSell": "Buy",
                }
            ],
        }
    ],
    "Errors": [],
}

orders_filled_response = {
    "Orders": [
        {
            "AccountID": "123456",
            "OrderID": "207887821",
            "Status": "FLL",
            "Duration": "DAY",
            "LimitPrice": "10.50",
            "FilledPrice": "10.50",
            "OpenedDateTime": "2025-04-20T09:31:00Z",
            "Legs": [
                {
                    "Symbol": "TSLA 250420C240",
                    "QuantityOrdered": "1",
                    "ExecQuantity": "1",
                    "BuyOrSell": "Buy",
                }
            ],
        }
    ],
    "Errors": [],
}

orders_cancelled_response = {
    "Orders": [
        {
            "AccountID": "123456",
            "OrderID": "207887821",
            "Status": "CAN",
            "Duration": "DAY",
            "LimitPrice": "10.50",
            "FilledPrice": "0",
            "OpenedDateTime": "2025-04-20T09:31:00Z",
            "Legs": [
                {
                    "Symbol": "TSLA 250420C240",
                    "QuantityOrdered": "1",
                    "ExecQuantity": "0",
                    "BuyOrSell": "Buy",
                }
            ],
        }
    ],
    "Errors": [],
}

cancel_order_response = {
    "OrderID": "207887821",
    "Message": "Cancel request submitted",
    "OrderStatus": "Ok",
}

"""
Fixture response dicts mirroring real TradeStation v2 API responses.
Used by unit tests — do not import in production code.
"""

accounts_response = [
    {
        "Alias": "My Account",
        "Key": 123456,
        "Name": "123456MSA",
        "DisplayName": "123456MSA",
        "Type": "M",
        "TypeDescription": "Margin",
        "Status": "A",
        "StatusDescription": "Active",
    }
]

balances_response = [
    {
        "Alias": "My Account",
        "Key": 123456,
        "Name": "123456MSA",
        "RealTimeBuyingPower": 50000.00,
        "RealTimeEquity": 52000.00,
        "BODNetCash": 48000.00,
        "RealTimeOptionBuyingPower": 50000.00,
        "DayTradingQualified": True,
        "PatternDayTrader": False,
    }
]

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

option_search_response = [
    {
        "Name": "TSLA  250417C00240000",
        "Description": "TSLA Apr 17 2025 240 Call",
        "Category": "StockOption",
        "ExpirationDate": "2025-04-17T00:00:00Z",
        "ExpirationType": "W",
        "OptionType": "Calls",
        "StrikePrice": 240.0,
        "Root": "TSLA",
        "Underlying": "TSLA",
    },
    {
        "Name": "TSLA  250417C00245000",
        "Description": "TSLA Apr 17 2025 245 Call",
        "Category": "StockOption",
        "ExpirationDate": "2025-04-17T00:00:00Z",
        "ExpirationType": "W",
        "OptionType": "Calls",
        "StrikePrice": 245.0,
        "Root": "TSLA",
        "Underlying": "TSLA",
    },
    {
        "Name": "TSLA  250417P00240000",
        "Description": "TSLA Apr 17 2025 240 Put",
        "Category": "StockOption",
        "ExpirationDate": "2025-04-17T00:00:00Z",
        "ExpirationType": "W",
        "OptionType": "Puts",
        "StrikePrice": 240.0,
        "Root": "TSLA",
        "Underlying": "TSLA",
    },
]

place_order_response = {
    "OrderID": "207887821",
    "Message": "Order submitted",
    "OrderStatus": "Ok",
}

orders_open_response = [
    {
        "AccountID": "123456",
        "OrderID": 207887821,
        "Symbol": "TSLA  250420C00240000",
        "AssetType": "OP",
        "Type": "Buy",
        "Status": "OPN",
        "StatusDescription": "Open",
        "Duration": "DAY",
        "Quantity": 1,
        "ExecuteQuantity": 0,
        "QuantityLeft": 1,
        "FilledPrice": 0.0,
        "LimitPrice": 10.50,
        "TimeStamp": "2025-04-20T09:31:00Z",
        "FilledCanceled": None,
        "CommissionFee": 0.0,
    }
]

orders_filled_response = [
    {
        "AccountID": "123456",
        "OrderID": 207887821,
        "Symbol": "TSLA  250420C00240000",
        "AssetType": "OP",
        "Type": "Buy",
        "Status": "FLL",
        "StatusDescription": "Filled",
        "Duration": "DAY",
        "Quantity": 1,
        "ExecuteQuantity": 1,
        "QuantityLeft": 0,
        "FilledPrice": 10.50,
        "LimitPrice": 10.50,
        "TimeStamp": "2025-04-20T09:31:00Z",
        "FilledCanceled": "2025-04-20T09:31:05Z",
        "CommissionFee": 0.65,
    }
]

orders_cancelled_response = [
    {
        "AccountID": "123456",
        "OrderID": 207887821,
        "Symbol": "TSLA  250420C00240000",
        "AssetType": "OP",
        "Type": "Buy",
        "Status": "CAN",
        "StatusDescription": "Canceled",
        "Duration": "DAY",
        "Quantity": 1,
        "ExecuteQuantity": 0,
        "QuantityLeft": 1,
        "FilledPrice": 0.0,
        "LimitPrice": 10.50,
        "TimeStamp": "2025-04-20T09:31:00Z",
        "FilledCanceled": "2025-04-20T09:32:00Z",
        "CommissionFee": 0.0,
    }
]

cancel_order_response = {
    "OrderID": "207887821",
    "Message": "Cancel request submitted",
    "OrderStatus": "Ok",
}

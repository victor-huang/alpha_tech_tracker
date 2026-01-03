# Alpaca Trading API Client

A Python client for trading stocks and options on Alpaca Markets, modeled after the EtradeAPIClient interface.

**Note:** This module is located at `alpha_tech_tracker/trade_api/alpaca_client/` (not `alpaca/`) to avoid naming conflicts with the installed `alpaca-py` package.

## Table of Contents

- [Features](#features)
- [Setup](#setup)
- [Authentication](#authentication)
- [Quick Start](#quick-start)
- [API Reference](#api-reference)
  - [Account Management](#account-management)
  - [Market Data](#market-data)
  - [Stock Trading](#stock-trading)
  - [Options Trading](#options-trading)
  - [Order Management](#order-management)
- [Testing](#testing)
- [Examples](#examples)

## Features

- Simple API key authentication (no OAuth required)
- Paper trading mode for risk-free testing
- Stock trading (market and limit orders)
- Options trading (calls and puts)
- Real-time market data for stocks and options
- Order management (place, cancel, status check)
- Compatible interface with EtradeAPIClient

## Setup

### Prerequisites

The required dependencies are already in your `requirements.txt`:

```
alpaca-py==0.43.2
```

If not installed, run:

```bash
pip install alpaca-py==0.43.2
```

### Getting API Keys

1. Sign up for an Alpaca account at [https://alpaca.markets](https://alpaca.markets)
2. Navigate to the API section in your dashboard
3. Generate API keys for paper trading or live trading
4. Save your API Key ID and Secret Key

## Authentication

Set your API credentials as environment variables:

```bash
export ALPACA_API_KEY="your_api_key_id"
export ALPACA_SECRET_KEY="your_secret_key"
```

Or pass them directly when initializing the client:

```python
from alpha_tech_tracker.trade_api.alpaca_client.client import AlpacaAPIClient

client = AlpacaAPIClient(
    api_key="your_api_key_id",
    secret_key="your_secret_key",
    is_paper_trading=True
)
```

## Quick Start

```python
from alpha_tech_tracker.trade_api.alpaca_client.client import AlpacaAPIClient

# Initialize client for paper trading
client = AlpacaAPIClient(is_paper_trading=True)

# Get account information
account = client.get_accounts()
print(f"Buying Power: ${account['buying_power']}")
print(f"Portfolio Value: ${account['portfolio_value']}")

# Get a stock quote
quote = client.get_stock_quote("TSLA")
bid = quote["QuoteResponse"]["QuoteData"][0]["All"]["bid"]
ask = quote["QuoteResponse"]["QuoteData"][0]["All"]["ask"]
print(f"TSLA - Bid: ${bid}, Ask: ${ask}")

# Place a limit order
order = client.place_stock_order(
    symbol="TSLA",
    quantity=1,
    side="BUY",
    order_type="LIMIT",
    limit_price=250.00
)
print(f"Order placed: {order['order_id']}")
```

## API Reference

### Account Management

#### `get_accounts()`

Get account information including cash, buying power, and portfolio value.

**Returns:**
```python
{
    "account_id": str,
    "account_type": str,
    "cash": float,
    "buying_power": float,
    "portfolio_value": float,
    "equity": float,
    "raw_response": Account  # Full Alpaca Account object
}
```

**Example:**
```python
account = client.get_accounts()
print(f"Available cash: ${account['cash']}")
print(f"Buying power: ${account['buying_power']}")
```

---

### Market Data

#### `get_stock_quote(symbols)`

Get real-time stock quotes for one or more symbols.

**Parameters:**
- `symbols` (str or list): Single symbol or list of symbols

**Returns:**
- Single symbol: Quote dictionary
- Multiple symbols: Dictionary with symbols as keys

**Example:**
```python
# Single quote
quote = client.get_stock_quote("TSLA")

# Multiple quotes
quotes = client.get_stock_quote(["TSLA", "AAPL", "MSFT"])
print(quotes["TSLA"]["QuoteResponse"]["QuoteData"][0]["All"]["bid"])
```

---

#### `get_option_quote(symbol, option_key, option_type="CALL")`

Get real-time option quotes.

**Parameters:**
- `symbol` (str): Underlying stock symbol
- `option_key` (str): Option key in format "YYYY-MM-DD s{strike}" (e.g., "2024-12-20 s240")
- `option_type` (str): "CALL" or "PUT" (default: "CALL")

**Returns:** Quote dictionary in Etrade-compatible format

**Example:**
```python
quote = client.get_option_quote(
    symbol="TSLA",
    option_key="2024-12-20 s240",
    option_type="CALL"
)
bid = quote["QuoteResponse"]["QuoteData"][0]["All"]["bid"]
ask = quote["QuoteResponse"]["QuoteData"][0]["All"]["ask"]
```

---

#### `get_options_contracts(underlying_symbol, expiration_date=None, option_type=None, strike_price_gte=None, strike_price_lte=None, limit=100)`

Search for available option contracts.

**Parameters:**
- `underlying_symbol` (str): Stock symbol
- `expiration_date` (str, optional): Filter by expiration date (YYYY-MM-DD)
- `option_type` (str, optional): "call" or "put"
- `strike_price_gte` (float, optional): Minimum strike price
- `strike_price_lte` (float, optional): Maximum strike price
- `limit` (int): Maximum contracts to return (default: 100)

**Returns:** List of contract dictionaries

**Example:**
```python
contracts = client.get_options_contracts(
    underlying_symbol="TSLA",
    option_type="call",
    strike_price_gte=200,
    strike_price_lte=300,
    limit=10
)

for contract in contracts:
    print(f"{contract['symbol']}: Strike ${contract['strike_price']}, "
          f"Exp: {contract['expiration_date']}")
```

---

#### `get_price_from_quote(quote, percentage_deviate_from_mid_point=-0.1, smallest_unit=0.05)`

Calculate smart mid-point price from a quote (useful for limit orders).

**Parameters:**
- `quote` (dict): Quote dictionary from `get_stock_quote()` or `get_option_quote()`
- `percentage_deviate_from_mid_point` (float): Percentage deviation from mid-point (default: -0.1)
  - Positive: Scale toward ask
  - Negative: Scale toward bid
- `smallest_unit` (float): Price rounding unit (default: 0.05)

**Returns:**
```python
{
    "bid": float,
    "ask": float,
    "mid": float,
    "s-mid": float  # Smart mid-point (recommended limit price)
}
```

**Example:**
```python
quote = client.get_stock_quote("TSLA")
price_info = client.get_price_from_quote(quote, percentage_deviate_from_mid_point=-0.05)
limit_price = price_info["s-mid"]  # Use this for limit orders
```

---

### Stock Trading

#### `place_stock_order(symbol, quantity, side="BUY", order_type="MARKET", limit_price=None, time_in_force="DAY")`

Place a stock order.

**Parameters:**
- `symbol` (str): Stock symbol
- `quantity` (float): Number of shares
- `side` (str): "BUY" or "SELL" (default: "BUY")
- `order_type` (str): "MARKET" or "LIMIT" (default: "MARKET")
- `limit_price` (float, optional): Required for LIMIT orders
- `time_in_force` (str): "DAY", "GTC", "IOC", "FOK" (default: "DAY")

**Returns:** Order dictionary with order details

**Example:**
```python
# Market order
market_order = client.place_stock_order(
    symbol="TSLA",
    quantity=10,
    side="BUY",
    order_type="MARKET"
)

# Limit order
limit_order = client.place_stock_order(
    symbol="TSLA",
    quantity=5,
    side="BUY",
    order_type="LIMIT",
    limit_price=245.50,
    time_in_force="GTC"
)

print(f"Order ID: {limit_order['order_id']}")
print(f"Status: {limit_order['status']}")
```

---

### Options Trading

#### `place_option_order(symbol, option_key, price=None, price_type="LIMIT", option_type="CALL", order_action="BUY_OPEN", quantity=1, ...)`

Place an option order.

**Parameters:**
- `symbol` (str): Underlying stock symbol
- `option_key` (str): Option key in format "YYYY-MM-DD s{strike}"
- `price` (float, optional): Limit price (required for LIMIT orders)
- `price_type` (str): "MARKET", "LIMIT", or "SMART_MARKET" (default: "LIMIT")
  - "SMART_MARKET": Automatically calculates smart mid-point price
- `option_type` (str): "CALL" or "PUT" (default: "CALL")
- `order_action` (str): "BUY_OPEN", "BUY_CLOSE", "SELL_OPEN", "SELL_CLOSE" (default: "BUY_OPEN")
- `quantity` (int): Number of contracts (default: 1)
- `order_id` (str, optional): Custom order ID
- `preview_order` (dict, optional): Unused (for Etrade compatibility)

**Returns:** Order dictionary with order details

**Example:**
```python
# Buy a call option with limit price
order = client.place_option_order(
    symbol="TSLA",
    option_key="2024-12-20 s240",
    price=1.50,
    option_type="CALL",
    order_action="BUY_OPEN",
    quantity=1
)

# Sell a put option using smart market pricing
order = client.place_option_order(
    symbol="AAPL",
    option_key="2024-12-20 s180",
    price_type="SMART_MARKET",  # Automatically calculates price
    option_type="PUT",
    order_action="SELL_CLOSE",
    quantity=2
)

print(f"Order ID: {order['order_id']}")
print(f"Limit Price: ${order['limit_price']}")
```

---

### Order Management

#### `order_status(order_id)`

Check the status of an order.

**Parameters:**
- `order_id` (str): Order ID returned from order placement

**Returns:**
```python
{
    "order_id": str,
    "client_order_id": str,
    "symbol": str,
    "quantity": float,
    "filled_qty": float,
    "side": str,
    "type": str,
    "status": str,  # "new", "filled", "partially_filled", "cancelled", etc.
    "limit_price": float or None,
    "stop_price": float or None,
    "filled_avg_price": float or None,
    "submitted_at": datetime,
    "filled_at": datetime or None,
    "cancelled_at": datetime or None,
    "expired_at": datetime or None,
    "raw_response": Order
}
```

**Example:**
```python
status = client.order_status(order_id="abc123")
print(f"Status: {status['status']}")
print(f"Filled: {status['filled_qty']}/{status['quantity']}")
if status['filled_avg_price']:
    print(f"Average fill price: ${status['filled_avg_price']}")
```

---

#### `cancel_order(order_id)`

Cancel an open order.

**Parameters:**
- `order_id` (str): Order ID to cancel

**Returns:**
```python
{
    "order_id": str,
    "status": "cancelled",
    "message": "Order cancelled successfully"
}
```

**Example:**
```python
result = client.cancel_order(order_id="abc123")
print(result["message"])
```

---

## Testing

Set up your environment:

```bash
# Set PYTHONPATH to project root
export PYTHONPATH=/path/to/alpha_tech_tracker

# Set your Alpaca paper trading credentials
export ALPACA_API_KEY="your_paper_api_key"
export ALPACA_SECRET_KEY="your_paper_secret_key"
```

Run the test suite:

```bash
# Run all Alpaca tests
PYTHONPATH=/path/to/alpha_tech_tracker python -m pytest tests/trade_api/alpaca_client/ -v

# Run specific test
PYTHONPATH=/path/to/alpha_tech_tracker python -m pytest tests/trade_api/alpaca_client/test_client.py::test_get_accounts -v

# Run with output
PYTHONPATH=/path/to/alpha_tech_tracker python -m pytest tests/trade_api/alpaca_client/test_client.py -v -s
```

**Notes:**
- Tests use paper trading mode by default, so they're safe to run without affecting real accounts
- Some option-related tests may be skipped if your paper account doesn't have options data access
- Make sure PYTHONPATH is set to the project root to avoid import errors

---

## Examples

### Complete Trading Workflow

```python
from alpha_tech_tracker.trade_api.alpaca_client.client import AlpacaAPIClient

# Initialize
client = AlpacaAPIClient(is_paper_trading=True)

# 1. Check account
account = client.get_accounts()
print(f"Available buying power: ${account['buying_power']}")

# 2. Research - Get quote
quote = client.get_stock_quote("TSLA")
price_info = client.get_price_from_quote(quote)
print(f"TSLA current bid/ask: ${price_info['bid']} / ${price_info['ask']}")

# 3. Place order with smart pricing
order = client.place_stock_order(
    symbol="TSLA",
    quantity=1,
    side="BUY",
    order_type="LIMIT",
    limit_price=price_info["s-mid"]  # Smart mid-point
)
order_id = order["order_id"]
print(f"Order placed: {order_id}")

# 4. Monitor order
import time
time.sleep(2)
status = client.order_status(order_id)
print(f"Order status: {status['status']}")

# 5. Cancel if not filled
if status['status'] != 'filled':
    client.cancel_order(order_id)
    print("Order cancelled")
```

### Options Trading Strategy

```python
# Find option contracts expiring soon with specific strikes
contracts = client.get_options_contracts(
    underlying_symbol="TSLA",
    option_type="call",
    strike_price_gte=240,
    strike_price_lte=260,
    limit=20
)

# Filter contracts expiring in the next week
from datetime import datetime, timedelta
target_date = datetime.now() + timedelta(days=7)

for contract in contracts:
    exp_date = datetime.strptime(contract['expiration_date'], '%Y-%m-%d')
    if abs((exp_date - target_date).days) <= 7:
        # Get quote for this option
        option_key = f"{contract['expiration_date']} s{contract['strike_price']}"
        quote = client.get_option_quote("TSLA", option_key, "CALL")

        price_info = client.get_price_from_quote(quote)
        print(f"Strike ${contract['strike_price']}: "
              f"Bid ${price_info['bid']}, Ask ${price_info['ask']}")

        # Place order if price is attractive
        if price_info['ask'] < 2.00:  # Example criteria
            order = client.place_option_order(
                symbol="TSLA",
                option_key=option_key,
                price=price_info['s-mid'],
                option_type="CALL",
                order_action="BUY_OPEN",
                quantity=1
            )
            print(f"Order placed: {order['order_id']}")
```

### Batch Quote Retrieval

```python
# Get quotes for multiple stocks efficiently
symbols = ["TSLA", "AAPL", "MSFT", "GOOGL", "AMZN"]
quotes = client.get_stock_quote(symbols)

for symbol, quote_data in quotes.items():
    quote = quote_data["QuoteResponse"]["QuoteData"][0]["All"]
    print(f"{symbol}: Bid ${quote['bid']:.2f}, Ask ${quote['ask']:.2f}")
```

---

## Error Handling

```python
from alpha_tech_tracker.trade_api.alpaca.client import (
    AlpacaAPIClient,
    APIError,
    APIInvalidArgumentError
)

try:
    client = AlpacaAPIClient(is_paper_trading=True)

    # This will raise an error if limit_price is missing
    order = client.place_stock_order(
        symbol="TSLA",
        quantity=1,
        side="BUY",
        order_type="LIMIT"  # Missing limit_price!
    )
except APIInvalidArgumentError as e:
    print(f"Invalid argument: {e.message}")
except APIError as e:
    print(f"API Error ({e.code}): {e.message}")
except Exception as e:
    print(f"Unexpected error: {e}")
```

---

## Differences from EtradeAPIClient

| Feature | Alpaca | Etrade |
|---------|--------|--------|
| Authentication | API Key | OAuth 1.0 |
| Paper Trading | Built-in | Sandbox environment |
| Preview Orders | Not available | Supported |
| Order Types | Market, Limit, Stop, Stop-Limit | Extended set |
| Option Format | OCC standard | Custom format |
| Authorization Flow | None needed | Manual browser flow |

---

## Tips

1. **Always use paper trading first**: Set `is_paper_trading=True` when testing
2. **Use smart pricing**: The `get_price_from_quote()` method helps you place orders between bid/ask
3. **Monitor orders**: Check order status before assuming fills
4. **Handle errors**: Always wrap API calls in try/except blocks
5. **Respect rate limits**: Alpaca has API rate limits; avoid excessive requests
6. **Options approval**: Ensure your account has options trading enabled

---

## Support & Resources

- [Alpaca Documentation](https://alpaca.markets/docs/)
- [Alpaca-py SDK Docs](https://alpaca.markets/sdks/python/)
- [Alpaca Community Forum](https://forum.alpaca.markets/)
- [API Status](https://status.alpaca.markets/)

---

## License

This client is part of the Alpha Tech Tracker project.

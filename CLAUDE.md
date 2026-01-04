# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Alpha Tech Tracker is an algorithmic trading system that tracks stock chart reversal patterns and executes automated trades using technical analysis. It supports multiple trading APIs (Alpaca and ETrade) and implements wave-based momentum strategies for options and stock trading.

## Development Setup

### Environment Variables

Required for ETrade API:
```bash
export ETRADE_API_KEY_ID="your_key"
export ETRADE_API_SECRET_KEY="your_secret"
```

Required for Alpaca API:
```bash
export ALPACA_API_KEY="your_key"
export ALPACA_SECRET_KEY="your_secret"
# Legacy (for alpaca_engine.py):
export ALPACA_KEY_ID="your_key"
export ALPACA_SECRET_KEY="your_secret"
```

### Running Tests

All tests should be run with PYTHONPATH set to the project root:

```bash
# Run all tests
PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker python -m pytest

# Run specific test file
PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker python -m pytest tests/test_tsla_buy_strategy.py

# Run specific test
PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker python -m pytest tests/test_tsla_buy_strategy.py::test_strategy_simulation -v

# Run with API credentials (for integration tests)
PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker \
  ALPACA_API_KEY="..." ALPACA_SECRET_KEY="..." \
  python -m pytest tests/trade_api/alpaca_client/ -v

# Run with output (includes print statements)
PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker python -m pytest tests/ -v -s
```

### Code Cleanup

Before committing, remove unused imports:
```bash
autoflake -i --remove-all-unused-imports <files>
```

## Architecture

### Core Components

**Strategy Layer** (`strategy.py`, `tsla_strategy.py`, `nvda_strategy.py`)
- Base `Strategy` class defines the interface for all trading strategies
- `SimpleStrategy` implements wave-based momentum trading with configurable triggers
- Strategies are stateful and manage their own portfolio, signals, and wave analysis
- Each strategy can run backtests via `simulate(start, end, use_saved_data, stream_data)`

**Trading Engines**
- `alpaca_engine.py` - Legacy Alpaca WebSocket streaming and historical data (uses ALPACA_KEY_ID/ALPACA_SECRET_KEY)
- `alpaca_py_engine.py` - Modern Alpaca data aggregation using alpaca-py SDK (`DataAggregator` class for streaming)
- `order_engine.py` - Order placement, tracking, and fulfillment logic

**Trade API Abstraction** (`alpha_tech_tracker/trade_api/`)
- `etrade/client.py` - ETrade OAuth client for stocks and options trading
- `alpaca_client/client.py` - Alpaca API client with ETrade-compatible interface
- Both clients implement the same interface: `get_stock_quote()`, `place_stock_order()`, `place_option_order()`, `order_status()`, `cancel_order()`, etc.
- The `alpaca_client` module is named this way (not `alpaca/`) to avoid conflicts with the installed `alpaca-py` package

**Portfolio & Position Management** (`portfolio.py`)
- `Portfolio` class tracks all positions (open/closed), P&L, and performance metrics
- `Position` class represents individual trades with open/close prices, timestamps, order IDs
- Supports both stock and option positions with strike prices and OSI keys

**Technical Analysis** (`technical_analysis.py`, `wave.py`, `signal.py`)
- `Wave` - Identifies and tracks price wave patterns (up/down movements)
- `Signal` - Generates buy/sell signals based on technical indicators
- Technical indicators include moving averages (20, 50, 100, 200 period), momentum, wave analysis

**Data Management**
- `stock_price_data_loader.py` - Loads historical price data
- `redis_client.py` - Redis integration for caching
- Market data saved to `market_data/` directory as JSON files

### Strategy Configuration

Strategies are highly configurable via parameters set in `__init__`:
- `buy_trigger_up_waves_ratio`, `buy_trigger_up_magnitude_ratio` - Entry thresholds
- `waves_loosing_steam_*` - Exit signal thresholds
- `maximum_position_loss` - Stop-loss limit
- `target_option_strike_price_delta`, `target_option_expiry` - Option selection
- `market_data_timeout` - Max seconds between data points before timeout

### Running Strategies

The `runner.py` script orchestrates strategy execution:
- Initializes trade API client (ETrade or Alpaca)
- Starts market data streaming via `DataAggregator.start_streaming_market_data()`
- Runs strategy simulation with threading for concurrent operations
- Maintains OAuth session keepalive for ETrade (sends periodic requests)
- Can run as daemon using `python -m alpha_tech_tracker.runner start|stop`

### Testing Strategy

Tests are organized by module:
- `tests/test_<module>.py` - Unit tests for individual modules
- `tests/trade_api/etrade/test_client.py` - ETrade API client tests
- `tests/trade_api/alpaca_client/test_client.py` - Alpaca API client tests
- Test strategies use `use_saved_data=False, stream_data=False` for backtesting historical periods

Unit tests use mocks/mocker.patch (no DB required). Backend tests can use real services for integration testing.

### Trade API Client Selection

Strategies accept a `trade_api_client` parameter in `__init__`:
```python
# ETrade (requires OAuth flow)
client = EtradeAPIClient(selected_account_id="...")
client.authorize_session()
strategy = SimpleStrategy(symbol="TSLA", trade_api_client=client)

# Alpaca (API key based, paper trading)
from alpha_tech_tracker.trade_api.alpaca_client.client import AlpacaAPIClient
client = AlpacaAPIClient(is_paper_trading=True)
strategy = SimpleStrategy(symbol="TSLA", trade_api_client=client)
```

### Data Flow

1. Market data streams in via `DataAggregator` (WebSocket) or historical API calls
2. Data aggregated into 5-minute bars and saved to `market_data/`
3. Strategy processes bars to identify waves and generate signals
4. Signals trigger order placement via `order_engine`
5. Orders executed through trade API client (ETrade or Alpaca)
6. Portfolio updated with positions and P&L tracking

## Key Implementation Notes

- Option keys use format "YYYY-MM-DD s{strike}" for Alpaca, e.g., "2024-12-20 s240"
- OSI keys for ETrade follow format: `{symbol}--{expiry}{C/P}{strike}`
- Strategies maintain state across multiple bar updates (not stateless)
- Wave analysis requires sufficient historical data (typically 200+ bars for moving averages)
- Backtests replay historical data chronologically to simulate real-time trading
- Real-time mode uses `stream_data=True` to process live market data

## Common Pitfalls

- Missing PYTHONPATH causes import errors - always set to project root
- ETrade OAuth tokens expire - use keepalive thread for long-running sessions
- Option contracts need proper account permissions (both ETrade and Alpaca)
- `alpaca_engine.py` vs `alpaca_py_engine.py` use different env var names
- The `alpaca_client` module name must not be changed to `alpaca` due to package conflicts

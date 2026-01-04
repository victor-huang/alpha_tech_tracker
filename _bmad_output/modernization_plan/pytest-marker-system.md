# Pytest Marker System for Alpha Tech Tracker

## Overview

A pytest marker system has been implemented to organize and selectively run tests based on their requirements and characteristics. This is particularly useful for managing tests that require API credentials or external service connections.

## Available Markers

The following custom markers are defined in `pytest.ini`:

- **`credentials`** - Tests requiring API credentials (Alpaca or ETrade)
- **`alpaca`** - Tests specifically requiring Alpaca API credentials
- **`etrade`** - Tests specifically requiring ETrade API credentials
- **`integration`** - Integration tests that connect to external services
- **`slow`** - Tests that take a long time to run

## Test Distribution

### Credential Tests (14 total)

**Alpaca Tests (10):** `tests/trade_api/alpaca_client/test_client.py`
- test_get_accounts
- test_get_stock_quote
- test_get_multiple_stock_quotes
- test_get_option_quote
- test_get_price_from_quote
- test_get_options_contracts
- test_place_stock_order
- test_place_option_order
- test_order_status
- test_cancel_order

**ETrade Tests (4):**
- `tests/trade_api/etrade/test_client.py`
  - test_get_stock_quote
  - test_get_accounts
- `tests/test_order_engine.py::TestETradeOrderEngine`
  - test_should_be_able_to_place_a_trade
  - test_sync_orders_should_update_order_status

### Non-Credential Tests (219)

All other tests can run without external API credentials.

## Default Behavior

**By default, pytest automatically skips credential tests!**

When you run `pytest tests/` without any `-m` marker flag, the conftest.py configuration automatically applies `-m "not credentials"` to skip tests requiring API credentials.

You'll see a friendly message:
```
💡 Skipping 14 credential tests (default behavior)
   To run credential tests only: pytest -m 'credentials'
   To run Alpaca tests only: pytest -m 'alpaca'
   To run ETrade tests only: pytest -m 'etrade'
   To run ALL tests: pytest -m 'core or credentials'
```

## Usage Examples

### Run core tests (default behavior - no credentials needed)
```bash
# These are equivalent:
pytest tests/
python -m pytest tests/
PYTHONPATH=. pytest tests/ -v
```

**Result:** 209 passed, 10 skipped, 14 deselected (credential tests auto-skipped)

### Run only Alpaca tests
```bash
PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker \
  ALPACA_API_KEY="..." ALPACA_SECRET_KEY="..." \
  python -m pytest tests/ -m "alpaca" -v
```

**Result:** Runs 10 Alpaca-specific tests

### Run only ETrade tests
```bash
PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker \
  ETRADE_API_KEY_ID="..." ETRADE_API_SECRET_KEY="..." \
  python -m pytest tests/ -m "etrade" -v
```

**Result:** Runs 4 ETrade-specific tests

### Run all credential tests
```bash
PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker \
  ALPACA_API_KEY="..." ALPACA_SECRET_KEY="..." \
  ETRADE_API_KEY_ID="..." ETRADE_API_SECRET_KEY="..." \
  python -m pytest tests/ -m "credentials" -v
```

**Result:** Runs all 14 credential-requiring tests

### Run ALL tests (including credentials)
```bash
# Explicitly include both credential and non-credential tests
PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker \
  ALPACA_API_KEY="..." ALPACA_SECRET_KEY="..." \
  ETRADE_API_KEY_ID="..." ETRADE_API_SECRET_KEY="..." \
  python -m pytest tests/ -m "" -v
```

**Note:** Using `-m ""` (empty marker expression) bypasses the default filtering and runs all 233 tests.

### List tests without running them
```bash
# Show all non-credential tests
python -m pytest tests/ -m "not credentials" --co -q

# Show only Alpaca tests
python -m pytest tests/ -m "alpaca" --co -q

# Show only ETrade tests
python -m pytest tests/ -m "etrade" --co -q
```

## Benefits

1. **CI/CD Optimization** - Run non-credential tests in CI without managing secrets
2. **Focused Testing** - Test specific API integrations in isolation
3. **Faster Development** - Skip slow/credential tests during rapid iteration
4. **Clear Organization** - Easy identification of test requirements
5. **Documentation** - Self-documenting test categorization

## Implementation Details

### Configuration Files

#### `pytest.ini` - Marker Definitions

```ini
[pytest]
# Custom markers for test categorization
markers =
    core: Core tests that don't require external credentials (runs by default)
    credentials: Tests requiring API credentials (Alpaca or ETrade)
    alpaca: Tests requiring Alpaca API credentials
    etrade: Tests requiring ETrade API credentials
    integration: Integration tests that connect to external services
    slow: Tests that take a long time to run

# Default test paths
testpaths = tests

# Additional options
addopts =
    --strict-markers
    --verbose
    --color=yes
```

The `--strict-markers` option ensures that only defined markers can be used, preventing typos.

#### `conftest.py` - Default Behavior Configuration

The `conftest.py` file at the project root implements automatic credential test skipping:

```python
def pytest_configure(config):
    """Configure pytest to skip credential tests by default."""
    # Check if -m flag was explicitly provided in command line
    marker_provided = any(arg.startswith("-m") for arg in sys.argv)

    # If no marker flag was provided, default to excluding credential tests
    if not marker_provided:
        config.option.markexpr = "not credentials"
```

This hook automatically adds `-m "not credentials"` when no explicit marker is provided, creating a developer-friendly default behavior.

### Adding Markers to Tests

Markers are added using pytest decorators:

```python
import pytest

@pytest.mark.alpaca
@pytest.mark.credentials
def test_get_accounts():
    client = AlpacaAPIClient(is_paper_trading=True)
    account_info = client.get_accounts()
    assert account_info is not None
```

For test classes:

```python
class TestETradeOrderEngine:
    @pytest.mark.etrade
    @pytest.mark.credentials
    @pytest.mark.integration
    def test_should_be_able_to_place_a_trade(self):
        # test implementation
        pass
```

## Current Test Results

When running with default configuration (auto-applies `"not credentials"`):
- ✅ 209 tests passed
- ⏭️ 10 tests skipped (missing data files, data persistence tests, strategy tuning tests, streaming tests)
- 🚫 14 tests deselected (credential tests)
- ⚠️ 3 warnings (deprecation warnings, non-critical)
- ⚡ **Test suite runs in ~4 seconds** (down from ~68 seconds)

### Tests Skipped to Prevent Side Effects or for Performance
- `test_export_data` - Rewrites test data files in test_data/
- `test_save_ticker_min_agg_to_json` - Appends to market_data/amzn_min_aggs
- `test_strategy_simulation` (AMZN) - Lengthy backtest for strategy tuning (~10 months of data)
- `test_strategy_simulation` (TSLA) - Lengthy backtest for strategy tuning (~multiple historical scenarios)
- `test_detect_moving_average_trend` - Missing test data file (regn.csv)
- Streaming tests that require market to be open

## Future Enhancements

Potential additional markers to consider:
- `@pytest.mark.realtime` - Tests that stream live market data
- `@pytest.mark.requires_market_hours` - Tests that need market to be open
- `@pytest.mark.paper_trading` - Tests that use paper trading accounts
- `@pytest.mark.sandbox` - Tests that use sandbox/demo environments

# Testing Guide

## Quick Start

```bash
# Run all core tests (no credentials needed) - DEFAULT BEHAVIOR
pytest tests/

# Run with specific markers
pytest tests/ -m "credentials"  # Only credential tests
pytest tests/ -m "alpaca"        # Only Alpaca tests
pytest tests/ -m "etrade"        # Only ETrade tests

# Run ALL tests (including credentials)
pytest tests/ -m ""              # Empty marker expression
```

## Default Behavior

**Credential tests are automatically skipped by default!**

When you run `pytest tests/` without any `-m` marker flag, credential-requiring tests are automatically skipped. You'll see:

```
💡 Skipping 14 credential tests (default behavior)
   To run credential tests only: pytest -m 'credentials'
   To run Alpaca tests only: pytest -m 'alpaca'
   To run ETrade tests only: pytest -m 'etrade'
   To run ALL tests: pytest -m 'core or credentials'
```

## Test Markers

- **`credentials`** - Tests requiring API credentials (auto-skipped by default)
- **`alpaca`** - Tests requiring Alpaca API (10 tests)
- **`etrade`** - Tests requiring ETrade API (4 tests)
- **`integration`** - Integration tests with external services
- **`slow`** - Long-running tests
- **`core`** - Core tests (documentation marker)

## Running Tests with Environment Setup

### Core Tests (Default)
```bash
PYTHONPATH=. TWILIO_ACCOUNT_ID="test" TWILIO_AUTH_TOKEN="test" pytest tests/ -v
```

### Alpaca Tests
```bash
PYTHONPATH=. \
  ALPACA_API_KEY="your_key" \
  ALPACA_SECRET_KEY="your_secret" \
  pytest tests/ -m "alpaca" -v
```

### ETrade Tests
```bash
PYTHONPATH=. \
  ETRADE_API_KEY_ID="your_key" \
  ETRADE_API_SECRET_KEY="your_secret" \
  pytest tests/ -m "etrade" -v
```

### All Credential Tests
```bash
PYTHONPATH=. \
  ALPACA_API_KEY="..." ALPACA_SECRET_KEY="..." \
  ETRADE_API_KEY_ID="..." ETRADE_API_SECRET_KEY="..." \
  pytest tests/ -m "credentials" -v
```

## Test Results Summary

When running core tests (default):
- ✅ 211 tests passed
- ⏭️ 8 tests skipped (missing data files, data persistence tests, etc.)
- 🚫 14 tests deselected (credential tests)

Total test suite: 233 tests

### Skipped Tests (By Default)
Tests that write to data files are skipped to prevent side effects:
- `test_export_data` - Rewrites test data files
- `test_save_ticker_min_agg_to_json` - Appends to market_data/amzn_min_aggs
- Streaming tests requiring open market hours

## Common Commands

```bash
# List tests without running
pytest tests/ --collect-only

# Run specific test file
pytest tests/test_portfolio.py -v

# Run specific test
pytest tests/test_portfolio.py::test_create_an_instance_of_portfolio -v

# Run with output (show print statements)
pytest tests/ -v -s

# Run with minimal output
pytest tests/ -q

# Stop on first failure
pytest tests/ -x

# Show local variables on failure
pytest tests/ -l
```

## Adding New Tests

### Unit Tests
Place in `tests/unit/` - these should not require credentials or external services.

### Integration Tests
Place in `tests/trade_api/alpaca_client/` or `tests/trade_api/etrade/` and add markers:

```python
import pytest

@pytest.mark.alpaca
@pytest.mark.credentials
@pytest.mark.integration
def test_my_alpaca_integration():
    # test code
    pass
```

### Test Classes
```python
class TestMyFeature:
    @pytest.mark.credentials
    @pytest.mark.alpaca
    def test_scenario_one(self):
        # test code
        pass
```

## Configuration Files

- **`pytest.ini`** - Marker definitions and pytest configuration
- **`conftest.py`** - Automatic credential test skipping logic
- **`tests/unit/`** - Pure unit tests (no external dependencies)
- **`tests/trade_api/`** - API integration tests

## CI/CD Usage

For CI/CD pipelines, use the default behavior to skip credential tests:

```yaml
# .github/workflows/test.yml
- name: Run tests
  run: |
    pytest tests/ -v
  env:
    PYTHONPATH: .
    TWILIO_ACCOUNT_ID: test
    TWILIO_AUTH_TOKEN: test
```

Only 212 core tests will run, credential tests are automatically skipped.

## Troubleshooting

### "AttributeError: No such file or directory"
Make sure PYTHONPATH is set:
```bash
PYTHONPATH=. pytest tests/
```

### "ValueError: ENVs TWILIO_ACCOUNT_ID and TWILIO_AUTH_TOKEN must be set"
Set dummy values for tests:
```bash
TWILIO_ACCOUNT_ID="test" TWILIO_AUTH_TOKEN="test" pytest tests/
```

### Credential tests running when they shouldn't
Check that you're not using `-m` flag. Default behavior only works without explicit markers.

### Need to run ALL tests
Use empty marker expression:
```bash
pytest tests/ -m ""
```

## More Information

See `_bmad_output/pytest-marker-system.md` for detailed documentation about the marker system implementation.

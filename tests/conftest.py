"""
Pytest configuration and fixtures for Alpha Tech Tracker tests.

This file provides shared fixtures and configurations for all tests,
including mocks for external API clients to enable testing without credentials.
"""

import json
import os
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pandas as pd
import pytest


# ============================================================================
# Test Data Directory
# ============================================================================

@pytest.fixture
def test_data_dir():
    """Return path to test data directory."""
    return Path(__file__).parent / "test_data"


# ============================================================================
# Mock Alpaca Clients (for tests that import alpaca_engine/alpaca_py_engine)
# ============================================================================

@pytest.fixture(autouse=True)
def mock_alpaca_clients_on_import(monkeypatch):
    """
    Mock Alpaca client initialization at module level.

    This fixture runs automatically for all tests and prevents both:
    - New API: StockHistoricalDataClient and StockDataStream (alpaca_py_engine.py)
    - Old API: tradeapi.REST (alpaca_engine.py - deprecated)
    from requiring credentials during module import.
    """
    # Set dummy environment variables if not present
    if not os.environ.get("ALPACA_KEY_ID"):
        monkeypatch.setenv("ALPACA_KEY_ID", "test_key_id")
    if not os.environ.get("ALPACA_SECRET_KEY"):
        monkeypatch.setenv("ALPACA_SECRET_KEY", "test_secret_key")

    # Mock the new API client classes (alpaca_py_engine.py)
    mock_stock_client = MagicMock()
    mock_wss_client = MagicMock()

    # Mock the old API client class (alpaca_engine.py - deprecated)
    mock_rest_api = MagicMock()
    mock_rest_api.polygon.historic_agg.return_value.df = pd.DataFrame({
        "open": [100.0],
        "high": [101.0],
        "low": [99.0],
        "close": [100.5],
        "volume": [1000]
    })

    with patch("alpha_tech_tracker.alpaca_py_engine.StockHistoricalDataClient", return_value=mock_stock_client):
        with patch("alpha_tech_tracker.alpaca_py_engine.StockDataStream", return_value=mock_wss_client):
            # Also mock the deprecated alpaca-trade-api REST client
            with patch("alpha_tech_tracker.alpaca_engine.tradeapi.REST", return_value=mock_rest_api):
                yield {
                    "stock_client": mock_stock_client,
                    "wss_client": mock_wss_client,
                    "rest_api": mock_rest_api,
                }


# ============================================================================
# Sample Market Data Fixtures
# ============================================================================

@pytest.fixture
def sample_stock_bars():
    """
    Return sample stock bar data as a pandas DataFrame.

    Generates realistic intraday data that can trigger trading signals.
    Includes enough data points for moving average calculations (200+ bars).
    """
    # Generate 2 weeks of 5-minute bars (9:30-16:00 = 78 bars/day * 10 days = 780 bars)
    periods = 780
    start_date = pd.Timestamp("2023-01-03 09:30", tz="America/New_York")

    # Create timestamps for market hours only (9:30-16:00)
    timestamps = []
    current = start_date
    while len(timestamps) < periods:
        # Add bars during market hours
        if current.hour >= 9 and (current.hour < 16 or (current.hour == 16 and current.minute == 0)):
            if not (current.hour == 9 and current.minute < 30):  # Skip before 9:30
                timestamps.append(current)
        current += pd.Timedelta(minutes=5)
        # Skip to next day at 16:00
        if current.hour >= 16:
            current = current.replace(hour=9, minute=30) + pd.Timedelta(days=1)
            # Skip weekends
            while current.weekday() >= 5:
                current += pd.Timedelta(days=1)

    timestamps = timestamps[:periods]

    # Generate price data with realistic patterns (trending + volatility)
    base_price = 1000.0
    trend = 0.0005  # Slight upward trend
    volatility = 0.01

    import numpy as np
    np.random.seed(42)  # For reproducibility

    prices = []
    current_price = base_price
    for i in range(periods):
        # Add trend and random walk
        change = current_price * (trend + volatility * np.random.randn())
        current_price += change
        prices.append(current_price)

    # Create OHLC data
    data = {
        "timestamp": timestamps,
        "open": prices,
        "high": [p * (1 + abs(volatility * np.random.rand())) for p in prices],
        "low": [p * (1 - abs(volatility * np.random.rand())) for p in prices],
        "close": [p * (1 + volatility * np.random.randn() * 0.5) for p in prices],
        "volume": [int(1000000 * (1 + 0.5 * np.random.rand())) for _ in prices],
    }

    df = pd.DataFrame(data)
    df.set_index("timestamp", inplace=True)
    return df


@pytest.fixture
def sample_quote_response():
    """Return sample quote response matching Alpaca format."""
    return {
        "QuoteResponse": {
            "QuoteData": [
                {
                    "All": {
                        "bid": 100.50,
                        "ask": 100.55,
                        "last": 100.52,
                        "volume": 1000000,
                    }
                }
            ]
        }
    }


@pytest.fixture
def sample_account_info():
    """Return sample account information."""
    return {
        "account_id": "test-account-123",
        "buying_power": "10000.00",
        "portfolio_value": "25000.00",
        "cash": "10000.00",
        "equity": "25000.00",
    }


# ============================================================================
# Mock Historical Data Function
# ============================================================================

@pytest.fixture
def mock_get_historical_stock_data(sample_stock_bars):
    """
    Mock the get_historical_stock_data function to return sample data.

    This prevents tests from making actual API calls.
    """
    with patch("alpha_tech_tracker.alpaca_py_engine.get_historical_stock_data") as mock:
        mock.return_value = sample_stock_bars
        yield mock


@pytest.fixture
def mock_historical_data_function(sample_stock_bars):
    """
    Alternative name for mock_get_historical_stock_data for clarity.
    """
    with patch("alpha_tech_tracker.alpaca_py_engine.get_historical_stock_data") as mock:
        mock.return_value = sample_stock_bars
        yield mock


# ============================================================================
# Static Test Data Loaders
# ============================================================================

@pytest.fixture
def load_test_data_json():
    """
    Factory fixture to load JSON test data files.

    Usage:
        def test_something(load_test_data_json):
            data = load_test_data_json("NVDA_2019-12-01_2020-01-15.json")
    """
    def _load(filename):
        test_data_path = Path(__file__).parent / "test_data" / filename
        if not test_data_path.exists():
            pytest.skip(f"Test data file not found: {filename}")
        with open(test_data_path, "r") as f:
            return json.load(f)
    return _load


@pytest.fixture
def load_test_data_csv():
    """
    Factory fixture to load CSV test data files.

    Usage:
        def test_something(load_test_data_csv):
            df = load_test_data_csv("eog_down_wave.csv")
    """
    def _load(filename):
        test_data_path = Path(__file__).parent / "test_data" / filename
        if not test_data_path.exists():
            pytest.skip(f"Test data file not found: {filename}")
        return pd.read_csv(test_data_path)
    return _load


# ============================================================================
# Strategy Testing Fixtures
# ============================================================================

@pytest.fixture
def mock_strategy_dependencies(sample_stock_bars, sample_account_info):
    """
    Mock all external dependencies for strategy testing.

    This allows strategy tests to run without:
    - API credentials
    - Network calls
    - External data providers
    """
    mocks = {}

    # Mock historical data fetching
    with patch("alpha_tech_tracker.alpaca_py_engine.get_historical_stock_data") as mock_hist:
        mock_hist.return_value = sample_stock_bars
        mocks["historical_data"] = mock_hist

        # Mock account info
        with patch("alpha_tech_tracker.trade_api.alpaca_client.client.AlpacaAPIClient") as mock_client_class:
            mock_client = MagicMock()
            mock_client.get_accounts.return_value = sample_account_info
            mock_client_class.return_value = mock_client
            mocks["api_client"] = mock_client

            yield mocks


# ============================================================================
# Decimal Precision Helpers
# ============================================================================

@pytest.fixture
def assert_decimal_equal():
    """
    Helper to assert Decimal equality with tolerance.

    Usage:
        def test_calculation(assert_decimal_equal):
            result = Decimal("10.12345")
            expected = Decimal("10.123")
            assert_decimal_equal(result, expected, places=2)
    """
    def _assert(actual, expected, places=2):
        tolerance = Decimal(10) ** -places
        assert abs(actual - expected) < tolerance, f"{actual} != {expected} (within {places} places)"
    return _assert


# ============================================================================
# Environment Variable Management
# ============================================================================

@pytest.fixture
def clean_env(monkeypatch):
    """
    Provide a clean environment for tests.

    Removes Alpaca credentials from environment to ensure
    tests don't accidentally use real API keys.
    """
    # Remove real credentials if present
    for key in ["ALPACA_KEY_ID", "ALPACA_SECRET_KEY", "ALPACA_API_KEY"]:
        monkeypatch.delenv(key, raising=False)

    # Set test credentials
    monkeypatch.setenv("ALPACA_KEY_ID", "test_key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "test_secret")

    yield


# ============================================================================
# Pytest Configuration Hooks
# ============================================================================

def pytest_configure(config):
    """Configure pytest with custom markers."""
    # Markers are already defined in pytest.ini, but we can add runtime config here if needed
    pass


def pytest_collection_modifyitems(config, items):
    """
    Modify test collection to add automatic markers or skips.

    This runs after test collection and can be used to:
    - Add markers automatically based on test location
    - Skip tests based on conditions
    - Modify test execution order
    """
    # Markers are now defined in pytest.ini, no need to add dynamically
    pass

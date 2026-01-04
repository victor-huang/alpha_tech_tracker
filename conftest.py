"""
Pytest configuration for Alpha Tech Tracker.

This file configures pytest to automatically skip credential-requiring tests
unless explicitly requested via markers.
"""

import pytest
import sys


def pytest_configure(config):
    """Configure pytest to skip credential tests by default."""
    # Check if -m flag was explicitly provided in command line
    marker_provided = any(arg.startswith("-m") for arg in sys.argv)

    # If no marker flag was provided, default to excluding credential tests
    if not marker_provided:
        config.option.markexpr = "not credentials"


def pytest_collection_modifyitems(config, items):
    """
    Modify test collection to add skip markers as needed.

    This hook runs after test collection and can be used to add markers
    or modify test items before they are executed.
    """
    # Get the marker expression being used
    markexpr = config.option.markexpr if hasattr(config.option, "markexpr") else ""

    # If running with default settings (auto-applied "not credentials"),
    # inform user that credential tests are being skipped
    if markexpr == "not credentials":
        # Check if this was auto-applied (not explicitly provided)
        marker_provided = any(arg.startswith("-m") for arg in sys.argv)
        if not marker_provided:
            # Count credential tests
            credential_tests = [item for item in items if item.get_closest_marker("credentials")]
            # Check if quiet mode is enabled (handle cases where attribute doesn't exist)
            is_quiet = getattr(config.option, "quiet", False) or getattr(config.option, "verbose", 0) < 0
            if credential_tests and not is_quiet:
                print(f"\n💡 Skipping {len(credential_tests)} credential tests (default behavior)")
                print("   To run credential tests only: pytest -m 'credentials'")
                print("   To run Alpaca tests only: pytest -m 'alpaca'")
                print("   To run ETrade tests only: pytest -m 'etrade'")
                print("   To run ALL tests: pytest -m 'core or credentials'")

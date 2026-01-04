import pytest
from alpha_tech_tracker.redis_client import redis_client


def test_redis_client():
    """Test Redis client connection. Skipped if Redis is not available."""
    try:
        # Try to ping Redis to check if it's available
        redis_client.ping()
    except Exception as e:
        pytest.skip(f"Redis not available: {e}")

    assert redis_client.get("__asdf__") == None

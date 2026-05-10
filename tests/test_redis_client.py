import pytest
from alpha_tech_tracker.redis_client import redis_client


@pytest.mark.integration
def test_redis_client():
    redis_client.ping()
    assert redis_client.get("__asdf__") == None

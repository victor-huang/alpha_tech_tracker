import ipdb

from alpha_tech_tracker.redis_client import redis_client

def test_redis_client():
    assert redis_client.get('__asdf__') == None

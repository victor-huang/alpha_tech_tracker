import json

import redis

host = 'localhost'
port = 6379
db = 0

#  redis_client = redis.Redis(host=host, port=port, db=db)

def init_client():
    return redis_client

def set_object(key, obj):
    redis_client

class RedisClient(redis.Redis):
    def set_object(self, key, obj):
        super().set(key, json.dumps(obj))

    def get_object(self, key):
        json_obj_str = super().get(key)

        return json.loads(json_obj_str)

redis_client = RedisClient(host=host, port=port, db=db)

init_client()



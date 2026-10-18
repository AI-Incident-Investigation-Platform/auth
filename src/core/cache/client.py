from redis.asyncio import Redis


class CacheClient:
    def __init__(self, connection: Redis) -> None:
        self._connection = connection

    def connection(self) -> Redis:
        return self._connection

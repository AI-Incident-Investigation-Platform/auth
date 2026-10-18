from collections.abc import Collection

from redis.exceptions import RedisError

from src.core.cache.client import CacheClient
from src.core.cache.exc import CacheUnavailableError


class CacheService:
    def __init__(self, client: CacheClient) -> None:
        self._client = client

    async def set_flags(self, keys: Collection[str], ttl_seconds: int) -> None:
        if not keys:
            return
        try:
            async with self._client.connection().pipeline(transaction=False) as pipeline:
                for key in keys:
                    pipeline.set(key, 1, ex=ttl_seconds)
                await pipeline.execute()
        except RedisError as exc:
            raise CacheUnavailableError from exc

    async def exists(self, key: str) -> bool:
        try:
            return bool(await self._client.connection().exists(key))
        except RedisError as exc:
            raise CacheUnavailableError from exc

    async def ping(self) -> None:
        try:
            await self._client.connection().ping()
        except RedisError as exc:
            raise CacheUnavailableError from exc

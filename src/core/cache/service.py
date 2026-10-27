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

    async def delete(self, keys: Collection[str]) -> None:
        if not keys:
            return
        try:
            await self._client.connection().delete(*keys)
        except RedisError as exc:
            raise CacheUnavailableError from exc

    async def exists(self, key: str) -> bool:
        try:
            return bool(await self._client.connection().exists(key))
        except RedisError as exc:
            raise CacheUnavailableError from exc

    async def set_value(self, key: str, value: str, ttl_seconds: int) -> None:
        try:
            await self._client.connection().set(key, value, ex=ttl_seconds)
        except RedisError as exc:
            raise CacheUnavailableError from exc

    async def replace_value(self, key: str, value: str) -> bool:
        """Перезаписывает значение существующего ключа, не трогая срок жизни; нет ключа — False."""
        try:
            return bool(await self._client.connection().set(key, value, xx=True, keepttl=True))
        except RedisError as exc:
            raise CacheUnavailableError from exc

    async def get_value(self, key: str) -> str | None:
        try:
            value = await self._client.connection().get(key)
        except RedisError as exc:
            raise CacheUnavailableError from exc
        return value.decode() if isinstance(value, bytes) else value

    async def delete_one(self, key: str) -> bool:
        """Удаляет ключ; True только у того из параллельных вызовов, который его удалил."""
        try:
            return bool(await self._client.connection().delete(key))
        except RedisError as exc:
            raise CacheUnavailableError from exc

    async def increment(self, key: str, ttl_seconds: int) -> tuple[int, int]:
        """Атомарно увеличивает счётчик; срок жизни ставится при создании.

        Returns:
            Новое значение и сколько секунд осталось жить счётчику.
        """
        try:
            async with self._client.connection().pipeline(transaction=True) as pipeline:
                pipeline.incr(key)
                pipeline.expire(key, ttl_seconds, nx=True)
                pipeline.ttl(key)
                count, _, ttl = await pipeline.execute()
        except RedisError as exc:
            raise CacheUnavailableError from exc
        return int(count), int(ttl)

    async def ping(self) -> None:
        try:
            await self._client.connection().ping()
        except RedisError as exc:
            raise CacheUnavailableError from exc

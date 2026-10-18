from collections.abc import AsyncIterator

from dishka import Provider, Scope, provide
from redis.asyncio import Redis

from src.config import cfg
from src.core.cache.client import CacheClient
from src.core.cache.service import CacheService


class CacheProvider(Provider):
    cache_client = provide(CacheClient, scope=Scope.APP)
    cache_service = provide(CacheService, scope=Scope.APP)

    @provide(scope=Scope.APP)
    async def get_connection(self) -> AsyncIterator[Redis]:
        connection = Redis.from_url(
            cfg.cache.url,
            socket_timeout=cfg.cache.timeout_seconds,
            socket_connect_timeout=cfg.cache.timeout_seconds,
        )
        yield connection
        await connection.aclose()

from collections.abc import AsyncIterator

import httpx
from dishka import Provider, Scope, provide

from src.config import cfg
from src.core.registry.client import ConsulClient
from src.core.registry.service import RegistryService


class RegistryProvider(Provider):
    consul_client = provide(ConsulClient, scope=Scope.APP)
    registry_service = provide(RegistryService, scope=Scope.APP)

    @provide(scope=Scope.APP)
    async def get_http_client(self) -> AsyncIterator[httpx.AsyncClient]:
        async with httpx.AsyncClient(
            base_url=cfg.registry.consul_url, timeout=cfg.registry.timeout_seconds
        ) as client:
            yield client

from src.core.cache.service import CacheService
from src.core.db.uow import UnitOfWork


class HealthService:
    def __init__(self, uow: UnitOfWork, cache: CacheService) -> None:
        self._uow = uow
        self._cache = cache

    async def check_ready(self) -> None:
        await self._uow.ping()
        await self._cache.ping()

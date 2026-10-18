from collections.abc import Collection
from uuid import UUID

from src.config import cfg
from src.core.cache.service import CacheService


class SessionRevocationList:
    def __init__(self, cache: CacheService) -> None:
        self._cache = cache

    async def revoke(self, session_ids: Collection[UUID]) -> None:
        await self._cache.set_flags(
            [self._key(session_id) for session_id in session_ids],
            ttl_seconds=cfg.auth.access_token_ttl_minutes * 60,
        )

    async def is_revoked(self, session_id: UUID) -> bool:
        return await self._cache.exists(self._key(session_id))

    @staticmethod
    def _key(session_id: UUID) -> str:
        return f"{cfg.cache.key_prefix}revoked:session:{session_id}"

from collections.abc import Collection
from uuid import UUID

from src.config import cfg
from src.core.cache.service import CacheService


class LiveSessions:
    """Пропуска живых сессий в кэше: по ним любой сервис мгновенно видит отзыв.

    Хранится список живых, а не отозванных: кэш может вытеснить ключ, и тогда
    запрос получит 401 и восстановит пропуск через refresh, а не пропустит
    отозванный токен. Ключ живёт столько же, сколько access-токен, и
    выставляется заново при каждой его выдаче.
    """

    def __init__(self, cache: CacheService) -> None:
        self._cache = cache

    async def mark_live(self, session_id: UUID) -> None:
        await self._cache.set_flags(
            [self._key(session_id)], ttl_seconds=cfg.auth.access_token_ttl_minutes * 60
        )

    async def forget(self, session_ids: Collection[UUID]) -> None:
        await self._cache.delete([self._key(session_id) for session_id in session_ids])

    async def is_live(self, session_id: UUID) -> bool:
        return await self._cache.exists(self._key(session_id))

    @staticmethod
    def _key(session_id: UUID) -> str:
        return f"{cfg.cache.key_prefix}session:{session_id}"

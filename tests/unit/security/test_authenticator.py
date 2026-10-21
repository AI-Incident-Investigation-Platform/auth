from uuid import uuid7

import pytest
from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError

from src.core.cache.client import CacheClient
from src.core.cache.exc import CacheUnavailableError
from src.core.cache.service import CacheService
from src.core.security.dto import AccessTokenClaims
from src.core.security.live_sessions import LiveSessions
from src.core.security.service import SecurityService, SessionAuthenticator


@pytest.mark.case(id="AUTH-TOKEN-007")
async def test_unreachable_cache_rejects_valid_token(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = Redis(host="127.0.0.1", port=1)

    async def unreachable(*keys: str) -> int:
        raise RedisConnectionError("cache is down")

    monkeypatch.setattr(connection, "exists", unreachable)
    security = SecurityService()
    authenticator = SessionAuthenticator(
        security, LiveSessions(CacheService(CacheClient(connection)))
    )
    token = security.issue_access_token(AccessTokenClaims(user_id=uuid7(), session_id=uuid7()))

    with pytest.raises(CacheUnavailableError):
        await authenticator.authenticate(f"Bearer {token}", None)

import hashlib
import json
from datetime import datetime

from src.config import cfg
from src.core.cache.service import CacheService
from src.core.security.dto import OtpChallenge, SendCount


class OtpChallenges:
    """Challenge входа по коду в кэше: живёт не дольше otp_challenge_ttl_seconds.

    Попытки считаются отдельным счётчиком (INCR), поэтому параллельные догадки
    не обходят лимит. Использованный challenge удаляется, и только один из
    параллельных verify получает право открыть сессию.
    """

    def __init__(self, cache: CacheService) -> None:
        self._cache = cache

    async def save(self, challenge: OtpChallenge) -> None:
        await self._cache.set_value(
            self._key(challenge.challenge_id),
            self._dump(challenge),
            ttl_seconds=cfg.auth.otp_challenge_ttl_seconds,
        )

    async def get(self, challenge_id: str) -> OtpChallenge | None:
        raw = await self._cache.get_value(self._key(challenge_id))
        return self._load(challenge_id, raw) if raw is not None else None

    async def replace(self, challenge: OtpChallenge) -> bool:
        """Новый код для живого challenge; счётчик попыток начинается заново."""
        replaced = await self._cache.replace_value(
            self._key(challenge.challenge_id), self._dump(challenge)
        )
        if replaced:
            await self._cache.delete([self._attempts_key(challenge.challenge_id)])
        return replaced

    async def register_attempt(self, challenge_id: str) -> int:
        count, _ = await self._cache.increment(
            self._attempts_key(challenge_id), ttl_seconds=cfg.auth.otp_challenge_ttl_seconds
        )
        return count

    async def consume(self, challenge_id: str) -> bool:
        consumed = await self._cache.delete_one(self._key(challenge_id))
        await self._cache.delete([self._attempts_key(challenge_id)])
        return consumed

    async def delete(self, challenge_id: str) -> None:
        await self._cache.delete([self._key(challenge_id), self._attempts_key(challenge_id)])

    async def register_send(self, email: str) -> SendCount:
        email_hash = hashlib.sha256(email.encode()).hexdigest()
        count, ttl = await self._cache.increment(
            f"{cfg.cache.key_prefix}otp-sends:{email_hash}", ttl_seconds=3600
        )
        return SendCount(count=count, resets_in_seconds=ttl)

    @staticmethod
    def _key(challenge_id: str) -> str:
        return f"{cfg.cache.key_prefix}otp:{challenge_id}"

    @staticmethod
    def _attempts_key(challenge_id: str) -> str:
        return f"{cfg.cache.key_prefix}otp:{challenge_id}:attempts"

    @staticmethod
    def _dump(challenge: OtpChallenge) -> str:
        return json.dumps(
            {
                "email": challenge.email,
                "code_digest": challenge.code_digest,
                "code_expires_at": challenge.code_expires_at.isoformat(),
                "resend_available_at": challenge.resend_available_at.isoformat(),
                "resends": challenge.resends,
            }
        )

    @staticmethod
    def _load(challenge_id: str, raw: str) -> OtpChallenge:
        data = json.loads(raw)
        return OtpChallenge(
            challenge_id=challenge_id,
            email=str(data["email"]),
            code_digest=str(data["code_digest"]),
            code_expires_at=datetime.fromisoformat(data["code_expires_at"]),
            resend_available_at=datetime.fromisoformat(data["resend_available_at"]),
            resends=int(data["resends"]),
        )

import asyncio
import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey, RSAPublicKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    PublicFormat,
    load_pem_private_key,
)
from jwt.algorithms import RSAAlgorithm

from src.config import cfg
from src.core.security.dto import (
    AccessTokenClaims,
    CurrentUser,
    Jwk,
    RefreshToken,
)
from src.core.security.exc import (
    MalformedRefreshTokenError,
    NotAuthenticatedError,
    SigningKeyUnavailableError,
)
from src.core.security.live_sessions import LiveSessions


class SecurityService:
    def __init__(self) -> None:
        self._password_hasher = PasswordHasher()
        self._unknown_user_password_hash = self._password_hasher.hash(secrets.token_urlsafe(32))
        self._private_key = self._load_private_key(Path(cfg.auth.private_key_path))
        self._public_key: RSAPublicKey = self._private_key.public_key()
        self._key_id = hashlib.sha256(
            self._public_key.public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
        ).hexdigest()[:16]

    async def hash_password(self, password: str) -> str:
        return await asyncio.to_thread(self._password_hasher.hash, password)

    async def verify_password(self, password_hash: str | None, password: str) -> bool:
        """Сверяет пароль с хэшем; без хэша (нет такого пользователя) тратит то же время.

        Так по времени ответа на вход нельзя узнать, зарегистрирована ли почта.
        """
        if password_hash is None:
            await asyncio.to_thread(
                self._verify_password, self._unknown_user_password_hash, password
            )
            return False
        return await asyncio.to_thread(self._verify_password, password_hash, password)

    def issue_access_token(self, claims: AccessTokenClaims) -> str:
        now = datetime.now(UTC)
        payload = {
            "iss": cfg.service.name,
            "aud": cfg.auth.audience,
            "sub": str(claims.user_id),
            "sid": str(claims.session_id),
            "iat": now,
            "exp": now + timedelta(minutes=cfg.auth.access_token_ttl_minutes),
        }
        return jwt.encode(
            payload, self._private_key, algorithm="RS256", headers={"kid": self._key_id}
        )

    def decode_access_token(self, token: str) -> AccessTokenClaims:
        try:
            payload = jwt.decode(
                token,
                self._public_key,
                algorithms=["RS256"],
                issuer=cfg.service.name,
                audience=cfg.auth.audience,
                options={"require": ["iss", "aud", "sub", "sid", "iat", "exp"]},
            )
            return AccessTokenClaims(user_id=UUID(payload["sub"]), session_id=UUID(payload["sid"]))
        except (jwt.PyJWTError, ValueError, TypeError) as exc:
            raise NotAuthenticatedError from exc

    def jwks(self) -> tuple[Jwk, ...]:
        public_numbers = RSAAlgorithm.to_jwk(self._public_key, as_dict=True)
        return (
            Jwk(
                kty=str(public_numbers["kty"]),
                n=str(public_numbers["n"]),
                e=str(public_numbers["e"]),
                kid=self._key_id,
                use="sig",
                alg="RS256",
            ),
        )

    @staticmethod
    def issue_refresh_token(session_id: UUID) -> RefreshToken:
        return RefreshToken(session_id=session_id, secret=secrets.token_urlsafe(32))

    @staticmethod
    def parse_refresh_token(token: str) -> RefreshToken:
        session_part, _, secret = token.partition(".")
        try:
            session_id = UUID(session_part)
        except ValueError as exc:
            raise MalformedRefreshTokenError from exc
        if not secret:
            raise MalformedRefreshTokenError
        return RefreshToken(session_id=session_id, secret=secret)

    @staticmethod
    def hash_token(value: str) -> str:
        return hashlib.sha256(value.encode()).hexdigest()

    @staticmethod
    def verify_token(value: str, token_hash: str) -> bool:
        return hmac.compare_digest(SecurityService.hash_token(value), token_hash)

    def _verify_password(self, password_hash: str, password: str) -> bool:
        try:
            return self._password_hasher.verify(password_hash, password)
        except VerificationError, InvalidHashError:
            return False

    @staticmethod
    def _load_private_key(path: Path) -> RSAPrivateKey:
        try:
            key = load_pem_private_key(path.read_bytes(), password=None)
        except (OSError, ValueError, TypeError) as exc:
            raise SigningKeyUnavailableError({"path": str(path)}) from exc
        if not isinstance(key, RSAPrivateKey):
            raise SigningKeyUnavailableError({"path": str(path)})
        return key


class SessionAuthenticator:
    def __init__(self, security: SecurityService, live_sessions: LiveSessions) -> None:
        self._security = security
        self._live_sessions = live_sessions

    async def authenticate(
        self, authorization: str | None, cookie_token: str | None
    ) -> CurrentUser:
        access_token = self._bearer_token(authorization) or cookie_token
        if not access_token:
            raise NotAuthenticatedError
        claims = self._security.decode_access_token(access_token)
        if not await self._live_sessions.is_live(claims.session_id):
            raise NotAuthenticatedError
        return CurrentUser(user_id=claims.user_id, session_id=claims.session_id)

    @staticmethod
    def _bearer_token(authorization: str | None) -> str | None:
        scheme, _, token = (authorization or "").partition(" ")
        return token if scheme.lower() == "bearer" else None

import asyncio
import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid7

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
from src.core.db.enums import UserRole
from src.core.db.models.session import Session
from src.core.db.uow import UnitOfWork
from src.core.security.dto import (
    AccessTokenClaims,
    CurrentUser,
    RefreshToken,
)
from src.core.security.exc import (
    MalformedRefreshTokenError,
    NotAuthenticatedError,
    SigningKeyUnavailableError,
)
from src.core.security.revocation import SessionRevocationList


class SecurityService:
    def __init__(self) -> None:
        self._password_hasher = PasswordHasher()
        self._private_key = self._load_private_key(Path(cfg.auth.private_key_path))
        self._public_key: RSAPublicKey = self._private_key.public_key()
        self._key_id = hashlib.sha256(
            self._public_key.public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
        ).hexdigest()[:16]

    async def hash_password(self, password: str) -> str:
        return await asyncio.to_thread(self._password_hasher.hash, password)

    async def verify_password(self, password_hash: str, password: str) -> bool:
        return await asyncio.to_thread(self._verify_password, password_hash, password)

    def issue_access_token(self, claims: AccessTokenClaims) -> str:
        now = datetime.now(UTC)
        payload = {
            "iss": cfg.service.name,
            "sub": str(claims.user_id),
            "sid": str(claims.session_id),
            "role": claims.role.value,
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
                options={"require": ["iss", "sub", "sid", "role", "iat", "exp"]},
            )
            return AccessTokenClaims(
                user_id=UUID(payload["sub"]),
                session_id=UUID(payload["sid"]),
                role=UserRole(payload["role"]),
            )
        except (jwt.PyJWTError, ValueError, TypeError) as exc:
            raise NotAuthenticatedError from exc

    def jwks(self) -> dict[str, list[dict[str, str]]]:
        key = {
            name: str(value)
            for name, value in RSAAlgorithm.to_jwk(self._public_key, as_dict=True).items()
        }
        return {"keys": [{**key, "kid": self._key_id, "use": "sig", "alg": "RS256"}]}

    def issue_refresh_token(self, session_id: UUID) -> RefreshToken:
        return RefreshToken(session_id=session_id, secret=secrets.token_urlsafe(32))

    def parse_refresh_token(self, token: str) -> RefreshToken:
        session_part, _, secret = token.partition(".")
        try:
            session_id = UUID(session_part)
        except ValueError as exc:
            raise MalformedRefreshTokenError from exc
        if not secret:
            raise MalformedRefreshTokenError
        return RefreshToken(session_id=session_id, secret=secret)

    def hash_token(self, value: str) -> str:
        return hashlib.sha256(value.encode()).hexdigest()

    def verify_token(self, value: str, token_hash: str) -> bool:
        return hmac.compare_digest(self.hash_token(value), token_hash)

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
    def __init__(self, security: SecurityService, revocations: SessionRevocationList) -> None:
        self._security = security
        self._revocations = revocations

    async def authenticate(self, access_token: str | None) -> CurrentUser:
        if not access_token:
            raise NotAuthenticatedError
        claims = self._security.decode_access_token(access_token)
        if await self._revocations.is_revoked(claims.session_id):
            raise NotAuthenticatedError
        return CurrentUser(user_id=claims.user_id, session_id=claims.session_id, role=claims.role)


class SessionIssuer:
    def __init__(self, uow: UnitOfWork, security: SecurityService) -> None:
        self._uow = uow
        self._security = security

    def open(self, user_id: UUID, user_agent: str | None, ttl: timedelta) -> RefreshToken:
        token = self._security.issue_refresh_token(uuid7())
        self._uow.sessions.add(
            Session(
                id=token.session_id,
                user_id=user_id,
                refresh_token_hash=self._security.hash_token(token.secret),
                expires_at=datetime.now(UTC) + ttl,
                user_agent=user_agent,
            )
        )
        return token

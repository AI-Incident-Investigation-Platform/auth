import asyncio
import contextvars
import functools
import hashlib
import hmac
import secrets
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
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
from opentelemetry import trace

from src.config import cfg
from src.core.context import bind_log_identity
from src.core.security.dto import (
    AccessTokenClaims,
    CurrentUser,
    Jwk,
    RefreshToken,
)
from src.core.security.exc import (
    MalformedRefreshTokenError,
    NotAuthenticatedError,
    PasswordHashingOverloadedError,
    SigningKeyUnavailableError,
)
from src.core.security.live_sessions import LiveSessions
from src.core.security.metrics import PASSWORD_DURATION, PASSWORD_OPERATIONS


class SecurityService:
    def __init__(self) -> None:
        self._tracer = trace.get_tracer(__name__)
        self._password_hasher = PasswordHasher(
            memory_cost=cfg.auth.password_hash_memory_kib,
            time_cost=cfg.auth.password_hash_time_cost,
            parallelism=cfg.auth.password_hash_parallelism,
        )
        # хэш argon2 берёт memory_kib памяти: без очереди всплеск входов выводит под за лимит.
        self._hashing_slots = asyncio.Semaphore(cfg.auth.password_hashing_concurrency)
        # длинная очередь означает ответ через секунды: отказ сразу честнее и бережёт под.
        self._hashing_waiters = 0
        self._unknown_user_password_hash = self._password_hasher.hash(secrets.token_urlsafe(32))
        self._private_key = self._load_private_key(Path(cfg.auth.private_key_path))
        self._public_key: RSAPublicKey = self._private_key.public_key()
        self._key_id = hashlib.sha256(
            self._public_key.public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
        ).hexdigest()[:16]

    async def hash_password(self, password: str) -> str:
        return await self._run_in_hashing_slot("hash", self._hash_password, password)

    async def verify_password(self, password_hash: str | None, password: str) -> bool:
        """Сверяет пароль с хэшем; без хэша (нет такого пользователя) тратит то же время.

        Так по времени ответа на вход нельзя узнать, зарегистрирована ли почта.
        """
        if password_hash is None:
            await self._run_in_hashing_slot(
                "verify", self._verify_password, self._unknown_user_password_hash, password
            )
            return False
        return await self._run_in_hashing_slot(
            "verify", self._verify_password, password_hash, password
        )

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

    async def _run_in_hashing_slot[T](
        self, operation: str, func: Callable[..., T], *args: object
    ) -> T:
        started = time.perf_counter()
        with self._tracer.start_as_current_span(f"auth.password.{operation}"):
            try:
                if (
                    self._hashing_slots.locked()
                    and self._hashing_waiters >= cfg.auth.password_hashing_queue_limit
                ):
                    raise PasswordHashingOverloadedError(
                        {"operation": operation, "waiting": self._hashing_waiters}
                    )
                waiting_since = time.perf_counter()
                self._hashing_waiters += 1
                PASSWORD_OPERATIONS.labels(operation, "waiting").inc()
                try:
                    with self._tracer.start_as_current_span("auth.password.wait"):
                        await self._hashing_slots.acquire()
                finally:
                    self._hashing_waiters -= 1
                    PASSWORD_OPERATIONS.labels(operation, "waiting").dec()
                    PASSWORD_DURATION.labels(operation, "wait").observe(
                        time.perf_counter() - waiting_since
                    )
                # Слот принадлежит работе в потоке: отменённый запрос не освобождает его, пока
                # Argon2 считает, иначе отмены запускают хэши сверх лимита.
                try:
                    work = asyncio.get_running_loop().run_in_executor(
                        None, functools.partial(contextvars.copy_context().run, func, *args)
                    )
                except BaseException:
                    self._hashing_slots.release()
                    raise
                work.add_done_callback(lambda _: self._hashing_slots.release())
                return await asyncio.shield(work)
            finally:
                PASSWORD_DURATION.labels(operation, "total").observe(time.perf_counter() - started)

    @contextmanager
    def _password_execution(self, operation: str) -> Iterator[None]:
        # Измеряем внутри потока: очередь executor и возобновление event loop сюда не входят.
        started = time.perf_counter()
        PASSWORD_OPERATIONS.labels(operation, "running").inc()
        try:
            with self._tracer.start_as_current_span("auth.password.execute"):
                yield
        finally:
            PASSWORD_DURATION.labels(operation, "execute").observe(time.perf_counter() - started)
            PASSWORD_OPERATIONS.labels(operation, "running").dec()

    def _hash_password(self, password: str) -> str:
        with self._password_execution("hash"):
            return self._password_hasher.hash(password)

    def _verify_password(self, password_hash: str, password: str) -> bool:
        with self._password_execution("verify"):
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
        bind_log_identity(claims.user_id, claims.session_id)
        if not await self._live_sessions.is_live(claims.session_id):
            raise NotAuthenticatedError
        return CurrentUser(user_id=claims.user_id, session_id=claims.session_id)

    @staticmethod
    def _bearer_token(authorization: str | None) -> str | None:
        scheme, _, token = (authorization or "").partition(" ")
        return token if scheme.lower() == "bearer" else None

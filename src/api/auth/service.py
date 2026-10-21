from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid7

from src.api.auth.dto import IssuedTokens, SignedIn
from src.api.exc.auth import (
    AccountNotFoundError,
    EmailAlreadyRegisteredError,
    InvalidCredentialsError,
    InvalidRefreshTokenError,
    RefreshTokenReusedError,
    WrongCurrentPasswordError,
)
from src.config import cfg
from src.core.db.dto.user import UserDTO
from src.core.db.exc import IntegrityViolationError
from src.core.db.models.session import Session
from src.core.db.models.user import User
from src.core.db.uow import UnitOfWork
from src.core.security.dto import AccessTokenClaims, CurrentUser, Jwk, RefreshToken
from src.core.security.exc import MalformedRefreshTokenError
from src.core.security.live_sessions import LiveSessions
from src.core.security.service import SecurityService


class AuthService:
    """Регистрация, вход, сессии и пароль.

    Сессия меняется только под блокировкой своей строки, а пропуск в кэше
    ставится и снимается до commit: параллельные refresh, выход и смена пароля
    не оставляют живой пропуск у отозванной сессии.
    """

    def __init__(
        self,
        uow: UnitOfWork,
        security: SecurityService,
        live_sessions: LiveSessions,
    ) -> None:
        self._uow = uow
        self._security = security
        self._live_sessions = live_sessions

    async def register(self, email: str, password: str, user_agent: str | None) -> SignedIn:
        if await self._uow.users.get_by_email(email):
            raise EmailAlreadyRegisteredError

        user = User(
            id=uuid7(), email=email, password_hash=await self._security.hash_password(password)
        )
        try:
            self._uow.users.add(user)
            await self._uow.flush()
        except IntegrityViolationError as exc:
            if exc.constraint == "uq_users_email":
                raise EmailAlreadyRegisteredError from exc
            raise
        tokens = await self._open_session(user.id, user_agent)
        await self._uow.commit()
        return SignedIn(user=UserDTO.from_orm(user), tokens=tokens)

    async def login(self, email: str, password: str, user_agent: str | None) -> SignedIn:
        # FOR SHARE до commit: смена пароля ждёт этот вход и отзывает его сессию,
        # а вход, начатый после смены, видит уже новый хэш.
        user = await self._uow.users.get_by_email_for_share(email)
        verified = await self._security.verify_password(
            user.password_hash if user else None, password
        )
        if user is None or not verified:
            raise InvalidCredentialsError

        tokens = await self._open_session(user.id, user_agent)
        await self._uow.commit()
        return SignedIn(user=UserDTO.from_orm(user), tokens=tokens)

    async def refresh(self, refresh_token: str | None) -> IssuedTokens:
        presented = self._parse_refresh_token(refresh_token)
        now = datetime.now(UTC)
        session = await self._uow.sessions.get_for_update(presented.session_id)
        if session is None or session.revoked_at is not None or session.expires_at <= now:
            raise InvalidRefreshTokenError

        if self._security.verify_token(presented.secret, session.refresh_token_hash):
            tokens = await self._rotate(session, now)
        elif self._is_neighbour_refresh(session, presented.secret, now):
            tokens = IssuedTokens(
                access_token=await self._issue_access_token(session.user_id, session.id),
                refresh_token=None,
            )
        else:
            await self._revoke(session, now)
            await self._uow.commit()
            raise RefreshTokenReusedError({"session_id": str(session.id)})
        await self._uow.commit()
        return tokens

    async def logout(self, refresh_token: str | None) -> None:
        try:
            presented = self._parse_refresh_token(refresh_token)
        except InvalidRefreshTokenError:
            return
        now = datetime.now(UTC)
        session = await self._uow.sessions.get_for_update(presented.session_id)
        if session is None or session.revoked_at is not None:
            return
        if self._security.verify_token(
            presented.secret, session.refresh_token_hash
        ) or self._is_neighbour_refresh(session, presented.secret, now):
            await self._revoke(session, now)
            await self._uow.commit()

    async def change_password(
        self, current_user: CurrentUser, current_password: str, new_password: str
    ) -> None:
        user = await self._uow.users.get_for_update(current_user.user_id)
        if user is None:
            raise AccountNotFoundError
        if not await self._security.verify_password(user.password_hash, current_password):
            raise WrongCurrentPasswordError

        user.password_hash = await self._security.hash_password(new_password)
        revoked = await self._uow.sessions.revoke_all_for_user(
            user.id, datetime.now(UTC), except_session_id=current_user.session_id
        )
        await self._live_sessions.forget(revoked)
        await self._uow.commit()

    async def get_me(self, current_user: CurrentUser) -> UserDTO:
        user = await self._uow.users.get_by_id(current_user.user_id)
        if user is None:
            raise AccountNotFoundError
        return UserDTO.from_orm(user)

    def jwks(self) -> tuple[Jwk, ...]:
        return self._security.jwks()

    def _parse_refresh_token(self, refresh_token: str | None) -> RefreshToken:
        if not refresh_token:
            raise InvalidRefreshTokenError
        try:
            return self._security.parse_refresh_token(refresh_token)
        except MalformedRefreshTokenError as exc:
            raise InvalidRefreshTokenError from exc

    def _is_neighbour_refresh(self, session: Session, secret: str, now: datetime) -> bool:
        """Предыдущий refresh-токен сразу после ротации — соседняя вкладка, а не кража.

        Вкладки делят куки: если две одновременно получили 401, обе придут с
        одним токеном, и вторая опоздает к уже ротированной сессии.
        """
        grace = timedelta(seconds=cfg.auth.refresh_reuse_grace_seconds)
        return (
            session.previous_refresh_token_hash is not None
            and session.rotated_at is not None
            and now - session.rotated_at <= grace
            and self._security.verify_token(secret, session.previous_refresh_token_hash)
        )

    async def _rotate(self, session: Session, now: datetime) -> IssuedTokens:
        refresh_token = self._security.issue_refresh_token(session.id)
        session.previous_refresh_token_hash = session.refresh_token_hash
        session.refresh_token_hash = self._security.hash_token(refresh_token.secret)
        session.rotated_at = now
        session.expires_at = now + timedelta(days=cfg.auth.refresh_token_ttl_days)
        return IssuedTokens(
            access_token=await self._issue_access_token(session.user_id, session.id),
            refresh_token=str(refresh_token),
        )

    async def _revoke(self, session: Session, now: datetime) -> None:
        session.revoked_at = now
        await self._live_sessions.forget([session.id])

    async def _open_session(self, user_id: UUID, user_agent: str | None) -> IssuedTokens:
        refresh_token = self._security.issue_refresh_token(uuid7())
        self._uow.sessions.add(
            Session(
                id=refresh_token.session_id,
                user_id=user_id,
                refresh_token_hash=self._security.hash_token(refresh_token.secret),
                expires_at=datetime.now(UTC) + timedelta(days=cfg.auth.refresh_token_ttl_days),
                user_agent=user_agent,
            )
        )
        return IssuedTokens(
            access_token=await self._issue_access_token(user_id, refresh_token.session_id),
            refresh_token=str(refresh_token),
        )

    async def _issue_access_token(self, user_id: UUID, session_id: UUID) -> str:
        await self._live_sessions.mark_live(session_id)
        return self._security.issue_access_token(
            AccessTokenClaims(user_id=user_id, session_id=session_id)
        )

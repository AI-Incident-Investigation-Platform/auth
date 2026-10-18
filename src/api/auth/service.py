from datetime import UTC, datetime, timedelta
from uuid import uuid7

from src.api.auth.dto import IssuedTokens, SignedIn
from src.api.exc.auth import (
    AccountDeactivatedError,
    EmailAlreadyRegisteredError,
    InvalidCredentialsError,
    InvalidRefreshTokenError,
    RefreshTokenReusedError,
    WrongCurrentPasswordError,
)
from src.config import cfg
from src.core.db.dto.user import UserDTO
from src.core.db.enums import UserRole
from src.core.db.exc import IntegrityViolationError
from src.core.db.models.user import User
from src.core.db.uow import UnitOfWork
from src.core.security.dto import AccessTokenClaims, CurrentUser
from src.core.security.exc import MalformedRefreshTokenError
from src.core.security.revocation import SessionRevocationList
from src.core.security.service import SecurityService, SessionIssuer


class AuthService:
    def __init__(
        self,
        uow: UnitOfWork,
        security: SecurityService,
        session_issuer: SessionIssuer,
        revocations: SessionRevocationList,
    ) -> None:
        self._uow = uow
        self._security = security
        self._session_issuer = session_issuer
        self._revocations = revocations

    async def register(self, email: str, password: str, user_agent: str | None) -> SignedIn:
        if await self._uow.users.get_by_email(email):
            raise EmailAlreadyRegisteredError

        user = User(
            id=uuid7(),
            email=email,
            password_hash=await self._security.hash_password(password),
            role=UserRole.USER,
        )
        try:
            self._uow.users.add(user)
            await self._uow.flush()
            tokens = self._open_session(user, user_agent)
            await self._uow.commit()
        except IntegrityViolationError as exc:
            if exc.constraint == "uq_users_email":
                raise EmailAlreadyRegisteredError from exc
            raise
        return SignedIn(user=UserDTO.from_orm(user), tokens=tokens)

    async def login(self, email: str, password: str, user_agent: str | None) -> SignedIn:
        user = await self._uow.users.get_by_email(email)
        if user is None or not await self._security.verify_password(user.password_hash, password):
            raise InvalidCredentialsError
        if not user.is_active:
            raise AccountDeactivatedError

        tokens = self._open_session(user, user_agent)
        await self._uow.commit()
        return SignedIn(user=UserDTO.from_orm(user), tokens=tokens)

    async def refresh(self, refresh_token: str | None) -> IssuedTokens:
        if not refresh_token:
            raise InvalidRefreshTokenError
        try:
            parsed = self._security.parse_refresh_token(refresh_token)
        except MalformedRefreshTokenError as exc:
            raise InvalidRefreshTokenError from exc

        now = datetime.now(UTC)
        session = await self._uow.sessions.get_for_update(parsed.session_id)
        if session is None or session.revoked_at is not None or session.expires_at <= now:
            raise InvalidRefreshTokenError
        if not self._security.verify_token(parsed.secret, session.refresh_token_hash):
            session.revoked_at = now
            await self._uow.commit()
            await self._revocations.revoke([session.id])
            raise RefreshTokenReusedError({"session_id": str(session.id)})

        user = await self._uow.users.get_by_id(session.user_id)
        if user is None or not user.is_active:
            raise AccountDeactivatedError

        new_refresh = self._security.issue_refresh_token(session.id)
        session.refresh_token_hash = self._security.hash_token(new_refresh.secret)
        session.expires_at = now + timedelta(days=cfg.auth.refresh_token_ttl_days)
        access_token = self._security.issue_access_token(
            AccessTokenClaims(user_id=user.id, session_id=session.id, role=user.role)
        )
        await self._uow.commit()
        return IssuedTokens(access_token=access_token, refresh_token=str(new_refresh))

    async def logout(self, refresh_token: str | None) -> None:
        if not refresh_token:
            return
        try:
            parsed = self._security.parse_refresh_token(refresh_token)
        except MalformedRefreshTokenError:
            return
        session = await self._uow.sessions.get_for_update(parsed.session_id)
        if session is None or session.revoked_at is not None:
            return
        session.revoked_at = datetime.now(UTC)
        await self._uow.commit()
        await self._revocations.revoke([session.id])

    async def change_password(
        self, current_user: CurrentUser, current_password: str, new_password: str
    ) -> None:
        user = await self._get_user(current_user)
        if not await self._security.verify_password(user.password_hash, current_password):
            raise WrongCurrentPasswordError

        user.password_hash = await self._security.hash_password(new_password)
        revoked = await self._uow.sessions.revoke_all_for_user(
            user.id, datetime.now(UTC), except_session_id=current_user.session_id
        )
        await self._uow.commit()
        await self._revocations.revoke(revoked)

    async def get_me(self, current_user: CurrentUser) -> UserDTO:
        return UserDTO.from_orm(await self._get_user(current_user))

    def jwks(self) -> dict[str, list[dict[str, str]]]:
        return self._security.jwks()

    async def _get_user(self, current_user: CurrentUser) -> User:
        user = await self._uow.users.get_by_id(current_user.user_id)
        if user is None:
            raise InvalidCredentialsError
        return user

    def _open_session(self, user: User, user_agent: str | None) -> IssuedTokens:
        refresh_token = self._session_issuer.open(
            user.id, user_agent, timedelta(days=cfg.auth.refresh_token_ttl_days)
        )
        access_token = self._security.issue_access_token(
            AccessTokenClaims(user_id=user.id, session_id=refresh_token.session_id, role=user.role)
        )
        return IssuedTokens(access_token=access_token, refresh_token=str(refresh_token))

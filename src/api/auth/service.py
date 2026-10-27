import logging
import math
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid7

from src.api.auth.dto import IssuedTokens, LoginChallenge, SignedIn
from src.api.exc.auth import (
    AccountNotFoundError,
    ChallengeInvalidError,
    InvalidRefreshTokenError,
    OtpExpiredError,
    OtpInvalidError,
    OtpRateLimitedError,
    RefreshTokenReusedError,
)
from src.config import cfg
from src.core.context import bind_log_identity
from src.core.db.dto.user import UserDTO
from src.core.db.exc import IntegrityViolationError
from src.core.db.models.session import Session
from src.core.db.models.user import User
from src.core.db.uow import UnitOfWork
from src.core.email.dto import EmailLetter
from src.core.email.enums import EmailTemplate
from src.core.email.service import EmailService
from src.core.errors import IntegrationError, InternalError
from src.core.security.dto import AccessTokenClaims, CurrentUser, OtpChallenge, RefreshToken
from src.core.security.exc import MalformedRefreshTokenError
from src.core.security.live_sessions import LiveSessions
from src.core.security.otp_challenges import OtpChallenges
from src.core.security.service import SecurityService

log = logging.getLogger(__name__)


class AuthService:
    """Вход и регистрация по коду на почту, сессии.

    Вход и регистрация — один поток: аккаунт создаётся, когда новый email
    подтверждён кодом, поэтому неподтверждённых аккаунтов нет. Ответ на запрос
    кода одинаков для известного и нового email.

    Сессия меняется только под блокировкой своей строки, а пропуск в кэше
    ставится и снимается до commit: параллельные refresh и выход не оставляют
    живой пропуск у отозванной сессии.
    """

    def __init__(
        self,
        uow: UnitOfWork,
        security: SecurityService,
        live_sessions: LiveSessions,
        otp_challenges: OtpChallenges,
        email: EmailService,
    ) -> None:
        self._uow = uow
        self._security = security
        self._live_sessions = live_sessions
        self._otp_challenges = otp_challenges
        self._email = email

    async def start_login(self, email: str) -> LoginChallenge:
        await self._check_send_quota(email)
        challenge_id = self._security.new_challenge_id()
        code = self._security.new_otp_code()
        challenge = self._issue_code(challenge_id, email, code, resends=0)
        await self._otp_challenges.save(challenge)
        try:
            await self._send_code(challenge, code)
        except IntegrationError:
            await self._otp_challenges.delete(challenge_id)
            raise
        log.info("Код входа поставлен в очередь на отправку")
        return self._present(challenge)

    async def resend_code(self, challenge_id: str) -> LoginChallenge:
        challenge = await self._otp_challenges.get(challenge_id)
        if challenge is None:
            raise ChallengeInvalidError
        if challenge.resends >= cfg.auth.otp_max_resends:
            raise OtpRateLimitedError(
                cfg.auth.otp_resend_interval_seconds, {"resends": challenge.resends}
            )
        if (wait := self._seconds_until(challenge.resend_available_at)) > 0:
            raise OtpRateLimitedError(wait, {"resends": challenge.resends})
        await self._check_send_quota(challenge.email)

        code = self._security.new_otp_code()
        resent = self._issue_code(
            challenge.challenge_id, challenge.email, code, resends=challenge.resends + 1
        )
        if not await self._otp_challenges.replace(resent):
            raise ChallengeInvalidError
        try:
            await self._send_code(resent, code)
        except IntegrationError:
            await self._otp_challenges.replace(challenge)
            raise
        log.info("Код входа отправлен повторно", extra={"otp": {"resends": resent.resends}})
        return self._present(resent)

    async def verify_code(self, challenge_id: str, code: str, user_agent: str | None) -> SignedIn:
        challenge = await self._otp_challenges.get(challenge_id)
        if challenge is None:
            raise ChallengeInvalidError
        attempts = await self._otp_challenges.register_attempt(challenge_id)
        if attempts > cfg.auth.otp_max_attempts:
            await self._otp_challenges.delete(challenge_id)
            raise ChallengeInvalidError({"attempts": attempts})
        if self._seconds_until(challenge.code_expires_at) <= 0:
            raise OtpExpiredError
        if not self._security.verify_otp(challenge_id, code, challenge.code_digest):
            attempts_left = cfg.auth.otp_max_attempts - attempts
            if attempts_left == 0:
                await self._otp_challenges.delete(challenge_id)
            raise OtpInvalidError({"attempts": attempts}, {"attempts_left": attempts_left})
        if not await self._otp_challenges.consume(challenge_id):
            raise ChallengeInvalidError

        user, account_created = await self._get_or_create_user(challenge.email)
        session_id = uuid7()
        bind_log_identity(user.id, session_id)
        tokens = await self._open_session(user.id, session_id, user_agent)
        await self._uow.commit()
        log.info(
            "Пользователь вошёл по коду",
            extra={
                "user_id": str(user.id),
                "session_id": str(session_id),
                "account_created": account_created,
            },
        )
        return SignedIn(user=UserDTO.from_orm(user), tokens=tokens, account_created=account_created)

    async def refresh(self, refresh_token: str | None) -> IssuedTokens:
        presented = self._parse_refresh_token(refresh_token)
        now = datetime.now(UTC)
        session = await self._uow.sessions.get_for_update(presented.session_id)
        if session is not None:
            bind_log_identity(session.user_id, session.id)
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
        log.debug(
            "Токены сессии обновлены"
            if tokens.refresh_token
            else "Обработано обновление токенов из соседней вкладки",
            extra={"user_id": str(session.user_id), "session_id": str(session.id)},
        )
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
            bind_log_identity(session.user_id, session.id)
            await self._revoke(session, now)
            await self._uow.commit()
            log.info(
                "Сессия отозвана при выходе пользователя",
                extra={"user_id": str(session.user_id), "session_id": str(session.id)},
            )

    async def get_me(self, current_user: CurrentUser) -> UserDTO:
        user = await self._uow.users.get_by_id(current_user.user_id)
        if user is None:
            raise AccountNotFoundError
        return UserDTO.from_orm(user)

    async def _check_send_quota(self, email: str) -> None:
        sent = await self._otp_challenges.register_send(email)
        if sent.count > cfg.auth.otp_sends_per_email_per_hour:
            raise OtpRateLimitedError(sent.resets_in_seconds, {"sends": sent.count})

    async def _send_code(self, challenge: OtpChallenge, code: str) -> None:
        await self._email.send(
            EmailLetter(
                template=EmailTemplate.LOGIN_CODE,
                to=challenge.email,
                params={"code": code, "expires_in": cfg.auth.otp_code_ttl_seconds},
                ttl_seconds=cfg.auth.otp_code_ttl_seconds,
            )
        )

    def _issue_code(self, challenge_id: str, email: str, code: str, resends: int) -> OtpChallenge:
        now = datetime.now(UTC)
        return OtpChallenge(
            challenge_id=challenge_id,
            email=email,
            code_digest=self._security.otp_digest(challenge_id, code),
            code_expires_at=now + timedelta(seconds=cfg.auth.otp_code_ttl_seconds),
            resend_available_at=now + timedelta(seconds=cfg.auth.otp_resend_interval_seconds),
            resends=resends,
        )

    async def _get_or_create_user(self, email: str) -> tuple[User, bool]:
        if user := await self._uow.users.get_by_email(email):
            return user, False
        user = User(id=uuid7(), email=email)
        try:
            self._uow.users.add(user)
            await self._uow.flush()
        except IntegrityViolationError as exc:
            if exc.constraint != "uq_users_email":
                raise
            await self._uow.rollback()
            if (existing := await self._uow.users.get_by_email(email)) is None:
                raise InternalError({"constraint": exc.constraint}) from exc
            return existing, False
        return user, True

    def _present(self, challenge: OtpChallenge) -> LoginChallenge:
        return LoginChallenge(
            challenge_id=challenge.challenge_id,
            masked_email=self._mask_email(challenge.email),
            expires_in=self._seconds_until(challenge.code_expires_at),
            resend_after=max(self._seconds_until(challenge.resend_available_at), 0),
        )

    @staticmethod
    def _mask_email(email: str) -> str:
        local, _, domain = email.partition("@")
        return f"{local[0]}***@{domain}"

    @staticmethod
    def _seconds_until(moment: datetime) -> int:
        return math.ceil((moment - datetime.now(UTC)).total_seconds())

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

    async def _open_session(
        self, user_id: UUID, session_id: UUID, user_agent: str | None
    ) -> IssuedTokens:
        refresh_token = self._security.issue_refresh_token(session_id)
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

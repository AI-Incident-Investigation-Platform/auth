import dataclasses
import logging
import math
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid7

from src.api.auth.dto import EmailChangeChallenge, IssuedTokens, LoginChallenge, SignedIn
from src.api.exc.auth import (
    AccountNotFoundError,
    ChallengeInvalidError,
    EmailNotRegisteredError,
    EmailTakenError,
    EmailUnchangedError,
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
from src.core.errors import ErrorReport, IntegrationError, InternalError
from src.core.events.enums import UserEventType
from src.core.events.service import UserEventsService
from src.core.security.dto import AccessTokenClaims, CurrentUser, OtpChallenge, RefreshToken
from src.core.security.enums import OtpPurpose
from src.core.security.exc import MalformedRefreshTokenError
from src.core.security.live_sessions import LiveSessions
from src.core.security.otp_challenges import OtpChallenges
from src.core.security.service import SecurityService

log = logging.getLogger(__name__)


class AuthService:
    """Регистрация, вход и смена почты по коду из письма, сессии.

    Регистрация и вход — разные потоки: регистрация принимает только новую почту,
    вход — только зарегистрированную. Аккаунт создаётся, когда новая почта
    подтверждена кодом, поэтому неподтверждённых аккаунтов нет. Смена почты
    подтверждается двумя кодами — с текущей и с новой почты: почта и есть
    аккаунт, и одной украденной сессии не хватает, чтобы его увести.

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
        user_events: UserEventsService,
    ) -> None:
        self._uow = uow
        self._security = security
        self._live_sessions = live_sessions
        self._otp_challenges = otp_challenges
        self._email = email
        self._user_events = user_events

    async def start_registration(self, email: str) -> LoginChallenge:
        if await self._uow.users.get_by_email(email) is not None:
            raise EmailTakenError
        await self._uow.rollback()
        challenge = await self._start(OtpPurpose.REGISTER, email)
        return self._present(challenge)

    async def start_login(self, email: str) -> LoginChallenge:
        if await self._uow.users.get_by_email(email) is None:
            raise EmailNotRegisteredError
        await self._uow.rollback()
        challenge = await self._start(OtpPurpose.LOGIN, email)
        return self._present(challenge)

    async def start_email_change(
        self, current_user: CurrentUser, new_email: str
    ) -> EmailChangeChallenge:
        user = await self._uow.users.get_by_id(current_user.user_id)
        if user is None:
            raise AccountNotFoundError
        if user.email == new_email:
            raise EmailUnchangedError
        if await self._uow.users.get_by_email(new_email) is not None:
            raise EmailTakenError
        current_email = user.email
        await self._uow.rollback()
        challenge = await self._start(
            OtpPurpose.EMAIL_CHANGE, current_email, current_user.user_id, new_email
        )
        return EmailChangeChallenge(
            challenge_id=challenge.challenge_id,
            masked_email=self._mask_email(current_email),
            masked_new_email=self._mask_email(new_email),
            expires_in=self._seconds_until(challenge.code_expires_at),
            resend_after=max(self._seconds_until(challenge.resend_available_at), 0),
        )

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
        await self._check_send_quota(challenge)

        resent, code, new_code = self._with_new_codes(
            dataclasses.replace(challenge, resends=challenge.resends + 1)
        )
        if not await self._otp_challenges.replace(resent):
            raise ChallengeInvalidError
        try:
            await self._send_codes(resent, code, new_code)
        except IntegrationError:
            await self._otp_challenges.replace(challenge)
            raise
        log.info(
            "Код отправлен повторно",
            extra={
                "event": "auth.otp_resent",
                "otp": {"purpose": resent.purpose.value, "resends": resent.resends},
            },
        )
        return self._present(resent)

    async def verify_code(self, challenge_id: str, code: str, user_agent: str | None) -> SignedIn:
        challenge = await self._redeem(
            challenge_id, code, None, (OtpPurpose.LOGIN, OtpPurpose.REGISTER), user_id=None
        )
        account_created = challenge.purpose == OtpPurpose.REGISTER
        if account_created:
            user = await self._register(challenge.email)
        elif (found := await self._uow.users.get_by_email(challenge.email)) is not None:
            user = found
        else:
            raise EmailNotRegisteredError
        session_id = uuid7()
        bind_log_identity(user.id, session_id)
        tokens = await self._open_session(user.id, session_id, user_agent)
        await self._uow.commit()
        log.info(
            "Пользователь зарегистрировался" if account_created else "Пользователь вошёл по коду",
            extra={
                "event": "auth.registered" if account_created else "auth.signed_in",
                "user_id": str(user.id),
                "session_id": str(session_id),
                "account_created": account_created,
            },
        )
        return SignedIn(user=UserDTO.from_orm(user), tokens=tokens, account_created=account_created)

    async def confirm_email_change(
        self, current_user: CurrentUser, challenge_id: str, code: str, new_code: str
    ) -> UserDTO:
        """Меняет почту по кодам с обеих почт и закрывает остальные сессии пользователя.

        Raises:
            ChallengeInvalidError: challenge чужой, использован или почту уже сменили.
            OtpInvalidError: хотя бы один код неверен.
            EmailTakenError: новую почту успели занять.
        """
        challenge = await self._redeem(
            challenge_id, code, new_code, (OtpPurpose.EMAIL_CHANGE,), current_user.user_id
        )
        if challenge.new_email is None:
            raise InternalError({"purpose": challenge.purpose.value})
        user = await self._uow.users.get_for_update(current_user.user_id)
        if user is None:
            raise AccountNotFoundError
        if user.email != challenge.email:
            raise ChallengeInvalidError({"reason": "email_changed_meanwhile"})
        previous_email = user.email
        user.email = challenge.new_email
        try:
            await self._uow.flush()
        except IntegrityViolationError as exc:
            if exc.constraint != "uq_users_email":
                raise
            raise EmailTakenError from exc
        revoked = await self._revoke_other_sessions(user.id, current_user.session_id)
        await self._user_events.publish(UserEventType.EMAIL_CHANGED, user.id, user.email)
        await self._uow.commit()
        log.info(
            "Почта пользователя изменена",
            extra={
                "event": "auth.email_changed",
                "user_id": str(user.id),
                "sessions": {"revoked": revoked},
            },
        )
        await self._notify_email_changed(previous_email, user.email)
        return UserDTO.from_orm(user)

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
            extra={
                "event": "auth.tokens_refreshed"
                if tokens.refresh_token
                else "auth.tokens_refreshed_sibling",
                "user_id": str(session.user_id),
                "session_id": str(session.id),
            },
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
                extra={
                    "event": "auth.signed_out",
                    "user_id": str(session.user_id),
                    "session_id": str(session.id),
                },
            )

    async def get_me(self, current_user: CurrentUser) -> UserDTO:
        user = await self._uow.users.get_by_id(current_user.user_id)
        if user is None:
            raise AccountNotFoundError
        return UserDTO.from_orm(user)

    async def _start(
        self,
        purpose: OtpPurpose,
        email: str,
        user_id: UUID | None = None,
        new_email: str | None = None,
    ) -> OtpChallenge:
        now = datetime.now(UTC)
        draft = OtpChallenge(
            challenge_id=self._security.new_challenge_id(),
            purpose=purpose,
            email=email,
            code_digest="",
            code_expires_at=now,
            resend_available_at=now,
            resends=0,
            user_id=user_id,
            new_email=new_email,
        )
        await self._check_send_quota(draft)
        challenge, code, new_code = self._with_new_codes(draft)
        await self._otp_challenges.save(challenge)
        try:
            await self._send_codes(challenge, code, new_code)
        except IntegrationError:
            await self._otp_challenges.delete(challenge.challenge_id)
            raise
        log.info(
            "Код поставлен в очередь на отправку",
            extra={"event": "auth.otp_sent", "otp": {"purpose": purpose.value}},
        )
        return challenge

    async def _redeem(
        self,
        challenge_id: str,
        code: str,
        new_code: str | None,
        purposes: tuple[OtpPurpose, ...],
        user_id: UUID | None,
    ) -> OtpChallenge:
        """Проверяет код и гасит challenge: один challenge погасит только один запрос."""
        challenge = await self._otp_challenges.get(challenge_id)
        if challenge is None or challenge.purpose not in purposes or challenge.user_id != user_id:
            raise ChallengeInvalidError
        attempts = await self._otp_challenges.register_attempt(challenge_id)
        if attempts > cfg.auth.otp_max_attempts:
            await self._otp_challenges.delete(challenge_id)
            raise ChallengeInvalidError({"attempts": attempts})
        if self._seconds_until(challenge.code_expires_at) <= 0:
            raise OtpExpiredError
        valid = self._security.verify_otp(challenge_id, code, challenge.code_digest)
        if challenge.new_code_digest is not None:
            valid = (
                self._security.verify_otp(
                    self._new_code_salt(challenge_id), new_code or "", challenge.new_code_digest
                )
                and valid
            )
        if not valid:
            attempts_left = cfg.auth.otp_max_attempts - attempts
            if attempts_left == 0:
                await self._otp_challenges.delete(challenge_id)
            raise OtpInvalidError({"attempts": attempts}, {"attempts_left": attempts_left})
        if not await self._otp_challenges.consume(challenge_id):
            raise ChallengeInvalidError
        return challenge

    async def _register(self, email: str) -> User:
        user = User(id=uuid7(), email=email)
        try:
            self._uow.users.add(user)
            await self._uow.flush()
        except IntegrityViolationError as exc:
            if exc.constraint != "uq_users_email":
                raise
            raise EmailTakenError from exc
        await self._user_events.publish(UserEventType.REGISTERED, user.id, email)
        return user

    async def _revoke_other_sessions(self, user_id: UUID, keep_session_id: UUID) -> int:
        now = datetime.now(UTC)
        sessions = await self._uow.sessions.lock_live_for_user(user_id, now, keep_session_id)
        for session in sessions:
            session.revoked_at = now
        await self._live_sessions.forget([session.id for session in sessions])
        return len(sessions)

    async def _notify_email_changed(self, previous_email: str, new_email: str) -> None:
        """Предупреждает старую почту; почта уже сменена, поэтому сбой письма её не отменяет."""
        try:
            await self._email.send(
                EmailLetter(
                    template=EmailTemplate.EMAIL_CHANGED,
                    to=previous_email,
                    params={"new_email": new_email},
                    ttl_seconds=cfg.auth.email_changed_letter_ttl_seconds,
                )
            )
        except IntegrationError as exc:
            log.warning(
                "Не удалось поставить письмо о смене почты",
                extra={
                    "event": "auth.email_changed_letter_failed",
                    "error": ErrorReport.from_exception(exc).to_log(),
                },
            )

    async def _check_send_quota(self, challenge: OtpChallenge) -> None:
        for email in (challenge.email, challenge.new_email):
            if email is None:
                continue
            sent = await self._otp_challenges.register_send(email)
            if sent.count > cfg.auth.otp_sends_per_email_per_hour:
                raise OtpRateLimitedError(sent.resets_in_seconds, {"sends": sent.count})

    async def _send_codes(self, challenge: OtpChallenge, code: str, new_code: str | None) -> None:
        match challenge.purpose:
            case OtpPurpose.LOGIN:
                await self._send_code(EmailTemplate.LOGIN_CODE, challenge.email, code, {})
            case OtpPurpose.REGISTER:
                await self._send_code(EmailTemplate.REGISTER_CODE, challenge.email, code, {})
            case OtpPurpose.EMAIL_CHANGE:
                if challenge.new_email is None or new_code is None:
                    raise InternalError({"purpose": challenge.purpose.value})
                await self._send_code(
                    EmailTemplate.EMAIL_CHANGE_CURRENT_CODE,
                    challenge.email,
                    code,
                    {"new_email": challenge.new_email},
                )
                await self._send_code(
                    EmailTemplate.EMAIL_CHANGE_NEW_CODE, challenge.new_email, new_code, {}
                )

    async def _send_code(
        self, template: EmailTemplate, to: str, code: str, params: Mapping[str, str]
    ) -> None:
        await self._email.send(
            EmailLetter(
                template=template,
                to=to,
                params={**params, "code": code, "expires_in": cfg.auth.otp_code_ttl_seconds},
                ttl_seconds=cfg.auth.otp_code_ttl_seconds,
                # новый код на тот же адрес делает ждущее письмо со старым кодом бесполезным
                collapse_key=f"{template.value}:{to}",
            )
        )

    def _with_new_codes(self, challenge: OtpChallenge) -> tuple[OtpChallenge, str, str | None]:
        """Challenge с новыми кодами и сроками; сами коды — только для писем."""
        now = datetime.now(UTC)
        code = self._security.new_otp_code()
        new_code = self._security.new_otp_code() if challenge.new_email is not None else None
        issued = dataclasses.replace(
            challenge,
            code_digest=self._security.otp_digest(challenge.challenge_id, code),
            new_code_digest=None
            if new_code is None
            else self._security.otp_digest(self._new_code_salt(challenge.challenge_id), new_code),
            code_expires_at=now + timedelta(seconds=cfg.auth.otp_code_ttl_seconds),
            resend_available_at=now + timedelta(seconds=cfg.auth.otp_resend_interval_seconds),
        )
        return issued, code, new_code

    @staticmethod
    def _new_code_salt(challenge_id: str) -> str:
        # код новой почты не подходит вместо кода текущей, и наоборот
        return f"{challenge_id}:new"

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

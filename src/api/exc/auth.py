from src.core.errors import (
    ConflictError,
    GoneError,
    NotFoundError,
    RateLimitedError,
    RuleViolationError,
    UnauthenticatedError,
)


class OtpInvalidError(UnauthenticatedError):
    code = "auth.otp_invalid"
    message = "Неверный код"


class OtpExpiredError(GoneError):
    code = "auth.otp_expired"
    message = "Срок действия кода истёк, запросите новый"


class ChallengeInvalidError(GoneError):
    code = "auth.challenge_invalid"
    message = "Код больше недействителен, начните вход заново"


class OtpRateLimitedError(RateLimitedError):
    code = "auth.otp_rate_limited"
    message = "Слишком много запросов кода, повторите позже"


class InvalidRefreshTokenError(UnauthenticatedError):
    code = "auth.invalid_refresh_token"
    message = "Сессия недействительна, войдите заново"


class RefreshTokenReusedError(UnauthenticatedError):
    code = "auth.refresh_token_reused"
    message = "Сессия отозвана, войдите заново"


class AccountNotFoundError(UnauthenticatedError):
    code = "auth.account_not_found"
    message = "Аккаунт не найден, войдите заново"


class EmailNotRegisteredError(NotFoundError):
    code = "auth.email_not_registered"
    message = "Аккаунта с этой почтой нет, зарегистрируйтесь"


class EmailTakenError(ConflictError):
    code = "auth.email_taken"
    message = "Эта почта уже зарегистрирована"


class EmailUnchangedError(RuleViolationError):
    code = "auth.email_unchanged"
    message = "Новая почта совпадает с текущей"

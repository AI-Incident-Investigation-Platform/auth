from src.core.errors import GoneError, RateLimitedError, UnauthenticatedError


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

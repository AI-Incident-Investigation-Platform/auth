from src.core.errors import ConflictError, RuleViolationError, UnauthenticatedError


class EmailAlreadyRegisteredError(ConflictError):
    code = "auth.email_already_registered"
    message = "Аккаунт с этой почтой уже зарегистрирован"


class InvalidCredentialsError(UnauthenticatedError):
    code = "auth.invalid_credentials"
    message = "Неверный email или пароль"


class AccountDeactivatedError(UnauthenticatedError):
    code = "auth.account_deactivated"
    message = "Аккаунт деактивирован"


class InvalidRefreshTokenError(UnauthenticatedError):
    code = "auth.invalid_refresh_token"
    message = "Сессия недействительна, войдите заново"


class RefreshTokenReusedError(UnauthenticatedError):
    code = "auth.refresh_token_reused"
    message = "Сессия отозвана, войдите заново"


class WrongCurrentPasswordError(RuleViolationError):
    code = "auth.wrong_current_password"
    message = "Неверный текущий пароль"


class AccountNotFoundError(UnauthenticatedError):
    code = "auth.account_not_found"
    message = "Аккаунт не найден, войдите заново"

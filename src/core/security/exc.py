from src.core.errors import CoreError, InternalError, OverloadedError, UnauthenticatedError


class NotAuthenticatedError(UnauthenticatedError):
    code = "security.not_authenticated"
    message = "Требуется вход в систему"


class MalformedRefreshTokenError(CoreError):
    code = "security.malformed_refresh_token"
    message = "Некорректный refresh-токен"


class SigningKeyUnavailableError(InternalError):
    code = "security.signing_key_unavailable"
    message = "Ключ подписи токенов не найден или повреждён"


class PasswordHashingOverloadedError(OverloadedError):
    code = "security.password_hashing_overloaded"
    message = "Сервис перегружен, повторите попытку через несколько секунд"

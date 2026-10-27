from src.core.errors import CoreError, ForbiddenError, InternalError, UnauthenticatedError


class NotAuthenticatedError(UnauthenticatedError):
    code = "security.not_authenticated"
    message = "Требуется вход в систему"


class MalformedRefreshTokenError(CoreError):
    code = "security.malformed_refresh_token"
    message = "Некорректный refresh-токен"


class SigningKeyUnavailableError(InternalError):
    code = "security.signing_key_unavailable"
    message = "Ключ подписи токенов не найден или повреждён"


class OriginForbiddenError(ForbiddenError):
    code = "security.origin_forbidden"
    message = "Запрос с этого адреса не принимается"

from src.core.errors import IntegrationUnavailableError


class CacheUnavailableError(IntegrationUnavailableError):
    code = "cache.unavailable"
    message = "Кэш недоступен"

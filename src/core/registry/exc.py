from src.core.errors import (
    IntegrationBadResponseError,
    IntegrationUnavailableError,
)


class RegistryUnavailableError(IntegrationUnavailableError):
    code = "registry.unavailable"
    message = "Реестр сервисов недоступен"


class RegistryBadResponseError(IntegrationBadResponseError):
    code = "registry.bad_response"
    message = "Реестр сервисов вернул ошибку"

from src.core.errors import (
    IntegrationBadResponseError,
    IntegrationUnavailableError,
    InternalError,
)


class RegistryUnavailableError(IntegrationUnavailableError):
    code = "registry.unavailable"
    message = "Реестр сервисов недоступен"


class RegistryBadResponseError(IntegrationBadResponseError):
    code = "registry.bad_response"
    message = "Реестр сервисов вернул ошибку"


class InstancePortBusyError(InternalError):
    code = "registry.port_busy"
    message = "Порт экземпляра уже занят другим процессом"

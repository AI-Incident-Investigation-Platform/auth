from src.core.errors import IntegrationTimeoutError, IntegrationUnavailableError


class EventsUnavailableError(IntegrationUnavailableError):
    code = "events.unavailable"
    message = "Сервис временно недоступен, повторите попытку позже"


class EventsTimeoutError(IntegrationTimeoutError):
    code = "events.timeout"
    message = "Сервис временно недоступен, повторите попытку позже"

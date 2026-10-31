from src.core.errors import IntegrationTimeoutError, IntegrationUnavailableError


class RabbitmqUnavailableError(IntegrationUnavailableError):
    code = "rabbitmq.unavailable"
    message = "Брокер сообщений недоступен"


class RabbitmqTimeoutError(IntegrationTimeoutError):
    code = "rabbitmq.timeout"
    message = "Брокер сообщений не ответил вовремя"

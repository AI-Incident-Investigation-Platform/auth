from src.core.errors import IntegrationTimeoutError, IntegrationUnavailableError


class EmailUnavailableError(IntegrationUnavailableError):
    code = "email.unavailable"
    message = "Не удалось отправить письмо, повторите попытку позже"


class EmailTimeoutError(IntegrationTimeoutError):
    code = "email.timeout"
    message = "Не удалось отправить письмо, повторите попытку позже"

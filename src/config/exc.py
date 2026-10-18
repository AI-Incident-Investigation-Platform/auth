from src.core.errors import InternalError


class ConfigIncompleteError(InternalError):
    code = "config.incomplete"
    message = "Не заданы обязательные настройки"

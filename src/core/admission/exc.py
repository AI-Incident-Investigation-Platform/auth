from src.core.errors import OverloadedError


class ServiceOverloadedError(OverloadedError):
    code = "service.overloaded"
    message = "Сервис перегружен, повторите запрос через несколько секунд"

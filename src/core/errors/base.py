from collections.abc import Mapping
from typing import ClassVar

from src.core.errors.enums import ErrorLayer


class AppError(Exception):
    code: ClassVar[str] = "app.error"
    message: ClassVar[str] = "Ошибка приложения"
    layer: ClassVar[ErrorLayer | None] = None

    def __init__(
        self,
        context: Mapping[str, object] | None = None,
        details: Mapping[str, object] | None = None,
    ) -> None:
        """Ошибка приложения.

        Args:
            context: безопасные поля для лога, клиенту не уходят.
            details: поля для клиента в `error.details`; только ID, enum и числа.
        """
        super().__init__(self.message)
        self.context: dict[str, object] = dict(context or {})
        self.details: dict[str, object] = dict(details or {})


class DomainError(AppError):
    layer = ErrorLayer.DOMAIN


class NotFoundError(DomainError):
    pass


class ConflictError(DomainError):
    pass


class RuleViolationError(DomainError):
    pass


class ForbiddenError(DomainError):
    pass


class GoneError(DomainError):
    """Объект был, но больше недействителен: клиент начинает операцию заново."""


class RateLimitedError(DomainError):
    """Клиент превысил лимит; повтор — не раньше `retry_after_seconds`."""

    def __init__(
        self,
        retry_after_seconds: int,
        context: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(context)
        self.retry_after_seconds = max(retry_after_seconds, 1)


class UnauthenticatedError(AppError):
    pass


class CoreError(AppError):
    layer = ErrorLayer.CORE


class IntegrationError(AppError):
    layer = ErrorLayer.INTEGRATION


class IntegrationUnavailableError(IntegrationError):
    pass


class IntegrationTimeoutError(IntegrationError):
    pass


class IntegrationBadResponseError(IntegrationError):
    pass


class PersistenceError(AppError):
    layer = ErrorLayer.DB


class PersistenceUnavailableError(PersistenceError):
    pass


class PersistenceConflictError(PersistenceError):
    pass


class OverloadedError(AppError):
    """Сервис сейчас не принимает работу, клиент повторяет запрос позже."""

    layer = ErrorLayer.CORE


class InternalError(AppError):
    code = "internal_error"
    message = "Внутренняя ошибка сервера"

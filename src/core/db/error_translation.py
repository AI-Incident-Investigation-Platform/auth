from typing import Any

from sqlalchemy.engine import Dialect, ExceptionContext
from sqlalchemy.exc import IntegrityError, InterfaceError, OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError
from sqlalchemy.pool import AsyncAdaptedQueuePool, ConnectionPoolEntry, PoolProxiedConnection

from src.core.db.exc import DatabaseUnavailableError, IntegrityViolationError

# statement_timeout и lock_timeout: БД не успела ответить в отведённое время.
TIMEOUT_SQLSTATES = frozenset({"57014", "55P03"})


class DatabaseErrorTranslator:
    @staticmethod
    def on_connect(
        dialect: Dialect,
        conn_rec: ConnectionPoolEntry,
        cargs: tuple[Any, ...],
        cparams: dict[str, Any],
    ) -> Any:
        try:
            return dialect.connect(*cargs, **cparams)
        except (OSError, dialect.loaded_dbapi.Error) as exc:
            raise DatabaseUnavailableError from exc

    @staticmethod
    def on_error(context: ExceptionContext) -> BaseException | None:
        error = context.sqlalchemy_exception
        if isinstance(error, IntegrityError):
            constraint = getattr(context.original_exception.__cause__, "constraint_name", None)
            return IntegrityViolationError(constraint)
        sqlstate = getattr(context.original_exception.__cause__, "sqlstate", None)
        if (
            context.is_disconnect
            or isinstance(error, OperationalError | InterfaceError)
            or sqlstate in TIMEOUT_SQLSTATES
        ):
            return DatabaseUnavailableError()
        return None


class TranslatingPool(AsyncAdaptedQueuePool):
    """Пул, у которого исчерпание соединений — недоступность БД, а не 500.

    Таймаут ожидания соединения возникает до выполнения запроса, `handle_error` его не видит.
    """

    def connect(self) -> PoolProxiedConnection:
        try:
            return super().connect()
        except PoolTimeoutError as exc:
            raise DatabaseUnavailableError from exc

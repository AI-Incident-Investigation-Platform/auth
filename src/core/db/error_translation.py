from typing import Any

from sqlalchemy.engine import Dialect, ExceptionContext
from sqlalchemy.exc import IntegrityError, InterfaceError, OperationalError
from sqlalchemy.pool import ConnectionPoolEntry

from src.core.db.exc import DatabaseUnavailableError, IntegrityViolationError


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
        if context.is_disconnect or isinstance(error, OperationalError | InterfaceError):
            return DatabaseUnavailableError()
        return None

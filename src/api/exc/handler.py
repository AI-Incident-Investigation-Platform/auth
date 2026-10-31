import dataclasses
import logging
import time
from collections.abc import Mapping
from http import HTTPStatus

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from src.api.exc.auth import RefreshTokenReusedError
from src.config import cfg
from src.core.context import REQUEST_ID_HEADER, get_trace_id, log_context
from src.core.errors import (
    AppError,
    ConflictError,
    DomainError,
    ErrorLayer,
    ErrorReport,
    ForbiddenError,
    GoneError,
    IntegrationBadResponseError,
    IntegrationError,
    IntegrationTimeoutError,
    IntegrationUnavailableError,
    InternalError,
    NotFoundError,
    OverloadedError,
    PersistenceUnavailableError,
    RateLimitedError,
    RuleViolationError,
    UnauthenticatedError,
)
from src.core.metrics import APP_ERRORS

log = logging.getLogger(__name__)


class ApiErrorHandler:
    @staticmethod
    def register(app: FastAPI) -> None:
        app.add_exception_handler(AppError, ApiErrorHandler.handle_app_error)
        app.add_exception_handler(RequestValidationError, ApiErrorHandler.handle_validation_error)
        app.add_exception_handler(StarletteHTTPException, ApiErrorHandler.handle_http_exception)
        app.add_exception_handler(Exception, ApiErrorHandler.handle_unexpected)

    @staticmethod
    async def handle_app_error(request: Request, exc: Exception) -> JSONResponse:
        if not isinstance(exc, AppError):
            return await ApiErrorHandler.handle_unexpected(request, exc)

        report = ErrorReport.from_exception(exc)
        status = ApiErrorHandler._status_for(exc)
        ApiErrorHandler._record(request, report, status, ApiErrorHandler._level_for(exc), exc)

        if isinstance(exc, OverloadedError):
            return ApiErrorHandler._respond(
                status,
                exc.code,
                exc.message,
                headers={"Retry-After": str(cfg.service.overload_retry_after_seconds)},
            )
        if isinstance(exc, RateLimitedError):
            return ApiErrorHandler._respond(
                status,
                exc.code,
                exc.message,
                details=exc.details,
                headers={"Retry-After": str(exc.retry_after_seconds)},
            )
        if isinstance(exc, DomainError | UnauthenticatedError):
            return ApiErrorHandler._respond(status, exc.code, exc.message, details=exc.details)
        if isinstance(exc, IntegrationError | PersistenceUnavailableError):
            return ApiErrorHandler._respond(status, exc.code, exc.message)
        return ApiErrorHandler._respond(status, InternalError.code, InternalError.message)

    @staticmethod
    async def handle_validation_error(request: Request, exc: Exception) -> JSONResponse:
        if not isinstance(exc, RequestValidationError):
            return await ApiErrorHandler.handle_unexpected(request, exc)

        fields = [
            {"loc": list(error["loc"]), "type": error["type"], "msg": error["msg"]}
            for error in exc.errors()
        ]
        report = dataclasses.replace(
            ErrorReport.from_exception(exc), code="request.invalid", layer=ErrorLayer.HTTP
        )
        status = HTTPStatus.UNPROCESSABLE_ENTITY
        ApiErrorHandler._record(request, report, status, logging.INFO, exc, {"fields": fields})
        errors = [
            {"field": ".".join(str(part) for part in field["loc"]), "message": field["msg"]}
            for field in fields
        ]
        return ApiErrorHandler._respond(
            status, report.code, "Некорректные параметры запроса", details={"errors": errors}
        )

    @staticmethod
    async def handle_http_exception(request: Request, exc: Exception) -> JSONResponse:
        if not isinstance(exc, StarletteHTTPException):
            return await ApiErrorHandler.handle_unexpected(request, exc)

        status = HTTPStatus(exc.status_code)
        report = dataclasses.replace(
            ErrorReport.from_exception(exc), code=f"http.{status.value}", layer=ErrorLayer.HTTP
        )
        level = logging.ERROR if status >= HTTPStatus.INTERNAL_SERVER_ERROR else logging.INFO
        ApiErrorHandler._record(request, report, status, level, exc)
        message = exc.detail if isinstance(exc.detail, str) else status.phrase
        return ApiErrorHandler._respond(status, report.code, message, headers=exc.headers)

    @staticmethod
    async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        report = ErrorReport.from_exception(exc)
        status = HTTPStatus.INTERNAL_SERVER_ERROR
        ApiErrorHandler._record(request, report, status, logging.ERROR, exc)
        request_id = str(
            request.scope.get("state", {}).get("log_context", {}).get("trace_id", get_trace_id())
        )
        return ApiErrorHandler._respond(
            status,
            InternalError.code,
            InternalError.message,
            headers={REQUEST_ID_HEADER: request_id},
            request_id=request_id,
        )

    @staticmethod
    def _status_for(exc: AppError) -> HTTPStatus:
        match exc:
            case UnauthenticatedError():
                return HTTPStatus.UNAUTHORIZED
            case NotFoundError():
                return HTTPStatus.NOT_FOUND
            case ConflictError():
                return HTTPStatus.CONFLICT
            case RuleViolationError():
                return HTTPStatus.UNPROCESSABLE_ENTITY
            case ForbiddenError():
                return HTTPStatus.FORBIDDEN
            case GoneError():
                return HTTPStatus.GONE
            case RateLimitedError():
                return HTTPStatus.TOO_MANY_REQUESTS
            case DomainError():
                return HTTPStatus.BAD_REQUEST
            case IntegrationTimeoutError():
                return HTTPStatus.GATEWAY_TIMEOUT
            case IntegrationUnavailableError() | PersistenceUnavailableError() | OverloadedError():
                return HTTPStatus.SERVICE_UNAVAILABLE
            case IntegrationBadResponseError() | IntegrationError():
                return HTTPStatus.BAD_GATEWAY
            case _:
                return HTTPStatus.INTERNAL_SERVER_ERROR

    @staticmethod
    def _level_for(exc: AppError) -> int:
        match exc:
            case RefreshTokenReusedError():
                return logging.WARNING
            case DomainError() | UnauthenticatedError():
                return logging.INFO
            case IntegrationError() | PersistenceUnavailableError() | OverloadedError():
                return logging.WARNING
            case _:
                return logging.ERROR

    @staticmethod
    def _record(
        request: Request,
        report: ErrorReport,
        status: HTTPStatus,
        level: int,
        exc: Exception,
        details: dict[str, object] | None = None,
    ) -> None:
        APP_ERRORS.labels(
            report.layer.value, report.code, str(status.value), str(report.untranslated).lower()
        ).inc()
        error = {**report.to_log(), "status": status.value}
        if details:
            error["details"] = details
        state = request.scope.setdefault("state", {})
        state["error_logged"] = True
        duration_ms = state.get("request_duration_ms")
        if duration_ms is None and (started_at := state.get("request_started_at")) is not None:
            duration_ms = round((time.monotonic() - started_at) * 1000)
        if isinstance(exc, RefreshTokenReusedError):
            message = "Обнаружено повторное использование refresh-токена. Сессия отозвана"
        elif isinstance(exc, AppError):
            message = exc.message
        elif isinstance(exc, RequestValidationError):
            message = "Некорректные параметры запроса"
        elif status >= HTTPStatus.INTERNAL_SERVER_ERROR:
            message = "Не удалось обработать запрос"
        else:
            message = "Запрос отклонён"
        token = log_context.set(state.get("log_context"))
        try:
            log.log(
                level,
                message,
                exc_info=exc if level >= logging.ERROR else None,
                extra={
                    "event": "http.error",
                    "error": jsonable_encoder(error),
                    "http": {
                        "method": request.method,
                        "path": request.url.path,
                        "status_code": status.value,
                        "duration_ms": duration_ms,
                    },
                },
            )
        finally:
            log_context.reset(token)

    @staticmethod
    def _respond(
        status: HTTPStatus,
        code: str,
        message: str,
        details: Mapping[str, object] | None = None,
        headers: Mapping[str, str] | None = None,
        request_id: str | None = None,
    ) -> JSONResponse:
        error: dict[str, object] = {
            "code": code,
            "message": message,
            "request_id": request_id if request_id is not None else get_trace_id(),
        }
        if details:
            error["details"] = jsonable_encoder(details)
        return JSONResponse(status_code=status.value, content={"error": error}, headers=headers)

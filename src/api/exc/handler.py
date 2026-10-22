import dataclasses
import logging
from collections.abc import Mapping
from http import HTTPStatus

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from src.core.context import REQUEST_ID_HEADER, get_trace_id
from src.core.errors import (
    AppError,
    ConflictError,
    DomainError,
    ErrorLayer,
    ErrorReport,
    ForbiddenError,
    IntegrationBadResponseError,
    IntegrationError,
    IntegrationTimeoutError,
    IntegrationUnavailableError,
    InternalError,
    NotFoundError,
    PersistenceUnavailableError,
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

        if isinstance(
            exc, DomainError | UnauthenticatedError | IntegrationError | PersistenceUnavailableError
        ):
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
            status, report.code, "Некорректные параметры запроса", errors=errors
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
        return ApiErrorHandler._respond(
            status,
            InternalError.code,
            InternalError.message,
            headers={REQUEST_ID_HEADER: get_trace_id()},
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
            case DomainError():
                return HTTPStatus.BAD_REQUEST
            case IntegrationTimeoutError():
                return HTTPStatus.GATEWAY_TIMEOUT
            case IntegrationUnavailableError() | PersistenceUnavailableError():
                return HTTPStatus.SERVICE_UNAVAILABLE
            case IntegrationBadResponseError() | IntegrationError():
                return HTTPStatus.BAD_GATEWAY
            case _:
                return HTTPStatus.INTERNAL_SERVER_ERROR

    @staticmethod
    def _level_for(exc: AppError) -> int:
        match exc:
            case DomainError() | UnauthenticatedError():
                return logging.INFO
            case IntegrationError() | PersistenceUnavailableError():
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
        log.log(
            level,
            "http.error",
            exc_info=exc if level >= logging.ERROR else None,
            extra={
                "error": jsonable_encoder(error),
                "http": {"method": request.method, "path": request.url.path},
            },
        )

    @staticmethod
    def _respond(
        status: HTTPStatus,
        code: str,
        detail: str,
        errors: list[dict[str, str]] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> JSONResponse:
        content: dict[str, object] = {
            "type": "about:blank",
            "title": status.phrase,
            "status": status.value,
            "code": code,
            "detail": detail,
            "request_id": get_trace_id(),
        }
        if errors:
            content["errors"] = errors
        return JSONResponse(
            status_code=status.value,
            content=content,
            headers=headers,
            media_type="application/problem+json",
        )

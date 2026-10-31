import logging
import time

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from src.config import cfg
from src.core.context import REQUEST_ID_HEADER, get_span_id, get_trace_id, log_context
from src.core.metrics import UNOBSERVED_PATHS

log = logging.getLogger(__name__)


class RequestLoggingMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] in UNOBSERVED_PATHS:
            await self.app(scope, receive, send)
            return

        start = time.monotonic()
        context: dict[str, object] = {"trace_id": get_trace_id(), "span_id": get_span_id()}
        state = scope.setdefault("state", {})
        state["log_context"] = context
        state["request_started_at"] = start
        token = log_context.set(context)
        status_holder: dict[str, int] = {}

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
                message.setdefault("headers", []).append(
                    (REQUEST_ID_HEADER.encode(), str(context["trace_id"]).encode())
                )
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
            if state.get("error_logged"):
                return
            status_code = status_holder.get("status", 0)
            duration_ms = round((time.monotonic() - start) * 1000)
            if status_code >= 500:
                level = logging.ERROR
                message = "Запрос завершился ошибкой сервера"
            elif status_code >= 400:
                level = logging.INFO
                message = "Запрос отклонён"
            elif duration_ms >= cfg.logging.slow_request_ms:
                level = logging.WARNING
                message = "Запрос обработан медленно"
            else:
                level = logging.DEBUG
                message = "Запрос обработан"
            log.log(
                level,
                message,
                extra={
                    "event": "http.request",
                    "http": {
                        "method": scope["method"],
                        "path": scope["path"],
                        "status_code": status_code,
                        "duration_ms": duration_ms,
                    },
                },
            )
        finally:
            # Неожиданную ошибку обработает внешний ServerErrorMiddleware.
            state["request_duration_ms"] = round((time.monotonic() - start) * 1000)
            log_context.reset(token)

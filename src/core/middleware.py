import logging
import time

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from src.core.context import get_trace_id

log = logging.getLogger(__name__)


class RequestLoggingMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] in {"/health", "/ready"}:
            await self.app(scope, receive, send)
            return

        start = time.monotonic()
        status_holder: dict[str, int] = {}

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
                message.setdefault("headers", []).append((b"x-trace-id", get_trace_id().encode()))
            await send(message)

        await self.app(scope, receive, send_wrapper)

        status_code = status_holder.get("status", 0)
        if status_code >= 500:
            level = logging.ERROR
        elif status_code >= 400:
            level = logging.WARNING
        else:
            level = logging.INFO
        log.log(
            level,
            "http.request_completed",
            extra={
                "http": {
                    "method": scope["method"],
                    "path": scope["path"],
                    "status_code": status_code,
                    "duration_ms": round((time.monotonic() - start) * 1000),
                }
            },
        )

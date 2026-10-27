from collections.abc import Awaitable, Callable

from starlette.datastructures import Headers
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp, Receive, Scope, Send

from src.config import cfg
from src.core.security.exc import OriginForbiddenError


class OriginMiddleware:
    """CSRF-защита cookie-сессии: изменяющий запрос к /api принимается только с разрешённого Origin.

    Вызов другого сервиса несёт токен в Authorization, а не в куке, — его Origin не проверяется.
    Ответ об отказе строит обработчик ошибок приложения, переданный в `reject`.
    """

    def __init__(
        self, app: ASGIApp, reject: Callable[[Request, Exception], Awaitable[Response]]
    ) -> None:
        self.app = app
        self._reject = reject

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope["method"] not in {"POST", "PUT", "PATCH", "DELETE"}
            or not scope["path"].startswith("/api/")
        ):
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        origin = headers.get("origin")
        if "authorization" in headers or origin in cfg.auth.allowed_origins:
            await self.app(scope, receive, send)
            return
        error = OriginForbiddenError({"origin": origin})
        response = await self._reject(Request(scope, receive), error)
        await response(scope, receive, send)

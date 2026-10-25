from collections.abc import Awaitable, Callable

from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp, Receive, Scope, Send

from src.config import cfg
from src.core.admission.exc import ServiceOverloadedError
from src.core.admission.metrics import ADMISSION_CAPACITY
from src.core.metrics import UNOBSERVED_PATHS


class AdmissionMiddleware:
    """Предел одновременных запросов процесса: сверх него запрос сразу получает отказ.

    Без предела очередь копит запросы в памяти, держит транзакции и выводит под за лимит.
    Ответ об отказе строит обработчик ошибок приложения, переданный в `reject`.
    """

    def __init__(
        self, app: ASGIApp, reject: Callable[[Request, Exception], Awaitable[Response]]
    ) -> None:
        self.app = app
        self._reject = reject
        self._in_flight = 0
        ADMISSION_CAPACITY.set(cfg.service.max_concurrent_requests)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] in UNOBSERVED_PATHS:
            await self.app(scope, receive, send)
            return
        if self._in_flight >= cfg.service.max_concurrent_requests:
            error = ServiceOverloadedError({"in_flight": self._in_flight})
            response = await self._reject(Request(scope, receive), error)
            await response(scope, receive, send)
            return
        self._in_flight += 1
        try:
            await self.app(scope, receive, send)
        finally:
            self._in_flight -= 1

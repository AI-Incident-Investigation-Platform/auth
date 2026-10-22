import time

from fastapi.routing import iter_route_contexts
from prometheus_client import Counter, Gauge, Histogram
from starlette.routing import Match
from starlette.types import ASGIApp, Message, Receive, Scope, Send

UNMATCHED_PATH = "unmatched"
UNOBSERVED_PATHS = frozenset({"/health", "/ready", "/metrics"})

HTTP_REQUESTS = Counter(
    "http_requests_total", "Завершённые HTTP-запросы", ["method", "path", "status"]
)
HTTP_REQUEST_DURATION = Histogram(
    "http_request_duration_seconds",
    "Длительность HTTP-запроса",
    ["method", "path"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)
HTTP_REQUESTS_ACTIVE = Gauge("http_requests_active", "HTTP-запросы в обработке", ["method"])
APP_ERRORS = Counter(
    "app_errors_total", "Ошибки, отданные клиенту", ["layer", "code", "status", "untranslated"]
)


class MetricsMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] in UNOBSERVED_PATHS:
            await self.app(scope, receive, send)
            return

        method = scope["method"]
        status_holder: dict[str, int] = {}

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
            await send(message)

        start = time.perf_counter()
        HTTP_REQUESTS_ACTIVE.labels(method).inc()
        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            HTTP_REQUESTS_ACTIVE.labels(method).dec()
            path = self._route_path(scope)
            HTTP_REQUEST_DURATION.labels(method, path).observe(time.perf_counter() - start)
            HTTP_REQUESTS.labels(method, path, str(status_holder.get("status", 500))).inc()

    @staticmethod
    def _route_path(scope: Scope) -> str:
        for route in iter_route_contexts(scope["app"].routes):
            match, _ = route.matches(scope)
            if match != Match.NONE:
                return route.path or UNMATCHED_PATH
        return UNMATCHED_PATH

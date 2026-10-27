import asyncio
import io
import json
import logging
from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.trace import TracerProvider

from src.api.exc.auth import RefreshTokenReusedError
from src.api.exc.handler import ApiErrorHandler
from src.config import cfg
from src.core.context import bind_log_identity
from src.core.logging import StructuredJsonFormatter
from src.core.middleware import RequestLoggingMiddleware


@pytest.fixture
def logs() -> Iterator[io.StringIO]:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(StructuredJsonFormatter())
    logger = logging.getLogger("src")
    previous_level = logger.level
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    try:
        yield stream
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)


@pytest.mark.case(id="API-LOG-001")
async def test_error_logged_once_with_trace_duration_and_safe_stack(logs: io.StringIO) -> None:
    app = FastAPI()
    app.add_middleware(RequestLoggingMiddleware)
    ApiErrorHandler.register(app)

    @app.get("/crash")
    async def crash() -> None:
        bind_log_identity("user-1", "session-1")
        try:
            raise ValueError("password=secret")
        except ValueError as exc:
            raise RuntimeError("token=secret") from exc

    provider = TracerProvider()
    FastAPIInstrumentor.instrument_app(app, tracer_provider=provider)
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/crash")

    entries = [json.loads(line) for line in logs.getvalue().splitlines()]
    assert len(entries) == 1
    entry = entries[0]
    assert entry["message"] == "Не удалось обработать запрос"
    assert entry["level"] == "ERROR"
    assert len(entry["trace_id"]) == 32
    assert len(entry["span_id"]) == 16
    assert response.json()["error"]["request_id"] == entry["trace_id"]
    assert entry["user_id"] == "user-1"
    assert entry["session_id"] == "session-1"
    assert entry["http"]["status_code"] == 500
    assert entry["http"]["duration_ms"] >= 0
    assert "RuntimeError" in entry["exception"]
    assert "ValueError" in entry["exception"]
    assert " in crash" in entry["exception"]
    assert "secret" not in logs.getvalue()
    provider.shutdown()


@pytest.mark.case(id="API-LOG-002")
async def test_refresh_reuse_is_one_warning(logs: io.StringIO) -> None:
    app = FastAPI()
    app.add_middleware(RequestLoggingMiddleware)
    ApiErrorHandler.register(app)

    @app.post("/refresh")
    async def refresh() -> None:
        bind_log_identity("user-1", "session-1")
        raise RefreshTokenReusedError({"session_id": "session-1"})

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post("/refresh")

    entries = [json.loads(line) for line in logs.getvalue().splitlines()]
    assert response.status_code == 401
    assert len(entries) == 1
    assert entries[0]["level"] == "WARNING"
    assert entries[0]["error"]["code"] == "auth.refresh_token_reused"
    assert entries[0]["user_id"] == "user-1"
    assert "Сессия отозвана" in entries[0]["message"]


@pytest.mark.case(id="API-LOG-003")
async def test_parallel_requests_keep_identity_and_successful_http_is_quiet(
    logs: io.StringIO,
) -> None:
    app = FastAPI()
    app.add_middleware(RequestLoggingMiddleware)
    both_started = asyncio.Event()
    started: list[str] = []

    @app.get("/users/{user_id}")
    async def user(user_id: str) -> None:
        bind_log_identity(user_id)
        started.append(user_id)
        if len(started) == 2:
            both_started.set()
        await asyncio.wait_for(both_started.wait(), timeout=2)
        logging.getLogger("src.test").info("Действие пользователя выполнено")

    @app.get("/profile")
    async def profile() -> None:
        return None

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        responses = await asyncio.gather(client.get("/users/one"), client.get("/users/two"))
        assert all(response.status_code == 200 for response in responses)
        assert (await client.get("/profile")).status_code == 200
    logging.getLogger("src.test").info("Фоновая операция завершена")
    entries = [json.loads(line) for line in logs.getvalue().splitlines()]
    assert len(entries) == 3
    assert {entry["user_id"] for entry in entries[:2]} == {"one", "two"}
    assert "user_id" not in entries[2]


@pytest.mark.case(id="API-LOG-004")
def test_formatter_protects_fields_and_uses_current_span(logs: io.StringIO) -> None:
    provider = TracerProvider()
    span = provider.get_tracer(__name__).start_span("operation")
    with trace.use_span(span, end_on_exit=True):
        logging.getLogger("src.test").info(
            "Операция завершена",
            extra={"level": "ERROR", "timestamp": "wrong", "service": "wrong", "count": 2},
        )
    entry = json.loads(logs.getvalue())
    assert entry["level"] == "INFO"
    assert entry["timestamp"] != "wrong"
    assert entry["service"] != "wrong"
    assert entry["count"] == 2
    assert entry["span_id"] == format(span.get_span_context().span_id, "016x")
    provider.shutdown()


@pytest.mark.case(id="API-LOG-005")
async def test_slow_successful_request_is_warning(
    logs: io.StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cfg.logging, "slow_request_ms", 0)
    app = FastAPI()
    app.add_middleware(RequestLoggingMiddleware)

    @app.get("/slow")
    async def slow() -> None:
        return None

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        assert (await client.get("/slow")).status_code == 200
    entry = json.loads(logs.getvalue())
    assert entry["level"] == "WARNING"
    assert entry["message"] == "Запрос обработан медленно"
    assert entry["http"]["status_code"] == 200
    assert entry["http"]["duration_ms"] >= 0

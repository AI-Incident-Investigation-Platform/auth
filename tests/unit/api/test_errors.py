from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel

from src.api.exc import handler
from src.api.exc.handler import ApiErrorHandler
from src.config import cfg
from src.core import middleware
from src.core.errors import ConflictError, OverloadedError
from src.core.middleware import RequestLoggingMiddleware

TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"


class EmailTakenError(ConflictError):
    code = "test.email_taken"
    message = "Почта уже занята"


class BusyError(OverloadedError):
    code = "test.busy"
    message = "Сервис перегружен"


class Payload(BaseModel):
    email: str


def build_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestLoggingMiddleware)
    ApiErrorHandler.register(app)

    @app.post("/conflict")
    async def conflict() -> None:
        raise EmailTakenError({"user_id": "internal"})

    @app.post("/busy")
    async def busy() -> None:
        raise BusyError

    @app.post("/validate")
    async def validate(payload: Payload) -> None:
        return None

    @app.post("/crash")
    async def crash() -> None:
        raise RuntimeError("password=secret")

    return app


@pytest.fixture
async def client(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncClient]:
    monkeypatch.setattr(handler, "get_trace_id", lambda: TRACE_ID)
    monkeypatch.setattr(middleware, "get_trace_id", lambda: TRACE_ID)
    transport = ASGITransport(app=build_app(), raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


@pytest.mark.case(id="API-ERROR-001")
async def test_domain_error_is_problem_json_with_request_id(client: AsyncClient) -> None:
    response = await client.post("/conflict")

    assert response.status_code == 409
    assert response.headers["content-type"] == "application/problem+json"
    assert response.headers["x-request-id"] == TRACE_ID
    assert response.json() == {
        "type": "about:blank",
        "title": "Conflict",
        "status": 409,
        "code": "test.email_taken",
        "detail": "Почта уже занята",
        "request_id": TRACE_ID,
    }


@pytest.mark.case(id="API-ERROR-002")
async def test_validation_error_lists_fields_in_errors(client: AsyncClient) -> None:
    response = await client.post("/validate", json={})

    body = response.json()
    assert response.status_code == 422
    assert body["code"] == "request.invalid"
    assert body["request_id"] == TRACE_ID
    assert body["errors"] == [{"field": "body.email", "message": "Field required"}]


@pytest.mark.case(id="API-ERROR-003")
async def test_unexpected_error_hides_internals_and_keeps_request_id(
    client: AsyncClient,
) -> None:
    response = await client.post("/crash")

    body = response.json()
    assert response.status_code == 500
    assert response.headers["x-request-id"] == TRACE_ID
    assert body["code"] == "internal_error"
    assert body["detail"] == "Внутренняя ошибка сервера"
    assert body["request_id"] == TRACE_ID
    assert "secret" not in response.text


@pytest.mark.case(id="API-ERROR-004")
async def test_overload_is_503_with_retry_after(client: AsyncClient) -> None:
    response = await client.post("/busy")

    assert response.status_code == 503
    assert response.headers["retry-after"] == str(cfg.service.overload_retry_after_seconds)
    assert response.json()["code"] == "test.busy"
    assert response.json()["detail"] == "Сервис перегружен"

from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel

from src.api.exc import handler
from src.api.exc.handler import ApiErrorHandler
from src.config import cfg
from src.core import middleware
from src.core.errors import ConflictError, GoneError, OverloadedError, RateLimitedError
from src.core.middleware import RequestLoggingMiddleware

TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"


class EmailTakenError(ConflictError):
    code = "test.email_taken"
    message = "Почта уже занята"


class BusyError(OverloadedError):
    code = "test.busy"
    message = "Сервис перегружен"


class TooOftenError(RateLimitedError):
    code = "test.too_often"
    message = "Слишком часто"


class ExpiredError(GoneError):
    code = "test.expired"
    message = "Срок истёк"


class Payload(BaseModel):
    email: str


def build_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestLoggingMiddleware)
    ApiErrorHandler.register(app)

    @app.post("/conflict")
    async def conflict() -> None:
        raise EmailTakenError({"user_id": "internal"}, {"field": "email"})

    @app.post("/busy")
    async def busy() -> None:
        raise BusyError

    @app.post("/limited")
    async def limited() -> None:
        raise TooOftenError(42)

    @app.post("/gone")
    async def gone() -> None:
        raise ExpiredError

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
async def test_domain_error_is_error_envelope_with_request_id(client: AsyncClient) -> None:
    response = await client.post("/conflict")

    assert response.status_code == 409
    assert response.headers["content-type"] == "application/json"
    assert response.headers["x-request-id"] == TRACE_ID
    assert response.json() == {
        "error": {
            "code": "test.email_taken",
            "message": "Почта уже занята",
            "request_id": TRACE_ID,
            "details": {"field": "email"},
        }
    }


@pytest.mark.case(id="API-ERROR-002")
async def test_validation_error_lists_fields_in_errors(client: AsyncClient) -> None:
    response = await client.post("/validate", json={})

    body = response.json()["error"]
    assert response.status_code == 422
    assert body["code"] == "request.invalid"
    assert body["request_id"] == TRACE_ID
    assert body["details"] == {"errors": [{"field": "body.email", "message": "Field required"}]}


@pytest.mark.case(id="API-ERROR-003")
async def test_unexpected_error_hides_internals_and_keeps_request_id(
    client: AsyncClient,
) -> None:
    response = await client.post("/crash")

    body = response.json()["error"]
    assert response.status_code == 500
    assert response.headers["x-request-id"] == TRACE_ID
    assert body["code"] == "internal_error"
    assert body["message"] == "Внутренняя ошибка сервера"
    assert body["request_id"] == TRACE_ID
    assert "secret" not in response.text


@pytest.mark.case(id="API-ERROR-004")
async def test_overload_is_503_with_retry_after(client: AsyncClient) -> None:
    response = await client.post("/busy")

    assert response.status_code == 503
    assert response.headers["retry-after"] == str(cfg.service.overload_retry_after_seconds)
    assert response.json()["error"]["code"] == "test.busy"
    assert response.json()["error"]["message"] == "Сервис перегружен"


@pytest.mark.case(id="API-ERROR-005")
async def test_rate_limit_is_429_with_retry_after_and_expiry_is_410(client: AsyncClient) -> None:
    limited = await client.post("/limited")
    gone = await client.post("/gone")

    assert limited.status_code == 429
    assert limited.headers["retry-after"] == "42"
    assert limited.json()["error"]["code"] == "test.too_often"
    assert gone.status_code == 410
    assert gone.json()["error"]["code"] == "test.expired"

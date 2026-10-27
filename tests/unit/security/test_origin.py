from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.api.exc.handler import ApiErrorHandler
from src.config import cfg
from src.core.security.origin import OriginMiddleware


def build_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(OriginMiddleware, reject=ApiErrorHandler.handle_app_error)
    ApiErrorHandler.register(app)

    @app.post("/api/v1/things")
    async def create() -> None:
        return None

    @app.get("/api/v1/things")
    async def read() -> None:
        return None

    return app


@pytest.fixture
async def client(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncClient]:
    monkeypatch.setattr(cfg.auth, "allowed_origins", ["https://aiip.example"])
    async with AsyncClient(
        transport=ASGITransport(app=build_app()), base_url="http://testserver"
    ) as c:
        yield c


@pytest.mark.case(id="AUTH-ORIGIN-001")
async def test_state_changing_request_requires_allowed_origin(client: AsyncClient) -> None:
    missing = await client.post("/api/v1/things")
    foreign = await client.post("/api/v1/things", headers={"Origin": "https://evil.example"})
    allowed = await client.post("/api/v1/things", headers={"Origin": "https://aiip.example"})
    service_call = await client.post("/api/v1/things", headers={"Authorization": "Bearer x"})
    read = await client.get("/api/v1/things")

    assert missing.status_code == foreign.status_code == 403
    assert missing.json()["error"]["code"] == "security.origin_forbidden"
    assert allowed.status_code == service_call.status_code == read.status_code == 200

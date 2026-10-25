import asyncio
from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.api.exc.handler import ApiErrorHandler
from src.config import cfg
from src.core.admission.middleware import AdmissionMiddleware
from src.core.middleware import RequestLoggingMiddleware


@pytest.fixture
async def gate_and_client(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[tuple[asyncio.Event, AsyncClient]]:
    monkeypatch.setattr(cfg.service, "max_concurrent_requests", 1)
    gate = asyncio.Event()
    app = FastAPI()
    app.add_middleware(AdmissionMiddleware, reject=ApiErrorHandler.handle_app_error)
    app.add_middleware(RequestLoggingMiddleware)
    ApiErrorHandler.register(app)

    @app.get("/slow")
    async def slow() -> None:
        await gate.wait()

    @app.get("/ready")
    async def ready() -> None:
        return None

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield gate, client


@pytest.mark.case(id="API-ADMISSION-001")
async def test_request_over_limit_is_rejected_and_slot_is_freed(
    gate_and_client: tuple[asyncio.Event, AsyncClient],
) -> None:
    gate, client = gate_and_client

    first = asyncio.create_task(client.get("/slow"))
    await asyncio.sleep(0.05)
    rejected = await client.get("/slow")
    probe = await client.get("/ready")
    gate.set()
    accepted = await first
    after = await client.get("/slow")

    assert rejected.status_code == 503
    assert rejected.headers["retry-after"] == str(cfg.service.overload_retry_after_seconds)
    assert rejected.headers["content-type"] == "application/problem+json"
    assert rejected.json()["code"] == "service.overloaded"
    assert probe.status_code == 200
    assert accepted.status_code == 200
    assert after.status_code == 200

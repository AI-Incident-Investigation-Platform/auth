import asyncio
import logging

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from tests.support.auth import Account, client_with_cookies, error_code, register


@pytest.mark.case(id="AUTH-REGISTER-001")
async def test_registration_signs_in_with_normalized_email(
    client: AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="src")
    response = await register(client, "New.User@Example.COM", "password-1")

    assert response.status_code == 201
    assert response.json()["email"] == "new.user@example.com"
    assert set(response.json()) == {"id", "email", "created_at"}
    assert {"access_token", "refresh_token"} <= set(client.cookies.keys())
    assert (await client.get("/api/auth/me")).status_code == 200
    events = [record for record in caplog.records if record.name == "src.api.auth.service"]
    assert len(events) == 1
    assert events[0].message == "Пользователь зарегистрирован"
    assert events[0].__dict__["user_id"] == response.json()["id"]
    assert events[0].__dict__["session_id"] == client.cookies["refresh_token"].split(".", 1)[0]


@pytest.mark.case(id="AUTH-REGISTER-002")
async def test_registration_rejects_taken_email_in_any_case(
    client: AsyncClient, account: Account
) -> None:
    response = await register(client, account.email.upper(), "other-password")

    assert response.status_code == 409
    assert error_code(response) == "auth.email_already_registered"


@pytest.mark.case(id="AUTH-REGISTER-003")
@pytest.mark.parametrize(
    "body",
    [
        {"email": "not-an-email", "password": "password-1"},
        {"email": "user@example.com", "password": "short"},
    ],
    ids=["bad-email", "short-password"],
)
async def test_registration_validates_input(client: AsyncClient, body: dict[str, str]) -> None:
    response = await client.post("/api/auth/register", json=body)

    assert response.status_code == 422
    assert error_code(response) == "request.invalid"


@pytest.mark.case(id="AUTH-REGISTER-004")
async def test_concurrent_registration_creates_one_account(app: FastAPI) -> None:
    async with client_with_cookies(app, {}) as first, client_with_cookies(app, {}) as second:
        responses = await asyncio.gather(
            register(first, "concurrent@example.com", "password-1"),
            register(second, "concurrent@example.com", "password-1"),
        )
    assert sorted(response.status_code for response in responses) == [201, 409]
    rejected = next(response for response in responses if response.status_code == 409)
    assert error_code(rejected) == "auth.email_already_registered"

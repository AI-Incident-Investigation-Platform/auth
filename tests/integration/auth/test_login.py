import asyncio
import logging
import threading

import pytest
from argon2 import PasswordHasher
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.support.auth import Account, client_with_cookies, error_code, login


@pytest.mark.case(id="AUTH-LOGIN-001")
async def test_login_opens_new_session(
    client: AsyncClient, account: Account, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="src")
    client.cookies.clear()

    response = await login(client, account.email.upper(), account.password)

    assert response.status_code == 200
    assert response.json()["email"] == account.email
    assert {"access_token", "refresh_token"} <= set(client.cookies.keys())
    assert (await client.get("/api/auth/me")).status_code == 200
    events = [record for record in caplog.records if record.name == "src.api.auth.service"]
    assert len(events) == 1
    assert events[0].message == "Пользователь вошёл в систему"
    assert events[0].__dict__["user_id"] == response.json()["id"]
    assert events[0].__dict__["session_id"] == client.cookies["refresh_token"].split(".", 1)[0]


@pytest.mark.case(id="AUTH-LOGIN-002")
async def test_login_does_not_reveal_whether_email_exists(
    client: AsyncClient, account: Account, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="src")
    wrong_password = await login(client, account.email, "wrong-password")
    unknown_email = await login(client, "nobody@example.com", "wrong-password")

    assert wrong_password.status_code == unknown_email.status_code == 401
    assert error_code(wrong_password) == error_code(unknown_email) == "auth.invalid_credentials"
    assert not any(record.name == "src.api.auth.service" for record in caplog.records)
    errors = [record for record in caplog.records if record.name == "src.api.exc.handler"]
    assert len(errors) == 2
    assert all(record.message == "Неверный email или пароль" for record in errors)


@pytest.mark.case(id="AUTH-LOGIN-004")
async def test_short_wrong_password_is_rejected_as_invalid_credentials(
    client: AsyncClient, account: Account
) -> None:
    response = await login(client, account.email, "short")

    assert response.status_code == 401
    assert error_code(response) == "auth.invalid_credentials"


@pytest.mark.case(id="AUTH-LOGIN-005")
async def test_password_check_releases_db_and_rejects_password_changed_during_login(
    app: FastAPI,
    client: AsyncClient,
    account: Account,
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered = threading.Event()
    release = threading.Event()
    lock = threading.Lock()
    paused = False
    original_verify = PasswordHasher.verify

    def paused_verify(self: PasswordHasher, encoded: str | bytes, password: str | bytes) -> bool:
        nonlocal paused
        with lock:
            first = not paused
            paused = True
        if first:
            entered.set()
            if not release.wait(5):
                raise TimeoutError("Тест не освободил проверку пароля")
        return original_verify(self, encoded, password)

    monkeypatch.setattr(PasswordHasher, "verify", paused_verify)
    async with client_with_cookies(app, {}) as signing_in:
        pending = asyncio.create_task(login(signing_in, account.email, account.password))
        try:
            assert await asyncio.to_thread(entered.wait, 2)
            idle_transactions = await db.scalar(
                text(
                    "SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() "
                    "AND pid <> pg_backend_pid() AND state='idle in transaction'"
                )
            )
            assert idle_transactions == 0
            changed = await asyncio.wait_for(
                client.post(
                    "/api/auth/password",
                    json={"current_password": account.password, "new_password": "password-2"},
                ),
                timeout=3,
            )
            assert changed.status_code == 204
        finally:
            release.set()
            response = await pending

    assert response.status_code == 401
    assert error_code(response) == "auth.invalid_credentials"
    assert (await login(client, account.email, "password-2")).status_code == 200

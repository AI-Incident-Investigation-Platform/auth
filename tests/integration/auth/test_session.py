import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.db.models import Session
from tests.support.auth import Account, client_with_cookies, error_code, login


@pytest.mark.case(id="AUTH-SESSION-001")
async def test_refresh_rotates_tokens_and_keeps_session(
    client: AsyncClient, db: AsyncSession, account: Account
) -> None:
    old_refresh = client.cookies["refresh_token"]

    response = await client.post("/api/auth/refresh")

    assert response.status_code == 204
    assert set(response.cookies.keys()) == {"access_token", "refresh_token"}
    assert client.cookies["refresh_token"] != old_refresh
    assert (await client.get("/api/auth/me")).status_code == 200
    sessions = (await db.scalars(select(Session))).all()
    assert len(sessions) == 1
    assert sessions[0].revoked_at is None


@pytest.mark.case(id="AUTH-SESSION-002")
async def test_reused_refresh_token_revokes_session_at_once(
    app: FastAPI, client: AsyncClient, account: Account
) -> None:
    stolen_refresh = client.cookies["refresh_token"]
    assert (await client.post("/api/auth/refresh")).status_code == 204

    async with client_with_cookies(app, {"refresh_token": stolen_refresh}) as thief:
        reuse = await thief.post("/api/auth/refresh")

    assert reuse.status_code == 401
    assert error_code(reuse) == "auth.refresh_token_reused"
    assert (await client.get("/api/auth/me")).status_code == 401
    assert (await client.post("/api/auth/refresh")).status_code == 401


@pytest.mark.case(id="AUTH-SESSION-003")
async def test_refresh_rejects_missing_and_malformed_tokens(
    app: FastAPI, client: AsyncClient
) -> None:
    missing = await client.post("/api/auth/refresh")
    async with client_with_cookies(app, {"refresh_token": "not-a-token"}) as malformed_client:
        malformed = await malformed_client.post("/api/auth/refresh")

    assert missing.status_code == malformed.status_code == 401
    assert error_code(missing) == error_code(malformed) == "auth.invalid_refresh_token"


@pytest.mark.case(id="AUTH-SESSION-004")
async def test_me_requires_authentication(client: AsyncClient) -> None:
    response = await client.get("/api/auth/me")

    assert response.status_code == 401
    assert error_code(response) == "security.not_authenticated"


@pytest.mark.case(id="AUTH-SESSION-005")
async def test_bearer_header_is_accepted_like_cookie(
    app: FastAPI, client: AsyncClient, account: Account
) -> None:
    access = client.cookies["access_token"]

    async with client_with_cookies(app, {}) as service_call:
        response = await service_call.get(
            "/api/auth/me", headers={"Authorization": f"Bearer {access}"}
        )

    assert response.status_code == 200
    assert response.json()["email"] == account.email


@pytest.mark.case(id="AUTH-LOGOUT-001")
async def test_logout_revokes_access_token_immediately(
    app: FastAPI, client: AsyncClient, account: Account
) -> None:
    access = client.cookies["access_token"]
    refresh = client.cookies["refresh_token"]

    response = await client.post("/api/auth/logout")

    assert response.status_code == 204
    assert "access_token" not in client.cookies
    async with client_with_cookies(
        app, {"access_token": access, "refresh_token": refresh}
    ) as replay:
        assert (await replay.get("/api/auth/me")).status_code == 401
        assert (await replay.post("/api/auth/refresh")).status_code == 401


@pytest.mark.case(id="AUTH-LOGOUT-002")
async def test_logout_without_session_is_idempotent(client: AsyncClient) -> None:
    response = await client.post("/api/auth/logout")

    assert response.status_code == 204


@pytest.mark.case(id="AUTH-PASSWORD-002")
async def test_password_change_revokes_other_sessions_immediately(
    app: FastAPI, client: AsyncClient, account: Account
) -> None:
    async with client_with_cookies(app, {}) as other_device:
        assert (await login(other_device, account.email, account.password)).status_code == 200

        response = await client.post(
            "/api/auth/password",
            json={"current_password": account.password, "new_password": "password-2"},
        )

        assert response.status_code == 204
        assert (await other_device.get("/api/auth/me")).status_code == 401
    assert (await client.get("/api/auth/me")).status_code == 200
    assert (await login(client, account.email, "password-2")).status_code == 200


@pytest.mark.case(id="AUTH-PASSWORD-003")
async def test_password_change_requires_current_password(
    client: AsyncClient, account: Account
) -> None:
    response = await client.post(
        "/api/auth/password",
        json={"current_password": "wrong-password", "new_password": "password-2"},
    )

    assert response.status_code == 422
    assert error_code(response) == "auth.wrong_current_password"

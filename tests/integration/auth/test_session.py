from datetime import timedelta
from uuid import uuid7

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from redis.asyncio import Redis
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.db.models import Session, User
from src.main import container
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
async def test_previous_refresh_token_after_grace_revokes_session(
    app: FastAPI, client: AsyncClient, db: AsyncSession, account: Account
) -> None:
    stolen_refresh = client.cookies["refresh_token"]
    assert (await client.post("/api/auth/refresh")).status_code == 204
    await db.execute(update(Session).values(rotated_at=func.now() - timedelta(minutes=1)))
    await db.commit()

    async with client_with_cookies(app, {"refresh_token": stolen_refresh}) as thief:
        reuse = await thief.post("/api/auth/refresh")

    assert reuse.status_code == 401
    assert error_code(reuse) == "auth.refresh_token_reused"
    assert (await client.get("/api/auth/me")).status_code == 401
    assert (await client.post("/api/auth/refresh")).status_code == 401


@pytest.mark.case(id="AUTH-SESSION-008")
async def test_neighbour_tab_refresh_with_previous_token_keeps_session(
    app: FastAPI, client: AsyncClient, account: Account
) -> None:
    shared_refresh = client.cookies["refresh_token"]
    assert (await client.post("/api/auth/refresh")).status_code == 204

    async with client_with_cookies(app, {"refresh_token": shared_refresh}) as late_tab:
        late = await late_tab.post("/api/auth/refresh")
        late_me = await late_tab.get("/api/auth/me")

    assert late.status_code == 204
    assert set(late.cookies.keys()) == {"access_token"}
    assert late_me.status_code == 200
    assert (await client.get("/api/auth/me")).status_code == 200
    assert (await client.post("/api/auth/refresh")).status_code == 204


@pytest.mark.case(id="AUTH-SESSION-009")
async def test_refresh_token_older_than_previous_is_theft_even_within_grace(
    app: FastAPI, client: AsyncClient, account: Account
) -> None:
    oldest_refresh = client.cookies["refresh_token"]
    assert (await client.post("/api/auth/refresh")).status_code == 204
    assert (await client.post("/api/auth/refresh")).status_code == 204

    async with client_with_cookies(app, {"refresh_token": oldest_refresh}) as thief:
        reuse = await thief.post("/api/auth/refresh")

    assert error_code(reuse) == "auth.refresh_token_reused"
    assert (await client.get("/api/auth/me")).status_code == 401


@pytest.mark.case(id="AUTH-SESSION-010")
async def test_lost_session_pass_is_restored_by_refresh(
    client: AsyncClient, account: Account
) -> None:
    await (await container.get(Redis)).flushdb()

    assert (await client.get("/api/auth/me")).status_code == 401
    assert (await client.post("/api/auth/refresh")).status_code == 204
    assert (await client.get("/api/auth/me")).status_code == 200


@pytest.mark.case(id="AUTH-SESSION-011")
async def test_sessions_of_different_devices_are_independent(
    app: FastAPI, client: AsyncClient, account: Account
) -> None:
    async with client_with_cookies(app, {}) as other_device:
        assert (await login(other_device, account.email, account.password)).status_code == 200

        assert (await client.post("/api/auth/logout")).status_code == 204

        assert (await other_device.get("/api/auth/me")).status_code == 200
        assert (await other_device.post("/api/auth/refresh")).status_code == 204
    assert (await client.get("/api/auth/me")).status_code == 401


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


@pytest.mark.case(id="AUTH-COOKIE-001")
async def test_auth_cookies_are_http_only_strict_and_scoped(
    client: AsyncClient, account: Account
) -> None:
    response = await login(client, account.email, account.password)

    cookies = {
        header.split("=", 1)[0]: header.lower()
        for header in response.headers.get_list("set-cookie")
    }
    assert set(cookies) == {"access_token", "refresh_token"}
    for header in cookies.values():
        assert "httponly" in header
        assert "samesite=strict" in header
    assert "path=/api;" in cookies["access_token"]
    assert "path=/api/auth;" in cookies["refresh_token"]


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


@pytest.mark.case(id="AUTH-LOGOUT-003")
async def test_logout_with_session_id_but_wrong_secret_revokes_nothing(
    app: FastAPI, client: AsyncClient, account: Account
) -> None:
    session_id = client.cookies["refresh_token"].split(".", 1)[0]

    async with client_with_cookies(app, {"refresh_token": f"{session_id}.forged"}) as attacker:
        assert (await attacker.post("/api/auth/logout")).status_code == 204

    assert (await client.get("/api/auth/me")).status_code == 200
    assert (await client.post("/api/auth/refresh")).status_code == 204


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
        assert (await other_device.post("/api/auth/refresh")).status_code == 401
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


@pytest.mark.case(id="AUTH-SESSION-007")
async def test_deleted_account_is_reported_as_not_found(
    client: AsyncClient, db: AsyncSession, account: Account
) -> None:
    await db.execute(delete(User))
    await db.commit()

    response = await client.get("/api/auth/me")

    assert response.status_code == 401
    assert error_code(response) == "auth.account_not_found"
    assert (await client.post("/api/auth/refresh")).status_code == 401


@pytest.mark.case(id="AUTH-JWKS-002")
async def test_jwks_endpoint_publishes_valid_public_key(client: AsyncClient) -> None:
    response = await client.get("/api/auth/.well-known/jwks.json")

    assert response.status_code == 200
    (key,) = response.json()["keys"]
    assert set(key) == {"kty", "n", "e", "kid", "use", "alg"}
    assert (key["kty"], key["use"], key["alg"]) == ("RSA", "sig", "RS256")


@pytest.mark.case(id="AUTH-SESSION-012")
async def test_unknown_session_id_in_refresh_token_is_rejected(
    app: FastAPI, client: AsyncClient
) -> None:
    async with client_with_cookies(app, {"refresh_token": f"{uuid7()}.secret"}) as stranger:
        response = await stranger.post("/api/auth/refresh")

    assert response.status_code == 401
    assert error_code(response) == "auth.invalid_refresh_token"

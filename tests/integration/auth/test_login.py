import pytest
from httpx import AsyncClient

from tests.support.auth import Account, error_code, login


@pytest.mark.case(id="AUTH-LOGIN-001")
async def test_login_opens_new_session(client: AsyncClient, account: Account) -> None:
    client.cookies.clear()

    response = await login(client, account.email.upper(), account.password)

    assert response.status_code == 200
    assert response.json()["email"] == account.email
    assert {"access_token", "refresh_token"} <= set(client.cookies.keys())
    assert (await client.get("/api/auth/me")).status_code == 200


@pytest.mark.case(id="AUTH-LOGIN-002")
async def test_login_does_not_reveal_whether_email_exists(
    client: AsyncClient, account: Account
) -> None:
    wrong_password = await login(client, account.email, "wrong-password")
    unknown_email = await login(client, "nobody@example.com", "wrong-password")

    assert wrong_password.status_code == unknown_email.status_code == 401
    assert error_code(wrong_password) == error_code(unknown_email) == "auth.invalid_credentials"


@pytest.mark.case(id="AUTH-LOGIN-004")
async def test_short_wrong_password_is_rejected_as_invalid_credentials(
    client: AsyncClient, account: Account
) -> None:
    response = await login(client, account.email, "short")

    assert response.status_code == 401
    assert error_code(response) == "auth.invalid_credentials"

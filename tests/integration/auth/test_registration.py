import pytest
from httpx import AsyncClient

from tests.support.auth import Account, error_code, register


@pytest.mark.case(id="AUTH-REGISTER-001")
async def test_registration_signs_in_with_normalized_email(client: AsyncClient) -> None:
    response = await register(client, "New.User@Example.COM", "password-1")

    assert response.status_code == 201
    assert response.json()["email"] == "new.user@example.com"
    assert set(response.json()) == {"id", "email", "created_at"}
    assert {"access_token", "refresh_token"} <= set(client.cookies.keys())
    assert (await client.get("/api/auth/me")).status_code == 200


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

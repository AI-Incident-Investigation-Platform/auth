import pytest
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.db.models import User
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


@pytest.mark.case(id="AUTH-LOGIN-003")
async def test_login_reports_deactivated_account_only_after_correct_password(
    client: AsyncClient, db: AsyncSession, account: Account
) -> None:
    await db.execute(update(User).values(is_active=False))
    await db.commit()

    correct = await login(client, account.email, account.password)
    wrong = await login(client, account.email, "wrong-password")

    assert error_code(correct) == "auth.account_deactivated"
    assert error_code(wrong) == "auth.invalid_credentials"

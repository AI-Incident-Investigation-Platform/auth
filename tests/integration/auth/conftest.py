import pytest
from httpx import AsyncClient

from tests.support.auth import Account, register


@pytest.fixture
async def account(client: AsyncClient) -> Account:
    registered = Account(email="user@example.com", password="password-1")
    response = await register(client, registered.email, registered.password)
    assert response.status_code == 201, response.text
    return registered

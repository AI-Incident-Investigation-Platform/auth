import pytest
from httpx import AsyncClient

from tests.support.auth import Account, Mailbox, sign_in


@pytest.fixture
async def account(client: AsyncClient, mailbox: Mailbox) -> Account:
    signed_in = Account(email="user@example.com")
    response = await sign_in(client, mailbox, signed_in.email)
    assert response.status_code == 200, response.text
    return signed_in

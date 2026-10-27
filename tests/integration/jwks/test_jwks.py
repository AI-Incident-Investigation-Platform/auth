import pytest
from httpx import AsyncClient


@pytest.mark.case(id="JWKS-001")
async def test_jwks_endpoint_publishes_valid_public_key(client: AsyncClient) -> None:
    response = await client.get("/.well-known/jwks.json")

    assert response.status_code == 200
    (key,) = response.json()["keys"]
    assert set(key) == {"kty", "n", "e", "kid", "use", "alg"}
    assert (key["kty"], key["use"], key["alg"]) == ("RSA", "sig", "RS256")

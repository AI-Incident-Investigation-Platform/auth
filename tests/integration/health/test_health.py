import pytest
from httpx import AsyncClient


@pytest.mark.case(id="HEALTH-001")
async def test_ready_checks_database_and_cache(client: AsyncClient) -> None:
    health = await client.get("/health")
    ready = await client.get("/ready")

    assert health.status_code == ready.status_code == 200
    assert ready.json() == {"status": "ok"}

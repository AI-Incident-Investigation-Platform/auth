import pytest
from httpx import AsyncClient
from prometheus_client.parser import text_string_to_metric_families


async def scrape(client: AsyncClient) -> dict[tuple[str, frozenset[tuple[str, str]]], float]:
    response = await client.get("/metrics")
    assert response.status_code == 200
    return {
        (sample.name, frozenset(sample.labels.items())): sample.value
        for family in text_string_to_metric_families(response.text)
        for sample in family.samples
    }


@pytest.mark.case(id="METRICS-001")
async def test_metrics_count_requests_by_route_and_errors_by_code(client: AsyncClient) -> None:
    request = (
        "http_requests_total",
        frozenset({("method", "GET"), ("path", "/api/v1/auth/me"), ("status", "401")}),
    )
    error = (
        "app_errors_total",
        frozenset(
            {
                ("layer", "core"),
                ("code", "security.not_authenticated"),
                ("status", "401"),
                ("untranslated", "false"),
            }
        ),
    )
    before = await scrape(client)

    assert (await client.get("/api/v1/auth/me")).status_code == 401
    await client.get("/health")

    after = await scrape(client)
    assert after[request] == before.get(request, 0) + 1
    assert after[error] == before.get(error, 0) + 1
    assert not any(dict(labels).get("path") in {"/health", "/metrics"} for _, labels in after)

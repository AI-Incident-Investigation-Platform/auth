from unittest.mock import AsyncMock

import pytest

from src.config import cfg
from src.core.registry.client import ConsulClient
from src.core.registry.dto import ServiceInstance
from src.core.registry.service import RegistryService


@pytest.mark.case(id="REGISTRY-001")
async def test_instance_is_registered_with_gateway_route_and_readiness_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cfg.service, "port", 8002)
    consul = AsyncMock(spec=ConsulClient)

    await RegistryService(consul).register_self()

    instance: ServiceInstance = consul.register.await_args.args[0]
    assert instance.id == "auth-host.docker.internal-8002"
    assert instance.name == "auth"
    assert (instance.address, instance.port) == ("host.docker.internal", 8002)
    assert "traefik.enable=true" in instance.tags
    assert "traefik.http.routers.auth.rule=PathPrefix(`/api/auth`)" in instance.tags
    assert instance.check_url == "http://host.docker.internal:8002/ready"


@pytest.mark.case(id="REGISTRY-002")
async def test_gateway_rate_limit_comes_from_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cfg.gateway, "rate_limit_average", 25)
    monkeypatch.setattr(cfg.gateway, "rate_limit_burst", 50)
    monkeypatch.setattr(cfg.gateway, "rate_limit_period", "1m")
    consul = AsyncMock(spec=ConsulClient)

    await RegistryService(consul).register_self()

    tags = consul.register.await_args.args[0].tags
    assert "traefik.http.routers.auth.middlewares=auth-ratelimit" in tags
    assert "traefik.http.middlewares.auth-ratelimit.ratelimit.average=25" in tags
    assert "traefik.http.middlewares.auth-ratelimit.ratelimit.burst=50" in tags
    assert "traefik.http.middlewares.auth-ratelimit.ratelimit.period=1m" in tags

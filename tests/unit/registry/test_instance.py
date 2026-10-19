import re
import socket
from unittest.mock import AsyncMock

import pytest

from src.config import cfg
from src.core.registry.client import ConsulClient
from src.core.registry.service import RegistryService


@pytest.fixture
def free_port(monkeypatch: pytest.MonkeyPatch) -> int:
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    monkeypatch.setattr(cfg.service, "port", port)
    return port


@pytest.mark.case(id="REGISTRY-001")
async def test_instance_is_registered_with_gateway_route_and_readiness_check(
    free_port: int,
) -> None:
    consul = AsyncMock(spec=ConsulClient)

    await RegistryService(consul).register_self(ready=True)

    path, registration = consul.put.await_args.args
    assert path == "/v1/agent/service/register"
    assert re.fullmatch(
        rf"auth-host\.docker\.internal-{free_port}-[0-9a-f]{{6}}", registration["ID"]
    )
    assert registration["Name"] == "auth"
    assert (registration["Address"], registration["Port"]) == ("host.docker.internal", free_port)
    assert "traefik.enable=true" in registration["Tags"]
    assert "traefik.http.routers.auth.rule=PathPrefix(`/api/auth`)" in registration["Tags"]
    assert registration["Check"]["HTTP"] == f"http://host.docker.internal:{free_port}/ready"


@pytest.mark.case(id="REGISTRY-002")
async def test_gateway_rate_limit_comes_from_config(
    monkeypatch: pytest.MonkeyPatch, free_port: int
) -> None:
    monkeypatch.setattr(cfg.gateway, "rate_limit_average", 25)
    monkeypatch.setattr(cfg.gateway, "rate_limit_burst", 50)
    monkeypatch.setattr(cfg.gateway, "rate_limit_period", "1m")
    consul = AsyncMock(spec=ConsulClient)

    await RegistryService(consul).register_self(ready=True)

    tags = consul.put.await_args.args[1]["Tags"]
    assert "traefik.http.routers.auth.middlewares=auth-ratelimit" in tags
    assert "traefik.http.middlewares.auth-ratelimit.ratelimit.average=25" in tags
    assert "traefik.http.middlewares.auth-ratelimit.ratelimit.burst=50" in tags
    assert "traefik.http.middlewares.auth-ratelimit.ratelimit.period=1m" in tags


@pytest.mark.case(id="REGISTRY-003")
async def test_each_process_deregisters_only_itself(free_port: int) -> None:
    first_consul = AsyncMock(spec=ConsulClient)
    second_consul = AsyncMock(spec=ConsulClient)
    first = RegistryService(first_consul)
    second = RegistryService(second_consul)

    await first.register_self(ready=True)
    await second.deregister_self()

    first_id = first_consul.put.await_args.args[1]["ID"]
    assert second_consul.put.await_args.args[0] != f"/v1/agent/service/deregister/{first_id}"


@pytest.mark.case(id="REGISTRY-006")
@pytest.mark.parametrize(("ready", "status"), [(True, "passing"), (False, "critical")])
async def test_initial_check_status_follows_readiness(
    free_port: int, ready: bool, status: str
) -> None:
    consul = AsyncMock(spec=ConsulClient)

    await RegistryService(consul).register_self(ready=ready)

    assert consul.put.await_args.args[1]["Check"]["Status"] == status


@pytest.mark.case(id="REGISTRY-005")
async def test_instance_without_public_host_registers_with_its_network_address(
    monkeypatch: pytest.MonkeyPatch, free_port: int
) -> None:
    monkeypatch.setattr(cfg.service, "public_host", "")
    monkeypatch.setattr(socket, "gethostbyname", lambda _: "172.18.0.7")
    consul = AsyncMock(spec=ConsulClient)

    await RegistryService(consul).register_self(ready=True)

    registration = consul.put.await_args.args[1]
    assert (registration["Address"], registration["Port"]) == ("172.18.0.7", free_port)
    assert registration["Check"]["HTTP"] == f"http://172.18.0.7:{free_port}/ready"

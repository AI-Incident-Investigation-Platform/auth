import logging
import secrets
import socket

from src.config import cfg
from src.core.registry.client import ConsulClient
from src.core.registry.dto import ServiceInstance
from src.core.registry.exc import InstancePortBusyError

log = logging.getLogger(__name__)


class RegistryService:
    def __init__(self, consul: ConsulClient) -> None:
        self._consul = consul
        self._instance = self._describe_self()

    async def register_self(self) -> None:
        self._ensure_port_free(self._instance.port)
        await self._consul.register(self._instance)
        log.info("registry.registered", extra={"instance_id": self._instance.id})

    async def deregister_self(self) -> None:
        await self._consul.deregister(self._instance.id)
        log.info("registry.deregistered", extra={"instance_id": self._instance.id})

    @staticmethod
    def _ensure_port_free(port: int) -> None:
        for host in ("127.0.0.1", "0.0.0.0"):
            probe = socket.socket()
            try:
                probe.bind((host, port))
            except OSError as exc:
                raise InstancePortBusyError({"port": port}) from exc
            finally:
                probe.close()

    @staticmethod
    def _describe_self() -> ServiceInstance:
        name = cfg.service.name
        host = cfg.service.public_host
        port = cfg.service.port
        rate_limit = f"traefik.http.middlewares.{name}-ratelimit.ratelimit"
        return ServiceInstance(
            id=f"{name}-{host}-{port}-{secrets.token_hex(3)}",
            name=name,
            address=host,
            port=port,
            tags=(
                "traefik.enable=true",
                f"traefik.http.routers.{name}.rule=PathPrefix(`{cfg.service.route_prefix}`)",
                f"traefik.http.routers.{name}.middlewares={name}-ratelimit",
                f"{rate_limit}.average={cfg.gateway.rate_limit_average}",
                f"{rate_limit}.burst={cfg.gateway.rate_limit_burst}",
                f"{rate_limit}.period={cfg.gateway.rate_limit_period}",
            ),
            check_url=f"http://{host}:{port}/ready",
            check_interval_seconds=cfg.registry.check_interval_seconds,
            deregister_after_minutes=cfg.registry.deregister_after_minutes,
        )

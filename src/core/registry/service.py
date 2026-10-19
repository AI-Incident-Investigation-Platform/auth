import logging
import secrets
import socket

from src.config import cfg
from src.core.registry.client import ConsulClient
from src.core.registry.exc import InstancePortBusyError

log = logging.getLogger(__name__)


class RegistryService:
    def __init__(self, consul: ConsulClient) -> None:
        self._consul = consul
        self._port = cfg.service.port
        host = cfg.service.public_host or socket.gethostbyname(socket.gethostname())
        self._instance_id = f"{cfg.service.name}-{host}-{self._port}-{secrets.token_hex(3)}"
        self._registration = self._describe_self(self._instance_id, host, self._port)

    async def register_self(self) -> None:
        self._ensure_port_free(self._port)
        await self._consul.put("/v1/agent/service/register", self._registration)
        log.info("registry.registered", extra={"instance_id": self._instance_id})

    async def deregister_self(self) -> None:
        await self._consul.put(f"/v1/agent/service/deregister/{self._instance_id}")
        log.info("registry.deregistered", extra={"instance_id": self._instance_id})

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
    def _describe_self(instance_id: str, host: str, port: int) -> dict[str, object]:
        name = cfg.service.name
        rate_limit = f"traefik.http.middlewares.{name}-ratelimit.ratelimit"
        return {
            "ID": instance_id,
            "Name": name,
            "Address": host,
            "Port": port,
            "Tags": [
                "traefik.enable=true",
                f"traefik.http.routers.{name}.rule=PathPrefix(`{cfg.service.route_prefix}`)",
                f"traefik.http.routers.{name}.middlewares={name}-ratelimit",
                f"{rate_limit}.average={cfg.gateway.rate_limit_average}",
                f"{rate_limit}.burst={cfg.gateway.rate_limit_burst}",
                f"{rate_limit}.period={cfg.gateway.rate_limit_period}",
            ],
            "Check": {
                "HTTP": f"http://{host}:{port}/ready",
                "Interval": f"{cfg.registry.check_interval_seconds}s",
                "DeregisterCriticalServiceAfter": f"{cfg.registry.deregister_after_minutes}m",
            },
        }

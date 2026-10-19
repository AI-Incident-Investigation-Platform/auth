import logging
import secrets
import socket

from src.config import cfg
from src.core.registry.client import ConsulClient

log = logging.getLogger(__name__)


class RegistryService:
    def __init__(self, consul: ConsulClient) -> None:
        self._consul = consul
        self._port = cfg.service.port
        self._host = cfg.service.public_host or socket.gethostbyname(socket.gethostname())
        self._instance_id = f"{cfg.service.name}-{self._host}-{self._port}-{secrets.token_hex(3)}"

    async def register_self(self, ready: bool) -> None:
        await self._consul.put("/v1/agent/service/register", self._describe_self(ready))
        log.info("registry.registered", extra={"instance_id": self._instance_id, "ready": ready})

    async def deregister_self(self) -> None:
        await self._consul.put(f"/v1/agent/service/deregister/{self._instance_id}")
        log.info("registry.deregistered", extra={"instance_id": self._instance_id})

    def _describe_self(self, ready: bool) -> dict[str, object]:
        name = cfg.service.name
        rate_limit = f"traefik.http.middlewares.{name}-ratelimit.ratelimit"
        return {
            "ID": self._instance_id,
            "Name": name,
            "Address": self._host,
            "Port": self._port,
            "Tags": [
                "traefik.enable=true",
                f"traefik.http.routers.{name}.rule=PathPrefix(`{cfg.service.route_prefix}`)",
                f"traefik.http.routers.{name}.middlewares={name}-ratelimit",
                f"{rate_limit}.average={cfg.gateway.rate_limit_average}",
                f"{rate_limit}.burst={cfg.gateway.rate_limit_burst}",
                f"{rate_limit}.period={cfg.gateway.rate_limit_period}",
            ],
            "Check": {
                "HTTP": f"http://{self._host}:{self._port}/ready",
                "Status": "passing" if ready else "critical",
                "Interval": f"{cfg.registry.check_interval_seconds}s",
                "DeregisterCriticalServiceAfter": f"{cfg.registry.deregister_after_minutes}m",
            },
        }

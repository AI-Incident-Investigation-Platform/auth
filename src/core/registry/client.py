import httpx

from src.core.registry.dto import ServiceInstance
from src.core.registry.exc import RegistryBadResponseError, RegistryUnavailableError


class ConsulClient:
    def __init__(self, http: httpx.AsyncClient) -> None:
        self._http = http

    async def register(self, instance: ServiceInstance) -> None:
        await self._put(
            "/v1/agent/service/register",
            {
                "ID": instance.id,
                "Name": instance.name,
                "Address": instance.address,
                "Port": instance.port,
                "Tags": list(instance.tags),
                "Check": {
                    "HTTP": instance.check_url,
                    "Interval": f"{instance.check_interval_seconds}s",
                    "DeregisterCriticalServiceAfter": f"{instance.deregister_after_minutes}m",
                },
            },
        )

    async def deregister(self, instance_id: str) -> None:
        await self._put(f"/v1/agent/service/deregister/{instance_id}", None)

    async def _put(self, path: str, body: dict[str, object] | None) -> None:
        try:
            response = await self._http.put(path, json=body)
        except httpx.HTTPError as exc:
            raise RegistryUnavailableError({"path": path}) from exc
        if response.is_error:
            raise RegistryBadResponseError({"path": path, "status": response.status_code})

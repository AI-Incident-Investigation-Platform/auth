import httpx

from src.core.registry.exc import RegistryBadResponseError, RegistryUnavailableError


class ConsulClient:
    def __init__(self, http: httpx.AsyncClient) -> None:
        self._http = http

    async def put(self, path: str, body: dict[str, object] | None = None) -> None:
        try:
            response = await self._http.put(path, json=body)
        except httpx.HTTPError as exc:
            raise RegistryUnavailableError({"path": path}) from exc
        if response.is_error:
            raise RegistryBadResponseError({"path": path, "status": response.status_code})

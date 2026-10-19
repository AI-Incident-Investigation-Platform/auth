import asyncio
import logging
import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from dishka import make_async_container
from dishka.integrations.fastapi import FastapiProvider
from dishka.integrations.fastapi import setup_dishka as setup_fastapi_dishka
from fastapi import FastAPI

from src.api import router
from src.api.exc.handler import ApiErrorHandler
from src.api.health.router import router as health_router
from src.api.health.service import HealthService
from src.config import cfg
from src.config.exc import ConfigIncompleteError
from src.core.db.db import engine
from src.core.di import (
    AuthProvider,
    CacheProvider,
    DbProvider,
    HealthProvider,
    RegistryProvider,
    SecurityProvider,
)
from src.core.errors import AppError, ErrorReport
from src.core.logging import setup_logging
from src.core.middleware import RequestLoggingMiddleware
from src.core.registry.service import RegistryService
from src.core.security.service import SecurityService
from src.core.tracing import setup_tracing, shutdown_tracing

log = logging.getLogger(__name__)

container = make_async_container(
    FastapiProvider(),
    DbProvider(),
    CacheProvider(),
    SecurityProvider(),
    AuthProvider(),
    HealthProvider(),
    RegistryProvider(),
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    setup_logging(cfg.logging.level)
    if missing := cfg.missing_required():
        log.critical("app.config_incomplete", extra={"missing_settings": missing})
        raise ConfigIncompleteError({"missing_settings": missing})
    await container.get(SecurityService)
    try:
        yield
    finally:
        await container.close()
        shutdown_tracing()


class RegisteredServer(uvicorn.Server):
    registration_failed = False

    async def startup(self, sockets: list[socket.socket] | None = None) -> None:
        await super().startup(sockets)
        if self.should_exit or not cfg.registry.enabled:
            return
        try:
            registry = await container.get(RegistryService)
            await registry.register_self(ready=await self._is_ready())
        except AppError as exc:
            log.critical(
                "app.registration_failed", extra={"error": ErrorReport.from_exception(exc).to_log()}
            )
            self.registration_failed = True
            self.should_exit = True

    async def shutdown(self, sockets: list[socket.socket] | None = None) -> None:
        if cfg.registry.enabled and not self.registration_failed:
            try:
                await (await container.get(RegistryService)).deregister_self()
                await asyncio.sleep(cfg.registry.drain_seconds)
            except AppError as exc:
                log.warning(
                    "registry.deregister_failed",
                    extra={"error": ErrorReport.from_exception(exc).to_log()},
                )
        await super().shutdown(sockets)

    @staticmethod
    async def _is_ready() -> bool:
        async with container() as request_container:
            health = await request_container.get(HealthService)
            try:
                await health.check_ready()
            except AppError:
                return False
        return True


app = FastAPI(title="AIIP auth", lifespan=lifespan)

setup_fastapi_dishka(app=app, container=container)

app.add_middleware(RequestLoggingMiddleware)

app.include_router(router)
app.include_router(health_router)

ApiErrorHandler.register(app)

if cfg.tracing.enabled:
    setup_tracing(app, engine)


def main() -> None:
    server = RegisteredServer(
        uvicorn.Config(
            "src.main:app",
            host=cfg.service.bind_host,
            port=cfg.service.port,
            log_config=None,
            workers=1,
        )
    )
    server.run()
    if server.registration_failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

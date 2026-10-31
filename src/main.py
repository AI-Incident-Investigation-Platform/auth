import gc
import logging
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
from src.api.jwks.router import router as jwks_router
from src.api.metrics.router import router as metrics_router
from src.config import cfg
from src.config.exc import ConfigIncompleteError
from src.core.admission.middleware import AdmissionMiddleware
from src.core.db.db import engine
from src.core.di import (
    AuthProvider,
    CacheProvider,
    DbProvider,
    EmailProvider,
    HealthProvider,
    JwksProvider,
    SecurityProvider,
)
from src.core.logging import setup_logging
from src.core.metrics import MetricsMiddleware
from src.core.middleware import RequestLoggingMiddleware
from src.core.security.origin import OriginMiddleware
from src.core.security.service import SecurityService
from src.core.tracing import setup_tracing, shutdown_tracing

log = logging.getLogger(__name__)

container = make_async_container(
    FastapiProvider(),
    DbProvider(),
    CacheProvider(),
    EmailProvider(),
    SecurityProvider(),
    AuthProvider(),
    HealthProvider(),
    JwksProvider(),
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    setup_logging(cfg.logging.level)
    if missing := cfg.missing_required():
        log.critical(
            "Не заданы обязательные настройки сервиса",
            extra={"event": "service.config_incomplete", "missing_settings": missing},
        )
        raise ConfigIncompleteError({"missing_settings": missing})
    try:
        await container.get(SecurityService)
        # объекты старта (модули, модели, DI) — в постоянное поколение: полная сборка мусора
        # перестаёт их обходить, паузы event loop под нагрузкой — ~20 мс вместо ~150
        gc.collect()
        gc.freeze()
        log.info("Сервис готов принимать запросы", extra={"event": "service.started"})
        yield
    finally:
        log.info("Сервис останавливается", extra={"event": "service.stopping"})
        await container.close()
        shutdown_tracing()
        log.info("Сервис остановлен", extra={"event": "service.stopped"})


app = FastAPI(title="AIIP auth", lifespan=lifespan)

setup_fastapi_dishka(app=app, container=container)

app.add_middleware(OriginMiddleware, reject=ApiErrorHandler.handle_app_error)
app.add_middleware(AdmissionMiddleware, reject=ApiErrorHandler.handle_app_error)
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(MetricsMiddleware)

app.include_router(router)
app.include_router(health_router)
app.include_router(jwks_router)
app.include_router(metrics_router)

ApiErrorHandler.register(app)

if cfg.tracing.enabled:
    setup_tracing(app, engine)


def main() -> None:
    uvicorn.run(
        "src.main:app",
        host=cfg.service.bind_host,
        port=cfg.service.port,
        log_config=None,
        workers=1,
    )


if __name__ == "__main__":
    main()

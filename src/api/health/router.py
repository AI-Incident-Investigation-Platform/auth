from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter

from src.api.health.schemas import HealthResponse
from src.api.health.service import HealthService

router = APIRouter(tags=["health"], route_class=DishkaRoute)


@router.get("/health")
async def health() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get("/ready")
async def ready(service: FromDishka[HealthService]) -> HealthResponse:
    await service.check_ready()
    return HealthResponse(status="ok")

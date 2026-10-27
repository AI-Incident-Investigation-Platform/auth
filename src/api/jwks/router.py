from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter

from src.api.jwks.schemas import JwksResponse
from src.api.jwks.service import JwksService

router = APIRouter(tags=["jwks"], route_class=DishkaRoute)


@router.get("/.well-known/jwks.json")
async def jwks(service: FromDishka[JwksService]) -> JwksResponse:
    return JwksResponse.model_validate({"keys": service.jwks()}, from_attributes=True)

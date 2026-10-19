from typing import Annotated

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Cookie, Header, Response, status

from src.api.auth.cookies import clear_auth_cookies, set_auth_cookies
from src.api.auth.schemas import (
    JwksResponse,
    LoginRequest,
    PasswordChangeRequest,
    RegisterRequest,
    UserResponse,
)
from src.api.auth.service import AuthService
from src.core.security.dto import CurrentUser
from src.core.security.enums import AuthCookie

router = APIRouter(prefix="/auth", tags=["auth"], route_class=DishkaRoute)


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(
    body: RegisterRequest,
    response: Response,
    service: FromDishka[AuthService],
    user_agent: Annotated[str | None, Header()] = None,
) -> UserResponse:
    signed_in = await service.register(body.email, body.password, user_agent)
    set_auth_cookies(response, signed_in.tokens)
    return UserResponse.model_validate(signed_in.user, from_attributes=True)


@router.post("/login")
async def login(
    body: LoginRequest,
    response: Response,
    service: FromDishka[AuthService],
    user_agent: Annotated[str | None, Header()] = None,
) -> UserResponse:
    signed_in = await service.login(body.email, body.password, user_agent)
    set_auth_cookies(response, signed_in.tokens)
    return UserResponse.model_validate(signed_in.user, from_attributes=True)


@router.post("/refresh", status_code=status.HTTP_204_NO_CONTENT)
async def refresh(
    response: Response,
    service: FromDishka[AuthService],
    refresh_token: Annotated[str | None, Cookie(alias=AuthCookie.REFRESH_TOKEN)] = None,
) -> None:
    tokens = await service.refresh(refresh_token)
    set_auth_cookies(response, tokens)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response,
    service: FromDishka[AuthService],
    refresh_token: Annotated[str | None, Cookie(alias=AuthCookie.REFRESH_TOKEN)] = None,
) -> None:
    await service.logout(refresh_token)
    clear_auth_cookies(response)


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    body: PasswordChangeRequest,
    current_user: FromDishka[CurrentUser],
    service: FromDishka[AuthService],
) -> None:
    await service.change_password(current_user, body.current_password, body.new_password)


@router.get("/me")
async def get_me(
    current_user: FromDishka[CurrentUser],
    service: FromDishka[AuthService],
) -> UserResponse:
    user = await service.get_me(current_user)
    return UserResponse.model_validate(user, from_attributes=True)


@router.get("/.well-known/jwks.json")
async def jwks(service: FromDishka[AuthService]) -> JwksResponse:
    return JwksResponse.model_validate({"keys": service.jwks()}, from_attributes=True)

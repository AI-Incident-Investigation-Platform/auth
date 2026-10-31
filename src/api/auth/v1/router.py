from typing import Annotated

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Cookie, Header, Response, status

from src.api.auth.service import AuthService
from src.api.auth.v1.cookies import clear_auth_cookies, set_auth_cookies
from src.api.auth.v1.schemas import (
    AuthSessionResponse,
    EmailChangeChallengeResponse,
    EmailChangeRequest,
    EmailChangeVerifyRequest,
    LoginChallengeResponse,
    LoginRequest,
    OtpResendRequest,
    OtpResendResponse,
    OtpVerifyRequest,
    RegisterRequest,
    UserResponse,
)
from src.core.security.dto import CurrentUser
from src.core.security.enums import AuthCookie

router = APIRouter(prefix="/auth", tags=["auth"], route_class=DishkaRoute)


@router.post("/register", status_code=status.HTTP_202_ACCEPTED)
async def register(
    body: RegisterRequest, service: FromDishka[AuthService]
) -> LoginChallengeResponse:
    challenge = await service.start_registration(body.email)
    return LoginChallengeResponse.model_validate(challenge, from_attributes=True)


@router.post("/login", status_code=status.HTTP_202_ACCEPTED)
async def login(body: LoginRequest, service: FromDishka[AuthService]) -> LoginChallengeResponse:
    challenge = await service.start_login(body.email)
    return LoginChallengeResponse.model_validate(challenge, from_attributes=True)


@router.post("/otp/verify")
async def verify_otp(
    body: OtpVerifyRequest,
    response: Response,
    service: FromDishka[AuthService],
    user_agent: Annotated[str | None, Header()] = None,
) -> AuthSessionResponse:
    signed_in = await service.verify_code(body.challenge_id, body.code, user_agent)
    set_auth_cookies(response, signed_in.tokens)
    return AuthSessionResponse(
        user=UserResponse.model_validate(signed_in.user, from_attributes=True),
        account_created=signed_in.account_created,
    )


@router.post("/otp/resend", status_code=status.HTTP_202_ACCEPTED)
async def resend_otp(body: OtpResendRequest, service: FromDishka[AuthService]) -> OtpResendResponse:
    challenge = await service.resend_code(body.challenge_id)
    return OtpResendResponse.model_validate(challenge, from_attributes=True)


@router.post("/email/change", status_code=status.HTTP_202_ACCEPTED)
async def start_email_change(
    body: EmailChangeRequest,
    current_user: FromDishka[CurrentUser],
    service: FromDishka[AuthService],
) -> EmailChangeChallengeResponse:
    challenge = await service.start_email_change(current_user, body.new_email)
    return EmailChangeChallengeResponse.model_validate(challenge, from_attributes=True)


@router.post("/email/change/verify")
async def confirm_email_change(
    body: EmailChangeVerifyRequest,
    current_user: FromDishka[CurrentUser],
    service: FromDishka[AuthService],
) -> UserResponse:
    user = await service.confirm_email_change(
        current_user, body.challenge_id, body.code, body.new_code
    )
    return UserResponse.model_validate(user, from_attributes=True)


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


@router.get("/me")
async def get_me(
    current_user: FromDishka[CurrentUser],
    service: FromDishka[AuthService],
) -> UserResponse:
    user = await service.get_me(current_user)
    return UserResponse.model_validate(user, from_attributes=True)

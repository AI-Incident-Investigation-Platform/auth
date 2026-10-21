from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import AfterValidator, BaseModel, EmailStr, Field

from src.config import cfg

type NormalizedEmail = Annotated[EmailStr, AfterValidator(str.lower)]
type NewPassword = Annotated[
    str,
    Field(min_length=cfg.auth.password_min_length, max_length=cfg.auth.password_max_length),
]
type PasswordAttempt = Annotated[str, Field(min_length=1, max_length=cfg.auth.password_max_length)]


class RegisterRequest(BaseModel):
    email: NormalizedEmail
    password: NewPassword


class LoginRequest(BaseModel):
    email: NormalizedEmail
    password: PasswordAttempt


class PasswordChangeRequest(BaseModel):
    current_password: PasswordAttempt
    new_password: NewPassword


class UserResponse(BaseModel):
    id: UUID
    email: str
    created_at: datetime


class JwkResponse(BaseModel):
    kty: str
    n: str
    e: str
    kid: str
    use: str
    alg: str


class JwksResponse(BaseModel):
    keys: list[JwkResponse]

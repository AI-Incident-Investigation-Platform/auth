from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import AfterValidator, BaseModel, EmailStr, Field

from src.config import cfg
from src.core.db.enums import UserRole

type NormalizedEmail = Annotated[EmailStr, AfterValidator(str.lower)]
type Password = Annotated[
    str,
    Field(min_length=cfg.auth.password_min_length, max_length=cfg.auth.password_max_length),
]


class RegisterRequest(BaseModel):
    email: NormalizedEmail
    password: Password


class LoginRequest(BaseModel):
    email: NormalizedEmail
    password: Password


class PasswordChangeRequest(BaseModel):
    current_password: Password
    new_password: Password


class UserResponse(BaseModel):
    id: UUID
    email: str
    role: UserRole
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

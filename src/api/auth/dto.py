from dataclasses import dataclass
from typing import Literal

from src.core.db.dto.user import UserDTO
from src.core.security.enums import AuthCookie


@dataclass(frozen=True)
class ResponseCookie:
    key: AuthCookie
    value: str
    max_age: int
    path: str
    secure: bool
    httponly: bool
    samesite: Literal["lax", "strict", "none"]
    expires: int | None = None


@dataclass(frozen=True)
class SignedIn:
    user: UserDTO
    cookies: tuple[ResponseCookie, ...]

from dataclasses import dataclass

from src.core.db.dto.user import UserDTO


@dataclass(frozen=True)
class IssuedTokens:
    access_token: str
    refresh_token: str


@dataclass(frozen=True)
class SignedIn:
    user: UserDTO
    tokens: IssuedTokens

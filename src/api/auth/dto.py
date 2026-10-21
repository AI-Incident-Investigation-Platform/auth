from dataclasses import dataclass

from src.core.db.dto.user import UserDTO


@dataclass(frozen=True)
class IssuedTokens:
    """Выданные токены; refresh_token пуст, когда сессия не ротировалась."""

    access_token: str
    refresh_token: str | None


@dataclass(frozen=True)
class SignedIn:
    user: UserDTO
    tokens: IssuedTokens

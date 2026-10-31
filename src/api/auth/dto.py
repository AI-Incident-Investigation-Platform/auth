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
    account_created: bool


@dataclass(frozen=True)
class LoginChallenge:
    challenge_id: str
    masked_email: str
    expires_in: int
    resend_after: int


@dataclass(frozen=True)
class EmailChangeChallenge:
    challenge_id: str
    masked_email: str
    masked_new_email: str
    expires_in: int
    resend_after: int

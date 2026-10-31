from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from src.core.security.enums import OtpPurpose


@dataclass(frozen=True)
class AccessTokenClaims:
    user_id: UUID
    session_id: UUID


@dataclass(frozen=True)
class RefreshToken:
    session_id: UUID
    secret: str

    def __str__(self) -> str:
        return f"{self.session_id}.{self.secret}"


@dataclass(frozen=True)
class CurrentUser:
    user_id: UUID
    session_id: UUID


@dataclass(frozen=True)
class Jwk:
    kty: str
    n: str
    e: str
    kid: str
    use: str
    alg: str


@dataclass(frozen=True)
class OtpChallenge:
    """Ожидание кода из письма.

    `email` — адрес, на который ушёл код. При смене почты это текущий адрес
    пользователя `user_id`, а второй код (`new_code_digest`) ушёл на `new_email`.
    """

    challenge_id: str
    purpose: OtpPurpose
    email: str
    code_digest: str
    code_expires_at: datetime
    resend_available_at: datetime
    resends: int
    user_id: UUID | None = None
    new_email: str | None = None
    new_code_digest: str | None = None


@dataclass(frozen=True)
class SendCount:
    count: int
    resets_in_seconds: int

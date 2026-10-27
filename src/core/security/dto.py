from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


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
    challenge_id: str
    email: str
    code_digest: str
    code_expires_at: datetime
    resend_available_at: datetime
    resends: int


@dataclass(frozen=True)
class SendCount:
    count: int
    resets_in_seconds: int

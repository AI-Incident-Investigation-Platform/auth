from dataclasses import dataclass
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

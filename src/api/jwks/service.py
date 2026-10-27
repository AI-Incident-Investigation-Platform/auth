from src.core.security.dto import Jwk
from src.core.security.service import SecurityService


class JwksService:
    def __init__(self, security: SecurityService) -> None:
        self._security = security

    def jwks(self) -> tuple[Jwk, ...]:
        return self._security.jwks()

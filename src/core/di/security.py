from dishka import Provider, Scope, provide
from fastapi import Request

from src.core.security.dto import CurrentUser
from src.core.security.enums import AuthCookie
from src.core.security.revocation import SessionRevocationList
from src.core.security.service import SecurityService, SessionAuthenticator, SessionIssuer


class SecurityProvider(Provider):
    security_service = provide(SecurityService, scope=Scope.APP)
    revocation_list = provide(SessionRevocationList, scope=Scope.APP)
    session_authenticator = provide(SessionAuthenticator, scope=Scope.REQUEST)
    session_issuer = provide(SessionIssuer, scope=Scope.REQUEST)

    @provide(scope=Scope.REQUEST)
    async def get_current_user(
        self, request: Request, authenticator: SessionAuthenticator
    ) -> CurrentUser:
        scheme, _, bearer = request.headers.get("authorization", "").partition(" ")
        token = bearer if scheme.lower() == "bearer" else None
        return await authenticator.authenticate(
            token or request.cookies.get(AuthCookie.ACCESS_TOKEN)
        )

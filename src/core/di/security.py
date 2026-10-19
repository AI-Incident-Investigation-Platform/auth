from dishka import Provider, Scope, provide
from fastapi import Request

from src.core.security.dto import CurrentUser
from src.core.security.enums import AuthCookie
from src.core.security.revocation import SessionRevocationList
from src.core.security.service import SecurityService, SessionAuthenticator


class SecurityProvider(Provider):
    security_service = provide(SecurityService, scope=Scope.APP)
    revocation_list = provide(SessionRevocationList, scope=Scope.APP)
    session_authenticator = provide(SessionAuthenticator, scope=Scope.REQUEST)

    @provide(scope=Scope.REQUEST)
    async def get_current_user(
        self, request: Request, authenticator: SessionAuthenticator
    ) -> CurrentUser:
        return await authenticator.authenticate(
            request.headers.get("authorization"), request.cookies.get(AuthCookie.ACCESS_TOKEN)
        )

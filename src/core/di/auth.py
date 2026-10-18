from dishka import Provider, Scope, provide

from src.api.auth.service import AuthService


class AuthProvider(Provider):
    auth_service = provide(AuthService, scope=Scope.REQUEST)

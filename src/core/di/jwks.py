from dishka import Provider, Scope, provide

from src.api.jwks.service import JwksService


class JwksProvider(Provider):
    jwks_service = provide(JwksService, scope=Scope.APP)
